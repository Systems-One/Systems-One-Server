import main
from fastapi.testclient import TestClient

def test_health_ok_when_probe_succeeds(monkeypatch):
    monkeypatch.setattr(main, "PROBE", lambda: True)
    main.state.snapshot_error = main.state.snapshot_error_class = None
    r = TestClient(main.app).get("/health")
    b = r.json()
    assert r.status_code == 200 and b["db_ok"] is True
    assert b["snapshot_ok"] is True and b["snapshot_error_class"] is None and "snapshot_error" not in b


def test_health_reports_snapshot_error_as_a_class_name(monkeypatch):
    monkeypatch.setattr(main, "PROBE", lambda: True)
    main.state.snapshot_error = "RuntimeError: login failed for user 'admin'"
    main.state.snapshot_error_class = "RuntimeError"
    try:
        b = TestClient(main.app).get("/health").json()
    finally:
        main.state.snapshot_error = main.state.snapshot_error_class = None
    assert b["snapshot_ok"] is False and b["snapshot_error_class"] == "RuntimeError"
    assert "login failed" not in str(b)

def test_health_503_when_probe_fails(monkeypatch):
    monkeypatch.setattr(main, "PROBE", lambda: False)
    main.state.last_query_utc = None
    r = TestClient(main.app).get("/health")
    assert r.status_code == 503
