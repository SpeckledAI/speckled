"""Tests for lib/speckled_chain/corpus.py [T-F08-05]."""
import os
import tempfile
import unittest
from pathlib import Path

from speckled_chain.corpus import is_document_place, load_corpus, pdrd_features

from .fixtures import PlanRepo, clean_project, frd, pdrd, research, tasks


def line_of(text: str, start: str) -> int:
    """The 1-based number of the first line of `text` that starts with `start`."""
    return next(n for n, line in enumerate(text.splitlines(), 1) if line.startswith(start))


class Corpus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = clean_project(PlanRepo(self.tmp, git=False))

    def write(self, rel: str, text: str) -> str:
        self.repo.write(self.repo.doc(rel), text)
        return text

    def load(self):
        return load_corpus(self.repo.root)

    def test_clean_project(self):
        corpus = self.load()
        self.assertEqual(sorted(corpus.docs), ["docs/brief.md", "docs/frds/F01-example.md", "docs/pdrd.md",
                                               "docs/tasks/F01-example.md", "docs/tdds/F01-example.md"])
        self.assertEqual(corpus.broken, {})
        self.assertEqual(corpus.documents, 5)
        self.assertEqual(sorted(corpus.by_id), ["BRIEF", "FRD-F01", "PDRD", "TASKS-F01", "TDD-F01"])
        task_list = corpus.docs["docs/tasks/F01-example.md"].task_list
        self.assertEqual(list(task_list.tasks), ["T-F01-01", "T-F01-02"])
        self.assertIsNone(corpus.docs["docs/frds/F01-example.md"].task_list)

    def test_discovery_includes_completed_and_research(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02"]))
        self.write("frds/completed/F02-old.md", frd("F02"))
        self.write("research/interviews.md", research("RES-interviews"))
        self.write("research/completed/spike.md", research("spike"))
        self.write("completed/architecture.md", "---\nid: ARCH\n---\n")
        corpus = self.load()
        for path in ("docs/frds/completed/F02-old.md", "docs/research/interviews.md",
                     "docs/research/completed/spike.md", "docs/completed/architecture.md"):
            self.assertIn(path, corpus.docs)
        self.assertEqual(corpus.documents, 9)

    def test_document_places(self):
        for rel in ("brief.md", "pdrd.md", "architecture.md", "frds/F01-x.md", "tasks/completed/F01-x.md",
                    "research/a.md", "research/completed/a.md", "completed/brief.md"):
            self.assertTrue(is_document_place(rel), rel)
        for rel in ("notes.md", "frds/old/F01-x.md", "frds/completed/old/F01-x.md", "other/a.md",
                    "completed/x/a.md"):
            self.assertFalse(is_document_place(rel), rel)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlinks_skipped(self):
        outside = self.tmp / "outside.md"
        outside.write_text(frd("F01", id="FRD-F09"), encoding="utf-8")
        links = [self.repo.root / "docs" / "frds" / "F09-link.md", self.repo.root / "docs" / "linked"]
        try:
            os.symlink(outside, links[0])
            os.symlink(self.tmp, links[1], target_is_directory=True)
        except OSError:
            self.skipTest("can't create symlinks here")
        corpus = self.load()
        self.assertNotIn("docs/frds/F09-link.md", corpus.docs)
        self.assertNotIn("docs/frds/F09-link.md", corpus.broken)
        self.assertFalse(any(path.startswith("docs/linked/") for path in [*corpus.docs, *corpus.broken]))

    def test_stray_markdown_without_front_matter(self):
        self.write("notes.md", "# Notes\n\nSome notes.\n")
        self.write("notes/meeting.md", "# Meeting\n")
        self.write("frds/notes.md", "# Notes\n")
        corpus = self.load()
        self.assertNotIn("docs/notes.md", corpus.docs)
        self.assertNotIn("docs/notes.md", corpus.broken)
        self.assertNotIn("docs/notes/meeting.md", corpus.broken)
        finding = corpus.broken["docs/frds/notes.md"]
        self.assertEqual((finding.rule, finding.file, finding.line), ("front-matter", "docs/frds/notes.md", 1))
        self.assertEqual(finding.subject, "docs/frds/notes.md")

    def test_other_markdown_with_front_matter_is_a_document(self):
        self.write("notes/decision.md", research("decision-1"))
        self.assertIn("docs/notes/decision.md", self.load().docs)

    def test_unreadable_front_matter_and_text(self):
        self.write("frds/F01-example.md", "---\nid: FRD-F01\nstatus: [approved\n---\n")
        (self.repo.root / "docs" / "tdds" / "F01-example.md").write_bytes(b"---\nid: \xff\n---\n")
        corpus = self.load()
        self.assertEqual(corpus.broken["docs/frds/F01-example.md"].rule, "front-matter")
        self.assertEqual(corpus.broken["docs/tdds/F01-example.md"].rule, "front-matter")
        self.assertNotIn("docs/frds/F01-example.md", corpus.docs)
        self.assertEqual(corpus.documents, 5)

    def test_pdrd_features(self):
        self.write("pdrd.md", pdrd(features=["F01", "F02", "F123"]))
        corpus = self.load()
        self.assertEqual(corpus.features, {"F01", "F02", "F123"})
        self.assertTrue(corpus.pdrd_read)
        self.assertEqual(pdrd_features("### F01: A\n```\n### F02: example\n```\n#### F03: deeper\n### F4: short\n"),
                         {"F01"})

    def test_no_pdrd(self):
        self.repo.delete(self.repo.doc("pdrd.md"))
        corpus = self.load()
        self.assertFalse(corpus.pdrd_read)
        self.assertEqual(corpus.features, set())

    def test_field_and_approval_lines(self):
        text = self.write("frds/F01-example.md", frd("F01", approvals=[
            {"by": "alice", "role": "frd", "date": "2026-10-01", "version": 1},
            {"by": "bob", "role": "frd", "date": "2026-10-02", "version": 1}]))
        doc = self.load().docs["docs/frds/F01-example.md"]
        self.assertEqual(doc.line("id"), 2)
        self.assertEqual(doc.line("status"), line_of(text, "status:"))
        self.assertEqual(doc.line("nope"), 1)
        first = line_of(text, "  - {by: alice")
        self.assertEqual(doc.approval_lines, [first, first + 1])
        self.assertEqual(doc.body.strip().splitlines()[0], "# FRD-F01")

    def test_flow_style_approvals_share_a_line(self):
        self.write("brief.md", "---\nid: BRIEF\napprovals: [{by: a, role: brief, date: 2026-10-01, version: 1},"
                               " {by: b, role: brief, date: 2026-10-01, version: 1}]\n---\n")
        self.assertEqual(self.load().docs["docs/brief.md"].approval_lines, [3, 3])

    def test_rule2_line(self):
        warning = "> ⚠️ Drafted from an unapproved parent (FRD-F01 v1, status in-review)."
        self.write("tdds/F01-example.md", frd("F01", id="TDD-F01", body=f"# TDD-F01\n\n{warning}\n\nText.\n"))
        self.write("frds/F01-example.md", frd("F01", body=f"# FRD-F01\n\nText.\n\n{warning}\n"))
        corpus = self.load()
        self.assertTrue(corpus.docs["docs/tdds/F01-example.md"].rule2_line)
        self.assertFalse(corpus.docs["docs/frds/F01-example.md"].rule2_line)
        self.assertFalse(corpus.docs["docs/brief.md"].rule2_line)

    def test_docs_dir_setting(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = clean_project(PlanRepo(tmp.name, git=False, docs_dir="planning"))
        self.assertIn("planning/tasks/F01-example.md", load_corpus(repo.root).docs)

    def test_missing_docs_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = PlanRepo(tmp.name, git=False)
        self.assertEqual(load_corpus(repo.root).documents, 0)

    def test_task_list_missing_a_list_field(self):
        self.write("tasks/F01-example.md", tasks("F01", version=None))
        finding = self.load().broken["docs/tasks/F01-example.md"]
        self.assertEqual((finding.rule, finding.subject), ("front-matter", "TASKS-F01"))


if __name__ == "__main__":
    unittest.main()
