"""index.html must reference its scripts and stylesheet with a content-derived version, so a deploy
changes the URLs and Cloudflare's edge cache of /static/*.js cannot serve the previous build."""
import os, re
import main
from fastapi.testclient import TestClient

REF = re.compile(r'(?:src|href)="(/static/[^"]+)"')

def test_index_versions_every_static_reference():
    html = TestClient(main.app).get("/").text
    refs = REF.findall(html)
    assert len(refs) >= 5, refs
    versions = set()
    for ref in refs:
        m = re.fullmatch(r"/static/[A-Za-z0-9_./-]+\?v=([0-9a-f]{12})", ref)
        assert m, ref
        versions.add(m.group(1))
    assert len(versions) == 1, "one version for the whole build"
    assert versions.pop() == main.STATIC_VERSION

def test_versioned_static_url_is_served():
    r = TestClient(main.app).get("/static/api.js?v=" + main.STATIC_VERSION)
    assert r.status_code == 200 and "attachDownload" in r.text

def test_version_follows_the_file_contents(tmp_path):
    (tmp_path / "api.js").write_text("one", encoding="utf-8")
    a = main.static_version(str(tmp_path))
    (tmp_path / "api.js").write_text("two", encoding="utf-8")
    b = main.static_version(str(tmp_path))
    assert a != b and len(a) == 12

def test_index_stays_uncached():
    r = TestClient(main.app).get("/")
    assert "no-store" in r.headers.get("cache-control", "")
