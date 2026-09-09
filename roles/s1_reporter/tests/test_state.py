import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter.state import AlertState

NOW = datetime(2026, 9, 9, 7, 0)


class TestAlertState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "offline_state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_or_corrupt_file_is_empty(self):
        self.assertEqual(AlertState(self.path).load(), {})
        with open(self.path, "w") as fh:
            fh.write("{not json")
        self.assertEqual(AlertState(self.path).load(), {})

    def test_diff_new_unchanged_recovered(self):
        s = AlertState(self.path)
        first = s.diff({"A@X": {"machine_name": "A", "location": "X"}}, NOW)
        self.assertEqual([d["machine_name"] for d in first.new], ["A"])
        self.assertEqual(first.pending["A@X"]["alerted_at"], NOW.isoformat())
        s.commit(first.pending)

        later = NOW + timedelta(minutes=40)
        second = s.diff({"B@Y": {"machine_name": "B", "location": "Y"}}, later)
        self.assertEqual([d["machine_name"] for d in second.new], ["B"])
        self.assertEqual([d["machine_name"] for d in second.recovered], ["A"])
        self.assertEqual(second.recovered[0]["downtime_minutes"], 40)
        self.assertEqual(second.unchanged, [])

    def test_alerted_at_is_preserved_for_unchanged(self):
        s = AlertState(self.path)
        s.commit(s.diff({"A@X": {"machine_name": "A", "location": "X"}}, NOW).pending)
        d = s.diff({"A@X": {"machine_name": "A", "location": "X"}}, NOW + timedelta(hours=2))
        self.assertEqual(d.new, [])
        self.assertEqual(len(d.unchanged), 1)
        self.assertEqual(d.pending["A@X"]["alerted_at"], NOW.isoformat())

    def test_uncommitted_diff_does_not_touch_disk(self):
        s = AlertState(self.path)
        s.diff({"A@X": {"machine_name": "A", "location": "X"}}, NOW)
        self.assertFalse(os.path.exists(self.path))

    def test_commit_writes_json(self):
        s = AlertState(self.path)
        s.commit({"A@X": {"machine_name": "A", "alerted_at": NOW.isoformat()}})
        with open(self.path) as fh:
            self.assertEqual(json.load(fh)["A@X"]["machine_name"], "A")


if __name__ == "__main__":
    unittest.main()
