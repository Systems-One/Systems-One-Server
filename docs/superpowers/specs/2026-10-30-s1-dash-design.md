# s1_dash: customer and operations dashboard replacing Grafana — Design

**Date:** 2026-10-30
**Target:** new GitHub repository `Systems-One/Systems-One-Dash` (the application) plus a thin
deploy role `roles/s1_dash/` in this repository.
**Related:** `2026-09-09-s1-monitor-design.md` (fault-diagnosis site at www.sysone.co.za, which
stays as it is), `2026-09-09-s1-reporter-overhaul-design.md` (threshold and liveness rules),
`2026-09-09-s1-baselines-role-design.md` (`dbo.alert_thresholds`).

## Context

Grafana 12.3.1 runs on `s1_server` behind `dash.sysone.co.za` (Cloudflare ingress rule 2 to
`localhost:3000`). It serves 19 dashboards synced from the `Jwagener1/grafana` repo:

| Folder | Dashboards | What they show |
|---|---|---|
| Admin | admin_panel | Day, month and year item totals and good read %, online count, apps not running, device table, good read by machine today, hourly items today against the monthly hourly average |
| Admin | Customer Summary | Per-customer table for a chosen period (devices, online, items, good read %, no read %), bars by customer, 7-day good read per machine, all-machines table |
| Admin | Machine Detail | One device: status, OS, C: %, items and good read today, app, memory, temperature, uptime, four rate gauges, items and good read series, drive table, sent against not sent |
| Admin | MQTT Broker Health | Latest `broker.broker_stats` row as tiles plus series of clients, messages, load, bytes, subscriptions |
| Admin | Parameter Explorer | Several devices overlaid on one time axis, raw 5-minute rows, one chart per metric (items, good read %, no read %, out of spec %, multiple items %, no weight %, sent against not sent), free time range |
| Per customer (7) | `<customer>_overview`, `Device_Drill_Down` | The admin panels again, with the customer name hard-coded in the variable query |

Who uses it (Grafana user table, 2026-10-30): `jonathan` and `pkluser` (PEPKOR) the same
morning; `avi`, `cust_madibana`, `cust_snowsoft` about two months ago; `chris` five months;
`cust_bex`, `cust_dcb`, `cust_pep`, `cust_pep_africa`, `cust_pepkor` never. All accounts are
Viewers in one org, so a logged-in customer can open any folder. Grafana is the only surface
that gives a customer a login; `s1_monitor` has none by design.

Profiling the production database on 2026-10-30 (19 devices, 7 customers, 954,059 rows in
`dbo.device_statistics`, 246,909 rows in `broker.broker_stats`, 91,979 rows in
`dbo.device_health_history` since 2026-09-09) established the facts in **Data semantics**
below. They drive which metrics each customer gets and which insights are worth building.

Decisions taken with the product owner on 2026-10-30:

- Build a complete new service in its own repository. Leave Grafana and `s1_monitor` untouched.
- No Cloudflare route until the owner is happy; then `dash.sysone.co.za` is pointed at it.
  Grafana retirement is separate, later work.
- Everything Grafana shows must be in the new dashboard, plus the extra metrics and insights
  the data supports.

## Goals

1. A customer logs in and sees only their own devices, with every figure Grafana gave them and
   nothing they have to configure.
2. An operator logs in and sees the whole fleet, the broker and the ingest pipeline.
3. Any device, any metric, any time range, overlaid across devices (Parameter Explorer parity).
4. Insights that Grafana could not compute: expected-activity anomalies, storage forecasts,
   upload reliability, capability mismatches, OS end-of-support, reboot and availability
   history, drift against the 60-day baseline.
5. Comfortable on a phone: readable tables, charts that fit, tappable controls, never a blank
   page.
6. One definition of today, of a rate, of low volume and of offline, identical to the reporter
   and `s1_monitor`.
7. Deployable by Ansible like every other service, with the image built by the new repo's CI.

## Non-goals

- Editing `customer_config`, `alert_thresholds`, device flags or users from the UI (v1).
- Alerting or notifications. Teams and WhatsApp stay with `s1_reporter`.
- Replacing `s1_monitor` or changing its route.
- Single sign-on, Cloudflare Access, self-service password reset.
- PDF export. TV or kiosk mode.
- Any write to telemetry tables. The service writes only its own `dbo.dash_*` tables.

Anti-goals (would make this a failure even if it works):

- A customer seeing another customer's data through any endpoint, including Explorer and CSV.
- A page that renders nothing while a query runs or fails.
- A rate, low-volume or threshold rule that disagrees with the reporter. (Offline timing is
  the one deliberate difference, see Liveness below.)

## Architecture

### Runtime

```
browser -- Cloudflare tunnel (later) -- 127.0.0.1:8094 -- s1_dash (uvicorn, one process)
                                                           |-- /login, /logout        session cookie
                                                           |-- /api/*                 JSON, scoped by session
                                                           |-- static pages + vendored ECharts
                                                           `-- asyncio job every 15 min: expected-activity
                                                               profiles and storage forecasts -> dbo.dash_*
```

One container, one replica. Reads `S1_Remote_Monitoring` over pyodbc with the `admin`
application login. Image built by GitHub Actions in `Systems-One-Dash` and pushed to
`ghcr.io/systems-one/s1-dash:<tag>`; Ansible pulls the tag it is told. Loopback bind only.
Until the Cloudflare route exists, testing is through `ssh -L 8094:127.0.0.1:8094 s1_server`.

### Stack (my call, matching the fleet's conventions)

Python 3.12, FastAPI, uvicorn, pyodbc with `msodbcsql18`. Front end is static HTML, CSS and
plain JavaScript with ECharts 5.5.1 vendored, no build toolchain and no framework, as
`PRODUCT.md` constrains and as `s1_monitor` proved. Passwords hashed with `bcrypt`. Sessions
are HMAC-signed cookies (`itsdangerous`), no server-side session store. Fonts: Inter from
Google Fonts with system-sans fallback, like the existing sites.

### Repository `Systems-One-Dash`

```
app/
  main.py              FastAPI app, routes, lifespan, static mount
  config.py            env vars with defaults
  db.py                pyodbc connect, query(sql, params) -> list[dict], timeouts
  cache.py             TTL cache keyed by (endpoint, params, scope); stale-on-error
  auth.py              users from DASH_USERS_JSON, bcrypt, session cookie, scope resolution, login rate limit
  scope.py             turns a session into a SQL predicate + params on dbo.devices.customer
  timewin.py           SAST helpers, period presets, bucket chooser for free ranges
  rates.py             bucket rate maths, low-volume flag, summary stats (ported from s1_monitor)
  availability.py      outages from row cadence; transitions from health history (ported)
  severity.py          needs-attention rules (ported, must match reporter)
  thresholds.py        lookup order device row -> customer row -> customer_config (ported)
  capabilities.py      declared vs observed capability per customer
  expected.py          weekday x hour expected-activity profile and anomaly test
  forecast.py          linear storage forecast per drive
  broker.py            counter deltas, restart detection, per-minute rates
  queries/             overview.py customers.py device.py explorer.py insights.py broker.py pipeline.py health.py
  jobs.py              15-minute job: refresh dbo.dash_expected_profile and dbo.dash_storage_forecast
  migrations/          001_dash_tables.sql (idempotent)
  static/
    login.html
    index.html         single page app, hash routes
    app.css            tokens, layout, mobile breakpoints
    api.js             fetch wrapper, 401 -> login, stale banner
    charts.js          ECharts theme, figure builders, PNG download, CSV export
    app.js             router, screens
    vendor/echarts.min.js
tests/                 pytest: pure modules, auth, API with fake query(), SQL hygiene
Dockerfile             python:3.12-slim-bookworm, msodbcsql18, non-root appuser, healthcheck /health
docker-compose.dev.yml local run against production over Tailscale, .env gitignored
.github/workflows/ci.yml   pytest on every push; build and push image to GHCR on main and on tags v*
README.md
docs/                  this design copied in, plus later plans
```

### Preview before the route exists

The owner's acceptance includes a phone, which cannot use an SSH tunnel. For the preview
period the role is deployed with `s1_dash_bind_address: 100.102.46.89` (the box's Tailscale
address) and `SESSION_SECURE=false`, so a phone or laptop on the tailnet opens
`http://100.102.46.89:8094`. At cutover both revert to `127.0.0.1` and `true` in the same
PR that asks for the Cloudflare change. Nothing else differs between preview and production.

### Deploy role `roles/s1_dash/` in Systems-One-Server

- `defaults/main.yml`: `s1_dash_image: ghcr.io/systems-one/s1-dash`, `s1_dash_tag: latest`,
  `s1_dash_port: 8094`, `s1_dash_bind_address: 127.0.0.1`, `s1_dash_dir: /opt/s1-dash`, DB
  vars from `mssql_rm_admin_login` and `mssql_rm_admin_password`, all tuning vars below,
  `s1_dash_users: []`.
- `tasks/main.yml`: directory, `docker login ghcr.io` when `s1_dash_ghcr_token` is set
  (private repo), render `users.json` (0600) and compose, `docker compose pull && up -d`,
  no `--build`.
- `templates/docker-compose.s1_dash.yml.j2`, `templates/users.json.j2`.
- `host_vars/sysone.yml`: `s1_dash_users` mirroring the Grafana accounts that are still used,
  passwords from vault (`vault_s1_dash_<login>_password`), `s1_dash_session_secret` from vault.
- `webservers.yml`: add `role: s1_dash` with `tags: [s1_dash]`.
- `VAULT_VARS.md` and `README.md` updated (services, ports, diagram).
- `roles/s1_dash/tests/test_role_files.py`: compose template renders, users template renders
  with an empty list and with two users, no plaintext password in the compose file, preview
  and production bind values both render.

### Configuration

| Env var | Default | Purpose |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` | `mssql`, `1433`, `S1_Remote_Monitoring`, `admin`, | database |
| `DASH_USERS_FILE` | `/run/secrets/users.json` | users list, see Auth |
| `SESSION_SECRET` | required | HMAC key for the session cookie |
| `SESSION_DAYS` | `30` | cookie lifetime (Grafana's was 30 days) |
| `SESSION_SECURE` | `true` | `Secure` flag on the cookie; `false` only for a plain-HTTP preview bind |
| `TRUST_PROXY_IP` | `true` | take the client IP from `CF-Connecting-IP` (every request arrives from 127.0.0.1 through cloudflared) |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_MINUTES` | `10`, `15` | per-IP and per-login throttle |
| `TZ_OFFSET_HOURS` | `2` | SAST |
| `MIN_ITEMS_DAY`, `MIN_ITEMS_HOUR`, `MIN_ITEMS_HALF_HOUR`, `MIN_ITEMS_PACKET` | `100`, `30`, `15`, `5` | low-volume thresholds per day, hour, 30-minute and 5-minute bucket |
| `OFFLINE_GAP_MINUTES`, `STALE_DAYS` | `11`, `14` | liveness, same as `s1_monitor` (the reporter alerts at 30, see Liveness) |
| `EXPECTED_WEEKS` | `8` | weeks of history behind the expected-activity profile |
| `QUIET_RATIO` | `0.2` | actual below this share of expected flags "quiet when usually busy" |
| `FORECAST_DAYS` | `30` | history window for the storage fit |
| `FORECAST_HORIZON_DAYS` | `60` | flag drives that reach the bad limit inside this horizon |
| `JOB_INTERVAL_MINUTES` | `15` | profile and forecast refresh |
| `CACHE_TTL_LIVE_SECONDS`, `CACHE_TTL_HISTORY_SECONDS` | `30`, `300` | cache |
| `QUERY_TIMEOUT_SECONDS` | `20` | every query |
| `EXPLORER_MAX_POINTS` | `20000` | cap on points returned per Explorer request |

## Auth and tenancy

Users come from `users.json`, rendered by Ansible from vault:

```json
[
  {"login": "jonathan", "password": "...", "role": "admin"},
  {"login": "avi",      "password": "...", "role": "viewer"},
  {"login": "pkluser",  "password": "...", "role": "viewer", "customers": ["PEPKOR"]},
  {"login": "cust_madibana", "password": "...", "role": "viewer", "customers": ["MADIBANA"]}
]
```

Three shapes: `admin` sees every customer and the admin screens; `viewer` without a
`customers` list sees every customer but no admin screens (internal staff such as `avi` and
`chris` today); `viewer` with a list sees those customers only. Customer strings are exact
`dbo.devices.customer` values: `BEX`, `DCB`, `MADIBANA`, `PEP`, `PEP AFRICA`, `PEPKOR`,
`SNOWSOFT`. The default `s1_dash_users` in `host_vars` carries over every current Grafana
login with the same password variable (`vault_grafana_<login>_password`) so nobody has to be
told a new password; the owner trims the list.

At startup passwords are bcrypt-hashed in memory; the file is never served. `/login` is a
plain HTML form (works without JavaScript), POST sets an `HttpOnly; Secure; SameSite=Lax`
cookie carrying `login`, `role`, `customers`, `issued_at`, signed with `SESSION_SECRET`.
`/logout` clears it. Failed logins are throttled per client IP and per login, where the
client IP is `CF-Connecting-IP` when `TRUST_PROXY_IP` is on (behind cloudflared every request
has a 127.0.0.1 peer, so throttling the peer would lock out everyone at once). Every `/api/*` and
the `/` page require a valid cookie; otherwise 401 JSON for the API and a redirect to
`/login?next=` for pages.

Scope is applied in SQL, never in JavaScript: `scope.predicate(session)` returns
`("d.customer IN (?, ?)", params)` for viewers and `("1=1", [])` for admins, and every query
that touches a device table joins `dbo.devices d` and includes it. A viewer asking for a
`device_id` outside their customers gets 404, the same as an unknown id. Admin-only screens
(Broker, Pipeline) return 403 to viewers. Customer names in the UI (filters, pickers) come
from the scoped `/api/meta`.

`dbo.customer_login_map` (4 rows) is not used; the users file is the single source. Which
Grafana accounts are carried over, and their passwords, is the owner's decision at deploy
time, see Open points.

## Data semantics (measured 2026-10-30, to be encoded in code and tests)

- `dbo.device_statistics` has one row per device every 5 minutes with per-interval counts
  (not cumulative). `total_items = good_read + no_read` exactly. `data_sent + not_sent =
  total_items` and `image_sent + image_not_sent = total_items` hold on every row for every
  customer.
- Images are only uploaded by BEX and DCB (`image_sent > 0`). For every other customer
  `image_not_sent = total_items`, so image failure is only a metric where `image_sent` has
  ever been non-zero for that customer. DCB had 54,400 images not sent out of 311,298 items in
  90 days; that is a real customer-facing number Grafana never showed.
- `hand_scanned` is populated for BEX, DCB and MADIBANA although `customer_config` says
  `has_hand_scan = 0` for BEX and DCB. `no_weight` is populated for DCB (863) and PEP (166)
  although `has_weight = 0` for both. `complete` is populated for BEX, DCB, MADIBANA and
  SNOWSOFT only. `item_out_of_spec` and `more_than_1_item` are populated for PEPKOR and PEP
  only. The dashboard therefore has **observed capabilities** (any non-zero in the last 90
  days) next to the **declared** ones, shows metrics when either says so, and lists the
  mismatch on the Insights screen.
- PEPKOR reports `no_weight` equal to `total_items` (no scale fitted). `no_weight_pct` is
  hidden for a customer whose 90-day `no_weight` equals its `total_items`.
- Every timestamp is UTC. Site time is SAST, UTC+2, no DST. SQL computes
  `local_ts = DATEADD(HOUR, ?, ts_datetime)` once in a subquery with the offset bound as a
  parameter; outer queries group on `local_ts`.
- Operating hours differ per customer: MADIBANA is weekday daytime only; BEX and DCB run
  evenings and overnight; SNOWSOFT is flat around the clock; PEPKOR is daytime-heavy with
  overnight volume. A single "working hours" assumption is wrong, hence the per-device
  weekday x hour profile.
- Volumes differ by four orders of magnitude (PEPKOR JBH DIM4 450,804 items in 90 days,
  PEPKOR JBH DIM2 781). Percentages below `MIN_ITEMS_*` are noise and are drawn hollow and
  excluded from averages.
- Latest-value tables (`device_status`, `device_application_status`, `device_os_metrics`,
  `device_os_status`, `device_storage_status`, `device_uptime_status`) hold one row per device
  (or per device and drive). History for them exists only in `dbo.device_health_history`
  (15-minute snapshots from 2026-09-09, written by `s1_monitor`), whose `drives_json` carries
  every drive.
- `temp_celsius` is constant per device (27.9 or 29.9 on every snapshot). It is shown as a
  value, never charted or alerted.
- `broker.broker_stats` has one row per minute since 2026-05-11. `msgs_received`,
  `msgs_sent`, `bytes_*` are cumulative counters that reset when the broker restarts
  (`uptime_seconds` drops); 51 resets so far. Rates are deltas between consecutive rows
  divided by elapsed seconds, with negative deltas treated as a restart. `clients_connected`
  fell to 1 on 2026-10-15 and 2026-10-29, both restarts.
- `ingest.pipeline_state.last_db_write_utc` is the pipeline heartbeat.
  `ingest.telemetry_deadletter` holds failed payloads (0 rows today).
- Known fleet conditions useful for acceptance: PEP AFRICA DUR STATIC1 (id 3014) has sent
  nothing since 2026-07-08 (stale); PEPKOR JBH DIM2 (id 6) has `reporting_enabled = 0`;
  DCB CPT DIM1 (id 3015) E: drive is at 98%; DCB DUR DIM1 (id 4015) C: grew from 71.7% to
  84.8% in 51 days; MADIBANA PE DIM1 (id 3013) had a 2,925-minute gap ending 2026-10-26 and
  999 snapshots with the application stopped; 11 of 19 devices run Windows 10 (build 19044 or
  19045), 8 run Windows 11.

## Data layer

### Periods and buckets

Period presets, all in SAST: Today, Yesterday, This week (Monday to now), Last 7 days, This
month, Last 30 days, Last 90 days, This year, and Custom (from and to, date or datetime).
Bucket is chosen from the span: up to 48 hours 5-minute rows as stored; up to 14 days 30
minutes; up to 60 days 1 hour; beyond that 1 day. The Explorer shows the chosen bucket and
lets the user force a coarser one. A bucket with no rows is `nodata: true`, distinct from
rows with zero items.

### Rates, summaries, thresholds, liveness

Ported from `s1_monitor` unchanged in semantics: a rate is `100 x SUM(part) / SUM(total)`
over rows in the bucket, never an average of row percentages; percentage axes fixed 0 to
100; low-volume buckets hollow and excluded from averages; thresholds looked up device row,
customer row, `customer_config`; state `stale`, `never`, `offline`, `online` from row cadence;
outages from gaps over `OFFLINE_GAP_MINUTES`.

**Liveness timing (my call).** The reporter classifies offline at 30 minutes
(`s1_reporter_offline_threshold_minutes`) so that Teams alerts are not noisy; `s1_monitor`
shows offline at 11 minutes (two missed 5-minute packets) so that an operator looking at a
screen sees it early. The dashboard follows `s1_monitor` (11). The Device header states
"offline since HH:MM, Teams alert after 30 min" so the two never look contradictory. Stale
(14 days) and every rate rule are identical across all three.

### Expected-activity profile (`expected.py`, job)

For each device and each (weekday, hour) in SAST: median of hourly item counts over the last
`EXPECTED_WEEKS` weeks, over hours that had at least one row (so outages do not drag the
median down). Stored in `dbo.dash_expected_profile (device_id, dow, hour, expected_items,
samples, computed_utc)`. Used for:

- the "today against expected" overlay on Overview and Device (replaces Grafana's "today
  against monthly hourly average", which ignored weekday);
- the **quiet when usually busy** insight: for the last two completed SAST hours, if
  `expected_items >= MIN_ITEMS_HOUR` for both and actual items `< QUIET_RATIO x expected`
  for both, flag the device with expected and actual. Devices that are offline are flagged by
  the liveness rule instead, so this catches "online but not scanning".

### Storage forecast (`forecast.py`, job)

For each device and drive, least-squares line through `usage_percent` over the last
`FORECAST_DAYS` days of `device_health_history` (C: from `c_usage_percent`, others from
`drives_json`). Stored in `dbo.dash_storage_forecast (device_id, drive, usage_now,
slope_pct_per_day, days_to_warn, days_to_bad, samples, computed_utc)`. A drive with fewer than
7 days of samples has null days. A drive already past `storage_bad_pct` reports 0 days.

### Broker (`broker.py`)

From consecutive rows: `msgs_in_per_s`, `msgs_out_per_s`, `bytes_in_per_s`,
`bytes_out_per_s`; `restart: true` on a row whose `uptime_seconds` is below the previous
row's. Restarts are listed with time and the uptime achieved. Series are thinned to at most
2,000 points per request.

### Capabilities (`capabilities.py`)

`declared` from `customer_config`; `observed` as any non-zero in 90 days for `no_dimension`,
`no_weight`, `hand_scanned`, `complete`, `item_out_of_spec`, `more_than_1_item`,
`image_sent`. `effective = declared OR observed`, with the special rule for `no_weight` above.
Mismatches (declared without observed, observed without declared) are reported on Insights.

### Caching and failure

`cache.get_or_build(key, ttl, builder)` keyed by endpoint, sorted params and scope. Live
TTL for today-ish periods, history TTL otherwise. On failure with a cached entry return it
with `stale: true` and `stale_since`; without one return 503 `{"detail": "<exception
class>"}`. The message never reaches the browser; it is logged with a traceback. `api.js`
shows the stale banner and, on 503, an error panel inside the affected figure while the rest
of the page keeps rendering. The page shell, nav and last good data are always on screen
while a request is in flight.

### Own tables (`migrations/001_dash_tables.sql`, idempotent at startup)

`dbo.dash_expected_profile`, `dbo.dash_storage_forecast` as above, plus
`dbo.dash_login_audit (login, ok, ip, at_utc)` kept 90 days. No other writes.

## API

All `GET` under `/api`, JSON, UTC ISO timestamps, scoped by session. `period` is a preset
name or `custom` with `from` and `to`. `device_id` is `dbo.devices.id`.

| Endpoint | Params | Returns |
|---|---|---|
| `/health` | none, unauthenticated | `{status, db_ok, last_query_utc, job_last_utc, job_ok}` |
| `/api/meta` | | `user {login, role}`, scoped `customers[]` with declared, observed and effective capabilities and limits, scoped `devices[]`, thresholds per device per metric with `source`, `tz_offset_hours`, low-volume thresholds, `history_since` |
| `/api/overview` | `customer?` | KPI tiles for today, this month, this year (items, good read %), online, offline, stale, apps not running, attention count; `devices[]` (state, last seen, items today, good read today, no read %, no dim %, not sent %, C: %, app, 24 hourly items); `by_machine_today[]`; `today_vs_expected[]` 24 hours actual and expected |
| `/api/customers` | `period` | per customer: devices, online, items, good read %, no read %, no dim %, hand scan %, not sent %, image fail % (where effective), low-volume flag; `by_customer[]` for the bars; `machines_7d[]` good read per machine |
| `/api/device/{id}` | | identity, state, last seen, app and `stopped_since`, uptime, OS, memory, CPU, temperature value, drives with forecast, effective capabilities, thresholds |
| `/api/device/{id}/series` | `period`, `bucket?` | buckets with every count column, rates, `low_volume`, `nodata`; `summary` max/min/avg; `totals`; `outages[]`; `hourly_today_vs_expected[]` |
| `/api/device/{id}/health` | `period` | thinned history rows (cpu, mem, every drive %, app, status, uptime) and `events[]` (reboot, app stopped, app started, offline, online) |
| `/api/explorer` | `devices` (csv ids), `metrics` (csv), `from`, `to`, `bucket?` | one series per device per metric, the bucket used, `truncated: true` if the point cap was hit |
| `/api/explorer.csv` | same | CSV of the same data |
| `/api/insights` | `customer?` | cards: `attention[]` (severity rules), `quiet[]`, `storage[]`, `upload[]` (not sent % and image fail % over 7 days above 1%), `capability_mismatch[]`, `os[]` (version, count, end-of-support flag), `reboots[]` (count in 30 days), `availability[]` (percentage of expected 5-minute rows present over 30 days, worst first), `drift[]` (this week's good read against `baseline_mean`, worst first) |
| `/api/broker` | `period`, admin | latest tiles, series with per-second rates, `restarts[]` |
| `/api/pipeline` | admin | last DB write age, deadletter count and last 20, rows written per hour over 24 hours, per-device largest gap over 7 days |

Validation: unknown period, metric or bucket 400; unknown or out-of-scope device 404;
viewer on admin endpoint 403; no session 401.

## Screens

Shared chrome: top bar with the customer's name (viewer) or "Systems One" (admin), nav
(Overview, Customers [admin], Device, Explorer, Insights, Broker [admin], Pipeline [admin]),
customer filter (admin), period picker where the screen takes one, "Data as of HH:MM SAST",
a bell with the attention count, the user's login and Logout. Dark palette and tokens from
the existing sites; semantic colours reserved for state. Pages poll every 60 seconds while
visible. Hash routes keep deep links and back and forward working.

Mobile (the owner's stated need): below 640 px the nav becomes a bottom bar with icons and
labels, tiles stack two per row, tables become stacked cards with the key figure large,
charts take full width with a minimum height of 220 px and horizontal time axes thinned,
controls are at least 40 px tall, and pickers open as full-width sheets. Nothing depends on
hover.

### Login (`/login`)

Login and password, "Keep me signed in" (30 days, otherwise the browser session), error text
on failure, throttle message after too many attempts.

### Overview (`#overview`)

Replaces admin_panel and the customer overviews.

1. Tiles: Items today, Good read today, Items this month, Good read this month, Items this
   year, Good read this year, Online / Offline / Stale, Apps not running, Attention.
2. Today against expected: 24 bars of actual items with the expected-profile line, fleet or
   filtered customer.
3. Good read by machine today: horizontal bars, device's own warn and bad as marks, hollow
   when low volume.
4. Device table grouped by customer: state dot, device, last seen, items today, good read
   today, no read %, no dim % (effective), not sent %, C: %, app, 24-hour sparkline. Row tap
   opens the device.

### Customers (`#customers`, admin)

Replaces Customer Summary. Period picker. Table per customer with the columns in the API,
bars for good read and no read by customer, bars for volumes by customer, 7-day good read per
machine, and the all-machines table for the period.

### Device (`#device/<id>/<period>`)

Replaces Machine Detail and Device Drill Down.

1. Header: identity, state and last seen, app (with stopped since), uptime, OS version with
   friendly name and end-of-support flag, CPU, memory, temperature value, drives with usage
   bar and "about N days to 90%" from the forecast.
2. Device picker (scoped), period picker, Compare with picker (other scoped devices as extra
   series).
3. Summary table: max, min, average of items per bucket, good read %, items per hour; totals;
   outages count and longest; limits with source.
4. Items per bucket; Good read % with average, warn and bad lines; row of applicable rate
   panels (no read, no dim, out of spec, multiple items, no weight, hand scan, not sent, image
   fail), each 0 to 100 with its limit where one exists.
5. Sent against not sent, and images sent against not sent where effective, stacked bars.
6. Today against expected for this device.
7. Throughput heatmap (dates by hours, value in every cell) for periods of 7 days or more.
8. Outages table; host history (CPU, memory, each drive, app and reboot markers); events list.

Every figure downloads as a stamped 2x PNG and its data as CSV.

### Explorer (`#explorer`)

Replaces Parameter Explorer. Device multi-select (scoped, grouped by customer), metric
multi-select (items, good read %, no read %, no dim %, out of spec %, multiple items %, no
weight %, hand scan %, not sent %, image fail %, sent and not sent counts), range picker with
presets and custom from and to, bucket override. One chart per metric, one line per device,
shared time axis with linked zoom and tooltip. A note states the bucket and whether points
were truncated. CSV export of what is shown.

### Insights (`#insights`)

Cards, each with a count in its header, the worst items first, and a tap-through to the
device: Needs attention, Quiet when usually busy, Storage running out, Upload failures,
Availability (30 days), Drift against baseline, Reboots (30 days), Operating system (version
counts with Windows 10 marked end of support since 2025-10-14), Capability mismatches
(admin only). Viewers see their own devices only.

### Broker (`#broker`, admin)

Replaces MQTT Broker Health. Tiles from the latest row (connected, total, inactive,
subscriptions, stored, uptime, version, messages in and out per second). Series: clients,
messages per second, bytes per second, subscriptions and stored, with restart markers.
Restarts table.

### Pipeline (`#pipeline`, admin)

Last DB write age (amber over 10 minutes, red over 30), deadletter count and recent rows,
rows written per hour over 24 hours, largest gap per device over 7 days.

## Testing

- **Unit, no database:** `timewin` presets, SAST boundaries, bucket chooser; `rates`;
  `availability`; `severity` (every skip rule, ordering); `thresholds` lookup order;
  `capabilities` (declared, observed, effective, the PEPKOR no-weight rule, mismatch list);
  `expected` (median over sampled hours only, quiet rule both hours, one hour, expected too
  small); `forecast` (flat, rising, falling, under 7 days, already past bad); `broker`
  (deltas, restart on counter drop, thinning); `scope` (admin, one customer, many, device out
  of scope); `auth` (hash and verify, cookie sign and expire, throttle).
- **API:** `TestClient` with `db.query` faked. Every endpoint: shape, 400 and 404, 401 without
  a cookie, 403 for a viewer on admin endpoints, a viewer cannot see another customer's device
  through `/api/device`, `/api/explorer` or `/api/explorer.csv`; stale flag; 503 on cold
  failure; `/health`.
- **SQL hygiene:** no `GETDATE()` in `queries/`; every query in `queries/` that selects from a
  device table contains the scope placeholder.
- **Role files (Systems-One-Server):** compose and users templates render; no plaintext
  password in compose; `webservers.yml` carries the role with its tag.
- **CI:** `Systems-One-Dash` runs pytest on every push, builds the image on `main` and on
  `v*` tags and pushes to GHCR. `Systems-One-Server` CI runs the role-file tests.
- **Manual acceptance on the box over an SSH tunnel:** log in as a PEPKOR viewer and confirm
  only PEPKOR devices appear anywhere, including Explorer and its CSV; log in as admin and
  confirm the Broker page shows the 2026-10-15 and 2026-10-29 restarts; Insights shows DCB
  CPT DIM1 E: at 98% and DCB DUR DIM1 C: with a forecast under 60 days; PEP AFRICA DUR shows
  as stale; MADIBANA PE shows the 2026-10-26 outage; Windows 10 count is 11; a phone-width
  window shows the bottom nav and card tables with no horizontal page scroll; pulling the
  database connection during a poll leaves the page visible with the stale banner.

## Rollout

0. Owner decides repo visibility. Public: no tokens anywhere, the box pulls from GHCR
   anonymously. Private: owner issues a GitHub PAT with `read:packages`, stored as
   `vault_s1_dash_ghcr_token`, and the role logs in before pulling. The builder creates the
   repository under `Systems-One` with the `gh` CLI (the account is an org member).
1. Create `Systems-One/Systems-One-Dash`, scaffold, CI green, first image pushed.
2. Add `roles/s1_dash` and vault variables here; deploy with `--tags s1_dash` on
   `127.0.0.1:8094`. Grafana and `s1_monitor` untouched.
3. Owner reviews over the tunnel and iterates.
4. When happy: Cloudflare Zero Trust public hostname `dash.sysone.co.za` moves from
   `localhost:3000` to `localhost:8094`. Grafana keeps running on 3000 without a route until
   the owner decides to retire it (separate work: role, vault vars, README, dashboards repo).

## Local development

```
cp .env.example .env       # DB_HOST=100.102.46.89 DB_USER=... DB_PASS=..., SESSION_SECRET=dev
docker compose -f docker-compose.dev.yml up --build   # http://localhost:8094
```

Static files are bind-mounted so page edits show on refresh. Jobs are on in dev but write
only `dbo.dash_*`. A `users.dev.json` with one admin and one PEPKOR viewer is committed for
development only.

## Left to the builder

ECharts option details, exact CSS, SQL shapes within the rules above, cache keys, the
friendly OS-version mapping table, icon set for the bottom nav, PNG stamp layout, how the
device picker is laid out on a phone.

## Grafana parity checklist

Every panel in the `Jwagener1/grafana` repo (clone of 2026-10-30) and where it lands. The
builder ticks these off; the customer folders are seven copies of the same two dashboards.

| Grafana panel | New home |
|---|---|
| admin_panel: Year / Month / Day total parcels and good read % (6 stats) | Overview tiles |
| admin_panel: Apps not running, Total devices, Online now | Overview tiles |
| admin_panel: Device Overview table | Overview device table |
| admin_panel: Good Read % by Machine (Today) | Overview bars |
| admin_panel: Items Processed, Today vs Monthly Avg (Hourly) | Overview today against expected (weekday-matched) |
| Customer Summary: fleet stat strip, Total customers, Total machines, Online, Offline, Items today, Fleet good read, Not sent today | Customers tiles |
| Customer Summary: Customer Performance Summary table | Customers table |
| Customer Summary: Performance % by Customer, Item Volumes by Customer | Customers bars |
| Customer Summary: 7-Day Average Good Read % per Machine | Customers machines_7d |
| Customer Summary: All Machines table | Customers all-machines table |
| Machine Detail and Device_Drill_Down: Status, OS, C: used, Items today, Good read today, App, Customer/Location, Memory, Temperature, Uptime, CPU | Device header |
| Machine Detail and Device_Drill_Down: Out of Spec %, Multiple Items %, No Weight %, No Dimensions % gauges | Device rate panels (effective capabilities) |
| Machine Detail and Device_Drill_Down: Items Processed Over Time, Good Read % Over Time | Device items and good read figures |
| Machine Detail and Device_Drill_Down: Drive Storage table | Device header drives with forecast |
| Machine Detail and Device_Drill_Down: Data Transmission Sent vs Not Sent (and Images Sent / Not Sent) | Device sent against not sent, images where effective |
| Device_Drill_Down: Hourly Items, Today vs Daily Average | Device today against expected |
| `<customer>_overview`: period stat, Performance Overview bars, Device Status table, Good Read % Overview bars, Raw Metrics table | Overview scoped to the viewer's customer (tiles, bars, device table); Raw Metrics counts are the Customers table columns plus CSV on the Device figures |
| MQTT Broker Health: 9 stats, Client Connections, Messages Received / Sent, Message Load, Bytes In / Out, Subscriptions & Stored | Broker screen (rates derived from counters, restart markers added) |
| Parameter Explorer: Total Items, Good Read %, No Read %, Out of Spec %, Multiple Items %, No Weight %, Data Sent vs Not Sent, multi-device overlay, free range | Explorer |
| Grafana time picker and auto-refresh | Period picker with Custom range; 60 s poll |
| Grafana Inspect, Data, Download CSV | CSV button on every figure |

## Owner decisions (2026-10-30)

- Repository `Systems-One/Systems-One-Dash` is **private**. The image on GHCR is therefore
  private too; the owner issues a GitHub token with `read:packages` and stores it as
  `vault_s1_dash_ghcr_token` before the first deploy. CI pushes with the workflow's own
  `GITHUB_TOKEN`.
- The owner's phone is on the tailnet, so the Tailscale preview bind stands. The builder also
  renders the pages in Chrome on the workstation, running the app locally against the
  production database over Tailscale.
- **All twelve Grafana logins carry over** with their existing vault password variables:
  `jonathan` admin; `avi`, `chris` viewers of everything; `pkluser` viewer of `PEPKOR`;
  `cust_bex`, `cust_dcb`, `cust_madibana`, `cust_pep`, `cust_pep_africa`, `cust_pepkor`,
  `cust_snowsoft` viewers of their customer (`cust_pep_africa` maps to `PEP AFRICA`,
  `cust_pepkor` to `PEPKOR`). `cust_pepkor` has no vault variable today (it was unmanaged in
  Grafana); it gets `vault_s1_dash_cust_pepkor_password`.
