"""Tests for hooks/guard.py. Run with: python3 -m unittest discover tests"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def run(payload) -> int:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(GUARD)], input=data, text=True, capture_output=True).returncode


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def file_tool(tool: str, path: str) -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


class BlocksDangerousCalls(unittest.TestCase):
    def test_recursive_force_delete(self):
        for cmd in ["rm -rf build", "npm test && rm -fr /tmp/x", "rm --recursive --force x",
                    "rm -r -f x", "sudo rm -Rf /", "FOO=1 /bin/rm -rf dir"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 2)

    def test_secret_env_in_shell(self):
        for cmd in ["cat .env", "cp .env.example .env.local", "source ./.env && npm start"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 2)

    def test_secret_env_file_tools(self):
        for tool in ["Read", "Edit", "MultiEdit", "Write"]:
            for path in ["/p/.env", "/p/.env.production"]:
                with self.subTest(tool=tool, path=path):
                    self.assertEqual(run(file_tool(tool, path)), 2)


class AllowsSafeCalls(unittest.TestCase):
    def test_safe_shell(self):
        for cmd in ["rm file.txt", "rm -r dir", 'git commit -m "rm -rf docs mention"',
                    "cat .env.example", "grep -r environment src", "ls -la"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(bash(cmd)), 0)

    def test_safe_files(self):
        for path in ["/p/.env.sample", "/p/.env.example", "/p/.env.template", "/p/src/env.ts", "/p/.envrc.md"]:
            with self.subTest(path=path):
                self.assertEqual(run(file_tool("Read", path)), 0)

    def test_fails_open_on_bad_input(self):
        self.assertEqual(run("not json"), 0)
        self.assertEqual(run({"tool_name": "Bash"}), 0)


if __name__ == "__main__":
    unittest.main()
