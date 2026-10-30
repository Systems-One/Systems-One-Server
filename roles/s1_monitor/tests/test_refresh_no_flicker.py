"""The 60 s poll must not flash the page: fetch first, keep the old page and charts untouched while
waiting, swap synchronously, keep the scroll position, and never blank the page on a failed background poll."""
import json, os, shutil, subprocess, pytest
HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "..", "files", "app", "static")
HARNESS = os.path.join(HERE, "refresh_harness.mjs")

@pytest.fixture(scope="module")
def run():
    node = shutil.which("node")
    if not node: pytest.skip("node not installed")
    out = subprocess.run([node, HARNESS, STATIC], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def test_page_and_charts_untouched_while_fetch_pending(run):
    assert run["first_len"] > 0
    assert run["pending_unchanged"] is True
    assert run["pending_disposed"] == 0

def test_page_swaps_once_data_arrives(run):
    assert run["resolved_changed"] is True
    assert run["resolved_disposed"] == 1

def test_scroll_position_restored_on_same_route_poll(run):
    assert run["scroll_y_restored"] == 321

def test_failed_background_poll_keeps_the_page(run):
    assert run["failed_bg_kept_page"] is True

def test_failed_user_render_still_shows_error(run):
    assert run["failed_user_shows_error"] is True
