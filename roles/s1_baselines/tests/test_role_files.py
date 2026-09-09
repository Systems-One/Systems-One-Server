import os
import unittest

import yaml

ROLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REPO = os.path.join(ROLE, "..", "..")


def _read(rel):
    with open(os.path.join(ROLE, rel), encoding="utf-8") as fh:
        return fh.read()


class TestRoleFiles(unittest.TestCase):
    def test_yaml_parses(self):
        for rel in ("defaults/main.yml", "tasks/main.yml"):
            self.assertIsNotNone(yaml.safe_load(_read(rel)), rel)

    def test_defaults_use_admin_login_not_sa(self):
        d = yaml.safe_load(_read("defaults/main.yml"))
        self.assertIn("mssql_rm_admin_login", d["s1_baselines_db_user"])
        self.assertEqual(d["s1_baselines_dir"], "/opt/s1-baselines")
        self.assertEqual(d["s1_baselines_image"], "s1-baselines:latest")

    def test_dockerfile_entrypoint_passes_args_through(self):
        df = _read("files/Dockerfile")
        self.assertIn('ENTRYPOINT ["python3", "/app/compute_baselines.py"]', df)
        self.assertNotIn("\nCMD", df)
        self.assertIn("COPY migrations/", df)

    def test_compose_is_one_shot(self):
        tpl = _read("templates/docker-compose.s1_baselines.yml.j2")
        self.assertNotIn("ports:", tpl)
        self.assertNotIn("restart:", tpl)
        self.assertNotIn("container_name:", tpl)
        for env in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS"):
            self.assertIn(env, tpl)

    def test_wrapper_is_bash_with_pipefail(self):
        sh = _read("templates/run-baselines.sh.j2")
        self.assertTrue(sh.startswith("#!/bin/bash"))
        self.assertIn("set -o pipefail", sh)
        self.assertIn('docker compose run --rm baselines "$@"', sh)

    def test_tasks_build_migrate_then_cron(self):
        names = [t["name"] for t in yaml.safe_load(_read("tasks/main.yml"))]
        build = next(i for i, n in enumerate(names) if "build" in n.lower())
        migrate = next(i for i, n in enumerate(names) if "migrat" in n.lower())
        cron = next(i for i, n in enumerate(names) if "cron" in n.lower())
        self.assertLess(build, migrate)
        self.assertLess(migrate, cron)

    def test_cron_runs_apply_on_sunday(self):
        tasks = yaml.safe_load(_read("tasks/main.yml"))
        cron = next(t for t in tasks if "cron" in t and t["cron"].get("state", "present") == "present")
        self.assertEqual(str(cron["cron"]["weekday"]), "0")
        self.assertIn("run-baselines.sh apply", cron["cron"]["job"])

    def test_webservers_includes_tagged_role_after_reporter(self):
        with open(os.path.join(REPO, "webservers.yml"), encoding="utf-8") as fh:
            roles = yaml.safe_load(fh)[0]["roles"]
        names = [r["role"] if isinstance(r, dict) else r for r in roles]
        self.assertIn("s1_baselines", names)
        self.assertGreater(names.index("s1_baselines"), names.index("s1_reporter"))
        entry = next(r for r in roles if isinstance(r, dict) and r.get("role") == "s1_baselines")
        self.assertIn("s1_baselines", entry["tags"])


if __name__ == "__main__":
    unittest.main()
