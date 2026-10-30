"""The 'download as image' PNG must hold the whole header and, for the doughnut, its legend.
Reproduces: a 230px-wide doughnut produced a 460px PNG that clipped the title and dropped the legend."""
import json, os, shutil, subprocess, pytest
HERE = os.path.dirname(__file__)
API = os.path.join(HERE, "..", "files", "app", "static", "api.js")
HARNESS = os.path.join(HERE, "download_harness.mjs")
PR = 2  # pixelRatio used by attachDownload

def export(meta):
    node = shutil.which("node")
    if not node: pytest.skip("node not installed")
    out = subprocess.run([node, HARNESS, API, json.dumps(meta)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def png(calls): return next(c for c in calls if c["op"] == "png")
def texts(calls): return [c for c in calls if c["op"] == "text"]
def width_of(c): return len(c["s"]) * float(c["font"].split("px")[0].split()[-1]) * 0.55

def test_canvas_is_wide_enough_for_the_header():
    calls = export({"title": "DIM5 @ JBH · Errors, last 48 hours", "sub": "PEPKOR · 14 720 items", "name": ["x"], "imgW": 460, "imgH": 460})
    p = png(calls)
    for c in texts(calls):
        assert c["x"] + width_of(c) <= p["w"], (c["s"], c["x"] + width_of(c), p["w"])
    img = next(c for c in calls if c["op"] == "img")
    assert img["x"] >= 0 and img["x"] + img["w"] <= p["w"]
    assert img["y"] + img["h"] <= p["h"]

def test_wide_chart_keeps_its_own_width():
    calls = export({"title": "DIM5 @ JBH · Per hour total items, last 48 hours", "sub": "PEPKOR", "name": ["x"], "imgW": 2200, "imgH": 560})
    p = png(calls)
    assert p["w"] == 2200 and p["h"] == 560 + 76 * PR

def test_legend_rows_are_drawn_beside_the_chart():
    legend = [{"col": "#39f", "name": "Good read", "n": "14 484", "pct": "98.4%"},
              {"col": "#e66", "name": "No read", "n": "236", "pct": "1.6%"},
              {"note": "Also flagged, can overlap with the above"},
              {"col": "#d95", "name": "No dimension", "n": "12", "pct": "0.1%"}]
    calls = export({"title": "DIM5 @ JBH · Errors, last 48 hours", "sub": "PEPKOR · 14 720 items", "name": ["x"], "imgW": 460, "imgH": 460, "legend": legend})
    p = png(calls); drawn = {c["s"]: c for c in texts(calls)}
    for s in ("Good read", "14 484", "98.4%", "No read", "Also flagged, can overlap with the above", "No dimension"):
        assert s in drawn, s
        assert drawn[s]["x"] + width_of(drawn[s]) <= p["w"] + 1, s
    img = next(c for c in calls if c["op"] == "img")
    assert drawn["Good read"]["x"] >= img["x"] + img["w"], "legend sits to the right of the doughnut"
    assert drawn["Good read"]["y"] > 76 * PR, "legend starts below the header"
    assert drawn["No read"]["y"] > drawn["Good read"]["y"]


# ---- delivery: iPhone gets the share sheet (Save Image), everything else a blob download ----
IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"
BASE = {"title": "DIM5 @ JBH · Errors, last 48 hours", "sub": "PEPKOR", "name": ["PEPKOR", "JBH", "DIM5", "errors", "48h"], "imgW": 460, "imgH": 460}

def test_iphone_uses_the_share_sheet_with_a_png_file():
    calls = export(dict(BASE, ua=IOS, canShare=True))
    share = [c for c in calls if c["op"] == "share"]
    assert len(share) == 1 and share[0]["files"] == 1 and share[0]["type"] == "image/png"
    assert share[0]["name"].startswith("S1_PEPKOR_JBH_DIM5_errors_48h_") and share[0]["name"].endswith(".png")
    assert not [c for c in calls if c["op"] == "click"], "no hidden-link download on iOS"

def test_desktop_downloads_a_blob_url_not_a_data_url():
    calls = export(dict(BASE, canShare=True))   # desktop Chrome can share files too, but must still download
    click = [c for c in calls if c["op"] == "click"]
    assert len(click) == 1 and click[0]["href"] == "blob:" and click[0]["download"].endswith(".png")
    assert not [c for c in calls if c["op"] == "share"]

def test_iphone_without_file_sharing_falls_back_to_download():
    calls = export(dict(BASE, ua=IOS, canShare=False))
    assert [c for c in calls if c["op"] == "click"] and not [c for c in calls if c["op"] == "share"]

def test_ipad_reporting_as_mac_is_treated_as_ios():
    calls = export(dict(BASE, ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", platform="MacIntel", touch=5, canShare=True))
    assert [c for c in calls if c["op"] == "share"]

def test_export_is_synchronous_with_the_tap():
    """iOS only opens the share sheet inside the user gesture, so nothing may wait for an Image load first."""
    calls = export(dict(BASE, ua=IOS, canShare=True))
    assert calls and calls[-1]["op"] == "share"
