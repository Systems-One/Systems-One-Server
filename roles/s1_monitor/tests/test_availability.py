import datetime as dt
import availability as av

T = lambda h, m=0: dt.datetime(2026, 9, 9, h, m)


def test_no_gaps():
    assert av.outages([T(8), T(8, 5), T(8, 10)], 11, T(8, 12)) == []


def test_one_gap_and_open_gap():
    o = av.outages([T(8), T(8, 5), T(9, 0), T(9, 5)], 11, T(10, 0))
    assert o == [{"start": "2026-09-09T08:10:00Z", "end": "2026-09-09T09:00:00Z", "minutes": 55, "open": False},
                 {"start": "2026-09-09T09:10:00Z", "end": "2026-09-09T10:00:00Z", "minutes": 55, "open": True}]


def test_gap_exactly_at_threshold_is_not_outage():
    assert av.outages([T(8), T(8, 11)], 11, T(8, 12)) == []
    assert len(av.outages([T(8), T(8, 12)], 11, T(8, 13))) == 1


def test_classify():
    now = T(12)
    assert av.classify(None, T(1), now, 11, 14) == "never"
    assert av.classify(T(11, 55), T(1), now, 11, 14) == "online"
    assert av.classify(T(11, 40), T(1), now, 11, 14) == "offline"
    assert av.classify(now - dt.timedelta(days=15), T(1), now, 11, 14) == "stale"


def test_transitions():
    rows = [{"snapshot_utc": T(8), "uptime_seconds": 5000, "application_running": True, "status": "online"},
            {"snapshot_utc": T(8, 15), "uptime_seconds": 5900, "application_running": False, "status": "online"},
            {"snapshot_utc": T(8, 30), "uptime_seconds": 120, "application_running": True, "status": "offline"}]
    ev = av.transitions(rows)
    kinds = [e["kind"] for e in ev]
    assert kinds == ["app_stopped", "uptime_reset", "app_started", "status_change"]
    assert ev[1]["ts"] == "2026-09-09T08:28:00Z"   # 08:30 minus 120 s
