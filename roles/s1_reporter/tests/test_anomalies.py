import unittest
from datetime import date, datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import anomalies
from s1_reporter.customers import CustomerConfig
from s1_reporter.liveness import Device, DeviceState

NOW = datetime(2026, 9, 9, 7, 0)
CFG = CustomerConfig(customer="A", has_dimension=True, has_weight=True, has_hand_scan=True)


def row(machine="DIM1", items=1000, good=None, no_dim=0, hand=0, no_weight=0, day=date(2026, 9, 8)):
    good = items if good is None else good
    return {"machine_name": machine, "location": "JHB", "customer": "A", "report_date": day,
            "daily_items": items, "daily_good": good, "daily_no_dim": no_dim,
            "daily_hand_scanned": hand, "daily_no_weight": no_weight,
            "good_read_pct": round(good * 100.0 / items, 1) if items else None}


def offline(machine, minutes):
    d = Device(id=1, customer="A", machine_name=machine, location="JHB", last_seen=NOW - timedelta(minutes=minutes),
               created_at=NOW - timedelta(days=5), reporting_enabled=True, muted_until=None)
    return DeviceState(device=d, state="offline", last_seen=d.last_seen, minutes_ago=minutes)


class TestGoodRead(unittest.TestCase):
    def test_uses_device_threshold_from_table(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (77.5, 70.0)}
        out = anomalies.detect([row(good=750)], [], [], CFG, t)   # 75.0% < warn 77.5, > bad 70
        self.assertEqual(out, [("warn", "DIM1 @ JHB: good read 75.0% on 2026-09-08 (warn below 77.5%)")])

    def test_bad_when_below_bad(self):
        out = anomalies.detect([row(good=600)], [], [], CFG, {})   # 60% < cfg bad 90
        self.assertEqual(out[0][0], "bad")

    def test_small_volume_rows_ignored(self):
        self.assertEqual(anomalies.detect([row(items=50, good=10)], [], [], CFG, {}), [])


class TestCapabilityRules(unittest.TestCase):
    def test_no_dim_uses_table_then_config(self):
        out = anomalies.detect([row(no_dim=60)], [], [], CFG, {})   # 6% > cfg warn 5
        self.assertEqual(out[0], ("warn", "DIM1 @ JHB: no-dimension 6.0% on 2026-09-08 (warn above 5.0%)"))

    def test_no_dim_skipped_without_capability(self):
        cfg = CustomerConfig(customer="A", has_dimension=False)
        self.assertEqual(anomalies.detect([row(no_dim=600)], [], [], cfg, {}), [])

    def test_hand_scan_and_no_weight(self):
        out = anomalies.detect([row(hand=200, no_weight=60)], [], [], CFG, {})
        msgs = [m for _, m in out]
        self.assertIn("DIM1 @ JHB: hand-scanned 20.0% on 2026-09-08 (warn above 15.0%)", msgs)
        self.assertIn("DIM1 @ JHB: no-weight 6.0% on 2026-09-08 (warn above 5.0%)", msgs)


class TestStorageAndOffline(unittest.TestCase):
    def test_storage_levels(self):
        storage = [{"machine_name": "DIM1", "location": "JHB", "usage_percent": 91},
                   {"machine_name": "DIM2", "location": "JHB", "usage_percent": 85},
                   {"machine_name": "DIM3", "location": "JHB", "usage_percent": 50}]
        out = anomalies.detect([], storage, [], CFG, {})
        self.assertEqual([s for s, _ in out], ["bad", "warn"])
        self.assertIn("C: drive at 91%", out[0][1])

    def test_offline_states_listed_as_bad(self):
        out = anomalies.detect([], [], [offline("DIM1", 125)], CFG, {})
        self.assertEqual(out, [("bad", "DIM1 @ JHB: no data for 2h 5m (last seen 2026-09-09 04:55 UTC)")])


class TestFormat(unittest.TestCase):
    def test_icons(self):
        self.assertEqual(anomalies.format_lines([("bad", "x"), ("warn", "y")]), ["🔴 x", "⚠️ y"])


if __name__ == "__main__":
    unittest.main()
