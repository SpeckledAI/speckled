"""Tests for lib/speckled_chain/cli.py and bin/lint-chain [T-F08-03].

These run `bin/lint-chain` as a subprocess, as a user or CI would.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "bin" / "lint-chain"


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.plans = self.tmp / "plans"
        (self.plans / "docs").mkdir(parents=True)
        (self.plans / "speckled.yaml").write_text("project: example\nroles:\n  code: [alice]\n", encoding="utf-8")

    def run_cli(self, *argv, cwd=None):
        return subprocess.run([sys.executable, str(BIN), *argv], cwd=cwd or self.plans,
                              capture_output=True, text=True, timeout=30)

    def test_no_speckled_yaml(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        out = self.run_cli(cwd=empty)
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stdout, "")
        self.assertEqual(len(out.stderr.splitlines()), 1)
        self.assertIn("no speckled.yaml in", out.stderr)
        self.assertIn("Run it from the planning repo.", out.stderr)

    def test_project_without_speckled_yaml(self):
        out = self.run_cli("--project", str(self.tmp))
        self.assertEqual(out.returncode, 2)
        self.assertEqual(len(out.stderr.splitlines()), 1)

    def test_bad_roles(self):
        (self.plans / "speckled.yaml").write_text("project: example\nroles: [alice]\n", encoding="utf-8")
        out = self.run_cli()
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stderr.splitlines(), [out.stderr.strip()])
        self.assertIn("line 2", out.stderr)

    def test_explain(self):
        out = self.run_cli("--explain", "front-matter", cwd=self.tmp)  # needs no project
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.startswith("front-matter (default severity: error)"))
        self.assertIn("Fix: ", out.stdout)

    def test_explain_unknown_rule(self):
        out = self.run_cli("--explain", "nope")
        self.assertEqual(out.returncode, 64)
        self.assertIn("unknown rule 'nope'", out.stderr)

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("--feature", "F8").returncode, 64)
        self.assertEqual(self.run_cli("--nope").returncode, 64)
        self.assertEqual(self.run_cli("--feature", "F08").returncode, 0)

    def test_help(self):
        out = self.run_cli("--help")
        self.assertEqual(out.returncode, 0)
        self.assertIn("--explain", out.stdout)

    def test_minimal_project(self):
        out = self.run_cli()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("speckled lint-chain: example", out.stdout)
        self.assertTrue(out.stdout.endswith("No problems found.\n"))

    def test_from_a_subfolder(self):
        self.assertEqual(self.run_cli(cwd=self.plans / "docs").returncode, 0)

    def test_json(self):
        out = self.run_cli("--json", "--docs", "--strict")
        self.assertEqual(out.returncode, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["project"], "example")
        self.assertEqual(data["findings"], [])

    def test_output(self):
        target = self.tmp / "report.json"
        out = self.run_cli("--output", str(target))
        self.assertEqual(out.returncode, 0)
        self.assertIn("No problems found.", out.stdout)  # text still printed
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["tool"], "lint-chain")

    def test_output_failure_after_text(self):
        out = self.run_cli("--output", str(self.tmp / "missing" / "report.json"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("No problems found.", out.stdout)
        self.assertEqual(len(out.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
