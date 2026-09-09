import json
import unittest
import urllib.error
from unittest.mock import patch

import _bootstrap  # noqa: F401
from s1_reporter import teams as teams_notifier


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestPostToTeams(unittest.TestCase):
    def test_success_on_first_attempt(self):
        with patch("s1_reporter.teams.urllib.request.urlopen", return_value=FakeResponse(202)) as mock_open:
            ok = teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard"})
        self.assertTrue(ok)
        mock_open.assert_called_once()

    def test_envelope_shape(self):
        captured = {}

        def fake_urlopen(req, timeout=10):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = req.headers
            return FakeResponse(202)

        with patch("s1_reporter.teams.urllib.request.urlopen", side_effect=fake_urlopen):
            teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard", "version": "1.4"})

        self.assertEqual(captured["body"]["type"], "message")
        attachment = captured["body"]["attachments"][0]
        self.assertEqual(attachment["contentType"], "application/vnd.microsoft.card.adaptive")
        self.assertEqual(attachment["content"], {"type": "AdaptiveCard", "version": "1.4"})
        self.assertEqual(captured["headers"].get("Content-type"), "application/json")

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky_urlopen(req, timeout=10):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("boom")
            return FakeResponse(202)

        with patch("s1_reporter.teams.urllib.request.urlopen", side_effect=flaky_urlopen), \
             patch("s1_reporter.teams.time.sleep") as mock_sleep:
            ok = teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard"}, max_retries=3, backoff_seconds=1)

        self.assertTrue(ok)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_gives_up_after_max_retries(self):
        with patch("s1_reporter.teams.urllib.request.urlopen", side_effect=urllib.error.URLError("boom")) as mock_open, \
             patch("s1_reporter.teams.time.sleep"):
            ok = teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard"}, max_retries=3, backoff_seconds=0)

        self.assertFalse(ok)
        self.assertEqual(mock_open.call_count, 3)

    def test_bare_oserror_does_not_escape(self):
        """CPython can raise TimeoutError/OSError from getresponse() without wrapping
        it in URLError; post_to_teams documents that it never raises."""
        with patch("s1_reporter.teams.urllib.request.urlopen", side_effect=TimeoutError("timed out")), \
             patch("s1_reporter.teams.time.sleep"):
            ok = teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard"}, max_retries=2, backoff_seconds=0)
        self.assertFalse(ok)

    def test_non_2xx_status_is_treated_as_failure_and_retried(self):
        with patch("s1_reporter.teams.urllib.request.urlopen", return_value=FakeResponse(400)), \
             patch("s1_reporter.teams.time.sleep"):
            ok = teams_notifier.post_to_teams("https://example.invalid/webhook", {"type": "AdaptiveCard"}, max_retries=2, backoff_seconds=0)

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
