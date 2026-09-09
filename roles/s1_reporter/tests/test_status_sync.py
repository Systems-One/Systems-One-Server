import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import status_sync
from s1_reporter.liveness import Device, DeviceState

NOW = datetime(2026, 9, 9, 7, 0)


def st(dev_id, state, minutes):
    last = NOW - timedelta(minutes=minutes)
    d = Device(id=dev_id, customer="A", machine_name=f"D{dev_id}", location="JHB", last_seen=last,
               created_at=NOW - timedelta(days=9), reporting_enabled=True, muted_until=None)
    return DeviceState(device=d, state=state, last_seen=last, minutes_ago=minutes)


class TestStatusSync(unittest.TestCase):
    def test_rows_and_counts(self):
        calls = []
        counts = status_sync.sync(lambda sql, rows: calls.append((sql, rows)),
                                  [st(1, "online", 1), st(2, "offline", 45), st(3, "stale", 30000), st(4, "never", 60)])
        self.assertEqual(counts, (1, 3))
        sql, rows = calls[0]
        self.assertIs(sql, status_sync.MERGE_SQL)
        self.assertEqual(rows[0], (1, "online", NOW - timedelta(minutes=1), NOW - timedelta(minutes=1), None))
        self.assertEqual(rows[1][1], "offline")
        self.assertEqual(rows[1][4], NOW - timedelta(minutes=45))  # offline_since candidate
        self.assertEqual(rows[2][1], "offline")                    # stale writes as offline
        self.assertEqual(rows[3][1], "offline")                    # never writes as offline

    def test_merge_preserves_existing_offline_since(self):
        self.assertIn("COALESCE(t.offline_since, s.offline_since)", status_sync.MERGE_SQL)
        self.assertIn("WHEN NOT MATCHED", status_sync.MERGE_SQL)

    def test_no_states_no_call(self):
        calls = []
        self.assertEqual(status_sync.sync(lambda s, r: calls.append(1), []), (0, 0))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
