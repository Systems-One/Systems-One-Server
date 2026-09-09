import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import upload

T0 = datetime(2026, 9, 9, 7, 0)


def pk(name, rn, items, not_sent, loc="JHB"):
    return {"machine_name": name, "location": loc, "customer": "A",
            "ts_datetime": T0 - timedelta(minutes=15 * rn), "total_items": items, "not_sent": not_sent, "rn": rn}


class TestDetect(unittest.TestCase):
    def test_flags_three_consecutive_failing_packets(self):
        rows = [pk("D", 1, 10, 3), pk("D", 2, 12, 4), pk("D", 3, 9, 1), pk("D", 4, 10, 0)]
        out = upload.detect_upload_failures(rows, consecutive=3)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["total_not_sent"], 8)
        self.assertEqual(out[0]["latest_ts"], T0 - timedelta(minutes=15))

    def test_idle_packet_breaks_the_run(self):
        rows = [pk("D", 1, 10, 3), pk("D", 2, 0, 4), pk("D", 3, 9, 1)]
        self.assertEqual(upload.detect_upload_failures(rows, 3), [])

    def test_too_few_packets(self):
        self.assertEqual(upload.detect_upload_failures([pk("D", 1, 10, 3), pk("D", 2, 10, 3)], 3), [])

    def test_sorted_by_backlog_desc(self):
        rows = [pk("S", 1, 10, 1), pk("S", 2, 10, 1), pk("S", 3, 10, 1),
                pk("B", 1, 10, 9, "CPT"), pk("B", 2, 10, 9, "CPT"), pk("B", 3, 10, 9, "CPT")]
        self.assertEqual([d["machine_name"] for d in upload.detect_upload_failures(rows, 3)], ["B", "S"])


class TestFetch(unittest.TestCase):
    def test_query_filters_disabled_devices_and_uses_lookback_param(self):
        captured = {}

        def q(sql, params=None):
            captured["sql"], captured["params"] = sql, params
            return []
        upload.fetch_recent_packets(q, 6)
        self.assertIn("reporting_enabled = 1", captured["sql"])
        self.assertEqual(captured["params"], (6,))


if __name__ == "__main__":
    unittest.main()
