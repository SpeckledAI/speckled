"""Tests for lib/speckled_chain/approvals.py, through `lint` [T-F08-07, T-F08-09].

Each test seeds one fault into the clean fixture project and checks the rule, file,
line and severity of what's reported, and that nothing else is. `Approvers` needs no
history, so it runs as `--docs` does. `AppendOnly` and `RolesAtCommit` build real git
histories.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speckled_chain import lint, load_corpus
from speckled_chain.approvals import _broken, check_approvers

from .fixtures import (AUTHOR, GATES, SENTINEL, PlanRepo, approval, clean_project, frd, git_env, pdrd,
                       task, tasks)
from .test_corpus import line_of

FRD = "frds/F01-example.md"
TDD = "tdds/F01-example.md"
TASKS = "tasks/F01-example.md"


class Approvers(unittest.TestCase):
    def project(self, roles: dict | None = None) -> PlanRepo:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = clean_project(PlanRepo(tmp.name, git=False, roles=roles))
        return self.repo

    def setUp(self):
        self.project()

    def write(self, rel: str, text: str) -> str:
        self.repo.write(self.repo.doc(rel), text)
        return text

    def findings(self):
        findings = lint(self.repo.root, history=False).findings
        for f in findings:
            self.assertNotIn(SENTINEL, f.message)
        return findings

    def assertFindings(self, *expected):
        """The findings are exactly `expected`: (rule, severity, file, line), in any order.

        `file` is under docs, or `speckled.yaml` itself.
        """
        def path(rel):
            return rel if rel == "speckled.yaml" else self.repo.doc(rel)
        got = sorted((f.rule, f.severity, f.file, f.line or 0) for f in self.findings())
        self.assertEqual(got, sorted((rule, severity, path(rel), line or 0)
                                     for rule, severity, rel, line in expected))

    # --- approver-not-listed ---------------------------------------------------------

    def test_approval_by_a_name_not_under_its_gate(self):
        text = self.write(FRD, frd("F01", approvals=[approval("frd", by="mallory")]))
        self.assertFindings(("approver-not-listed", "error", FRD, line_of(text, "  - {by: mallory")))
        message = self.findings()[0].message
        self.assertIn("'mallory'", message)
        self.assertIn("roles.frd", message)

    def test_approved_by_name_not_under_code(self):
        text = self.write(TASKS, tasks("F01", tasks=[
            task("T-F01-01", "Done", approved_by=["Approved by bob on 2026-10-02 (looks fine)"])]))
        self.assertFindings(("approver-not-listed", "error", TASKS, line_of(text, "Approved by bob")))
        finding = self.findings()[0]
        self.assertEqual(finding.subject, "T-F01-01")
        self.assertIn("roles.code", finding.message)

    def test_gate_listed_with_nobody(self):
        self.project(roles={**{gate: ["alice"] for gate in GATES}, "frd": []})
        text = frd("F01")
        self.assertFindings(("approver-not-listed", "error", FRD, line_of(text, "  - {by: alice")))

    # --- approval-role-mismatch ------------------------------------------------------

    def test_frd_approval_with_the_tdd_role(self):
        text = self.write(FRD, frd("F01", approvals=[approval("tdd")]))
        self.assertFindings(("approval-role-mismatch", "error", FRD, line_of(text, "  - {by: alice")))
        self.assertIn("'tdd'", self.findings()[0].message)

    def test_mismatched_role_is_one_finding(self):
        # The name isn't checked as well: one wrong entry, one finding.
        self.write(FRD, frd("F01", approvals=[approval("brief", by="mallory")]))
        self.assertEqual([f.rule for f in self.findings()], ["approval-role-mismatch"])

    # --- gate-without-approvers ------------------------------------------------------

    def test_gate_missing_from_roles_is_one_warning_counting_its_approvals(self):
        self.project(roles={gate: ["alice"] for gate in GATES if gate != "frd"})
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-other.md", frd("F02", approvals=[approval("frd", by="mallory"),
                                                             approval("frd", by="bob", version=1)]))
        self.assertFindings(("gate-without-approvers", "warning", "speckled.yaml", None))
        finding = self.findings()[0]
        self.assertEqual(finding.subject, "speckled.yaml")
        self.assertIn("'frd'", finding.message)
        self.assertIn("3 approvals", finding.message)

    def test_one_warning_per_missing_gate(self):
        self.project(roles={"brief": ["alice"], "pdrd": ["alice"], "frd": ["alice"]})
        messages = sorted(f.message for f in self.findings())
        self.assertEqual([f.rule for f in self.findings()], ["gate-without-approvers"] * 3)
        for gate, count in (("code", "1 approval "), ("tasks", "1 approval "), ("tdd", "1 approval ")):
            self.assertTrue(any(f"'{gate}'" in m and count in m for m in messages), (gate, messages))

    def test_no_roles_at_all(self):
        self.project(roles={})
        self.assertEqual(sorted(f.message.split("'")[1] for f in self.findings()),
                         ["brief", "code", "frd", "pdrd", "tasks", "tdd"])

    # --- passes ----------------------------------------------------------------------

    def test_clean_project(self):
        self.assertFindings()

    def test_roles_come_from_roles_for(self):
        # With history, each entry is checked against the roles of the commit that added it.
        self.write(FRD, frd("F01", approvals=[approval("frd", by="mallory")]))
        corpus = load_corpus(self.repo.root)
        then = {**corpus.config.roles, "frd": ["mallory"]}
        seen = []

        def roles_for(entry):
            seen.append(entry)
            return then

        self.assertEqual(check_approvers(corpus, roles_for), [])
        self.assertEqual(len(seen), 6)   # five documents' approvals and one `Approved by` line


# --- history -------------------------------------------------------------------------

HISTORY_RULES = ("approval-edited", "approval-removed", "document-deleted", "approver-not-listed")


class HistoryTest(unittest.TestCase):
    """A clean project with git. The linter runs git with the fixtures' isolated environment."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, git_env(self.tmp), clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repo = clean_project(PlanRepo(self.tmp))

    def write(self, rel: str, text: str) -> str:
        self.repo.write(self.repo.doc(rel), text)
        return text

    def set_roles(self, **changed) -> None:
        roles = {**{gate: ["alice"] for gate in GATES}, **changed}
        lines = ["project: example", "docs_dir: docs", "roles:"]
        lines += [f"  {gate}: {json.dumps(names)}" for gate, names in roles.items()]
        self.repo.write("speckled.yaml", "\n".join(lines) + "\n")

    def findings(self):
        """The findings of the rules under test, checked for privacy."""
        report = lint(self.repo.root)
        self.assertEqual(report.history, "full")
        text = json.dumps(report.to_json())
        self.assertNotIn("@", text)
        self.assertNotIn(SENTINEL, text)
        return [f for f in report.findings if f.rule in HISTORY_RULES]

    def assertFindings(self, *expected):
        """The findings are exactly `expected`: (rule, subject, file under docs, line, commit or None)."""
        got = sorted((f.rule, f.subject, f.file, f.line or 0, f.commit) for f in self.findings())
        self.assertEqual(got, sorted((rule, subject, self.repo.doc(rel), line or 0, commit)
                                     for rule, subject, rel, line, commit in expected))


class AppendOnly(HistoryTest):
    def test_clean_project(self):
        self.assertFindings()

    def test_commit_that_edits_an_approvals_version(self):
        text = self.write(FRD, frd(approvals=[approval("frd", version=2)]))
        sha = self.repo.commit("Edit an approval")
        self.assertFindings(("approval-edited", "FRD-F01", FRD, line_of(text, "  - {by: alice"), sha))
        (finding,) = self.findings()
        self.assertEqual((finding.by, finding.date, finding.severity), (AUTHOR[0], "2026-10-01", "error"))
        self.assertIn(sha[:7], finding.message)

    def test_commit_that_removes_an_approval(self):
        text = self.write(FRD, frd(approvals=[]))
        sha = self.repo.commit("Remove the approval")
        self.assertFindings(("approval-removed", "FRD-F01", FRD, line_of(text, "approvals:"), sha))

    def test_commit_that_removes_an_approved_by_line(self):
        text = self.write(TASKS, tasks(tasks=[task("T-F01-01", "Done"),
                                              task("T-F01-02", "In progress", depends_on=["T-F01-01"])]))
        sha = self.repo.commit("Remove the line")
        self.assertFindings(("approval-removed", "T-F01-01", TASKS, line_of(text, "### T-F01-01"), sha))

    def test_commit_that_edits_an_approved_by_line(self):
        text = self.write(TASKS, tasks(tasks=[
            task("T-F01-01", "Done", approved_by=["Approved by alice on 2026-10-03"]),
            task("T-F01-02", "In progress", depends_on=["T-F01-01"])]))
        sha = self.repo.commit("Edit the line")
        self.assertFindings(("approval-edited", "T-F01-01", TASKS, line_of(text, "Approved by alice"), sha))

    def test_commit_that_deletes_an_approved_document(self):
        self.repo.delete(self.repo.doc(FRD))
        sha = self.repo.commit("Delete the FRD")
        self.assertFindings(("document-deleted", "FRD-F01", FRD, None, sha))

    def test_reorder(self):
        first, second = approval("frd"), approval("frd", date="2026-10-02", version=2)
        self.write(FRD, frd(version=2, approvals=[first, second]))
        self.repo.commit("Approve version 2")
        text = self.write(FRD, frd(version=2, approvals=[second, first]))
        sha = self.repo.commit("Reorder")
        # One finding for the moves, at the first moved entry's new line.
        self.assertFindings(("approval-edited", "FRD-F01", FRD,
                             line_of(text, "  - {by: alice, role: frd, date: 2026-10-01"), sha))
        self.assertIn("approvals 1 and 2 were moved", self.findings()[0].message)

    def test_entry_added_before_the_committed_ones(self):
        text = self.write(FRD, frd(approvals=[approval("frd", by="alice", date="2026-10-05"), approval("frd")]))
        sha = self.repo.commit("Approve, at the top")
        self.assertFindings(("approval-edited", "FRD-F01", FRD,
                             line_of(text, "  - {by: alice, role: frd, date: 2026-10-01"), sha))
        message = self.findings()[0].message
        self.assertIn("approval 1 (by 'alice') was moved to position 2, because an entry was added before it",
                      message)
        self.assertIn("go at the end", message)

    def test_removal_hidden_behind_an_unreadable_version(self):
        self.write(FRD, "---\nid: FRD-F01\napprovals: [unclosed\n---\n\n# FRD-F01\n")
        self.repo.commit("Break the front matter")
        text = self.write(FRD, frd(approvals=[]))
        sha = self.repo.commit("Fix it, without the approval")
        self.assertFindings(("approval-removed", "FRD-F01", FRD, line_of(text, "approvals:"), sha))

    def test_unreadable_version_then_restored(self):
        self.write(FRD, "---\nid: FRD-F01\napprovals: [unclosed\n---\n\n# FRD-F01\n")
        self.repo.commit("Break the front matter")
        self.write(FRD, frd())
        self.repo.commit("Restore it")
        self.assertFindings()

    def test_removal_shifts_no_other_entry(self):
        a, b, c = approval("frd"), approval("frd", date="2026-10-02"), approval("frd", date="2026-10-03")
        self.write(FRD, frd(approvals=[a, b, c]))
        self.repo.commit("Approve three times")
        self.write(FRD, frd(approvals=[a, c]))
        self.repo.commit("Remove the middle one")
        self.assertEqual([f.rule for f in self.findings()], ["approval-removed"])

    # --- the same faults, uncommitted ------------------------------------------------

    def test_uncommitted_edit_and_removal(self):
        text = self.write(FRD, frd(approvals=[approval("frd", by="alice", version=2)]))
        self.write(TASKS, tasks(tasks=[task("T-F01-01", "Done"),
                                       task("T-F01-02", "In progress", depends_on=["T-F01-01"])]))
        tasks_text = (self.repo.root / self.repo.doc(TASKS)).read_text(encoding="utf-8")
        self.assertFindings(("approval-edited", "FRD-F01", FRD, line_of(text, "  - {by: alice"), None),
                            ("approval-removed", "T-F01-01", TASKS, line_of(tasks_text, "### T-F01-01"), None))
        for f in self.findings():
            self.assertIn("working tree", f.message)
            self.assertEqual((f.by, f.date), (None, None))

    def test_uncommitted_deletion(self):
        self.repo.delete(self.repo.doc(FRD))
        self.assertFindings(("document-deleted", "FRD-F01", FRD, None, None))

    # --- passes ----------------------------------------------------------------------

    def test_move_to_completed(self):
        self.repo.move(self.repo.doc(TDD), self.repo.doc("tdds/completed/F01-example.md"))
        self.repo.commit("Complete F01")
        self.assertFindings()

    def test_appending_passes(self):
        self.write(FRD, frd(version=2, approvals=[approval("frd"), approval("frd", version=2)]))
        self.repo.commit("Approve version 2")
        self.write(TASKS, tasks(tasks=[
            task("T-F01-01", "Done", approved_by=[f"Approved by alice on 2026-10-02 ({SENTINEL} checked)"]),
            task("T-F01-02", "Done", depends_on=["T-F01-01"], approved_by=["Approved by alice on 2026-10-03"])]))
        self.assertFindings()

    def test_concurrent_branch_approvals(self):
        x, y = approval("frd", date="2026-10-03"), approval("frd", date="2026-10-04")
        self.repo.branch("y")
        self.repo.git("checkout", "-q", "-b", "x")
        self.write(FRD, frd(approvals=[approval("frd"), x]))
        self.repo.commit("Approve on x")
        self.repo.checkout("y")
        self.write(FRD, frd(approvals=[approval("frd"), y]))
        self.repo.commit("Approve on y")
        self.repo.checkout("main")
        self.repo.merge("x")
        with self.assertRaises(subprocess.CalledProcessError):
            self.repo.git("merge", "-q", "--no-ff", "-m", "Merge y", "y")
        self.write(FRD, frd(approvals=[approval("frd"), x, y]))
        self.repo.commit("Merge y")
        self.assertFindings()

    def test_fault_on_a_branch_is_reported_once(self):
        self.repo.git("checkout", "-q", "-b", "side")
        self.write(FRD, frd(approvals=[]))
        sha = self.repo.commit("Remove on a branch")
        self.repo.checkout("main")
        self.repo.merge("side")
        self.assertEqual([(f.rule, f.commit) for f in self.findings()], [("approval-removed", sha)])


class RolesAtCommit(HistoryTest):
    def test_approver_removed_from_roles_after_approving(self):
        self.set_roles(frd=["alice", "bob"])
        self.repo.commit("Add bob")
        self.write(FRD, frd(approvals=[approval("frd"), approval("frd", by="bob", date="2026-10-02")]))
        self.repo.commit("bob approves")
        self.set_roles(frd=["alice"])
        self.repo.commit("Remove bob")
        self.assertFindings()

    def test_approver_added_to_roles_only_after_approving(self):
        text = self.write(FRD, frd(approvals=[approval("frd"), approval("frd", by="bob", date="2026-10-02")]))
        sha = self.repo.commit("bob approves")
        self.set_roles(frd=["alice", "bob"])
        self.repo.commit("Add bob")
        self.assertFindings(("approver-not-listed", "FRD-F01", FRD, line_of(text, "  - {by: bob"), sha))
        (finding,) = self.findings()
        self.assertEqual((finding.by, finding.date), (AUTHOR[0], "2026-10-01"))
        self.assertIn(sha[:7], finding.message)

    def test_approved_by_name_checked_as_of_its_commit(self):
        self.set_roles(code=["alice", "bob"])
        self.repo.commit("Add bob")
        self.write(TASKS, tasks(tasks=[
            task("T-F01-01", "Done", approved_by=[f"Approved by alice on 2026-10-02 ({SENTINEL} checked)"]),
            task("T-F01-02", "Done", depends_on=["T-F01-01"], approved_by=["Approved by bob on 2026-10-03"])]))
        self.repo.commit("bob approves T-F01-02")
        self.set_roles(code=["alice"])
        self.repo.commit("Remove bob")
        self.assertFindings()

    def test_uncommitted_entry_uses_the_current_roles(self):
        self.set_roles(frd=["alice", "bob"])
        self.repo.commit("Add bob")
        self.set_roles(frd=["alice"])
        text = self.write(FRD, frd(approvals=[approval("frd"), approval("frd", by="bob", date="2026-10-02")]))
        self.assertFindings(("approver-not-listed", "FRD-F01", FRD, line_of(text, "  - {by: bob"), None))

    def test_unreadable_config_at_the_commit_uses_the_current_roles(self):
        self.repo.write("speckled.yaml", "roles: [unclosed\n")
        self.write(FRD, frd(approvals=[approval("frd"), approval("frd", by="bob", date="2026-10-02")]))
        self.repo.commit("bob approves, with a broken config")
        self.set_roles(frd=["alice", "bob"])
        self.repo.commit("Fix the config")
        self.assertFindings()


class Broken(unittest.TestCase):
    """How an old list stopped being a prefix of the new one."""

    def test_cases(self):
        cases = [
            ("ab", "ab", []),
            ("ab", "abc", []),
            ("ab", "ax", [("changed", 1, 1)]),
            ("ab", "a", [("removed", 1, None)]),
            ("abc", "ac", [("removed", 1, None)]),
            ("ab", "ba", [("moved", 0, 1), ("moved", 1, 0)]),
            ("ab", "xab", [("moved", 0, 1), ("moved", 1, 2), ("inserted", None, 0)]),
            ("ab", "axb", [("moved", 1, 2), ("inserted", None, 1)]),
            ("aa", "a", [("removed", 1, None)]),
        ]
        for old, new, expected in cases:
            self.assertEqual(_broken(list(old), list(new)), expected, (old, new))


if __name__ == "__main__":
    unittest.main()
