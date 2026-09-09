import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter.config import Settings
from s1_reporter.reports import Runner

NOW = datetime(2026, 9, 9, 4, 0)   # 06:00 SAST
D8 = date(2026, 9, 8)


class FakeDb:
    """Routes SQL by keyword to canned rows and records writes."""
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def query(self, sql, params=None):
        # Customer-scoped queries carry the customer in params; "EMPTY" has no data.
        if params and "EMPTY" in params:
            return []
        for key, val in self.rows.items():
            if key in sql:
                return val
        return []

    def execute(self, sql, params=None):
        self.writes.append((sql, params))
        return 1

    def executemany(self, sql, seq):
        self.writes.append((sql, list(seq)))


def device_row(id_, customer, machine, loc, last_seen, created=None):
    return {"id": id_, "customer": customer, "machine_name": machine, "location": loc, "created_at": created or (NOW - timedelta(days=100)),
            "reporting_enabled": True, "muted_until": None, "last_seen": last_seen}


def trend_row(customer, machine, loc, items, good):
    return {"machine_name": machine, "location": loc, "customer": customer, "report_date": D8, "daily_items": items,
            "daily_good": good, "daily_no_read": items - good, "daily_no_dim": 0, "daily_hand_scanned": 0,
            "daily_no_weight": 0, "good_read_pct": round(good * 100.0 / items, 1)}


def summary_row(machine, loc, items, good):
    return {"machine_name": machine, "location": loc, "customer": "A", "total_items": items, "good_reads": good, "no_reads": items - good,
            "no_dimensions": 0, "not_sent": 0, "hand_scanned": 0, "no_weight": 0, "good_read_pct": good * 100.0 / items}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(db_host="h", db_port=1, db_name="n", db_user="u", db_pass="p",
                                 teams_webhook_url="https://hook", chart_dir=os.path.join(self.tmp.name, "charts"),
                                 chart_public_base_url="https://charts.example",
                                 offline_state_file=os.path.join(self.tmp.name, "off.json"),
                                 upload_state_file=os.path.join(self.tmp.name, "up.json"))
        self.posted = []
        self.render = {"volume": lambda *a, **k: b"png", "goodread": lambda *a, **k: b"png", "hourly": lambda *a, **k: b"png"}

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, rows, post_ok=True):
        def post(url, card):
            self.posted.append(card)
            return post_ok
        return Runner(self.settings, FakeDb(rows), now_utc=NOW, post=post, render=self.render)


class TestSyncStatus(Base):
    def test_merges_only_enabled_devices(self):
        db_rows = {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW - timedelta(minutes=5)),
                                                    device_row(2, "A", "D2", "JHB", NOW - timedelta(days=30))]}
        r = self.runner(db_rows)
        self.assertEqual(r.sync_status(), (1, 1))
        self.assertEqual(len(r.db.writes), 1)


class TestCheckAlerts(Base):
    def _rows(self):
        return {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "OFF", "JHB", NOW - timedelta(hours=2)),
                                                 device_row(2, "A", "STALE", "DUR", NOW - timedelta(days=60))],
                "ROW_NUMBER()": []}

    def test_new_offline_alert_commits_state_after_success(self):
        r = self.runner(self._rows())
        self.assertTrue(r.check_alerts())
        self.assertEqual(len(self.posted), 1)
        self.assertIn("OFF", str(self.posted[0]))
        self.assertNotIn("STALE", str(self.posted[0]))
        self.assertTrue(os.path.exists(self.settings.offline_state_file))

    def test_failed_post_leaves_state_uncommitted(self):
        r = self.runner(self._rows(), post_ok=False)
        self.assertFalse(r.check_alerts())
        self.assertFalse(os.path.exists(self.settings.offline_state_file))

    def test_second_run_is_quiet(self):
        r = self.runner(self._rows())
        r.check_alerts()
        self.posted.clear()
        self.assertTrue(r.check_alerts())
        self.assertEqual(self.posted, [])


class TestDaily(Base):
    def test_posts_only_customers_with_data(self):
        rows = {"customer_config WHERE reports_enabled": [{"customer": "A"}, {"customer": "EMPTY"}],
                "FROM dbo.customer_config": [],
                "FROM dbo.alert_thresholds": [],
                "FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW - timedelta(minutes=5))],
                "AS report_date": [trend_row("A", "D1", "JHB", 1000, 990)],
                "AS good_reads": [summary_row("D1", "JHB", 1000, 990)],
                "AS hour_of_day": [{"hour_of_day": 9, "total_items": 500}],
                "device_storage_status": []}
        r = self.runner(rows)
        self.assertTrue(r.daily())
        self.assertEqual(len(self.posted), 1)
        text = str(self.posted[0])
        self.assertIn("🏢 A", text)
        self.assertIn("Yesterday", text)
        self.assertIn("https://charts.example/", text)

    def test_daily_with_no_customers_posts_nothing(self):
        r = self.runner({"customer_config WHERE reports_enabled": []})
        self.assertTrue(r.daily())
        self.assertEqual(self.posted, [])


class TestStaleDigest(Base):
    def test_posts_when_stale_exists(self):
        rows = {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "PEP AFRICA", "STATIC1", "DUR", datetime(2026, 7, 8, 7, 30))]}
        r = self.runner(rows)
        self.assertTrue(r.stale_digest())
        self.assertIn("STATIC1", str(self.posted[0]))

    def test_silent_when_none(self):
        r = self.runner({"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW)]})
        self.assertTrue(r.stale_digest())
        self.assertEqual(self.posted, [])


if __name__ == "__main__":
    unittest.main()
