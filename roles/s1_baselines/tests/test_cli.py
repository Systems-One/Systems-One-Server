"""CLI and config tests for compute_baselines.py (no DB)."""
import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINES = os.path.join(HERE, "..", "files", "compute_baselines.py")


def _load():
    installed = False
    if "pymssql" not in sys.modules:
        sys.modules["pymssql"] = types.ModuleType("pymssql")
        installed = True
    try:
        loader = importlib.machinery.SourceFileLoader("s1_baselines_cli", BASELINES)
        spec = importlib.util.spec_from_loader("s1_baselines_cli", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        if installed:
            sys.modules.pop("pymssql", None)


baselines = _load()

ENV = {"DB_HOST": "h", "DB_PORT": "1433", "DB_USER": "u", "DB_PASS": "p", "DB_NAME": "n"}


class TestParseArgs(unittest.TestCase):
    def test_dry_run_default_lookback(self):
        ns = baselines.parse_args(["dry-run"])
        self.assertEqual(ns.command, "dry-run")
        self.assertEqual(ns.lookback, 60)

    def test_apply_with_lookback(self):
        ns = baselines.parse_args(["apply", "--lookback", "30"])
        self.assertEqual(ns.command, "apply")
        self.assertEqual(ns.lookback, 30)

    def test_migrate(self):
        self.assertEqual(baselines.parse_args(["migrate"]).command, "migrate")

    def test_no_subcommand_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            baselines.parse_args([])
        self.assertEqual(cm.exception.code, 2)

    def test_legacy_dry_run_flag_rejected(self):
        with self.assertRaises(SystemExit):
            baselines.parse_args(["--dry-run"])


class TestLoadConfig(unittest.TestCase):
    def test_reads_all_five_from_env(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(baselines.load_config(), ENV)

    def test_missing_var_names_it(self):
        partial = dict(ENV)
        del partial["DB_PASS"]
        with patch.dict(os.environ, partial, clear=True):
            with self.assertRaises(SystemExit) as cm:
                baselines.load_config()
        self.assertIn("DB_PASS", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
