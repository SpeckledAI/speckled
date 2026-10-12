"""Tests for task activation: rules.activate and `speckled-gate activate` [T-F07-09]."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from speckled_gate.cli import main
from speckled_gate.rules import actions_for, activate, decide, validate_task

# Imported as a module so unittest doesn't collect (and re-run) its test classes here.
from . import test_rules

BUILD_SKILL = Path(__file__).resolve().parents[2] / "skills" / "build" / "SKILL.md"


class Activate(test_rules.Fixture):
    @property
    def marker(self):
        return self.plans / ".speckled" / "active-task"

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["activate", *argv, "--project", str(self.plans), "--cwd", str(self.plans),
                         "--plugin-root", str(self.plugin), "--plugin-data", str(self.data)])
        return code, out.getvalue(), err.getvalue()

    def test_in_progress_task_in_an_approved_list(self):
        code, out, _ = self.cli("T-F01-02")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "Active task: T-F01-02 (TASKS-F01 v1, approved)")
        data = json.loads(self.marker.read_text())
        self.assertEqual((data["v"], data["task"]), (1, "T-F01-02"))
        self.assertRegex(data["activated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("by", data)
        self.assertEqual((self.plans / ".speckled" / ".gitignore").read_text(), "active-task\n*.tmp\n")
        self.assertFalse((self.plans / ".speckled" / "active-task.tmp").exists())

    def test_in_review_task(self):
        self.assertEqual(self.cli("T-F01-06")[0], 0)

    def test_running_it_again_is_fine(self):
        self.assertEqual(self.cli("T-F01-02")[0], 0)
        self.assertEqual(self.cli("T-F01-02")[0], 0)
        self.assertEqual(json.loads(self.marker.read_text())["task"], "T-F01-02")

    def test_refusals_leave_the_marker_unchanged(self):
        self.cli("T-F01-02")
        before = self.marker.read_text()
        for task, rule in [("T-F01-03", "task-not-started"), ("T-F01-01", "task-done"),
                           ("T-F02-01", "task-list-not-approved"), ("T-F01-04", "dependency-not-done"),
                           ("T-F01-05", "dependency-missing"), ("T-F99-01", "no-active-task")]:
            with self.subTest(task=task):
                code, out, err = self.cli(task)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith(f"Not activated ({rule}): "), err)
                self.assertEqual(len(err.strip().split("\n")), 2)  # the reason, then the next step
                self.assertEqual(self.marker.read_text(), before)

    def test_refusal_without_a_marker_creates_none(self):
        self.assertEqual(self.cli("T-F01-03")[0], 1)
        self.assertFalse(self.marker.exists())

    def test_no_project(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main(["activate", "T-F01-02", "--cwd", str(elsewhere), "--plugin-data", str(self.data)])
        self.assertEqual(code, 1)
        self.assertIn("No Speckled project found", err.getvalue())

    def test_works_with_enforcement_off_and_a_custom_docs_dir(self):
        (self.plans / "docs").rename(self.plans / "plans-docs")
        (self.plans / "speckled.yaml").write_text("enforcement: off\ndocs_dir: plans-docs\nrepos: [../app]\n")
        self.assertEqual(self.cli("T-F01-02")[0], 0)


class SharedValidation(test_rules.Fixture):
    def test_activate_and_decide_agree(self):
        """activate() and a governed edit give the same answer for every task (one check)."""
        project = self.project()
        edit = actions_for("Edit", {"file_path": str(self.app / "x.py")}, project, str(self.plans))[0]
        for task in ["T-F01-01", "T-F01-02", "T-F01-03", "T-F01-04", "T-F01-05", "T-F01-06",
                     "T-F02-01", "T-F99-01"]:
            with self.subTest(task=task):
                (self.plans / ".speckled").mkdir(exist_ok=True)
                self.marker_write(task)
                self.assertEqual(decide(project, edit).rule, validate_task(project, task).rule)
                self.assertEqual(activate(project, task).rule, validate_task(project, task).rule)

    def marker_write(self, task):
        (self.plans / ".speckled" / "active-task").write_text(json.dumps({"v": 1, "task": task}))


class Story11(test_rules.Fixture):
    """FRD-F07 story 11: edits stop once the active task is Done."""

    def test_edit_allowed_then_blocked_after_done(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F01-02").ok)
        edit = actions_for("Edit", {"file_path": str(self.app / "src" / "x.py")}, project, str(self.plans))[0]
        self.assertTrue(decide(project, edit).ok)

        tasks = self.plans / "docs" / "tasks" / "F01.md"
        text = tasks.read_text()
        start = text.index("### T-F01-02")
        tasks.write_text(text[:start] + text[start:].replace("- **Status:** In progress", "- **Status:** Done", 1))
        self.assertEqual(decide(project, edit).rule, "task-done")


class BuildSkill(test_rules.Fixture):
    def test_build_runs_activate_and_stops_on_failure(self):
        text = BUILD_SKILL.read_text()
        step = text[text.index("3. **Activate the task.**"):text.index("4. **Load context.**")]
        self.assertIn("`In progress`", step)
        self.assertIn("../../bin/speckled-gate activate <task-id>", step)
        self.assertIn("If it fails, set the status back", step)
        self.assertIn("stop", step)
        self.assertLess(text.index("2. **Check the gate.**"), text.index("3. **Activate the task.**"))
