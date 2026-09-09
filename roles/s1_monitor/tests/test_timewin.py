import datetime as dt
import timewin as tw

NOW = dt.datetime(2026, 9, 9, 11, 33, 15)   # UTC = 13:33 SAST

def test_presets_exist():
    assert set(tw.PRESETS) == {"24h", "48h", "7d", "30d", "90d"}
    assert tw.PRESETS["24h"].bucket_seconds == 1800 and tw.PRESETS["48h"].bucket_seconds == 3600
    assert all(tw.PRESETS[k].bucket_seconds == 86400 and tw.PRESETS[k].daily for k in ("7d", "30d", "90d"))

def test_local_midnight_is_utc_2200_previous_day():
    assert tw.local_midnight(NOW, 2) == dt.datetime(2026, 9, 8, 22, 0, 0)

def test_daily_window_7d():
    f, t = tw.window(tw.PRESETS["7d"], NOW, 2)
    assert f == dt.datetime(2026, 9, 2, 22, 0) and t == dt.datetime(2026, 9, 9, 22, 0)
    assert len(tw.bucket_starts(f, t, 86400)) == 7

def test_detail_window_24h_aligned_to_bucket():
    f, t = tw.window(tw.PRESETS["24h"], NOW, 2)
    assert t == dt.datetime(2026, 9, 9, 11, 30) and (t - f) == dt.timedelta(hours=24) - dt.timedelta(minutes=30)
    assert len(tw.bucket_starts(f, t + dt.timedelta(seconds=1800), 1800)) == 48

def test_week_monday():
    assert tw.week_monday(dt.date(2026, 9, 9)) == dt.date(2026, 9, 7)   # Wednesday -> Monday
    assert tw.week_monday(dt.date(2026, 9, 7)) == dt.date(2026, 9, 7)

def test_min_items_for():
    class S: min_items_day=100; min_items_hour=30; min_items_half_hour=15
    assert tw.min_items_for(tw.PRESETS["90d"], S) == 100
    assert tw.min_items_for(tw.PRESETS["48h"], S) == 30
    assert tw.min_items_for(tw.PRESETS["24h"], S) == 15
