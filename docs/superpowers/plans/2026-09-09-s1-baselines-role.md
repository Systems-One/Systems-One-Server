# s1_baselines Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move alert-threshold recomputation out of `s1_reporter` into its own one-shot Docker image and Ansible role, scheduled by host cron, with an explicit `dry-run` / `apply` / `migrate` CLI.

**Architecture:** New role `roles/s1_baselines` builds a slim `python:3.12-slim` + `pymssql` image on the host and runs it via `docker compose run --rm baselines <cmd>`. A wrapper script `run-baselines.sh` is the single entry point for cron and operators. `s1_reporter` loses its Sunday baseline block, its copy of the script and its copy task.

**Tech Stack:** Python 3.12, pymssql, Docker Compose, Ansible (cron module), unittest.

**Spec:** `docs/superpowers/specs/2026-09-09-s1-baselines-role-design.md`

## Global Constraints

- Container image name `s1-baselines:latest`; install dir `/opt/s1-baselines`.
- Database login is `mssql_rm_admin_login` (`admin`), never `sa`.
- The script must never write to the database unless the `apply` subcommand is given.
- Wrapper is `#!/bin/bash` with `set -o pipefail`.
- Cron entry name `systems-one baselines recompute`, Sunday 02:00 host time by default.
- Tests are `unittest`, run with `python -m unittest discover -s roles/s1_baselines/tests`.
- Work on branch `feat/s1-baselines-role` created from `feat/warn-15pct-below-mean`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Create the role skeleton by moving the script and its tests

**Files:**
- Move: `roles/s1_reporter/files/compute_baselines.py` -> `roles/s1_baselines/files/compute_baselines.py`
- Move: `roles/s1_reporter/tests/test_baselines.py` -> `roles/s1_baselines/tests/test_baselines.py`
- Create: `roles/s1_baselines/defaults/main.yml`

**Interfaces:**
- Produces: module `compute_baselines` at the new path, loaded by tests via `SourceFileLoader` with `BASELINES = os.path.join(HERE, "..", "files", "compute_baselines.py")` (unchanged relative path, new role).

- [ ] **Step 1: Create the branch and move the files with git so history follows**

```bash
git checkout -b feat/s1-baselines-role
mkdir -p roles/s1_baselines/files roles/s1_baselines/tests roles/s1_baselines/defaults roles/s1_baselines/templates roles/s1_baselines/tasks
git mv roles/s1_reporter/files/compute_baselines.py roles/s1_baselines/files/compute_baselines.py
git mv roles/s1_reporter/tests/test_baselines.py roles/s1_baselines/tests/test_baselines.py
```

- [ ] **Step 2: Write the defaults file**

`roles/s1_baselines/defaults/main.yml`:

```yaml
---
# s1_baselines: one-shot recompute of dbo.alert_thresholds, scheduled by host cron.
s1_baselines_image: "s1-baselines:latest"
s1_baselines_dir: "/opt/s1-baselines"

s1_baselines_db_host: "mssql"
s1_baselines_db_port: 1433
s1_baselines_db_name: "{{ mssql_rm_database | default('S1_Remote_Monitoring') }}"
# Least-privilege application login, never sa.
s1_baselines_db_user: "{{ mssql_rm_admin_login | default('admin') }}"
s1_baselines_db_pass: "{{ mssql_rm_admin_password | default('') }}"

s1_baselines_lookback_days: 60

# Host cron. Sunday 02:00 host-local time (the host runs SAST).
s1_baselines_schedule_enabled: true
s1_baselines_schedule_hour: "2"
s1_baselines_schedule_minute: "0"
s1_baselines_log_path: "/opt/s1-baselines/baselines.log"
```

- [ ] **Step 3: Run the moved tests to prove the move is clean**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 9 tests PASS (the loader path `../files/compute_baselines.py` resolves inside the new role).

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: 33 tests PASS (the 9 baseline tests are gone from here, nothing else changed).

- [ ] **Step 4: Commit**

```bash
git add roles/s1_baselines roles/s1_reporter
git commit -m "refactor(s1_baselines): move compute_baselines.py and its tests into a new role

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Explicit `dry-run` / `apply` / `migrate` subcommands, env-only config

**Files:**
- Modify: `roles/s1_baselines/files/compute_baselines.py`
- Test: `roles/s1_baselines/tests/test_cli.py`

**Interfaces:**
- Produces: `parse_args(argv: list[str]) -> argparse.Namespace` with `.command in {"dry-run","apply","migrate"}` and `.lookback: int`; `load_config() -> dict` raising `SystemExit` naming a missing variable; `main(argv=None)`.

- [ ] **Step 1: Write the failing tests**

`roles/s1_baselines/tests/test_cli.py`:

```python
"""CLI and config tests for compute_baselines.py (no DB)."""
import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINES = os.path.join(HERE, "..", "files", "compute_baselines.py")


def _load():
    installed = False
    if "pymssql" not in sys.modules:
        sys.modules["pymssql"] = types.ModuleType("pymssql")
        installed = True
    try:
        loader = importlib.machinery.SourceFileLoader("s1_baselines_cli", BASELINES)
        spec = importlib.util.spec_from_loader("s1_baselines_cli", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        if installed:
            sys.modules.pop("pymssql", None)


baselines = _load()

ENV = {"DB_HOST": "h", "DB_PORT": "1433", "DB_USER": "u", "DB_PASS": "p", "DB_NAME": "n"}


class TestParseArgs(unittest.TestCase):
    def test_dry_run_default_lookback(self):
        ns = baselines.parse_args(["dry-run"])
        self.assertEqual(ns.command, "dry-run")
        self.assertEqual(ns.lookback, 60)

    def test_apply_with_lookback(self):
        ns = baselines.parse_args(["apply", "--lookback", "30"])
        self.assertEqual(ns.command, "apply")
        self.assertEqual(ns.lookback, 30)

    def test_migrate(self):
        self.assertEqual(baselines.parse_args(["migrate"]).command, "migrate")

    def test_no_subcommand_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            baselines.parse_args([])
        self.assertEqual(cm.exception.code, 2)

    def test_legacy_dry_run_flag_rejected(self):
        with self.assertRaises(SystemExit):
            baselines.parse_args(["--dry-run"])


class TestLoadConfig(unittest.TestCase):
    def test_reads_all_five_from_env(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(baselines.load_config(), ENV)

    def test_missing_var_names_it(self):
        partial = dict(ENV)
        del partial["DB_PASS"]
        with patch.dict(os.environ, partial, clear=True):
            with self.assertRaises(SystemExit) as cm:
                baselines.load_config()
        self.assertIn("DB_PASS", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest roles.s1_baselines.tests.test_cli -v` (or `python -m unittest discover -s roles/s1_baselines/tests -v`)
Expected: FAIL with `AttributeError: module has no attribute 'parse_args'` and the config test failing because `load_config()` currently returns a partial dict instead of raising.

- [ ] **Step 3: Rewrite the config and CLI sections of the script**

Replace the `# ── Config` block (from `ENV_PATH = ...` through `CFG = load_config()`) with:

```python
# ── Config ─────────────────────────────────────────────────────────────────────
ENV_KEYS = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASS", "DB_NAME"]


def load_config():
    """Read DB settings from the environment. Compose is the only config source."""
    missing = [k for k in ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")
    return {k: os.environ[k] for k in ENV_KEYS}


def get_conn(cfg):
    return pymssql.connect(
        server=cfg["DB_HOST"], port=int(cfg["DB_PORT"]),
        user=cfg["DB_USER"], password=cfg["DB_PASS"],
        database=cfg["DB_NAME"], timeout=30
    )
```

Delete the old module-level `CFG = load_config()` and the old `get_conn()` that read `CFG`. Then replace the `main()` argument parsing with:

```python
def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="compute_baselines.py",
        description="Compute per-device alert thresholds into dbo.alert_thresholds",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    for name, help_text in (
        ("dry-run", "Print thresholds; write nothing"),
        ("apply", "Compute and upsert thresholds"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--lookback", type=int, default=60,
                       help="Days of history to use (default: 60)")
    sub.add_parser("migrate", help="Create dbo.alert_thresholds if it does not exist")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cfg = load_config()
    if args.command == "migrate":
        run_migrations(cfg)
        return
    compute(cfg, lookback=args.lookback, dry_run=(args.command == "dry-run"))


if __name__ == "__main__":
    main()
```

Rename the old body of `main()` (everything after argument parsing) to `def compute(cfg, lookback, dry_run):` and change `with get_conn() as conn:` to `with get_conn(cfg) as conn:`. Add a temporary stub so the module imports until Task 4 supplies the real one:

```python
def run_migrations(cfg):
    raise NotImplementedError("added in the migrations task")
```

- [ ] **Step 4: Run the whole role test suite**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 16 tests PASS (9 from `test_baselines.py`, 7 new).

- [ ] **Step 5: Commit**

```bash
git add roles/s1_baselines
git commit -m "feat(s1_baselines): explicit dry-run/apply/migrate subcommands, env-only config

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Print what changed on `apply`

**Files:**
- Modify: `roles/s1_baselines/files/compute_baselines.py` (inside `compute()`, before the upsert loop)
- Test: `roles/s1_baselines/tests/test_diff_lines.py`

**Interfaces:**
- Produces: `format_change_lines(existing: dict[tuple, tuple[float|None, float|None]], results: list[dict]) -> tuple[list[str], int]` where the key is `(customer, machine_name, location, metric)`, the value is `(warn_value, bad_value)`, and the int is the count of rows whose values did not change.

- [ ] **Step 1: Write the failing test**

`roles/s1_baselines/tests/test_diff_lines.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 3 new tests FAIL with `AttributeError: ... 'format_change_lines'`.

- [ ] **Step 3: Implement the formatter and wire it into `compute()`**

Add after `derive_thresholds`:

```python
# ── Change reporting ───────────────────────────────────────────────────────────
def format_change_lines(existing, results):
    """One line per row that is new or changed; unchanged rows are only counted."""
    lines, unchanged = [], 0
    for r in results:
        key = (r["customer"], r["machine_name"], r["location"], r["metric"])
        label = " / ".join(key)
        old = existing.get(key)
        if old is None:
            lines.append(f"{label}: NEW warn {r['warn_value']:.4f}, bad {r['bad_value']:.4f}")
            continue
        old_warn, old_bad = old
        if old_warn == r["warn_value"] and old_bad == r["bad_value"]:
            unchanged += 1
            continue
        lines.append(f"{label}: warn {old_warn:.4f} -> {r['warn_value']:.4f}, "
                     f"bad {old_bad:.4f} -> {r['bad_value']:.4f}")
    return lines, unchanged
```

In `compute()`, replace the block that starts `# Upsert` / `now = datetime.now()` so that the existing values are read once and the change lines printed before the loop:

```python
        # Upsert
        with conn.cursor(as_dict=True) as cur:
            cur.execute("SELECT customer, machine_name, location, metric, warn_value, bad_value FROM alert_thresholds")
            existing = {
                (e["customer"], e["machine_name"], e["location"], e["metric"]):
                (float(e["warn_value"]) if e["warn_value"] is not None else None,
                 float(e["bad_value"]) if e["bad_value"] is not None else None)
                for e in cur.fetchall()
            }
        change_lines, unchanged = format_change_lines(existing, results)
        print("\nChanges:")
        for line in change_lines:
            print(f"  {line}")
        print(f"  ({unchanged} unchanged)")

        now = datetime.now()
        inserted = updated = 0
        with conn.cursor(as_dict=True) as cur:
            for r in results:
                if (r["customer"], r["machine_name"], r["location"], r["metric"]) in existing:
                    cur.execute("""
                        UPDATE alert_thresholds SET
                        ... (unchanged UPDATE statement and parameters) ...
                    """, (...))
                    updated += 1
                else:
                    cur.execute("""
                        INSERT INTO alert_thresholds
                        ... (unchanged INSERT statement and parameters) ...
                    """, (...))
                    inserted += 1
        conn.commit()
        print(f"\nDone: {inserted} inserted, {updated} updated.")
```

Keep the UPDATE and INSERT statements exactly as they are today; only the per-row `SELECT id ... existing = cur.fetchone()` pre-check is replaced by the `in existing` membership test.

- [ ] **Step 4: Run tests**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 19 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_baselines
git commit -m "feat(s1_baselines): print old -> new threshold lines on apply

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `migrate` subcommand and the `alert_thresholds` DDL

**Files:**
- Create: `roles/s1_baselines/files/migrations/001_alert_thresholds.sql`
- Modify: `roles/s1_baselines/files/compute_baselines.py` (replace the `run_migrations` stub)
- Test: `roles/s1_baselines/tests/test_migrations.py`

**Interfaces:**
- Produces: `split_batches(sql_text: str) -> list[str]` (splits on lines that are exactly `GO`, case-insensitive, drops empty batches); `run_migrations(cfg, migrations_dir=MIGRATIONS_DIR)` executing every `*.sql` in sorted order, one batch per `cursor.execute`, committing per file.

- [ ] **Step 1: Write the failing tests**

`roles/s1_baselines/tests/test_migrations.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: the 4 new tests FAIL (`split_batches` missing, migration file missing).

- [ ] **Step 3: Write the migration file**

`roles/s1_baselines/files/migrations/001_alert_thresholds.sql`:

```sql
-- dbo.alert_thresholds: per-device warn/bad limits computed by s1_baselines.
-- Column set matches the table that already exists on production (2026-09-09).
IF OBJECT_ID(N'dbo.alert_thresholds', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.alert_thresholds (
        id               INT IDENTITY(1,1) PRIMARY KEY,
        customer         NVARCHAR(100) NOT NULL,
        machine_name     NVARCHAR(100) NULL,
        location         NVARCHAR(100) NULL,
        metric           NVARCHAR(50)  NOT NULL,
        direction        NVARCHAR(10)  NOT NULL,
        warn_value       DECIMAL(10,4) NULL,
        bad_value        DECIMAL(10,4) NULL,
        baseline_mean    DECIMAL(10,4) NULL,
        baseline_stddev  DECIMAL(10,4) NULL,
        baseline_p05     DECIMAL(10,4) NULL,
        baseline_p10     DECIMAL(10,4) NULL,
        baseline_p90     DECIMAL(10,4) NULL,
        baseline_p95     DECIMAL(10,4) NULL,
        baseline_samples INT NULL,
        lookback_days    INT NULL,
        last_computed    DATETIME NULL,
        is_override      BIT NOT NULL DEFAULT 0,
        updated_at       DATETIME NULL
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_alert_thresholds_key' AND object_id = OBJECT_ID(N'dbo.alert_thresholds'))
BEGIN
    CREATE INDEX IX_alert_thresholds_key
    ON dbo.alert_thresholds (customer, machine_name, location, metric);
END
GO
```

- [ ] **Step 4: Replace the `run_migrations` stub**

```python
# ── Migrations ─────────────────────────────────────────────────────────────────
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def split_batches(sql_text):
    """Split T-SQL on lines that are exactly GO (sqlcmd batch separator)."""
    batches, current = [], []
    for line in sql_text.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def run_migrations(cfg, migrations_dir=MIGRATIONS_DIR, connect=None):
    """Apply every migrations/*.sql in name order. Files must be idempotent."""
    connect = connect or get_conn
    files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    with connect(cfg) as conn:
        for name in files:
            with open(os.path.join(migrations_dir, name), encoding="utf-8") as fh:
                batches = split_batches(fh.read())
            with conn.cursor() as cur:
                for batch in batches:
                    cur.execute(batch)
            conn.commit()
            print(f"migrated {name} ({len(batches)} batch(es))")
```

- [ ] **Step 5: Run tests**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 23 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add roles/s1_baselines
git commit -m "feat(s1_baselines): migrate subcommand creates dbo.alert_thresholds when absent

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Dockerfile, compose, wrapper, Ansible tasks and cron

**Files:**
- Create: `roles/s1_baselines/files/Dockerfile`
- Create: `roles/s1_baselines/templates/docker-compose.s1_baselines.yml.j2`
- Create: `roles/s1_baselines/templates/run-baselines.sh.j2`
- Create: `roles/s1_baselines/tasks/main.yml`
- Modify: `webservers.yml` (append role after `s1_reporter`)
- Test: `roles/s1_baselines/tests/test_role_files.py`

**Interfaces:**
- Consumes: `compute_baselines.py` subcommands from Tasks 2 and 4.
- Produces: host command `/opt/s1-baselines/run-baselines.sh dry-run|apply|migrate [--lookback N]`.

- [ ] **Step 1: Write the failing role-file tests**

`roles/s1_baselines/tests/test_role_files.py`:

```python
import os
import re
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
        self.assertNotIn("CMD", df)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: the 8 new tests FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the Dockerfile**

`roles/s1_baselines/files/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates gcc g++ freetds-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "pymssql==2.3.2"

COPY compute_baselines.py /app/compute_baselines.py
COPY migrations/ /app/migrations/

# No CMD: running with no subcommand prints usage and exits 2 instead of writing anything.
ENTRYPOINT ["python3", "/app/compute_baselines.py"]
```

- [ ] **Step 4: Write the compose template**

`roles/s1_baselines/templates/docker-compose.s1_baselines.yml.j2`:

```yaml
# One-shot service: started only by `docker compose run --rm baselines <cmd>`.
services:
  baselines:
    build:
      context: .
      dockerfile: Dockerfile
    image: "{{ s1_baselines_image }}"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    environment:
      DB_HOST: "{{ s1_baselines_db_host }}"
      DB_PORT: "{{ s1_baselines_db_port }}"
      DB_NAME: "{{ s1_baselines_db_name }}"
      DB_USER: "{{ s1_baselines_db_user }}"
      DB_PASS: "{{ s1_baselines_db_pass }}"
    networks:
      - {{ docker_shared_network | default('infra') }}

networks:
  {{ docker_shared_network | default('infra') }}:
    external: true
```

- [ ] **Step 5: Write the wrapper template**

`roles/s1_baselines/templates/run-baselines.sh.j2`:

```bash
#!/bin/bash
# Usage: run-baselines.sh dry-run|apply|migrate [--lookback N]
# Same entry point for cron and operators. Exit code is the container's.
set -o pipefail
cd {{ s1_baselines_dir }} || exit 1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] run-baselines $*" >> {{ s1_baselines_log_path }}
docker compose run --rm baselines "$@" 2>&1 | tee -a {{ s1_baselines_log_path }}
```

- [ ] **Step 6: Write the tasks**

`roles/s1_baselines/tasks/main.yml`:

```yaml
---
- name: Ensure s1_baselines directory exists
  file:
    path: "{{ s1_baselines_dir }}"
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Validate required variables
  assert:
    that:
      - s1_baselines_db_pass | length > 0
    fail_msg: "s1_baselines_db_pass is empty; set mssql_rm_admin_password in group_vars/dbservers.yml"

- name: Copy application source
  copy:
    src: "{{ item.src }}"
    dest: "{{ s1_baselines_dir }}/{{ item.dest }}"
    owner: root
    group: root
    mode: "0644"
  loop:
    - { src: Dockerfile,           dest: Dockerfile }
    - { src: compute_baselines.py, dest: compute_baselines.py }
    - { src: migrations/,          dest: migrations/ }

- name: Render docker-compose file
  template:
    src: docker-compose.s1_baselines.yml.j2
    dest: "{{ s1_baselines_dir }}/docker-compose.yml"
    owner: root
    group: root
    mode: "0640"

- name: Render run-baselines.sh wrapper
  template:
    src: run-baselines.sh.j2
    dest: "{{ s1_baselines_dir }}/run-baselines.sh"
    owner: root
    group: root
    mode: "0755"

- name: Build s1_baselines image
  command: docker compose build
  args:
    chdir: "{{ s1_baselines_dir }}"
  changed_when: false

- name: Run migrations (creates dbo.alert_thresholds when absent)
  command: docker compose run --rm baselines migrate
  args:
    chdir: "{{ s1_baselines_dir }}"
  changed_when: false

- name: Install weekly baseline recompute cron job
  cron:
    name: "systems-one baselines recompute"
    user: root
    weekday: "0"
    hour: "{{ s1_baselines_schedule_hour }}"
    minute: "{{ s1_baselines_schedule_minute }}"
    job: "{{ s1_baselines_dir }}/run-baselines.sh apply --lookback {{ s1_baselines_lookback_days }} >> {{ s1_baselines_log_path }} 2>&1"
    state: present
  when: s1_baselines_schedule_enabled | bool

- name: Remove baseline cron job when schedule disabled
  cron:
    name: "systems-one baselines recompute"
    user: root
    state: absent
  when: not (s1_baselines_schedule_enabled | bool)
```

- [ ] **Step 7: Add the role to `webservers.yml`**

After the `scan_fleet_dashboard` entry (it is the last one; the test only requires "after s1_reporter"), add:

```yaml
    - role: s1_baselines
      tags: [s1_baselines]
```

- [ ] **Step 8: Run tests and the playbook syntax check**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 31 tests PASS.

Run (needs Ansible; on a machine without it, skip and rely on CI):
`ansible-playbook site.yml --syntax-check -i production -e "mssql_sa_password=test grafana_admin_password=test mqtt_password=test grafana_git_sync_token=test cloudflare_tunnel_token=test backup_b2_account_id=test backup_b2_account_key=test backup_restic_password=test"`
Expected: `playbook: site.yml` with no errors.

- [ ] **Step 9: Commit**

```bash
git add roles/s1_baselines webservers.yml
git commit -m "feat(s1_baselines): Dockerfile, one-shot compose, wrapper, Ansible tasks and Sunday cron

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Remove baselines from `s1_reporter` and wire CI

**Files:**
- Modify: `roles/s1_reporter/files/entrypoint.sh` (remove `last_baseline_week`, the Sunday block, and the "baselines every Sunday" text)
- Modify: `roles/s1_reporter/files/Dockerfile` (remove `COPY compute_baselines.py`)
- Modify: `roles/s1_reporter/tasks/main.yml:34-40` (remove the "Copy compute_baselines.py" task)
- Modify: `.github/workflows/ci.yml` (add the new test step)
- Test: `roles/s1_baselines/tests/test_reporter_detached.py`

- [ ] **Step 1: Write the failing test**

`roles/s1_baselines/tests/test_reporter_detached.py`:

```python
"""Guards against the reporter regaining its own baseline schedule."""
import os
import unittest

REPORTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "s1_reporter")


def _read(rel):
    with open(os.path.join(REPORTER, rel), encoding="utf-8") as fh:
        return fh.read()


class TestReporterNoLongerOwnsBaselines(unittest.TestCase):
    def test_entrypoint_has_no_baseline_block(self):
        sh = _read("files/entrypoint.sh")
        self.assertNotIn("compute_baselines", sh)
        self.assertNotIn("last_baseline_week", sh)
        self.assertNotIn("baselines every Sunday", sh)

    def test_dockerfile_does_not_copy_script(self):
        self.assertNotIn("compute_baselines", _read("files/Dockerfile"))

    def test_tasks_do_not_copy_script(self):
        self.assertNotIn("compute_baselines", _read("tasks/main.yml"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 3 FAIL.

- [ ] **Step 3: Edit the reporter files**

In `roles/s1_reporter/files/entrypoint.sh`:
- Delete the line `last_baseline_week=""`.
- Change the startup echo to end with `monthly on 1st at ${MONTHLY_HOUR}:30 (no alerts Sat/Sun)"`.
- Delete the comment plus block from `# Weekly baseline recompute — every Sunday at 02:00` through the matching `fi` (the block that runs `python3 /app/compute_baselines.py`).

In `roles/s1_reporter/files/Dockerfile`: delete `COPY compute_baselines.py /app/compute_baselines.py`.

In `roles/s1_reporter/tasks/main.yml`: delete the task named `Copy compute_baselines.py` (the `copy:` block with `src: compute_baselines.py`).

- [ ] **Step 4: Add the CI step**

In `.github/workflows/ci.yml`, after the `Run s1_reporter unit tests` step add:

```yaml
      - name: Run s1_baselines unit tests
        run: |
          pip install pyyaml
          python -m unittest discover -s roles/s1_baselines/tests
```

- [ ] **Step 5: Run both suites**

Run: `python -m unittest discover -s roles/s1_baselines/tests -v`
Expected: 34 PASS.

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: 33 PASS.

Run: `bash -n roles/s1_reporter/files/entrypoint.sh`
Expected: no output (syntax OK).

- [ ] **Step 6: Commit**

```bash
git add roles/s1_reporter roles/s1_baselines .github/workflows/ci.yml
git commit -m "refactor(s1_reporter): drop the in-container baseline schedule; s1_baselines owns it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: README service table and deploy notes

**Files:**
- Modify: `README.md` (Services table, Deploying section, Known rough edges)

- [ ] **Step 1: Add the role row and update text**

In the Services table, after the `s1_reporter` row, add:

```markdown
| `s1_baselines` | none (one-shot via `compose run`) | built `s1-baselines:latest` | `/opt/s1-baselines` | Recomputes `dbo.alert_thresholds` from 60 days of `device_statistics`. Host cron runs `run-baselines.sh apply` every Sunday 02:00; operators run `run-baselines.sh dry-run` to preview. Owns the table's DDL via `migrate`. |
```

In the `s1_reporter` row, delete the words `weekly baseline recompute Sunday 02:00,`.

In "Roles that carry tags", add `s1_baselines`.

In "Known rough edges", delete the bullet about the `alert_thresholds` DDL if present, and change the `s1_reporter` `sa` bullet to note that baselines now use `admin`.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the s1_baselines role

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Live verification on `sysone` (manual, after merge)

Not code. Run in this order and record the output in the PR:

1. `ansible-playbook -i production webservers.yml --tags s1_baselines`
2. `/opt/s1-baselines/run-baselines.sh dry-run` and confirm the summary table lists the 15 devices seen today and MADIBANA DIM1 `good_read_pct` warn is about 77.5.
3. `/opt/s1-baselines/run-baselines.sh apply` and confirm `SELECT MAX(last_computed) FROM alert_thresholds` advanced.
4. `ansible-playbook -i production webservers.yml --tags s1_reporter` and confirm `docker logs s1_reporter | tail -1` no longer mentions baselines.
5. `sudo crontab -l | grep baselines` shows the Sunday entry.
