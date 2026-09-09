import datetime as dt
import rates

def row(ts, items, good, **k):
    r = {"bucket_utc": ts, "items": items, "good_read": good, "no_read": items - good, "no_dimension": 0, "no_weight": 0,
         "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 0, "rows": 12}
    r.update(k); return r

def test_fill_marks_nodata_and_low_volume():
    starts = [dt.datetime(2026, 9, 1), dt.datetime(2026, 9, 2), dt.datetime(2026, 9, 3)]
    rows = [row(dt.datetime(2026, 9, 1), 200, 190), row(dt.datetime(2026, 9, 3), 40, 20)]
    b = rates.fill_buckets(rows, starts, 100)
    assert [x["nodata"] for x in b] == [False, True, False]
    assert b[0]["rates"]["good_read_pct"] == 95.0 and b[0]["low_volume"] is False
    assert b[2]["low_volume"] is True and b[2]["rates"]["good_read_pct"] == 50.0
    assert b[1]["items"] == 0 and b[1]["rates"]["good_read_pct"] is None
    assert b[0]["ts"] == "2026-09-01T00:00:00Z"

def test_rate_zero_items_is_none():
    assert rates.rate(5, 0) is None and rates.rate(1, 4) == 25.0

def test_summary_excludes_low_volume_from_good_read():
    starts = [dt.datetime(2026, 9, d) for d in (1, 2, 3)]
    b = rates.fill_buckets([row(starts[0], 1000, 900), row(starts[1], 50, 10), row(starts[2], 400, 400)], starts, 100)
    s = rates.summary(b, [10, 300, 2], "hour")
    assert s["items"] == {"max": 1000, "min": 50, "avg": 483.3}
    assert s["good_read_pct"] == {"max": 100.0, "min": 90.0, "avg": 95.0}
    assert s["per_unit"] == {"max": 300, "min": 2, "avg": 104.0, "label": "hour"}

def test_summary_empty():
    s = rates.summary([], [], "hour")
    assert s["items"] == {"max": None, "min": None, "avg": None}

def test_totals_and_partition():
    starts = [dt.datetime(2026, 9, 1)]
    b = rates.fill_buckets([row(starts[0], 100, 80, hand_scanned=15)], starts, 10)
    t = rates.totals(b)
    assert t["items"] == 100 and t["no_read"] == 20 and t["hand_scanned"] == 15
    assert rates.partition(t, True) == [{"name": "Good read", "value": 80}, {"name": "No read, recovered by hand scan", "value": 15}, {"name": "No read, not recovered", "value": 5}]
    assert rates.partition(t, False) == [{"name": "Good read", "value": 80}, {"name": "No read", "value": 20}]

def test_partition_clamps_hand_scan_to_no_read():
    t = {"items": 100, "good_read": 90, "no_read": 10, "hand_scanned": 25}
    assert rates.partition(t, True)[1]["value"] == 10 and rates.partition(t, True)[2]["value"] == 0

def test_applicable_rates_gating():
    keys = [r["key"] for r in rates.applicable_rates({"has_dimension": True, "has_weight": False, "has_hand_scan": True})]
    assert keys == ["good_read_pct", "no_dim_pct", "hand_scan_pct", "not_sent_pct"]
