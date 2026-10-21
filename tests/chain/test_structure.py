"""Tests for lib/speckled_chain/structure.py, through `lint` [T-F08-05].

Each test seeds one fault into the clean fixture project and checks the rule, file and
line of what's reported, and that nothing else is.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from speckled_chain import lint, load_corpus
from speckled_gate.docs import DocError, load_task_list

from .fixtures import (SENTINEL, PlanRepo, brief, clean_project, frd, pdrd, research, task, tasks, tdd,
                       without_log)
from .test_corpus import line_of

TASKS = "tasks/F01-example.md"


def replace(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


class Structure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = clean_project(PlanRepo(tmp.name, git=False))

    def write(self, rel: str, text: str) -> str:
        self.repo.write(self.repo.doc(rel), text)
        return text

    def findings(self):
        findings = without_log(lint(self.repo.root, history=False).findings)
        for f in findings:
            self.assertNotIn(SENTINEL, f.message)
            self.assertNotIn(SENTINEL, f.subject)
        return findings

    def assertFindings(self, *expected):
        """The findings are exactly `expected`: (rule, path under docs, line) triples, in any order."""
        got = sorted((f.rule, f.file, f.line) for f in self.findings())
        self.assertEqual(got, sorted((rule, self.repo.doc(rel), line) for rule, rel, line in expected))

    def only(self, rule: str, rel: str, line: int):
        self.assertFindings((rule, rel, line))
        return self.findings()[0]

    def tasks(self, *specs, **kw) -> str:
        return self.write(TASKS, tasks("F01", tasks=list(specs), **kw))

    # --- clean passes ----------------------------------------------------------------

    def test_clean_project(self):
        report = lint(self.repo.root, history=False)
        self.assertEqual([f.rule for f in report.findings], ["warn-event"])   # the log's one `warn` line
        self.assertEqual(report.documents, 5)

    def test_research_with_free_form_id(self):
        self.write("research/user-interviews.md", research("Interviews 2026 (round 1)"))
        self.write("research/completed/x.md", research("spike-x"))
        self.assertFindings()

    def test_approved_by_with_a_note(self):
        self.tasks(task("T-F01-01", "Done", approved_by=["Approved by alice on 2026-10-02 (CI passed)"]))
        self.assertFindings()

    def test_completed_documents(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/completed/F02-old-thing.md", frd("F02", status="done"))
        self.assertFindings()

    def test_optional_fields(self):
        # An approval `note` is optional, and an unapproved document has `approvals: []`.
        self.write("brief.md", brief(approvals=[{"by": "alice", "role": "brief", "date": "2026-10-01", "version": 1,
                                                 "note": "first cut"}]))
        self.write("research/a.md", research("a", approvals=[]))
        self.assertFindings()

    # --- front-matter ----------------------------------------------------------------

    def test_missing_front_matter(self):
        self.write("frds/F01-example.md", "# FRD-F01\n\nNo front matter.\n")
        finding = self.only("front-matter", "frds/F01-example.md", 1)
        self.assertEqual(finding.subject, "docs/frds/F01-example.md")

    def test_malformed_front_matter(self):
        text = self.write("frds/F01-example.md", replace(frd("F01"), "status: approved", "status: approved: yes"))
        self.only("front-matter", "frds/F01-example.md", line_of(text, "status:"))

    def test_unclosed_front_matter(self):
        self.write("tdds/F01-example.md", "---\nid: TDD-F01\n\n# TDD-F01\n")
        self.only("front-matter", "tdds/F01-example.md", 1)

    def test_invalid_status(self):
        text = self.write("frds/F01-example.md", frd("F01", status="Doing", approvals=[]))
        finding = self.only("front-matter", "frds/F01-example.md", line_of(text, "status:"))
        self.assertIn("unknown status 'Doing'", finding.message)

    def test_missing_required_fields(self):
        self.write("tdds/F01-example.md", replace(tdd("F01", updated=None), "feature: F01\n", ""))
        self.assertFindings(("front-matter", "tdds/F01-example.md", 1), ("front-matter", "tdds/F01-example.md", 1))

    def test_missing_parent_is_left_to_the_chain_check(self):
        self.write("tdds/F01-example.md", tdd("F01", parent=None))
        self.assertFindings(("parent-missing", "tdds/F01-example.md", 1))

    def test_unknown_type(self):
        text = self.write("research/a.md", research("a", type="memo"))
        self.only("front-matter", "research/a.md", line_of(text, "type:"))

    def test_invalid_values(self):
        text = self.write("frds/F01-example.md", replace(frd("F01", version=0, parent_version="two",
                                                             updated="2026-02-30", approvals=[]), "feature: F01", "feature: F1"))
        self.assertFindings(*[("front-matter", "frds/F01-example.md", line_of(text, key))
                              for key in ("version:", "parent_version:", "updated:", "feature:")])

    def test_invalid_approval_entry(self):
        text = self.write("frds/F01-example.md", frd("F01", approvals=[
            {"by": "alice", "role": "frd", "date": "2026-10-01", "version": 1},
            {"by": "alice", "role": "frd", "version": 1},
            {"by": "alice", "role": "frd", "date": "10/02/2026", "version": "one"}]))
        second = line_of(text, "  - {by: alice") + 1
        self.assertFindings(("front-matter", "frds/F01-example.md", second),
                            ("front-matter", "frds/F01-example.md", second + 1),
                            ("front-matter", "frds/F01-example.md", second + 1))

    # --- broken files ------------------------------------------------------------------

    def test_a_broken_file_gives_one_finding_and_the_rest_is_checked(self):
        text = "---\nid: FRD-F01\ntitle: [unclosed\nstatus: Doing\n---\n"
        self.write("frds/F01-example.md", text)
        self.write("tdds/F01-other.md", tdd("F01"))
        self.assertFindings(("front-matter", "frds/F01-example.md", 4),
                            ("duplicate-id", "tdds/F01-other.md", 2))

    # --- bad-id ------------------------------------------------------------------------

    def test_frd_whose_feature_doesnt_match_its_id(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        text = self.write("frds/F01-example.md", replace(frd("F01"), "feature: F01", "feature: F02"))
        self.only("bad-id", "frds/F01-example.md", line_of(text, "feature:"))

    def test_badly_formed_ids(self):
        self.write("pdrd.md", pdrd(id="ROADMAP"))
        self.write("tdds/F01-example.md", tdd("F01", id="TDD-01"))
        # Their children now cite IDs no document has.
        self.assertFindings(("bad-id", "pdrd.md", 2), ("bad-id", "tdds/F01-example.md", 2),
                            ("parent-missing", "frds/F01-example.md", line_of(frd("F01"), "parent:")),
                            ("parent-missing", TASKS, line_of(tasks("F01"), "parent:")))

    def test_task_heading_that_isnt_a_task_id(self):
        text = self.tasks(task("T-F01-01"))
        text = self.write(TASKS, text + "\n### T-F1-2: Badly numbered\n- **Status:** Todo\n\n```\n### T-x: example\n```\n")
        self.only("bad-id", TASKS, line_of(text, "### T-F1-2"))

    def test_task_from_another_feature(self):
        text = self.tasks(task("T-F01-01"), task("T-F02-01"))
        finding = self.only("bad-id", TASKS, line_of(text, "### T-F02-01"))
        self.assertEqual(finding.subject, "T-F02-01")

    # --- duplicate-id, file-name, unknown-feature ---------------------------------------

    def test_duplicate_id(self):
        self.write("frds/F01-other.md", frd("F01"))
        finding = self.only("duplicate-id", "frds/F01-other.md", 2)
        self.assertIn("docs/frds/F01-example.md", finding.message)
        self.assertEqual(finding.subject, "FRD-F01")

    def test_duplicate_id_is_reported_on_every_later_file(self):
        self.write("frds/F01-other.md", frd("F01"))
        self.write("frds/completed/F01-example.md", frd("F01"))
        self.assertFindings(("duplicate-id", "frds/F01-other.md", 2),
                            ("duplicate-id", "frds/completed/F01-example.md", 2))

    def test_frd_whose_file_name_doesnt_match_its_id(self):
        self.repo.move(self.repo.doc("frds/F01-example.md"), self.repo.doc("frds/F02-example.md"))
        finding = self.only("file-name", "frds/F02-example.md", 2)
        self.assertIn("docs/frds/F01-<slug>.md", finding.message)

    def test_file_names(self):
        self.repo.move(self.repo.doc("tdds/F01-example.md"), self.repo.doc("tdds/F01_Example.md"))
        self.repo.move(self.repo.doc("brief.md"), self.repo.doc("research/brief.md"))
        self.write("research/old/note.md", research("note"))
        text = self.write("frds/archive/F01-x.md", frd("F09"))
        self.assertFindings(("file-name", "research/brief.md", 2), ("file-name", "tdds/F01_Example.md", 2),
                            ("file-name", "research/old/note.md", 2), ("file-name", "frds/archive/F01-x.md", 2),
                            ("unknown-feature", "frds/archive/F01-x.md", line_of(text, "feature:")))

    def test_frd_for_a_feature_not_in_the_pdrd(self):
        text = self.write("frds/F03-new.md", frd("F03"))
        finding = self.only("unknown-feature", "frds/F03-new.md", line_of(text, "feature:"))
        self.assertIn("F03", finding.message)

    def test_no_unknown_feature_without_a_pdrd(self):
        self.repo.delete(self.repo.doc("pdrd.md"))
        self.assertFindings(("parent-missing", "frds/F01-example.md", line_of(frd("F01"), "parent:")))

    # --- tasks -------------------------------------------------------------------------

    def test_non_strict_task_status(self):
        text = self.tasks(task("T-F01-01", "Doing"))
        finding = self.only("task-format", TASKS, line_of(text, "- **Status:** Doing"))
        self.assertIn("unknown status 'Doing'", finding.message)
        self.assertEqual(finding.subject, "TASKS-F01")

    def test_task_without_status(self):
        text = self.write(TASKS, replace(tasks("F01"), "- **Status:** Todo", "- Status: Todo"))
        self.only("task-format", TASKS, line_of(text, "### T-F01-01"))

    def test_malformed_approved_by_lines(self):
        text = self.tasks(task("T-F01-01", "Done", approved_by=[
            "Approved by alice on 2026-10-02",
            "Approved by alice on 2026-10-15x",
            f"Approved by alice on 2026-10-15 {SENTINEL} without brackets",
            "Approved by alice"]))
        lines = text.splitlines()
        self.assertFindings(("task-format", TASKS, lines.index("Approved by alice on 2026-10-15x") + 1),
                            ("task-format", TASKS, line_of(text, "Approved by alice on 2026-10-15 ")),
                            ("task-format", TASKS, lines.index("Approved by alice") + 1))

    def test_duplicate_task_across_lists(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-example.md", frd("F02"))
        self.write("tdds/F02-example.md", tdd("F02"))
        text = self.write("tasks/F02-example.md", tasks("F02", tasks=[task("T-F02-01"), task("T-F01-01")]))
        line = line_of(text, "### T-F01-01")
        self.assertFindings(("duplicate-task", "tasks/F02-example.md", line), ("bad-id", "tasks/F02-example.md", line))

    def test_missing_dependency(self):
        text = self.tasks(task("T-F01-01"), task("T-F01-02", depends_on=["T-F01-01", "T-F07-09"]))
        depends = [n for n, line in enumerate(text.splitlines(), 1) if line.startswith("- **Depends on:**")]
        finding = self.only("dependency-missing", TASKS, depends[1])
        self.assertEqual(finding.subject, "T-F01-02")
        self.assertIn("T-F07-09", finding.message)

    def test_dependency_in_another_list(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-example.md", frd("F02"))
        self.write("tdds/F02-example.md", tdd("F02"))
        self.write("tasks/F02-example.md", tasks("F02", tasks=[task("T-F02-01", depends_on=["T-F01-02"])]))
        self.assertFindings()

    def test_dependency_on_a_broken_list_isnt_reported_twice(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-example.md", frd("F02"))
        self.write("tdds/F02-example.md", tdd("F02"))
        text = self.write("tasks/F02-example.md", tasks("F02", tasks=[task("T-F02-01", "Doing")]))
        self.tasks(task("T-F01-01", depends_on=["T-F02-01"]))
        self.only("task-format", "tasks/F02-example.md", line_of(text, "- **Status:** Doing"))

    def test_dependency_cycle(self):
        text = self.tasks(task("T-F01-01", depends_on=["T-F01-03"]), task("T-F01-02", depends_on=["T-F01-01"]),
                          task("T-F01-03", depends_on=["T-F01-02"]), task("T-F01-04", depends_on=["T-F01-03"]))
        finding = self.only("dependency-cycle", TASKS, line_of(text, "- **Depends on:** T-F01-03"))
        self.assertEqual(finding.subject, "T-F01-01")
        self.assertIn("T-F01-01 -> T-F01-03 -> T-F01-02 -> T-F01-01", finding.message)

    def test_self_dependency_and_two_cycles(self):
        text = self.tasks(task("T-F01-01", depends_on=["T-F01-01"]),
                          task("T-F01-02", depends_on=["T-F01-03"]), task("T-F01-03", depends_on=["T-F01-02"]))
        depends = [n for n, line in enumerate(text.splitlines(), 1) if line.startswith("- **Depends on:**")]
        self.assertFindings(("dependency-cycle", TASKS, depends[0]), ("dependency-cycle", TASKS, depends[1]))

    def test_long_dependency_chain(self):
        specs = [task("T-F01-01")] + [task(f"T-F01-{n:04d}", depends_on=[f"T-F01-{n - 1:04d}" if n > 2 else "T-F01-01"])
                                      for n in range(2, 1500)]
        self.tasks(*specs)
        self.assertFindings()

    # --- privacy -----------------------------------------------------------------------

    def test_no_message_quotes_a_title_or_body(self):
        self.write("frds/F01-example.md", frd("F01", status="Doing", version=0, title=f"{SENTINEL} status: x"))
        self.write("tdds/F01-other.md", tdd("F01"))
        self.write("frds/F03-x.md", frd("F03"))
        self.tasks(task("T-F01-01", depends_on=["T-F01-09"], approved_by=[f"Approved by x on 2026-10-02 {SENTINEL}"]),
                   task("T-F02-01"))
        findings = self.findings()  # checks the sentinel on every finding
        self.assertGreaterEqual(len(findings), 7)


class GateAgreement(unittest.TestCase):
    """The linter and the gate agree on which task lists are readable, and what they say."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def project(self, name: str, task_list_text: str | None = None) -> PlanRepo:
        folder = self.tmp / name
        folder.mkdir()
        repo = clean_project(PlanRepo(folder, git=False))
        if task_list_text is not None:
            repo.write(repo.doc(TASKS), task_list_text)
        return repo

    def test_agreement(self):
        variants = {
            "clean": None,
            "status": tasks("F01", tasks=[task("T-F01-01", "Doing")]),
            "no-status": replace(tasks("F01"), "- **Status:** Todo", "Status: Todo"),
            "duplicate": tasks("F01", tasks=[task("T-F01-01"), task("T-F01-01")]),
            "yaml": "---\nid: TASKS-F01\ntype: tasks\nstatus: [x\n---\n",
            "no-version": tasks("F01", version=None),
            "approved-by": tasks("F01", tasks=[task("T-F01-01", "Done", approved_by=["Approved by x on 2026-1-1"])]),
            "case": tasks("F01", tasks=[task("T-F01-01", "in REVIEW"), task("T-F01-02", "done", ["T-F01-01"])]),
        }
        for name, text in variants.items():
            with self.subTest(name):
                repo = self.project(name, text)
                corpus = load_corpus(repo.root)
                for file in sorted((repo.root / "docs").rglob("*.md")):
                    path = file.relative_to(repo.root).as_posix()
                    try:
                        gate = load_task_list(file)
                    except DocError:
                        gate = "unreadable"
                    if gate == "unreadable":
                        self.assertIn(path, corpus.broken)
                        self.assertIn(corpus.broken[path].rule, ("front-matter", "task-format"))
                        continue
                    self.assertNotIn(path, corpus.broken)
                    mine = corpus.docs[path].task_list
                    if gate is None:
                        self.assertIsNone(mine)
                        continue
                    self.assertEqual({t.id: (t.status, t.depends_on) for t in mine.tasks.values()},
                                     {t.id: (t.status, t.depends_on) for t in gate.tasks.values()})


if __name__ == "__main__":
    unittest.main()
