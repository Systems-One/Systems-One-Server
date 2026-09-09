import unittest

import _bootstrap  # noqa: F401
from s1_reporter.config import Settings, load_settings

REQUIRED = {
    "DB_HOST": "mssql", "DB_PORT": "1433", "DB_NAME": "RM", "DB_USER": "admin", "DB_PASS": "pw",
    "TEAMS_WEBHOOK_URL": "https://example.invalid/hook",
}


class TestLoadSettings(unittest.TestCase):
    def test_required_and_defaults(self):
        s = load_settings(REQUIRED)
        self.assertIsInstance(s, Settings)
        self.assertEqual(s.db_port, 1433)
        self.assertEqual(s.chart_dir, "/data/charts")
        self.assertEqual(s.chart_public_base_url, "")
        self.assertEqual(s.chart_retention_days, 14)
        self.assertEqual(s.offline_threshold_minutes, 30)
        self.assertEqual(s.stale_days, 14)
        self.assertEqual(s.tz_offset_hours, 2)
        self.assertEqual(s.upload_alert_consecutive, 3)
        self.assertEqual(s.upload_lookback_packets, 6)
        self.assertEqual(s.offline_state_file, "/data/offline_state.json")
        self.assertEqual(s.upload_state_file, "/data/upload_state.json")

    def test_overrides(self):
        env = dict(REQUIRED, STALE_DAYS="30", REPORT_TZ_OFFSET_HOURS="0", CHART_PUBLIC_BASE_URL="https://c.example/")
        s = load_settings(env)
        self.assertEqual(s.stale_days, 30)
        self.assertEqual(s.tz_offset_hours, 0)
        self.assertEqual(s.chart_public_base_url, "https://c.example/")

    def test_missing_required_names_variable(self):
        env = dict(REQUIRED)
        del env["TEAMS_WEBHOOK_URL"]
        with self.assertRaises(SystemExit) as cm:
            load_settings(env)
        self.assertIn("TEAMS_WEBHOOK_URL", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
