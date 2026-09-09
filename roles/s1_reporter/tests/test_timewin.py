import unittest
from datetime import date, datetime

import _bootstrap  # noqa: F401
from s1_reporter import timewin


class TestTimeWindows(unittest.TestCase):
    def test_local_date_crosses_midnight(self):
        # 23:30 UTC on the 8th is 01:30 SAST on the 9th
        self.assertEqual(timewin.local_date(datetime(2026, 9, 8, 23, 30), 2), date(2026, 9, 9))

    def test_daily_window_ends_yesterday(self):
        start, end = timewin.daily_window(datetime(2026, 9, 9, 4, 0), 2, days=7)
        self.assertEqual(end, date(2026, 9, 8))
        self.assertEqual(start, date(2026, 9, 2))

    def test_previous_month_from_first(self):
        start, end = timewin.previous_month(datetime(2026, 9, 1, 4, 30), 2)
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_previous_month_january(self):
        start, end = timewin.previous_month(datetime(2027, 1, 1, 4, 30), 2)
        self.assertEqual((start, end), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_utc_bounds_shift_by_offset(self):
        s, e = timewin.utc_bounds(date(2026, 9, 8), date(2026, 9, 8), 2)
        self.assertEqual(s, datetime(2026, 9, 7, 22, 0))
        self.assertEqual(e, datetime(2026, 9, 8, 22, 0))


if __name__ == "__main__":
    unittest.main()
