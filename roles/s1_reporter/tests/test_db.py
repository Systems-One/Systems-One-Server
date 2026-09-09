import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from s1_reporter import db

MIGRATIONS = os.path.join(_bootstrap.APP, "migrations")


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def execute(self, sql, params=None):
        self.owner.calls.append((sql.strip(), params))
        self.rowcount = 1

    def executemany(self, sql, seq):
        self.owner.calls.append((sql.strip(), list(seq)))

    def fetchall(self):
        return [{"n": 1}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.closed = False

    def cursor(self, as_dict=False):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class TestSplitBatches(unittest.TestCase):
    def test_splits_on_go(self):
        self.assertEqual(db.split_batches("A;\nGO\nB;\ngo\n"), ["A;", "B;"])


class TestDatabase(unittest.TestCase):
    def test_query_and_execute_pass_params(self):
        conn = FakeConn()
        d = db.Database(None, connect=lambda s: conn)
        self.assertEqual(d.query("SELECT %s", ("x",)), [{"n": 1}])
        d.execute("UPDATE t SET a=%s", (1,))
        self.assertEqual(conn.calls[0], ("SELECT %s", ("x",)))
        self.assertEqual(conn.calls[1], ("UPDATE t SET a=%s", (1,)))
        self.assertEqual(conn.commits, 1)

    def test_run_migrations_in_order_committing_each(self):
        conn = FakeConn()
        d = db.Database(None, connect=lambda s: conn)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "002_b.sql"), "w") as fh:
                fh.write("B;\n")
            with open(os.path.join(tmp, "001_a.sql"), "w") as fh:
                fh.write("A1;\nGO\nA2;\n")
            applied = d.run_migrations(tmp)
        self.assertEqual(applied, ["001_a.sql", "002_b.sql"])
        self.assertEqual([c[0] for c in conn.calls], ["A1;", "A2;", "B;"])
        self.assertEqual(conn.commits, 2)

    def test_context_manager_closes(self):
        conn = FakeConn()
        with db.Database(None, connect=lambda s: conn):
            pass
        self.assertTrue(conn.closed)


class TestShippedMigrations(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(MIGRATIONS, name), encoding="utf-8") as fh:
            return fh.read()

    def test_customer_config_is_idempotent_and_seeds_known_customers(self):
        sql = self._read("001_customer_config.sql")
        self.assertIn("IF OBJECT_ID(N'dbo.customer_config', N'U') IS NULL", sql)
        for c in ("PEPKOR", "MADIBANA", "PEP", "SNOWSOFT"):
            self.assertIn(f"N'{c}'", sql)
        self.assertIn("INSERT INTO dbo.customer_config (customer)", sql)  # backfill from devices

    def test_device_flags_adds_columns_and_marks_standby(self):
        sql = self._read("002_device_flags.sql")
        self.assertIn("reporting_enabled", sql)
        self.assertIn("muted_until", sql)
        self.assertIn("N'DIM2'", sql)
        self.assertIn("N'JBH'", sql)


if __name__ == "__main__":
    unittest.main()
