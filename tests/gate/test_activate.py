"""Tests for task activation: rules.activate and `speckled-gate activate` [T-F07-09]."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from speckled_gate.cli import main
from speckled_gate.rules import actions_for, activate, active_marker, decide, validate_task

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
    """Edits stop once the active task is Done."""

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


class TaskPointer(test_rules.Fixture):
    """The task-list files recorded at activation [T-F07-16]."""

    F03 = test_rules.task_list("TASKS-F03", "approved", [
        ("T-F03-01", "Done", []),
        ("T-F03-02", "In progress", ["T-F03-01", "T-F01-01"]),
    ])

    def setUp(self):
        super().setUp()
        self.tasks = self.plans / "docs" / "tasks"
        (self.tasks / "F03.md").write_text(self.F03)

    def files(self):
        return json.loads((self.plans / ".speckled" / "active-task").read_text())["files"]

    def edit_rule(self, project):
        action = actions_for("Edit", {"file_path": str(self.app / "src" / "x.py")}, project, str(self.plans))[0]
        return decide(project, action).rule

    def test_records_the_list_holding_the_task(self):
        self.assertTrue(activate(self.project(), "T-F01-02").ok)
        self.assertEqual(self.files(), ["tasks/F01.md"])

    def test_records_dependency_lists_once_each(self):
        self.assertTrue(activate(self.project(), "T-F03-02").ok)
        self.assertEqual(self.files(), ["tasks/F03.md", "tasks/F01.md"])

    def test_unrelated_broken_list_is_not_read(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F01-02").ok)
        (self.tasks / "F09.md").write_text(test_rules.task_list("TASKS-F09", "approved", [("T-F09-01", "Doing", [])]))
        self.assertIsNone(self.edit_rule(project))
        # Without the pointer, every list is read, and the broken one blocks.
        self.marker_without_files()
        self.assertEqual(self.edit_rule(project), "config-unreadable")

    def test_broken_recorded_list_blocks(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F01-02").ok)
        text = (self.tasks / "F01.md").read_text()
        (self.tasks / "F01.md").write_text(text.replace("- **Status:** Todo", "- **Status:** Doing", 1))
        self.assertEqual(self.edit_rule(project), "config-unreadable")

    def test_list_moved_to_completed(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F01-02").ok)
        (self.tasks / "completed").mkdir()
        (self.tasks / "F01.md").rename(self.tasks / "completed" / "F01.md")
        self.assertIsNone(self.edit_rule(project))
        self.set_status(self.tasks / "completed" / "F01.md", "T-F01-02", "Done")
        self.assertEqual(self.edit_rule(project), "task-done")

    def test_dependency_moved_to_another_list(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F03-02").ok)
        f01 = (self.tasks / "F01.md").read_text()
        start = f01.index("### T-F01-01")
        end = f01.index("### T-F01-02")
        (self.tasks / "F01.md").write_text(f01[:start] + f01[end:])
        (self.tasks / "F04.md").write_text(test_rules.task_list("TASKS-F04", "approved", [("T-F01-01", "Done", [])]))
        self.assertIsNone(self.edit_rule(project))
        self.set_status(self.tasks / "F04.md", "T-F01-01", "In review")
        self.assertEqual(self.edit_rule(project), "dependency-not-done")

    def test_recorded_file_deleted(self):
        project = self.project()
        self.assertTrue(activate(project, "T-F03-02").ok)
        (self.tasks / "F01.md").unlink()
        self.assertEqual(self.edit_rule(project), "dependency-missing")

    def test_malformed_files_are_ignored(self):
        project = self.project()
        for files in [["../F01.md"], ["/tmp/F01.md"], ["tasks/../../x.md"], [7], "tasks/F01.md", [],
                      ["docs/tasks/F01.md"]]:
            with self.subTest(files=files):
                self.write_marker("T-F01-02", files)
                self.assertEqual(active_marker(project), ("T-F01-02", None))
                self.assertIsNone(self.edit_rule(project))

    def test_marker_without_files_still_works(self):
        project = self.project()
        self.write_marker("T-F01-02", None)
        self.assertEqual(active_marker(project), ("T-F01-02", None))
        self.assertIsNone(self.edit_rule(project))

    # helpers

    def write_marker(self, task, files):
        (self.plans / ".speckled").mkdir(exist_ok=True)
        data = {"v": 1, "task": task, **({} if files is None else {"files": files})}
        (self.plans / ".speckled" / "active-task").write_text(json.dumps(data))

    def marker_without_files(self):
        data = json.loads((self.plans / ".speckled" / "active-task").read_text())
        data.pop("files")
        (self.plans / ".speckled" / "active-task").write_text(json.dumps(data))

    def set_status(self, path, task, status):
        text = path.read_text()
        start = text.index(f"### {task}")
        rest = text[start:]
        line = next(l for l in rest.splitlines() if l.startswith("- **Status:**"))
        path.write_text(text[:start] + rest.replace(line, f"- **Status:** {status}", 1))
