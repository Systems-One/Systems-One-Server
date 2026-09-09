"""Trend maths over per-device daily rows (SAST days)."""
import datetime as dt
from statistics import median
from timewin import week_monday

METRICS = {
    "items": {"name": "Items per day", "part": None, "direction": "high", "good": "up", "cap": "always"},
    "good_read_pct": {"name": "Good read %", "part": "good_read", "direction": "low", "good": "up", "cap": "always"},
    "no_dim_pct": {"name": "No dimension %", "part": "no_dimension", "direction": "high", "good": "down", "cap": "has_dimension"},
    "hand_scan_pct": {"name": "Hand scanned %", "part": "hand_scanned", "direction": "high", "good": "down", "cap": "has_hand_scan"},
    "not_sent_pct": {"name": "Not sent %", "part": "not_sent", "direction": "high", "good": "down", "cap": "always"},
}


def _value(rows, metric):
    items = sum(int(r["items"] or 0) for r in rows)
    if metric == "items":
        return items, items
    part = sum(int(r[METRICS[metric]["part"]] or 0) for r in rows)
    return (round(100.0 * part / items, 2) if items > 0 else None), items


def daily_series(daily_rows, metric, min_items):
    out = []
    for r in sorted(daily_rows, key=lambda x: x["day"]):
        v, items = _value([r], metric)
        out.append({"ts": r["day"].isoformat(), "value": v, "items": items, "low_volume": items < min_items})
    return out


def _agg(rows, metric, a, b, min_items):
    sel = [r for r in rows if a <= r["day"] < b]
    v, items = _value(sel, metric)
    if metric != "items" and items < min_items:
        return None
    return v


def week_over_week(daily_rows, metric, today_local, now_local, min_items):
    mon = week_monday(today_local)
    wk = dt.timedelta(days=7)
    elapsed = (now_local.date() - mon).days + 1          # days of this week that have started, incl. today
    this_week = _agg(daily_rows, metric, mon, mon + dt.timedelta(days=elapsed), min_items)
    prev = []
    for i in range(4, 0, -1):
        start = mon - i * wk
        end = start + (dt.timedelta(days=elapsed) if metric == "items" else wk)
        prev.append(_agg(daily_rows, metric, start, end, min_items))
    full_prev = [_agg(daily_rows, metric, mon - i * wk, mon - (i - 1) * wk, min_items) for i in range(4, 0, -1)]
    valid = [v for v in prev if v is not None]
    med = round(median(valid), 2) if valid else None
    delta_abs = round(this_week - med, 2) if this_week is not None and med is not None else None
    delta_pct = round(100.0 * (this_week - med) / med, 1) if delta_abs is not None and med else None
    return {"this_week": this_week, "prev4_median": med, "delta_abs": delta_abs, "delta_pct": delta_pct, "last5": full_prev + [this_week]}
