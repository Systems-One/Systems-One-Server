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
