# s1_monitor: fault-diagnosis website — Design

**Date:** 2026-09-09
**Target:** new role `roles/s1_monitor/`; retires `roles/marketing_display/` and
`roles/scan_fleet_dashboard/` at cutover
**Related:** `2026-09-09-s1-reporter-overhaul-design.md` (threshold and liveness semantics the
site must agree with), `2026-09-09-s1-baselines-role-design.md` (`dbo.alert_thresholds`)

## Context

The status page served at sysone.co.za (`marketing_display`, port 8090) makes faults hard to
find. Profiling the live `S1_Remote_Monitoring` database on 2026-09-09 established:

- 19 devices across 8 customers. `dbo.device_statistics` holds 701,639 rows since January
  2026, one row per device every 5 minutes. Rows arrive with zero items when a device is idle,
  so "online but not scanning" and "offline" are distinguishable from the row cadence alone.
  Over 7 days, 34,561 of 34,592 inter-row gaps were 5 minutes or less.
- Every timestamp column is UTC. Site local time is SAST (UTC+2, no DST).
- Storage, CPU, memory, temperature, application-running and uptime tables hold only the
  latest value per device (MERGE upserts). No history exists for them.
- Volume is strongly seasonal: weekdays carry roughly ten times Sunday's items; 08:00 to 16:00
  SAST carries most of the day with a dip at 13:00.
- Devices differ in volume by four orders of magnitude (40,140 items a week at PEPKOR JBH
  DIM4, 1 at PEPKOR JBH DIM2). Percentages on low volumes are noise.
- Metric meaning is per customer: PEPKOR reports `no_weight` equal to `total_items` because
  no scale is fitted; PEP STATIC devices never fill `complete`. `dbo.customer_config` carries
  the capability flags (`has_dimension`, `has_weight`, `has_hand_scan`).
- `dbo.alert_thresholds` holds per-device warn/bad values plus a 60-day baseline mean,
  stddev and percentiles for `good_read_pct` (low) and `no_dim_pct` (high). The current site
  ignores it and hard-codes "target 98%, minimum 90%". DCB DUR's baseline mean is 65%, so
  the fixed line is permanently red there.
- The current site mixes `GETDATE()` with and without a +2h shift, so "today" starts at
  different times on different panels.
- The current charts show one day of hourly bars and 7 or 14 days of daily lines with all
  customers overlaid. No per-device timeline, no zoom, no threshold overlay, no outage history.

Decisions taken with the product owner on 2026-09-09: internal ops audience with no login;
primary questions are "why did quality drop on device X", "is something degrading slowly"
and "is data getting through"; the site records its own health snapshots; plain FastAPI plus
static pages with a vendored chart library, no JS build toolchain.

## Goals

1. Diagnose a quality fault on one device from a single screen: volume, every applicable
   quality rate with its own warn/bad lines and baseline band, outages, app stops, and host
   health, all on one shared, zoomable time axis.
2. Surface slow degradation: like-for-like expected-volume bands and week-over-week deltas.
3. Show pipeline health: broker, ingestor write age, dead letters, upload backlog.
4. One definition of "today", of a rate, of low volume, and of offline, shared with the
   reporter.
5. Accumulate health history from deployment day onward.
6. Replace `marketing_display` and `scan_fleet_dashboard` with one role on port 8090 so the
   Cloudflare route is untouched.

## Non-goals

- Login, per-customer scoping or any use of `dbo.customer_login_map`.
- Editing `customer_config`, `alert_thresholds` or device flags from the UI.
- Changing `mqtt_ingestor`, `s1_reporter` or `s1_baselines`.
- The TV/kiosk mode of the old page. The fleet screen is readable on a TV but nothing is
  built specifically for it.
- Alerting. Teams alerts remain the reporter's job.

## Architecture

### Runtime

```
browser -- Cloudflare tunnel -- 127.0.0.1:8090 -- s1_monitor (uvicorn, one process)
                                                    |-- FastAPI /api/*  (read: dbo.*, broker.*, ingest.*)
                                                    |-- static pages + vendored ECharts
                                                    `-- asyncio snapshot task every 15 min
                                                          `-- writes dbo.device_health_history
```

One container, one replica. The snapshot task lives in the API process. There is no
second container and no host cron. The image is built on the host by Ansible like every
other role.

### Role layout

```
roles/s1_monitor/
  defaults/main.yml
  handlers/main.yml
  tasks/main.yml
  templates/docker-compose.s1_monitor.yml.j2
  files/
    Dockerfile
    dev/
      docker-compose.dev.yml          # local run on a workstation, DB via Tailscale
      .env.example                    # DB_HOST, DB_USER, DB_PASS; real .env is gitignored
    app/
      requirements.txt
      main.py                         # FastAPI app, routes, lifespan, static mount
      config.py                       # env vars with defaults
      db.py                           # pyodbc connect, query(sql, params) -> list[dict], timeouts
      cache.py                        # TTL cache keyed by (endpoint, params); stale-on-error
      timewin.py                      # SAST helpers, window parsing, resolution choice
      rates.py                        # pure: bucket rate maths, low-volume flag
      availability.py                 # pure: outages from row timestamps; transitions from history
      severity.py                     # pure: needs-attention rules (mirrors reporter rules)
      trends.py                       # pure: week-over-week deltas, expected-volume band
      queries/
        fleet.py                      # status strip, per-device today, sparklines
        device.py                     # series, availability rows, health rows
        trends.py                     # small multiples, hour-of-week baseline
        pipeline.py                   # broker, ingest state, backlog
      snapshots.py                    # health snapshot job, table DDL, pruning
      migrations/
        001_device_health_history.sql
      static/
        index.html                    # Fleet
        device.html                   # Device diagnosis
        trends.html                   # Trends
        pipeline.html                 # Pipeline
        app.css                       # theme tokens, layout
        api.js                        # fetch wrapper, stale banner
        charts.js                     # ECharts theme, shared-axis helpers, band/line helpers
        vendor/echarts.min.js         # pinned ECharts 5.x UMD, copied into the image
  tests/
    conftest.py
    test_timewin.py
    test_rates.py
    test_availability.py
    test_severity.py
    test_trends.py
    test_api.py                       # FastAPI TestClient with a fake query()
    test_snapshots.py                 # snapshot row shaping and transition detection
    test_role_files.py                # Dockerfile, compose template, defaults, vendor file present
```

### Configuration (defaults/main.yml to compose environment)

| Env var | Default | Ansible var |
|---|---|---|
| `DB_HOST` | `mssql` | `s1_monitor_db_host` |
| `DB_PORT` | `1433` | `s1_monitor_db_port` |
| `DB_NAME` | `S1_Remote_Monitoring` | `s1_monitor_db_name` |
| `DB_USER` | `admin` | `s1_monitor_db_user` (from `mssql_rm_admin_login`) |
| `DB_PASS` | | `s1_monitor_db_pass` (from `mssql_rm_admin_password`) |
| `TZ_OFFSET_HOURS` | `2` | `s1_monitor_tz_offset_hours` |
| `MIN_ITEMS_FOR_RATES` | `100` | `s1_monitor_min_items_for_rates` |
| `OFFLINE_GAP_MINUTES` | `11` | `s1_monitor_offline_gap_minutes` |
| `STALE_DAYS` | `14` | `s1_monitor_stale_days` |
| `SNAPSHOT_ENABLED` | `true` | `s1_monitor_snapshot_enabled` |
| `SNAPSHOT_INTERVAL_MINUTES` | `15` | `s1_monitor_snapshot_interval_minutes` |
| `SNAPSHOT_RETENTION_DAYS` | `400` | `s1_monitor_snapshot_retention_days` |
| `CACHE_TTL_LIVE_SECONDS` | `30` | `s1_monitor_cache_ttl_live` |
| `CACHE_TTL_HISTORY_SECONDS` | `300` | `s1_monitor_cache_ttl_history` |
| `QUERY_TIMEOUT_SECONDS` | `20` | `s1_monitor_query_timeout` |

Role-level: `s1_monitor_image: s1-monitor:latest`, `s1_monitor_dir: /opt/s1-monitor`,
`s1_monitor_port: 8090`, `s1_monitor_bind_address: 127.0.0.1`. The container sets
`TZ=Africa/Johannesburg` for log timestamps only; all bucketing uses `TZ_OFFSET_HOURS`.

### Image

Same two-stage pattern as `marketing_display`: `python:3.12-slim-bookworm`, `msodbcsql18`,
`unixodbc`, pinned `fastapi`, `uvicorn[standard]`, `pyodbc`. Non-root `appuser`. Healthcheck
hits `/health`, which returns 200 only if the last database query succeeded within
`3 x CACHE_TTL_LIVE_SECONDS` or a probe query succeeds now. `static/vendor/echarts.min.js` is
committed to the repo so the page works with no internet access from the browser.

## Data layer

### Time and windows

Every endpoint that takes a window accepts `from` and `to` as ISO-8601 UTC or as a preset
(`24h`, `7d`, `30d`, `90d`, `1y`). "Today", "this week" and day boundaries are computed in
SAST by `DATEADD(HOUR, ?, ts_datetime)` with `TZ_OFFSET_HOURS` bound as a parameter. The
API returns bucket timestamps as UTC ISO strings; the browser formats them in SAST.

Resolution is chosen by `timewin.resolution(window)`:

| Window | Bucket | Source |
|---|---|---|
| up to 2 days | 5 min (raw rows) | `device_statistics` rows as-is |
| up to 14 days | 1 hour | `DATEADD(HOUR, DATEDIFF(HOUR, 0, local_ts), 0)` |
| up to 120 days | 1 day | `CAST(local_ts AS date)` |
| over 120 days | 1 week (Mon to Sun) | `DATEADD(DAY, -((DATEPART(WEEKDAY, local_ts)+5)%7), CAST(local_ts AS date))` with `SET DATEFIRST 7` semantics handled in Python |

Responses carry `bucket_seconds` so the client can draw bar widths and decide when a zoom
warrants a refetch (when the visible span drops below 4 buckets of the next finer resolution).

### Rates

A bucket's rate is `100 x SUM(part) / SUM(total_items)` over rows in the bucket. Rates are
never averaged from per-row percentages. A bucket with `SUM(total_items) < MIN_ITEMS_FOR_RATES`
is returned with `low_volume: true` and its rates present but flagged; the UI draws those
points hollow and excludes them from the y-axis autoscale. Which rates a device gets:

| Rate | Formula | Shown when |
|---|---|---|
| `good_read_pct` | good_read / total_items | always |
| `no_dim_pct` | no_dimension / total_items | `has_dimension` |
| `no_weight_pct` | no_weight / total_items | `has_weight` |
| `hand_scan_pct` | hand_scanned / total_items | `has_hand_scan` |
| `not_sent_pct` | not_sent / total_items | always |
| `multi_item_pct` | more_than_1_item / total_items | `has_dimension` |

### Thresholds and baselines

`queries.device.thresholds(device)` returns, per metric, `warn`, `bad`, `direction`,
`baseline_mean`, `baseline_stddev`, `baseline_p10`, `baseline_p90` from `dbo.alert_thresholds`
matched on `(customer, machine_name, location)`, falling back to the customer-wide row
(`machine_name IS NULL AND location IS NULL`), then to `customer_config` percentages
(`good_read_warn_pct`, `good_read_bad_pct`, `no_dim_warn_pct`, `no_dim_bad_pct`,
`hand_scan_warn_pct`, `no_weight_warn_pct`). Storage limits come from `customer_config`
(`storage_warn_pct`, `storage_bad_pct`). The lookup order is the reporter's.

The expected-volume band is computed per device by `queries.trends.hour_of_week_profile`:
for the trailing 8 weeks, group items per hour by `weekday x 24 + hour` (SAST) and take
`PERCENTILE_CONT(0.25/0.5/0.75)`. The device series endpoint joins each bucket to its slot's
quartiles (summed over the slots a daily or weekly bucket covers) and returns them as
`expected_p25`, `expected_p50`, `expected_p75`. The band is drawn behind the volume bars.

### Availability from cadence

`availability.outages(timestamps, gap_minutes, window_end)` walks a device's row timestamps
in order and emits `{start, end, minutes}` for each gap longer than `OFFLINE_GAP_MINUTES`,
where `start` is the last row before the gap plus 5 minutes and `end` is the next row. If
the final row is older than the gap, an open outage ends at `window_end` with `open: true`.
The device endpoint fetches only `ts_datetime` for the window, which is cheap on
`IX_device_statistics_ts (device_id, ts_datetime)`.

Device state for the fleet screen follows the reporter's `liveness.classify`: `stale` when
last seen is at least `STALE_DAYS` old, `never` when no rows, `offline` when last seen is at
least `OFFLINE_GAP_MINUTES` old, else `online`. Devices with `reporting_enabled = 0` are shown
greyed with a "reporting disabled" tag, never hidden. `muted_until` in the future shows a
"muted" tag and drops the device from the needs-attention list.

### Health history

`migrations/001_device_health_history.sql`, applied idempotently at startup:

```sql
IF OBJECT_ID(N'dbo.device_health_history', N'U') IS NULL
CREATE TABLE dbo.device_health_history (
    id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
    device_id           INT          NOT NULL,
    snapshot_utc        DATETIME2(0) NOT NULL,
    status              NVARCHAR(40) NULL,     -- device_status.status
    status_ts_utc       DATETIME2(0) NULL,
    application_running BIT          NULL,
    app_ts_utc          DATETIME2(0) NULL,
    uptime_seconds      DECIMAL(18,3) NULL,
    cpu_percent         DECIMAL(5,2) NULL,
    mem_usage_pct       DECIMAL(5,2) NULL,
    temp_celsius        DECIMAL(5,2) NULL,
    c_usage_percent     DECIMAL(5,2) NULL,
    max_usage_percent   DECIMAL(5,2) NULL,
    drives_json         NVARCHAR(MAX) NULL,    -- [{"drive":"C:","total_gb":..,"free_gb":..,"usage_percent":..}]
    last_stats_utc      DATETIME2(0) NULL      -- MAX(device_statistics.ts_datetime) at snapshot time
);
CREATE INDEX IX_device_health_history_device_ts
    ON dbo.device_health_history (device_id, snapshot_utc);
```

`snapshots.run_once(query, execute, now_utc)` reads one joined row per device from the
latest-value tables and inserts one history row each. It runs every
`SNAPSHOT_INTERVAL_MINUTES`, first run 60 seconds after startup. Once a day it deletes rows
older than `SNAPSHOT_RETENTION_DAYS`. Failures are logged with the exception and retried at
the next tick; they never stop the API. `SNAPSHOT_ENABLED=false` turns the task off entirely
(used by the workstation dev compose so a laptop never writes history into production).

Derived events from consecutive rows (`availability.transitions(rows)`):

- **uptime reset**: `uptime_seconds` smaller than the previous row's by more than the
  interval means the device rebooted at approximately `snapshot_utc - uptime_seconds`.
- **app stopped / started**: `application_running` changes value.
- **status change**: `status` changes value.

The device screen's health lanes are empty until rows exist. The UI says "history starts
<date>" using `MIN(snapshot_utc)` for that device.

### Caching and failure

`cache.get_or_build(key, ttl, builder)` keeps one entry per `(endpoint, sorted params)`.
TTL is `CACHE_TTL_LIVE_SECONDS` when the window includes now and
`CACHE_TTL_HISTORY_SECONDS` otherwise. On a builder exception with a cached entry, the entry
is returned with `"stale": true` and `"stale_since"`; with no entry the endpoint returns
503 `{ "detail": "<exception class>: <message>" }`. `api.js` shows a persistent top banner
"Showing data from HH:MM, database unreachable" when `stale` is set, and an error panel on
503. Every query runs with `QUERY_TIMEOUT_SECONDS` via pyodbc's `timeout`.

## API

All endpoints are `GET`, JSON, no auth. Times are UTC ISO-8601. `device_id` is
`dbo.devices.id`; machine names are never used as keys because `DIM1` repeats across sites.

| Endpoint | Params | Returns |
|---|---|---|
| `/health` | | `{status, db_ok, last_query_utc, snapshot_last_utc}` |
| `/api/meta` | | customers with capabilities, devices list (`id, customer, location, machine_name, serial_number, reporting_enabled, muted_until`), `tz_offset_hours`, `min_items_for_rates`, `history_since` |
| `/api/fleet` | `customer?` | `strip` (online, offline, stale, never, disabled, last_db_write_utc, db_write_age_s, broker_clients, deadletter), `attention[]` (severity, device, rule, value, limit, since), `devices[]` (state, last_seen, today items/rates, 24h sparkline arrays of items and good_read_pct at hourly buckets, c_usage_percent, app_running) |
| `/api/device/{id}` | | header: identity, state, last_seen, current health row, os_version, thresholds per metric, capabilities, history_since |
| `/api/device/{id}/series` | `from, to` | `bucket_seconds`, `buckets[]` with `ts, items, good_read, no_read, no_dimension, no_weight, hand_scanned, not_sent, more_than_1_item, rates{...}, low_volume, expected_p25/p50/p75` |
| `/api/device/{id}/availability` | `from, to` | `outages[]`, `events[]` (uptime_reset, app_stopped, app_started, status_change with ts and detail), `uptime_pct` |
| `/api/device/{id}/health` | `from, to` | history rows thinned to at most 2,000 points: `ts, cpu_percent, mem_usage_pct, temp_celsius, c_usage_percent, max_usage_percent`, plus `drives_latest[]` |
| `/api/trends` | `metric, from, to, customer?` | `bucket_seconds`, `devices[]` each with `series[]` and `warn`/`bad`; and `wow[]` rows: device, this_week, prev4_median, delta_abs, delta_pct, sparkline (last 5 weeks) |
| `/api/pipeline` | `from, to` | `broker[]` (ts, clients_connected, load_msgs_recv_1min, msgs_received delta), `ingest` (last_db_write_utc, age_s, last_error_utc, deadletter_count), `ingest_gaps[]` (minutes with zero rows fleet-wide, merged into intervals), `backlog[]` (device, consecutive_not_sent_packets, total_not_sent, since) |

Validation: `from < to`, window at most 400 days, unknown `device_id` gives 404, unknown
`metric` gives 400. `customer` filters by exact `dbo.devices.customer`.

### Needs-attention rules (`severity.py`)

Evaluated over "today so far" (SAST) per device, in this order, first match per rule:

| Rule | bad | warn | Skipped when |
|---|---|---|---|
| no data | state `offline` or `never` | | stale, muted, disabled |
| upload stuck | last 3 packets all `total_items > 0 AND not_sent > 0` | | |
| good read | below `bad` | below `warn` | today items < `MIN_ITEMS_FOR_RATES` |
| no-dim | above `bad` | above `warn` | not `has_dimension`, or low volume |
| hand scan | | above `hand_scan_warn_pct` | not `has_hand_scan`, or low volume |
| no weight | | above `no_weight_warn_pct` | not `has_weight`, or low volume |
| storage | C: above `storage_bad_pct` | above `storage_warn_pct` | |
| app stopped | `application_running = 0` | | |

Ordering of the list: bad before warn, then by how far past the limit, then device name.

## Screens

Shared chrome: top bar with "S1 Remote Monitoring", nav (Fleet, Trends, Pipeline), customer
filter, refresh countdown, stale banner slot. Dark palette and tokens from the current site
(`#0f1117` background family, Inter with system fallback), semantic colours reserved for
state: green online/ok, amber warn, red bad, blue informational, grey disabled/low-volume.
Pages poll their endpoints every 60 seconds while visible.

### Fleet (`index.html`)

1. Status strip: seven tiles (online, offline, stale, never, DB write age, broker clients,
   dead letters). Tiles colour by state; DB write age turns amber over 10 minutes, red over
   30.
2. Needs attention: a list, empty state "Nothing needs attention", each row showing
   severity dot, device (`machine_name @ location`, customer), rule, value against limit,
   and "since" where known. Row click opens the device with a 24h window.
3. Devices: one compact row per device grouped by customer: state dot and last seen, today
   items, good read % (coloured against that device's own warn/bad), two 24-hour sparklines
   (items, good read %), C: usage, app running. Sorted by customer, location, machine.
   Disabled devices greyed at the bottom of their customer group.

### Device (`device.html?id=`)

Header: `machine_name @ location`, customer, serial, state and last seen, OS version, uptime,
capability tags, "history starts <date>". Range picker: 24h, 7d, 30d, 90d, custom from/to.
Charts stacked in one ECharts instance with `axisPointer.link` and a shared `dataZoom`
(slider at the bottom plus drag-to-zoom inside; double-click resets):

1. **Items per bucket** (bars) with the expected band (p25 to p75 shaded, p50 line).
2. **Quality rates** (one line chart per applicable rate, `good_read_pct` first): warn and
   bad as dashed `markLine`s in amber and red, baseline mean plus or minus stddev as a faint
   band, low-volume points hollow. The y-axis floors at `min(lowest visible non-low-volume
   point, bad line) - 5` rather than a fixed range.
3. **Availability lane**: outages as red blocks, app-stopped as amber blocks, uptime resets
   and status changes as markers, with `uptime_pct` for the window in the lane title.
4. **Host health lanes** (only when history rows exist): C: usage with storage warn/bad
   lines, memory %, CPU %, temperature.

Zoom refetch: when the visible span falls below 4 buckets at the next finer resolution,
`api.js` refetches `series` for the visible range and swaps the data without resetting zoom.

### Trends (`trends.html`)

Controls: metric (items, good_read_pct, no_dim_pct, hand_scan_pct, not_sent_pct,
c_usage_percent), window (7d, 30d, 90d, 1y), customer. Small multiples: one panel per device
on a shared y-scale, each with its own warn line where the metric has one, so a device that
drifts stands out from its neighbours. Devices lacking the capability for the metric are
omitted with a count note. Below, the week-over-week table: device, this week (Mon to now),
median of the previous 4 full weeks, delta, 5-week sparkline; sorted by worst delta in the
metric's bad direction.

### Pipeline (`pipeline.html`)

Window 24h or 7d. Tiles: last DB write age, dead letters, broker clients connected against
registered devices, broker uptime. Charts: broker clients over time; messages received per
minute; ingest gap lane (fleet-wide minutes with zero rows). Table: upload backlog devices
with consecutive failing packets, total not sent and since.

## Cutover

1. Merge the role behind a feature branch; first deploy with `--tags s1_monitor` while
   `marketing_display` still holds 8090, using `s1_monitor_port: 8093` in
   `host_vars/sysone.yml`, checked through an SSH tunnel.
2. Cutover PR: remove the port override; remove `marketing_display` and
   `scan_fleet_dashboard` from `webservers.yml`; add a `retire_legacy_dashboards` task list
   in the `s1_monitor` role that runs `docker compose down --rmi local` in
   `/opt/marketing-display` and `/opt/scan-fleet-dashboard` when those directories exist;
   update README service and port tables and the architecture diagram; delete the two old
   roles and their tests; update `ci.yml`.
3. Deploy. Cloudflare route `sysone.co.za -> localhost:8090` is unchanged.
4. Snapshot table starts filling on first start. Verify with `/health` and
   `SELECT COUNT(*) FROM dbo.device_health_history`.

## Testing

- **Unit (pytest, no database):** `timewin` presets, SAST day boundaries, resolution table;
  `rates` sums and low-volume flag; `availability.outages` on synthetic timestamp lists
  (no gaps, one gap, open gap at the end, gap exactly at the threshold) and `transitions`
  (uptime reset, app stop/start, status change); `severity` ordering and every skip rule;
  `trends` week-over-week with fewer than 4 previous weeks and with zero medians.
- **API:** FastAPI `TestClient` with `db.query` replaced by a fake returning canned rows;
  checks response shapes, 404/400 validation, stale flag on builder failure, 503 on cold
  failure, `/health` semantics.
- **Snapshots:** row shaping from a joined latest-values row; pruning SQL parameters;
  scheduler tick does not raise when `execute` fails.
- **Role files:** Dockerfile has the ODBC install and non-root user; compose template renders
  with defaults; `static/vendor/echarts.min.js` exists and is the pinned version; no
  `GETDATE()` without the offset parameter anywhere in `queries/`.
- **CI:** `python -m pytest roles/s1_monitor/tests` added to `ci.yml`; the retired roles'
  test steps are removed at cutover.
- **Manual acceptance on the workstation:** run the dev compose against the production
  database over Tailscale; open a PEPKOR JBH device at 30 days and zoom to a single day; open
  DCB DUR and confirm its warn line sits at its own baseline, not 90%; open MADIBANA PE and
  confirm today's outage appears in the availability lane; open Pipeline and confirm the
  broker client count matches `docker ps` on the host.

## Local development

```
cd roles/s1_monitor/files/dev
cp .env.example .env        # DB_HOST=100.102.46.89 DB_USER=... DB_PASS=...
docker compose -f docker-compose.dev.yml up --build
# http://localhost:8090
```

`.env` is covered by `.gitignore`. The dev compose bind-mounts `../app/static` so page edits
show on refresh without a rebuild; Python changes rebuild the image. The snapshot task is off
in dev (`SNAPSHOT_ENABLED=false`); set it true deliberately to test the job against
production.
