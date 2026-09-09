# s1_baselines: standalone alert-threshold recompute — Design

**Date:** 2026-09-09
**Target:** new role `roles/s1_baselines/`, small changes to `roles/s1_reporter/`

## Context

Per-device alert thresholds (`dbo.alert_thresholds`, columns `warn_value` and
`bad_value` per `customer + machine_name + location + metric`) are computed by
`compute_baselines.py`. Today that script lives inside the `s1_reporter` role, is baked
into the `s1-reporter:latest` image alongside the reporter, and is triggered by a block
in the reporter's `entrypoint.sh` loop every Sunday at 02:00.

Problems with that arrangement:

- Recomputing thresholds on demand (for example after a formula change such as
  `feat/warn-15pct-below-mean`) means `docker exec` into a long-running container whose
  image may or may not contain the new code.
- The script writes to the database unless `--dry-run` is passed. That is the wrong
  default for something operators will run by hand.
- It connects as `sa` because it inherits the reporter's credentials. Every other
  application on the host uses the least-privilege `admin` login.
- The reporter image carries matplotlib and numpy; the baseline script needs neither.

The `alert_thresholds` table is not created by any DDL in this repo. It exists on the
live server (30 rows, last computed 2026-09-06 with the pre-15% formula). This role takes
ownership of it: a `migrate` subcommand creates it when absent, using the live column set.

## Goals

1. One small Python image whose only job is computing and upserting thresholds.
2. Run it as a one-shot container: it starts, computes, writes (or not), exits.
3. One owner of the weekly schedule. The reporter stops running baselines.
4. Explicit, safe CLI: `dry-run` and `apply` are separate subcommands.
5. Least-privilege database login.

## Non-goals

- Posting results to Teams.
- Changing the `no_dim_pct` derivation or any statistics logic.
- A long-running scheduler container.

## Architecture

### New role `roles/s1_baselines/`

```
roles/s1_baselines/
  defaults/main.yml
  files/
    Dockerfile
    compute_baselines.py          # git mv from roles/s1_reporter/files/
    migrations/
      001_alert_thresholds.sql    # CREATE TABLE IF absent, live column set
  templates/
    docker-compose.s1_baselines.yml.j2
    run-baselines.sh.j2
  tasks/main.yml
  tests/
    test_baselines.py             # git mv from roles/s1_reporter/tests/
```

**Defaults** (`defaults/main.yml`):

| Variable | Default | Purpose |
|---|---|---|
| `s1_baselines_image` | `s1-baselines:latest` | Image tag built on the host |
| `s1_baselines_dir` | `/opt/s1-baselines` | Install directory |
| `s1_baselines_db_host` | `mssql` | Container name on `infra` |
| `s1_baselines_db_port` | `1433` | |
| `s1_baselines_db_name` | `{{ mssql_rm_database \| default('S1_Remote_Monitoring') }}` | |
| `s1_baselines_db_user` | `{{ mssql_rm_admin_login \| default('admin') }}` | Least-privilege login |
| `s1_baselines_db_pass` | `{{ mssql_rm_admin_password \| default('') }}` | |
| `s1_baselines_lookback_days` | `60` | Passed as `--lookback` |
| `s1_baselines_schedule_enabled` | `true` | Install the cron entry |
| `s1_baselines_schedule_hour` | `"2"` | Sunday 02:00, matches the old reporter slot |
| `s1_baselines_schedule_minute` | `"0"` | |
| `s1_baselines_log_path` | `/opt/s1-baselines/baselines.log` | Wrapper appends here |

**Dockerfile**: `python:3.12-slim`, installs `freetds-dev`, `gcc`, `g++` for the
`pymssql` build, `pip install pymssql`, copies `compute_baselines.py` and `migrations/` to
`/app`.
`ENTRYPOINT ["python3", "/app/compute_baselines.py"]` so compose `command:` and CLI
arguments pass straight through. No `CMD` default, so running with no arguments prints
usage and exits non-zero rather than silently writing.

**Compose** (`docker-compose.s1_baselines.yml.j2`): one service `baselines`, `build:
.`, `image: {{ s1_baselines_image }}`, environment `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASS`, joined to `{{ docker_shared_network }}` (external). No `ports`, no
`restart`, no `container_name` (compose `run --rm` generates one, so two manual runs never
collide). Log driver `json-file` with the same 10m / 3 rotation the other roles use.

**Wrapper** (`run-baselines.sh.j2`, installed to `{{ s1_baselines_dir }}/run-baselines.sh`,
mode 0755):

```bash
#!/bin/bash
# Usage: run-baselines.sh dry-run|apply [--lookback N]
set -o pipefail
cd {{ s1_baselines_dir }}
echo "[$(date '+%Y-%m-%d %H:%M:%S')] run-baselines $*" >> {{ s1_baselines_log_path }}
docker compose run --rm baselines "$@" 2>&1 | tee -a {{ s1_baselines_log_path }}
```

`pipefail` makes the script's exit code the container's exit code, not `tee`'s, so cron
and operators see failures.

Cron and humans use the same entry point, so a manual run is exactly what the schedule
does. The wrapper does not build; the Ansible role builds.

**Tasks** (`tasks/main.yml`), tagged `s1_baselines`:

1. Ensure `{{ s1_baselines_dir }}` exists.
2. Copy `Dockerfile` and `compute_baselines.py` into it.
3. Render the compose file and the wrapper script.
4. `docker compose build` in that directory (`changed_when` on the build output
   containing a new layer is unreliable, so this task is `changed_when: false` and always
   runs; it is fast when cached).
5. `docker compose run --rm baselines migrate` (`changed_when: false`).
6. Install (or remove, when `s1_baselines_schedule_enabled` is false) a root cron entry
   named `systems-one baselines recompute`: `{{ s1_baselines_dir }}/run-baselines.sh
   apply --lookback {{ s1_baselines_lookback_days }} >> {{ s1_baselines_log_path }} 2>&1`,
   weekday `0`, at the configured hour and minute. Use the same crontab-availability guard
   pattern as `roles/backup`.

The role is appended to `webservers.yml` after `s1_reporter`.

### Script changes (`compute_baselines.py`)

Minimal and behaviour-preserving apart from the CLI:

- CLI becomes subcommand based: `compute_baselines.py dry-run [--lookback N]`,
  `compute_baselines.py apply [--lookback N]` and `compute_baselines.py migrate`. The old
  `--dry-run` flag is removed. No subcommand prints usage and exits 2.
- `migrate` executes `migrations/*.sql` in name order, splitting on `GO` lines, each file
  idempotent (`IF OBJECT_ID(...) IS NULL`). The Ansible role runs it after the image build
  and before installing cron.
- Remove `ENV_PATH` / `report.env` fallback in `load_config()`. Missing env vars raise a
  clear `SystemExit` naming the variable.
- On `apply`, print one line per row that changes: `customer / machine / location /
  metric: warn OLD -> NEW, bad OLD -> NEW`. Rows whose values are unchanged are counted,
  not printed. The existing summary table stays.
- `derive_thresholds`, `compute_stats`, `percentile`, the SQL, the override skip and the
  upsert are untouched.

### Changes to `roles/s1_reporter/`

- `files/entrypoint.sh`: remove the `last_baseline_week` variable, the weekly block, and
  the "baselines every Sunday" text in the startup echo.
- `files/Dockerfile`: remove `COPY compute_baselines.py`.
- `tasks/main.yml`: remove the "Copy compute_baselines.py" task.
- `tests/test_baselines.py` moves to `roles/s1_baselines/tests/` with `BASELINES` path
  updated; tests for the new CLI parsing are added there.
- Nothing else in the reporter changes. It keeps reading `alert_thresholds` through
  `load_thresholds()` in `report.py`.

### CI

`.github/workflows/ci.yml` gains one step: `python -m unittest discover -s
roles/s1_baselines/tests`. The `s1_reporter` test step keeps running and no longer
covers baselines.

## Data flow

```
cron (Sun 02:00) or operator
  -> /opt/s1-baselines/run-baselines.sh apply|dry-run
    -> docker compose run --rm baselines <args>
      -> python3 /app/compute_baselines.py <args>
        -> reads dbo.devices + dbo.device_statistics (60 days, total_items >= 50)
        -> reads alert_thresholds where is_override = 1 (skip list)
        -> dry-run: print table, exit 0
        -> apply:   upsert alert_thresholds, print diff + table, exit 0
  -> output appended to /opt/s1-baselines/baselines.log
```

Consumers of `alert_thresholds` (reporter anomaly detection, `marketing_display`,
`scan_fleet_dashboard`) are unchanged.

## Error handling

- Database unreachable or bad credentials: `pymssql` raises, the script exits non-zero,
  the wrapper propagates the code, and cron mail / the log records it. No partial writes
  because the upsert loop commits once at the end.
- Missing env var: explicit `SystemExit` with the variable name.
- No qualifying rows: the script prints "Fetched 0 qualifying rows" and exits 0 with
  nothing written. That is the existing behaviour and is correct for a quiet fleet.
- Cron overlap with a manual run: two `compose run` containers can coexist; the second
  upsert wins. Acceptable, since both compute from the same data.

## Testing

- Unit tests (moved and extended): `derive_thresholds` cases as today, plus argument
  parsing (`dry-run` sets no-write, `apply` sets write, no subcommand exits 2, `--lookback`
  parsed), and the diff-line formatter given old/new rows.
- Role file tests in the same style as `roles/scan_fleet_dashboard/tests/test_role_files.py`:
  Dockerfile has the expected `ENTRYPOINT`, compose template has no `ports`/`restart`,
  reporter's `entrypoint.sh` no longer mentions baselines.
- Live verification, in order, on `sysone`:
  1. `ansible-playbook -i production webservers.yml --tags s1_baselines`
  2. `/opt/s1-baselines/run-baselines.sh dry-run` and review against the current table.
  3. `/opt/s1-baselines/run-baselines.sh apply`, confirm `last_computed` advanced and
     the MADIBANA DIM1 `good_read_pct` warn moved from 85.0 to roughly 77.5.
  4. `ansible-playbook -i production webservers.yml --tags s1_reporter` to rebuild the
     reporter without the Sunday job; confirm its startup line no longer mentions
     baselines.

## Rollout order and prerequisites

1. Merge `feat/warn-15pct-below-mean` to `master` first. This work branches from it.
2. Resolve the uncommitted `group_vars/vault.yml` change in the server checkout at
   `/home/s1/Systems-One-Server`; the Deploy workflow refuses to run over local changes.
   That change is not part of this work and needs a human decision.
3. Deploy `s1_baselines`, then redeploy `s1_reporter`, in the same session (see Testing).
   Between those two steps both schedulers exist; the next Sunday is the only collision
   window and it is harmless (same table, reporter's copy uses the older formula only if
   its image was not rebuilt).
