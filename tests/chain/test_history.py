"""Tests for lib/speckled_chain/history.py, on real git histories [T-F08-08].

The linter runs git with the caller's environment, so each test runs it with the
fixtures' isolated one: the user's own git config can't change what's read.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speckled_chain import GitError, lint
from speckled_chain import history as history_module
from speckled_chain.cli import main
from speckled_chain.history import entry_keys, open_history

from .fixtures import (CLEAN_COMMITS, PlanRepo, approval, clean_project, frd, git_env, research, task,
                       tasks, tdd)

FRD = "docs/frds/F01-example.md"
TDD = "docs/tdds/F01-example.md"


class HistoryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, git_env(self.tmp), clear=True)
        env.start()
        self.addCleanup(env.stop)

    def project(self, git: bool = True) -> PlanRepo:
        self.repo = clean_project(PlanRepo(self.tmp, git=git))
        return self.repo

    def history(self, root=None):
        return open_history(root or self.repo.root, "docs")

    def changes_in(self, history, sha):
        return [c for c in history.changes if c.commit is not None and c.commit.sha == sha]

    def merge_conflicted(self, branch: str, resolution: dict[str, str], message: str) -> str:
        """Merge `branch`, expecting a conflict; write `resolution` (path -> text) and commit it."""
        with self.assertRaises(subprocess.CalledProcessError):
            self.repo.git("merge", "-q", "--no-ff", "-m", message, branch)
        for path, text in resolution.items():
            self.repo.write(path, text)
        return self.repo.commit(message)


class Availability(HistoryTest):
    def test_plain_folder_is_a_warning(self):
        self.project(git=False)
        history = self.history()
        self.assertEqual(history.status, "none")
        self.assertEqual([(f.rule, f.severity) for f in history.findings], [("history-unavailable", "warning")])
        report = lint(self.repo.root)
        self.assertEqual((report.history, report.commits, report.exit_code()), ("none", 0, 0))

    def test_shallow_clone_is_an_error(self):
        self.project()
        clone = self.repo.shallow_clone(self.tmp / "clone")
        history = self.history(clone)
        self.assertEqual(history.status, "shallow")
        self.assertEqual([(f.rule, f.severity) for f in history.findings], [("history-unavailable", "error")])
        self.assertIn("fetch-depth: 0", history.findings[0].message)
        self.assertEqual(lint(clone).exit_code(), 1)

    def test_empty_repo_has_no_changes(self):
        repo = PlanRepo(self.tmp)
        repo.write(repo.doc("frds/F01-example.md"), frd())
        history = self.history(repo.root)
        self.assertEqual((history.status, history.commits, history.changes, history.findings), ("full", [], [], []))
        self.assertEqual(history.added_in({"FRD-F01": entry_keys(None)}), {})

    def test_full_history_in_the_report(self):
        self.project()
        report = lint(self.repo.root)
        self.assertEqual((report.history, report.commits, report.findings), ("full", CLEAN_COMMITS, []))

    def test_git_missing_in_a_repo(self):
        self.project()
        with mock.patch.object(history_module.subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(GitError) as raised:
                self.history()
        self.assertIn("isn't installed", str(raised.exception))

    def test_git_missing_outside_a_repo(self):
        self.project(git=False)
        with mock.patch.object(history_module.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertEqual(self.history().status, "none")

    def test_git_failing_part_way(self):
        # A missing object, as in a corrupt repo: no partial history.
        self.project()
        blob = self.repo.git("rev-parse", f"HEAD:{TDD}").strip()
        (self.repo.root / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
        with self.assertRaises(GitError) as raised:
            self.history()
        self.assertEqual(raised.exception.command, "git cat-file")
        with mock.patch("sys.stderr"), mock.patch("sys.stdout") as stdout:
            self.assertEqual(main(["--project", str(self.repo.root)]), 2)
        stdout.write.assert_not_called()   # no partial report


class Commits(HistoryTest):
    def test_commits_and_changes(self):
        self.project()
        history = self.history()
        self.assertEqual(len(history.commits), CLEAN_COMMITS)
        first = history.commits[0]
        self.assertEqual((first.parents, first.author, first.date), ((), "Fixture Author", "2026-10-01"))
        self.assertEqual([c.doc for c in history.changes],
                         ["BRIEF", "PDRD", "FRD-F01", "TDD-F01", "TASKS-F01"])
        self.assertTrue(all(c.old is None and c.new is not None for c in history.changes))
        tasks_version = history.changes[-1].new
        self.assertEqual(list(tasks_version.task_list.tasks), ["T-F01-01", "T-F01-02"])
        self.assertTrue(tasks_version.body.lstrip().startswith("# TASKS-F01"))

    def test_author_names_never_emails(self):
        self.project()
        self.repo.write(FRD, frd(version=2, approvals=[approval("frd"), approval("frd", version=2)]))
        sha = self.repo.commit("Approve v2", author="bob")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual(change.commit.author, "bob")
        self.assertNotIn("@", repr(self.history().commits))

    def test_config_and_log_blobs(self):
        self.project()
        history = self.history()
        first = history.commits[0].sha
        self.assertIn(b"roles:", history.reader.read(history.config_blob(first)))
        (log,) = history.log_changes
        self.assertEqual((log.commit.sha, log.old), (history.commits[-1].sha, None))
        self.assertIn(b'"mode": "warn"', history.reader.read(log.new))

    def test_sha256_repository(self):
        # Working-tree blob IDs are computed here, so they must match git's in either format.
        try:
            self.repo = clean_project(PlanRepo(self.tmp, object_format="sha256"))
        except subprocess.CalledProcessError:
            self.skipTest("this git can't create SHA-256 repositories")
        history = self.history()
        self.assertEqual(len(history.commits[0].sha), 64)
        self.assertEqual([c for c in history.changes if c.commit is None], [])
        self.repo.write(FRD, frd(status="in-review", version=2))
        (change,) = [c for c in self.history().changes if c.commit is None]
        self.assertEqual((change.doc, len(change.old.blob), len(change.new.blob)), ("FRD-F01", 64, 64))

    def test_planning_repo_inside_a_larger_repository(self):
        self.repo = clean_project(PlanRepo(self.tmp, nested=True))
        outer = self.repo.git_root
        (outer / "docs").mkdir()
        (outer / "docs" / "outside.md").write_text(frd("F09"), encoding="utf-8")
        (outer / "speckled.yaml").write_text("project: other\n", encoding="utf-8")
        self.repo.commit("Files outside the planning repo")
        (outer / "docs" / "outside.md").write_text(frd("F09", status="draft"), encoding="utf-8")

        history = self.history()
        self.assertEqual(len(history.commits), CLEAN_COMMITS)
        self.assertEqual([c.new.path for c in history.changes],
                         ["docs/brief.md", "docs/pdrd.md", FRD, TDD, "docs/tasks/F01-example.md"])
        self.assertIn(b"roles:", history.reader.read(history.config_blob(history.commits[-1].sha)))
        self.assertEqual(lint(self.repo.root).findings, [])

    def test_head_that_touched_nothing_tracked(self):
        self.project()
        self.repo.write("notes.txt", "unrelated\n")
        self.repo.commit("Unrelated")
        history = self.history()
        self.assertEqual(len(history.commits), CLEAN_COMMITS)
        self.assertEqual([c for c in history.changes if c.commit is None], [])


class Identity(HistoryTest):
    def test_move_to_completed_with_an_edit(self):
        self.project()
        self.repo.move(TDD, "docs/tdds/completed/F01-example.md")
        self.repo.write("docs/tdds/completed/F01-example.md", tdd(status="done"))
        sha = self.repo.commit("Complete F01")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual((change.doc, change.old.path, change.new.path),
                         ("TDD-F01", TDD, "docs/tdds/completed/F01-example.md"))
        self.assertEqual((change.old.meta["status"], change.new.meta["status"]), ("approved", "done"))

    def test_rename(self):
        self.project()
        self.repo.move(FRD, "docs/frds/F01-renamed.md")
        sha = self.repo.commit("Rename")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual((change.doc, change.new.path), ("FRD-F01", "docs/frds/F01-renamed.md"))

    def test_research_note_is_tracked_by_path_across_a_rename(self):
        self.project()
        self.repo.write("docs/research/a.md", research("R-1", body="# R-1\n\n" + "Findings line.\n" * 20))
        self.repo.commit("Research")
        self.repo.move("docs/research/a.md", "docs/research/b.md")
        self.repo.write("docs/research/b.md", research("R-2", body="# R-1\n\n" + "Findings line.\n" * 20))
        sha = self.repo.commit("Rename research, new id")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual((change.doc, change.old.id, change.new.id), ("docs/research/a.md", "R-1", "R-2"))

    def test_real_deletion(self):
        self.project()
        self.repo.delete(FRD)
        sha = self.repo.commit("Delete")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual((change.doc, change.old.path, change.new), ("FRD-F01", FRD, None))

    def test_deleted_path_whose_id_is_still_in_the_tree(self):
        self.project()
        self.repo.write("docs/frds/F01-copy.md", frd())
        self.repo.commit("Copy")
        self.repo.delete(FRD)
        sha = self.repo.commit("Delete the original")
        (change,) = self.changes_in(self.history(), sha)
        self.assertEqual((change.doc, change.old.path, change.new.path), ("FRD-F01", FRD, "docs/frds/F01-copy.md"))

    def test_symlinks_and_submodules_are_not_documents(self):
        self.project()
        link = self.repo.root / "docs/frds/F02-link.md"
        os.symlink("F01-example.md", link)
        self.repo.commit("A symlinked document")
        # A submodule entry, written straight into the index: no second repository needed.
        sha = self.repo.head()
        self.repo.git("update-index", "--add", "--cacheinfo", f"160000,{sha},docs/research/sub.md")
        self.repo.git("commit", "-q", "-m", "A submodule")
        history = self.history()
        paths = {v.path for c in history.changes for v in (c.old, c.new) if v is not None}
        self.assertFalse({"docs/frds/F02-link.md", "docs/research/sub.md"} & paths, paths)
        self.assertEqual([c for c in history.changes if c.commit is None], [])

    def test_hostile_file_names(self):
        self.project()
        name = "docs/research/-x y\nz é.md"
        self.repo.write(name, research("R-hostile"))
        added = self.repo.commit("Add")
        self.repo.move(name, "docs/research/--moved.md")
        moved = self.repo.commit("Move")
        history = self.history()
        (add,) = self.changes_in(history, added)
        (move,) = self.changes_in(history, moved)
        self.assertEqual((add.doc, add.new.path), (name, name))
        self.assertEqual((move.doc, move.old.path, move.new.path), (name, name, "docs/research/--moved.md"))


class Merges(HistoryTest):
    def append(self, *entries, author=None) -> str:
        self.repo.write(FRD, frd(approvals=[approval("frd"), *entries]))
        return self.repo.commit("Approve", author=author)

    def test_entry_appended_on_a_branch_and_merged(self):
        self.project()
        self.repo.git("checkout", "-q", "-b", "side")
        entry = approval("frd", by="bob", date="2026-10-03")
        added = self.append(entry)
        self.repo.checkout("main")
        self.repo.write("docs/research/r.md", research("R-1"))
        self.repo.commit("Unrelated on main")
        merge = self.repo.merge("side")
        history = self.history()
        frd_version = self.changes_in(history, merge)[0].new
        keys = entry_keys(frd_version)
        commits = history.added_in({"FRD-F01": keys})
        self.assertEqual(commits[("FRD-F01", keys[0])].sha, history.commits[2].sha)   # the FRD's first commit
        self.assertEqual(commits[("FRD-F01", keys[1])].sha, added)
        self.assertTrue(next(c for c in history.commits if c.sha == merge).is_merge)

    def test_concurrent_approvals_merged_with_a_conflict(self):
        self.project()
        x = approval("frd", by="xavier", date="2026-10-03")
        y = approval("frd", by="yolanda", date="2026-10-04")
        z = approval("frd", by="zed", date="2026-10-05")
        self.repo.branch("y")
        self.repo.git("checkout", "-q", "-b", "x")
        added_x = self.append(x)
        self.repo.checkout("y")
        added_y = self.append(y)
        self.repo.checkout("main")
        self.repo.merge("x")
        # Resolving the conflict keeps both, and adds a third entry that neither branch had.
        merge = self.merge_conflicted("y", {FRD: frd(approvals=[approval("frd"), x, y, z])}, "Merge y")

        history = self.history()
        (change,) = self.changes_in(history, merge)
        old, new = entry_keys(change.old), entry_keys(change.new)
        # Compared with the first parent only: the old entries are an unchanged prefix.
        self.assertEqual(new[:len(old)], old)
        self.assertEqual(len(old), 2)
        commits = history.added_in({"FRD-F01": new})
        self.assertEqual([commits[("FRD-F01", k)].sha for k in new[1:]], [added_x, added_y, merge])

    def test_uncommitted_entries(self):
        self.project()
        self.repo.write(FRD, frd(approvals=[approval("frd"), approval("frd", by="carol")]))
        history = self.history()
        (change,) = [c for c in history.changes if c.commit is None]
        self.assertEqual((change.doc, change.old.path, change.new.path), ("FRD-F01", FRD, FRD))
        keys = entry_keys(change.new)
        commits = history.added_in({"FRD-F01": keys})
        self.assertIsNotNone(commits[("FRD-F01", keys[0])])
        self.assertIsNone(commits[("FRD-F01", keys[1])])

    def test_approved_by_lines_have_keys(self):
        self.project()
        self.repo.write("docs/tasks/F01-example.md", tasks(tasks=[
            task("T-F01-01", "Done", approved_by=["Approved by alice on 2026-10-02 (first)"]),
            task("T-F01-02", "Done", approved_by=["Approved by alice on 2026-10-03"])]))
        sha = self.repo.commit("Approve T-F01-02")
        history = self.history()
        (change,) = self.changes_in(history, sha)
        new = [k for k in entry_keys(change.new) if k[0] == "approved-by"]
        self.assertEqual(new[1], ("approved-by", "T-F01-02", "alice", "2026-10-03", None))
        self.assertEqual(history.added_in({"TASKS-F01": [new[1]]})[("TASKS-F01", new[1])].sha, sha)


class Safety(HistoryTest):
    ALLOWED = (["git", "rev-parse", "--is-inside-work-tree"],
               ["git", "rev-parse", "--is-shallow-repository"],
               ["git", "rev-parse", "--verify", "-q", "HEAD"],
               ["git", "cat-file", "--batch"])

    def test_only_the_allowed_commands_run(self):
        self.project()
        self.repo.write(FRD, frd(status="in-review", version=2))   # a working-tree change too
        calls = []
        real_popen = subprocess.Popen

        def popen(args, *a, **kw):
            calls.append(list(args))
            return real_popen(args, *a, **kw)

        # `subprocess.run` starts its process through `Popen` too, so this records every command.
        with mock.patch.object(history_module.subprocess, "Popen", popen):
            self.history()
        logs = [c for c in calls if c[:4] == ["git", "-c", "core.quotepath=off", "log"]]
        self.assertEqual(len(logs), 1)
        self.assertIn("--", logs[0])
        self.assertEqual(calls.count(["git", "cat-file", "--batch"]), 1)
        for call in calls:
            self.assertTrue(call in self.ALLOWED or call in logs, call)

    def test_repo_config_never_runs(self):
        self.project()
        marker = self.tmp / "marker"
        command = f"touch '{marker}'; cat"
        for key in ("diff.md.textconv", "filter.evil.clean", "filter.evil.smudge", "filter.evil.process",
                    "core.fsmonitor"):
            self.repo.git("config", key, command)
        self.repo.write(".gitattributes", "*.md diff=md filter=evil\n")
        self.repo.write(FRD, frd(status="in-review", version=2))
        self.history()
        lint(self.repo.root)
        self.assertFalse(marker.exists())
        # The trap works: a command the linter never uses would have run it.
        self.repo.git("diff")
        self.assertTrue(marker.exists())

    def test_each_blob_is_read_once(self):
        self.project()
        self.repo.write(TDD, tdd(version=2, approvals=[approval("tdd"), approval("tdd", version=2)]))
        self.repo.commit("Approve v2")
        self.repo.move(TDD, "docs/tdds/completed/F01-example.md")   # same blob, new path
        self.repo.commit("Move")
        history = self.history()
        requests = history.reader.requests
        self.assertEqual(len(requests), len(set(requests)))
        blobs = {v.blob for c in history.changes for v in (c.old, c.new) if v is not None and c.commit}
        self.assertTrue(blobs <= set(requests))


if __name__ == "__main__":
    unittest.main()
