"""Trends screen: daily per device over a window, week over week."""
import datetime as dt
import thresholds as th
import timewin as tw
import trends as tr
from queries import fleet as qf

SQL_DAILY = """SELECT device_id, CAST(local_ts AS date) AS day, SUM(total_items) AS items, SUM(good_read) AS good_read, SUM(no_read) AS no_read,
       SUM(no_dimension) AS no_dimension, SUM(no_weight) AS no_weight, SUM(hand_scanned) AS hand_scanned, SUM(not_sent) AS not_sent, SUM(more_than_1_item) AS more_than_1_item
FROM (SELECT device_id, DATEADD(HOUR, ?, ts_datetime) AS local_ts, total_items, good_read, no_read, no_dimension, no_weight, hand_scanned, not_sent, more_than_1_item
      FROM dbo.device_statistics WHERE ts_datetime >= ?) x
GROUP BY device_id, CAST(local_ts AS date)"""

_THR_KEY = {"good_read_pct": "good_read_pct", "no_dim_pct": "no_dim_pct", "hand_scan_pct": "hand_scan_pct"}


def _date(v):
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def build_trends(q, s, now_utc, metric, preset_name, customer=None):
    m = tr.METRICS.get(metric); preset = tw.PRESETS.get(preset_name)
    if m is None or preset is None or not preset.daily:
        raise ValueError("bad metric or range")
    devices = [d for d in q(qf.SQL_DEVICES, ()) if d.get("reporting_enabled", True) and (not customer or d["customer"] == customer)]
    cfg = qf._cfg_map(q); rows_thr = q(qf.SQL_THRESHOLDS, ())
    frm, _ = tw.window(preset, now_utc, s.tz_offset_hours)
    wow_from = tw.local_midnight(now_utc, s.tz_offset_hours) - dt.timedelta(days=42)
    daily = q(SQL_DAILY, (s.tz_offset_hours, min(frm, wow_from)))
    for r in daily:
        r["day"] = _date(r["day"])
    local_now = tw.to_local(now_utc, s.tz_offset_hours); today = local_now.date(); from_date = tw.to_local(frm, s.tz_offset_hours).date()
    out, wow, hidden = [], [], 0
    for d in devices:
        c = cfg.get(d["customer"], th.DEFAULT_CFG)
        if m["cap"] != "always" and not c.get(m["cap"]):
            hidden += 1
            continue
        rows = [r for r in daily if r["device_id"] == d["id"]]
        series = tr.daily_series([r for r in rows if r["day"] >= from_date], metric, s.min_items_day)
        vals = [x["value"] for x in series if not x["low_volume"] and x["value"] is not None]
        t = th.lookup(rows_thr, c, d["customer"], d["machine_name"], d["location"], _THR_KEY[metric]) if metric in _THR_KEY else {"warn": None, "bad": None}
        out.append({"id": d["id"], "customer": d["customer"], "location": d["location"], "machine_name": d["machine_name"], "daily": series,
                    "average": round(sum(vals) / len(vals), 2) if vals else None, "warn": t["warn"], "bad": t["bad"]})
        w = tr.week_over_week(rows, metric, today, local_now, s.min_items_day)
        wow.append({"id": d["id"], "label": f"{d['machine_name']} @ {d['location']}", "customer": d["customer"], **w})
    key = (lambda w: w["delta_pct"]) if metric == "items" else (lambda w: w["delta_abs"])
    wow.sort(key=lambda w: (key(w) is None, (key(w) or 0) if m["good"] == "up" else -(key(w) or 0)))
    return {"generated_utc": now_utc.isoformat() + "Z", "metric": metric, "range": preset.name, "devices": out, "wow": wow, "hidden": hidden}
