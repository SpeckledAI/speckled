"""Tests for `speckled_chain` as a library: `lint`, `chain_for` and scoping [T-F08-12].

Another tool calls `lint(root, scope=chain_for(load_corpus(root), task))` to check one
task's chain. These check that a library call and the command give the same
findings, that a scoped run keeps exactly a full run's findings for its documents,
and that narrowing the history never changes what's found.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import speckled_chain.history as history_module
from speckled_chain import ConfigError, GitError, chain_for, lint, load_corpus
from speckled_chain.history import _glob_matcher, glob_escape, open_history
from speckled_chain.scope import Scope

from .fixtures import LOG, PlanRepo, approval, clean_project, frd, git_env, log_line, pdrd, task, tasks, tdd
from .test_cli import BIN

FRD = "docs/frds/F01-example.md"
TDD = "docs/tdds/F01-example.md"
TASKS = "docs/tasks/F01-example.md"
CHAIN = {"TASKS-F01", "TDD-F01", "FRD-F01", "PDRD", "BRIEF", "T-F01-01", "T-F01-02"}


class Library(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.env = git_env(self.tmp)
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.repo = clean_project(PlanRepo(self.tmp))

    def two_features(self) -> None:
        """A second feature, F02, and a fault in each feature, in the log and in the project."""
        self.repo.write(self.repo.doc("pdrd.md"), pdrd(features=["F01", "F02"], version=2,
                                                       approvals=[approval("pdrd"), approval("pdrd", version=2)]))
        self.repo.write(self.repo.doc("frds/F02-other.md"), frd("F02", status="in-review", approvals=[]))
        self.repo.write(self.repo.doc("tdds/F02-other.md"), tdd("F02"))
        self.repo.write(self.repo.doc("tasks/F02-other.md"), tasks("F02", tasks=[task("T-F02-01", depends_on=["T-F09-01"])]))
        # PDRD v2's approval is recorded on a gate `roles` no longer lists: a project-wide warning.
        self.repo.write("speckled.yaml", (self.repo.root / "speckled.yaml").read_text(encoding="utf-8")
                        .replace('  pdrd: ["alice"]\n', ""))
        self.repo.commit("Add F02")
        self.repo.write(FRD, frd(approvals=[]))
        self.repo.write(LOG, (self.repo.root / LOG).read_text(encoding="utf-8") + "not json\n")
        self.repo.commit("Faults")

    @staticmethod
    def keys(findings):
        return [json.dumps(f.to_json(), sort_keys=True) for f in findings]

    # --- the library and the command agree ---------------------------------------------

    def test_lint_and_the_command_give_the_same_findings(self):
        self.two_features()
        for argv, kwargs in (((), {}), (("--docs",), {"history": False}), (("--feature", "F02"), {"feature": "F02"})):
            with self.subTest(argv=argv):
                out = subprocess.run([sys.executable, str(BIN), "--json", *argv], cwd=self.repo.root,
                                     env=self.env, capture_output=True, text=True, timeout=60)
                self.assertEqual(json.loads(out.stdout), lint(self.repo.root, **kwargs).to_json())

    # --- scope -------------------------------------------------------------------------

    def test_scope_covers_only_that_chain(self):
        self.two_features()
        scope = chain_for(load_corpus(self.repo.root), "T-F01-02")
        self.assertEqual(scope, ["TASKS-F01", "TDD-F01", "FRD-F01", "PDRD", "BRIEF"])
        scoped = lint(self.repo.root, scope=scope)
        full = lint(self.repo.root)
        self.assertEqual(self.keys(scoped.findings), self.keys([f for f in full.findings if f.subject in CHAIN]))
        self.assertEqual([f.rule for f in scoped.findings], ["approval-removed"])
        self.assertEqual(scoped.documents, 5)
        # The full run does see the other feature, the log and the project-wide finding.
        self.assertTrue({"TDD-F02", "T-F02-01", LOG, "speckled.yaml"} <= {f.subject for f in full.findings})

    def test_feature_keeps_a_full_runs_findings_for_it(self):
        self.two_features()
        full = lint(self.repo.root)
        for feature in ("F01", "F02"):
            with self.subTest(feature=feature):
                ids = {f"FRD-{feature}", f"TDD-{feature}", f"TASKS-{feature}"}
                expected = [f for f in full.findings if f.subject in ids or f.subject.startswith(f"T-{feature}-")]
                self.assertEqual(self.keys(lint(self.repo.root, feature=feature).findings), self.keys(expected))

    def test_feature_and_scope_together(self):
        self.two_features()
        report = lint(self.repo.root, feature="F02", scope=["TDD-F02", "PDRD"])
        self.assertEqual([(f.rule, f.subject) for f in report.findings], [("parent-unapproved", "TDD-F02")])

    def test_unreadable_file_in_scope(self):
        self.repo.write(self.repo.doc("frds/F01-example.md"), "# FRD-F01\n\nNo front matter.\n")
        findings = lint(self.repo.root, feature="F01").findings
        self.assertIn(("front-matter", FRD), [(f.rule, f.subject) for f in findings])

    def test_history_unavailable_is_always_kept(self):
        clone = self.repo.shallow_clone(self.tmp / "clone")
        report = lint(clone, feature="F01")
        self.assertEqual([(f.rule, f.severity) for f in report.findings], [("history-unavailable", "error")])
        self.assertEqual(report.exit_code(), 1)

    # --- the narrowed history ----------------------------------------------------------

    def test_history_is_narrowed_to_the_scoped_documents(self):
        self.two_features()
        calls = []
        real_run = subprocess.run

        def run(args, *a, **kw):
            calls.append(list(args))
            return real_run(args, *a, **kw)

        with mock.patch.object(history_module.subprocess, "run", run):
            report = lint(self.repo.root, feature="F02")
        (log,) = [c for c in calls if "log" in c]
        specs = log[log.index("--") + 1:]
        self.assertEqual(specs, [":(glob)docs/completed/F02-*.md", ":(glob)docs/frds/F02-*.md",
                                 ":(glob)docs/frds/completed/F02-*.md", ":(glob)docs/tasks/F02-*.md",
                                 ":(glob)docs/tasks/completed/F02-*.md", ":(glob)docs/tdds/F02-*.md",
                                 ":(glob)docs/tdds/completed/F02-*.md", "speckled.yaml", LOG])
        self.assertLess(report.commits, lint(self.repo.root).commits)

    def test_move_through_a_path_outside_the_globs(self):
        # FRD-F01 goes through a misnamed path: the narrowed history alone sees a deletion.
        self.repo.move(FRD, "docs/frds/misnamed.md")
        self.repo.commit("Move it somewhere odd")
        self.repo.move("docs/frds/misnamed.md", "docs/frds/F01-final.md")
        self.repo.commit("And back")
        globs = Scope.of(load_corpus(self.repo.root), "F01").globs
        narrowed = open_history(self.repo.root, "docs", only=globs)
        self.assertTrue(any(c.new is None and c.doc == "FRD-F01" for c in narrowed.changes))
        # So lint reads the whole history, which follows the move.
        self.assertEqual(lint(self.repo.root, feature="F01").findings, [])

    def test_real_deletion_in_scope(self):
        self.repo.delete(TASKS)
        self.repo.commit("Delete the task list")
        findings = lint(self.repo.root, feature="F01").findings
        self.assertEqual([(f.rule, f.subject) for f in findings], [("document-deleted", "TASKS-F01")])

    def test_move_to_completed_in_scope(self):
        self.repo.move(TDD, "docs/tdds/completed/F01-example.md")
        self.repo.move(FRD, "docs/frds/completed/F01-example.md")
        self.repo.commit("Complete F01")
        report = lint(self.repo.root, feature="F01")
        self.assertEqual(report.findings, [])

    def test_globs_match_as_git_does(self):
        matches = _glob_matcher(["docs/frds/F01-*.md", glob_escape("docs/odd [x]*?.md")])
        self.assertTrue(matches("docs/frds/F01-example.md"))
        self.assertFalse(matches("docs/frds/sub/F01-example.md"))   # `*` stays within one folder
        self.assertFalse(matches("docs/frds/F010-example.md"))
        self.assertTrue(matches("docs/odd [x]*?.md"))
        self.assertFalse(matches("docs/odd x-anything.md"))
        self.assertFalse(_glob_matcher([])("docs/brief.md"))

    def test_odd_file_names_in_scope(self):
        odd = "docs/frds/F01 [draft]*.md"
        self.repo.move(FRD, odd)
        self.repo.commit("An odd name")
        self.repo.write(odd, frd(approvals=[]))
        self.repo.commit("Remove the approval")
        rules = [(f.rule, f.file) for f in lint(self.repo.root, feature="F01").findings]
        self.assertIn(("approval-removed", odd), rules)

    # --- couldn't run ------------------------------------------------------------------

    def test_lint_raises_where_the_command_exits_2(self):
        (self.repo.root / "speckled.yaml").write_text("project: example\nroles: [alice]\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            lint(self.repo.root)
        self.repo.git("checkout", "--", "speckled.yaml")
        blob = self.repo.git("rev-parse", f"HEAD:{TDD}").strip()
        (self.repo.root / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
        with self.assertRaises(GitError):
            lint(self.repo.root)
        with self.assertRaises(GitError):
            lint(self.repo.root, feature="F01")
        self.assertEqual(lint(self.repo.root, history=False).history, "none")   # no git, so no failure


if __name__ == "__main__":
    unittest.main()
