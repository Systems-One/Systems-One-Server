"""s1_monitor API and static site."""
import asyncio
import datetime as dt
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db
from config import settings

# Indirection so tests can swap the database layer.
QUERY: Callable[[str, tuple], list] = db.query
EXECUTE: Callable[[str, tuple], int] = db.execute
PROBE: Callable[[], bool] = db.probe


@dataclass
class State:
    last_query_utc: Optional[dt.datetime] = None
    snapshot_last_utc: Optional[dt.datetime] = None
    snapshot_error: Optional[str] = None


state = State()
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

from cache import cache
from queries import fleet as qfleet
NOW_OVERRIDE = None   # tests set a fixed time


def current_time():
    return NOW_OVERRIDE or now_utc()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def run_query(sql: str, params: tuple = ()) -> list:
    rows = QUERY(sql, params)
    state.last_query_utc = now_utc()
    return rows


async def in_thread(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="S1 Remote Monitoring", lifespan=lifespan)


@app.get("/health")
async def health():
    recent = state.last_query_utc and (now_utc() - state.last_query_utc).total_seconds() <= 3 * settings.cache_ttl_live
    ok = bool(recent) or await in_thread(PROBE)
    body = {"status": "ok" if ok else "degraded", "db_ok": ok,
            "last_query_utc": state.last_query_utc.isoformat() + "Z" if state.last_query_utc else None,
            "snapshot_last_utc": state.snapshot_last_utc.isoformat() + "Z" if state.snapshot_last_utc else None,
            "snapshot_error": state.snapshot_error}
    return JSONResponse(body, status_code=200 if ok else 503)


def _cached(key, ttl, builder):
    try:
        return JSONResponse(cache.get_or_build(key, ttl, builder))
    except Exception as exc:   # cold cache and the database is down
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}")


@app.get("/api/meta")
async def api_meta():
    return await in_thread(_cached, "meta", settings.cache_ttl_history, lambda: qfleet.build_meta(run_query, settings, current_time()))


@app.get("/api/fleet")
async def api_fleet(customer: str = ""):
    key = f"fleet|{customer}"
    try:
        return await in_thread(_cached, key, settings.cache_ttl_live, lambda: qfleet.build_fleet(run_query, settings, current_time(), customer or None))
    except HTTPException:
        # No cached payload has ever existed for this exact customer filter and the database is down.
        # Degrade the live tile instead of erroring the whole dashboard.
        return JSONResponse({"generated_utc": current_time().isoformat() + "Z",
                              "strip": {}, "attention": [], "devices": [], "stale": True})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})
