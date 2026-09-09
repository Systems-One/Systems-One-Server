"""Pure anomaly rules. Inputs are rows and states; output is (severity, message) pairs."""
from . import thresholds as th

MIN_ITEMS_FOR_RATE_RULES = 100
_ICON = {"bad": "🔴", "warn": "⚠️"}


def _pct(part, whole):
    return float(part or 0) / float(whole) * 100.0


def _label(r):
    return f"{r['machine_name']} @ {r['location']}"


def _low_rule(alerts, r, value, warn, bad, name):
    if bad is not None and value < bad:
        alerts.append(("bad", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (bad below {bad:.1f}%)"))
    elif warn is not None and value < warn:
        alerts.append(("warn", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (warn below {warn:.1f}%)"))


def _high_rule(alerts, r, value, warn, bad, name):
    if bad is not None and value > bad:
        alerts.append(("bad", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (bad above {bad:.1f}%)"))
    elif warn is not None and value > warn:
        alerts.append(("warn", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (warn above {warn:.1f}%)"))


def detect(day_rows, storage_rows, offline_states, cfg, thresholds) -> list:
    alerts = []
    for r in day_rows:
        items = r.get("daily_items") or 0
        if items <= MIN_ITEMS_FOR_RATE_RULES:
            continue
        ident = (r["customer"], r["machine_name"], r["location"])

        warn, bad = th.lookup(thresholds, cfg, *ident, "good_read_pct")
        _low_rule(alerts, r, _pct(r.get("daily_good"), items), warn, bad, "good read")

        if cfg.has_dimension:
            warn, bad = th.lookup(thresholds, cfg, *ident, "no_dim_pct")
            _high_rule(alerts, r, _pct(r.get("daily_no_dim"), items), warn, bad, "no-dimension")
        if cfg.has_hand_scan:
            _high_rule(alerts, r, _pct(r.get("daily_hand_scanned"), items), cfg.hand_scan_warn_pct, None, "hand-scanned")
        if cfg.has_weight:
            _high_rule(alerts, r, _pct(r.get("daily_no_weight"), items), cfg.no_weight_warn_pct, None, "no-weight")

    for s in storage_rows:
        pct = float(s.get("usage_percent") or 0)
        if pct > cfg.storage_bad_pct:
            alerts.append(("bad", f"{_label(s)}: C: drive at {pct:.0f}% (action required)"))
        elif pct > cfg.storage_warn_pct:
            alerts.append(("warn", f"{_label(s)}: C: drive at {pct:.0f}% (monitor)"))

    for st in offline_states:
        age = st.minutes_ago
        age_str = f"{age // 60}h {age % 60}m" if age >= 60 else f"{age}m"
        alerts.append(("bad", f"{st.device.machine_name} @ {st.device.location}: no data for {age_str} "
                              f"(last seen {st.last_seen:%Y-%m-%d %H:%M} UTC)"))
    return alerts


def format_lines(alerts) -> list:
    return [f"{_ICON.get(sev, '•')} {msg}" for sev, msg in alerts]
