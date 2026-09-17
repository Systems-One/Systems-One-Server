"""Heatmap cell labels: every cell that has a rate must show it, with a % sign.

Runs the label formatter from charts.js under Node so the check exercises the real
code rather than a string match.
"""
import os, re, json, shutil, subprocess, pytest
ROLE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHARTS = os.path.join(ROLE, "files", "app", "static", "charts.js")
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")

def _formatter_src():
    src = open(CHARTS, encoding="utf-8").read()
    m = re.search(r"type:'heatmap',data:cells,label:\{[^}]*?formatter:(p=>.*?)\},itemStyle", src)
    assert m, "heatmap label formatter not found in charts.js"
    return m.group(1)

def _run(is_pct, cells):
    js = ("const MIN_HOUR=30; const fn=(isPct)=>(%s);"
          "const out=%s.map(v=>fn(%s)({value:v})); process.stdout.write(JSON.stringify(out));"
          % (_formatter_src(), json.dumps(cells), "true" if is_pct else "false"))
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)

def test_pct_labels_always_shown_with_percent_sign():
    # [hour, row, rate, items]: high volume, low volume (under MIN_HOUR), and a single item
    out = _run(True, [[0, 0, 97.4, 500], [1, 0, 55.0, 12], [2, 0, 0.0, 1]])
    assert out == ["97%", "55%", "0%"]

def test_items_labels_show_counts_and_blank_idle():
    out = _run(False, [[0, 0, 340, 340], [1, 0, 0, 0]])
    assert out == [340, ""]
