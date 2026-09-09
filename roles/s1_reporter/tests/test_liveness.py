import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import liveness
from s1_reporter.liveness import Device

NOW = datetime(2026, 9, 9, 7, 0)


def dev(name, last_seen_min_ago=None, created_days_ago=100, enabled=True, muted_until=None, loc="JHB"):
    last = NOW - timedelta(minutes=last_seen_min_ago) if last_seen_min_ago is not None else None
    return Device(id=1, customer="A", machine_name=name, location=loc, last_seen=last,
                  created_at=NOW - timedelta(days=created_days_ago), reporting_enabled=enabled,
                  muted_until=muted_until)


class TestClassify(unittest.TestCase):
    def _one(self, d):
        return liveness.classify([d], NOW, offline_threshold_min=30, stale_days=14)[0]

    def test_online(self):
        self.assertEqual(self._one(dev("D", 5)).state, "online")

    def test_offline_at_threshold(self):
        s = self._one(dev("D", 30))
        self.assertEqual(s.state, "offline")
        self.assertEqual(s.minutes_ago, 30)

    def test_stale_after_stale_days(self):
        self.assertEqual(self._one(dev("D", 14 * 24 * 60)).state, "stale")

    def test_never_reported_uses_created_at(self):
        s = self._one(dev("D", None, created_days_ago=2))
        self.assertEqual(s.state, "never")
        self.assertEqual(s.last_seen, NOW - timedelta(days=2))

    def test_never_reported_and_old_is_stale(self):
        self.assertEqual(self._one(dev("D", None, created_days_ago=60)).state, "stale")

    def test_disabled_devices_are_dropped(self):
        self.assertEqual(liveness.classify([dev("D", 5, enabled=False)], NOW, 30, 14), [])


class TestSelections(unittest.TestCase):
    def test_alertable_excludes_stale_and_muted(self):
        states = liveness.classify([
            dev("OFF", 60), dev("MUTED", 60, muted_until=NOW + timedelta(hours=1), loc="CPT"),
            dev("EXPIRED", 60, muted_until=NOW - timedelta(hours=1), loc="DUR"),
            dev("STALE", 30 * 24 * 60, loc="PE"), dev("ON", 1, loc="BFN"),
        ], NOW, 30, 14)
        names = sorted(s.device.machine_name for s in liveness.alertable_offline(states, NOW))
        self.assertEqual(names, ["EXPIRED", "OFF"])

    def test_stale_devices(self):
        states = liveness.classify([dev("STALE", 30 * 24 * 60), dev("ON", 1, loc="CPT")], NOW, 30, 14)
        self.assertEqual([s.device.machine_name for s in liveness.stale_devices(states)], ["STALE"])

    def test_key(self):
        self.assertEqual(liveness.key(dev("DIM1", 1, loc="JHB")), "DIM1@JHB")


if __name__ == "__main__":
    unittest.main()
