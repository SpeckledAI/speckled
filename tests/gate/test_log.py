"""Tests for lib/speckled_gate/log.py [T-F07-06]."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from speckled_gate import log
from speckled_gate.project import find_project

from .fixtures import make_project

CONFIG = "project: Acme\nenforcement: warn\nrepos:\n  - ../app\n"
V1_FIELDS = {"v", "ts", "mode", "by", "tool", "repo", "paths", "task", "rule", "agent"}


class Log(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(os.path.realpath(self._tmp.name))
        self.paths = make_project(self.tmp, CONFIG, code_repos=["app"])
        self.project = find_project(self.paths.root, self.tmp / "plugin", self.tmp / "data", self.tmp)
        self.file = self.paths.root / ".speckled" / "log.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def entry(self, paths, **kw):
        args = dict(mode="warn", rule="no-active-task", tool="Bash", task=None, by="alice", agent="main")
        args.update(kw)
        return log.entry(self.project, paths=[str(p) for p in paths], **args)

    def test_entry_has_exactly_the_v1_fields(self):
        e = self.entry([self.paths.repos["app"] / "src" / "x.py"], task="T-F01-02", agent="Explore")
        self.assertEqual(set(e), V1_FIELDS)
        self.assertEqual((e["v"], e["mode"], e["by"], e["tool"], e["repo"], e["paths"], e["task"],
                          e["rule"], e["agent"]),
                         (1, "warn", "alice", "Bash", "../app", ["src/x.py"], "T-F01-02",
                          "no-active-task", "Explore"))
        self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_no_absolute_paths_or_command_text(self):
        command = "sed -i 's/password=hunter2/x/' src/x.py"
        home = self.tmp / "home"
        home.mkdir()
        self.project.home = home
        e = self.entry([self.paths.repos["app"] / "src" / "x.py", self.paths.root / "speckled.yaml",
                        home / ".claude" / "settings.json", "/opt/elsewhere/tool.cfg"])
        text = json.dumps(e)
        self.assertNotIn(str(self.tmp), text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn(command, text)
        self.assertEqual(e["paths"], ["src/x.py", "speckled.yaml", "~/.claude/settings.json", "tool.cfg"])

    def test_planning_repo_paths(self):
        e = self.entry([self.paths.root / "docs" / "x.md"])
        self.assertEqual((e["repo"], e["paths"]), (".", ["docs/x.md"]))

    def test_git_actions_have_no_paths(self):
        e = self.entry([], rule="git-push")
        self.assertEqual((e["repo"], e["paths"]), ("", []))

    def test_two_appends_give_two_lines(self):
        log.append(self.project, self.entry([], rule="git-push"))
        log.append(self.project, self.entry([], rule="git-commit"))
        lines = self.file.read_text().splitlines()
        self.assertEqual([json.loads(l)["rule"] for l in lines], ["git-push", "git-commit"])

    def test_gitignore_is_created(self):
        log.append(self.project, self.entry([]))
        self.assertEqual((self.paths.root / ".speckled" / ".gitignore").read_text(), "active-task\n*.tmp\n")

    def test_existing_gitignore_is_kept(self):
        (self.paths.root / ".speckled").mkdir()
        (self.paths.root / ".speckled" / ".gitignore").write_text("custom\n")
        log.append(self.project, self.entry([]))
        self.assertEqual((self.paths.root / ".speckled" / ".gitignore").read_text(), "custom\n")

    def test_long_path_lists_are_capped(self):
        many = [self.paths.repos["app"] / f"f{i}.py" for i in range(100)]
        e = self.entry(many)
        self.assertEqual(len(e["paths"]), 20)
        self.assertLess(len(json.dumps(e)), 4096)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores permissions")
    def test_append_raises_when_it_cannot_write(self):
        (self.paths.root / ".speckled").mkdir()
        os.chmod(self.paths.root / ".speckled", 0o500)
        try:
            with self.assertRaises(OSError):
                log.append(self.project, self.entry([]))
        finally:
            os.chmod(self.paths.root / ".speckled", 0o700)

    def test_git_user(self):
        self.assertIsInstance(log.git_user(self.tmp), str)


if __name__ == "__main__":
    unittest.main()
