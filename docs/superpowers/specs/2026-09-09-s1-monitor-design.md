# s1_monitor: fault-diagnosis website — Design

**Date:** 2026-09-09 (revised the same day after a clickable demo review)
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
- Devices differ in volume by four orders of magnitude. Percentages on low volumes are noise.
- Metric meaning is per customer: PEPKOR reports `no_weight` equal to `total_items` because
  no scale is fitted; PEP STATIC devices never fill `complete`. `dbo.customer_config` carries
  the capability flags (`has_dimension`, `has_weight`, `has_hand_scan`).
- `total_items = good_read + no_read` holds exactly. `hand_scanned`, `no_dimension`,
  `no_weight`, `not_sent` and `more_than_1_item` are flags that overlap with those two and
  with each other.
- `dbo.alert_thresholds` holds per-device warn/bad values plus a 60-day baseline for
  `good_read_pct` (low) and `no_dim_pct` (high). The current site ignores it and hard-codes
  "target 98%, minimum 90%". DCB DUR's baseline mean is 65%, so the fixed line is
  permanently red there.
- The current site mixes `GETDATE()` with and without a +2h shift, so "today" starts at
  different times on different panels.

The product owner's reference for legibility is the printed SLA inspection report
(`PKL JHB SLA Inspections 10 December 2024.pdf`): one point per day with a marker, a dashed
average line that states its value, a date-by-hour throughput heatmap with the number
written in every cell, and a Maximum / Minimum / Average table under each figure.

Decisions taken with the product owner on 2026-09-09, confirmed on a clickable demo built
from a live data pull: internal ops audience with no login; good read is the headline
metric; the site records its own health snapshots; plain FastAPI plus static pages with a
vendored chart library, no JS build toolchain; no broker or pipeline screens.

## Goals

1. Diagnose a quality fault on one device from a single screen in the report's idiom:
   summary table, daily figures with average and the device's own warn/bad lines, error
   breakdown, throughput heatmap, outage list.
2. Compare machines on the same figures.
3. Surface slow degradation: small multiples per device and week-over-week deltas.
4. One definition of "today", of a rate, of low volume, and of offline, shared with the
   reporter.
5. Every figure downloadable as a labelled PNG with a meaningful filename.
6. Accumulate host health history from deployment day onward.
7. Replace `marketing_display` and `scan_fleet_dashboard` with one role on port 8090 so the
   Cloudflare route is untouched.

## Non-goals

- Login, per-customer scoping or any use of `dbo.customer_login_map`.
- Editing `customer_config`, `alert_thresholds` or device flags from the UI.
- Changing `mqtt_ingestor`, `s1_reporter` or `s1_baselines`.
- Broker statistics, ingest gap views, or any pipeline screen. The only pipeline signal on
  the site is the last database write age on the Fleet strip.
- TV/kiosk mode. Alerting (Teams remains the reporter's job). PDF export.

## Architecture

### Runtime

```
browser -- Cloudflare tunnel -- 127.0.0.1:8090 -- s1_monitor (uvicorn, one process)
                                                    |-- FastAPI /api/*  (read: dbo.*, ingest.pipeline_state)
                                                    |-- static pages + vendored ECharts
                                                    `-- asyncio snapshot task every 15 min
                                                          `-- writes dbo.device_health_history
```

One container, one replica. The snapshot task lives in the API process. No second
container, no host cron. The image is built on the host by Ansible like every other role.

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
      timewin.py                      # SAST helpers, range presets, bucket sizes
      rates.py                        # pure: bucket rate maths, low-volume flag, summary stats
      availability.py                 # pure: outages from row timestamps; transitions from history
      severity.py                     # pure: needs-attention rules (mirrors reporter rules)
      trends.py                       # pure: week-over-week deltas
      thresholds.py                   # pure: lookup order device row -> customer row -> customer_config
      queries/
        fleet.py                      # strip, per-device today and 30 days, 24h hourly sparkline
        device.py                     # header, bucketed series, hourly rows, timestamps for outages
        trends.py                     # daily per device over a window
        health.py                     # history rows for the host section
      snapshots.py                    # health snapshot job, table DDL, pruning
      migrations/
        001_device_health_history.sql
      static/
        index.html                    # single page, hash routes #fleet, #device/<id>/<range>[/cmp=a,b], #trends[/tiles|/table]
        app.css                       # theme tokens, layout
        api.js                        # fetch wrapper, stale banner, bell
        charts.js                     # ECharts theme, figure builders, heatmap, doughnut, download
        app.js                        # router, screen rendering, polling
        vendor/echarts.min.js         # pinned ECharts 5.5.1 UMD
  tests/
    conftest.py
    test_timewin.py
    test_rates.py
    test_availability.py
    test_severity.py
    test_trends.py
    test_thresholds.py
    test_api.py                       # FastAPI TestClient with a fake query()
    test_snapshots.py
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
| `MIN_ITEMS_DAY` | `100` | `s1_monitor_min_items_day` |
| `MIN_ITEMS_HOUR` | `30` | `s1_monitor_min_items_hour` |
| `MIN_ITEMS_HALF_HOUR` | `15` | `s1_monitor_min_items_half_hour` |
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
committed to the repo so the page works with no internet access from the browser. Inter is
loaded from Google Fonts with a system-sans fallback, as the current site does.

## Data layer

### Time and ranges

"Today", day boundaries and week boundaries are computed in SAST. In SQL this is done by a
subquery that computes `local_ts = DATEADD(HOUR, ?, ts_datetime)` once, with
`TZ_OFFSET_HOURS` bound as a parameter, and outer queries group on expressions of `local_ts`.
(SQL Server rejects a parameterised expression that appears in both SELECT and GROUP BY,
so the subquery form is mandatory.) The API returns bucket timestamps as UTC ISO strings;
the browser formats them in SAST.

Ranges are presets, not free windows. Each preset fixes its bucket:

| Preset | Window | Bucket | Low-volume threshold | Figure style |
|---|---|---|---|---|
| `24h` | last 24 hours to now | 30 min | `MIN_ITEMS_HALF_HOUR` | bars |
| `48h` | last 48 hours to now | 1 hour | `MIN_ITEMS_HOUR` | bars |
| `7d` | 7 SAST days ending today | 1 day | `MIN_ITEMS_DAY` | line with markers |
| `30d` | 30 SAST days ending today | 1 day | `MIN_ITEMS_DAY` | line with markers |
| `90d` | 90 SAST days ending today | 1 day | `MIN_ITEMS_DAY` | line with markers |

Daily presets also fetch hourly buckets for the same window, for the heatmap and for the
items-per-hour summary column. A bucket with no rows at all is returned as `nodata: true`
(distinct from a bucket with rows and zero items).

### Rates

A bucket's rate is `100 x SUM(part) / SUM(total_items)` over rows in the bucket. Rates are
never averaged from per-row percentages. A bucket under its low-volume threshold carries
`low_volume: true`; the UI draws it hollow and excludes it from averages. Which rates a
device gets is decided by its customer's capabilities:

| Rate | Formula | Shown when |
|---|---|---|
| `good_read_pct` | good_read / total_items | always |
| `no_read_pct` | no_read / total_items | heatmap only, always |
| `no_dim_pct` | no_dimension / total_items | `has_dimension` |
| `no_weight_pct` | no_weight / total_items | `has_weight` |
| `hand_scan_pct` | hand_scanned / total_items | `has_hand_scan` |
| `not_sent_pct` | not_sent / total_items | always |
| `multi_item_pct` | more_than_1_item / total_items | `has_dimension`, error list only |

**Every percentage axis is fixed at 0 to 100.** No autoscaling of rate axes anywhere.

### Summary statistics (report Tables 6 and 7)

For the chosen range: Maximum, Minimum and Average of items per bucket over buckets with
data; of good read % over buckets at or above the low-volume threshold; and of items per
hour (daily presets, hours with at least one item) or items per 5-minute packet (detail
presets, packets with at least one item). Computed in `rates.summary()` from the bucket
list so the API and the UI cannot disagree.

### Error breakdown

The doughnut is a true partition of items: `good_read`, and `no_read` split into
"recovered by hand scan" (`min(hand_scanned, no_read)`) and "not recovered" when the
customer has hand scanning, otherwise a single `no_read` slice. Flags that overlap
(`no_dimension`, `no_weight`, `not_sent`, `more_than_1_item`) are listed under the ring
with counts and share of items, gated by capability, never drawn as slices. The panel
states which flags are not measured on this machine.

### Thresholds

`thresholds.lookup(rows, cfg, customer, machine, location, metric)` returns `warn`, `bad`,
`direction`, baseline fields and a `source` label, using the reporter's order: device row in
`dbo.alert_thresholds`, then the customer-wide row (`machine_name IS NULL AND location IS
NULL`), then `customer_config` percentages. Storage limits come from `customer_config`.

### Availability from cadence

`availability.outages(timestamps, gap_minutes, window_end)` walks a device's row timestamps
and emits `{start, end, minutes, open}` for each gap longer than `OFFLINE_GAP_MINUTES`,
where `start` is the last row before the gap plus 5 minutes. Device state follows the
reporter's `liveness.classify`: `stale` at or beyond `STALE_DAYS`, `never` with no rows,
`offline` at or beyond `OFFLINE_GAP_MINUTES`, else `online`. Devices with
`reporting_enabled = 0` are shown greyed with a tag, never hidden; `muted_until` in the
future shows a tag and drops the device from needs-attention.

### Health history

`migrations/001_device_health_history.sql`, applied idempotently at startup:

```sql
IF OBJECT_ID(N'dbo.device_health_history', N'U') IS NULL
CREATE TABLE dbo.device_health_history (
    id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
    device_id           INT          NOT NULL,
    snapshot_utc        DATETIME2(0) NOT NULL,
    status              NVARCHAR(40) NULL,
    status_ts_utc       DATETIME2(0) NULL,
    application_running BIT          NULL,
    app_ts_utc          DATETIME2(0) NULL,
    uptime_seconds      DECIMAL(18,3) NULL,
    cpu_percent         DECIMAL(5,2) NULL,
    mem_usage_pct       DECIMAL(5,2) NULL,
    temp_celsius        DECIMAL(5,2) NULL,
    c_usage_percent     DECIMAL(5,2) NULL,
    max_usage_percent   DECIMAL(5,2) NULL,
    drives_json         NVARCHAR(MAX) NULL,
    last_stats_utc      DATETIME2(0) NULL
);
CREATE INDEX IX_device_health_history_device_ts
    ON dbo.device_health_history (device_id, snapshot_utc);
```

`snapshots.run_once(query, execute, now_utc)` inserts one row per device from the
latest-value tables every `SNAPSHOT_INTERVAL_MINUTES`, first run 60 seconds after startup,
pruning rows older than `SNAPSHOT_RETENTION_DAYS` once a day. Failures are logged and
retried next tick. `SNAPSHOT_ENABLED=false` turns the task off (workstation dev compose).
`availability.transitions(rows)` derives uptime resets, app stop/start and status changes
from consecutive rows.

### Caching and failure

`cache.get_or_build(key, ttl, builder)` keeps one entry per `(endpoint, sorted params)`.
TTL is `CACHE_TTL_LIVE_SECONDS` for the `24h`/`48h` presets and fleet, and
`CACHE_TTL_HISTORY_SECONDS` for the daily presets and trends. On a builder exception with a
cached entry, the entry is returned with `stale: true` and `stale_since`; with no entry the
endpoint returns 503 `{ "detail": "<exception class name>" }`. The exception message never
reaches the response body; it is logged server-side with the traceback. `api.js` shows a persistent banner "Showing data from
HH:MM, database unreachable" when `stale` is set, and an error panel on 503. Every query
runs with `QUERY_TIMEOUT_SECONDS`.

## API

All endpoints are `GET`, JSON, no auth. Times are UTC ISO-8601. `device_id` is
`dbo.devices.id`; machine names are never keys because `DIM1` repeats across sites.

| Endpoint | Params | Returns |
|---|---|---|
| `/health` | | `{status, db_ok, last_query_utc, snapshot_last_utc, snapshot_ok, snapshot_error_class}`; the error is reported as a class name or null, never as a message |
| `/api/meta` | | customers with capabilities and limits, devices list (`id, customer, location, machine_name, serial_number, reporting_enabled, muted_until`), thresholds per device per metric (with `source`), `tz_offset_hours`, the three low-volume thresholds, `history_since` |
| `/api/fleet` | `customer?` | `strip` (online, offline, stale, never, disabled, items_today, good_read_today_pct, items_30d, good_read_30d_pct, last_db_write_utc, db_write_age_s), `attention[]` (severity, device_id, rule, value, limit, since), `devices[]` (state, last_seen, today items and good_read_pct with low_volume, 30-day items and good_read_pct with low_volume, 24 hourly item counts, `c_usage` and `max_usage` as percentages, app_running) |
| `/api/device/{id}` | | identity, state, last_seen, latest health row, os_version, drives, capabilities, thresholds per metric, `history_since` |
| `/api/device/{id}/series` | `range` (preset) | `bucket_seconds`, `from`, `to`, `buckets[]` with `ts, nodata, items, good_read, no_read, no_dimension, no_weight, hand_scanned, not_sent, more_than_1_item, low_volume`, `hourly[]` (same shape, daily presets only), `summary` (max/min/avg per the rules above; its `per_unit` block holds items per hour on daily presets and items per packet, label `"packet"`, on detail presets), `totals` (sums over the range), `outages[]` |
| `/api/device/{id}/health` | `range` | history rows thinned to at most 2,000 points plus `events[]` from transitions; empty arrays with `history_since: null` until snapshots exist |
| `/api/trends` | `metric, range (7d/30d/90d), customer?` | `devices[]` each with `daily[]` (`ts, value, items, low_volume`), `average`, `warn`; `wow[]` rows: device, this_week, prev4_median, delta_abs, delta_pct, last5[] |

Validation: unknown `range` or `metric` gives 400, unknown `device_id` gives 404.
`customer` filters by exact `dbo.devices.customer`. Comparison is client-side: the device
page calls `/api/device/{id}/series` once per compared device.

### Needs-attention rules (`severity.py`)

Evaluated over today so far (SAST) per device, in this order:

| Rule | bad | warn | Skipped when |
|---|---|---|---|
| no data | state `offline` or `never` | | stale, muted, disabled (stale devices are excluded from every rule, matching the reporter) |
| upload stuck | last 3 packets all `total_items > 0 AND not_sent > 0` | | |
| good read | below `bad` | below `warn` | today items < `MIN_ITEMS_DAY` |
| no-dim | above `bad` | above `warn` | not `has_dimension`, or low volume |
| hand scan | | above `hand_scan_warn_pct` | not `has_hand_scan`, or low volume |
| no weight | | above `no_weight_warn_pct` | not `has_weight`, or low volume |
| storage | C: above `storage_bad_pct` | above `storage_warn_pct` | |
| app stopped | `application_running = 0` | | |

Ordering: bad before warn, then by how far past the limit, then device name.

## Screens

Shared chrome: top bar with "S1 Remote Monitoring", nav (Fleet, Device, Trends), customer
filter, "Data as of HH:MM SAST", and a **bell** with a count badge (red if any bad item,
amber if warnings only). Clicking the bell opens a panel listing needs-attention items;
clicking an item opens that device at `24h`. Pages fill the full window width. Dark palette
and tokens from the current site (`#0f1117` page, `#151a23` panels, Inter), semantic
colours reserved for state: green ok, amber warn, red bad, blue informational, grey
disabled or low volume. Pages poll every 60 seconds while visible.

### Fleet (route `#fleet`)

1. Strip of seven tiles: Online, Offline, Stale, Items today, Good read today, Good read 30
   days, Last DB write (amber over 10 minutes, red over 30).
2. Device table grouped by customer with a colour swatch per customer: device and serial,
   state dot, last seen, items today, **good read today** (large, coloured against the
   device's own warn/bad, hollow dot when under `MIN_ITEMS_DAY`), **good read 30 days**
   (same treatment, weighted by items), items over the last 24 hours as a small bar
   sparkline, C: drive meter coloured against storage limits, app running. Disabled devices
   greyed with a tag. Row click opens the device.

No needs-attention list on the page; it lives in the bell.

### Device (route `#device/<id>/<range>[/cmp=a,b]`)

Header panel in four aligned columns: identity (name, customer, serial, capabilities),
state (state, last seen, app, uptime), host (drives, CPU, memory, temperature), OS and
history start. Tool row: device selector, range presets `7d 30d 90d`, detail presets
`24h 48h`, **Compare with…** picker (checkbox list; chosen machines appear as removable chips
and as extra series on every figure, categorical colours, legend), and a hint line.

Body, top to bottom:

1. **Summary** (report Table 6 and 7): Maximum / Minimum / Average for items per bucket,
   good read %, items per hour (daily) or per packet (detail); outage count and longest;
   the device's warn and bad limits with their source; the low-volume rule in words.
2. **Errors** doughnut for the range with the centre stating good read %, legend table with
   counts and shares, "also flagged" list, and the not-measured line.
3. **Total items** per bucket: daily presets draw a line with markers, weekends shaded;
   detail presets draw bars with no-data buckets shaded grey. Dashed average line stating
   its value.
4. **Good read %**: same style, y fixed 0 to 100, dashed average, dashed warn (amber) and
   bad (red) lines with values, hollow marks for low volume.
5. **Other rates** that apply to the machine, in a row of smaller panels, each with average
   and limits, y fixed 0 to 100.
6. **Throughput heatmap** (daily presets only): rows are dates, columns hours 00 to 23,
   value written in every cell at every range (rows 30px for 7d, 20px otherwise). A metric
   selector in the header offers Items per hour, Good read %, No read %, and the applicable
   error rates; percentage metrics use a fixed 0 to 100 scale and leave hours under
   `MIN_ITEMS_HOUR` unlabelled. Hours with no rows are red; hours with rows and zero items
   are empty. Sequential blue ramp for magnitude so red only ever means "no data".
7. **Outages in range** table (started, ended or "still silent", duration) beside **Host
   history** (disk, memory, CPU, temperature lines and app/reboot markers once snapshot rows
   exist; a note about the start date until then). If the host-history request fails, that
   panel shows a local notice; the rest of the page still renders.

Every figure (doughnut, items, good read, each rate, heatmap) has a download button that
produces a 2x PNG with a header stamped in (device and figure name, customer, limits or
compared machines, data timestamp) and a filename
`S1_<customer>_<location>_<machine>_<figure>_<range>_<yyyymmdd-hhmm>.png`.

### Trends (route `#trends[/tiles|/table]`)

Sub-menu with two pages. Controls above both: metric (items, good read %, no dimension %,
hand scanned %, not sent %) and window (7, 30, 90 days).

- **Machines**: one tile per device on a shared scale (percentages 0 to 100), one marker per
  day, the device's own warn line, the average stated in the tile title, hollow low-volume
  points, a download button, click through to the device. Devices lacking the capability
  are omitted with a count note, as are devices with `reporting_enabled = 0`. Percentage tiles
  share the fixed 0 to 100 scale; items tiles autoscale per device, because device volumes differ
  by four orders of magnitude and one shared items scale flattens every small machine to nothing.
- **Week over week**: table of this week (Monday to now) against the median of the previous
  four full weeks, delta, and a five-week sparkline, sorted worst first in the metric's bad
  direction. Items compares to the same point in each previous week.

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

- **Unit (pytest, no database):** `timewin` presets, SAST day and week boundaries, bucket
  sizes; `rates` sums, low-volume flags per bucket size, summary statistics, doughnut
  partition; `availability.outages` (no gaps, one gap, open gap, gap exactly at threshold)
  and `transitions`; `severity` ordering and every skip rule; `trends` week-over-week with
  fewer than 4 previous weeks and with zero medians; `thresholds` lookup order.
- **API:** `TestClient` with `db.query` replaced by a fake returning canned rows; response
  shapes, 400/404 validation, stale flag on builder failure, 503 on cold failure, `/health`.
- **Snapshots:** row shaping, pruning parameters, scheduler tick tolerates failures.
- **Role files:** Dockerfile has the ODBC install and non-root user; compose template renders
  with defaults; vendored ECharts present and pinned; no `GETDATE()` in `queries/`.
- **CI:** `python -m pytest roles/s1_monitor/tests` added to `ci.yml`.
- **Manual acceptance on the workstation** against production over Tailscale: PEPKOR JBH
  DIM1 at 90d matches the shape of the December 2024 report's Figure 5 style; DCB DUR's warn
  line sits at 55.8%, not 90%; MADIBANA PE at 7d shows the weekend outage as a red band in
  the heatmap and in the outages table; comparison of PEPKOR JBH DIM1, DIM3, DIM4 overlays
  cleanly; a downloaded good-read PNG carries the header and the expected filename.

## Local development

```
cd roles/s1_monitor/files/dev
cp .env.example .env        # DB_HOST=100.102.46.89 DB_USER=... DB_PASS=...
docker compose -f docker-compose.dev.yml up --build
# http://localhost:8090
```

`.env` is added to `.gitignore`. The dev compose bind-mounts `../app/static` so page edits
show on refresh without a rebuild. The snapshot task is off in dev (`SNAPSHOT_ENABLED=false`).
