import datetime as dt
import main
from fastapi.testclient import TestClient
from queries import trends as T
from queries import fleet as F
from test_api_fleet import DEV, CFG   # PEPKOR JBH DIM1, has_dimension only

NOW = dt.datetime(2026, 9, 9, 11, 0)
def fake_query(sql, params=()):
    if sql is F.SQL_DEVICES: return [DEV, {**DEV, "id": 4, "customer": "PEP", "machine_name": "STATIC1", "location": "HDH"}]
    if sql is F.SQL_CONFIG: return [CFG, {**CFG, "customer": "PEP", "has_dimension": False}]
    if sql is F.SQL_THRESHOLDS: return []
    if sql is T.SQL_DAILY:
        assert params[0] == 2
        return [{"device_id": 3, "day": dt.date(2026, 9, 9) - dt.timedelta(days=i), "items": 1000, "good_read": 950, "no_read": 50, "no_dimension": 10, "no_weight": 0, "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 0} for i in range(40)]
    raise AssertionError(sql[:40])

def setup_function():
    main.QUERY = fake_query; main.NOW_OVERRIDE = NOW; main.cache._entries.clear()

def test_trends_good_read_30d():
    r = TestClient(main.app).get("/api/trends?metric=good_read_pct&range=30d").json()
    assert r["hidden"] == 0 and len(r["devices"]) == 2
    d3 = next(x for x in r["devices"] if x["id"] == 3)
    assert len(d3["daily"]) == 30 and d3["average"] == 95.0 and d3["warn"] == 95.0
    w = next(x for x in r["wow"] if x["id"] == 3)
    assert w["this_week"] == 95.0 and w["prev4_median"] == 95.0

def test_trends_no_dim_hides_pep():
    r = TestClient(main.app).get("/api/trends?metric=no_dim_pct&range=7d").json()
    assert r["hidden"] == 1 and [x["id"] for x in r["devices"]] == [3]

def test_trends_validation():
    assert TestClient(main.app).get("/api/trends?metric=nope&range=7d").status_code == 400
    assert TestClient(main.app).get("/api/trends?metric=items&range=24h").status_code == 400
