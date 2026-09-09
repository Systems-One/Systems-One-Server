import unittest
from datetime import date, datetime

import _bootstrap  # noqa: F401
from s1_reporter import queries


class Capture:
    def __init__(self):
        self.sql = None
        self.params = None

    def __call__(self, sql, params=None):
        self.sql, self.params = sql, params
        return []


class TestQueries(unittest.TestCase):
    def test_daily_trend_is_parameterised_and_local_day_grouped(self):
        q = Capture()
        queries.daily_trend(q, "PEP'S", date(2026, 9, 2), date(2026, 9, 8), 2)
        self.assertNotIn("PEP'S", q.sql)
        self.assertEqual(q.params, (2, "PEP'S", datetime(2026, 9, 1, 22, 0), datetime(2026, 9, 8, 22, 0), 2))
        self.assertIn("DATEADD(hour, %s, ds.ts_datetime)", q.sql)
        self.assertIn("d.reporting_enabled = 1", q.sql)

    def test_device_summary_and_hourly_filter_enabled(self):
        for fn in (queries.device_summary, queries.hourly_pattern):
            q = Capture()
            fn(q, "A", date(2026, 9, 8), date(2026, 9, 8), 2)
            self.assertIn("d.reporting_enabled = 1", q.sql)
            self.assertIn("%s", q.sql)

    def test_storage_and_customers(self):
        q = Capture()
        queries.storage(q, "A")
        self.assertEqual(q.params, ("A",))
        self.assertIn("drive = 'C:'", q.sql)
        q = Capture()
        queries.customers_with_reports(q)
        self.assertIn("reports_enabled = 1", q.sql)


if __name__ == "__main__":
    unittest.main()
