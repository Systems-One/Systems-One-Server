# s1_reporter Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the reporter's in-container loop and 763-line monolith with a package of testable modules run as one-shot jobs by host cron, with customer configuration and device reporting flags in the database.

**Architecture:** `roles/s1_reporter/files/app/s1_reporter/` is a Python package; `python -m s1_reporter <job>` runs one job and exits. Only `db.py` imports pymssql and only `charts.py` imports matplotlib, so every rule module is unit-tested with plain imports and injected fake `query` functions. Ansible builds the image, keeps the nginx chart server up, runs `migrate`, and installs five cron entries.

**Tech Stack:** Python 3.12, pymssql 2.3.2, matplotlib 3.9.2, numpy 2.1.3, Docker multi-stage build, Ansible cron module, unittest.

**Spec:** `docs/superpowers/specs/2026-09-09-s1-reporter-overhaul-design.md`

## Global Constraints

- Branch `feat/s1-reporter-overhaul`, created from `feat/s1-baselines-role` after that plan is complete (it removes the Sunday block and owns `alert_thresholds`).
- Jobs: `sync-status`, `check-alerts`, `daily`, `monthly`, `stale-digest`, `migrate`. Exit 0 on success, 1 on any failed Teams POST or DB error, 2 on usage error.
- DB login `admin` (`mssql_rm_admin_login`), never `sa`.
- All SQL uses `%s` parameters; never interpolate customer names or device names into SQL text.
- Timestamps in the DB are UTC. Local day = UTC + `REPORT_TZ_OFFSET_HOURS` (default 2).
- Defaults: `OFFLINE_THRESHOLD_MINUTES=30`, `STALE_DAYS=14`, `UPLOAD_ALERT_CONSECUTIVE=3`, `UPLOAD_LOOKBACK_PACKETS=6`, `CHART_RETENTION_DAYS=14`.
- Alert state files are written only after every Teams POST for that run returned True.
- Tests: `python -m unittest discover -s roles/s1_reporter/tests`. Tests import the package via `sys.path.insert(0, <role>/files/app)`; they must not import `pymssql` or `matplotlib`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## File map

```
roles/s1_reporter/
  defaults/main.yml                      rewritten (cron fields, stale days, tz offset, admin login)
  tasks/main.yml                         rewritten (copy app/, build, up charts, migrate, cron)
  templates/docker-compose.s1_reporter.yml.j2   rewritten (reporter one-shot + s1-charts)
  templates/run-reporter.sh.j2           new
  handlers/main.yml                      unchanged (none exist today; skip)
  files/Dockerfile                       rewritten multi-stage
  files/requirements.txt                 new
  files/app/s1_reporter/__init__.py      empty
  files/app/s1_reporter/__main__.py      -> cli.main()
  files/app/s1_reporter/cli.py           job dispatch
  files/app/s1_reporter/config.py        Settings
  files/app/s1_reporter/db.py            Database (pymssql only here)
  files/app/s1_reporter/timewin.py       local-day windows
  files/app/s1_reporter/customers.py     CustomerConfig from dbo.customer_config
  files/app/s1_reporter/thresholds.py    alert_thresholds lookup
  files/app/s1_reporter/liveness.py      Device, DeviceState, classify
  files/app/s1_reporter/status_sync.py   MERGE into device_status
  files/app/s1_reporter/state.py         AlertState (commit-after-send)
  files/app/s1_reporter/upload.py        not_sent detection
  files/app/s1_reporter/anomalies.py     rules
  files/app/s1_reporter/queries.py       report SQL (window based)
  files/app/s1_reporter/charts.py        matplotlib only here
  files/app/s1_reporter/chart_store.py   moved unchanged
  files/app/s1_reporter/cards.py         moved + build_stale_digest_card
  files/app/s1_reporter/teams.py         moved from teams_notifier.py
  files/app/s1_reporter/reports.py       job orchestration
  files/app/migrations/001_customer_config.sql
  files/app/migrations/002_device_flags.sql
  tests/*.py                             one per module + test_role_files.py
```

Deleted at the end: `files/report.py`, `files/upload_monitor.py`, `files/entrypoint.sh`, `files/teams_notifier.py`, `files/cards.py`, `files/chart_store.py`, `tests/test_report_shapes.py`.

---

### Task 1: Package skeleton, settings, and the test bootstrap

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/__init__.py` (empty)
- Create: `roles/s1_reporter/files/app/s1_reporter/config.py`
- Create: `roles/s1_reporter/tests/_bootstrap.py`
- Test: `roles/s1_reporter/tests/test_config.py`

**Interfaces:**
- Produces: `Settings` frozen dataclass with fields `db_host, db_port:int, db_name, db_user, db_pass, teams_webhook_url, chart_dir, chart_public_base_url, chart_retention_days:int, offline_threshold_minutes:int, stale_days:int, tz_offset_hours:int, upload_alert_consecutive:int, upload_lookback_packets:int, offline_state_file, upload_state_file`; `load_settings(env: Mapping[str,str]) -> Settings`.

- [ ] **Step 1: Create the branch and the test bootstrap**

```bash
git checkout -b feat/s1-reporter-overhaul
mkdir -p roles/s1_reporter/files/app/s1_reporter roles/s1_reporter/files/app/migrations
touch roles/s1_reporter/files/app/s1_reporter/__init__.py
```

`roles/s1_reporter/tests/_bootstrap.py`:

```python
"""Puts files/app on sys.path so tests import the package like the container does."""
import os
import sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)
```

- [ ] **Step 2: Write the failing test**

`roles/s1_reporter/tests/test_config.py`:

```python
import unittest

import _bootstrap  # noqa: F401
from s1_reporter.config import Settings, load_settings

REQUIRED = {
    "DB_HOST": "mssql", "DB_PORT": "1433", "DB_NAME": "RM", "DB_USER": "admin", "DB_PASS": "pw",
    "TEAMS_WEBHOOK_URL": "https://example.invalid/hook",
}


class TestLoadSettings(unittest.TestCase):
    def test_required_and_defaults(self):
        s = load_settings(REQUIRED)
        self.assertIsInstance(s, Settings)
        self.assertEqual(s.db_port, 1433)
        self.assertEqual(s.chart_dir, "/data/charts")
        self.assertEqual(s.chart_public_base_url, "")
        self.assertEqual(s.chart_retention_days, 14)
        self.assertEqual(s.offline_threshold_minutes, 30)
        self.assertEqual(s.stale_days, 14)
        self.assertEqual(s.tz_offset_hours, 2)
        self.assertEqual(s.upload_alert_consecutive, 3)
        self.assertEqual(s.upload_lookback_packets, 6)
        self.assertEqual(s.offline_state_file, "/data/offline_state.json")
        self.assertEqual(s.upload_state_file, "/data/upload_state.json")

    def test_overrides(self):
        env = dict(REQUIRED, STALE_DAYS="30", REPORT_TZ_OFFSET_HOURS="0", CHART_PUBLIC_BASE_URL="https://c.example/")
        s = load_settings(env)
        self.assertEqual(s.stale_days, 30)
        self.assertEqual(s.tz_offset_hours, 0)
        self.assertEqual(s.chart_public_base_url, "https://c.example/")

    def test_missing_required_names_variable(self):
        env = dict(REQUIRED)
        del env["TEAMS_WEBHOOK_URL"]
        with self.assertRaises(SystemExit) as cm:
            load_settings(env)
        self.assertIn("TEAMS_WEBHOOK_URL", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_config.py" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 's1_reporter.config'`.

- [ ] **Step 4: Write config.py**

```python
"""Settings from environment variables. Compose is the only configuration source."""
from dataclasses import dataclass
from typing import Mapping

_REQUIRED = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "TEAMS_WEBHOOK_URL")


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str
    teams_webhook_url: str
    chart_dir: str = "/data/charts"
    chart_public_base_url: str = ""
    chart_retention_days: int = 14
    offline_threshold_minutes: int = 30
    stale_days: int = 14
    tz_offset_hours: int = 2
    upload_alert_consecutive: int = 3
    upload_lookback_packets: int = 6
    offline_state_file: str = "/data/offline_state.json"
    upload_state_file: str = "/data/upload_state.json"


def load_settings(env: Mapping[str, str]) -> Settings:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")

    def _int(name, default):
        return int(env.get(name, default))

    return Settings(
        db_host=env["DB_HOST"],
        db_port=int(env["DB_PORT"]),
        db_name=env["DB_NAME"],
        db_user=env["DB_USER"],
        db_pass=env["DB_PASS"],
        teams_webhook_url=env["TEAMS_WEBHOOK_URL"],
        chart_dir=env.get("CHART_DIR", "/data/charts"),
        chart_public_base_url=env.get("CHART_PUBLIC_BASE_URL", ""),
        chart_retention_days=_int("CHART_RETENTION_DAYS", 14),
        offline_threshold_minutes=_int("OFFLINE_THRESHOLD_MINUTES", 30),
        stale_days=_int("STALE_DAYS", 14),
        tz_offset_hours=_int("REPORT_TZ_OFFSET_HOURS", 2),
        upload_alert_consecutive=_int("UPLOAD_ALERT_CONSECUTIVE", 3),
        upload_lookback_packets=_int("UPLOAD_LOOKBACK_PACKETS", 6),
        offline_state_file=env.get("OFFLINE_STATE_FILE", "/data/offline_state.json"),
        upload_state_file=env.get("UPLOAD_STATE_FILE", "/data/upload_state.json"),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_config.py" -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add roles/s1_reporter/files/app roles/s1_reporter/tests/_bootstrap.py roles/s1_reporter/tests/test_config.py
git commit -m "feat(s1_reporter): package skeleton and Settings loader

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Local-day windows

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/timewin.py`
- Test: `roles/s1_reporter/tests/test_timewin.py`

**Interfaces:**
- Produces: `local_date(now_utc: datetime, offset_hours: int) -> date`; `daily_window(now_utc, offset_hours, days=7) -> (start_date, end_date)` inclusive local dates ending yesterday; `previous_month(now_utc, offset_hours) -> (start_date, end_date)`; `utc_bounds(start_date, end_date, offset_hours) -> (start_utc: datetime, end_utc_exclusive: datetime)`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_timewin.py`:

```python
import unittest
from datetime import date, datetime

import _bootstrap  # noqa: F401
from s1_reporter import timewin


class TestTimeWindows(unittest.TestCase):
    def test_local_date_crosses_midnight(self):
        # 23:30 UTC on the 8th is 01:30 SAST on the 9th
        self.assertEqual(timewin.local_date(datetime(2026, 9, 8, 23, 30), 2), date(2026, 9, 9))

    def test_daily_window_ends_yesterday(self):
        start, end = timewin.daily_window(datetime(2026, 9, 9, 4, 0), 2, days=7)
        self.assertEqual(end, date(2026, 9, 8))
        self.assertEqual(start, date(2026, 9, 2))

    def test_previous_month_from_first(self):
        start, end = timewin.previous_month(datetime(2026, 9, 1, 4, 30), 2)
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_previous_month_january(self):
        start, end = timewin.previous_month(datetime(2027, 1, 1, 4, 30), 2)
        self.assertEqual((start, end), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_utc_bounds_shift_by_offset(self):
        s, e = timewin.utc_bounds(date(2026, 9, 8), date(2026, 9, 8), 2)
        self.assertEqual(s, datetime(2026, 9, 7, 22, 0))
        self.assertEqual(e, datetime(2026, 9, 8, 22, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_timewin.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write timewin.py**

```python
"""Local-day windows. DB timestamps are UTC; reports are about SAST days (UTC+offset, no DST)."""
from datetime import date, datetime, timedelta


def local_date(now_utc: datetime, offset_hours: int) -> date:
    return (now_utc + timedelta(hours=offset_hours)).date()


def daily_window(now_utc: datetime, offset_hours: int, days: int = 7):
    """Inclusive local date range of `days` complete days ending yesterday."""
    end = local_date(now_utc, offset_hours) - timedelta(days=1)
    return end - timedelta(days=days - 1), end


def previous_month(now_utc: datetime, offset_hours: int):
    today = local_date(now_utc, offset_hours)
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def utc_bounds(start_date: date, end_date: date, offset_hours: int):
    """[start, end) UTC datetimes covering the inclusive local date range."""
    off = timedelta(hours=offset_hours)
    start = datetime.combine(start_date, datetime.min.time()) - off
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time()) - off
    return start, end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_timewin.py" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/timewin.py roles/s1_reporter/tests/test_timewin.py
git commit -m "feat(s1_reporter): local-day window helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Database wrapper and migrations runner

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/db.py`
- Create: `roles/s1_reporter/files/app/migrations/001_customer_config.sql`
- Create: `roles/s1_reporter/files/app/migrations/002_device_flags.sql`
- Test: `roles/s1_reporter/tests/test_db.py`

**Interfaces:**
- Produces: `split_batches(sql_text) -> list[str]`; `class Database(settings, connect=None)` with `query(sql, params=None) -> list[dict]`, `execute(sql, params=None) -> int`, `executemany(sql, seq) -> None`, `run_migrations(migrations_dir) -> list[str]`, context manager closing the connection. `QueryFn = Callable[[str, tuple | None], list[dict]]` is the type every rule module accepts.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_db.py`:

```python
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
            open(os.path.join(tmp, "002_b.sql"), "w").write("B;\n")
            open(os.path.join(tmp, "001_a.sql"), "w").write("A1;\nGO\nA2;\n")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_db.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write db.py**

```python
"""The only module that imports pymssql."""
import os
from typing import Callable, Iterable, Optional, Sequence

QueryFn = Callable[[str, Optional[tuple]], list]


def split_batches(sql_text: str) -> list:
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


def _pymssql_connect(settings):
    import pymssql  # imported here so tests never need it
    return pymssql.connect(
        server=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_pass,
        database=settings.db_name, timeout=30,
    )


class Database:
    def __init__(self, settings, connect=None):
        self._conn = (connect or _pymssql_connect)(settings)

    def query(self, sql: str, params: Optional[tuple] = None) -> list:
        with self._conn.cursor(as_dict=True) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.rowcount
        self._conn.commit()
        return count

    def executemany(self, sql: str, seq: Iterable[Sequence]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(sql, seq)
        self._conn.commit()

    def run_migrations(self, migrations_dir: str) -> list:
        applied = []
        for name in sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql")):
            with open(os.path.join(migrations_dir, name), encoding="utf-8") as fh:
                batches = split_batches(fh.read())
            with self._conn.cursor() as cur:
                for batch in batches:
                    cur.execute(batch)
            self._conn.commit()
            applied.append(name)
        return applied

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False
```

- [ ] **Step 4: Write the migrations**

`roles/s1_reporter/files/app/migrations/001_customer_config.sql`:

```sql
-- Per-customer capabilities and alert limits, replacing CUSTOMER_CAPS in code.
IF OBJECT_ID(N'dbo.customer_config', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.customer_config (
        customer            NVARCHAR(100) NOT NULL PRIMARY KEY,
        has_dimension       BIT NOT NULL DEFAULT 1,
        has_weight          BIT NOT NULL DEFAULT 0,
        has_hand_scan       BIT NOT NULL DEFAULT 0,
        hand_scan_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 15.0,
        no_weight_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 5.0,
        storage_warn_pct    DECIMAL(5,2) NOT NULL DEFAULT 80.0,
        storage_bad_pct     DECIMAL(5,2) NOT NULL DEFAULT 90.0,
        good_read_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 95.0,
        good_read_bad_pct   DECIMAL(5,2) NOT NULL DEFAULT 90.0,
        no_dim_warn_pct     DECIMAL(5,2) NOT NULL DEFAULT 5.0,
        no_dim_bad_pct      DECIMAL(5,2) NOT NULL DEFAULT 10.0,
        reports_enabled     BIT NOT NULL DEFAULT 1,
        updated_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- Seed the four customers that had explicit capabilities in the old code.
MERGE dbo.customer_config AS t
USING (VALUES
    (N'PEPKOR',   1, 0, 0),
    (N'MADIBANA', 1, 1, 1),
    (N'PEP',      0, 0, 0),
    (N'SNOWSOFT', 0, 0, 0)
) AS s (customer, has_dimension, has_weight, has_hand_scan)
ON t.customer = s.customer
WHEN NOT MATCHED THEN
    INSERT (customer, has_dimension, has_weight, has_hand_scan)
    VALUES (s.customer, s.has_dimension, s.has_weight, s.has_hand_scan);
GO

-- Every other customer known to devices gets a defaults row.
INSERT INTO dbo.customer_config (customer)
SELECT DISTINCT d.customer
FROM dbo.devices d
WHERE NOT EXISTS (SELECT 1 FROM dbo.customer_config c WHERE c.customer = d.customer);
GO
```

`roles/s1_reporter/files/app/migrations/002_device_flags.sql`:

```sql
-- Reporting flags on devices. mqtt_ingestor inserts with an explicit column list, unaffected.
IF COL_LENGTH(N'dbo.devices', N'reporting_enabled') IS NULL
BEGIN
    ALTER TABLE dbo.devices ADD reporting_enabled BIT NOT NULL CONSTRAINT DF_devices_reporting_enabled DEFAULT 1;
END
GO

IF COL_LENGTH(N'dbo.devices', N'muted_until') IS NULL
BEGIN
    ALTER TABLE dbo.devices ADD muted_until DATETIME2 NULL;
END
GO

-- The one standby line that was hard-coded as an exclusion in the old reporter.
UPDATE dbo.devices SET reporting_enabled = 0
WHERE machine_name = N'DIM2' AND location = N'JBH' AND reporting_enabled = 1;
GO
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_db.py" -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add roles/s1_reporter/files/app roles/s1_reporter/tests/test_db.py
git commit -m "feat(s1_reporter): Database wrapper, migration runner, customer_config and device flag migrations

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Customer configuration and threshold lookup

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/customers.py`
- Create: `roles/s1_reporter/files/app/s1_reporter/thresholds.py`
- Test: `roles/s1_reporter/tests/test_customers.py`, `roles/s1_reporter/tests/test_thresholds.py`

**Interfaces:**
- Produces: `CustomerConfig` dataclass (fields mirror the `customer_config` columns, same defaults); `load_customer_configs(query) -> dict[str, CustomerConfig]`; `config_for(configs, customer) -> CustomerConfig`.
- Produces: `load_thresholds(query) -> dict[tuple, tuple]` keyed `(customer, machine_name, location, metric)`; `lookup(thresholds, cfg, customer, machine_name, location, metric) -> (warn, bad)` where `metric in {"good_read_pct", "no_dim_pct"}`.

- [ ] **Step 1: Write the failing tests**

`roles/s1_reporter/tests/test_customers.py`:

```python
import unittest

import _bootstrap  # noqa: F401
from s1_reporter.customers import CustomerConfig, config_for, load_customer_configs


def fake_query(rows):
    def q(sql, params=None):
        assert "customer_config" in sql
        return rows
    return q


class TestCustomers(unittest.TestCase):
    def test_loads_rows_into_dataclasses(self):
        rows = [{"customer": "MADIBANA", "has_dimension": True, "has_weight": True, "has_hand_scan": True,
                 "hand_scan_warn_pct": 15, "no_weight_warn_pct": 5, "storage_warn_pct": 80, "storage_bad_pct": 90,
                 "good_read_warn_pct": 95, "good_read_bad_pct": 90, "no_dim_warn_pct": 5, "no_dim_bad_pct": 10,
                 "reports_enabled": True}]
        cfgs = load_customer_configs(fake_query(rows))
        self.assertEqual(set(cfgs), {"MADIBANA"})
        self.assertTrue(cfgs["MADIBANA"].has_weight)
        self.assertEqual(cfgs["MADIBANA"].storage_bad_pct, 90.0)

    def test_unknown_customer_gets_defaults(self):
        cfg = config_for({}, "NEWCO")
        self.assertEqual(cfg, CustomerConfig(customer="NEWCO"))
        self.assertTrue(cfg.has_dimension)
        self.assertFalse(cfg.has_weight)
        self.assertEqual(cfg.good_read_warn_pct, 95.0)
        self.assertTrue(cfg.reports_enabled)


if __name__ == "__main__":
    unittest.main()
```

`roles/s1_reporter/tests/test_thresholds.py`:

```python
import unittest

import _bootstrap  # noqa: F401
from s1_reporter.customers import CustomerConfig
from s1_reporter.thresholds import load_thresholds, lookup

CFG = CustomerConfig(customer="A", good_read_warn_pct=95, good_read_bad_pct=90,
                     no_dim_warn_pct=5, no_dim_bad_pct=10)


class TestThresholds(unittest.TestCase):
    def test_load_keys_and_floats(self):
        rows = [{"customer": "A", "machine_name": "DIM1", "location": "JHB", "metric": "good_read_pct",
                 "warn_value": 77.5, "bad_value": 70.0},
                {"customer": "A", "machine_name": None, "location": None, "metric": "no_dim_pct",
                 "warn_value": 3.0, "bad_value": None}]
        t = load_thresholds(lambda sql, params=None: rows)
        self.assertEqual(t[("A", "DIM1", "JHB", "good_read_pct")], (77.5, 70.0))
        self.assertEqual(t[("A", None, None, "no_dim_pct")], (3.0, None))

    def test_device_row_wins(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (77.5, 70.0), ("A", None, None, "good_read_pct"): (93.0, 88.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM1", "JHB", "good_read_pct"), (77.5, 70.0))

    def test_customer_row_when_no_device_row(self):
        t = {("A", None, None, "good_read_pct"): (93.0, 88.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM9", "CPT", "good_read_pct"), (93.0, 88.0))

    def test_config_fallback(self):
        self.assertEqual(lookup({}, CFG, "A", "DIM9", "CPT", "good_read_pct"), (95.0, 90.0))
        self.assertEqual(lookup({}, CFG, "A", "DIM9", "CPT", "no_dim_pct"), (5.0, 10.0))

    def test_row_with_null_warn_falls_through(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (None, 70.0)}
        self.assertEqual(lookup(t, CFG, "A", "DIM1", "JHB", "good_read_pct"), (95.0, 90.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_customers.py" -v` and the same for `test_thresholds.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write customers.py**

```python
"""Customer capabilities and alert limits, loaded from dbo.customer_config."""
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CustomerConfig:
    customer: str
    has_dimension: bool = True
    has_weight: bool = False
    has_hand_scan: bool = False
    hand_scan_warn_pct: float = 15.0
    no_weight_warn_pct: float = 5.0
    storage_warn_pct: float = 80.0
    storage_bad_pct: float = 90.0
    good_read_warn_pct: float = 95.0
    good_read_bad_pct: float = 90.0
    no_dim_warn_pct: float = 5.0
    no_dim_bad_pct: float = 10.0
    reports_enabled: bool = True


_SQL = "SELECT " + ", ".join(f.name for f in fields(CustomerConfig)) + " FROM dbo.customer_config"


def _coerce(field, value):
    if field.type is bool:
        return bool(value)
    if field.type is float:
        return float(value)
    return value


def load_customer_configs(query) -> dict:
    configs = {}
    for row in query(_SQL, None):
        kwargs = {f.name: _coerce(f, row[f.name]) for f in fields(CustomerConfig)}
        configs[kwargs["customer"]] = CustomerConfig(**kwargs)
    return configs


def config_for(configs: dict, customer: str) -> CustomerConfig:
    """Defaults for a customer that has no row yet (the next `migrate` inserts one)."""
    return configs.get(customer) or CustomerConfig(customer=customer)
```

- [ ] **Step 4: Write thresholds.py**

```python
"""Per-device alert thresholds from dbo.alert_thresholds with a customer-config fallback."""

_SQL = ("SELECT customer, machine_name, location, metric, warn_value, bad_value "
        "FROM dbo.alert_thresholds")


def _f(v):
    return float(v) if v is not None else None


def load_thresholds(query) -> dict:
    return {
        (r["customer"], r["machine_name"], r["location"], r["metric"]): (_f(r["warn_value"]), _f(r["bad_value"]))
        for r in query(_SQL, None)
    }


def lookup(thresholds, cfg, customer, machine_name, location, metric):
    """Device row, then customer-wide row, then the customer_config fallback columns."""
    for key in ((customer, machine_name, location, metric), (customer, None, None, metric)):
        val = thresholds.get(key)
        if val and val[0] is not None:
            return val
    if metric == "good_read_pct":
        return cfg.good_read_warn_pct, cfg.good_read_bad_pct
    if metric == "no_dim_pct":
        return cfg.no_dim_warn_pct, cfg.no_dim_bad_pct
    raise KeyError(metric)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: all PASS (config 3, timewin 5, db 7, customers 2, thresholds 5).

- [ ] **Step 6: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/customers.py roles/s1_reporter/files/app/s1_reporter/thresholds.py roles/s1_reporter/tests/test_customers.py roles/s1_reporter/tests/test_thresholds.py
git commit -m "feat(s1_reporter): customer config from DB and threshold lookup chain

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Liveness classification

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/liveness.py`
- Test: `roles/s1_reporter/tests/test_liveness.py`

**Interfaces:**
- Produces: `Device(id, customer, machine_name, location, last_seen: datetime|None, created_at: datetime, reporting_enabled: bool, muted_until: datetime|None)`; `DeviceState(device, state: str, last_seen: datetime, minutes_ago: int)` with `state in {"online","offline","stale","never"}`; `fetch_devices(query) -> list[Device]`; `classify(devices, now_utc, offline_threshold_min, stale_days) -> list[DeviceState]` (only `reporting_enabled` devices); `alertable_offline(states, now_utc) -> list[DeviceState]`; `stale_devices(states) -> list[DeviceState]`; `key(state_or_device) -> str` = `"MACHINE@LOCATION"`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_liveness.py`:

```python
import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import liveness
from s1_reporter.liveness import Device

NOW = datetime(2026, 9, 9, 7, 0)


def dev(name, last_seen_min_ago=None, created_days_ago=100, enabled=True, muted_until=None, loc="JHB"):
    last = NOW - timedelta(minutes=last_seen_min_ago) if last_seen_min_ago is not None else None
    return Device(id=1, customer="A", machine_name=name, location=loc, last_seen=last,
                  created_at=NOW - timedelta(days=created_days_ago), reporting_enabled=enabled,
                  muted_until=muted_until)


class TestClassify(unittest.TestCase):
    def _one(self, d):
        return liveness.classify([d], NOW, offline_threshold_min=30, stale_days=14)[0]

    def test_online(self):
        self.assertEqual(self._one(dev("D", 5)).state, "online")

    def test_offline_at_threshold(self):
        s = self._one(dev("D", 30))
        self.assertEqual(s.state, "offline")
        self.assertEqual(s.minutes_ago, 30)

    def test_stale_after_stale_days(self):
        self.assertEqual(self._one(dev("D", 14 * 24 * 60)).state, "stale")

    def test_never_reported_uses_created_at(self):
        s = self._one(dev("D", None, created_days_ago=2))
        self.assertEqual(s.state, "never")
        self.assertEqual(s.last_seen, NOW - timedelta(days=2))

    def test_never_reported_and_old_is_stale(self):
        self.assertEqual(self._one(dev("D", None, created_days_ago=60)).state, "stale")

    def test_disabled_devices_are_dropped(self):
        self.assertEqual(liveness.classify([dev("D", 5, enabled=False)], NOW, 30, 14), [])


class TestSelections(unittest.TestCase):
    def test_alertable_excludes_stale_and_muted(self):
        states = liveness.classify([
            dev("OFF", 60), dev("MUTED", 60, muted_until=NOW + timedelta(hours=1), loc="CPT"),
            dev("EXPIRED", 60, muted_until=NOW - timedelta(hours=1), loc="DUR"),
            dev("STALE", 30 * 24 * 60, loc="PE"), dev("ON", 1, loc="BFN"),
        ], NOW, 30, 14)
        names = sorted(s.device.machine_name for s in liveness.alertable_offline(states, NOW))
        self.assertEqual(names, ["EXPIRED", "OFF"])

    def test_stale_devices(self):
        states = liveness.classify([dev("STALE", 30 * 24 * 60), dev("ON", 1, loc="CPT")], NOW, 30, 14)
        self.assertEqual([s.device.machine_name for s in liveness.stale_devices(states)], ["STALE"])

    def test_key(self):
        self.assertEqual(liveness.key(dev("DIM1", 1, loc="JHB")), "DIM1@JHB")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_liveness.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write liveness.py**

```python
"""Device liveness from observed telemetry. Never trusts what devices say about themselves."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_SQL = """
SELECT d.id, d.customer, d.machine_name, d.location, d.created_at,
       d.reporting_enabled, d.muted_until,
       MAX(ds.ts_datetime) AS last_seen
FROM dbo.devices d
LEFT JOIN dbo.device_statistics ds ON ds.device_id = d.id
GROUP BY d.id, d.customer, d.machine_name, d.location, d.created_at,
         d.reporting_enabled, d.muted_until
"""


@dataclass(frozen=True)
class Device:
    id: int
    customer: str
    machine_name: str
    location: str
    last_seen: Optional[datetime]
    created_at: datetime
    reporting_enabled: bool
    muted_until: Optional[datetime]


@dataclass(frozen=True)
class DeviceState:
    device: Device
    state: str          # online | offline | stale | never
    last_seen: datetime  # effective: created_at when the device never reported
    minutes_ago: int


def key(obj) -> str:
    d = obj.device if isinstance(obj, DeviceState) else obj
    return f"{d.machine_name}@{d.location}"


def fetch_devices(query) -> list:
    return [
        Device(id=r["id"], customer=r["customer"], machine_name=r["machine_name"], location=r["location"],
               last_seen=r["last_seen"], created_at=r["created_at"],
               reporting_enabled=bool(r["reporting_enabled"]), muted_until=r["muted_until"])
        for r in query(_SQL, None)
    ]


def classify(devices, now_utc: datetime, offline_threshold_min: int, stale_days: int) -> list:
    out = []
    stale_cutoff = timedelta(days=stale_days)
    for d in devices:
        if not d.reporting_enabled:
            continue
        never = d.last_seen is None
        last = d.created_at if never else d.last_seen
        age = now_utc - last
        minutes = max(int(age.total_seconds() // 60), 0)
        if age >= stale_cutoff:
            state = "stale"
        elif never:
            state = "never"
        elif minutes >= offline_threshold_min:
            state = "offline"
        else:
            state = "online"
        out.append(DeviceState(device=d, state=state, last_seen=last, minutes_ago=minutes))
    return out


def alertable_offline(states, now_utc: datetime) -> list:
    return [
        s for s in states
        if s.state in ("offline", "never")
        and not (s.device.muted_until and s.device.muted_until > now_utc)
    ]


def stale_devices(states) -> list:
    return [s for s in states if s.state == "stale"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_liveness.py" -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/liveness.py roles/s1_reporter/tests/test_liveness.py
git commit -m "feat(s1_reporter): liveness classification with stale and muted devices

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Status sync via MERGE

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/status_sync.py`
- Test: `roles/s1_reporter/tests/test_status_sync.py`

**Interfaces:**
- Consumes: `DeviceState` from Task 5.
- Produces: `rows_for_merge(states) -> list[tuple]` of `(device_id, status, last_seen, last_seen, offline_since_or_None)`; `sync(executemany, states) -> (online_count, offline_count)`; module constant `MERGE_SQL`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_status_sync.py`:

```python
import unittest
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import status_sync
from s1_reporter.liveness import Device, DeviceState

NOW = datetime(2026, 9, 9, 7, 0)


def st(dev_id, state, minutes):
    last = NOW - timedelta(minutes=minutes)
    d = Device(id=dev_id, customer="A", machine_name=f"D{dev_id}", location="JHB", last_seen=last,
               created_at=NOW - timedelta(days=9), reporting_enabled=True, muted_until=None)
    return DeviceState(device=d, state=state, last_seen=last, minutes_ago=minutes)


class TestStatusSync(unittest.TestCase):
    def test_rows_and_counts(self):
        calls = []
        counts = status_sync.sync(lambda sql, rows: calls.append((sql, rows)),
                                  [st(1, "online", 1), st(2, "offline", 45), st(3, "stale", 30000), st(4, "never", 60)])
        self.assertEqual(counts, (1, 3))
        sql, rows = calls[0]
        self.assertIs(sql, status_sync.MERGE_SQL)
        self.assertEqual(rows[0], (1, "online", NOW - timedelta(minutes=1), NOW - timedelta(minutes=1), None))
        self.assertEqual(rows[1][1], "offline")
        self.assertEqual(rows[1][4], NOW - timedelta(minutes=45))  # offline_since candidate
        self.assertEqual(rows[2][1], "offline")                    # stale writes as offline
        self.assertEqual(rows[3][1], "offline")                    # never writes as offline

    def test_merge_preserves_existing_offline_since(self):
        self.assertIn("COALESCE(t.offline_since, s.offline_since)", status_sync.MERGE_SQL)
        self.assertIn("WHEN NOT MATCHED", status_sync.MERGE_SQL)

    def test_no_states_no_call(self):
        calls = []
        self.assertEqual(status_sync.sync(lambda s, r: calls.append(1), []), (0, 0))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_status_sync.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write status_sync.py**

```python
"""Writes the observed online/offline truth into dbo.device_status in one MERGE per run."""

MERGE_SQL = """
MERGE dbo.device_status AS t
USING (SELECT %s AS device_id, %s AS status, %s AS ts_datetime, %s AS ts_datetime2, %s AS offline_since) AS s
    ON t.device_id = s.device_id
WHEN MATCHED THEN UPDATE SET
    status        = s.status,
    ts_epoch      = DATEDIFF_BIG(second, '19700101', s.ts_datetime),
    ts_datetime   = s.ts_datetime,
    offline_since = CASE WHEN s.status = 'offline'
                         THEN COALESCE(t.offline_since, s.offline_since)
                         ELSE NULL END,
    updated_at    = SYSUTCDATETIME()
WHEN NOT MATCHED THEN INSERT
    (device_id, status, ts_epoch, ts_datetime, offline_since, created_at, updated_at)
    VALUES (s.device_id, s.status, DATEDIFF_BIG(second, '19700101', s.ts_datetime), s.ts_datetime,
            s.offline_since, SYSUTCDATETIME(), SYSUTCDATETIME());
"""


def rows_for_merge(states) -> list:
    rows = []
    for s in states:
        status = "online" if s.state == "online" else "offline"
        offline_since = s.last_seen if status == "offline" else None
        rows.append((s.device.id, status, s.last_seen, s.last_seen, offline_since))
    return rows


def sync(executemany, states):
    rows = rows_for_merge(states)
    if not rows:
        return 0, 0
    executemany(MERGE_SQL, rows)
    online = sum(1 for r in rows if r[1] == "online")
    return online, len(rows) - online
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_status_sync.py" -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/status_sync.py roles/s1_reporter/tests/test_status_sync.py
git commit -m "feat(s1_reporter): device_status sync as a single MERGE statement

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Alert state with commit-after-send

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/state.py`
- Test: `roles/s1_reporter/tests/test_state.py`

**Interfaces:**
- Produces: `class AlertState(path)`; `.load() -> dict`; `.diff(current: dict[str, dict], now: datetime) -> Diff` where `Diff(new: list[dict], recovered: list[dict], unchanged: list[dict], pending: dict)`; recovered entries carry `downtime_minutes`; `.commit(pending: dict) -> None` writes the file. Current entries are dicts already serialisable; `alerted_at` is added/preserved by `diff`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_state.py`:

```python
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
        open(self.path, "w").write("{not json")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_state.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write state.py**

```python
"""JSON alert state on the data volume. diff() never writes; commit() does, after Teams accepted."""
import json
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Diff:
    new: list
    recovered: list
    unchanged: list
    pending: dict


def _downtime_minutes(alerted_at, now: datetime) -> int:
    try:
        started = datetime.fromisoformat(str(alerted_at))
    except (TypeError, ValueError):
        return 0
    return max(int((now - started).total_seconds() // 60), 0)


class AlertState:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def diff(self, current: dict, now: datetime) -> Diff:
        prev = self.load()
        new = [d for k, d in current.items() if k not in prev]
        unchanged = [d for k, d in current.items() if k in prev]
        recovered = []
        for k, d in prev.items():
            if k not in current:
                entry = dict(d)
                entry["downtime_minutes"] = _downtime_minutes(d.get("alerted_at"), now)
                recovered.append(entry)
        pending = {}
        for k, d in current.items():
            entry = {kk: (str(v) if isinstance(v, datetime) else v) for kk, v in d.items()}
            entry["alerted_at"] = prev[k]["alerted_at"] if k in prev and "alerted_at" in prev[k] else now.isoformat()
            pending[k] = entry
        return Diff(new=new, recovered=recovered, unchanged=unchanged, pending=pending)

    def commit(self, pending: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(pending, fh, indent=2, default=str)
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_state.py" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/state.py roles/s1_reporter/tests/test_state.py
git commit -m "feat(s1_reporter): alert state with commit-after-send semantics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Upload-failure detection

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/upload.py`
- Test: `roles/s1_reporter/tests/test_upload.py`

**Interfaces:**
- Produces: `fetch_recent_packets(query, lookback: int) -> list[dict]` (rows with `machine_name, location, customer, ts_datetime, total_items, not_sent, rn`, only `reporting_enabled = 1` devices); `detect_upload_failures(rows, consecutive: int) -> list[dict]` each with `machine_name, location, customer, total_not_sent, latest_ts`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_upload.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_upload.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write upload.py**

```python
"""Devices whose last N scanning packets all have not_sent > 0: the upload service is stuck."""

_SQL = """
SELECT machine_name, location, customer, ts_datetime, total_items, not_sent, rn
FROM (
    SELECT d.machine_name, d.location, d.customer,
           ds.ts_datetime, ds.total_items, ds.not_sent,
           ROW_NUMBER() OVER (PARTITION BY d.id ORDER BY ds.ts_datetime DESC) AS rn
    FROM dbo.devices d
    JOIN dbo.device_statistics ds ON ds.device_id = d.id
    WHERE d.reporting_enabled = 1
) x
WHERE rn <= %s
ORDER BY machine_name, location, rn
"""


def fetch_recent_packets(query, lookback: int) -> list:
    return query(_SQL, (lookback,))


def detect_upload_failures(rows, consecutive: int) -> list:
    by_device = {}
    for r in rows:
        by_device.setdefault((r["machine_name"], r["location"]), []).append(r)

    failing = []
    for (machine, location), packets in by_device.items():
        recent = sorted(packets, key=lambda p: p["rn"])[:consecutive]
        if len(recent) < consecutive:
            continue
        if all((p["total_items"] or 0) > 0 and (p["not_sent"] or 0) > 0 for p in recent):
            failing.append({
                "machine_name": machine,
                "location": location,
                "customer": recent[0]["customer"],
                "total_not_sent": sum(int(p["not_sent"] or 0) for p in recent),
                "latest_ts": max(p["ts_datetime"] for p in recent),
            })
    return sorted(failing, key=lambda d: d["total_not_sent"], reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_upload.py" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/upload.py roles/s1_reporter/tests/test_upload.py
git commit -m "feat(s1_reporter): upload-failure detection as a tested module

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Anomaly rules

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/anomalies.py`
- Test: `roles/s1_reporter/tests/test_anomalies.py`

**Interfaces:**
- Consumes: `CustomerConfig`, `thresholds.lookup`, `DeviceState`.
- Produces: `detect(day_rows, storage_rows, offline_states, cfg, thresholds) -> list[tuple[str, str]]` of `(severity, message)` with severity `"bad"|"warn"`, messages plain text (no HTML); `format_lines(anomalies) -> list[str]` prefixing `🔴` / `⚠️`. `day_rows` are per-device-per-day dicts with keys `machine_name, location, customer, report_date, daily_items, daily_good, daily_no_dim, daily_hand_scanned, daily_no_weight, good_read_pct`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_anomalies.py`:

```python
import unittest
from datetime import date, datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter import anomalies
from s1_reporter.customers import CustomerConfig
from s1_reporter.liveness import Device, DeviceState

NOW = datetime(2026, 9, 9, 7, 0)
CFG = CustomerConfig(customer="A", has_dimension=True, has_weight=True, has_hand_scan=True)


def row(machine="DIM1", items=1000, good=None, no_dim=0, hand=0, no_weight=0, day=date(2026, 9, 8)):
    good = items if good is None else good
    return {"machine_name": machine, "location": "JHB", "customer": "A", "report_date": day,
            "daily_items": items, "daily_good": good, "daily_no_dim": no_dim,
            "daily_hand_scanned": hand, "daily_no_weight": no_weight,
            "good_read_pct": round(good * 100.0 / items, 1) if items else None}


def offline(machine, minutes):
    d = Device(id=1, customer="A", machine_name=machine, location="JHB", last_seen=NOW - timedelta(minutes=minutes),
               created_at=NOW - timedelta(days=5), reporting_enabled=True, muted_until=None)
    return DeviceState(device=d, state="offline", last_seen=d.last_seen, minutes_ago=minutes)


class TestGoodRead(unittest.TestCase):
    def test_uses_device_threshold_from_table(self):
        t = {("A", "DIM1", "JHB", "good_read_pct"): (77.5, 70.0)}
        out = anomalies.detect([row(good=750)], [], [], CFG, t)   # 75.0% < warn 77.5, > bad 70
        self.assertEqual(out, [("warn", "DIM1 @ JHB: good read 75.0% on 2026-09-08 (warn below 77.5%)")])

    def test_bad_when_below_bad(self):
        out = anomalies.detect([row(good=600)], [], [], CFG, {})   # 60% < cfg bad 90
        self.assertEqual(out[0][0], "bad")

    def test_small_volume_rows_ignored(self):
        self.assertEqual(anomalies.detect([row(items=50, good=10)], [], [], CFG, {}), [])


class TestCapabilityRules(unittest.TestCase):
    def test_no_dim_uses_table_then_config(self):
        out = anomalies.detect([row(no_dim=60)], [], [], CFG, {})   # 6% > cfg warn 5
        self.assertEqual(out[0], ("warn", "DIM1 @ JHB: no-dimension 6.0% on 2026-09-08 (warn above 5.0%)"))

    def test_no_dim_skipped_without_capability(self):
        cfg = CustomerConfig(customer="A", has_dimension=False)
        self.assertEqual(anomalies.detect([row(no_dim=600)], [], [], cfg, {}), [])

    def test_hand_scan_and_no_weight(self):
        out = anomalies.detect([row(hand=200, no_weight=60)], [], [], CFG, {})
        msgs = [m for _, m in out]
        self.assertIn("DIM1 @ JHB: hand-scanned 20.0% on 2026-09-08 (warn above 15.0%)", msgs)
        self.assertIn("DIM1 @ JHB: no-weight 6.0% on 2026-09-08 (warn above 5.0%)", msgs)


class TestStorageAndOffline(unittest.TestCase):
    def test_storage_levels(self):
        storage = [{"machine_name": "DIM1", "location": "JHB", "usage_percent": 91},
                   {"machine_name": "DIM2", "location": "JHB", "usage_percent": 85},
                   {"machine_name": "DIM3", "location": "JHB", "usage_percent": 50}]
        out = anomalies.detect([], storage, [], CFG, {})
        self.assertEqual([s for s, _ in out], ["bad", "warn"])
        self.assertIn("C: drive at 91%", out[0][1])

    def test_offline_states_listed_as_bad(self):
        out = anomalies.detect([], [], [offline("DIM1", 125)], CFG, {})
        self.assertEqual(out, [("bad", "DIM1 @ JHB: no data for 2h 5m (last seen 2026-09-09 04:55 UTC)")])


class TestFormat(unittest.TestCase):
    def test_icons(self):
        self.assertEqual(anomalies.format_lines([("bad", "x"), ("warn", "y")]), ["🔴 x", "⚠️ y"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_anomalies.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write anomalies.py**

```python
"""Pure anomaly rules. Inputs are rows and states; output is (severity, message) pairs."""
from . import thresholds as th

MIN_ITEMS_FOR_RATE_RULES = 100
_ICON = {"bad": "🔴", "warn": "⚠️"}


def _pct(part, whole):
    return float(part or 0) / float(whole) * 100.0


def _label(r):
    return f"{r['machine_name']} @ {r['location']}"


def _low_rule(alerts, r, value, warn, bad, name):
    if bad is not None and value < bad:
        alerts.append(("bad", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (bad below {bad:.1f}%)"))
    elif warn is not None and value < warn:
        alerts.append(("warn", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (warn below {warn:.1f}%)"))


def _high_rule(alerts, r, value, warn, bad, name):
    if bad is not None and value > bad:
        alerts.append(("bad", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (bad above {bad:.1f}%)"))
    elif warn is not None and value > warn:
        alerts.append(("warn", f"{_label(r)}: {name} {value:.1f}% on {r['report_date']} (warn above {warn:.1f}%)"))


def detect(day_rows, storage_rows, offline_states, cfg, thresholds) -> list:
    alerts = []
    for r in day_rows:
        items = r.get("daily_items") or 0
        if items <= MIN_ITEMS_FOR_RATE_RULES:
            continue
        ident = (r["customer"], r["machine_name"], r["location"])

        warn, bad = th.lookup(thresholds, cfg, *ident, "good_read_pct")
        _low_rule(alerts, r, _pct(r.get("daily_good"), items), warn, bad, "good read")

        if cfg.has_dimension:
            warn, bad = th.lookup(thresholds, cfg, *ident, "no_dim_pct")
            _high_rule(alerts, r, _pct(r.get("daily_no_dim"), items), warn, bad, "no-dimension")
        if cfg.has_hand_scan:
            _high_rule(alerts, r, _pct(r.get("daily_hand_scanned"), items), cfg.hand_scan_warn_pct, None, "hand-scanned")
        if cfg.has_weight:
            _high_rule(alerts, r, _pct(r.get("daily_no_weight"), items), cfg.no_weight_warn_pct, None, "no-weight")

    for s in storage_rows:
        pct = float(s.get("usage_percent") or 0)
        if pct > cfg.storage_bad_pct:
            alerts.append(("bad", f"{_label(s)}: C: drive at {pct:.0f}% (action required)"))
        elif pct > cfg.storage_warn_pct:
            alerts.append(("warn", f"{_label(s)}: C: drive at {pct:.0f}% (monitor)"))

    for st in offline_states:
        age = st.minutes_ago
        age_str = f"{age // 60}h {age % 60}m" if age >= 60 else f"{age}m"
        alerts.append(("bad", f"{st.device.machine_name} @ {st.device.location}: no data for {age_str} "
                              f"(last seen {st.last_seen:%Y-%m-%d %H:%M} UTC)"))
    return alerts


def format_lines(alerts) -> list:
    return [f"{_ICON.get(sev, '•')} {msg}" for sev, msg in alerts]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_anomalies.py" -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/anomalies.py roles/s1_reporter/tests/test_anomalies.py
git commit -m "feat(s1_reporter): anomaly rules driven by alert_thresholds and customer_config

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Move cards, teams and chart_store into the package; add the stale digest card

**Files:**
- Move: `roles/s1_reporter/files/cards.py` -> `roles/s1_reporter/files/app/s1_reporter/cards.py`
- Move: `roles/s1_reporter/files/teams_notifier.py` -> `roles/s1_reporter/files/app/s1_reporter/teams.py`
- Move: `roles/s1_reporter/files/chart_store.py` -> `roles/s1_reporter/files/app/s1_reporter/chart_store.py`
- Modify: `roles/s1_reporter/tests/test_cards.py`, `test_teams_notifier.py`, `test_chart_store.py` (imports)
- Test: add `TestStaleDigestCard` to `test_cards.py`

**Interfaces:**
- Produces: `cards.build_stale_digest_card(stale: list[dict]) -> dict` where each item has `machine_name, location, customer, last_seen: datetime, days_silent: int`; everything else in `cards`, `teams.post_to_teams(webhook_url, card, ...)`, `chart_store.save_chart`, `chart_store.cleanup_old_charts` unchanged.

- [ ] **Step 1: Move the files and fix the test imports**

```bash
git mv roles/s1_reporter/files/cards.py roles/s1_reporter/files/app/s1_reporter/cards.py
git mv roles/s1_reporter/files/teams_notifier.py roles/s1_reporter/files/app/s1_reporter/teams.py
git mv roles/s1_reporter/files/chart_store.py roles/s1_reporter/files/app/s1_reporter/chart_store.py
```

In each of the three test files replace the `HERE = ...` / `sys.path.insert(...)` / `import cards` (or `teams_notifier`, `chart_store`) lines with:

```python
import _bootstrap  # noqa: F401
from s1_reporter import cards
```

(`from s1_reporter import teams as teams_notifier` in `test_teams_notifier.py` so the existing test body compiles unchanged, and `patch("s1_reporter.teams.urllib.request.urlopen", ...)` replacing `patch("teams_notifier.urllib.request.urlopen", ...)`; `from s1_reporter import chart_store` in `test_chart_store.py`.)

- [ ] **Step 2: Add the failing stale-digest test to `test_cards.py`**

```python
from datetime import datetime


class TestStaleDigestCard(unittest.TestCase):
    def test_lists_devices_with_days_silent(self):
        card = cards.build_stale_digest_card([
            {"machine_name": "STATIC1", "location": "DUR", "customer": "PEP AFRICA",
             "last_seen": datetime(2026, 7, 8, 7, 30), "days_silent": 63},
        ])
        text = str(card)
        self.assertIn("1 Stale Device", text)
        self.assertIn("STATIC1", text)
        self.assertIn("63 days", text)
        self.assertIn("2026-07-08", text)
        self.assertIn("reporting_enabled", text)
```

- [ ] **Step 3: Run tests to verify the moved suites pass and the new test fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: all previous tests PASS; `TestStaleDigestCard` FAILS with `AttributeError`.

- [ ] **Step 4: Add the builder to cards.py**

```python
def build_stale_digest_card(stale_devices):
    count = len(stale_devices)
    body = [_header(f"🕸️ S1 — {count} Stale Device{'s' if count != 1 else ''} (no data for 14+ days)", "warning")]
    rows = [
        [d["machine_name"], d["location"], d["customer"],
         f"{d['last_seen']:%Y-%m-%d}", f"{d['days_silent']} days"]
        for d in stale_devices
    ]
    body.extend(build_table(["Device", "Location", "Customer", "Last Seen", "Silent For"], rows))
    body.append(_text("These devices are excluded from alerts and daily reports. "
                      "Set devices.reporting_enabled = 0 to retire one permanently."))
    return build_card(body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add roles/s1_reporter
git commit -m "refactor(s1_reporter): move cards/teams/chart_store into the package; add stale digest card

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Report queries

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/queries.py`
- Test: `roles/s1_reporter/tests/test_queries.py`

**Interfaces:**
- Produces functions all taking `(query, customer, start_date, end_date, offset_hours)` unless noted:
  `daily_trend(...) -> list[dict]` (per device per local day, keys as in Task 9's `day_rows` plus `daily_no_read`), `device_summary(...) -> list[dict]` (keys `machine_name, location, customer, total_items, good_reads, no_reads, no_dimensions, not_sent, hand_scanned, no_weight, good_read_pct`), `hourly_pattern(...) -> list[dict]` (`hour_of_day, total_items`), `storage(query, customer) -> list[dict]` (`machine_name, location, drive, total_gb, used_gb, usage_percent`), `customers_with_reports(query) -> list[str]` (customers with `reports_enabled = 1`). Every query filters `d.reporting_enabled = 1`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_queries.py`:

```python
import unittest
from datetime import date, datetime

import _bootstrap  # noqa: F401
from s1_reporter import queries


class Capture:
    def __init__(self):
        self.sql = None
        self.params = None

    def __call__(self, sql, params=None):
        self.sql, self.params = sql, params
        return []


class TestQueries(unittest.TestCase):
    def test_daily_trend_is_parameterised_and_local_day_grouped(self):
        q = Capture()
        queries.daily_trend(q, "PEP'S", date(2026, 9, 2), date(2026, 9, 8), 2)
        self.assertNotIn("PEP'S", q.sql)
        self.assertEqual(q.params, (2, "PEP'S", datetime(2026, 9, 1, 22, 0), datetime(2026, 9, 8, 22, 0), 2))
        self.assertIn("DATEADD(hour, %s, ds.ts_datetime)", q.sql)
        self.assertIn("d.reporting_enabled = 1", q.sql)

    def test_device_summary_and_hourly_filter_enabled(self):
        for fn in (queries.device_summary, queries.hourly_pattern):
            q = Capture()
            fn(q, "A", date(2026, 9, 8), date(2026, 9, 8), 2)
            self.assertIn("d.reporting_enabled = 1", q.sql)
            self.assertIn("%s", q.sql)

    def test_storage_and_customers(self):
        q = Capture()
        queries.storage(q, "A")
        self.assertEqual(q.params, ("A",))
        self.assertIn("drive = 'C:'", q.sql)
        q = Capture()
        queries.customers_with_reports(q)
        self.assertIn("reports_enabled = 1", q.sql)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_queries.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write queries.py**

```python
"""Report SQL. All windows are inclusive local dates converted to UTC bounds; all values parameterised."""
from .timewin import utc_bounds

_ENABLED = "d.reporting_enabled = 1"


def _window_params(customer, start_date, end_date, offset_hours):
    start_utc, end_utc = utc_bounds(start_date, end_date, offset_hours)
    return start_utc, end_utc


def daily_trend(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = _window_params(customer, start_date, end_date, offset_hours)
    return query(f"""
        SELECT d.machine_name, d.location, d.customer,
               CAST(DATEADD(hour, %s, ds.ts_datetime) AS DATE) AS report_date,
               SUM(ds.total_items)   AS daily_items,
               SUM(ds.good_read)     AS daily_good,
               SUM(ds.no_read)       AS daily_no_read,
               SUM(ds.no_dimension)  AS daily_no_dim,
               SUM(ds.hand_scanned)  AS daily_hand_scanned,
               SUM(ds.no_weight)     AS daily_no_weight,
               CAST(SUM(ds.good_read)*100.0/NULLIF(SUM(ds.total_items),0) AS DECIMAL(5,1)) AS good_read_pct
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY d.machine_name, d.location, d.customer, CAST(DATEADD(hour, %s, ds.ts_datetime) AS DATE)
        ORDER BY d.location, d.machine_name, report_date
    """, (offset_hours, customer, start_utc, end_utc, offset_hours))


def device_summary(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = _window_params(customer, start_date, end_date, offset_hours)
    return query(f"""
        SELECT d.machine_name, d.location, d.customer,
               SUM(ds.total_items)  AS total_items,
               SUM(ds.good_read)    AS good_reads,
               SUM(ds.no_read)      AS no_reads,
               SUM(ds.no_dimension) AS no_dimensions,
               SUM(ds.not_sent)     AS not_sent,
               SUM(ds.hand_scanned) AS hand_scanned,
               SUM(ds.no_weight)    AS no_weight,
               CAST(SUM(ds.good_read)*100.0/NULLIF(SUM(ds.total_items),0) AS DECIMAL(5,2)) AS good_read_pct
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY d.machine_name, d.location, d.customer
        ORDER BY total_items DESC
    """, (customer, start_utc, end_utc))


def hourly_pattern(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = _window_params(customer, start_date, end_date, offset_hours)
    return query(f"""
        SELECT DATEPART(HOUR, DATEADD(hour, %s, ds.ts_datetime)) AS hour_of_day,
               SUM(ds.total_items) AS total_items
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s AND ds.total_items > 0
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY DATEPART(HOUR, DATEADD(hour, %s, ds.ts_datetime))
        ORDER BY hour_of_day
    """, (offset_hours, customer, start_utc, end_utc, offset_hours))


def storage(query, customer):
    return query(f"""
        SELECT d.machine_name, d.location, dss.drive, dss.total_gb, dss.used_gb, dss.usage_percent
        FROM dbo.devices d
        JOIN dbo.device_storage_status dss ON dss.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s AND dss.drive = 'C:'
        ORDER BY dss.usage_percent DESC
    """, (customer,))


def customers_with_reports(query):
    return [r["customer"] for r in query(
        "SELECT customer FROM dbo.customer_config WHERE reports_enabled = 1 ORDER BY customer", None)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_queries.py" -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/queries.py roles/s1_reporter/tests/test_queries.py
git commit -m "feat(s1_reporter): parameterised, local-day report queries

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Charts with threshold-aware axes

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/charts.py`
- Test: `roles/s1_reporter/tests/test_charts.py`

**Interfaces:**
- Produces pure helpers (top of module, no matplotlib needed): `goodread_axis_bounds(points: list[float], warn_lines: list[float]) -> (lo, hi)`; `series_by_device(rows) -> dict[(machine, location), list[(date, value)]]` using `good_read_pct` and skipping rows with no items; `devices_with_data(rows) -> list[(machine, location)]`.
- Produces chart functions (matplotlib imported lazily inside each): `chart_daily_volume(rows, title) -> bytes`, `chart_goodread_trend(rows, title, warn_by_device: dict[(machine, location), float]) -> bytes`, `chart_hourly_volume(rows, title) -> bytes`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_charts.py`:

```python
import unittest
from datetime import date

import _bootstrap  # noqa: F401
from s1_reporter import charts


def row(machine, day, items, pct):
    return {"machine_name": machine, "location": "JHB", "report_date": day, "daily_items": items, "good_read_pct": pct}


class TestPureHelpers(unittest.TestCase):
    def test_axis_bounds_include_lowest_warn_line(self):
        self.assertEqual(charts.goodread_axis_bounds([96.0, 99.0], [77.5, 93.0]), (72.5, 101.0))

    def test_axis_bounds_floor_at_zero(self):
        self.assertEqual(charts.goodread_axis_bounds([2.0], [1.0]), (0.0, 101.0))

    def test_axis_bounds_no_data(self):
        self.assertEqual(charts.goodread_axis_bounds([], []), (85.0, 101.0))

    def test_series_skips_empty_days(self):
        rows = [row("A", date(2026, 9, 1), 100, 99.0), row("A", date(2026, 9, 2), 0, None), row("B", date(2026, 9, 1), 5, 80.0)]
        s = charts.series_by_device(rows)
        self.assertEqual(s[("A", "JHB")], [(date(2026, 9, 1), 99.0)])
        self.assertEqual(s[("B", "JHB")], [(date(2026, 9, 1), 80.0)])

    def test_devices_with_data(self):
        rows = [row("A", date(2026, 9, 1), 0, None), row("B", date(2026, 9, 1), 5, 80.0)]
        self.assertEqual(charts.devices_with_data(rows), [("B", "JHB")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_charts.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write charts.py**

```python
"""Chart rendering. Pure helpers at the top are unit-tested; matplotlib is imported lazily below."""
import io

PALETTE = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#db2777",
           "#0891b2", "#16a34a", "#dc2626", "#9333ea", "#0284c7"]
CHART_STYLE = {
    "figure.facecolor": "none", "axes.facecolor": "none", "axes.edgecolor": "#d1d5db",
    "axes.labelcolor": "#374151", "xtick.color": "#6b7280", "ytick.color": "#6b7280",
    "text.color": "#1f2937", "grid.color": "#e5e7eb", "grid.linestyle": "--", "grid.alpha": 0.8,
}


# ── Pure helpers ───────────────────────────────────────────────────────────────
def goodread_axis_bounds(points, warn_lines):
    values = [float(v) for v in list(points) + list(warn_lines) if v is not None]
    if not values:
        return 85.0, 101.0
    return max(min(values) - 5.0, 0.0), 101.0


def series_by_device(rows):
    out = {}
    for r in rows:
        if (r.get("daily_items") or 0) > 0 and r.get("good_read_pct") is not None:
            out.setdefault((r["machine_name"], r["location"]), []).append((r["report_date"], float(r["good_read_pct"])))
    for pts in out.values():
        pts.sort()
    return out


def devices_with_data(rows):
    seen = []
    for r in rows:
        k = (r["machine_name"], r["location"])
        if (r.get("daily_items") or 0) > 0 and k not in seen:
            seen.append(k)
    return sorted(seen)


# ── Rendering ──────────────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _fig_to_png(plt, fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130, transparent=True)
    plt.close(fig)
    return buf.getvalue()


def chart_daily_volume(rows, title):
    plt = _plt()
    import numpy as np
    with plt.rc_context(CHART_STYLE):
        devices = devices_with_data(rows)
        dates = sorted({r["report_date"] for r in rows})
        fig, ax = plt.subplots(figsize=(12, 5))
        x = np.arange(len(dates))
        w = min(0.8 / max(len(devices), 1), 0.15)
        for i, (m, loc) in enumerate(devices):
            vals = [next((r["daily_items"] for r in rows
                          if r["machine_name"] == m and r["location"] == loc and r["report_date"] == d), 0)
                    for d in dates]
            ax.bar(x + i * w - (len(devices) * w / 2) + w / 2, vals, w * 0.85,
                   label=f"{m}@{loc}", color=PALETTE[i % len(PALETTE)], alpha=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels([str(d) for d in dates], rotation=25, ha="right", fontsize=9)
        ax.set_ylabel("Items Scanned", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        if devices:
            ax.legend(fontsize=8, ncol=3, loc="upper left", framealpha=0.3)
        ax.grid(axis="y", alpha=0.4)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))
        fig.tight_layout()
        return _fig_to_png(plt, fig)


def chart_goodread_trend(rows, title, warn_by_device):
    plt = _plt()
    with plt.rc_context(CHART_STYLE):
        series = series_by_device(rows)
        fig, ax = plt.subplots(figsize=(13, 6))
        all_points = []
        for i, (key, pts) in enumerate(sorted(series.items())):
            xs, ys = zip(*pts)
            all_points.extend(ys)
            color = PALETTE[i % len(PALETTE)]
            ax.plot(xs, ys, marker="o", markersize=5, label=f"{key[0]}@{key[1]}", color=color, linewidth=2, zorder=3)
            warn = warn_by_device.get(key)
            for x, y in pts:
                if warn is not None and y < warn:
                    ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, -14),
                                fontsize=7.5, ha="center", color=color, fontweight="bold")
        lo, hi = goodread_axis_bounds(all_points, [v for v in warn_by_device.values() if v is not None])
        ax.set_ylim(lo, hi)
        ax.set_ylabel("Good Read %", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        if series:
            ax.legend(fontsize=8, ncol=3, loc="lower left", framealpha=0.3)
        ax.grid(True, alpha=0.4)
        plt.xticks(rotation=25, ha="right", fontsize=9)
        fig.tight_layout()
        return _fig_to_png(plt, fig)


def chart_hourly_volume(rows, title):
    plt = _plt()
    with plt.rc_context(CHART_STYLE):
        fig, ax = plt.subplots(figsize=(12, 4))
        hours = [r["hour_of_day"] for r in rows]
        items = [r["total_items"] for r in rows]
        bars = ax.bar(hours, items, color="#38bdf8", alpha=0.85, width=0.7)
        if items:
            peak = max(items)
            for bar, val in zip(bars, items):
                if val == peak:
                    bar.set_color("#a78bfa")
        ax.set_xlabel("Hour of Day (24h, local)", fontsize=10)
        ax.set_ylabel("Total Items", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        ax.set_xticks(range(0, 24))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))
        ax.grid(axis="y", alpha=0.4)
        fig.tight_layout()
        return _fig_to_png(plt, fig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_charts.py" -v`
Expected: 5 PASS (no matplotlib import happens).

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/charts.py roles/s1_reporter/tests/test_charts.py
git commit -m "feat(s1_reporter): charts with threshold-aware axes and lazy matplotlib import

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Report and alert orchestration

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/reports.py`
- Test: `roles/s1_reporter/tests/test_reports.py`

**Interfaces:**
- Consumes everything above.
- Produces: `class Runner(settings, db, now_utc=None, post=None, render=None)` where `db` exposes `query/execute/executemany`, `post(webhook_url, card) -> bool` defaults to `teams.post_to_teams`, `render` is a dict of chart functions defaulting to `charts.*` (injected so tests never render). Jobs: `sync_status() -> (online, offline)`, `check_alerts() -> bool`, `daily() -> bool`, `monthly() -> bool`, `stale_digest() -> bool`. Each `bool` is "every POST succeeded".

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_reports.py`:

```python
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import _bootstrap  # noqa: F401
from s1_reporter.config import Settings
from s1_reporter.reports import Runner

NOW = datetime(2026, 9, 9, 4, 0)   # 06:00 SAST
D8 = date(2026, 9, 8)


class FakeDb:
    """Routes SQL by keyword to canned rows and records writes."""
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def query(self, sql, params=None):
        # Customer-scoped queries carry the customer in params; "EMPTY" has no data.
        if params and "EMPTY" in params:
            return []
        for key, val in self.rows.items():
            if key in sql:
                return val
        return []

    def execute(self, sql, params=None):
        self.writes.append((sql, params))
        return 1

    def executemany(self, sql, seq):
        self.writes.append((sql, list(seq)))


def device_row(id_, customer, machine, loc, last_seen, created=None):
    return {"id": id_, "customer": customer, "machine_name": machine, "location": loc, "created_at": created or (NOW - timedelta(days=100)),
            "reporting_enabled": True, "muted_until": None, "last_seen": last_seen}


def trend_row(customer, machine, loc, items, good):
    return {"machine_name": machine, "location": loc, "customer": customer, "report_date": D8, "daily_items": items,
            "daily_good": good, "daily_no_read": items - good, "daily_no_dim": 0, "daily_hand_scanned": 0,
            "daily_no_weight": 0, "good_read_pct": round(good * 100.0 / items, 1)}


def summary_row(machine, loc, items, good):
    return {"machine_name": machine, "location": loc, "customer": "A", "total_items": items, "good_reads": good, "no_reads": items - good,
            "no_dimensions": 0, "not_sent": 0, "hand_scanned": 0, "no_weight": 0, "good_read_pct": good * 100.0 / items}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(db_host="h", db_port=1, db_name="n", db_user="u", db_pass="p",
                                 teams_webhook_url="https://hook", chart_dir=os.path.join(self.tmp.name, "charts"),
                                 chart_public_base_url="https://charts.example",
                                 offline_state_file=os.path.join(self.tmp.name, "off.json"),
                                 upload_state_file=os.path.join(self.tmp.name, "up.json"))
        self.posted = []
        self.render = {"volume": lambda *a, **k: b"png", "goodread": lambda *a, **k: b"png", "hourly": lambda *a, **k: b"png"}

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, rows, post_ok=True):
        def post(url, card):
            self.posted.append(card)
            return post_ok
        return Runner(self.settings, FakeDb(rows), now_utc=NOW, post=post, render=self.render)


class TestSyncStatus(Base):
    def test_merges_only_enabled_devices(self):
        db_rows = {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW - timedelta(minutes=5)),
                                                    device_row(2, "A", "D2", "JHB", NOW - timedelta(days=30))]}
        r = self.runner(db_rows)
        self.assertEqual(r.sync_status(), (1, 1))
        self.assertEqual(len(r.db.writes), 1)


class TestCheckAlerts(Base):
    def _rows(self):
        return {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "OFF", "JHB", NOW - timedelta(hours=2)),
                                                 device_row(2, "A", "STALE", "DUR", NOW - timedelta(days=60))],
                "ROW_NUMBER()": []}

    def test_new_offline_alert_commits_state_after_success(self):
        r = self.runner(self._rows())
        self.assertTrue(r.check_alerts())
        self.assertEqual(len(self.posted), 1)
        self.assertIn("OFF", str(self.posted[0]))
        self.assertNotIn("STALE", str(self.posted[0]))
        self.assertTrue(os.path.exists(self.settings.offline_state_file))

    def test_failed_post_leaves_state_uncommitted(self):
        r = self.runner(self._rows(), post_ok=False)
        self.assertFalse(r.check_alerts())
        self.assertFalse(os.path.exists(self.settings.offline_state_file))

    def test_second_run_is_quiet(self):
        r = self.runner(self._rows())
        r.check_alerts()
        self.posted.clear()
        self.assertTrue(r.check_alerts())
        self.assertEqual(self.posted, [])


class TestDaily(Base):
    def test_posts_only_customers_with_data(self):
        rows = {"customer_config WHERE reports_enabled": [{"customer": "A"}, {"customer": "EMPTY"}],
                "FROM dbo.customer_config": [],
                "FROM dbo.alert_thresholds": [],
                "FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW - timedelta(minutes=5))],
                "AS report_date": [trend_row("A", "D1", "JHB", 1000, 990)],
                "AS good_reads": [summary_row("D1", "JHB", 1000, 990)],
                "AS hour_of_day": [{"hour_of_day": 9, "total_items": 500}],
                "device_storage_status": []}
        r = self.runner(rows)
        self.assertTrue(r.daily())
        self.assertEqual(len(self.posted), 1)
        text = str(self.posted[0])
        self.assertIn("🏢 A", text)
        self.assertIn("Yesterday", text)
        self.assertIn("https://charts.example/", text)

    def test_daily_with_no_customers_posts_nothing(self):
        r = self.runner({"customer_config WHERE reports_enabled": []})
        self.assertTrue(r.daily())
        self.assertEqual(self.posted, [])


class TestStaleDigest(Base):
    def test_posts_when_stale_exists(self):
        rows = {"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "PEP AFRICA", "STATIC1", "DUR", datetime(2026, 7, 8, 7, 30))]}
        r = self.runner(rows)
        self.assertTrue(r.stale_digest())
        self.assertIn("STATIC1", str(self.posted[0]))

    def test_silent_when_none(self):
        r = self.runner({"FROM dbo.devices d\nLEFT JOIN": [device_row(1, "A", "D1", "JHB", NOW)]})
        self.assertTrue(r.stale_digest())
        self.assertEqual(self.posted, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_reports.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write reports.py**

```python
"""Job orchestration. Everything with side effects (DB, Teams, chart rendering) is injected."""
from datetime import datetime

from . import anomalies, cards, charts, chart_store, customers, liveness, queries, status_sync, teams, thresholds, timewin, upload
from .state import AlertState


class Runner:
    def __init__(self, settings, db, now_utc=None, post=None, render=None):
        self.s = settings
        self.db = db
        self.now = now_utc or datetime.utcnow()
        self.post = post or teams.post_to_teams
        self.render = render or {
            "volume": charts.chart_daily_volume,
            "goodread": charts.chart_goodread_trend,
            "hourly": charts.chart_hourly_volume,
        }

    # ── shared ────────────────────────────────────────────────────────────────
    def _states(self):
        devices = liveness.fetch_devices(self.db.query)
        return liveness.classify(devices, self.now, self.s.offline_threshold_minutes, self.s.stale_days)

    def _send(self, card) -> bool:
        return bool(self.post(self.s.teams_webhook_url, card))

    # ── sync-status ───────────────────────────────────────────────────────────
    def sync_status(self):
        online, offline = status_sync.sync(self.db.executemany, self._states())
        print(f"device_status synced: {online} online, {offline} offline")
        return online, offline

    # ── check-alerts ──────────────────────────────────────────────────────────
    def check_alerts(self) -> bool:
        ok = True
        states = self._states()

        current = {}
        for st in liveness.alertable_offline(states, self.now):
            current[liveness.key(st)] = {
                "machine_name": st.device.machine_name, "location": st.device.location,
                "customer": st.device.customer, "last_seen": st.last_seen, "minutes_ago": st.minutes_ago,
            }
        off_state = AlertState(self.s.offline_state_file)
        d = off_state.diff(current, self.now)
        sent = True
        if d.new:
            sent &= self._send(cards.build_offline_alert_card(d.new))
            print(f"offline alert: {[liveness.key_from_dict(x) if hasattr(liveness, 'key_from_dict') else x['machine_name'] for x in d.new]}")
        if d.recovered:
            sent &= self._send(cards.build_recovery_card(d.recovered))
            print(f"recovery: {[x['machine_name'] for x in d.recovered]}")
        if d.unchanged:
            print(f"still offline (no re-alert): {[x['machine_name'] for x in d.unchanged]}")
        if sent:
            off_state.commit(d.pending)
        else:
            print("offline state NOT committed: a Teams post failed")
        ok &= sent

        failing = upload.detect_upload_failures(
            upload.fetch_recent_packets(self.db.query, self.s.upload_lookback_packets),
            self.s.upload_alert_consecutive)
        current_up = {f"{f['machine_name']}@{f['location']}": f for f in failing}
        up_state = AlertState(self.s.upload_state_file)
        du = up_state.diff(current_up, self.now)
        sent = True
        if du.new:
            sent &= self._send(cards.build_upload_alert_card(du.new))
        if du.recovered:
            sent &= self._send(cards.build_upload_recovery_card(du.recovered))
        if sent:
            up_state.commit(du.pending)
        else:
            print("upload state NOT committed: a Teams post failed")
        ok &= sent
        return ok

    # ── daily / monthly ───────────────────────────────────────────────────────
    def _customer_card(self, customer, start, end, cfg, thr, states, monthly_label=None):
        q, off = self.db.query, self.s.tz_offset_hours
        trend = queries.daily_trend(q, customer, start, end, off)
        summary = queries.device_summary(q, customer, start, end, off)
        if not summary:
            return None
        hourly = queries.hourly_pattern(q, customer, start, end, off)
        storage = queries.storage(q, customer)
        offline = [st for st in liveness.alertable_offline(states, self.now) if st.device.customer == customer]

        day_rows = [r for r in trend if r["report_date"] == end] if monthly_label is None else trend
        found = anomalies.detect(day_rows, storage, offline, cfg, thr)

        warn_by_device = {
            (r["machine_name"], r["location"]):
            thresholds.lookup(thr, cfg, customer, r["machine_name"], r["location"], "good_read_pct")[0]
            for r in summary
        }
        label = monthly_label or f"Last {(end - start).days + 1} Days"
        chart_urls = {
            "volume": self._save(self.render["volume"](trend, f"Daily Volume — {customer} — {label}"), "volume"),
            "goodread": self._save(self.render["goodread"](trend, f"Good Read % — {customer} — {label}", warn_by_device), "goodread"),
            "hourly": self._save(self.render["hourly"](hourly, f"Hourly Pattern — {customer} — {label}"), "hourly"),
        }

        headers = ["Device", "Location", "Items", "Good Read %", "No Reads"]
        if cfg.has_dimension:
            headers.append("No Dims")
        if cfg.has_hand_scan:
            headers.append("Hand Scanned")
        if cfg.has_weight:
            headers.append("No Weight")

        def _row(r, trailing):
            cells = [r["machine_name"], r["location"], f"{(r['total_items'] or 0):,}",
                     f"{float(r['good_read_pct']):.1f}%" if r.get("good_read_pct") is not None else "—",
                     f"{r['no_reads'] or 0:,}"]
            if cfg.has_dimension:
                cells.append(f"{r['no_dimensions'] or 0:,}")
            if cfg.has_hand_scan:
                cells.append(f"{r['hand_scanned'] or 0:,}")
            if cfg.has_weight:
                cells.append(f"{r['no_weight'] or 0:,}")
            return cells + trailing

        storage_table = {"headers": ["Device", "Location", "Usage", "%"],
                         "rows": [[s["machine_name"], s["location"],
                                   f"{float(s['used_gb']):.1f} / {float(s['total_gb']):.1f} GB",
                                   f"{float(s['usage_percent']):.0f}%"] for s in storage]}

        if monthly_label is None:
            yesterday = queries.device_summary(q, customer, end, end, off)
            today_table = {"headers": headers + ["Not Sent"],
                           "rows": [_row(r, [f"{r['not_sent'] or 0:,}"]) for r in yesterday]}
            week_table = {"headers": headers, "rows": [_row(r, []) for r in summary]}
            card = cards.build_customer_section_card(
                customer=customer, days=(end - start).days + 1, anomalies=anomalies.format_lines(found),
                today_table=today_table, week_table=week_table, storage_table=storage_table, chart_urls=chart_urls)
            # cards.py labels the first table "Today's Scan Summary"; rename for complete-day semantics.
            for el in card["body"]:
                if el.get("type") == "TextBlock" and "Today" in el.get("text", ""):
                    el["text"] = "📦 Yesterday's Scan Summary"
            return card

        total_items = sum(int(r["total_items"] or 0) for r in summary)
        avg_good = sum(float(r["good_read_pct"] or 0) for r in summary) / max(len(summary), 1)
        kpis = {"total_items": total_items, "avg_good_read_pct": avg_good, "active_devices": len(summary)}
        month_rows = [_row(r, [f"{int(r['not_sent'] or 0):,}",
                               "▲ Strong" if float(r["good_read_pct"] or 0) >= 99 else "▼ Monitor"]) for r in summary]
        return cards.build_customer_section_card(
            customer=customer, days=(end - start).days + 1, anomalies=anomalies.format_lines(found),
            today_table={"headers": [], "rows": []},
            week_table={"headers": headers + ["Not Sent", "Trend"], "rows": month_rows},
            storage_table=storage_table, chart_urls=chart_urls, kpis=kpis)

    def _save(self, png, label):
        try:
            return chart_store.save_chart(png, self.s.chart_dir, self.s.chart_public_base_url)
        except OSError as e:
            print(f"chart '{label}' could not be saved: {e}")
            return None

    def _report(self, start, end, monthly_label=None) -> bool:
        chart_store.cleanup_old_charts(self.s.chart_dir, self.s.chart_retention_days)
        cfgs = customers.load_customer_configs(self.db.query)
        thr = thresholds.load_thresholds(self.db.query)
        states = self._states()
        ok = True
        sent = 0
        for customer in queries.customers_with_reports(self.db.query):
            card = self._customer_card(customer, start, end, customers.config_for(cfgs, customer), thr, states, monthly_label)
            if card is None:
                print(f"skip {customer}: no data in window")
                continue
            ok &= self._send(card)
            sent += 1
        print(f"{'monthly' if monthly_label else 'daily'} report: {sent} card(s), ok={ok}")
        return ok

    def daily(self) -> bool:
        start, end = timewin.daily_window(self.now, self.s.tz_offset_hours, days=7)
        return self._report(start, end)

    def monthly(self) -> bool:
        start, end = timewin.previous_month(self.now, self.s.tz_offset_hours)
        return self._report(start, end, monthly_label=start.strftime("%B %Y"))

    # ── stale-digest ──────────────────────────────────────────────────────────
    def stale_digest(self) -> bool:
        stale = liveness.stale_devices(self._states())
        if not stale:
            print("no stale devices")
            return True
        items = [{"machine_name": st.device.machine_name, "location": st.device.location,
                  "customer": st.device.customer, "last_seen": st.last_seen,
                  "days_silent": st.minutes_ago // 1440} for st in stale]
        return self._send(cards.build_stale_digest_card(items))
```

Then simplify the one awkward print in `check_alerts` (it was written defensively above; use this exact line instead):

```python
            print(f"offline alert: {[x['machine_name'] + '@' + x['location'] for x in d.new]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_reports.py" -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/reports.py roles/s1_reporter/tests/test_reports.py
git commit -m "feat(s1_reporter): Runner orchestrating sync, alerts, daily/monthly reports and stale digest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: CLI entry point

**Files:**
- Create: `roles/s1_reporter/files/app/s1_reporter/cli.py`
- Create: `roles/s1_reporter/files/app/s1_reporter/__main__.py`
- Test: `roles/s1_reporter/tests/test_cli.py`

**Interfaces:**
- Produces: `JOBS = ("sync-status", "check-alerts", "daily", "monthly", "stale-digest", "migrate")`; `parse_args(argv) -> Namespace(job)`; `main(argv=None, env=None, make_db=None, make_runner=None) -> int` returning 0/1; `__main__` calls `sys.exit(main())`.

- [ ] **Step 1: Write the failing test**

`roles/s1_reporter/tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_cli.py" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write cli.py and __main__.py**

`cli.py`:

```python
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
```

`__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add roles/s1_reporter/files/app/s1_reporter/cli.py roles/s1_reporter/files/app/s1_reporter/__main__.py roles/s1_reporter/tests/test_cli.py
git commit -m "feat(s1_reporter): job CLI with migrate and exit codes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: Image, compose, wrapper, defaults, tasks and cron

**Files:**
- Rewrite: `roles/s1_reporter/files/Dockerfile`
- Create: `roles/s1_reporter/files/requirements.txt`
- Rewrite: `roles/s1_reporter/templates/docker-compose.s1_reporter.yml.j2`
- Create: `roles/s1_reporter/templates/run-reporter.sh.j2`
- Rewrite: `roles/s1_reporter/defaults/main.yml`
- Rewrite: `roles/s1_reporter/tasks/main.yml`
- Test: `roles/s1_reporter/tests/test_role_files.py`

- [ ] **Step 1: Write the failing role-file test**

`roles/s1_reporter/tests/test_role_files.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s roles/s1_reporter/tests -p "test_role_files.py" -v`
Expected: FAIL on defaults, Dockerfile, requirements, compose, wrapper, tasks and old-files checks.

- [ ] **Step 3: Write requirements.txt and the Dockerfile**

`roles/s1_reporter/files/requirements.txt`:

```
pymssql==2.3.2
matplotlib==3.9.2
numpy==2.1.3
```

`roles/s1_reporter/files/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc g++ freetds-dev \
  && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --wheel-dir /wheels -r /tmp/requirements.txt

FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib
ENV TZ=Africa/Johannesburg
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libsybdb5 tzdata \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --system --uid 10001 --create-home reporter
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY app/ /app/
USER reporter
ENTRYPOINT ["python", "-m", "s1_reporter"]
```

- [ ] **Step 4: Write the compose template**

`roles/s1_reporter/templates/docker-compose.s1_reporter.yml.j2`:

```yaml
# reporter: one-shot, started only by `docker compose run --rm reporter <job>` (host cron).
# s1-charts: long-running nginx serving chart PNGs for Teams cards.
services:
  reporter:
    build:
      context: .
      dockerfile: Dockerfile
    image: "{{ s1_reporter_image }}"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    environment:
      DB_HOST: "{{ s1_reporter_db_host }}"
      DB_PORT: "{{ s1_reporter_db_port }}"
      DB_NAME: "{{ s1_reporter_db_name }}"
      DB_USER: "{{ s1_reporter_db_user }}"
      DB_PASS: "{{ s1_reporter_db_pass }}"
      TEAMS_WEBHOOK_URL: "{{ vault_s1_reporter_teams_webhook_url }}"
      CHART_DIR: "/data/charts"
      CHART_PUBLIC_BASE_URL: "{{ s1_reporter_chart_public_base_url }}"
      CHART_RETENTION_DAYS: "{{ s1_reporter_chart_retention_days }}"
      OFFLINE_THRESHOLD_MINUTES: "{{ s1_reporter_offline_threshold_minutes }}"
      STALE_DAYS: "{{ s1_reporter_stale_days }}"
      REPORT_TZ_OFFSET_HOURS: "{{ s1_reporter_tz_offset_hours }}"
      UPLOAD_ALERT_CONSECUTIVE: "{{ s1_reporter_upload_alert_consecutive }}"
      UPLOAD_LOOKBACK_PACKETS: "{{ s1_reporter_upload_lookback_packets }}"
      OFFLINE_STATE_FILE: "/data/offline_state.json"
      UPLOAD_STATE_FILE: "/data/upload_state.json"
    volumes:
      - s1_reporter_data:/data
      - s1_reporter_charts:/data/charts
    networks:
      - {{ docker_shared_network | default('infra') }}

  s1-charts:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    image: "{{ s1_reporter_charts_image | default('nginx:alpine') }}"
    container_name: s1_reporter_charts
    restart: unless-stopped
    ports:
      - "127.0.0.1:{{ s1_reporter_chart_local_port | default(8091) }}:80"
    volumes:
      - s1_reporter_charts:/usr/share/nginx/html:ro
    healthcheck:
      test: ["CMD-SHELL", "wget --spider -S http://localhost/ 2>&1 | grep -qE 'HTTP/1\\.[01] (200|403|404)' || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    networks:
      - {{ docker_shared_network | default('infra') }}

networks:
  {{ docker_shared_network | default('infra') }}:
    external: true

volumes:
  s1_reporter_data:
  s1_reporter_charts:
```

The reporter runs as uid 10001 and writes to `/data`; the volume was created by the old root container. The tasks below `chown` it once (Step 7).

- [ ] **Step 5: Write the wrapper**

`roles/s1_reporter/templates/run-reporter.sh.j2`:

```bash
#!/bin/bash
# Usage: run-reporter.sh sync-status|check-alerts|daily|monthly|stale-digest|migrate
# Same entry point for cron and operators. Exit code is the container's.
set -o pipefail
cd {{ s1_reporter_dir }} || exit 1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] run-reporter $*" >> {{ s1_reporter_log_path }}
docker compose run --rm reporter "$@" 2>&1 | tee -a {{ s1_reporter_log_path }}
```

- [ ] **Step 6: Write the defaults**

`roles/s1_reporter/defaults/main.yml`:

```yaml
---
# s1_reporter: Teams alerts and reports, run as one-shot jobs by host cron.
s1_reporter_image: "s1-reporter:latest"
s1_reporter_dir: "/opt/s1-reporter"
s1_reporter_log_path: "/opt/s1-reporter/reporter.log"

s1_reporter_db_host: "mssql"
s1_reporter_db_port: 1433
s1_reporter_db_name: "{{ mssql_rm_database | default('S1_Remote_Monitoring') }}"
# Least-privilege application login, never sa.
s1_reporter_db_user: "{{ mssql_rm_admin_login | default('admin') }}"
s1_reporter_db_pass: "{{ mssql_rm_admin_password | default('') }}"

# Liveness
s1_reporter_offline_threshold_minutes: 30
s1_reporter_stale_days: 14
# Local day = UTC + this (SAST, no DST)
s1_reporter_tz_offset_hours: 2

# Upload-failure rule
s1_reporter_upload_alert_consecutive: 3
s1_reporter_upload_lookback_packets: 6

# Teams chart hosting
s1_reporter_chart_public_base_url: ""
s1_reporter_chart_retention_days: 14
s1_reporter_chart_local_port: 8091
s1_reporter_charts_image: "nginx:alpine"

# Host cron (host-local time). weekday 1-5 = Mon-Fri.
s1_reporter_cron_sync_status:  { minute: "*/20", hour: "*", day: "*", weekday: "*" }
s1_reporter_cron_check_alerts: { minute: "*/20", hour: "*", day: "*", weekday: "1-5" }
s1_reporter_cron_daily:        { minute: "0",    hour: "6", day: "*", weekday: "1-5" }
s1_reporter_cron_monthly:      { minute: "30",   hour: "6", day: "1", weekday: "*" }
s1_reporter_cron_stale_digest: { minute: "0",    hour: "7", day: "*", weekday: "1" }
```

- [ ] **Step 7: Write the tasks**

`roles/s1_reporter/tasks/main.yml`:

```yaml
---
- name: Ensure s1_reporter directory exists
  file:
    path: "{{ s1_reporter_dir }}"
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Validate required variables
  assert:
    that:
      - vault_s1_reporter_teams_webhook_url is defined
      - vault_s1_reporter_teams_webhook_url | length > 0
      - s1_reporter_db_pass | length > 0
    fail_msg: "s1_reporter needs vault_s1_reporter_teams_webhook_url and a non-empty DB password"

- name: Remove legacy files from the loop-based reporter
  file:
    path: "{{ s1_reporter_dir }}/{{ item }}"
    state: absent
  loop:
    - report.py
    - upload_monitor.py
    - entrypoint.sh
    - teams_notifier.py
    - cards.py
    - chart_store.py
    - compute_baselines.py
    - .env

- name: Copy application source
  copy:
    src: "{{ item.src }}"
    dest: "{{ s1_reporter_dir }}/{{ item.dest }}"
    owner: root
    group: root
    mode: "0644"
  loop:
    - { src: Dockerfile,       dest: Dockerfile }
    - { src: requirements.txt, dest: requirements.txt }
    - { src: app/,             dest: app/ }

- name: Render docker-compose file
  template:
    src: docker-compose.s1_reporter.yml.j2
    dest: "{{ s1_reporter_dir }}/docker-compose.yml"
    owner: root
    group: root
    mode: "0640"

- name: Render run-reporter.sh wrapper
  template:
    src: run-reporter.sh.j2
    dest: "{{ s1_reporter_dir }}/run-reporter.sh"
    owner: root
    group: root
    mode: "0755"

- name: Stop legacy long-running reporter container if present
  command: docker rm -f s1_reporter
  register: s1_reporter_legacy_rm
  failed_when: false
  changed_when: "'s1_reporter' in s1_reporter_legacy_rm.stdout"

- name: Build s1_reporter image
  command: docker compose build reporter
  args:
    chdir: "{{ s1_reporter_dir }}"
  changed_when: false

- name: Start chart server
  command: docker compose up -d --remove-orphans s1-charts
  args:
    chdir: "{{ s1_reporter_dir }}"
  changed_when: false

- name: Make the data volume writable by the non-root reporter user
  command: docker run --rm -v s1-reporter_s1_reporter_data:/data -v s1-reporter_s1_reporter_charts:/data/charts alpine:3 chown -R 10001:10001 /data
  changed_when: false

- name: Run migrations (customer_config, device flags)
  command: docker compose run --rm reporter migrate
  args:
    chdir: "{{ s1_reporter_dir }}"
  changed_when: false

- name: Install reporter cron jobs
  cron:
    name: "systems-one reporter {{ item.job }}"
    user: root
    minute: "{{ item.spec.minute }}"
    hour: "{{ item.spec.hour }}"
    day: "{{ item.spec.day }}"
    weekday: "{{ item.spec.weekday }}"
    job: "{{ s1_reporter_dir }}/run-reporter.sh {{ item.job }} >> {{ s1_reporter_log_path }} 2>&1"
    state: present
  loop:
    - { job: sync-status,  spec: "{{ s1_reporter_cron_sync_status }}" }
    - { job: check-alerts, spec: "{{ s1_reporter_cron_check_alerts }}" }
    - { job: daily,        spec: "{{ s1_reporter_cron_daily }}" }
    - { job: monthly,      spec: "{{ s1_reporter_cron_monthly }}" }
    - { job: stale-digest, spec: "{{ s1_reporter_cron_stale_digest }}" }
  loop_control:
    label: "{{ item.job }}"
```

The volume names in the chown task follow Docker Compose's `<project>_<volume>` convention; the project name is the directory name `s1-reporter`. Verify on the box with `docker volume ls | grep s1_reporter` before the first deploy and adjust if the existing volumes carry a different prefix.

- [ ] **Step 8: Delete the old files**

```bash
git rm roles/s1_reporter/files/report.py roles/s1_reporter/files/upload_monitor.py roles/s1_reporter/files/entrypoint.sh roles/s1_reporter/tests/test_report_shapes.py
```

(`cards.py`, `teams_notifier.py`, `chart_store.py` were already moved in Task 10.)

- [ ] **Step 9: Run the whole suite**

Run: `python -m unittest discover -s roles/s1_reporter/tests -v`
Expected: all PASS, including `test_role_files.py`.

Run: `bash -n roles/s1_reporter/templates/run-reporter.sh.j2` (the Jinja braces are inside quotes and shell-parse fine)
Expected: no output.

- [ ] **Step 10: Commit**

```bash
git add -A roles/s1_reporter
git commit -m "feat(s1_reporter): multi-stage non-root image, one-shot compose, wrapper and host cron jobs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 16: CI, docs and the baselines-side guard

**Files:**
- Modify: `.github/workflows/ci.yml` (reporter test step needs pyyaml)
- Modify: `roles/s1_baselines/tests/test_reporter_detached.py` (entrypoint.sh no longer exists)
- Modify: `README.md`

- [ ] **Step 1: Update CI**

Replace the `Run s1_reporter unit tests` step with:

```yaml
      - name: Run s1_reporter unit tests
        run: |
          pip install pyyaml
          python -m unittest discover -s roles/s1_reporter/tests
```

- [ ] **Step 2: Update the baselines guard test**

In `roles/s1_baselines/tests/test_reporter_detached.py` replace `test_entrypoint_has_no_baseline_block` with:

```python
    def test_reporter_has_no_baseline_code(self):
        app = os.path.join(REPORTER, "files", "app", "s1_reporter")
        for name in os.listdir(app):
            if name.endswith(".py"):
                with open(os.path.join(app, name), encoding="utf-8") as fh:
                    self.assertNotIn("compute_baselines", fh.read(), name)
        self.assertFalse(os.path.exists(os.path.join(REPORTER, "files", "entrypoint.sh")))
```

- [ ] **Step 3: Update README**

In the Services table replace the `s1_reporter` row with:

```markdown
| `s1_reporter` | one-shot `reporter` via `compose run`, plus `s1_reporter_charts` | built `s1-reporter:latest`, `nginx:alpine` | `/opt/s1-reporter` | Teams alerts and reports as host-cron jobs: `sync-status` every 20 min, `check-alerts` every 20 min on weekdays, `daily` 06:00 weekdays, `monthly` on the 1st, `stale-digest` Monday 07:00. Customer capabilities and limits live in `dbo.customer_config`; per-device `reporting_enabled` and `muted_until` on `dbo.devices`. Chart PNGs served by nginx as `charts.sysone.co.za`. |
```

Add to the Data table:

```markdown
| `dbo.customer_config` | reporter `migrate`, edited by hand | Per-customer capabilities (dimension, weight, hand scan) and alert limits. |
| `dbo.alert_thresholds` | `s1_baselines` | Per-device warn/bad thresholds from 60-day baselines. |
```

In "Known rough edges" remove the `sa` bullet and the "healthcheck cannot fail" wording if present; add: "`dbo.customer_config` and device flags are edited by hand in SQL until a UI exists."

- [ ] **Step 4: Run every suite**

Run:
```bash
python -m unittest discover -s roles/s1_reporter/tests
python -m unittest discover -s roles/s1_baselines/tests
python -m unittest discover -s roles/mqtt_ingestor/tests
python roles/s1_dashboard/tests/test_dashboard.py
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml roles/s1_baselines/tests/test_reporter_detached.py README.md
git commit -m "docs+ci: reporter overhaul wiring

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 17: Live verification on `sysone` (manual, after merge)

1. Confirm the volume names: `docker volume ls | grep s1_reporter`. Adjust the chown task if the prefix is not `s1-reporter_`.
2. `ansible-playbook -i production webservers.yml --tags s1_reporter`. Expect: legacy `s1_reporter` container removed, `s1_reporter_charts` healthy, `migrated: ['001_customer_config.sql', '002_device_flags.sql']`, five cron lines in `sudo crontab -l`.
3. `SELECT * FROM dbo.customer_config` shows 7 rows; `SELECT machine_name, location, reporting_enabled FROM dbo.devices WHERE reporting_enabled = 0` shows `DIM2 JBH`.
4. `/opt/s1-reporter/run-reporter.sh sync-status` prints the online/offline counts.
5. `/opt/s1-reporter/run-reporter.sh check-alerts` posts nothing (state carried over) and does not mention `STATIC1`.
6. `/opt/s1-reporter/run-reporter.sh daily` posts cards for customers with data; no PEP AFRICA card.
7. `/opt/s1-reporter/run-reporter.sh stale-digest` posts one card listing `STATIC1@DUR`.
8. Next weekday morning, confirm the 06:00 SAST card in Teams and the `reporter.log` line.
