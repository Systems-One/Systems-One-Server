# s1_reporter overhaul — Design

**Date:** 2026-09-09
**Target:** `roles/s1_reporter/` (rewrite of the application, same role name, same container names
for the chart server)
**Companion:** `2026-09-09-s1-baselines-role-design.md` (shares the one-shot + host-cron + migrate
mechanics defined here)

## Context

`s1_reporter` posts offline/recovery alerts, upload-failure alerts, daily and monthly per-customer
reports to Microsoft Teams. Today it is a single 786 MB container running a `sleep 60` shell loop
that shells out to a 763-line `report.py` and a duplicate-config `upload_monitor.py`. A review on
2026-09-09 (see the conversation that produced this spec) confirmed on the live host:

- Container clock is UTC, nothing sets `TZ`, so "06:00 SAST" reports go out at 08:00 SAST.
- A device dead since 2026-07-08 (`STATIC1@DUR`, PEP AFRICA) is re-listed every 20 minutes and
  produces an empty-chart PEP AFRICA card with a "no data for 1511h" alert every morning.
- Cards are posted for every customer in `devices`, including ones with no data in the window.
- The healthcheck always passes. Restarts skip or duplicate daily reports.
- Alert state is saved before the Teams POST, whose result is ignored, so a failed POST is never
  retried.
- "Today" anomaly checks at 06:00 see under an hour of data; the no-dimension check re-raises
  spikes from six days ago daily.
- Chart y-axis fixed at 85–101 with hard-coded 97%/90% lines, which contradicts the per-device
  `alert_thresholds` and hides warn lines below 85.
- SQL built with f-strings; runs as `sa`; `CUSTOMER_CAPS` hard-coded for 4 of 7 customers.

## Goals

1. Scheduling by host cron, each job a one-shot container run. No in-container loop.
2. Customer capabilities, per-customer alert limits and per-device reporting flags live in the
   database, readable by the dashboards later.
3. A stale-device concept so dead devices stop polluting alerts and reports.
4. Alerts are recorded as sent only after Teams accepts them.
5. Reports describe complete local days, in SAST.
6. Charts and anomaly rules use the same thresholds.
7. Package structure with unit tests over the rules, not just the card builders.
8. Least-privilege `admin` login, pinned dependencies, non-root image with `TZ`.

## Non-goals

- Changing what the cards look like beyond what the fixes require.
- Moving alert state (offline/upload JSON files) into the database.
- Replacing matplotlib.
- Any change to `mqtt_ingestor`, `marketing_display` or `scan_fleet_dashboard`. They keep working
  because every schema change here is additive.
- Threshold computation (that is `s1_baselines`).

## Architecture

### Runtime model

```
host cron (SAST)                      /opt/s1-reporter/
  */20 * * * *     run-reporter.sh sync-status
  */20 * * * 1-5   run-reporter.sh check-alerts
  0 6   * * 1-5    run-reporter.sh daily
  30 6  1 * *      run-reporter.sh monthly
  0 7   * * 1      run-reporter.sh stale-digest
        |
        v
  docker compose run --rm reporter <job>      (one-shot, exits)
        |
        +-- reads/writes S1_Remote_Monitoring as `admin`
        +-- writes PNGs to volume s1_reporter_charts  --> s1_reporter_charts (nginx, long-running)
        +-- reads/writes /data/*.json state on volume s1_reporter_data
        +-- POSTs Adaptive Cards to Teams
```

The compose file keeps two services. `s1-charts` (nginx) is unchanged and stays up via
`docker compose up -d s1-charts`. `reporter` has no `restart`, no `container_name`, no
healthcheck, and is only ever started by `compose run`. Ansible's deploy sequence is: build,
`up -d s1-charts`, `run --rm reporter migrate`, install cron entries.

The monthly report runs on the 1st regardless of weekday. The old rule silently skipped months
whose 1st fell on a weekend.

### Wrapper `run-reporter.sh`

Identical shape to `run-baselines.sh` in the companion spec: `#!/bin/bash`, `set -o pipefail`,
`cd` to the install dir, timestamped line to `/opt/s1-reporter/reporter.log`, then
`docker compose run --rm reporter "$@" 2>&1 | tee -a` the same log. Exit code is the
container's.

### Package layout

```
roles/s1_reporter/files/
  Dockerfile
  requirements.txt              # pinned: pymssql, matplotlib, numpy
  app/
    s1_reporter/
      __init__.py
      __main__.py               # python -m s1_reporter <job>
      cli.py                    # argparse: sync-status | check-alerts | daily | monthly | stale-digest | migrate
      config.py                 # Settings dataclass from env; fails fast on missing vars
      db.py                     # connect(), query(sql, params), execute(), run_migrations()
      customers.py              # CustomerConfig + DeviceFlags loaded from DB
      liveness.py               # last-seen per device, offline classification, stale classification
      status_sync.py            # single MERGE into dbo.device_status
      anomalies.py              # pure rules over rows + thresholds + customer config
      thresholds.py             # load alert_thresholds, lookup with fallback chain
      upload.py                 # not_sent consecutive-packet detection
      state.py                  # JSON state files with commit-after-send semantics
      charts.py                 # matplotlib, imported only here
      chart_store.py            # unchanged
      cards.py                  # unchanged plus build_stale_digest_card
      teams.py                  # post_to_teams unchanged, renamed module
      reports.py                # daily / monthly / digest orchestration
    migrations/
      001_customer_config.sql
      002_device_flags.sql
  tests/                        # unittest, plain imports (no SourceFileLoader)
```

Only `db.py` imports `pymssql` and only `charts.py` imports matplotlib/numpy. Every rule module is
importable in CI without stubs.

### Database changes (additive, idempotent, applied by the `migrate` job)

`001_customer_config.sql`

```sql
CREATE TABLE dbo.customer_config (
    customer            NVARCHAR(100) NOT NULL PRIMARY KEY,
    has_dimension       BIT NOT NULL DEFAULT 1,
    has_weight          BIT NOT NULL DEFAULT 0,
    has_hand_scan       BIT NOT NULL DEFAULT 0,
    hand_scan_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 15.0,
    no_weight_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 5.0,
    storage_warn_pct    DECIMAL(5,2) NOT NULL DEFAULT 80.0,
    storage_bad_pct     DECIMAL(5,2) NOT NULL DEFAULT 90.0,
    good_read_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 95.0,   -- fallback when no alert_thresholds row
    good_read_bad_pct   DECIMAL(5,2) NOT NULL DEFAULT 90.0,
    no_dim_warn_pct     DECIMAL(5,2) NOT NULL DEFAULT 5.0,
    no_dim_bad_pct      DECIMAL(5,2) NOT NULL DEFAULT 10.0,
    reports_enabled     BIT NOT NULL DEFAULT 1,
    updated_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
```

Seed rows (INSERT only where the customer is absent) reproduce today's `CUSTOMER_CAPS`:
PEPKOR (dimension), MADIBANA (dimension, weight, hand scan), PEP and SNOWSOFT (none). Every
other customer present in `dbo.devices` at migration time is inserted with defaults, so the
table is complete after the first run. New customers that appear later get defaults in code and a
log line; the next `migrate` inserts them.

`002_device_flags.sql` adds to `dbo.devices`:

```sql
reporting_enabled  BIT NOT NULL DEFAULT 1,   -- 0 = standby/decommissioned: ignored everywhere
muted_until        DATETIME2 NULL            -- alerts suppressed until this UTC time
```

and sets `reporting_enabled = 0` for `DIM2 @ JBH` (the only standby line in code today, under
PEPKOR). `mqtt_ingestor` inserts devices with an explicit column list, so the new columns do not
affect it.

`alert_thresholds` is created by the `s1_baselines` migration if absent (see companion spec).

### Time

All stored timestamps are UTC. Reports are about local (SAST, UTC+2, no DST) days. A single
`REPORT_TZ_OFFSET_HOURS` setting (default 2, Ansible `s1_reporter_tz_offset_hours`) is applied in
SQL as `CAST(DATEADD(hour, @off, ds.ts_datetime) AS DATE)` for day grouping, matching what
`scan_fleet_dashboard` already does. The "last complete local day" is yesterday in that offset.

### Liveness and staleness

`liveness.py` classifies every device with `reporting_enabled = 1`:

| State | Rule | Effect |
|---|---|---|
| online | last stats packet within `OFFLINE_THRESHOLD_MINUTES` (default 30) | normal |
| offline | older than threshold, newer than `STALE_DAYS` (default 14) | alerts, listed in cards |
| stale | older than `STALE_DAYS` | excluded from alerts and daily/monthly cards; listed in the weekly stale digest |
| never | no stats packet at all | treated as offline with `last_seen = created_at` so it alerts once |

`muted_until` in the future suppresses alerts for that device but not its status in the DB.
`status_sync.py` writes every device with `reporting_enabled = 1` (online/offline, stale counts
as offline) in one `MERGE`, preserving `offline_since` as today.

### Alerts (`check-alerts`)

Offline and upload checks run in one job. The state machine in `state.py` exposes
`diff(current)` returning `(new, recovered, unchanged, commit)` where `commit()` writes the file.
`reports.py` posts the card(s), and calls `commit()` only when every POST returned True. On a
failed POST nothing is written, so the next run re-alerts. Devices that are stale or muted are
removed from `current` before the diff, so a device crossing into stale produces no recovery card.

### Reports (`daily`, `monthly`)

For each customer with `reports_enabled = 1` and at least one non-stale device that has stats in
the window: build the card as today with these changes.

- Window is complete local days: daily = last 7 complete days ending yesterday, with a "Yesterday"
  table replacing "Today"; monthly = the previous calendar month.
- Anomaly rules run over yesterday only (daily) or the whole month (monthly), never re-raising
  earlier days in the daily card. Rules and their limits come from `alert_thresholds` (device row,
  then customer-wide row) and `customer_config` (fallback and the hand-scan/no-weight/storage
  limits).
- Offline devices in the card come from `liveness.py` (non-stale only).
- Customers with nothing to say are skipped and logged, not posted.

### Charts

`charts.py` keeps the three chart types. The good-read chart drops the fixed 97/90 lines and the
85–101 limits: the y-axis lower bound is `min(lowest point, lowest device warn line) - 5`, and a
point is annotated when it is below its own device's warn line. The volume chart skips devices
with no data (no empty legend). Chart URLs, storage and retention are unchanged.

### Stale digest

Weekly card listing devices in the stale state with last-seen date and days silent, with a note
that setting `reporting_enabled = 0` retires them. Posted only if the list is non-empty.

### Config (env, from Ansible)

| Env | Ansible default | Notes |
|---|---|---|
| `DB_HOST/PORT/NAME/USER/PASS` | `mssql`, 1433, RM DB, `admin` login | `s1_reporter_db_user` default changes from `sa` to `mssql_rm_admin_login` |
| `TEAMS_WEBHOOK_URL` | vault | |
| `CHART_DIR`, `CHART_PUBLIC_BASE_URL`, `CHART_RETENTION_DAYS` | as today | |
| `OFFLINE_THRESHOLD_MINUTES` | 30 | |
| `STALE_DAYS` | 14 | new `s1_reporter_stale_days` |
| `REPORT_TZ_OFFSET_HOURS` | 2 | new `s1_reporter_tz_offset_hours` |
| `UPLOAD_ALERT_CONSECUTIVE`, `UPLOAD_LOOKBACK_PACKETS` | 3, 6 | now Ansible vars |
| `OFFLINE_STATE_FILE`, `UPLOAD_STATE_FILE` | `/data/*.json` | |
| `TZ` | `Africa/Johannesburg` | container clock for log lines only; logic uses the offset |

Removed: `OFFLINE_CHECK_INTERVAL_MINUTES`, `DAILY_REPORT_HOUR`, `MONTHLY_REPORT_HOUR` (now cron
fields in Ansible: `s1_reporter_cron_*`).

### Image

Multi-stage: builder stage installs `freetds-dev`, `gcc`, `g++` and builds wheels from
`requirements.txt`; final stage is `python:3.12-slim` plus `freetds` runtime lib, the wheels, the
`app/` directory, a non-root `reporter` user, `TZ`. `ENTRYPOINT ["python", "-m", "s1_reporter"]`.

## Error handling

- Missing env var: `config.py` raises `SystemExit` naming it.
- DB unreachable: job exits non-zero, wrapper logs it, nothing is posted or committed.
- Teams POST fails after retries: card JSON logged (unchanged); state not committed; exit code 1
  so the log line is visible.
- Chart save fails: card omits the image (unchanged).
- Threshold table missing or unreadable: job exits non-zero. Silent fallback to constants is
  removed; fallbacks are the explicit `customer_config` columns.
- Two overlapping cron runs (for example a slow daily and a `check-alerts`): they touch different
  state files and the status MERGE is idempotent. Acceptable.

## Testing

Unit tests (unittest, plain imports, no DB):

- `liveness`: classification table above, `never` case, muted handling, reporting_enabled filter.
- `anomalies`: each rule fires/doesn't at its limit, uses device threshold before customer
  fallback, only yesterday's rows in daily mode.
- `state`: diff semantics, commit-after-send (state unchanged when commit not called).
- `upload`: consecutive-packet rule (moved from today's untested code).
- `reports`: customer skip rule, using an injected fake query function.
- `charts`: y-axis bound computation and annotation selection extracted as pure helpers.
- `cards`, `teams`, `chart_store`: existing tests carried over.
- Role file tests: compose has no `restart`/`healthcheck` on `reporter`, cron template renders
  the five entries, Dockerfile entrypoint.

Live verification on `sysone`, in order:

1. Deploy with `--tags s1_reporter`. Confirm `migrate` created `customer_config` (7 rows) and the
   `devices` columns, and that the old `s1_reporter` loop container is gone.
2. `run-reporter.sh sync-status`: `device_status` counts match the previous behaviour.
3. `run-reporter.sh check-alerts`: no card (nothing changed); `STATIC1@DUR` no longer logged as
   still-offline (it is stale).
4. `run-reporter.sh daily`: cards for customers with data only; no PEP AFRICA card; chart axis
   includes every device's warn line.
5. `run-reporter.sh stale-digest`: one card listing `STATIC1@DUR`.
6. Watch the next cron cycle in `/opt/s1-reporter/reporter.log`.

## Rollout

1. Land `s1_baselines` first (it removes the Sunday block from the current entrypoint and owns
   `alert_thresholds` creation).
2. This overhaul replaces the reporter application wholesale on its own branch. The role's
   `tasks/main.yml` removes the old container (`docker compose down` of the previous project
   before `up -d s1-charts`) so the loop cannot keep running beside the cron jobs.
3. The existing `s1_reporter_data` volume and its state files are reused; the offline state file
   format is unchanged, so no double alerts on cutover. `STATIC1@DUR` leaves the state silently
   because stale devices are filtered before the diff.
