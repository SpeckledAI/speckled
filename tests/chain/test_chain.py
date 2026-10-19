"""Tests for lib/speckled_chain/chain.py: parent checks through `lint`, and `chain_for` [T-F08-06].

Each test seeds one fault into the clean fixture project and checks the rule, file,
line and severity of what's reported, and that nothing else is.
"""
from __future__ import annotations

import tempfile
import unittest

from speckled_chain import chain_for, lint, load_corpus

from .fixtures import SENTINEL, PlanRepo, approval, clean_project, frd, pdrd, tasks, tdd
from .test_corpus import line_of

TDD = "tdds/F01-example.md"
RULE2 = "> ⚠️ Drafted from an unapproved parent (FRD-F01 v1, status in-review)."


class Chain(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = clean_project(PlanRepo(tmp.name, git=False))

    def write(self, rel: str, text: str) -> str:
        self.repo.write(self.repo.doc(rel), text)
        return text

    def findings(self):
        findings = lint(self.repo.root, history=False).findings
        for f in findings:
            self.assertNotIn(SENTINEL, f.message)
        return findings

    def assertFindings(self, *expected):
        """The findings are exactly `expected`: (rule, severity, path under docs, line), in any order."""
        got = sorted((f.rule, f.severity, f.file, f.line) for f in self.findings())
        self.assertEqual(got, sorted((rule, severity, self.repo.doc(rel), line)
                                     for rule, severity, rel, line in expected))

    # --- parent-missing --------------------------------------------------------------

    def test_no_parent(self):
        self.write(TDD, tdd("F01", parent=None))
        self.assertFindings(("parent-missing", "error", TDD, 1))

    def test_parent_frd_does_not_exist(self):
        self.repo.delete(self.repo.doc("frds/F01-example.md"))
        text = tdd("F01")
        self.assertFindings(("parent-missing", "error", TDD, line_of(text, "parent:")))
        self.assertIn("FRD-F01", self.findings()[0].message)

    def test_broken_parent_is_not_also_missing(self):
        self.write("frds/F01-example.md", "---\nid: FRD-F01\nstatus: approved: yes\n---\n")
        self.assertEqual([f.rule for f in self.findings()], ["front-matter"])

    # --- parent-wrong-type -----------------------------------------------------------

    def test_parent_is_another_tdd(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-other.md", frd("F02"))
        self.write("tdds/F02-other.md", tdd("F02"))
        text = self.write(TDD, tdd("F01", parent="TDD-F02"))
        self.assertFindings(("parent-wrong-type", "error", TDD, line_of(text, "parent:")))

    def test_parent_is_another_features_frd(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/F02-other.md", frd("F02"))
        text = self.write(TDD, tdd("F01", parent="FRD-F02"))
        self.assertFindings(("parent-wrong-type", "error", TDD, line_of(text, "parent:")))

    def test_pdrd_parent_must_be_the_brief(self):
        text = self.write("pdrd.md", pdrd(parent="PDRD"))
        self.assertFindings(("parent-wrong-type", "error", "pdrd.md", line_of(text, "parent:")))

    # --- parent-unapproved and parent-reopened ---------------------------------------

    def test_never_approved_parent_is_an_error(self):
        self.write("frds/F01-example.md", frd("F01", status="in-review", approvals=[]))
        text = tdd("F01")
        self.write(TDD, text)
        self.assertFindings(("parent-unapproved", "error", TDD, line_of(text, "parent:")))

    def test_never_approved_parent_with_the_rule2_line_is_a_warning(self):
        self.write("frds/F01-example.md", frd("F01", status="in-review", approvals=[]))
        text = self.write(TDD, tdd("F01", body=f"# TDD-F01\n\n{RULE2}\n\nText.\n"))
        self.assertFindings(("parent-unapproved", "warning", TDD, line_of(text, "parent:")))

    def test_reopened_parent_is_a_warning(self):
        for status in ("draft", "in-review", "superseded"):
            with self.subTest(status=status):
                self.write("frds/F01-example.md", frd("F01", status=status, version=2,
                                                      approvals=[approval("frd")]))
                text = tdd("F01")
                self.assertFindings(("parent-reopened", "warning", TDD, line_of(text, "parent:")))

    # --- correct passes --------------------------------------------------------------

    def test_approved_with_no_entries_counts_as_approved(self):
        self.write("frds/F01-example.md", frd("F01", status="approved", approvals=[]))
        self.assertFindings()

    def test_done_parent(self):
        self.write("frds/F01-example.md", frd("F01", status="done"))
        self.assertFindings()

    def test_stale_parent_version_passes(self):
        self.write("frds/F01-example.md", frd("F01", version=3, approvals=[approval("frd", version=3)]))
        self.write(TDD, tdd("F01", parent_version=1))
        self.assertFindings()

    def test_brief_and_research_have_no_parent_check(self):
        self.write("research/notes.md", "---\nid: notes\ntitle: Notes\ntype: research\nstatus: draft\n"
                                        "version: 1\nupdated: 2026-10-01\napprovals: []\n---\n\n# Notes\n")
        self.assertFindings()

    # --- chain_for -------------------------------------------------------------------

    def test_chain_for_a_task(self):
        corpus = load_corpus(self.repo.root)
        self.assertEqual(chain_for(corpus, "T-F01-02"), ["TASKS-F01", "TDD-F01", "FRD-F01", "PDRD", "BRIEF"])

    def test_chain_for_a_tdd(self):
        corpus = load_corpus(self.repo.root)
        self.assertEqual(chain_for(corpus, "TDD-F01"), ["TDD-F01", "FRD-F01", "PDRD", "BRIEF"])

    def test_chain_for_an_unknown_id(self):
        corpus = load_corpus(self.repo.root)
        for id_ in ("T-F01-99", "TDD-F99", "nope"):
            with self.subTest(id=id_), self.assertRaises(KeyError):
                chain_for(corpus, id_)

    def test_chain_for_stops_at_a_missing_parent(self):
        self.write("frds/F01-example.md", frd("F01", parent="PDRD-gone"))
        self.assertEqual(chain_for(load_corpus(self.repo.root), "TASKS-F01"), ["TASKS-F01", "TDD-F01", "FRD-F01"])

    def test_chain_for_is_cycle_safe(self):
        self.write("frds/F01-example.md", frd("F01", parent="TASKS-F01"))
        self.write("tasks/F01-example.md", tasks("F01"))
        self.assertEqual(chain_for(load_corpus(self.repo.root), "T-F01-01"), ["TASKS-F01", "TDD-F01", "FRD-F01"])


if __name__ == "__main__":
    unittest.main()
