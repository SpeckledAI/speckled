"""Tests for hooks/pretooluse.py, the one registered PreToolUse hook [T-F07-17].

The guard's and the gate's hook tests run again here, through the entry script: each
case must give the same answer as guard.py or gate.py run on its own. The tests in
tests/test_guard.py and tests/test_gate_hook.py are reused unchanged; only the function
that runs the hook is swapped. Run with: python3 -m unittest discover tests
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_gate_hook
import test_guard
from gate.fixtures import make_project

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "hooks" / "pretooluse.py"

# guard.py loaded under another name, for its verdicts: "gate" is the tests/gate package here.
_spec = importlib.util.spec_from_file_location("guard_hook", ROOT / "hooks" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

GUARD_RUN = test_guard.run  # the original, before the patches below


def run_entry(payload, plugin_data, entry=ENTRY, env=None, cwd=None):
    """Run pretooluse.py; return (exit code, stdout, stderr)."""
    data = payload if isinstance(payload, str) else json.dumps(payload)
    full_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
    full_env.update(env or {})
    out = subprocess.run([sys.executable, str(entry), "--plugin-data", str(plugin_data)],
                         input=data, text=True, capture_output=True, env=full_env, cwd=cwd)
    return out.returncode, out.stdout, out.stderr


def guard_reason(payload):
    """The guard's verdict on a payload, or None."""
    if not isinstance(payload, dict):
        return None
    return guard.check(payload.get("tool_name", ""), payload.get("tool_input") or {})


# --- the guard's cases ------------------------------------------------------------------

class GuardThroughEntry:
    """Runs test_guard's cases through pretooluse.py, inside a project with `mode` enforcement.

    With enforcement off, the exit code must be guard.py's. With block, a guard block must
    be the guard's message; any other case may still be stopped by the gate, but not by
    the guard.
    """
    mode = "off"

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(os.path.realpath(tmp.name))
        self.plans = make_project(root, f"enforcement: {self.mode}\nrepos:\n  - ../app\n").root
        self.data = root / "plugin-data"
        patcher = mock.patch.object(test_guard, "run", self.compare)
        patcher.start()
        self.addCleanup(patcher.stop)

    def compare(self, payload, guard=test_guard.GUARD, cwd=None) -> int:
        expected = GUARD_RUN(payload, guard, cwd)
        if isinstance(payload, dict):
            payload = {"cwd": str(self.plans), **payload}
        code, stdout, stderr = run_entry(payload, self.data, cwd=self.plans)
        if self.mode == "off":
            self.assertEqual(code, expected, payload)
        elif expected == 2:
            self.assertEqual((code, stdout), (2, ""), payload)
            self.assertTrue(stderr.startswith("speckled guard: "), stderr)
        else:
            self.assertFalse(stderr.startswith("speckled guard: "), payload)
        return expected


class GuardBlocksEnforcementOff(GuardThroughEntry, test_guard.BlocksDangerousCalls):
    mode = "off"


class GuardAllowsEnforcementOff(GuardThroughEntry, test_guard.AllowsSafeCalls):
    mode = "off"


class GuardBlocksEnforcementBlock(GuardThroughEntry, test_guard.BlocksDangerousCalls):
    mode = "block"


class GuardAllowsEnforcementBlock(GuardThroughEntry, test_guard.AllowsSafeCalls):
    mode = "block"


# --- the gate's cases -------------------------------------------------------------------

class GateThroughEntry:
    """Runs each test_gate_hook case through gate.py and pretooluse.py, and compares them.

    Same exit code, stdout, stderr and log entries, unless the guard blocks the call: then
    the entry script must stop with the guard's message and log only that block, and the case's
    own assertions check gate.py's answer and log, so they stay about the gate. Otherwise
    the log is left as the entry script wrote it.
    """

    def run_hook(self, payload, env=None):
        log = self.plans / ".speckled" / "log.jsonl"
        before = log.read_text() if log.exists() else None
        expected = super().run_hook(payload, env)
        gate_log = self._new_entries(log, before)
        if gate_log:
            after_gate = log.read_text()
            log.write_text(before or "")
        code, stdout, stderr = run_entry(payload, self.data, env=env)
        self.assertNotIn("permissionDecision", stdout)
        entry_log = self._new_entries(log, before)

        reason = guard_reason(payload)
        if reason:
            self.assertEqual((code, stdout, stderr), (2, "", f"speckled guard: {reason}\n"))
            # The guard's block is logged as one block entry [T-F07-20].
            rule = {guard.RM_MESSAGE: "recursive-delete", guard.ENV_MESSAGE: "secret-env-file"}[reason]
            self.assertEqual([(e["mode"], e["rule"]) for e in entry_log], [("block", rule)])
            # The case goes on to check gate.py's log, so put that back.
            if gate_log:
                log.write_text(after_gate)
            elif before is None:
                log.unlink()
            else:
                log.write_text(before)
            return expected
        self.assertEqual((code, stdout, stderr), expected)
        self.assertEqual(entry_log, gate_log)
        return code, stdout, stderr

    @staticmethod
    def _new_entries(log, before):
        """Log entries added since `before`, without their timestamps."""
        lines = log.read_text().splitlines() if log.exists() else []
        new = lines[len(before.splitlines()) if before else 0:]
        return [{k: v for k, v in json.loads(line).items() if k != "ts"} for line in new]


class BlockModeThroughEntry(GateThroughEntry, test_gate_hook.BlockMode):
    pass


class WarnModeThroughEntry(GateThroughEntry, test_gate_hook.WarnMode):
    pass


class SubagentsThroughEntry(GateThroughEntry, test_gate_hook.Subagents):
    pass


class WrongStartThroughEntry(GateThroughEntry, test_gate_hook.WrongStart):
    pass


class StaysOutOfTheWayThroughEntry(GateThroughEntry, test_gate_hook.StaysOutOfTheWay):
    pass


class FailsClosedThroughEntry(GateThroughEntry, test_gate_hook.FailsClosed):
    pass


# --- the entry script itself ------------------------------------------------------------

class GuardComesFirst(test_gate_hook.HookFixture):
    def set_mode(self, mode):
        text = (self.plans / "speckled.yaml").read_text().replace("enforcement: block", f"enforcement: {mode}")
        (self.plans / "speckled.yaml").write_text(text)

    def test_warn_mode_guard_block_is_logged_as_a_block(self):
        self.set_mode("warn")
        payload = self.payload("Bash", {"command": f"cd {self.app} && rm -rf build"}, self.plans)
        # gate.py alone would warn about it (no active task) ...
        self.assertTrue(self.run_hook(payload)[1])
        (self.plans / ".speckled" / "log.jsonl").unlink()
        # ... but through the entry script the guard stops it first, and it's logged as a
        # guard block, not a warn event [T-F07-20].
        self.assertEqual(run_entry(payload, self.data), (2, "", f"speckled guard: {guard.RM_MESSAGE}\n"))
        entries = [json.loads(line) for line in self.log_lines()]
        self.assertEqual([(e["mode"], e["rule"], e["paths"]) for e in entries],
                         [("block", "recursive-delete", [])])
        self.assertNotIn("rm -rf", self.log_lines()[0])

    def test_guard_blocks_logged_in_both_modes(self):
        config = (self.plans / "speckled.yaml").read_text()
        for mode in ("warn", "block"):
            with self.subTest(mode):
                (self.plans / "speckled.yaml").write_text(config.replace("enforcement: block", f"enforcement: {mode}"))
                payload = self.payload("Read", {"file_path": str(self.app / ".env")}, self.plans)
                code, _, stderr = run_entry(payload, self.data)
                self.assertEqual((code, stderr), (2, f"speckled guard: {guard.ENV_MESSAGE}\n"))
                entry = json.loads(self.log_lines()[-1])
                self.assertEqual((entry["mode"], entry["rule"], entry["tool"], entry["repo"], entry["paths"]),
                                 ("block", "secret-env-file", "Read", "../app", [".env"]))

    def test_guard_block_not_logged_without_enforcement(self):
        (self.plans / "speckled.yaml").write_text("enforcement: off\nrepos: [../app]\n")
        payload = self.payload("Bash", {"command": "rm -rf build"}, self.plans)
        self.assertEqual(run_entry(payload, self.data)[0], 2)
        self.assertEqual(self.log_lines(), [])
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.assertEqual(run_entry(self.payload("Bash", {"command": "rm -rf build"}, elsewhere), self.data)[0], 2)
        self.assertFalse((elsewhere / ".speckled").exists())


class PluginCopy(test_gate_hook.HookFixture):
    """A copy of the plugin whose gate.py is replaced by `gate_source`."""
    gate_source = ""

    def setUp(self):
        super().setUp()
        copy = self.tmp / "plugin-copy"
        shutil.copytree(ROOT / "hooks", copy / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "lib", copy / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        (copy / "hooks" / "gate.py").write_text(self.gate_source)
        self.entry = copy / "hooks" / "pretooluse.py"

    def run_copy(self, tool, tool_input, env=None):
        return run_entry(self.payload(tool, tool_input, self.plans), self.data, entry=self.entry, env=env)


class BrokenGate(PluginCopy):
    """Broken gate code can't stop the guard, and allows everything else."""
    gate_source = 'raise RuntimeError("broken gate")\n'

    def test_guard_still_blocks(self):
        code, _, stderr = self.run_copy("Bash", {"command": "rm -rf build"})
        self.assertEqual((code, stderr), (2, f"speckled guard: {guard.RM_MESSAGE}\n"))
        code, _, stderr = self.run_copy("Read", {"file_path": str(self.app / ".env")})
        self.assertEqual((code, stderr), (2, f"speckled guard: {guard.ENV_MESSAGE}\n"))

    def test_other_calls_allowed(self):
        # The real gate blocks this edit: enforcement is block and no task is active.
        self.assertEqual(self.run_hook(self.payload("Edit", {"file_path": str(self.app / "x.py")}, self.plans))[0], 2)
        self.assertEqual(self.run_copy("Edit", {"file_path": str(self.app / "x.py")}), (0, "", ""))


class BrokenGateLib(PluginCopy):
    """Broken rules in lib/ can't stop the guard; the gate, unable to load them, allows."""
    gate_source = (ROOT / "hooks" / "gate.py").read_text()

    def setUp(self):
        super().setUp()
        (self.entry.parents[1] / "lib" / "speckled_gate" / "rules.py").write_text("raise RuntimeError('broken')\n")

    def test_guard_still_blocks(self):
        for cmd in ["rm -rf build", f"cd {self.app} && rm -rf build", 'bash -c "rm -rf x"']:
            with self.subTest(cmd=cmd):
                code, _, stderr = self.run_copy("Bash", {"command": cmd})
                self.assertEqual((code, stderr), (2, f"speckled guard: {guard.RM_MESSAGE}\n"))

    def test_edit_allowed(self):
        self.assertEqual(self.run_copy("Edit", {"file_path": str(self.app / "x.py")}), (0, "", ""))


class GuardLoadsOnlyTheTokenizer(unittest.TestCase):
    def test_modules_loaded(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from speckled_gate import shell; "
                "print(sorted(m for m in sys.modules if m.startswith('speckled_gate')))")
        out = subprocess.run([sys.executable, "-c", code, str(ROOT / "lib")], text=True, capture_output=True)
        self.assertEqual(out.stdout.strip(), "['speckled_gate', 'speckled_gate.shell']")

    def test_public_api_still_available(self):
        import speckled_gate
        from speckled_gate import project, rules
        self.assertIs(speckled_gate.find_project, project.find_project)
        self.assertIs(speckled_gate.decide, rules.decide)
        with self.assertRaises(AttributeError):
            speckled_gate.nothing_here


class ReadOnlyToolsSkipTheGate(PluginCopy):
    gate_source = ("import os\n"
                   "open(os.environ['GATE_IMPORTED'], 'a').close()\n"
                   "def run(payload, argv):\n"
                   "    return 0\n")

    def test_gate_never_imported(self):
        marker = self.tmp / "gate-imported"
        env = {"GATE_IMPORTED": str(marker)}
        for tool, tool_input in [("Read", {"file_path": str(self.app / "x.py")}),
                                 ("Grep", {"pattern": "x", "path": str(self.app)}),
                                 ("Glob", {"pattern": "**/*.py"})]:
            with self.subTest(tool=tool):
                self.assertEqual(self.run_copy(tool, tool_input, env), (0, "", ""))
                self.assertFalse(marker.exists())
        # The probe works: an Edit does import the gate.
        self.run_copy("Edit", {"file_path": str(self.app / "x.py")}, env)
        self.assertTrue(marker.exists())


class HooksJson(unittest.TestCase):
    def test_final_shape(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        self.assertEqual(len(config), 1)
        entry = config[0]
        self.assertEqual(entry["matcher"],
                         "Bash|PowerShell|Read|Edit|MultiEdit|Write|NotebookEdit|Grep|Glob|mcp__.*")
        self.assertEqual(len(entry["hooks"]), 1)
        hook = entry["hooks"][0]
        self.assertIn("hooks/pretooluse.py", hook["command"])
        self.assertIn('--plugin-data "${CLAUDE_PLUGIN_DATA}"', hook["command"])
        self.assertEqual(hook["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
