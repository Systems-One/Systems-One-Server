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
