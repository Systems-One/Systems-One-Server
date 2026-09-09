"""Fleet screen queries and builders."""
import datetime as dt
import availability as av
import rates
import severity
import thresholds as th
import timewin as tw

SQL_DEVICES = """
SELECT d.id, d.serial_number, d.customer, d.location, d.machine_name, d.reporting_enabled, d.muted_until, d.created_at,
       ds.status, ds.offline_since, das.application_running, das.stopped_since, os.os_version, u.uptime_seconds,
       m.cpu_percent, m.mem_usage_pct, m.temp_celsius,
       (SELECT MAX(usage_percent) FROM dbo.device_storage_status WHERE device_id = d.id AND drive = 'C:') AS c_usage,
       (SELECT MAX(usage_percent) FROM dbo.device_storage_status WHERE device_id = d.id) AS max_usage,
       ls.last_seen
FROM dbo.devices d
LEFT JOIN dbo.device_status ds ON ds.device_id = d.id
LEFT JOIN dbo.device_application_status das ON das.device_id = d.id
LEFT JOIN dbo.device_os_status os ON os.device_id = d.id
LEFT JOIN dbo.device_uptime_status u ON u.device_id = d.id
LEFT JOIN dbo.device_os_metrics m ON m.device_id = d.id
LEFT JOIN (SELECT device_id, MAX(ts_datetime) AS last_seen FROM dbo.device_statistics GROUP BY device_id) ls ON ls.device_id = d.id
ORDER BY d.customer, d.location, d.machine_name
"""
_SUMS = """SELECT device_id, SUM(total_items) AS items, SUM(good_read) AS good_read, SUM(no_read) AS no_read, SUM(no_dimension) AS no_dimension,
       SUM(no_weight) AS no_weight, SUM(hand_scanned) AS hand_scanned, SUM(not_sent) AS not_sent, SUM(more_than_1_item) AS more_than_1_item
FROM dbo.device_statistics WHERE ts_datetime >= ? GROUP BY device_id"""
SQL_TODAY = _SUMS
SQL_30D = _SUMS + " "   # distinct object so tests can tell them apart
SQL_SPARK24 = """SELECT device_id, DATEADD(HOUR, DATEDIFF(HOUR, 0, ts_datetime), 0) AS hour_utc, SUM(total_items) AS items
FROM dbo.device_statistics WHERE ts_datetime >= ?
GROUP BY device_id, DATEADD(HOUR, DATEDIFF(HOUR, 0, ts_datetime), 0)"""
SQL_RECENT_PACKETS = """SELECT device_id, items, not_sent, rn FROM (
  SELECT device_id, total_items AS items, not_sent, ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY ts_datetime DESC) AS rn
  FROM dbo.device_statistics) x WHERE rn <= 3"""
SQL_CONFIG = "SELECT * FROM dbo.customer_config"
SQL_THRESHOLDS = """SELECT customer, machine_name, location, metric, direction, warn_value, bad_value, baseline_mean, baseline_stddev,
       baseline_p10, baseline_p90, baseline_samples FROM dbo.alert_thresholds"""
SQL_LAST_WRITE = "SELECT state_value FROM ingest.pipeline_state WHERE state_key = 'last_db_write_utc'"


def _dt(v):
    if v is None or isinstance(v, dt.datetime):
        return v
    return dt.datetime.fromisoformat(str(v).replace("Z", "").split("+")[0])


def _cfg_map(q):
    return {r["customer"]: r for r in q(SQL_CONFIG, ())}


def _identity(d):
    return {k: d.get(k) for k in ("id", "serial_number", "customer", "location", "machine_name", "reporting_enabled", "muted_until")}


def build_meta(q, s, now_utc):
    devices = q(SQL_DEVICES, ())
    cfg = _cfg_map(q)
    rows = q(SQL_THRESHOLDS, ())
    thr = {str(d["id"]): th.all_for_device(rows, cfg.get(d["customer"]), d["customer"], d["machine_name"], d["location"]) for d in devices}
    return {"generated_utc": now_utc.isoformat() + "Z", "tz_offset_hours": s.tz_offset_hours,
            "min_items": {"day": s.min_items_day, "hour": s.min_items_hour, "half_hour": s.min_items_half_hour},
            "offline_gap_minutes": s.offline_gap_minutes, "stale_days": s.stale_days,
            "customers": sorted(cfg.values(), key=lambda c: c["customer"]),
            "devices": [_identity(d) for d in devices], "thresholds": thr}


def _sums(rows, device_id):
    r = next((x for x in rows if x["device_id"] == device_id), None)
    items = int(r["items"]) if r else 0
    out = {"items": items, "good_read_pct": rates.rate(r["good_read"], items) if r else None}
    out.update({p: int(r[p] or 0) if r else 0 for p in rates.PARTS})
    return out


def build_fleet(q, s, now_utc, customer=None):
    devices = q(SQL_DEVICES, ())
    if customer:
        devices = [d for d in devices if d["customer"] == customer]
    cfg = _cfg_map(q)
    rows_thr = q(SQL_THRESHOLDS, ())
    midnight = tw.local_midnight(now_utc, s.tz_offset_hours)
    today = q(SQL_TODAY, (midnight,))
    d30 = q(SQL_30D, (midnight - dt.timedelta(days=29),))
    spark = q(SQL_SPARK24, (now_utc - dt.timedelta(hours=24),))
    packets = q(SQL_RECENT_PACKETS, ())
    lw = q(SQL_LAST_WRITE, ())
    last_write = _dt(lw[0]["state_value"]) if lw else None
    hour_now = now_utc.replace(minute=0, second=0, microsecond=0)
    out_devices, sev_input = [], []
    for d in devices:
        last_seen, created = _dt(d.get("last_seen")), _dt(d.get("created_at"))
        state = av.classify(last_seen, created, now_utc, s.offline_gap_minutes, s.stale_days)
        t, m = _sums(today, d["id"]), _sums(d30, d["id"])
        t["low_volume"], m["low_volume"] = t["items"] < s.min_items_day, m["items"] < s.min_items_day
        hours = {}
        for r in spark:
            if r["device_id"] == d["id"]:
                hours[_dt(r["hour_utc"])] = int(r["items"] or 0)
        spark24 = [hours.get(hour_now - dt.timedelta(hours=i), 0) for i in range(23, -1, -1)]
        out_devices.append({**_identity(d), "state": state, "last_seen": d.get("last_seen"), "today": t, "d30": m, "spark24": spark24,
                            "c_usage": d.get("c_usage"), "max_usage": d.get("max_usage"), "app_running": d.get("application_running"),
                            "os_version": d.get("os_version")})
        sev_input.append({**_identity(d), "muted_until": _dt(d.get("muted_until")), "state": state, "last_seen": last_seen,
                          "items": t["items"], "good_read": t["good_read"], "no_dimension": t["no_dimension"], "hand_scanned": t["hand_scanned"],
                          "no_weight": t["no_weight"], "c_usage": d.get("c_usage"), "application_running": d.get("application_running"),
                          "stopped_since": _dt(d.get("stopped_since"))})
    pk_by = {}
    for p in sorted(packets, key=lambda p: p["rn"]):
        pk_by.setdefault(p["device_id"], []).append(p)
    attention = severity.attention(sev_input, cfg, rows_thr, pk_by, now_utc, s)
    items_today = sum(x["today"]["items"] for x in out_devices); good_today = sum(x["today"]["good_read"] for x in out_devices)
    items_30 = sum(x["d30"]["items"] for x in out_devices); good_30 = sum(x["d30"]["good_read"] for x in out_devices)
    states = [x["state"] for x in out_devices]
    strip = {"online": states.count("online"), "offline": states.count("offline"), "stale": states.count("stale"), "never": states.count("never"),
             "disabled": sum(1 for x in out_devices if not x["reporting_enabled"]), "total": len(out_devices),
             "items_today": items_today, "good_read_today_pct": rates.rate(good_today, items_today),
             "items_30d": items_30, "good_read_30d_pct": rates.rate(good_30, items_30),
             "last_db_write_utc": last_write.isoformat() + "Z" if last_write else None,
             "db_write_age_s": int((now_utc - last_write).total_seconds()) if last_write else None}
    return {"generated_utc": now_utc.isoformat() + "Z", "strip": strip, "attention": attention, "devices": out_devices}
