import os, re
ROLE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
def read(*p): return open(os.path.join(ROLE, *p), encoding="utf-8").read()

def test_dockerfile_has_odbc_and_non_root():
    d = read("files", "Dockerfile")
    assert "msodbcsql18" in d and "USER appuser" in d and "TZ=Africa/Johannesburg" in d

def test_compose_template_binds_loopback_and_env():
    t = read("templates", "docker-compose.s1_monitor.yml.j2")
    for key in ("DB_HOST", "DB_PASS", "TZ_OFFSET_HOURS", "MIN_ITEMS_DAY", "OFFLINE_GAP_MINUTES", "SNAPSHOT_ENABLED"):
        assert key in t
    assert "{{ s1_monitor_bind_address }}:{{ s1_monitor_port }}:8000" in t

def test_defaults_present():
    d = read("defaults", "main.yml")
    for key in ("s1_monitor_port: 8090", "s1_monitor_bind_address: \"127.0.0.1\"", "s1_monitor_min_items_day: 100", "s1_monitor_min_items_hour: 30", "s1_monitor_min_items_half_hour: 15", "s1_monitor_offline_gap_minutes: 11", "s1_monitor_stale_days: 14"):
        assert key in d, key

def test_vendored_echarts_present_and_pinned():
    p = os.path.join(ROLE, "files", "app", "static", "vendor", "echarts.min.js")
    assert os.path.getsize(p) > 900_000
    head = open(p, encoding="utf-8", errors="ignore").read(4000)
    assert "Apache" in head

def test_no_getdate_in_queries():
    qdir = os.path.join(ROLE, "files", "app", "queries")
    for name in os.listdir(qdir):
        if name.endswith(".py"):
            assert not re.search(r"GETDATE\s*\(", read("files", "app", "queries", name), re.I), name
