import asyncio, datetime as dt, os
import snapshots as sn

def test_migration_sql_is_idempotent_ddl():
    sql = open(os.path.join(os.path.dirname(sn.__file__), "migrations", "001_device_health_history.sql"), encoding="utf-8").read()
    assert "IF OBJECT_ID(N'dbo.device_health_history'" in sql and "CREATE INDEX IX_device_health_history_device_ts" in sql
    assert "OBJECT_ID(N'dbo.device_health_history')" in sql   # the index guard is qualified to this table

def test_migrate_runs_two_batches_in_order():
    """GO splits the file: SQL Server will not parse the index batch before the table exists."""
    calls = []
    def execute(sql, params=()): calls.append(sql); return 0
    sn.migrate(execute)
    assert len(calls) == 2 and all(s.strip() for s in calls)
    assert "CREATE TABLE dbo.device_health_history" in calls[0] and "CREATE INDEX" not in calls[0]
    assert "CREATE INDEX IX_device_health_history_device_ts" in calls[1]
    assert not any("GO" == line.strip() for s in calls for line in s.splitlines())


def test_run_once_inserts_and_returns_rowcount():
    calls = []
    def execute(sql, params=()): calls.append((sql, params)); return 19
    assert sn.run_once(execute, dt.datetime(2026, 9, 9, 12, 0)) == 19
    assert calls[0][0] is sn.SQL_INSERT and calls[0][1] == (dt.datetime(2026, 9, 9, 12, 0),)

def test_prune_cutoff():
    calls = []
    def execute(sql, params=()): calls.append((sql, params)); return 0
    sn.prune(execute, dt.datetime(2026, 9, 9), 400)
    assert calls[0][0] is sn.SQL_PRUNE and calls[0][1] == (dt.datetime(2025, 8, 5),)

def test_loop_survives_failure_and_records_state():
    class S: snapshot_interval_minutes = 15; snapshot_retention_days = 400
    class St: snapshot_last_utc = None; snapshot_error = None
    st = St(); n = {"i": 0}
    def execute(sql, params=()):
        n["i"] += 1
        if n["i"] == 1: raise RuntimeError("boom")
        return 1
    slept = []
    async def sleep(x):
        slept.append(x)
        if len(slept) >= 3: raise asyncio.CancelledError
    try:
        asyncio.run(sn.loop(execute, S, st, sleep=sleep, clock=lambda: dt.datetime(2026, 9, 9, 12)))
    except asyncio.CancelledError:
        pass
    assert st.snapshot_error is None and st.snapshot_last_utc == dt.datetime(2026, 9, 9, 12) and slept[0] == 60 and slept[1] == 900
