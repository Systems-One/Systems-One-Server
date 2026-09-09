import unittest

import _bootstrap  # noqa: F401
from s1_reporter.customers import CustomerConfig
from s1_reporter.thresholds import load_thresholds, lookup

CFG = CustomerConfig(customer="A", good_read_warn_pct=95, good_read_bad_pct=90,
                     no_dim_warn_pct=5, no_dim_bad_pct=10)


class TestThresholds(unittest.TestCase):
    def test_load_keys_and_floats(self):
        rows = [{"customer": "A", "machine_name": "DIM1", "location": "JHB", "metric": "good_read_pct",
                 "warn_value": 77.5, "bad_value": 70.0},
                {"customer": "A", "machine_name": None, "location": None, "metric": "no_dim_pct",
                 "warn_value": 3.0, "bad_value": None}]
        t = load_thresholds(lambda sql, params=None: rows)
        self.assertEqual(t[("A", "DIM1", "JHB", "good_read_pct")], (77.5, 70.0))
        self.assertEqual(t[("A", None, None, "no_dim_pct")], (3.0, None))

    def test_device_row_wins(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (77.5, 70.0), ("A", None, None, "good_read_pct"): (93.0, 88.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM1", "JHB", "good_read_pct"), (77.5, 70.0))

    def test_customer_row_when_no_device_row(self):
        t = {("A", None, None, "good_read_pct"): (93.0, 88.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM9", "CPT", "good_read_pct"), (93.0, 88.0))

    def test_config_fallback(self):
        self.assertEqual(lookup({}, CFG, "A", "DIM9", "CPT", "good_read_pct"), (95.0, 90.0))
        self.assertEqual(lookup({}, CFG, "A", "DIM9", "CPT", "no_dim_pct"), (5.0, 10.0))

    def test_row_with_null_warn_falls_through(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (None, 70.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM1", "JHB", "good_read_pct"), (95.0, 90.0))


if __name__ == "__main__":
    unittest.main()
