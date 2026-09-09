import os
import unittest

import yaml

ROLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _read(rel):
    with open(os.path.join(ROLE, rel), encoding="utf-8") as fh:
        return fh.read()


class TestRoleFiles(unittest.TestCase):
    def test_yaml_parses(self):
        for rel in ("defaults/main.yml", "tasks/main.yml"):
            self.assertIsNotNone(yaml.safe_load(_read(rel)), rel)

    def test_defaults(self):
        d = yaml.safe_load(_read("defaults/main.yml"))
        self.assertIn("mssql_rm_admin_login", d["s1_reporter_db_user"])
        self.assertEqual(d["s1_reporter_stale_days"], 14)
        self.assertEqual(d["s1_reporter_tz_offset_hours"], 2)
        self.assertEqual(d["s1_reporter_offline_threshold_minutes"], 30)
        for k in ("s1_reporter_cron_sync_status", "s1_reporter_cron_check_alerts", "s1_reporter_cron_daily",
                  "s1_reporter_cron_monthly", "s1_reporter_cron_stale_digest"):
            self.assertIn(k, d)
        self.assertEqual(d["s1_reporter_cron_check_alerts"]["weekday"], "1-5")
        self.assertEqual(d["s1_reporter_cron_daily"]["hour"], "6")

    def test_dockerfile_is_multistage_nonroot_with_tz(self):
        df = _read("files/Dockerfile")
        self.assertEqual(df.count("FROM python:3.12-slim"), 2)
        self.assertIn("USER reporter", df)
        self.assertIn("ENV TZ=", df)
        self.assertIn('ENTRYPOINT ["python", "-m", "s1_reporter"]', df)
        self.assertNotIn("gcc", df.split("FROM python:3.12-slim")[2])   # no compiler in the final stage

    def test_requirements_pinned(self):
        for line in _read("files/requirements.txt").splitlines():
            if line.strip():
                self.assertIn("==", line)

    def test_compose_reporter_is_one_shot_and_charts_stay_up(self):
        tpl = _read("templates/docker-compose.s1_reporter.yml.j2")
        reporter = tpl.split("  s1-charts:")[0]
        self.assertNotIn("restart:", reporter)
        self.assertNotIn("healthcheck:", reporter)
        self.assertNotIn("container_name:", reporter)
        for env in ("STALE_DAYS", "REPORT_TZ_OFFSET_HOURS", "OFFLINE_THRESHOLD_MINUTES", "TEAMS_WEBHOOK_URL"):
            self.assertIn(env, reporter)
        self.assertNotIn("DAILY_REPORT_HOUR", tpl)
        self.assertIn("container_name: s1_reporter_charts", tpl)

    def test_wrapper(self):
        sh = _read("templates/run-reporter.sh.j2")
        self.assertTrue(sh.startswith("#!/bin/bash"))
        self.assertIn("set -o pipefail", sh)
        self.assertIn('docker compose run --rm reporter "$@"', sh)

    def test_tasks_order_and_cron_entries(self):
        tasks = yaml.safe_load(_read("tasks/main.yml"))
        names = [t["name"].lower() for t in tasks]
        i_down = next(i for i, n in enumerate(names) if "stop legacy" in n)
        i_build = next(i for i, n in enumerate(names) if "build" in n)
        i_up = next(i for i, n in enumerate(names) if "chart server" in n)
        i_mig = next(i for i, n in enumerate(names) if "migrat" in n)
        i_cron = next(i for i, n in enumerate(names) if "cron" in n)
        self.assertTrue(i_down < i_build < i_up < i_mig < i_cron)
        crons = [t for t in tasks if "cron" in t]
        self.assertEqual(len(crons), 1)
        self.assertIn("loop", crons[0])

    def test_old_files_removed(self):
        for rel in ("files/report.py", "files/upload_monitor.py", "files/entrypoint.sh",
                    "files/teams_notifier.py", "files/cards.py", "files/chart_store.py"):
            self.assertFalse(os.path.exists(os.path.join(ROLE, rel)), rel)


if __name__ == "__main__":
    unittest.main()
