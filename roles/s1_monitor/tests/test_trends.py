import datetime as dt
import trends as tr


def rows_for(days_back, items, good):
    today = dt.date(2026, 9, 9)  # Wednesday
    return [{"day": today - dt.timedelta(days=i), "items": items, "good_read": good, "no_read": items - good, "no_dimension": 0, "no_weight": 0, "hand_scanned": 0, "not_sent": 0, "more_than_1_item": 0} for i in range(days_back)]


def test_daily_series_flags_low_volume():
    s = tr.daily_series(rows_for(2, 50, 40), "good_read_pct", 100)
    assert s[0]["low_volume"] is True and s[0]["value"] == 80.0


def test_wow_good_read_median_and_delta():
    rows = rows_for(40, 1000, 950)
    for r in rows[:3]:   # this week (Mon 7, Tue 8, Wed 9) at 90%
        r["good_read"] = 900; r["no_read"] = 100
    w = tr.week_over_week(rows, "good_read_pct", dt.date(2026, 9, 9), dt.datetime(2026, 9, 9, 13, 0), 100)
    assert w["this_week"] == 90.0 and w["prev4_median"] == 95.0 and w["delta_abs"] == -5.0 and len(w["last5"]) == 5


def test_wow_items_compares_same_point_in_week():
    rows = rows_for(40, 1000, 950)
    w = tr.week_over_week(rows, "items", dt.date(2026, 9, 9), dt.datetime(2026, 9, 9, 13, 0), 100)
    assert w["this_week"] == 3000 and w["prev4_median"] == 3000 and w["delta_pct"] == 0.0


def test_wow_with_no_previous_weeks():
    w = tr.week_over_week(rows_for(3, 1000, 950), "good_read_pct", dt.date(2026, 9, 9), dt.datetime(2026, 9, 9, 13, 0), 100)
    assert w["prev4_median"] is None and w["delta_abs"] is None
