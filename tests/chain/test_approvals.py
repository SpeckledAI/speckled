"""Tests for lib/speckled_chain/approvals.py: listed approvers, through `lint` [T-F08-07].

Each test seeds one fault into the clean fixture project and checks the rule, file,
line and severity of what's reported, and that nothing else is. These checks need no
history, so they run as `--docs` does.
"""
from __future__ import annotations

import tempfile
import unittest

from speckled_chain import lint, load_corpus
from speckled_chain.approvals import check_approvers

from .fixtures import GATES, SENTINEL, PlanRepo, approval, clean_project, frd, pdrd, task, tasks
from .test_corpus import line_of

FRD = "frds/F01-example.md"
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


if __name__ == "__main__":
    unittest.main()
