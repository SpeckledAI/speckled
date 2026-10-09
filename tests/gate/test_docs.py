"""Tests for lib/speckled_gate/docs.py [T-F07-03]."""
import tempfile
import unittest
from pathlib import Path

from speckled_gate.docs import DocError, find_task, front_matter, load_task_lists, parse_task_list
from speckled_gate.yamlio import YamlError

# The dependency graph of a real 15-task list (TASKS-F07), with generic titles.
GRAPH = {
    1: [], 2: [], 3: [2], 4: [2], 5: [2], 6: [3, 4, 5], 7: [6], 8: [1, 6, 7],
    9: [7], 10: [4, 8], 11: [3, 7], 12: [11], 13: [8, 9, 12], 14: [8], 15: [13, 14],
}


def tid(n: int) -> str:
    return f"T-F07-{n:02d}"


def task_list_text(statuses=None) -> str:
    """A task list in the strict format, shaped like a real one."""
    statuses = statuses or {}
    parts = ["---", "id: TASKS-F07", "title: Example Feature", "type: tasks", "feature: F07",
             "parent: TDD-F07", "parent_version: 2", "status: approved", "version: 2",
             "updated: 2026-10-08", "approvals:",
             "  - {by: alice, role: tasks, date: 2026-10-08, version: 2}", "---", "",
             "# TASKS-F07: Example Feature", "", "## Overview", "",
             "| Task | Title | Depends on | Status |", "|---|---|---|---|"]
    parts += [f"| {tid(n)} | Task {n} | - | Todo |" for n in GRAPH]
    parts += ["", "## Tasks", ""]
    for n, deps in GRAPH.items():
        parts += [f"### {tid(n)}: Task {n}",
                  "- **Owner:** agent",
                  f"- **Depends on:** {', '.join(tid(d) for d in deps) or 'none'}",
                  f"- **Status:** {statuses.get(n, 'Todo')}", ""]
        if statuses.get(n) == "Done":
            parts += ["Approved by alice on 2026-10-08", ""]
        parts += ["**Steps**", "1. Do the thing.", ""]
    parts += ["## Coverage", "", "| Section | Tasks |", "|---|---|", "| §1 | All |", ""]
    return "\n".join(parts)


def minimal(tasks_md: str, front: str = "id: TASKS-F01\ntype: tasks\nstatus: approved\nversion: 1") -> str:
    return f"---\n{front}\n---\n\n## Tasks\n\n{tasks_md}"


class ParsesARealShapedList(unittest.TestCase):
    def test_fifteen_tasks_with_dependencies(self):
        tl = parse_task_list(task_list_text({1: "Done", 2: "In review"}), "tasks/F07.md")
        self.assertEqual((tl.id, tl.status, tl.version, tl.path),
                         ("TASKS-F07", "approved", 2, "tasks/F07.md"))
        self.assertEqual(list(tl.tasks), [tid(n) for n in GRAPH])
        for n, deps in GRAPH.items():
            self.assertEqual(tl.tasks[tid(n)].depends_on, [tid(d) for d in deps])
        self.assertEqual(tl.tasks[tid(1)].status, "Done")
        self.assertEqual(tl.tasks[tid(2)].status, "In review")
        self.assertEqual(tl.tasks[tid(3)].status, "Todo")

    def test_heading_line_is_recorded(self):
        text = task_list_text()
        tl = parse_task_list(text, "x.md")
        self.assertEqual(text.splitlines()[tl.tasks[tid(5)].line - 1], f"### {tid(5)}: Task 5")


class Statuses(unittest.TestCase):
    def test_case_is_normalized(self):
        for written, expected in [("todo", "Todo"), ("IN PROGRESS", "In progress"),
                                  ("In Review", "In review"), ("done", "Done")]:
            with self.subTest(written):
                tl = parse_task_list(minimal(f"### T-F01-01: A\n- **Status:** {written}\n"), "x.md")
                self.assertEqual(tl.tasks["T-F01-01"].status, expected)

    def test_unknown_status_names_file_and_line(self):
        for written in ["In-Progress", "Doing"]:
            with self.subTest(written):
                text = minimal(f"### T-F01-01: A\n- **Status:** {written}\n")
                with self.assertRaises(DocError) as ctx:
                    parse_task_list(text, "tasks/F01.md")
                line = text.splitlines().index(f"- **Status:** {written}") + 1
                self.assertEqual((ctx.exception.path, ctx.exception.line), ("tasks/F01.md", line))
                self.assertTrue(str(ctx.exception).startswith(f"tasks/F01.md:{line}: "))

    def test_missing_status(self):
        text = minimal("### T-F01-01: A\n- **Owner:** agent\n\n### T-F01-02: B\n- **Status:** Todo\n")
        with self.assertRaises(DocError) as ctx:
            parse_task_list(text, "x.md")
        self.assertEqual(ctx.exception.line, text.splitlines().index("### T-F01-01: A") + 1)
        self.assertIn("T-F01-01", ctx.exception.reason)


class Structure(unittest.TestCase):
    def test_duplicate_task(self):
        text = minimal("### T-F01-01: A\n- **Status:** Todo\n\n### T-F01-01: Again\n- **Status:** Done\n")
        with self.assertRaises(DocError) as ctx:
            parse_task_list(text, "x.md")
        self.assertIn("more than once", ctx.exception.reason)

    def test_headings_in_code_blocks_are_ignored(self):
        text = minimal("### T-F01-01: A\n- **Status:** Todo\n\n```markdown\n"
                       "### T-F01-09: Example\n- **Status:** Bogus\n```\n")
        self.assertEqual(list(parse_task_list(text, "x.md").tasks), ["T-F01-01"])

    def test_deeper_headings_stay_in_the_task(self):
        text = minimal("### T-F01-01: A\n#### Notes\n- **Depends on:** T-F01-00\n- **Status:** Done\n")
        task = parse_task_list(text, "x.md").tasks["T-F01-01"]
        self.assertEqual((task.status, task.depends_on), ("Done", ["T-F01-00"]))

    def test_only_the_first_depends_line_counts(self):
        text = minimal("### T-F01-02: B\n- **Depends on:** none\n- **Depends on:** T-F01-01\n"
                       "- **Status:** Todo\n")
        self.assertEqual(parse_task_list(text, "x.md").tasks["T-F01-02"].depends_on, [])

    def test_section_heading_ends_a_task(self):
        text = minimal("### T-F01-01: A\n- **Depends on:** none\n\n## Coverage\n- **Status:** Done\n")
        with self.assertRaises(DocError):
            parse_task_list(text, "x.md")  # the Status line belongs to "Coverage", not the task

    def test_missing_front_matter_fields(self):
        with self.assertRaises(DocError) as ctx:
            parse_task_list(minimal("", front="id: TASKS-F01\ntype: tasks\nversion: 1"), "x.md")
        self.assertIn("'status'", ctx.exception.reason)


class FrontMatter(unittest.TestCase):
    def test_none(self):
        self.assertEqual(front_matter("# Just a heading\n"), {})

    def test_unclosed(self):
        with self.assertRaises(YamlError) as ctx:
            front_matter("---\nid: X\n")
        self.assertEqual(ctx.exception.line, 1)

    def test_yaml_error_line_is_relative_to_the_file(self):
        with self.assertRaises(YamlError) as ctx:
            front_matter("---\nid: X\nlist: [1, 2\n---\n")
        self.assertEqual(ctx.exception.line, 3)  # the line with the unclosed bracket

    def test_broken_front_matter_in_a_task_list(self):
        with self.assertRaises(DocError) as ctx:
            parse_task_list("---\nid: X\nlist: [1, 2\n---\n", "tasks/F09.md")
        self.assertEqual((ctx.exception.path, ctx.exception.line), ("tasks/F09.md", 3))


class LoadingAndFinding(unittest.TestCase):
    def test_load_and_find_across_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp, "tasks")
            (tasks / "completed").mkdir(parents=True)
            (tasks / "F07-feature.md").write_text(task_list_text())
            (tasks / "completed" / "F01-done.md").write_text(
                minimal("### T-F01-01: A\n- **Status:** Done\n"))
            (tasks / "notes.md").write_text("# Notes without front matter\n")
            (tasks / "design.md").write_text("---\nid: TDD-F07\ntype: tdd\nstatus: draft\nversion: 1\n---\n")

            lists = load_task_lists(tmp)
            self.assertEqual([tl.id for tl in lists], ["TASKS-F07", "TASKS-F01"])

            found = find_task(lists, "T-F01-01")
            self.assertIsNotNone(found)
            self.assertEqual((found[0].id, found[1].status), ("TASKS-F01", "Done"))
            self.assertEqual(find_task(lists, tid(6))[1].depends_on, [tid(3), tid(4), tid(5)])
            self.assertIsNone(find_task(lists, "T-F99-01"))

    def test_no_tasks_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_task_lists(tmp), [])


if __name__ == "__main__":
    unittest.main()
