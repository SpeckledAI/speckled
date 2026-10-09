"""Tests for lib/speckled_gate/rules.py [T-F07-06]."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from speckled_gate.project import find_project, load_project
from speckled_gate.rules import actions_for, decide, message, ready_tasks

from .fixtures import make_project

CONFIG = """\
project: Acme
enforcement: block
repos:
  - ../app
enforcement_exempt:
  - "*.lock"
"""


def task_list(list_id, status, tasks):
    lines = ["---", f"id: {list_id}", "type: tasks", f"status: {status}", "version: 1", "---", "", "## Tasks", ""]
    for task_id, task_status, deps in tasks:
        lines += [f"### {task_id}: Example", f"- **Depends on:** {', '.join(deps) or 'none'}",
                  f"- **Status:** {task_status}", ""]
    return "\n".join(lines)


TASKS_F01 = task_list("TASKS-F01", "approved", [
    ("T-F01-01", "Done", []),
    ("T-F01-02", "In progress", ["T-F01-01"]),
    ("T-F01-03", "Todo", ["T-F01-01"]),
    ("T-F01-04", "In progress", ["T-F01-03"]),     # dependency not done
    ("T-F01-05", "In progress", ["T-F09-01"]),     # dependency missing
    ("T-F01-06", "In review", ["T-F01-01"]),
])
TASKS_F02 = task_list("TASKS-F02", "in-review", [("T-F02-01", "In progress", [])])


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(os.path.realpath(self._tmp.name))
        self.paths = make_project(self.tmp, CONFIG, code_repos=["app"], files={
            "plans/docs/tasks/F01.md": TASKS_F01, "plans/docs/tasks/F02.md": TASKS_F02})
        self.app, self.plans = self.paths.repos["app"], self.paths.root
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.plugin = self.tmp / "plugin"
        self.data = self.tmp / "plugin-data"

    def tearDown(self):
        self._tmp.cleanup()

    def project(self, active=None, plugin_root=None):
        if active:
            (self.plans / ".speckled").mkdir(exist_ok=True)
            (self.plans / ".speckled" / "active-task").write_text(json.dumps({"v": 1, "task": active}))
        return find_project(self.plans, plugin_root or self.plugin, self.data, self.home)

    def verdicts(self, project, tool, tool_input, cwd):
        return [decide(project, a) for a in actions_for(tool, tool_input, project, str(cwd))]

    def rule(self, project, tool, tool_input, cwd=None):
        """The first violated rule for this tool call, or None if it's allowed."""
        broken = [v.rule for v in self.verdicts(project, tool, tool_input, cwd or self.plans) if not v.ok]
        return broken[0] if broken else None


def edit(path):
    return ("Edit", {"file_path": str(path)})


def bash(command):
    return ("Bash", {"command": command})


class RuleTable(Fixture):
    """At least 20 allow/block cases (NFR7); every rule value in TDD-F07 §4 appears."""

    def rows(self):
        app, plans = self.app, self.plans
        return [
            # name, active task, (tool, input), cwd, expected rule (None = allowed)
            ("no active task", None, edit(app / "src/x.py"), plans, "no-active-task"),
            ("valid task in progress", "T-F01-02", edit(app / "src/x.py"), plans, None),
            ("valid task in review", "T-F01-06", edit(app / "src/x.py"), plans, None),
            ("task still Todo", "T-F01-03", edit(app / "src/x.py"), plans, "task-not-started"),
            ("task Done", "T-F01-01", edit(app / "src/x.py"), plans, "task-done"),
            ("dependency not done", "T-F01-04", edit(app / "src/x.py"), plans, "dependency-not-done"),
            ("dependency missing", "T-F01-05", edit(app / "src/x.py"), plans, "dependency-missing"),
            ("list not approved", "T-F02-01", edit(app / "src/x.py"), plans, "task-list-not-approved"),
            ("unknown active task", "T-F99-01", edit(app / "src/x.py"), plans, "no-active-task"),
            ("planning doc is free", None, edit(plans / "docs/frds/F01.md"), plans, None),
            ("approval edit in docs is free (FR9)", None, edit(plans / "docs/tasks/F01.md"), plans, None),
            ("file outside every repo", None, edit(self.tmp / "notes.txt"), plans, None),
            ("exempt file", None, edit(app / "poetry.lock"), plans, None),
            ("speckled.yaml protected", "T-F01-02", ("Write", {"file_path": str(plans / "speckled.yaml")}),
             plans, "protected-path"),
            ("active-task marker via shell", None, bash("echo x > .speckled/active-task"), plans,
             "protected-path"),
            ("settings protected", "T-F01-02", edit(app / ".claude/settings.json"), plans, "protected-path"),
            ("hooksPath change", None, bash("git config core.hooksPath /dev/null"), plans, "protected-path"),
            ("session without hooks", None, bash("claude --settings '{}' -p hi"), plans,
             "hooks-disabled-session"),
            ("git commit", "T-F01-02", bash("git commit -m wip"), app, "git-commit"),
            ("git push", "T-F01-02", bash("git push"), app, "git-push"),
            ("gh pr create", "T-F01-02", bash("gh pr create --fill"), app, "pull-request"),
            ("PowerShell commit", None, ("PowerShell", {"command": "git commit -m x"}), app, "git-commit"),
            ("MCP push", None, ("mcp__github__push_files", {}), plans, "git-push"),
            ("MCP pull request", None, ("mcp__github__create_pull_request", {}), plans, "pull-request"),
            ("other MCP tool", None, ("mcp__memory__create_entities", {}), plans, None),
            ("NotebookEdit", None, ("NotebookEdit", {"notebook_path": str(app / "nb.ipynb")}), plans,
             "no-active-task"),
            ("sed -i in code", None, bash("sed -i 's/a/b/' src/x.py"), app, "no-active-task"),
            ("cd into code then write", None, bash("cd ../app && touch y.py"), plans, "no-active-task"),
            ("repo-wide reset", None, bash("git reset --hard"), app, "no-active-task"),
            ("find -delete in code", None, bash("find . -name '*.pyc' -delete"), app, "no-active-task"),
            ("unknown target from substitution", None, bash("cp a.py $(pwd)/b.py"), plans, "no-active-task"),
            ("shell write with valid task", "T-F01-02", bash("sed -i 's/a/b/' src/x.py"), app, None),
            ("read-only shell", None, bash("ls -la && git status"), app, None),
            ("guard's business, not the gate's", None, bash("cat .env"), app, None),
        ]

    def test_table(self):
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 20)
        for name, active, (tool, tool_input), cwd, expected in rows:
            with self.subTest(name):
                marker = self.plans / ".speckled" / "active-task"
                if marker.exists():
                    marker.unlink()
                project = self.project(active)
                self.assertEqual(self.rule(project, tool, tool_input, cwd), expected)

    def test_wrong_start_folder(self):
        project = self.project("T-F01-02")
        project.wrong_start = self.app
        self.assertEqual(self.rule(project, *edit(self.app / "src/x.py")), "wrong-start-folder")
        self.assertEqual(self.rule(project, *edit(self.plans / "speckled.yaml")), "wrong-start-folder")
        self.assertIsNone(self.rule(project, *edit(self.plans / "docs/frds/F01.md")))

    def test_config_unreadable(self):
        (self.plans / "speckled.yaml").write_text("enforcement: block\nrepos: [../app\n")
        project = self.project()
        self.assertEqual(self.rule(project, *edit(self.app / "src/x.py")), "config-unreadable")
        self.assertIsNone(self.rule(project, *edit(self.plans / "docs/frds/F01.md")))

    def test_broken_task_list(self):
        (self.plans / "docs/tasks/F03.md").write_text(task_list("TASKS-F03", "approved",
                                                                [("T-F03-01", "Doing", [])]))
        self.assertEqual(self.rule(self.project("T-F01-02"), *edit(self.app / "src/x.py")),
                         "config-unreadable")

    def test_dogfooding_layout(self):
        project = self.project("T-F01-02", plugin_root=self.app)
        self.assertEqual(self.rule(project, *edit(self.app / "hooks/hooks.json")), "protected-path")
        self.assertIsNone(self.rule(project, *edit(self.app / "lib/x.py")))

    def test_enforcement_off_allows_everything(self):
        (self.plans / "speckled.yaml").write_text("enforcement: off\nrepos: [../app]\n")
        project = self.project()
        self.assertIsNone(self.rule(project, *edit(self.app / "src/x.py")))
        self.assertIsNone(self.rule(project, *bash("git push")))

    def test_decide_and_message_write_nothing(self):
        before = sorted(p for p in self.tmp.rglob("*"))
        project = self.project()
        for tool, tool_input in [edit(self.app / "x.py"), bash("git push"), edit(self.plans / "speckled.yaml")]:
            for v in self.verdicts(project, tool, tool_input, self.plans):
                if not v.ok:
                    message(v, "warn", project)
                    message(v, "block", project)
        self.assertEqual(sorted(p for p in self.tmp.rglob("*")), before)


class Messages(Fixture):
    def violations(self):
        """One violation for every rule value, with the project it came from."""
        app, plans = self.app, self.plans
        cases = [(None, edit(app / "x.py")), ("T-F01-03", edit(app / "x.py")), ("T-F01-01", edit(app / "x.py")),
                 ("T-F01-04", edit(app / "x.py")), ("T-F01-05", edit(app / "x.py")),
                 ("T-F02-01", edit(app / "x.py")), (None, edit(plans / "speckled.yaml")),
                 (None, bash("claude --settings x")), (None, bash("git commit -m x")),
                 (None, bash("git push")), (None, bash("gh pr create"))]
        out = []
        for active, (tool, tool_input) in cases:
            marker = plans / ".speckled" / "active-task"
            if marker.exists():
                marker.unlink()
            project = self.project(active)
            out += [(v, project) for v in self.verdicts(project, tool, tool_input, plans) if not v.ok]
        wrong = self.project("T-F01-02")
        wrong.wrong_start = app
        out += [(v, wrong) for v in self.verdicts(wrong, *edit(app / "x.py"), plans)]
        (plans / "speckled.yaml").write_text("enforcement: block\nrepos: [../app\n")
        broken = self.project()
        out += [(v, broken) for v in self.verdicts(broken, *edit(app / "x.py"), plans)]
        return out

    def test_every_rule_has_a_three_line_message(self):
        seen = set()
        for verdict, project in self.violations():
            seen.add(verdict.rule)
            for mode, first, last in [("block", "speckled: blocked: ", "To bypass, a human can set enforcement: warn"),
                                      ("warn", "speckled (warn): would block: ", "Allowed and logged.")]:
                with self.subTest(rule=verdict.rule, mode=mode):
                    lines = message(verdict, mode, project).split("\n")
                    self.assertEqual(len(lines), 3)
                    self.assertTrue(lines[0].startswith(first))
                    self.assertTrue(lines[1].strip())
                    self.assertTrue(lines[2].startswith(last))
        self.assertEqual(seen, {"no-active-task", "task-not-started", "task-done", "dependency-not-done",
                                "dependency-missing", "task-list-not-approved", "protected-path",
                                "hooks-disabled-session", "git-commit", "git-push", "pull-request",
                                "wrong-start-folder", "config-unreadable"})

    def test_ready_task_hint(self):
        project = self.project()
        self.assertEqual(ready_tasks(project), ["T-F01-02", "T-F01-03"])
        v = [x for x in self.verdicts(project, *edit(self.app / "src/x.py"), self.plans) if not x.ok][0]
        lines = message(v, "block", project).split("\n")
        self.assertEqual(lines[0], "speckled: blocked: no active task for src/x.py (in ../app).")
        self.assertEqual(lines[1], "Ready to start: T-F01-02, T-F01-03. Run /speckled:build <task-id>.")

    def test_wrong_start_message_has_real_paths(self):
        project = self.project()
        project.wrong_start = self.app
        v = [x for x in self.verdicts(project, *edit(self.app / "x.py"), self.app) if not x.ok][0]
        self.assertIn(f"cd {self.plans} && claude --add-dir ../app", message(v, "block", project))

    def test_list_not_approved_names_the_command(self):
        project = self.project("T-F02-01")
        v = [x for x in self.verdicts(project, *edit(self.app / "x.py"), self.plans) if not x.ok][0]
        self.assertIn("/speckled:approve TASKS-F02", message(v, "block", project))


if __name__ == "__main__":
    unittest.main()
