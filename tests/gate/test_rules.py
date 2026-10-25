"""Tests for lib/speckled_gate/rules.py [T-F07-06]."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from speckled_gate.docs import find_task, load_task_lists
from speckled_gate.project import find_project, load_project
from speckled_gate.rules import (HARD_RULES, OK, Action, Verdict, actions_for, decide, first_to_show, message,
                                 outcome, ready_tasks)

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

    def project(self, active=None, plugin_root=None, files=None):
        """The fixture project; `active` writes the marker, with `files` if given."""
        if active:
            (self.plans / ".speckled").mkdir(exist_ok=True)
            marker = {"v": 1, "task": active, **({"files": files} if files else {})}
            (self.plans / ".speckled" / "active-task").write_text(json.dumps(marker))
        return find_project(self.plans, plugin_root or self.plugin, self.data, self.home)

    def verdicts(self, project, tool, tool_input, cwd):
        return [decide(project, a) for a in actions_for(tool, tool_input, project, str(cwd))]

    def rule(self, project, tool, tool_input, cwd=None):
        """The first violated rule for this tool call, or None if it's allowed."""
        broken = [v.rule for v in self.verdicts(project, tool, tool_input, cwd or self.plans) if not v.ok]
        return broken[0] if broken else None


def pointer_files(fixture, task_id):
    """The files `activate` would record for `task_id` (lists holding it and its known deps)."""
    if not task_id:
        return None
    docs = fixture.plans / "docs"
    lists = load_task_lists(docs)
    found = find_task(lists, task_id)
    if found is None:
        return None
    holders = [found[0]] + [f[0] for f in (find_task(lists, d) for d in found[1].depends_on) if f]
    return list(dict.fromkeys(Path(os.path.relpath(t.path, docs)).as_posix() for t in holders))


def edit(path):
    return ("Edit", {"file_path": str(path)})


def bash(command):
    return ("Bash", {"command": command})


class RuleTable(Fixture):
    """At least 20 allow/block cases; every rule value the gate can report appears."""

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
            ("approval edit in docs is free", None, edit(plans / "docs/tasks/F01.md"), plans, None),
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

    def test_same_verdicts_with_the_task_pointer(self):
        """Recorded task-list files never change a verdict [T-F07-16]."""
        for name, active, (tool, tool_input), cwd, expected in self.rows():
            with self.subTest(name):
                marker = self.plans / ".speckled" / "active-task"
                if marker.exists():
                    marker.unlink()
                self.assertEqual(self.rule(self.project(active, files=pointer_files(self, active)),
                                           tool, tool_input, cwd), expected)

    def test_wrong_start_folder(self):
        project = self.project("T-F01-02")
        project.wrong_start = self.app
        self.assertEqual(self.rule(project, *edit(self.app / "src/x.py")), "wrong-start-folder")
        # Hard rules come first, so warn mode can't let this through [T-F07-19].
        self.assertEqual(self.rule(project, *edit(self.plans / "speckled.yaml")), "protected-path")
        self.assertEqual(self.rule(project, *bash("git commit -m x"), self.app), "git-commit")
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

    def test_kind_and_outcome_for_every_row(self):
        """Hard rules block in both modes; task rules warn in warn [T-F07-19]."""
        for name, active, (tool, tool_input), cwd, expected in self.rows():
            with self.subTest(name):
                marker = self.plans / ".speckled" / "active-task"
                if marker.exists():
                    marker.unlink()
                verdicts = self.verdicts(self.project(active), tool, tool_input, cwd)
                if expected is None:
                    self.assertEqual((outcome("warn", verdicts), outcome("block", verdicts)), ("ok", "ok"))
                    continue
                hard = expected in HARD_RULES
                self.assertEqual(first_to_show(verdicts).hard, hard)
                self.assertEqual(outcome("block", verdicts), "block")
                self.assertEqual(outcome("warn", verdicts), "block" if hard else "warn")

    def test_hard_rules(self):
        self.assertEqual(HARD_RULES, {"protected-path", "hooks-disabled-session", "git-commit", "git-push",
                                      "pull-request", "config-unreadable"})

    def test_mixed_violations(self):
        """A hard violation decides the outcome and the message, wherever it is [T-F07-19]."""
        project = self.project()
        task = Verdict("no-active-task", Action("write", str(self.app / "x.py"), "Bash"))
        hard = Verdict("git-commit", Action("git-commit", None, "Bash"))
        self.assertEqual(outcome("warn", [task, hard]), "block")
        self.assertIs(first_to_show([task, hard]), hard)
        self.assertIs(first_to_show([task, OK]), task)
        self.assertEqual(outcome("warn", [task, OK]), "warn")
        self.assertEqual(outcome("warn", [OK]), "ok")
        shown = message(first_to_show([task, hard]), outcome("warn", [task, hard]), project)
        self.assertTrue(shown.startswith("speckled: blocked: "))
        self.assertNotIn("enforcement: warn", shown)

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

    def test_every_rule_has_a_message(self):
        """Task rules: three lines. Blocked hard rules: two, never suggesting warn [T-F07-19]."""
        seen = set()
        for verdict, project in self.violations():
            seen.add(verdict.rule)
            for mode, first, last in [("block", "speckled: blocked: ", "To bypass, a human can set enforcement: warn"),
                                      ("warn", "speckled (warn): would block: ", "Allowed and logged.")]:
                with self.subTest(rule=verdict.rule, mode=mode):
                    if verdict.hard and mode == "warn":
                        continue  # never shown: outcome() blocks a hard rule in warn mode
                    text = message(verdict, mode, project)
                    lines = text.split("\n")
                    self.assertTrue(lines[1].strip())
                    if verdict.hard:
                        self.assertEqual(len(lines), 2)
                        self.assertTrue(lines[0].startswith("speckled: blocked: "))
                        self.assertNotIn("enforcement: warn", text)
                    else:
                        self.assertEqual(len(lines), 3)
                        self.assertTrue(lines[0].startswith(first))
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
