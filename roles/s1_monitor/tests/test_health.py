import main
from fastapi.testclient import TestClient

def test_health_ok_when_probe_succeeds(monkeypatch):
    monkeypatch.setattr(main, "PROBE", lambda: True)
    r = TestClient(main.app).get("/health")
    assert r.status_code == 200 and r.json()["db_ok"] is True

def test_health_503_when_probe_fails(monkeypatch):
    monkeypatch.setattr(main, "PROBE", lambda: False)
    main.state.last_query_utc = None
    r = TestClient(main.app).get("/health")
    assert r.status_code == 503
