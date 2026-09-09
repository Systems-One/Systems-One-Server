"""Thin pyodbc layer. Everything above this module works with lists of dicts."""
import datetime
import decimal
from typing import Any

import pyodbc

from config import settings


def _coerce(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        return v.replace(microsecond=0).isoformat() + "Z"
    if isinstance(v, datetime.date):
        return v.isoformat()
    return v


def query(sql: str, params: tuple = ()) -> list[dict]:
    with pyodbc.connect(settings.conn_str, timeout=settings.query_timeout) as conn:
        conn.timeout = settings.query_timeout
        cur = conn.cursor()
        cur.execute(sql, params) if params else cur.execute(sql)
        cols = [c[0] for c in cur.description]
        return [{k: _coerce(v) for k, v in zip(cols, row)} for row in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with pyodbc.connect(settings.conn_str, timeout=settings.query_timeout, autocommit=True) as conn:
        conn.timeout = settings.query_timeout
        cur = conn.cursor()
        cur.execute(sql, params) if params else cur.execute(sql)
        return cur.rowcount


def probe() -> bool:
    try:
        return query("SELECT 1 AS ok")[0]["ok"] == 1
    except Exception:
        return False
