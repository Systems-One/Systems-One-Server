import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINES = os.path.join(HERE, "..", "files", "compute_baselines.py")
MIGRATIONS = os.path.join(HERE, "..", "files", "migrations")


def _load():
    installed = False
    if "pymssql" not in sys.modules:
        sys.modules["pymssql"] = types.ModuleType("pymssql")
        installed = True
    try:
        loader = importlib.machinery.SourceFileLoader("s1_baselines_mig", BASELINES)
        spec = importlib.util.spec_from_loader("s1_baselines_mig", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        if installed:
            sys.modules.pop("pymssql", None)


baselines = _load()


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(sql.strip())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self):
        self.executed = []
        self.commits = 0

    def cursor(self, **kw):
        return FakeCursor(self.executed)

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSplitBatches(unittest.TestCase):
    def test_splits_on_go_lines_only(self):
        sql = "CREATE TABLE a (id INT);\nGO\n\nCREATE INDEX i ON a(id);\ngo\n"
        self.assertEqual(baselines.split_batches(sql),
                         ["CREATE TABLE a (id INT);", "CREATE INDEX i ON a(id);"])

    def test_go_inside_a_line_is_not_a_separator(self):
        sql = "SELECT 'GO' AS word;\n"
        self.assertEqual(baselines.split_batches(sql), ["SELECT 'GO' AS word;"])


class TestRunMigrations(unittest.TestCase):
    def test_runs_files_in_name_order_and_commits_each(self):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "002_second.sql"), "w") as f:
                f.write("SECOND;\n")
            with open(os.path.join(d, "001_first.sql"), "w") as f:
                f.write("FIRST_A;\nGO\nFIRST_B;\n")
            baselines.run_migrations({}, migrations_dir=d, connect=lambda cfg: conn)
        self.assertEqual(conn.executed, ["FIRST_A;", "FIRST_B;", "SECOND;"])
        self.assertEqual(conn.commits, 2)

    def test_shipped_migration_is_idempotent_ddl(self):
        with open(os.path.join(MIGRATIONS, "001_alert_thresholds.sql"), encoding="utf-8") as f:
            sql = f.read()
        self.assertIn("IF OBJECT_ID(N'dbo.alert_thresholds', N'U') IS NULL", sql)
        for col in ("warn_value", "bad_value", "baseline_mean", "baseline_samples",
                    "lookback_days", "last_computed", "is_override", "updated_at"):
            self.assertIn(col, sql)


if __name__ == "__main__":
    unittest.main()
