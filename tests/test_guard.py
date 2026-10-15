"""Tests for hooks/guard.py. Run with: python3 -m unittest discover tests"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def run(payload, guard=GUARD, cwd=None) -> int:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(guard)], input=data, text=True, capture_output=True,
                          cwd=cwd).returncode


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def file_tool(tool: str, path: str) -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def tool(name: str, **tool_input) -> dict:
    return {"tool_name": name, "tool_input": tool_input}


BLOCKED = [bash("rm -rf build"), bash('bash -c "rm -rf x"'), bash("cat .env"),
           tool("Grep", pattern="KEY", path="/p/.env"), tool("Glob", pattern="**/.env.production")]
ALLOWED = [bash('echo "copy .env.example to .env"'), bash("rm -r dir"),
           tool("Grep", pattern="KEY", path="src/", glob="*.ts"), file_tool("Read", "/p/.env.example")]


class BlocksDangerousCalls(unittest.TestCase):
    def test_recursive_force_delete(self):
        for cmd in ["rm -rf build", "npm test && rm -fr /tmp/x", "rm --recursive --force x",
                    "rm -r -f x", "sudo rm -Rf /", "FOO=1 /bin/rm -rf dir",
                    'bash -c "rm -rf x"', "ls | xargs rm -rf", "find . -delete"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 2)

    def test_secret_env_in_shell(self):
        for cmd in ["cat .env", "cp .env.example .env.local", "source ./.env && npm start"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 2)

    def test_powershell(self):
        for cmd in ["rm -rf build", "Get-Content .env"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run({"tool_name": "PowerShell", "tool_input": {"command": cmd}}), 2)

    def test_secret_env_file_tools(self):
        for tool_name in ["Read", "Edit", "MultiEdit", "Write"]:
            for path in ["/p/.env", "/p/.env.production"]:
                with self.subTest(tool=tool_name, path=path):
                    self.assertEqual(run(file_tool(tool_name, path)), 2)

    def test_secret_env_search_and_notebook_tools(self):
        for payload in [tool("Grep", pattern="KEY", path="/p/.env"),
                        tool("Grep", pattern="KEY", path=".env.local"),
                        tool("Grep", pattern="KEY", glob=".env*"),
                        tool("Grep", pattern="KEY", glob="{.env,*.ts}"),
                        tool("Glob", pattern="**/.env.production"),
                        tool("Glob", pattern=".env"),
                        tool("NotebookEdit", notebook_path="/p/.env", new_source="x")]:
            with self.subTest(payload=payload):
                self.assertEqual(run(payload), 2)


class AllowsSafeCalls(unittest.TestCase):
    def test_safe_shell(self):
        for cmd in ["rm file.txt", "rm -r dir", 'git commit -m "rm -rf docs mention"',
                    "cat .env.example", "grep -r environment src", "ls -la",
                    'echo "copy .env.example to .env"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 0)

    def test_safe_files(self):
        for path in ["/p/.env.sample", "/p/.env.example", "/p/.env.template", "/p/.env.dist",
                     "/p/src/env.ts", "/p/.envrc.md"]:
            with self.subTest(path=path):
                self.assertEqual(run(file_tool("Read", path)), 0)

    def test_safe_search_and_notebook_tools(self):
        for payload in [tool("Grep", pattern="KEY", path="src/", glob="*.ts"),
                        tool("Grep", pattern="KEY", glob=".env.example"),
                        tool("Grep", pattern="KEY"),
                        tool("Glob", pattern="**/*.ts"),
                        tool("Glob", pattern="**/.env.sample"),
                        tool("NotebookEdit", notebook_path="/p/analysis.ipynb", new_source="x")]:
            with self.subTest(payload=payload):
                self.assertEqual(run(payload), 0)

    def test_fails_open_on_bad_input(self):
        self.assertEqual(run("not json"), 0)
        self.assertEqual(run({"tool_name": "Bash"}), 0)


class IndependentOfEnforcement(unittest.TestCase):
    """The guard gives the same answers inside a project, whatever its enforcement mode (NFR6)."""

    def test_same_results_with_enforcement_on_or_off(self):
        for mode in ["block", "warn", "off"]:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / ".git").mkdir()
                (Path(tmp) / "speckled.yaml").write_text(f"enforcement: {mode}\nrepos: [.]\n")
                for payload in BLOCKED:
                    with self.subTest(mode=mode, payload=payload):
                        self.assertEqual(run({**payload, "cwd": tmp}, cwd=tmp), 2)
                for payload in ALLOWED:
                    with self.subTest(mode=mode, payload=payload):
                        self.assertEqual(run({**payload, "cwd": tmp}, cwd=tmp), 0)


RM_RF = ["rm -rf build", "sudo rm -Rf /", "rm --recursive --force x", 'bash -c "rm -rf x"',
         "ls | xargs rm -rf", "npm test && rm -fr /tmp/x", "find . -delete", "echo $(rm -rf x)"]


class WithoutLib(unittest.TestCase):
    """A copy of guard.py with no lib/ beside it: rm -rf is still blocked, nothing crashes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        hooks = Path(self._tmp.name) / "hooks"
        hooks.mkdir()
        self.guard = hooks / "guard.py"
        shutil.copy(GUARD, self.guard)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rm_rf_still_blocked(self):
        for cmd in RM_RF:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd), guard=self.guard), 2)

    def test_other_shell_commands_allowed(self):
        for cmd in ["cat .env", "rm -r dir", "ls -la"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd), guard=self.guard), 0)

    def test_path_checks_still_apply(self):
        self.assertEqual(run(file_tool("Read", "/p/.env"), guard=self.guard), 2)
        self.assertEqual(run(tool("Grep", pattern="KEY", path="/p/.env"), guard=self.guard), 2)


class BrokenLib(unittest.TestCase):
    """A copy of the plugin with broken gate code: the guard still never allows rm -rf."""

    def make_copy(self, broken: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        copy = Path(tmp.name)
        shutil.copytree(GUARD.parent, copy / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(GUARD.parents[1] / "lib", copy / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        for rel, source in broken.items():
            (copy / "lib" / "speckled_gate" / rel).write_text(source)
        return copy / "hooks" / "guard.py"

    def test_broken_rules_and_yaml_dont_matter(self):
        # The guard loads only the tokenizer, so it still analyses commands in full.
        guard = self.make_copy({"rules.py": "raise RuntimeError('broken')\n",
                                "project.py": "raise RuntimeError('broken')\n",
                                "yamlio.py": "raise RuntimeError('broken')\n"})
        for payload, expected in [*[(p, 2) for p in BLOCKED], *[(p, 0) for p in ALLOWED]]:
            with self.subTest(payload=payload):
                self.assertEqual(run(payload, guard=guard), expected)

    def test_tokenizer_that_fails(self):
        guard = self.make_copy({"shell.py": "def actions(command):\n    raise RuntimeError('broken')\n"})
        for cmd in RM_RF:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd), guard=guard), 2)
        self.assertEqual(run(bash("ls -la"), guard=guard), 0)

    def test_tokenizer_that_cant_be_imported(self):
        guard = self.make_copy({"shell.py": "raise ImportError('broken')\n"})
        for cmd in RM_RF:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd), guard=guard), 2)


if __name__ == "__main__":
    unittest.main()
