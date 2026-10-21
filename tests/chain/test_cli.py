"""Tests for lib/speckled_chain/cli.py and bin/lint-chain [T-F08-03, T-F08-12].

These run `bin/lint-chain` as a subprocess, as a user or CI would. `Cli` uses a
minimal project. `EndToEnd` builds the clean fixture project with real git history,
and `SeededFaults` seeds each fault the linter must catch into its own copy, checking
the rule, file and line it's reported at.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .fixtures import (LOG, SENTINEL, PlanRepo, approval, clean_project, frd, git_env, log_line, pdrd, task,
                       tasks, tdd)
from .test_corpus import line_of

BIN = Path(__file__).resolve().parents[2] / "bin" / "lint-chain"
FRD = "docs/frds/F01-example.md"
TDD = "docs/tdds/F01-example.md"
TASKS = "docs/tasks/F01-example.md"
RULE2 = "> ⚠️ Drafted from an unapproved parent (FRD-F01 v1, status in-review)."
EDITED = "# FRD-F01\n\nA changed requirement.\n"


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.plans = self.tmp / "plans"
        (self.plans / "docs").mkdir(parents=True)
        (self.plans / "speckled.yaml").write_text("project: example\nroles:\n  code: [alice]\n", encoding="utf-8")

    def run_cli(self, *argv, cwd=None):
        return subprocess.run([sys.executable, str(BIN), *argv], cwd=cwd or self.plans,
                              capture_output=True, text=True, timeout=30)

    def test_no_speckled_yaml(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        out = self.run_cli(cwd=empty)
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stdout, "")
        self.assertEqual(len(out.stderr.splitlines()), 1)
        self.assertIn("no speckled.yaml in", out.stderr)
        self.assertIn("Run it from the planning repo.", out.stderr)

    def test_project_without_speckled_yaml(self):
        out = self.run_cli("--project", str(self.tmp))
        self.assertEqual(out.returncode, 2)
        self.assertEqual(len(out.stderr.splitlines()), 1)

    def test_bad_roles(self):
        (self.plans / "speckled.yaml").write_text("project: example\nroles: [alice]\n", encoding="utf-8")
        out = self.run_cli()
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stderr.splitlines(), [out.stderr.strip()])
        self.assertIn("line 2", out.stderr)

    def test_explain(self):
        out = self.run_cli("--explain", "front-matter", cwd=self.tmp)  # needs no project
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.startswith("front-matter (default severity: error)"))
        self.assertIn("Fix: ", out.stdout)

    def test_explain_unknown_rule(self):
        out = self.run_cli("--explain", "nope")
        self.assertEqual(out.returncode, 64)
        self.assertIn("unknown rule 'nope'", out.stderr)

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("--feature", "F8").returncode, 64)
        self.assertEqual(self.run_cli("--nope").returncode, 64)
        self.assertEqual(self.run_cli("--feature", "F08").returncode, 0)

    def test_help(self):
        out = self.run_cli("--help")
        self.assertEqual(out.returncode, 0)
        self.assertIn("--explain", out.stdout)

    def test_minimal_project(self):
        # A plain folder: history has its own tests [T-F08-08].
        out = self.run_cli("--docs")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("speckled lint-chain: example", out.stdout)
        self.assertTrue(out.stdout.endswith("No problems found.\n"))

    def test_from_a_subfolder(self):
        self.assertEqual(self.run_cli(cwd=self.plans / "docs").returncode, 0)

    def test_json(self):
        out = self.run_cli("--json", "--docs", "--strict")
        self.assertEqual(out.returncode, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["project"], "example")
        self.assertEqual(data["findings"], [])

    def test_output(self):
        target = self.tmp / "report.json"
        out = self.run_cli("--docs", "--output", str(target))
        self.assertEqual(out.returncode, 0)
        self.assertIn("No problems found.", out.stdout)  # text still printed
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["tool"], "lint-chain")

    def test_output_failure_after_text(self):
        out = self.run_cli("--docs", "--output", str(self.tmp / "missing" / "report.json"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("No problems found.", out.stdout)
        self.assertEqual(len(out.stderr.splitlines()), 1)



class Project(unittest.TestCase):
    """The clean fixture project, with git, and `bin/lint-chain` run on it."""

    warn = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.env = git_env(self.tmp)
        self.repo = clean_project(PlanRepo(self.tmp), warn=self.warn)

    def run_cli(self, *argv, env=None):
        return subprocess.run([sys.executable, str(BIN), *argv], cwd=self.repo.root, env=env or self.env,
                              capture_output=True, text=True, timeout=60)

    def report(self, *argv):
        out = self.run_cli("--json", *argv)
        self.assertIn(out.returncode, (0, 1), out.stderr)
        return out.returncode, json.loads(out.stdout)

    def git_state(self):
        """What a run must leave unchanged: `git status`, and every file under `.git`."""
        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--ignored"],
                                cwd=self.repo.root, env=self.env, capture_output=True, text=True, check=True)
        files = []
        for folder, _dirs, names in os.walk(self.repo.root / ".git"):
            for name in names:
                path = Path(folder) / name
                info = path.lstat()
                files.append((path.relative_to(self.repo.root).as_posix(), info.st_size, info.st_mtime_ns))
        return status.stdout, sorted(files)


class EndToEnd(Project):
    def test_clean_project(self):
        out = self.run_cli()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.endswith("No problems found.\n"))
        self.assertIn("(5 documents, 6 commits of history)", out.stdout)
        code, data = self.report()
        self.assertEqual(code, 0)
        self.assertEqual((data["schema"], data["history"], data["findings"]), (1, "full", []))

    def test_runs_change_nothing(self):
        # Something uncommitted, so `git status` has something to compare.
        self.repo.write(self.repo.doc("frds/F01-example.md"), frd(body=EDITED))
        before = self.git_state()
        for argv in ((), ("--docs",), ("--feature", "F01"), ("--json", "--strict")):
            with self.subTest(argv=argv):
                self.run_cli(*argv)
                self.assertEqual(self.git_state(), before)

    def test_output_is_the_only_write(self):
        target = self.tmp / "report.json"
        before = self.git_state()
        out = self.run_cli("--output", str(target))
        self.assertEqual(out.returncode, 0)
        self.assertEqual(self.git_state(), before)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["findings"], [])

    def test_warnings_only(self):
        self.repo.write(LOG, (self.repo.root / LOG).read_text(encoding="utf-8") + log_line("warn"))
        self.repo.commit("A warn event")
        out = self.run_cli()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("0 errors, 1 warning.", out.stdout)
        self.assertEqual(self.run_cli("--strict").returncode, 1)

    def test_docs_starts_no_git_process(self):
        shim = self.tmp / "shim"
        shim.mkdir()
        marker = self.tmp / "git-ran"
        (shim / "git").write_text(f"#!/bin/sh\necho ran >> {marker}\nexec {shutil.which('git')} \"$@\"\n",
                                  encoding="utf-8")
        (shim / "git").chmod(0o755)
        env = {**self.env, "PATH": f"{shim}{os.pathsep}{self.env['PATH']}"}
        self.assertEqual(self.run_cli("--docs", env=env).returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.run_cli(env=env).returncode, 0)   # the shim does catch a full run
        self.assertTrue(marker.exists())

    def test_docs(self):
        self.repo.write(self.repo.doc("frds/F01-example.md"), frd(approvals=[]))
        self.repo.commit("Remove the approval")
        code, data = self.report()
        self.assertEqual([f["rule"] for f in data["findings"]], ["approval-removed"])
        code, data = self.report("--docs")
        self.assertEqual((code, data["history"], data["findings"], data["summary"]["commits"]), (0, "none", [], 0))

    def test_feature(self):
        self.repo.write(self.repo.doc("pdrd.md"), pdrd(features=["F01", "F02"]))
        self.repo.write(self.repo.doc("frds/F02-other.md"), frd("F02", status="in-review", approvals=[]))
        text = tdd("F02")
        self.repo.write(self.repo.doc("tdds/F02-other.md"), text)
        self.repo.write(self.repo.doc("frds/F01-example.md"), frd(approvals=[]))
        self.repo.write(LOG, log_line("warn") + "not json\n")
        self.repo.commit("Two features, a fault in each, and a broken log")

        code, data = self.report("--feature", "F02")
        self.assertEqual([(f["rule"], f["file"], f["line"]) for f in data["findings"]],
                         [("parent-unapproved", "docs/tdds/F02-other.md", line_of(text, "parent:"))])
        self.assertEqual((code, data["summary"]["documents"]), (1, 2))
        code, data = self.report("--feature", "F01")
        self.assertEqual([f["rule"] for f in data["findings"]], ["approval-removed"])
        code, data = self.report("--feature", "F09")
        self.assertEqual((code, data["findings"], data["summary"]["documents"]), (0, [], 0))

    def test_explain_every_rule(self):
        from speckled_chain import RULES
        for rule in RULES:
            with self.subTest(rule=rule):
                out = self.run_cli("--explain", rule)
                self.assertEqual(out.returncode, 0)
                self.assertTrue(out.stdout.startswith(f"{rule} (default severity: "))
                self.assertIn("Fix: ", out.stdout)

    def test_not_a_git_repository(self):
        shutil.rmtree(self.repo.root / ".git")
        self.repo.write(self.repo.doc("frds/F01-example.md"), frd(status="Doing"))
        out = self.run_cli()
        self.assertEqual(out.returncode, 1)
        code, data = self.report()
        self.assertEqual(data["history"], "none")
        self.assertEqual(sorted((f["rule"], f["severity"]) for f in data["findings"]),
                         [("front-matter", "error"), ("history-unavailable", "warning")])

    def test_shallow_clone(self):
        clone = self.repo.shallow_clone(self.tmp / "clone")
        out = subprocess.run([sys.executable, str(BIN), "--json"], cwd=clone, env=self.env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 1)
        data = json.loads(out.stdout)
        self.assertEqual((data["history"], [(f["rule"], f["severity"]) for f in data["findings"]]),
                         ("shallow", [("history-unavailable", "error")]))
        out = subprocess.run([sys.executable, str(BIN), "--feature", "F01"], cwd=clone, env=self.env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 1)   # a narrowed run still says history couldn't be checked


def _seed(repo: PlanRepo, fault: str):
    """Seed `fault` into the clean project; return the (rule, severity, file, line) it must give.

    Faults found in history are committed; the rest are left in the working tree.
    """
    def write(rel: str, text: str) -> str:
        repo.write(rel, text)
        return text

    if fault == "missing front matter":
        write(FRD, "# FRD-F01\n\nNo front matter.\n")
        return "front-matter", "error", FRD, 1
    if fault == "malformed front matter":
        text = write(FRD, frd().replace("status: approved", "status: approved: yes"))
        return "front-matter", "error", FRD, line_of(text, "status:")
    if fault == "invalid status":
        text = write(FRD, frd(status="Doing"))
        return "front-matter", "error", FRD, line_of(text, "status:")
    if fault == "duplicate id":
        write("docs/frds/F01-other.md", frd())
        return "duplicate-id", "error", "docs/frds/F01-other.md", 2
    if fault == "file name doesn't match the id":
        repo.move(FRD, "docs/frds/F02-example.md")
        return "file-name", "error", "docs/frds/F02-example.md", 2
    if fault == "feature doesn't match the id":
        write("docs/pdrd.md", pdrd(features=["F01", "F02"]))
        text = write(FRD, frd().replace("feature: F01", "feature: F02"))
        return "bad-id", "error", FRD, line_of(text, "feature:")
    if fault == "feature not in the PDRD":
        text = write("docs/frds/F03-new.md", frd("F03"))
        return "unknown-feature", "error", "docs/frds/F03-new.md", line_of(text, "feature:")
    if fault == "non-strict task status":
        text = write(TASKS, tasks(tasks=[task("T-F01-01", "Doing")]))
        return "task-format", "error", TASKS, line_of(text, "- **Status:** Doing")
    if fault == "duplicate task":
        write("docs/pdrd.md", pdrd(features=["F01", "F02"]))
        write("docs/frds/F02-example.md", frd("F02"))
        write("docs/tdds/F02-example.md", tdd("F02"))
        text = write("docs/tasks/F02-example.md", tasks("F02", tasks=[task("T-F02-01"), task("T-F01-01")]))
        return "duplicate-task", "error", "docs/tasks/F02-example.md", line_of(text, "### T-F01-01")
    if fault == "missing dependency":
        text = write(TASKS, tasks(tasks=[task("T-F01-01"), task("T-F01-02", depends_on=["T-F07-09"])]))
        return "dependency-missing", "error", TASKS, line_of(text, "- **Depends on:** T-F07-09")
    if fault == "dependency cycle":
        text = write(TASKS, tasks(tasks=[task("T-F01-01", depends_on=["T-F01-02"]),
                                         task("T-F01-02", depends_on=["T-F01-01"])]))
        return "dependency-cycle", "error", TASKS, line_of(text, "- **Depends on:** T-F01-02")
    if fault == "parent doesn't exist":
        repo.delete(FRD)
        return "parent-missing", "error", TDD, line_of(tdd(), "parent:")
    if fault == "parent never approved":
        write(FRD, frd(status="in-review", approvals=[]))
        return "parent-unapproved", "error", TDD, line_of(tdd(), "parent:")
    if fault == "parent never approved, with the rule 2 line":
        write(FRD, frd(status="in-review", approvals=[]))
        text = write(TDD, tdd(body=f"# TDD-F01\n\n{RULE2}\n\nText.\n"))
        return "parent-unapproved", "warning", TDD, line_of(text, "parent:")
    if fault == "parent reopened":
        write(FRD, frd(status="in-review", version=2, approvals=[approval("frd")]))
        repo.commit("Reopen the FRD")
        return "parent-reopened", "warning", TDD, line_of(tdd(), "parent:")
    if fault == "approver not listed":
        text = write(FRD, frd(approvals=[approval("frd"), approval("frd", by="mallory", version=1)]))
        repo.commit("mallory approves")
        return "approver-not-listed", "error", FRD, line_of(text, "  - {by: mallory")
    if fault == "approval with the wrong role":
        text = write(FRD, frd(approvals=[approval("frd"), approval("tdd")]))
        repo.commit("A second approval with the wrong role")
        return "approval-role-mismatch", "error", FRD, line_of(text, "  - {by: alice, role: tdd")
    if fault == "Approved by name not listed":
        text = write(TASKS, tasks(tasks=[
            task("T-F01-01", "Done", approved_by=[f"Approved by alice on 2026-10-02 ({SENTINEL} checked)",
                                                  "Approved by bob on 2026-10-03"]),
            task("T-F01-02", "In progress", depends_on=["T-F01-01"])]))
        repo.commit("bob approves")
        return "approver-not-listed", "error", TASKS, line_of(text, "Approved by bob")
    if fault == "approval's version edited":
        text = write(FRD, frd(approvals=[approval("frd", version=2)]))
        repo.commit("Edit an approval")
        return "approval-edited", "error", FRD, line_of(text, "  - {by: alice")
    if fault == "approval removed":
        text = write(FRD, frd(approvals=[]))
        repo.commit("Remove the approval")
        return "approval-removed", "error", FRD, line_of(text, "approvals:")
    if fault == "Approved by line removed":
        text = write(TASKS, tasks(tasks=[task("T-F01-01", "Done"),
                                         task("T-F01-02", "In progress", depends_on=["T-F01-01"])]))
        repo.commit("Remove the line")
        return "approval-removed", "error", TASKS, line_of(text, "### T-F01-01")
    if fault == "approved document deleted":
        repo.delete(TDD)
        repo.delete(TASKS)
        repo.commit("Delete the TDD and its task list")
        return "document-deleted", "error", TDD, None
    if fault == "approved document edited without review":
        text = write(FRD, frd(body=EDITED))
        repo.commit("Edit the FRD")
        return "edited-without-review", "error", FRD, line_of(text, "status:")
    if fault == "done document edited without review":
        specs = [task("T-F01-01", "Done", approved_by=[f"Approved by alice on 2026-10-02 ({SENTINEL} checked)"]),
                 task("T-F01-02", "Done", depends_on=["T-F01-01"], approved_by=["Approved by alice on 2026-10-03"])]
        write(TASKS, tasks(status="done", tasks=specs))
        repo.commit("Finish F01")
        text = write(TASKS, tasks(status="done", tasks=specs).replace("What to build", "What to make", 1))
        repo.commit("Edit a finished task")
        return "edited-without-review", "error", TASKS, line_of(text, "status:")
    if fault == "log line edited":
        write(LOG, log_line("block", rule="git-push"))
        repo.commit("Edit the log")
        return "log-edited", "error", LOG, 1
    if fault == "log line removed":
        write(LOG, "")
        repo.commit("Empty the log")
        return "log-edited", "error", LOG, None
    if fault == "malformed log line":
        write(LOG, (repo.root / LOG).read_text(encoding="utf-8") + log_line(v=2))
        repo.commit("Append a bad line")
        return "log-malformed", "error", LOG, 2
    raise KeyError(fault)


FAULTS = (
    "missing front matter", "malformed front matter", "invalid status", "duplicate id",
    "file name doesn't match the id", "feature doesn't match the id", "feature not in the PDRD",
    "non-strict task status", "duplicate task", "missing dependency", "dependency cycle",
    "parent doesn't exist", "parent never approved", "parent never approved, with the rule 2 line",
    "parent reopened", "approver not listed", "approval with the wrong role", "Approved by name not listed",
    "approval's version edited", "approval removed", "Approved by line removed", "approved document deleted",
    "approved document edited without review", "done document edited without review",
    "log line edited", "log line removed", "malformed log line",
)


class SeededFaults(unittest.TestCase):
    def test_each_fault_is_caught(self):
        for fault in FAULTS:
            with self.subTest(fault), tempfile.TemporaryDirectory() as tmp:
                env = git_env(Path(tmp))
                repo = clean_project(PlanRepo(tmp), warn=False)
                rule, severity, file, line = _seed(repo, fault)
                out = subprocess.run([sys.executable, str(BIN), "--json"], cwd=repo.root, env=env,
                                     capture_output=True, text=True, timeout=60)
                data = json.loads(out.stdout)
                found = [(f["rule"], f["severity"], f["file"], f["line"]) for f in data["findings"]]
                self.assertIn((rule, severity, file, line), found)
                if severity == "error":   # a warning's own exit code is in EndToEnd.test_warnings_only
                    self.assertEqual(out.returncode, 1, found)
                self.assertNotIn(SENTINEL, out.stdout)


if __name__ == "__main__":
    unittest.main()
