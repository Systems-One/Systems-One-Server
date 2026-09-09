"""python -m s1_reporter <job>. One job per process; exit 0 ok, 1 failure, 2 usage."""
import argparse
import os
import sys

from .config import load_settings

JOBS = ("sync-status", "check-alerts", "daily", "monthly", "stale-digest", "migrate")
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="s1_reporter", description="Systems One Teams reporter jobs")
    p.add_argument("job", choices=JOBS)
    return p.parse_args(argv)


def _make_db(settings):
    from .db import Database
    return Database(settings)


def _make_runner(settings, db):
    from .reports import Runner
    return Runner(settings, db)


def main(argv=None, env=None, make_db=None, make_runner=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings(os.environ if env is None else env)
    make_db = make_db or _make_db
    make_runner = make_runner or _make_runner

    with make_db(settings) as db:
        if args.job == "migrate":
            applied = db.run_migrations(MIGRATIONS_DIR)
            print(f"migrated: {applied}")
            return 0
        runner = make_runner(settings, db)
        job = getattr(runner, args.job.replace("-", "_"))
        result = job()
        if args.job == "sync-status":
            return 0
        return 0 if result else 1
