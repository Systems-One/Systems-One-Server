"""Guards against the reporter regaining its own baseline schedule."""
import os
import unittest

REPORTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "s1_reporter")


def _read(rel):
    with open(os.path.join(REPORTER, rel), encoding="utf-8") as fh:
        return fh.read()


class TestReporterNoLongerOwnsBaselines(unittest.TestCase):
    def test_entrypoint_has_no_baseline_block(self):
        sh = _read("files/entrypoint.sh")
        self.assertNotIn("compute_baselines", sh)
        self.assertNotIn("last_baseline_week", sh)
        self.assertNotIn("baselines every Sunday", sh)

    def test_dockerfile_does_not_copy_script(self):
        self.assertNotIn("compute_baselines", _read("files/Dockerfile"))

    def test_tasks_do_not_copy_script(self):
        self.assertNotIn("compute_baselines", _read("tasks/main.yml"))


if __name__ == "__main__":
    unittest.main()
