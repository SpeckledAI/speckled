"""Tests for lib/speckled_gate/cli.py and bin/speckled-gate [T-F07-07]."""
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from speckled_gate.cli import USAGE_ERROR, main
from speckled_gate.rules import actions_for, decide

# Imported as a module so unittest doesn't collect (and re-run) its test classes here.
from . import test_rules

BIN = Path(__file__).resolve().parents[2] / "bin" / "speckled-gate"


class CliFixture(test_rules.Fixture):
    def run_cli(self, *argv):
        """Run main() in-process; return (exit code, stdout)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def common(self, cwd):
        return ["--project", str(self.plans), "--plugin-root", str(self.plugin),
                "--plugin-data", str(self.data), "--cwd", str(cwd)]

    def check(self, tool, tool_input, cwd):
        code, out = self.run_cli("check", "--tool", tool, "--input", json.dumps(tool_input), *self.common(cwd))
        self.assertEqual(code, 0)
        return json.loads(out)


class Check(CliFixture):
    def test_same_decision_as_decide_for_every_rule_row(self):
        rows = test_rules.RuleTable.rows(self)
        self.assertGreaterEqual(len(rows), 20)
        for name, active, (tool, tool_input), cwd, expected in rows:
            with self.subTest(name):
                marker = self.plans / ".speckled" / "active-task"
                if marker.exists():
                    marker.unlink()
                project = self.project(active)
                broken = [v.rule for v in (decide(project, a) for a in
                                           actions_for(tool, tool_input, project, str(cwd))) if not v.ok]
                result = self.check(tool, tool_input, cwd)
                self.assertEqual([v["rule"] for v in result["violations"]], broken)
                self.assertEqual(result["decision"], "block" if expected else "ok")
                if expected:
                    self.assertEqual(result["violations"][0]["rule"], expected)

    def test_violation_fields_are_relative(self):
        result = self.check("Edit", {"file_path": str(self.app / "src" / "x.py")}, self.plans)
        v = result["violations"][0]
        self.assertEqual((v["rule"], v["repo"], v["path"]), ("no-active-task", "../app", "src/x.py"))
        self.assertTrue(v["message"].startswith("speckled: blocked: "))
        self.assertNotIn(str(self.tmp), json.dumps({k: v[k] for k in ("repo", "path")}))

    def test_warn_mode_never_writes_the_log(self):
        (self.plans / "speckled.yaml").write_text("enforcement: warn\nrepos: [../app]\n")
        result = self.check("Edit", {"file_path": str(self.app / "x.py")}, self.plans)
        self.assertEqual(result["decision"], "warn")
        self.assertFalse((self.plans / ".speckled" / "log.jsonl").exists())

    def test_no_project_or_off_is_ok(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        code, out = self.run_cli("check", "--tool", "Bash", "--input", '{"command": "git push"}',
                                 "--cwd", str(elsewhere), "--plugin-data", str(self.data))
        self.assertEqual((code, json.loads(out)), (0, {"decision": "ok", "violations": []}))
        (self.plans / "speckled.yaml").write_text("enforcement: off\n")
        self.assertEqual(self.check("Bash", {"command": "git push"}, self.plans)["decision"], "ok")

    def test_bad_input_is_a_usage_error(self):
        code, _ = self.run_cli("check", "--tool", "Edit", "--input", "not json", *self.common(self.plans))
        self.assertEqual(code, USAGE_ERROR)


class Usage(CliFixture):
    def test_unknown_subcommand(self):
        self.assertEqual(self.run_cli("bogus")[0], USAGE_ERROR)

    def test_missing_subcommand(self):
        self.assertEqual(self.run_cli()[0], USAGE_ERROR)

    def test_missing_required_option(self):
        self.assertEqual(self.run_cli("check", "--tool", "Edit")[0], USAGE_ERROR)


class Status(CliFixture):
    def status(self, cwd=None, use_project=True):
        argv = ["status", *(self.common(cwd or self.plans) if use_project else
                            ["--cwd", str(cwd), "--plugin-data", str(self.data)])]
        code, out = self.run_cli(*argv)
        self.assertEqual(code, 0)
        return out

    def test_no_project(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.assertIn("No Speckled project found", self.status(elsewhere, use_project=False))

    def test_enforcement_off(self):
        (self.plans / "speckled.yaml").write_text("enforcement: off\n")
        out = self.status()
        self.assertIn("Enforcement:   off", out)
        self.assertIn("nothing is checked", out)

    def test_valid_task(self):
        self.project("T-F01-02")
        out = self.status()
        self.assertIn("Enforcement:   block", out)
        self.assertIn("Active task:   T-F01-02, valid", out)
        self.assertIn("(not created yet)", out)

    def test_done_task(self):
        self.project("T-F01-01")
        self.assertIn("Active task:   T-F01-01, not valid now (task-done): T-F01-01 is Done.", self.status())

    def test_no_active_task(self):
        self.assertIn("Active task:   none", self.status())


class Script(CliFixture):
    def test_runs_from_any_folder(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            out = subprocess.run([sys.executable, str(BIN), "check", "--tool", "Bash",
                                  "--input", '{"command": "git push"}', *self.common(self.app)],
                                 cwd=elsewhere, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["violations"][0]["rule"], "git-push")

    def test_is_executable(self):
        self.assertTrue(BIN.stat().st_mode & 0o111)
