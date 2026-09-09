"""Availability derived from observed telemetry. Never trusts what devices say about themselves."""
import datetime as dt

PACKET = dt.timedelta(minutes=5)


def _iso(d):
    return d.replace(microsecond=0).isoformat() + "Z"


def outages(timestamps, gap_minutes, window_end):
    gap = dt.timedelta(minutes=gap_minutes)
    out, prev = [], None
    for ts in timestamps:
        if prev is not None and ts - prev > gap:
            out.append({"start": _iso(prev + PACKET), "end": _iso(ts), "minutes": int((ts - prev).total_seconds() // 60), "open": False})
        prev = ts
    if prev is not None and window_end - prev > gap:
        out.append({"start": _iso(prev + PACKET), "end": _iso(window_end), "minutes": int((window_end - prev).total_seconds() // 60), "open": True})
    return out


def classify(last_seen, created_at, now_utc, gap_minutes, stale_days):
    last = created_at if last_seen is None else last_seen
    age = now_utc - last
    if age >= dt.timedelta(days=stale_days):
        return "stale"
    if last_seen is None:
        return "never"
    return "offline" if age >= dt.timedelta(minutes=gap_minutes) else "online"


def transitions(rows):
    ev, prev = [], None
    for r in rows:
        if prev is not None:
            ts = r["snapshot_utc"]
            if r.get("application_running") is not None and prev.get("application_running") is not None and r["application_running"] != prev["application_running"]:
                ev.append({"ts": _iso(ts), "kind": "app_started" if r["application_running"] else "app_stopped", "detail": ""})
            up, pup = r.get("uptime_seconds"), prev.get("uptime_seconds")
            if up is not None and pup is not None and up < pup:
                ev.append({"ts": _iso(ts - dt.timedelta(seconds=float(up))), "kind": "uptime_reset", "detail": "rebooted"})
            if r.get("status") != prev.get("status") and r.get("status") is not None:
                ev.append({"ts": _iso(ts), "kind": "status_change", "detail": f"{prev.get('status')} -> {r.get('status')}"})
        prev = r
    order = {"app_stopped": 0, "app_started": 0, "uptime_reset": 1, "status_change": 2}
    return sorted(ev, key=lambda e: (e["ts"][:16], order[e["kind"]]))
