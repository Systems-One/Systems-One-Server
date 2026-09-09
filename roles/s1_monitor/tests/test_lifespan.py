"""Startup and shutdown: the migration runs once and the snapshot task is created and cancelled."""
import asyncio
import dataclasses

import main
import snapshots
from fastapi.testclient import TestClient


def _fake_loop(seen):
    async def loop(execute, s, state, **kw):
        seen["ran"] = True
        seen["task"] = asyncio.current_task()
        await asyncio.sleep(3600)   # long enough that only a cancel can end it
    return loop


def test_lifespan_migrates_and_cancels_the_snapshot_task(monkeypatch):
    calls, seen = [], {}
    monkeypatch.setattr(main, "EXECUTE", lambda sql, params=(): calls.append(sql) or 0)
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, snapshot_enabled=True))
    monkeypatch.setattr(main, "PROBE", lambda: True)
    monkeypatch.setattr(snapshots, "loop", _fake_loop(seen))
    with TestClient(main.app) as c:
        c.get("/health")   # give the loop a turn so the task starts
        assert seen.get("ran") is True
    assert any("device_health_history" in s for s in calls)
    assert seen["task"].cancelled()


def test_lifespan_does_nothing_when_snapshots_are_disabled(monkeypatch):
    calls, seen = [], {}
    monkeypatch.setattr(main, "EXECUTE", lambda sql, params=(): calls.append(sql) or 0)
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, snapshot_enabled=False))
    monkeypatch.setattr(main, "PROBE", lambda: True)
    monkeypatch.setattr(snapshots, "loop", _fake_loop(seen))
    with TestClient(main.app) as c:
        c.get("/health")
    assert calls == [] and seen == {}
