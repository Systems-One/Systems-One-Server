import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINES = os.path.join(HERE, "..", "files", "compute_baselines.py")


def _load():
    installed = False
    if "pymssql" not in sys.modules:
        sys.modules["pymssql"] = types.ModuleType("pymssql")
        installed = True
    try:
        loader = importlib.machinery.SourceFileLoader("s1_baselines_diff", BASELINES)
        spec = importlib.util.spec_from_loader("s1_baselines_diff", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        if installed:
            sys.modules.pop("pymssql", None)


baselines = _load()


def _row(customer, machine, loc, metric, warn, bad):
    return {"customer": customer, "machine_name": machine, "location": loc,
            "metric": metric, "warn_value": warn, "bad_value": bad}


class TestFormatChangeLines(unittest.TestCase):
    def test_new_row_is_reported_as_new(self):
        lines, unchanged = baselines.format_change_lines({}, [_row("A", "DIM1", "JHB", "good_read_pct", 77.5, 70.0)])
        self.assertEqual(unchanged, 0)
        self.assertEqual(lines, ["A / DIM1 / JHB / good_read_pct: NEW warn 77.5000, bad 70.0000"])

    def test_changed_row_shows_old_and_new(self):
        existing = {("A", "DIM1", "JHB", "good_read_pct"): (85.0063, 81.594)}
        lines, unchanged = baselines.format_change_lines(existing, [_row("A", "DIM1", "JHB", "good_read_pct", 77.5458, 76.5458)])
        self.assertEqual(unchanged, 0)
        self.assertEqual(lines, ["A / DIM1 / JHB / good_read_pct: warn 85.0063 -> 77.5458, bad 81.5940 -> 76.5458"])

    def test_unchanged_row_is_counted_not_printed(self):
        existing = {("A", "DIM1", "JHB", "no_dim_pct"): (3.0, 5.0)}
        lines, unchanged = baselines.format_change_lines(existing, [_row("A", "DIM1", "JHB", "no_dim_pct", 3.0, 5.0)])
        self.assertEqual(lines, [])
        self.assertEqual(unchanged, 1)


if __name__ == "__main__":
    unittest.main()
