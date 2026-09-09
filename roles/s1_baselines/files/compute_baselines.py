#!/usr/bin/env python3
"""
compute_baselines.py — Compute per-device alert thresholds from historical data
and upsert into dbo.alert_thresholds.

Usage:
    python3 compute_baselines.py dry-run [--lookback 60]   # print, write nothing
    python3 compute_baselines.py apply   [--lookback 60]   # compute and upsert
    python3 compute_baselines.py migrate                   # create the table if absent
"""

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime

import pymssql

# ── Config ─────────────────────────────────────────────────────────────────────
ENV_KEYS = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASS", "DB_NAME"]


def load_config():
    """Read DB settings from the environment. Compose is the only config source."""
    missing = [k for k in ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")
    return {k: os.environ[k] for k in ENV_KEYS}


def get_conn(cfg):
    return pymssql.connect(
        server=cfg["DB_HOST"], port=int(cfg["DB_PORT"]),
        user=cfg["DB_USER"], password=cfg["DB_PASS"],
        database=cfg["DB_NAME"], timeout=30
    )


# ── Stats helpers ──────────────────────────────────────────────────────────────
def percentile(data, p):
    """Compute p-th percentile (0-100) of a sorted list."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def compute_stats(values):
    """Return (mean, stddev, p05, p10, p90, p95, n) for a list of floats."""
    n = len(values)
    if n == 0:
        return None
    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if n > 1 else 0.0
    p05 = percentile(values, 5)
    p10 = percentile(values, 10)
    p90 = percentile(values, 90)
    p95 = percentile(values, 95)
    return mean, stddev, p05, p10, p90, p95, n


# ── Threshold derivation ───────────────────────────────────────────────────────
# The good_read warn line sits a fixed fraction below each device's own baseline
# mean, so every device is judged against its own normal rather than a fleet-wide
# floor.
WARN_BELOW_MEAN = 0.15


def derive_thresholds(metric, mean, stddev, p05, p10, p90, p95):
    if metric == "good_read_pct":
        # 15% below the mean, relative — not 15 percentage points. No 50.0 floor:
        # a genuinely weak device gets a correspondingly low warn line instead of
        # being pinned up at 50 and alerting permanently.
        warn = mean * (1.0 - WARN_BELOW_MEAN)
        bad = max(p05, mean - 3 * stddev)
        # bad is the hard limit and must stay strictly under warn. With warn now
        # well below the mean, the statistical bad value usually lands above it.
        if bad >= warn:
            bad = max(0.0, warn - 1.0)
        return round(warn, 4), round(bad, 4)
    elif metric == "no_dim_pct":
        warn = (p90 * 1.5) if p90 > 0 else 3.0
        bad = (p95 * 2.0) if p95 > 0 else 5.0
        return round(warn, 4), round(bad, 4)
    return None, None


# ── Change reporting ───────────────────────────────────────────────────────────
def format_change_lines(existing, results):
    """One line per row that is new or changed; unchanged rows are only counted."""
    lines, unchanged = [], 0
    for r in results:
        key = (r["customer"], r["machine_name"], r["location"], r["metric"])
        label = " / ".join(key)
        old = existing.get(key)
        if old is None:
            lines.append(f"{label}: NEW warn {r['warn_value']:.4f}, bad {r['bad_value']:.4f}")
            continue
        old_warn, old_bad = old
        if old_warn == r["warn_value"] and old_bad == r["bad_value"]:
            unchanged += 1
            continue
        lines.append(f"{label}: warn {old_warn:.4f} -> {r['warn_value']:.4f}, "
                     f"bad {old_bad:.4f} -> {r['bad_value']:.4f}")
    return lines, unchanged


# ── Migrations ─────────────────────────────────────────────────────────────────
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def split_batches(sql_text):
    """Split T-SQL on lines that are exactly GO (sqlcmd batch separator)."""
    batches, current = [], []
    for line in sql_text.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def run_migrations(cfg, migrations_dir=MIGRATIONS_DIR, connect=None):
    """Apply every migrations/*.sql in name order. Files must be idempotent."""
    connect = connect or get_conn
    files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    with connect(cfg) as conn:
        for name in files:
            with open(os.path.join(migrations_dir, name), encoding="utf-8") as fh:
                batches = split_batches(fh.read())
            with conn.cursor() as cur:
                for batch in batches:
                    cur.execute(batch)
            conn.commit()
            print(f"migrated {name} ({len(batches)} batch(es))")


# ── Compute ────────────────────────────────────────────────────────────────────
def compute(cfg, lookback, dry_run):
    print(f"{'[DRY RUN] ' if dry_run else ''}Computing baselines from last {lookback} days of device_statistics...")

    with get_conn(cfg) as conn:
        with conn.cursor(as_dict=True) as cur:
            cur.execute("""
                SELECT d.customer, d.machine_name, d.location,
                       ds.total_items, ds.good_read, ds.no_dimension
                FROM devices d
                JOIN device_statistics ds ON ds.device_id = d.id
                WHERE ds.ts_datetime >= DATEADD(day, -%s, GETDATE())
                  AND ds.total_items >= 50
                ORDER BY d.customer, d.machine_name, d.location
            """, (lookback,))
            rows = cur.fetchall()

        print(f"  Fetched {len(rows)} qualifying rows.")

        # Group rows by device
        device_data = defaultdict(lambda: {"good_read_pcts": [], "no_dim_pcts": []})
        for r in rows:
            key = (r["customer"], r["machine_name"], r["location"])
            total = float(r["total_items"] or 0)
            if total <= 0:
                continue
            gr_pct = float(r["good_read"] or 0) / total * 100
            nd_pct = float(r["no_dimension"] or 0) / total * 100
            device_data[key]["good_read_pcts"].append(gr_pct)
            device_data[key]["no_dim_pcts"].append(nd_pct)

        # Check which devices have is_override set — skip those
        with conn.cursor(as_dict=True) as cur:
            cur.execute("""
                SELECT customer, machine_name, location, metric
                FROM alert_thresholds
                WHERE is_override = 1
            """)
            override_rows = cur.fetchall()
        override_set = {
            (r["customer"], r["machine_name"], r["location"], r["metric"])
            for r in override_rows
        }

        results = []
        skipped_override = 0

        for (customer, machine_name, location), data in sorted(device_data.items()):
            for metric, field in [("good_read_pct", "good_read_pcts"), ("no_dim_pct", "no_dim_pcts")]:
                if (customer, machine_name, location, metric) in override_set:
                    skipped_override += 1
                    print(f"  SKIP (override) {customer} / {machine_name} / {location} / {metric}")
                    continue

                values = data[field]
                stats = compute_stats(values)
                if stats is None:
                    continue

                mean, stddev, p05, p10, p90, p95, n = stats
                warn, bad = derive_thresholds(metric, mean, stddev, p05, p10, p90, p95)

                direction = "low" if metric == "good_read_pct" else "high"
                results.append({
                    "customer": customer,
                    "machine_name": machine_name,
                    "location": location,
                    "metric": metric,
                    "direction": direction,
                    "warn_value": warn,
                    "bad_value": bad,
                    "baseline_mean": round(mean, 4),
                    "baseline_stddev": round(stddev, 4),
                    "baseline_p05": round(p05, 4),
                    "baseline_p10": round(p10, 4),
                    "baseline_p90": round(p90, 4),
                    "baseline_p95": round(p95, 4),
                    "baseline_samples": n,
                })

        # Print summary
        print(f"\n{'-' * 90}")
        print(f"{'CUSTOMER':<12} {'MACHINE':<8} {'LOC':<6} {'METRIC':<16} {'WARN':>8} {'BAD':>8} {'MEAN':>8} {'STDDEV':>8} {'N':>6}")
        print(f"{'-' * 90}")
        for r in results:
            print(f"{r['customer']:<12} {r['machine_name']:<8} {r['location']:<6} {r['metric']:<16} "
                  f"{r['warn_value']:>8.4f} {r['bad_value']:>8.4f} {r['baseline_mean']:>8.4f} "
                  f"{r['baseline_stddev']:>8.4f} {r['baseline_samples']:>6}")
        print(f"{'-' * 90}")
        print(f"\nTotal: {len(results)} threshold rows to upsert, {skipped_override} skipped (is_override=1)")

        # Existing values, for the change report and the insert/update decision
        with conn.cursor(as_dict=True) as cur:
            cur.execute("SELECT customer, machine_name, location, metric, warn_value, bad_value FROM alert_thresholds")
            existing = {
                (e["customer"], e["machine_name"], e["location"], e["metric"]):
                (float(e["warn_value"]) if e["warn_value"] is not None else None,
                 float(e["bad_value"]) if e["bad_value"] is not None else None)
                for e in cur.fetchall()
            }
        change_lines, unchanged = format_change_lines(existing, results)
        print("\nChanges:")
        for line in change_lines:
            print(f"  {line}")
        print(f"  ({unchanged} unchanged)")

        if dry_run:
            print("\n[DRY RUN] No changes written to database.")
            return

        # Upsert
        now = datetime.now()
        inserted = updated = 0
        with conn.cursor(as_dict=True) as cur:
            for r in results:
                if (r["customer"], r["machine_name"], r["location"], r["metric"]) in existing:
                    cur.execute("""
                        UPDATE alert_thresholds SET
                            direction=%s, warn_value=%s, bad_value=%s,
                            baseline_mean=%s, baseline_stddev=%s,
                            baseline_p05=%s, baseline_p10=%s, baseline_p90=%s, baseline_p95=%s,
                            baseline_samples=%s, lookback_days=%s,
                            last_computed=%s, updated_at=%s
                        WHERE customer=%s AND machine_name=%s AND location=%s AND metric=%s
                    """, (
                        r["direction"], r["warn_value"], r["bad_value"],
                        r["baseline_mean"], r["baseline_stddev"],
                        r["baseline_p05"], r["baseline_p10"], r["baseline_p90"], r["baseline_p95"],
                        r["baseline_samples"], lookback,
                        now, now,
                        r["customer"], r["machine_name"], r["location"], r["metric"]
                    ))
                    updated += 1
                else:
                    cur.execute("""
                        INSERT INTO alert_thresholds
                            (customer, machine_name, location, metric, direction,
                             warn_value, bad_value,
                             baseline_mean, baseline_stddev,
                             baseline_p05, baseline_p10, baseline_p90, baseline_p95,
                             baseline_samples, lookback_days, last_computed, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        r["customer"], r["machine_name"], r["location"], r["metric"], r["direction"],
                        r["warn_value"], r["bad_value"],
                        r["baseline_mean"], r["baseline_stddev"],
                        r["baseline_p05"], r["baseline_p10"], r["baseline_p90"], r["baseline_p95"],
                        r["baseline_samples"], lookback, now, now
                    ))
                    inserted += 1
        conn.commit()
        print(f"\nDone: {inserted} inserted, {updated} updated.")


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="compute_baselines.py",
        description="Compute per-device alert thresholds into dbo.alert_thresholds",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    for name, help_text in (
        ("dry-run", "Print thresholds; write nothing"),
        ("apply", "Compute and upsert thresholds"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--lookback", type=int, default=60,
                       help="Days of history to use (default: 60)")
    sub.add_parser("migrate", help="Create dbo.alert_thresholds if it does not exist")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cfg = load_config()
    if args.command == "migrate":
        run_migrations(cfg)
        return
    compute(cfg, lookback=args.lookback, dry_run=(args.command == "dry-run"))


if __name__ == "__main__":
    main()
