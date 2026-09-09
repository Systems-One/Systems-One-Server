import unittest
from datetime import date

import _bootstrap  # noqa: F401
from s1_reporter import charts


def row(machine, day, items, pct):
    return {"machine_name": machine, "location": "JHB", "report_date": day, "daily_items": items, "good_read_pct": pct}


class TestPureHelpers(unittest.TestCase):
    def test_axis_bounds_include_lowest_warn_line(self):
        self.assertEqual(charts.goodread_axis_bounds([96.0, 99.0], [77.5, 93.0]), (72.5, 101.0))

    def test_axis_bounds_floor_at_zero(self):
        self.assertEqual(charts.goodread_axis_bounds([2.0], [1.0]), (0.0, 101.0))

    def test_axis_bounds_no_data(self):
        self.assertEqual(charts.goodread_axis_bounds([], []), (85.0, 101.0))

    def test_series_skips_empty_days(self):
        rows = [row("A", date(2026, 9, 1), 100, 99.0), row("A", date(2026, 9, 2), 0, None), row("B", date(2026, 9, 1), 5, 80.0)]
        s = charts.series_by_device(rows)
        self.assertEqual(s[("A", "JHB")], [(date(2026, 9, 1), 99.0)])
        self.assertEqual(s[("B", "JHB")], [(date(2026, 9, 1), 80.0)])

    def test_devices_with_data(self):
        rows = [row("A", date(2026, 9, 1), 0, None), row("B", date(2026, 9, 1), 5, 80.0)]
        self.assertEqual(charts.devices_with_data(rows), [("B", "JHB")])


if __name__ == "__main__":
    unittest.main()
