import datetime as dt
import main
from fastapi.testclient import TestClient
from queries import health as H
NOW = dt.datetime(2026, 9, 9, 11, 0)
def fake_query(sql, params=()):
    if sql is H.SQL_HISTORY_SINCE: return [{"since": "2026-09-01T00:00:00Z"}]
    if sql is H.SQL_HISTORY:
        base = dt.datetime(2026, 9, 9, 8)
        return [{"snapshot_utc": base + dt.timedelta(minutes=15 * i), "status": "online", "application_running": i != 1, "uptime_seconds": 1000 + i,
                 "cpu_percent": 5.0, "mem_usage_pct": 40.0, "temp_celsius": 29.0, "c_usage_percent": 80.0, "max_usage_percent": 80.0} for i in range(3)]
    raise AssertionError(sql[:30])
def setup_function():
    main.QUERY = fake_query; main.NOW_OVERRIDE = NOW; main.cache._entries.clear()
def test_health_history_rows_and_events():
    r = TestClient(main.app).get("/api/device/3/health?range=24h").json()
    assert r["history_since"] == "2026-09-01T00:00:00Z" and len(r["rows"]) == 3
    assert [e["kind"] for e in r["events"]] == ["app_stopped", "app_started"]
