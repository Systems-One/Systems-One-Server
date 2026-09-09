import datetime as dt
import severity as sv

NOW = dt.datetime(2026, 9, 9, 11, 0)


class S:
    min_items_day = 100
    min_items_hour = 30
    min_items_half_hour = 15
    offline_gap_minutes = 11
    stale_days = 14


CFG = {
    "PEP": {
        "has_dimension": False,
        "has_weight": False,
        "has_hand_scan": False,
        "hand_scan_warn_pct": 15,
        "no_weight_warn_pct": 5,
        "storage_warn_pct": 80,
        "storage_bad_pct": 90,
        "good_read_warn_pct": 95,
        "good_read_bad_pct": 90,
        "no_dim_warn_pct": 5,
        "no_dim_bad_pct": 10,
    }
}


def dev(**k):
    d = {
        "id": 1,
        "customer": "PEP",
        "location": "HDH",
        "machine_name": "STATIC1",
        "reporting_enabled": True,
        "muted_until": None,
        "state": "online",
        "last_seen": NOW,
        "items": 500,
        "good_read": 480,
        "no_dimension": 0,
        "hand_scanned": 0,
        "no_weight": 0,
        "c_usage": 40.0,
        "application_running": True,
        "stopped_since": None,
    }
    d.update(k)
    return d


def test_clean_device_has_no_items():
    assert sv.attention([dev()], CFG, [], {}, NOW, S) == []


def test_offline_is_bad_and_skipped_when_muted_or_disabled():
    assert sv.attention([dev(state="offline", last_seen=NOW - dt.timedelta(minutes=30))], CFG, [], {}, NOW, S)[0]["rule"] == "No data"
    assert sv.attention([dev(state="offline", muted_until=NOW + dt.timedelta(hours=1))], CFG, [], {}, NOW, S) == []
    assert sv.attention([dev(state="offline", reporting_enabled=False)], CFG, [], {}, NOW, S) == []


def test_good_read_warn_and_bad_and_low_volume_skip():
    assert sv.attention([dev(good_read=460)], CFG, [], {}, NOW, S)[0]["severity"] == "warn"  # 92%
    assert sv.attention([dev(good_read=400)], CFG, [], {}, NOW, S)[0]["severity"] == "bad"   # 80%
    assert sv.attention([dev(items=50, good_read=10)], CFG, [], {}, NOW, S) == []


def test_upload_stuck_needs_three_failing_packets():
    pk = [{"items": 10, "not_sent": 3}, {"items": 8, "not_sent": 8}, {"items": 5, "not_sent": 1}]
    a = sv.attention([dev()], CFG, [], {1: pk}, NOW, S)
    assert a[0]["rule"] == "Upload stuck" and a[0]["value"] == "12 items not sent in last 3 packets"
    assert sv.attention([dev()], CFG, [], {1: pk[:2]}, NOW, S) == []


def test_storage_and_app_stopped_and_ordering():
    a = sv.attention(
        [dev(c_usage=85.0, application_running=False, stopped_since=NOW - dt.timedelta(hours=2))],
        CFG,
        [],
        {},
        NOW,
        S,
    )
    assert [x["rule"] for x in a] == ["App stopped", "C: drive"]
    assert a[0]["severity"] == "bad" and a[1]["severity"] == "warn" and a[1]["value"] == "85.0%"
