"""Device screen queries and builders."""
import datetime as dt
import availability as av
import rates
import thresholds as th
import timewin as tw
from queries import fleet as qf

SQL_DEVICE = qf.SQL_DEVICES.replace("ORDER BY d.customer, d.location, d.machine_name", "WHERE d.id = ?")
SQL_DRIVES = "SELECT drive, drive_type, format, total_gb, free_gb, used_gb, usage_percent FROM dbo.device_storage_status WHERE device_id = ? ORDER BY drive"

_INNER = """(SELECT DATEADD(HOUR, ?, ts_datetime) AS local_ts, total_items, good_read, no_read, no_dimension, no_weight, hand_scanned, not_sent, more_than_1_item
            FROM dbo.device_statistics WHERE device_id = ? AND ts_datetime >= ? AND ts_datetime < ?) x"""
_SUMS = """SUM(total_items) AS items, SUM(good_read) AS good_read, SUM(no_read) AS no_read, SUM(no_dimension) AS no_dimension, SUM(no_weight) AS no_weight,
           SUM(hand_scanned) AS hand_scanned, SUM(not_sent) AS not_sent, SUM(more_than_1_item) AS more_than_1_item, COUNT(*) AS rows"""
SQL_BUCKETS_DAY = f"SELECT CAST(CAST(local_ts AS date) AS datetime2(0)) AS bucket_local, {_SUMS} FROM {_INNER} GROUP BY CAST(local_ts AS date)"
SQL_BUCKETS_HOUR = f"SELECT DATEADD(HOUR, DATEDIFF(HOUR, 0, local_ts), 0) AS bucket_local, {_SUMS} FROM {_INNER} GROUP BY DATEADD(HOUR, DATEDIFF(HOUR, 0, local_ts), 0)"
SQL_BUCKETS_HALF_HOUR = f"SELECT DATEADD(MINUTE, (DATEDIFF(MINUTE, 0, local_ts) / 30) * 30, 0) AS bucket_local, {_SUMS} FROM {_INNER} GROUP BY DATEADD(MINUTE, (DATEDIFF(MINUTE, 0, local_ts) / 30) * 30, 0)"
SQL_TIMESTAMPS = "SELECT ts_datetime AS ts FROM dbo.device_statistics WHERE device_id = ? AND ts_datetime >= ? ORDER BY ts_datetime"
SQL_PACKETS = "SELECT total_items AS items FROM dbo.device_statistics WHERE device_id = ? AND ts_datetime >= ? AND ts_datetime < ? AND total_items > 0"

_BUCKET_SQL = {86400: SQL_BUCKETS_DAY, 3600: SQL_BUCKETS_HOUR, 1800: SQL_BUCKETS_HALF_HOUR}
_NOT_MEASURED = [("has_dimension", "no dimension"), ("has_dimension", "more than 1 item"), ("has_weight", "no weight"), ("has_hand_scan", "hand scan")]


def _dt(v):
    return qf._dt(v)


def _caps(cfg):
    return {k: bool(cfg.get(k)) for k in ("has_dimension", "has_weight", "has_hand_scan")}


def build_device(q, s, now_utc, device_id):
    rows = q(SQL_DEVICE, (device_id,))
    if not rows:
        return None
    d = rows[0]
    cfg = qf._cfg_map(q).get(d["customer"], th.DEFAULT_CFG)
    thr = th.all_for_device(q(qf.SQL_THRESHOLDS, ()), cfg, d["customer"], d["machine_name"], d["location"])
    state = av.classify(_dt(d.get("last_seen")), _dt(d.get("created_at")), now_utc, s.offline_gap_minutes, s.stale_days)
    return {**d, "generated_utc": now_utc.isoformat() + "Z", "state": state, "capabilities": _caps(cfg), "storage_limits": {"warn": cfg.get("storage_warn_pct"), "bad": cfg.get("storage_bad_pct")},
            "thresholds": thr, "drives": q(SQL_DRIVES, (device_id,))}


def _fetch_buckets(q, s, device_id, bucket_seconds, from_utc, to_utc):
    rows = q(_BUCKET_SQL[bucket_seconds], (s.tz_offset_hours, device_id, from_utc, to_utc))
    for r in rows:
        r["bucket_utc"] = tw.to_utc(_dt(r["bucket_local"]), s.tz_offset_hours)
    return rows


def build_series(q, s, now_utc, device_id, preset_name):
    preset = tw.PRESETS.get(preset_name)
    if preset is None:
        raise ValueError("unknown range")
    dev = q(SQL_DEVICE, (device_id,))
    if not dev:
        return None
    d = dev[0]
    cfg = qf._cfg_map(q).get(d["customer"], th.DEFAULT_CFG)
    frm, to = tw.window(preset, now_utc, s.tz_offset_hours)
    end_excl = to if preset.daily else to + dt.timedelta(seconds=preset.bucket_seconds)
    starts = tw.bucket_starts(frm, end_excl, preset.bucket_seconds)
    min_items = tw.min_items_for(preset, s)
    buckets = rates.fill_buckets(_fetch_buckets(q, s, device_id, preset.bucket_seconds, frm, end_excl), starts, min_items)
    out = {"generated_utc": now_utc.isoformat() + "Z", "range": preset.name, "bucket_seconds": preset.bucket_seconds, "style": preset.style, "from": frm.isoformat() + "Z", "to": end_excl.isoformat() + "Z",
           "min_items": min_items, "buckets": buckets}
    if preset.daily:
        hourly = rates.fill_buckets(_fetch_buckets(q, s, device_id, 3600, frm, end_excl), tw.bucket_starts(frm, end_excl, 3600), s.min_items_hour)
        out["hourly"] = hourly
        per = [h["items"] for h in hourly if not h["nodata"] and h["items"] > 0]
        out["summary"] = rates.summary(buckets, per, "hour")
    else:
        per = [int(p["items"]) for p in q(SQL_PACKETS, (device_id, frm, end_excl))]
        out["summary"] = rates.summary(buckets, per, "packet")
    t = rates.totals(buckets)
    out["totals"] = t
    out["partition"] = rates.partition(t, bool(cfg.get("has_hand_scan")))
    out["applicable_rates"] = rates.applicable_rates(cfg)
    out["not_measured"] = [name for cap, name in _NOT_MEASURED if not cfg.get(cap)]
    ts = [_dt(r["ts"]) for r in q(SQL_TIMESTAMPS, (device_id, frm))]
    out["outages"] = av.outages(ts, s.offline_gap_minutes, min(now_utc, end_excl))
    return out
