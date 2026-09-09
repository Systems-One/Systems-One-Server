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
