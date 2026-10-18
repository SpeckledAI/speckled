"""Tests for tests/chain/fixtures.py [T-F08-04].

Later tests trust these fixtures to build the history they describe, and to build it
the same way on every machine, whatever the user's own git config says.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speckled_gate.docs import front_matter, parse_task_list

from . import fixtures
from .fixtures import SENTINEL, PlanRepo, clean_project

HERE = Path(__file__).resolve().parent


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def subdir(self, name: str) -> Path:
        folder = self.tmp / name
        folder.mkdir()
        return folder


class CleanProject(Fixture):
    def test_commits_and_files(self):
        repo = clean_project(PlanRepo(self.tmp))
        self.assertEqual(int(repo.git("rev-list", "--count", "HEAD")), fixtures.CLEAN_COMMITS)
        self.assertEqual(set(repo.git("ls-files").splitlines()), fixtures.CLEAN_FILES)
        self.assertEqual(repo.git("status", "--porcelain"), "")

    def test_documents_parse_with_the_gates_parser(self):
        repo = clean_project(PlanRepo(self.tmp))
        for rel in fixtures.CLEAN_FILES - {"speckled.yaml", ".speckled/log.jsonl"}:
            with self.subTest(rel):
                text = (repo.root / rel).read_text(encoding="utf-8")
                meta = front_matter(text)
                self.assertIn(SENTINEL, meta["title"])
                self.assertIn(SENTINEL, text.split("---", 2)[2])
                self.assertEqual(meta["status"], "approved")
                self.assertEqual(meta["approvals"], [{"by": "alice", "role": meta["type"],
                                                      "date": "2026-10-01", "version": 1}])
        task_list = parse_task_list((repo.root / "docs/tasks/F01-example.md").read_text(encoding="utf-8"),
                                    "docs/tasks/F01-example.md")
        done, started = task_list.tasks.values()
        self.assertEqual((done.id, done.status, started.status, started.depends_on),
                         ("T-F01-01", "Done", "In progress", ["T-F01-01"]))
        self.assertEqual([(a.name, a.date) for a in done.approved_by], [("alice", "2026-10-02")])
        self.assertIn(SENTINEL, done.approved_by[0].note)
        log = (repo.root / ".speckled/log.jsonl").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'"mode": "(\w+)"', log), ["warn", "block"])

    def test_plain_folder(self):
        repo = clean_project(PlanRepo(self.tmp, git=False))
        self.assertFalse((repo.root / ".git").exists())
        self.assertTrue((repo.root / "docs/tasks/F01-example.md").is_file())
        with self.assertRaises(RuntimeError):
            repo.commit("nope")


class FixedAuthorsAndDates(Fixture):
    def test_every_commit(self):
        repo = clean_project(PlanRepo(self.tmp))
        repo.write("docs/research/r1.md", fixtures.research("R-ONE"))
        repo.commit("Research", author="bob")
        rows = [line.split("|") for line in
                repo.git("log", "--reverse", "--format=%an|%ae|%cn|%ce|%at|%ct").splitlines()]
        self.assertEqual(len(rows), fixtures.CLEAN_COMMITS + 1)
        for i, (an, ae, cn, ce, at, ct) in enumerate(rows):
            with self.subTest(commit=i):
                self.assertEqual(an, "bob" if i == len(rows) - 1 else fixtures.AUTHOR[0])
                self.assertEqual((ae, cn, ce), (fixtures.AUTHOR[1], *fixtures.COMMITTER))
                self.assertEqual(int(at), fixtures.BASE_TIME + 60 * i)
                self.assertEqual(at, ct)

    def test_same_history_every_run(self):
        first = clean_project(PlanRepo(self.subdir("a")))
        second = clean_project(PlanRepo(self.subdir("b")))
        self.assertEqual(first.head(), second.head())


class HistoryShapes(Fixture):
    def test_move_delete_branch_merge(self):
        repo = clean_project(PlanRepo(self.tmp))
        repo.move("docs/frds/F01-example.md", "docs/frds/completed/F01-example.md")
        repo.delete("docs/tdds/F01-example.md")
        repo.commit("Move and delete")
        files = set(repo.git("ls-files").splitlines())
        self.assertIn("docs/frds/completed/F01-example.md", files)
        self.assertNotIn("docs/tdds/F01-example.md", files)

        repo.branch("side")
        repo.checkout("side")
        repo.write("docs/research/side.md", fixtures.research("R-SIDE"))
        repo.commit("Side")
        repo.checkout("main")
        repo.write("docs/research/main.md", fixtures.research("R-MAIN"))
        repo.commit("Main")
        merge = repo.merge("side")
        self.assertEqual(len(repo.git("rev-list", "--parents", "-n", "1", merge).split()), 3)
        self.assertTrue((repo.root / "docs/research/side.md").is_file())

    def test_shallow_clone(self):
        repo = clean_project(PlanRepo(self.tmp))
        clone = repo.shallow_clone(self.tmp / "clone")
        is_shallow = fixtures.git(clone, "rev-parse", "--is-shallow-repository", home=self.tmp).strip()
        self.assertEqual(is_shallow, "true")
        self.assertEqual(int(fixtures.git(clone, "rev-list", "--count", "HEAD", home=self.tmp)), 1)
        self.assertEqual(repo.git("rev-parse", "--is-shallow-repository").strip(), "false")

    def test_empty_repo(self):
        repo = PlanRepo(self.tmp)
        self.assertEqual(repo.git("rev-parse", "--is-inside-work-tree").strip(), "true")
        self.assertEqual(repo.git("rev-list", "--all"), "")


class Isolation(Fixture):
    def user_home(self) -> Path:
        """A HOME whose git config would break every commit if it leaked in."""
        home = self.tmp / "user-home"
        hooks = home / "hooks"
        hooks.mkdir(parents=True)
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        (home / ".gitconfig").write_text(
            f"[core]\n\thooksPath = {hooks}\n[commit]\n\tgpgsign = true\n"
            "[user]\n\tname = Leaked User\n\temail = leak@example.invalid\n", encoding="utf-8")
        return home

    def test_user_config_has_no_effect(self):
        home = self.user_home()
        with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home)}):
            repo = clean_project(PlanRepo(self.subdir("work")))
            # The leaked hook exits 1 and gpgsign has no key: either would fail a commit.
            self.assertEqual(int(repo.git("rev-list", "--count", "HEAD")), fixtures.CLEAN_COMMITS)
            self.assertNotIn("Leaked", repo.git("log", "--format=%an %cn"))
            origins = repo.git("config", "--list", "--show-origin")
            self.assertNotIn(str(home), origins)

    def test_inherited_git_variables_are_ignored(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        with mock.patch.dict(os.environ, {"GIT_DIR": str(elsewhere), "GIT_WORK_TREE": str(elsewhere)}):
            repo = clean_project(PlanRepo(self.tmp))
        self.assertTrue((repo.root / ".git").is_dir())
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_only_under_the_temporary_folder(self):
        with self.assertRaises(ValueError):
            PlanRepo(HERE)


class NoShell(unittest.TestCase):
    def test_no_test_runs_git_through_a_shell(self):
        for path in sorted(HERE.glob("*.py")):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("shell" + "=True", text)
                self.assertNotIn("os." + "system", text)
                self.assertNotIn("os." + "popen", text)


if __name__ == "__main__":
    unittest.main()
