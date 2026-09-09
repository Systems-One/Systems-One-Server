import datetime as dt
import main
from fastapi.testclient import TestClient
from queries import device as Q
from queries import fleet as F

NOW = dt.datetime(2026, 9, 9, 11, 33)
DEV = {"id": 3013, "serial_number": "019000-01-2", "customer": "MADIBANA", "location": "PE", "machine_name": "DIM1", "reporting_enabled": True, "muted_until": None,
       "created_at": "2026-05-12T09:48:54Z", "status": "online", "offline_since": None, "application_running": True, "stopped_since": None, "os_version": "Win",
       "uptime_seconds": 100.0, "cpu_percent": 1.0, "mem_usage_pct": 40.0, "temp_celsius": 29.0, "c_usage": 44.0, "max_usage": 44.0, "last_seen": "2026-09-09T11:30:00Z"}
CFG = {"customer": "MADIBANA", "has_dimension": True, "has_weight": True, "has_hand_scan": True, "hand_scan_warn_pct": 15.0, "no_weight_warn_pct": 5.0,
       "storage_warn_pct": 80.0, "storage_bad_pct": 90.0, "good_read_warn_pct": 95.0, "good_read_bad_pct": 90.0, "no_dim_warn_pct": 5.0, "no_dim_bad_pct": 10.0, "reports_enabled": True}
L = dt.datetime  # local (SAST) bucket starts as the SQL would return

def fake_query(sql, params=()):
    if sql is Q.SQL_DEVICE: return [DEV] if params[0] == 3013 else []
    if sql is Q.SQL_DRIVES: return [{"drive": "C:", "total_gb": 237.8, "free_gb": 139.4, "usage_percent": 44.0}]
    if sql is F.SQL_CONFIG: return [CFG]
    if sql is F.SQL_THRESHOLDS: return []
    if sql is Q.SQL_BUCKETS_DAY:
        assert params[0] == 2 and params[1] == 3013
        return [{"bucket_local": L(2026, 9, 9), "items": 600, "good_read": 500, "no_read": 100, "no_dimension": 0, "no_weight": 0, "hand_scanned": 90, "not_sent": 30, "more_than_1_item": 0, "rows": 130}]
    if sql is Q.SQL_BUCKETS_HOUR:
        return [{"bucket_local": L(2026, 9, 9, 9), "items": 600, "good_read": 500, "no_read": 100, "no_dimension": 0, "no_weight": 0, "hand_scanned": 90, "not_sent": 30, "more_than_1_item": 0, "rows": 12}]
    if sql is Q.SQL_BUCKETS_HALF_HOUR:
        return [{"bucket_local": L(2026, 9, 9, 13, 0), "items": 40, "good_read": 40, "no_read": 0, "no_dimension": 0, "no_weight": 0, "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 0, "rows": 6}]
    if sql is Q.SQL_TIMESTAMPS: return [{"ts": "2026-09-09T07:00:00Z"}, {"ts": "2026-09-09T07:05:00Z"}, {"ts": "2026-09-09T11:30:00Z"}]
    if sql is Q.SQL_PACKETS: return [{"items": 5}, {"items": 35}]
    raise AssertionError(sql[:40])

def setup_function():
    main.QUERY = fake_query; main.NOW_OVERRIDE = NOW; main.cache._entries.clear()

def test_device_header_and_404():
    c = TestClient(main.app)
    r = c.get("/api/device/3013").json()
    assert r["machine_name"] == "DIM1" and r["capabilities"] == {"has_dimension": True, "has_weight": True, "has_hand_scan": True}
    assert r["thresholds"]["good_read_pct"]["source"] == "customer default" and r["drives"][0]["drive"] == "C:"
    assert c.get("/api/device/999").status_code == 404

def test_series_daily_7d():
    r = TestClient(main.app).get("/api/device/3013/series?range=7d").json()
    assert r["bucket_seconds"] == 86400 and len(r["buckets"]) == 7 and r["style"] == "line"
    last = r["buckets"][-1]
    assert last["ts"] == "2026-09-08T22:00:00Z" and last["items"] == 600 and last["rates"]["good_read_pct"] == 83.33 and last["low_volume"] is False
    assert r["buckets"][0]["nodata"] is True
    assert r["summary"]["per_unit"] == {"max": 600, "min": 600, "avg": 600.0, "label": "hour"}
    assert r["partition"] == [{"name": "Good read", "value": 500}, {"name": "No read, recovered by hand scan", "value": 90}, {"name": "No read, not recovered", "value": 10}]
    assert [x["key"] for x in r["applicable_rates"]] == ["good_read_pct", "no_dim_pct", "hand_scan_pct", "no_weight_pct", "not_sent_pct"]
    assert r["not_measured"] == [] and len(r["hourly"]) == 168
    assert r["outages"][0]["minutes"] == 265 and r["outages"][0]["open"] is False

def test_series_detail_24h_uses_half_hour_and_packets():
    r = TestClient(main.app).get("/api/device/3013/series?range=24h").json()
    assert r["bucket_seconds"] == 1800 and len(r["buckets"]) == 48 and r["style"] == "bars" and "hourly" not in r
    assert r["summary"]["per_unit"]["label"] == "packet" and r["summary"]["per_unit"]["max"] == 35
    assert r["buckets"][-2]["ts"] == "2026-09-09T11:00:00Z" and r["buckets"][-2]["items"] == 40 and r["buckets"][-2]["low_volume"] is False

def test_series_bad_range():
    assert TestClient(main.app).get("/api/device/3013/series?range=5y").status_code == 400
