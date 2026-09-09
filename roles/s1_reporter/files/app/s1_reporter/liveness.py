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
    state: str           # online | offline | stale | never
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
