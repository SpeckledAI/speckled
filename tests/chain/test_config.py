"""Tests for lib/speckled_chain/config.py [T-F08-03]."""
import tempfile
import unittest
from pathlib import Path

from speckled_chain.config import Config, ConfigError, load_config


class LoadConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "plans"
        self.root.mkdir()

    def load(self, text):
        (self.root / "speckled.yaml").write_text(text, encoding="utf-8")
        return load_config(self.root)

    def error(self, text):
        with self.assertRaises(ConfigError) as caught:
            self.load(text)
        return caught.exception

    def test_valid(self):
        config = self.load("project: Example\ndocs_dir: planning\nroles:\n  frd: [alice, Ada Lovelace]\n"
                           "  code: [bob]\n")
        self.assertEqual(config, Config("Example", "planning", {"frd": ["alice", "Ada Lovelace"],
                                                                "code": ["bob"]}))

    def test_defaults(self):
        self.assertEqual(self.load("enforcement: warn\n"), Config("plans", "docs", {}))
        self.assertEqual(self.load(""), Config("plans", "docs", {}))

    def test_empty_roles_and_empty_role(self):
        self.assertEqual(self.load("roles:\n").roles, {})
        self.assertEqual(self.load("roles:\n  frd: []\n").roles, {"frd": []})

    def test_off_and_dates_stay_text(self):
        self.assertEqual(self.load("project: off\nroles:\n  code: [no]\n"), Config("off", "docs", {"code": ["no"]}))

    def test_unreadable_yaml(self):
        e = self.error("project: x\nroles: [unclosed\n")
        self.assertGreaterEqual(e.line, 2)
        self.assertTrue(e.reason)
        self.assertIn(f"line {e.line}", str(e))

    def test_docs_dir_not_a_string(self):
        e = self.error("project: x\ndocs_dir: [a, b]\n")
        self.assertEqual(e.line, 2)
        self.assertIn("docs_dir", e.reason)

    def test_roles_not_a_mapping(self):
        e = self.error("project: x\n\nroles: [alice]\n")
        self.assertEqual(e.line, 3)
        self.assertIn("roles", e.reason)

    def test_role_not_a_list(self):
        e = self.error("roles:\n  frd: [alice]\n  tdd: alice\n")
        self.assertEqual(e.line, 3)
        self.assertIn("roles.tdd", e.reason)

    def test_role_with_a_non_string_name(self):
        e = self.error("tdd: 1\nroles:\n  tdd: [alice, 3]\n")
        self.assertEqual(e.line, 3)  # the role under `roles`, not the top-level key

    def test_missing_file(self):
        with self.assertRaises(OSError):
            load_config(self.root)


if __name__ == "__main__":
    unittest.main()
