import unittest

import _bootstrap  # noqa: F401
from s1_reporter.customers import CustomerConfig, config_for, load_customer_configs


def fake_query(rows):
    def q(sql, params=None):
        assert "customer_config" in sql
        return rows
    return q


class TestCustomers(unittest.TestCase):
    def test_loads_rows_into_dataclasses(self):
        rows = [{"customer": "MADIBANA", "has_dimension": True, "has_weight": True, "has_hand_scan": True,
                 "hand_scan_warn_pct": 15, "no_weight_warn_pct": 5, "storage_warn_pct": 80, "storage_bad_pct": 90,
                 "good_read_warn_pct": 95, "good_read_bad_pct": 90, "no_dim_warn_pct": 5, "no_dim_bad_pct": 10,
                 "reports_enabled": True}]
        cfgs = load_customer_configs(fake_query(rows))
        self.assertEqual(set(cfgs), {"MADIBANA"})
        self.assertTrue(cfgs["MADIBANA"].has_weight)
        self.assertEqual(cfgs["MADIBANA"].storage_bad_pct, 90.0)

    def test_unknown_customer_gets_defaults(self):
        cfg = config_for({}, "NEWCO")
        self.assertEqual(cfg, CustomerConfig(customer="NEWCO"))
        self.assertTrue(cfg.has_dimension)
        self.assertFalse(cfg.has_weight)
        self.assertEqual(cfg.good_read_warn_pct, 95.0)
        self.assertTrue(cfg.reports_enabled)


if __name__ == "__main__":
    unittest.main()
