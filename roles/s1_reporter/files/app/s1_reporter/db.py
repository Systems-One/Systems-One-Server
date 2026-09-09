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
