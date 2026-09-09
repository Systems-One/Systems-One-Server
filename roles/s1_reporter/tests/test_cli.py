import unittest

import _bootstrap  # noqa: F401
from s1_reporter import cli

ENV = {"DB_HOST": "h", "DB_PORT": "1", "DB_NAME": "n", "DB_USER": "u", "DB_PASS": "p", "TEAMS_WEBHOOK_URL": "https://x"}


class FakeRunner:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def __getattr__(self, name):
        def job():
            self.calls.append(name)
            return self.ok if name != "sync_status" else (1, 0)
        return job


class FakeDb:
    def __init__(self):
        self.migrated = None

    def run_migrations(self, d):
        self.migrated = d
        return ["001.sql"]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCli(unittest.TestCase):
    def test_parse_valid_jobs(self):
        for job in cli.JOBS:
            self.assertEqual(cli.parse_args([job]).job, job)

    def test_unknown_job_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(["bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_dispatch_and_exit_codes(self):
        runner = FakeRunner(ok=True)
        rc = cli.main(["daily"], env=ENV, make_db=lambda s: FakeDb(), make_runner=lambda s, db: runner)
        self.assertEqual((rc, runner.calls), (0, ["daily"]))
        runner = FakeRunner(ok=False)
        rc = cli.main(["check-alerts"], env=ENV, make_db=lambda s: FakeDb(), make_runner=lambda s, db: runner)
        self.assertEqual((rc, runner.calls), (1, ["check_alerts"]))

    def test_migrate_runs_migrations_dir(self):
        db = FakeDb()
        rc = cli.main(["migrate"], env=ENV, make_db=lambda s: db, make_runner=lambda s, d: FakeRunner())
        self.assertEqual(rc, 0)
        self.assertTrue(db.migrated.endswith("migrations"))


if __name__ == "__main__":
    unittest.main()
