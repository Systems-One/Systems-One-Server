import json
import os
import re

import jinja2
import yaml

ROLE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO = os.path.abspath(os.path.join(ROLE, "..", ".."))


def read(*p):
    return open(os.path.join(ROLE, *p), encoding="utf-8").read()


def defaults():
    return yaml.safe_load(read("defaults", "main.yml"))


def render(template, **overrides):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    # Literal defaults only; defaults that reference group vars are supplied below.
    ctx = {
        k: v for k, v in defaults().items() if not (isinstance(v, str) and "{{" in v)
    }
    ctx.update(
        s1_dash_db_user="admin",
        s1_dash_db_pass="dbpw-placeholder",
        s1_dash_session_secret="x" * 48,
    )
    ctx.update(overrides)
    return env.from_string(read("templates", template)).render(**ctx)


def compose(**o):
    return yaml.safe_load(render("docker-compose.s1_dash.yml.j2", **o))


def test_compose_defaults():
    text = render("docker-compose.s1_dash.yml.j2")
    assert "ghcr.io/systems-one/s1-dash:latest" in text
    assert "/run/secrets/users.json:ro" in text
    assert "build:" not in text
    c = compose()
    svc = c["services"]["s1-dash"]
    assert svc["container_name"] == "s1_dash"
    assert svc["ports"] == ["127.0.0.1:8094:8000"]
    assert svc["volumes"] == ["/opt/s1-dash/users.json:/run/secrets/users.json:ro"]
    assert "infra" in c["networks"]


def test_compose_env_covers_spec_table():
    env = compose()["services"]["s1-dash"]["environment"]
    for key in (
        "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DASH_USERS_FILE",
        "SESSION_SECRET", "SESSION_DAYS", "SESSION_SECURE", "TRUST_PROXY_IP",
        "LOGIN_MAX_ATTEMPTS", "LOGIN_WINDOW_MINUTES", "TZ_OFFSET_HOURS",
        "MIN_ITEMS_DAY", "MIN_ITEMS_HOUR", "MIN_ITEMS_HALF_HOUR", "MIN_ITEMS_PACKET",
        "OFFLINE_GAP_MINUTES", "STALE_DAYS", "EXPECTED_WEEKS", "QUIET_RATIO",
        "FORECAST_DAYS", "FORECAST_HORIZON_DAYS", "JOB_INTERVAL_MINUTES",
        "CACHE_TTL_LIVE_SECONDS", "CACHE_TTL_HISTORY_SECONDS",
        "QUERY_TIMEOUT_SECONDS", "EXPLORER_MAX_POINTS",
    ):
        assert key in env, key
    assert env["DASH_USERS_FILE"] == "/run/secrets/users.json"
    assert env["SESSION_SECURE"] == "true"
    assert env["TRUST_PROXY_IP"] == "true"
    assert env["SESSION_DAYS"] == "30"
    assert env["QUIET_RATIO"] == "0.2"
    assert env["MIN_ITEMS_PACKET"] == "5"
    assert env["EXPLORER_MAX_POINTS"] == "20000"


def test_bind_preview_and_production_render():
    prod = compose()["services"]["s1-dash"]
    assert prod["ports"] == ["127.0.0.1:8094:8000"]
    assert prod["environment"]["SESSION_SECURE"] == "true"
    prev = compose(
        s1_dash_bind_address="100.102.46.89", s1_dash_session_secure=False
    )["services"]["s1-dash"]
    assert prev["ports"] == ["100.102.46.89:8094:8000"]
    assert prev["environment"]["SESSION_SECURE"] == "false"


def test_no_user_password_in_compose():
    users = [{"login": "a", "password": "hunter2-plain", "role": "admin"}]
    text = render("docker-compose.s1_dash.yml.j2", s1_dash_users=users)
    assert "hunter2-plain" not in text
    assert "s1_dash_users" not in read("templates", "docker-compose.s1_dash.yml.j2")


def test_users_template_empty_and_two_users():
    assert json.loads(render("users.json.j2", s1_dash_users=[])) == []
    users = [
        {"login": "jonathan", "password": "pw1", "role": "admin"},
        {
            "login": "cust_pep_africa",
            "password": 'p"w\\2',
            "role": "viewer",
            "customers": ["PEP AFRICA"],
        },
    ]
    out = json.loads(render("users.json.j2", s1_dash_users=users))
    assert out[0] == {"login": "jonathan", "password": "pw1", "role": "admin"}
    assert "customers" not in out[0]
    assert out[1]["password"] == 'p"w\\2'
    assert out[1]["customers"] == ["PEP AFRICA"]


def test_defaults_present():
    d = defaults()
    assert d["s1_dash_image"] == "ghcr.io/systems-one/s1-dash"
    assert d["s1_dash_tag"] == "latest"
    assert d["s1_dash_dir"] == "/opt/s1-dash"
    assert d["s1_dash_port"] == 8094
    assert d["s1_dash_bind_address"] == "127.0.0.1"
    assert d["s1_dash_session_secure"] is True
    assert d["s1_dash_trust_proxy_ip"] is True
    assert d["s1_dash_users"] == []
    assert d["s1_dash_session_secret"] == ""
    assert d["s1_dash_ghcr_token"] == ""
    assert "mssql_rm_admin_login" in d["s1_dash_db_user"]
    assert "mssql_rm_admin_password" in d["s1_dash_db_pass"]


def test_tasks_guard_secrets_and_modes():
    t = read("tasks", "main.yml")
    assert "s1_dash_session_secret | length >= 32" in t
    assert "docker compose pull" in t and "--build" not in t
    assert t.count("no_log: true") >= 3
    assert '"0600"' in t and '"0640"' in t
    assert 'owner: "1001"' in t


def test_webservers_has_role_with_tag():
    pb = yaml.safe_load(open(os.path.join(REPO, "webservers.yml"), encoding="utf-8"))
    roles = pb[0]["roles"]
    mine = [r for r in roles if isinstance(r, dict) and r.get("role") == "s1_dash"]
    assert mine and mine[0]["tags"] == ["s1_dash"]
    names = [r if isinstance(r, str) else r["role"] for r in roles]
    assert names.index("s1_dash") == names.index("s1_monitor") + 1


# The spec's "Owner decisions" section says "twelve" but lists eleven logins.
SPEC_USERS = {
    "jonathan": ("admin", None),
    "avi": ("viewer", None),
    "chris": ("viewer", None),
    "pkluser": ("viewer", ["PEPKOR"]),
    "cust_bex": ("viewer", ["BEX"]),
    "cust_dcb": ("viewer", ["DCB"]),
    "cust_madibana": ("viewer", ["MADIBANA"]),
    "cust_pep": ("viewer", ["PEP"]),
    "cust_pep_africa": ("viewer", ["PEP AFRICA"]),
    "cust_pepkor": ("viewer", ["PEPKOR"]),
    "cust_snowsoft": ("viewer", ["SNOWSOFT"]),
}


def hostvars():
    return yaml.safe_load(
        open(os.path.join(REPO, "host_vars", "sysone.yml"), encoding="utf-8")
    )


def test_host_vars_users_and_vault_references():
    users = hostvars()["s1_dash_users"]
    assert len(users) == len(SPEC_USERS) == 11
    assert {u["login"] for u in users} == set(SPEC_USERS)
    for u in users:
        role, customers = SPEC_USERS[u["login"]]
        assert u["role"] == role, u["login"]
        assert u.get("customers") == customers, u["login"]
        if u["login"] == "cust_pepkor":
            name = "vault_s1_dash_cust_pepkor_password"
        else:
            name = "vault_grafana_%s_password" % u["login"]
        assert u["password"] == "{{ %s }}" % name, u["login"]


def test_host_vars_preview_and_secrets_are_vault_refs():
    hv = hostvars()
    assert hv["s1_dash_bind_address"] == "100.102.46.89"
    assert hv["s1_dash_session_secure"] is False
    assert hv["s1_dash_session_secret"] == "{{ vault_s1_dash_session_secret }}"
    assert hv["s1_dash_ghcr_token"] == "{{ vault_s1_dash_ghcr_token }}"
    assert hv["s1_dash_ghcr_user"] == "Systems-One"
    raw = open(os.path.join(REPO, "host_vars", "sysone.yml"), encoding="utf-8").read()
    assert "revert" in raw.lower() and "cutover" in raw.lower()


def test_no_literal_secrets_in_role_yaml():
    # any secret-ish key must be empty or a Jinja reference
    pat = re.compile(r"^\s*s1_dash_\w*(secret|token|pass\w*)\s*:\s*(.*)$", re.I)
    for sub in (("defaults", "main.yml"), ("tasks", "main.yml")):
        for line in read(*sub).splitlines():
            m = pat.match(line)
            if m:
                val = m.group(2).strip()
                assert val in ('""', "") or val.startswith('"{{'), line


# ---- fix round 1 ----------------------------------------------------------

def tasks():
    return yaml.safe_load(read("tasks", "main.yml"))


def test_trust_proxy_preview_false_production_true():
    prod = compose()["services"]["s1-dash"]["environment"]
    assert prod["TRUST_PROXY_IP"] == "true"
    prev = compose(
        s1_dash_bind_address="100.102.46.89",
        s1_dash_session_secure=False,
        s1_dash_trust_proxy_ip=False,
    )["services"]["s1-dash"]["environment"]
    assert prev["TRUST_PROXY_IP"] == "false"


def test_host_vars_preview_disables_trust_proxy():
    hv = hostvars()
    assert hv["s1_dash_trust_proxy_ip"] is False
    raw = open(os.path.join(REPO, "host_vars", "sysone.yml"), encoding="utf-8").read()
    assert "three" in raw.lower()


def test_trust_proxy_assertion_conditions():
    guard = [
        t for t in tasks()
        if "assert" in t and any("trust_proxy" in c for c in t["assert"]["that"])
    ]
    assert len(guard) == 1
    assert "no_log" not in guard[0]
    assert "client-IP" in guard[0]["assert"]["fail_msg"] or "client IP" in guard[0]["assert"]["fail_msg"]
    env = jinja2.Environment()
    conds = [env.compile_expression(c) for c in guard[0]["assert"]["that"]]

    def ok(trust, bind):
        return all(
            c(s1_dash_trust_proxy_ip=trust, s1_dash_bind_address=bind) for c in conds
        )

    assert ok(True, "127.0.0.1")
    assert ok(True, "::1")
    assert ok(True, "localhost")
    assert not ok(True, "100.102.46.89")
    assert not ok(True, "0.0.0.0")
    assert ok(False, "100.102.46.89")
    assert ok(False, "127.0.0.1")


NASTY = 'a"b' + chr(92) + 'c$d#e: f' + chr(39) + 'g<h>&i'


def test_compose_escapes_secret_values():
    text = render(
        "docker-compose.s1_dash.yml.j2",
        s1_dash_db_pass="db" + NASTY,
        s1_dash_session_secret="sess" + NASTY + "x" * 40,
        s1_dash_db_user="u" + NASTY,
    )
    env = yaml.safe_load(text)["services"]["s1-dash"]["environment"]
    assert env["DB_PASS"] == ("db" + NASTY).replace("$", "$$")
    assert env["SESSION_SECRET"] == ("sess" + NASTY + "x" * 40).replace("$", "$$")
    assert env["DB_USER"] == ("u" + NASTY).replace("$", "$$")


def test_pull_changed_only_when_image_changes():
    ts = tasks()
    pull = [t for t in ts if t.get("command", "") == "docker compose pull"]
    assert pull and pull[0].get("changed_when") is False
    inspects = [t for t in ts if "docker image inspect" in str(t.get("command", ""))]
    assert len(inspects) == 2
    assert inspects[0].get("failed_when") is False
    assert inspects[1].get("failed_when") is False
    assert "stdout" in str(inspects[1]["changed_when"])
