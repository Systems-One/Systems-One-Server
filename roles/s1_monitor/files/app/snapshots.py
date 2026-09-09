"""Host health snapshots: copy latest-value rows into dbo.device_health_history on a timer."""
import asyncio
import datetime as dt
import logging
import os
import re

log = logging.getLogger("s1_monitor.snapshots")
MIGRATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations", "001_device_health_history.sql")

SQL_INSERT = """INSERT INTO dbo.device_health_history
 (device_id, snapshot_utc, status, status_ts_utc, application_running, app_ts_utc, uptime_seconds, cpu_percent, mem_usage_pct, temp_celsius,
  c_usage_percent, max_usage_percent, drives_json, last_stats_utc)
SELECT d.id, ?, ds.status, ds.ts_datetime, das.application_running, das.ts_datetime, u.uptime_seconds, m.cpu_percent, m.mem_usage_pct, m.temp_celsius,
  (SELECT MAX(usage_percent) FROM dbo.device_storage_status WHERE device_id = d.id AND drive = 'C:'),
  (SELECT MAX(usage_percent) FROM dbo.device_storage_status WHERE device_id = d.id),
  (SELECT drive, total_gb, free_gb, usage_percent FROM dbo.device_storage_status st WHERE st.device_id = d.id FOR JSON PATH),
  (SELECT MAX(ts_datetime) FROM dbo.device_statistics WHERE device_id = d.id)
FROM dbo.devices d
LEFT JOIN dbo.device_status ds ON ds.device_id = d.id
LEFT JOIN dbo.device_application_status das ON das.device_id = d.id
LEFT JOIN dbo.device_uptime_status u ON u.device_id = d.id
LEFT JOIN dbo.device_os_metrics m ON m.device_id = d.id"""
SQL_PRUNE = "DELETE FROM dbo.device_health_history WHERE snapshot_utc < ?"


def migrate(execute):
    sql = open(MIGRATION, encoding="utf-8").read()
    for stmt in [s.strip() for s in re.split(r"^\s*GO\s*$", sql, flags=re.M | re.I) if s.strip()]:
        execute(stmt, ())


def run_once(execute, now_utc):
    return execute(SQL_INSERT, (now_utc,))


def prune(execute, now_utc, retention_days):
    return execute(SQL_PRUNE, (now_utc - dt.timedelta(days=retention_days),))


async def loop(execute, s, state, sleep=asyncio.sleep, clock=None):
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0))
    await sleep(60)
    last_prune = None
    while True:
        now = clock()
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_once, execute, now)
            state.snapshot_last_utc, state.snapshot_error = now, None
            state.snapshot_error_class = None
            if last_prune is None or (now - last_prune) >= dt.timedelta(days=1):
                await asyncio.get_running_loop().run_in_executor(None, prune, execute, now, s.snapshot_retention_days)
                last_prune = now
        except Exception as exc:
            state.snapshot_error = f"{type(exc).__name__}: {exc}"
            state.snapshot_error_class = type(exc).__name__
            log.exception("snapshot failed")
        await sleep(s.snapshot_interval_minutes * 60)
