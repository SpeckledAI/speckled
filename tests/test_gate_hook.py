"""Tests for hooks/gate.py, the Claude Code adapter [T-F07-08].

Each case runs the hook as a subprocess with a Claude Code payload, as tests/test_guard.py
does. Run with: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "gate.py"
sys.path.insert(0, str(ROOT / "lib"))

from speckled_gate.project import load_project  # noqa: E402
from speckled_gate.rules import actions_for, decide  # noqa: E402

from gate import test_rules  # noqa: E402  (imported as a module: its tests aren't re-collected)
from gate.fixtures import make_project  # noqa: E402


class HookFixture(test_rules.Fixture):
    def run_hook(self, payload, env=None):
        """Run gate.py; return (exit code, stdout, stderr). Never allows permissionDecision."""
        data = payload if isinstance(payload, str) else json.dumps(payload)
        full_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
        full_env.update(env or {})
        out = subprocess.run([sys.executable, str(GATE), "--plugin-data", str(self.data)],
                             input=data, text=True, capture_output=True, env=full_env)
        self.assertNotIn("permissionDecision", out.stdout)
        return out.returncode, out.stdout, out.stderr

    def payload(self, tool, tool_input, cwd, **extra):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                "cwd": str(cwd), "session_id": "test", **extra}

    def rows(self):
        """The T-F07-06 rule table, as calls made from a session in the planning repo.

        Rows written for a shell in the code repo become `cd <repo> && ...`, because a
        session started in a code repo is a wrong start (tested separately).
        """
        out = []
        for name, active, (tool, tool_input), cwd, expected in test_rules.RuleTable.rows(self):
            if cwd != self.plans and tool == "Bash":
                tool_input = {"command": f"cd {cwd} && {tool_input['command']}"}
            out.append((name, active, tool, tool_input, expected))
        return out

    def set_active(self, active):
        marker = self.plans / ".speckled" / "active-task"
        if marker.exists():
            marker.unlink()
        if active:
            marker.parent.mkdir(exist_ok=True)
            marker.write_text(json.dumps({"v": 1, "task": active}))

    def log_lines(self):
        log = self.plans / ".speckled" / "log.jsonl"
        return log.read_text().splitlines() if log.exists() else []


class BlockMode(HookFixture):
    def test_rule_table(self):
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 20)
        for name, active, tool, tool_input, expected in rows:
            with self.subTest(name):
                self.set_active(active)
                code, stdout, stderr = self.run_hook(self.payload(tool, tool_input, self.plans))
                if expected:
                    self.assertEqual(code, 2)
                    self.assertTrue(stderr.startswith("speckled: blocked: "), stderr)
                    self.assertEqual(len(stderr.strip().split("\n")), 3)
                else:
                    self.assertEqual((code, stdout, stderr), (0, "", ""))
        self.assertEqual(self.log_lines(), [])  # block mode never logs


class WarnMode(HookFixture):
    def setUp(self):
        super().setUp()
        text = (self.plans / "speckled.yaml").read_text().replace("enforcement: block", "enforcement: warn")
        (self.plans / "speckled.yaml").write_text(text)

    def test_rule_table(self):
        for name, active, tool, tool_input, expected in self.rows():
            with self.subTest(name):
                self.set_active(active)
                project = load_project(self.plans, self.plugin, self.data, self.home)
                broken = [v for v in (decide(project, a) for a in
                                      actions_for(tool, tool_input, project, str(self.plans))) if not v.ok]
                before = len(self.log_lines())
                code, stdout, stderr = self.run_hook(self.payload(tool, tool_input, self.plans))
                self.assertEqual((code, stderr), (0, ""))
                if expected:
                    out = json.loads(stdout)
                    context = out["hookSpecificOutput"]["additionalContext"]
                    self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
                    self.assertTrue(context.startswith("speckled (warn): would block: "))
                    self.assertTrue(context.endswith("Allowed and logged."))
                    self.assertEqual(out["systemMessage"], context)
                    new = [json.loads(line) for line in self.log_lines()[before:]]
                    self.assertEqual(len(new), len(broken))
                    self.assertEqual(new[0]["rule"], expected)
                    self.assertEqual(new[0]["mode"], "warn")
                else:
                    self.assertEqual(stdout, "")
                    self.assertEqual(len(self.log_lines()), before)

    def test_subagent_is_logged_by_type(self):
        code, stdout, _ = self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")},
                                                     self.plans, agent_type="Explore", agent_id="a1"))
        self.assertEqual(code, 0)
        self.assertTrue(stdout)
        self.assertEqual(json.loads(self.log_lines()[-1])["agent"], "Explore")

    def test_unwritable_log_still_allows(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignores permissions")
        (self.plans / ".speckled").mkdir(exist_ok=True)
        os.chmod(self.plans / ".speckled", 0o500)
        try:
            code, stdout, _ = self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans))
        finally:
            os.chmod(self.plans / ".speckled", 0o700)
        self.assertEqual(code, 0)
        self.assertIn("(not logged:", json.loads(stdout)["systemMessage"])


class Subagents(HookFixture):
    def test_subagent_blocked_the_same_way(self):
        code, _, stderr = self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans,
                                                     agent_type="Explore", agent_id="a1"))
        self.assertEqual(code, 2)
        self.assertIn("no active task", stderr)


class WrongStart(HookFixture):
    def test_session_in_a_code_repo(self):
        self.run_hook(self.payload("Read", {}, self.plans))  # a normal start records the registry
        code, _, stderr = self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.app))
        self.assertEqual(code, 2)
        self.assertIn(f"cd {self.plans} && claude --add-dir ../app", stderr)


class StaysOutOfTheWay(HookFixture):
    """NFR6: without enforcement the hook behaves as if it weren't installed."""

    def test_no_speckled_yaml(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.assertEqual(self.run_hook(self.payload("Bash", {"command": "git push"}, elsewhere)), (0, "", ""))

    def test_enforcement_off(self):
        (self.plans / "speckled.yaml").write_text("enforcement: off\nrepos: [../app]\n")
        self.assertEqual(self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans)),
                         (0, "", ""))

    def test_invalid_payloads(self):
        for bad in ["not json", "[]", "{}"]:
            with self.subTest(bad=bad):
                self.assertEqual(self.run_hook(bad), (0, "", ""))


class FailsClosed(HookFixture):
    def test_internal_error_with_enforcement_on(self):
        code, _, stderr = self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans),
                                        env={"SPECKLED_TEST_INTERNAL_ERROR": "1"})
        self.assertEqual(code, 2)
        self.assertIn("internal error", stderr)
        self.assertIn("set enforcement: off", stderr)

    def test_internal_error_with_enforcement_off(self):
        (self.plans / "speckled.yaml").write_text("enforcement: off\n")
        self.assertEqual(self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans),
                                       env={"SPECKLED_TEST_INTERNAL_ERROR": "1"}), (0, "", ""))


class HooksJson(unittest.TestCase):
    def test_final_shape(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        self.assertEqual(len(config), 2)
        guard, gate = config
        self.assertEqual(guard["matcher"], "Bash|PowerShell|Read|Edit|MultiEdit|Write|NotebookEdit|Grep|Glob")
        self.assertIn("hooks/guard.py", guard["hooks"][0]["command"])
        self.assertEqual(gate["matcher"], "Bash|PowerShell|Edit|MultiEdit|Write|NotebookEdit|mcp__.*")
        self.assertIn("hooks/gate.py", gate["hooks"][0]["command"])
        self.assertIn('--plugin-data "${CLAUDE_PLUGIN_DATA}"', gate["hooks"][0]["command"])
        self.assertEqual(gate["hooks"][0]["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
