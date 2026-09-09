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
