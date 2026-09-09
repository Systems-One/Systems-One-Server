"""Guards against the reporter regaining its own baseline schedule."""
import os
import unittest

REPORTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "s1_reporter")


def _read(rel):
    with open(os.path.join(REPORTER, rel), encoding="utf-8") as fh:
        return fh.read()


class TestReporterNoLongerOwnsBaselines(unittest.TestCase):
    def test_reporter_has_no_baseline_code(self):
        app = os.path.join(REPORTER, "files", "app", "s1_reporter")
        for name in os.listdir(app):
            if name.endswith(".py"):
                with open(os.path.join(app, name), encoding="utf-8") as fh:
                    self.assertNotIn("compute_baselines", fh.read(), name)
        self.assertFalse(os.path.exists(os.path.join(REPORTER, "files", "entrypoint.sh")))

    def test_dockerfile_does_not_copy_script(self):
        self.assertNotIn("compute_baselines", _read("files/Dockerfile"))

    def test_tasks_do_not_copy_script(self):
        # It may appear in the legacy-file removal list, never as a copy source.
        self.assertNotIn("src: compute_baselines", _read("tasks/main.yml"))


if __name__ == "__main__":
    unittest.main()
