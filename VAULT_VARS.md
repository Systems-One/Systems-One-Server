# Vault Variables Reference

All secrets are stored in `group_vars/vault.yml` (Ansible Vault encrypted).
To edit: `ansible-vault edit group_vars/vault.yml`

## Required Variables

| Variable | Description |
|---|---|
| `vault_mqtt_username` | Mosquitto broker username (shared by all MQTT clients/devices) |
| `vault_mqtt_password` | Mosquitto broker password |
| `vault_mssql_sa_password` | MSSQL SA password |
| `vault_cloudflare_tunnel_token` | Cloudflare tunnel token |
| `vault_s1_dash_session_secret` | s1_dash session cookie HMAC key: random, 48+ characters |
| `vault_s1_dash_ghcr_token` | GitHub PAT with `read:packages`, used to pull the private `ghcr.io/systems-one/s1-dash` image |

## s1_dash logins

The names below are historical: they began as Grafana passwords, and Grafana is retired.
They are now the s1_dash login passwords, read by `s1_dash_users` in
`host_vars/sysone.yml`. **Do not rename them.** The role renders them in plaintext into
`/opt/s1-dash/users.json` (0600, uid 1001); the app bcrypt-hashes them in memory at startup.

| Variable | Description |
|---|---|
| `vault_grafana_jonathan_password` | s1_dash `jonathan` login password |
| `vault_grafana_avi_password` | s1_dash `avi` login password |
| `vault_grafana_chris_password` | s1_dash `chris` login password |
| `vault_grafana_pkluser_password` | s1_dash `pkluser` login password (PKL User Group; PEPKOR customer scope) |
| `vault_grafana_cust_bex_password` | s1_dash `cust_bex` login password (BEX customer login) |
| `vault_grafana_cust_dcb_password` | s1_dash `cust_dcb` login password (DCB customer login) |
| `vault_grafana_cust_madibana_password` | s1_dash `cust_madibana` login password (MADIBANA customer login) |
| `vault_grafana_cust_pep_password` | s1_dash `cust_pep` login password (PEP customer login) |
| `vault_grafana_cust_pep_africa_password` | s1_dash `cust_pep_africa` login password (PEP AFRICA customer login) |
| `vault_grafana_cust_snowsoft_password` | s1_dash `cust_snowsoft` login password (SNOWSOFT customer login) |

Note: a `cust_pepkor` Grafana account existed on the old server but was never vault-backed
and was not carried into s1_dash (owner decision, 2026-11-23; `pkluser` is the PEPKOR login).
See the 2026-08-11 vault rotation for context.

## No longer used

Grafana was retired when s1_dash took over `dash.sysone.co.za`. Nothing in the repo
references these any more, so they are safe to delete from the vault later (keep them until
the Grafana volume and `/opt/grafana` are deleted if you might roll back):

| Variable | Was |
|---|---|
| `vault_grafana_admin_password` | Grafana `admin` user password |
| `vault_grafana_git_sync_token` | GitHub PAT for Grafana Git Sync (repo: Jwagener1/grafana) |

## s1_reporter

| Variable | Description |
|---|---|
| `vault_s1_reporter_teams_webhook_url` | Power Automate Workflow webhook URL that posts Adaptive Cards into the Systems-One → Reporting Teams channel |

The legacy `vault_s1_reporter_smtp_user`/`_smtp_pass`/`_report_to` vars have
been fully removed — no code references them and they're gone from vault.yml
as of the 2026-08-11 vault rotation.

## Vault Recovery (2026-08-11)

The vault password was lost. All secrets above were recovered from the live
server's running containers (MSSQL, Cloudflare tunnel, existing Grafana
users) or rotated to new values (Grafana user/customer passwords, git-sync
token) and re-encrypted under a new vault password. If you need the current
vault password, ask Jonathan — it is not stored in this repo (only
`.vault_pass`, gitignored, holds it on each machine that needs to run
Ansible non-interactively).

`vault_mqtt_username`/`vault_mqtt_password` were missed in that recovery —
the `mqtt` role's variable validation never ran against the new vault until
2026-08-12 (nothing had touched the role in between), which is when the gap
surfaced. Added then with the live broker's actual credentials.
