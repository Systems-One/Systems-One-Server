"""Host history for the device page."""
import availability as av
import timewin as tw
from queries import fleet as qf

SQL_HISTORY = """SELECT snapshot_utc, status, application_running, uptime_seconds, cpu_percent, mem_usage_pct, temp_celsius, c_usage_percent, max_usage_percent
FROM dbo.device_health_history WHERE device_id = ? AND snapshot_utc >= ? ORDER BY snapshot_utc"""
SQL_HISTORY_SINCE = "SELECT MIN(snapshot_utc) AS since FROM dbo.device_health_history WHERE device_id = ?"


def build_health(q, s, now_utc, device_id, preset_name):
    preset = tw.PRESETS[preset_name]
    frm, _ = tw.window(preset, now_utc, s.tz_offset_hours)
    since = q(SQL_HISTORY_SINCE, (device_id,))
    rows = q(SQL_HISTORY, (device_id, frm))
    for r in rows:
        r["snapshot_utc"] = qf._dt(r["snapshot_utc"])
    events = av.transitions(rows)
    stride = max(1, len(rows) // 2000)
    thin = rows[::stride]
    out_rows = [{"ts": r["snapshot_utc"].isoformat() + "Z", **{k: r.get(k) for k in ("cpu_percent", "mem_usage_pct", "temp_celsius", "c_usage_percent", "max_usage_percent", "application_running", "status")}} for r in thin]
    return {"history_since": since[0]["since"] if since and since[0]["since"] else None, "rows": out_rows, "events": events}
