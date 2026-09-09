import dataclasses
import datetime as dt
import main
from fastapi.testclient import TestClient
from queries import fleet as F

NOW = dt.datetime(2026, 9, 9, 11, 0)
DEV = {"id": 3, "serial_number": "018389-01-1", "customer": "PEPKOR", "location": "JBH", "machine_name": "DIM1", "reporting_enabled": True,
       "muted_until": None, "created_at": "2026-01-15T10:27:15Z", "status": "online", "offline_since": None, "application_running": True,
       "stopped_since": None, "os_version": "Windows", "uptime_seconds": 1000.0, "cpu_percent": 3.0, "mem_usage_pct": 40.0, "temp_celsius": 29.9,
       "c_usage": 82.0, "max_usage": 82.0, "last_seen": "2026-09-09T10:58:00Z"}
CFG = {"customer": "PEPKOR", "has_dimension": True, "has_weight": False, "has_hand_scan": False, "hand_scan_warn_pct": 15.0, "no_weight_warn_pct": 5.0,
       "storage_warn_pct": 80.0, "storage_bad_pct": 90.0, "good_read_warn_pct": 95.0, "good_read_bad_pct": 90.0, "no_dim_warn_pct": 5.0, "no_dim_bad_pct": 10.0, "reports_enabled": True}

def fake_query(sql, params=()):
    if sql is F.SQL_DEVICES: return [DEV]
    if sql is F.SQL_CONFIG: return [CFG]
    if sql is F.SQL_THRESHOLDS: return []
    if sql is F.SQL_TODAY: return [{"device_id": 3, "items": 500, "good_read": 495, "no_read": 5, "no_dimension": 2, "no_weight": 0, "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 1}]
    if sql is F.SQL_30D: return [{"device_id": 3, "items": 60000, "good_read": 59000, "no_read": 1000, "no_dimension": 0, "no_weight": 0, "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 0}]
    if sql is F.SQL_SPARK24: return [{"device_id": 3, "hour_utc": "2026-09-09T11:00:00Z", "items": 120}]
    if sql is F.SQL_RECENT_PACKETS:
        # the rule reads the last 3 packets only, so the query is bounded to the last hour
        assert params[0] == NOW - dt.timedelta(hours=1)
        return [{"device_id": 3, "items": 10, "not_sent": 0, "rn": 1}]
    if sql is F.SQL_LAST_WRITE: return [{"state_value": "2026-09-09T10:59:00+00:00"}]
    raise AssertionError("unexpected sql")

def setup_function():
    main.QUERY = fake_query
    main.NOW_OVERRIDE = NOW
    main.cache._entries.clear()

def test_meta_shape():
    r = TestClient(main.app).get("/api/meta").json()
    assert r["tz_offset_hours"] == 2 and r["min_items"] == {"day": 100, "hour": 30, "half_hour": 15}
    assert r["devices"][0]["id"] == 3 and r["customers"][0]["customer"] == "PEPKOR"
    assert r["thresholds"]["3"]["good_read_pct"]["source"] == "customer default"

def test_fleet_strip_devices_and_attention():
    r = TestClient(main.app).get("/api/fleet").json()
    assert r["strip"]["online"] == 1 and r["strip"]["items_today"] == 500 and r["strip"]["good_read_today_pct"] == 99.0
    assert r["strip"]["db_write_age_s"] == 60
    d = r["devices"][0]
    assert d["state"] == "online" and d["today"]["good_read_pct"] == 99.0 and d["d30"]["good_read_pct"] == 98.33
    assert len(d["spark24"]) == 24 and d["spark24"][-1] == 120
    assert r["attention"][0]["rule"] == "C: drive" and r["attention"][0]["severity"] == "warn"

def test_fleet_customer_filter_and_stale_flag(monkeypatch):
    # A live ttl of 0 means every request re-validates against the DB instead of short-circuiting
    # on the warmed entry, so the boom below actually gets a chance to run and fail.
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, cache_ttl_live=0))
    assert TestClient(main.app).get("/api/fleet?customer=NOPE").json()["devices"] == []
    assert TestClient(main.app).get("/api/fleet").status_code == 200
    def boom(sql, params=()): raise RuntimeError("down")
    main.QUERY = boom
    r = TestClient(main.app).get("/api/fleet")
    assert r.status_code == 200 and r.json()["stale"] is True
    main.cache._entries.clear()
    r2 = TestClient(main.app).get("/api/fleet")
    assert r2.status_code == 503 and r2.json()["detail"] == "RuntimeError"   # class name only, never the message
