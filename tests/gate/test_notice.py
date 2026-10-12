"""Tests for hooks/pre-commit-notice.py and `speckled-gate install-git-hook` [T-F07-11].

Each test uses a real temporary git repo.
"""
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from speckled_gate.cli import NOTICE_MARKER, main

PLUGIN = Path(__file__).resolve().parents[2]
NOTICE = PLUGIN / "hooks" / "pre-commit-notice.py"

FRD = """---
id: FRD-F07
title: Example
status: in-review
version: 4
approvals:
  - {by: marczenn, role: frd, date: 2026-10-01, version: 3}
---

# FRD-F07
"""

TASKS = """---
id: TASKS-F07
status: approved
version: 1
---

### T-F07-03: Parser
- **Status:** In review

### T-F07-04: Shell
- **Status:** Todo
"""


def git(repo, *args, check=True) -> str:
    out = subprocess.run(["git", "-c", "user.name=Tester", "-c", "user.email=t@example.com", *args],
                         cwd=repo, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise AssertionError(f"git {args}: {out.stderr}")
    return out.stdout + out.stderr


class Repo(unittest.TestCase):
    """A planning repo with speckled.yaml and two committed documents."""

    docs = "docs"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "plans"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "speckled.yaml").write_text(f"docs_dir: {self.docs}  # planning documents\nrepos: []\n")
        self.write("frds/F07.md", FRD)
        self.write("tasks/F07.md", TASKS)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.repo / self.docs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def edit(self, rel, old, new):
        path = self.repo / self.docs / rel
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def notice(self, cwd=None):
        """Run the notice script; return (exit code, stdout, stderr)."""
        out = subprocess.run([sys.executable, str(NOTICE)], cwd=cwd or self.repo,
                             capture_output=True, text=True)
        return out.returncode, out.stdout, out.stderr

    def stage_approvals(self):
        self.edit("frds/F07.md", "version: 3}\n", "version: 3}\n  - {by: marczenn, role: frd, date: 2026-10-12, version: 4}\n")
        self.edit("frds/F07.md", "status: in-review", "status: approved")
        self.edit("tasks/F07.md", "- **Status:** In review\n",
                  "- **Status:** Done\n\nApproved by marczenn on 2026-10-12\n")
        git(self.repo, "add", "-A")


class Notice(Repo):
    def test_lists_approval_status_and_task_done(self):
        self.stage_approvals()
        code, out, err = self.notice()
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err.splitlines(), [
            "speckled: this commit records:",
            "  FRD-F07 set to approved",
            "  FRD-F07 approved by marczenn (v4)",
            "  T-F07-03 marked Done (approved by marczenn)",
        ])

    def test_approved_by_line_alone_is_listed(self):
        self.edit("tasks/F07.md", "### T-F07-04: Shell\n- **Status:** Todo\n",
                  "### T-F07-04: Shell\n- **Status:** Todo\n\nApproved by someone on 2026-10-12\n")
        git(self.repo, "add", "-A")
        self.assertEqual(self.notice()[2].splitlines()[1:], ["  T-F07-04 approved by someone"])

    def test_nothing_relevant_prints_nothing(self):
        self.edit("frds/F07.md", "# FRD-F07\n", "# FRD-F07\n\nMore text, status: approved.\n")
        (self.repo / "notes.md").write_text("status: approved\n")  # outside docs_dir
        git(self.repo, "add", "-A")
        self.assertEqual(self.notice(), (0, "", ""))

    def test_only_staged_changes_count(self):
        self.edit("frds/F07.md", "status: in-review", "status: approved")  # not staged
        self.assertEqual(self.notice(), (0, "", ""))

    def test_runs_from_a_subfolder(self):
        self.stage_approvals()
        code, _, err = self.notice(cwd=self.repo / self.docs)
        self.assertEqual(code, 0)
        self.assertIn("FRD-F07 set to approved", err)

    def test_exits_0_outside_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.notice(cwd=tmp), (0, "", ""))

    def test_marker_is_near_the_top(self):
        self.assertEqual(NOTICE.read_text().splitlines()[1], NOTICE_MARKER)


class CustomDocsDir(Repo):
    docs = "planning/docs"

    def test_reads_docs_dir_from_speckled_yaml(self):
        self.stage_approvals()
        self.assertIn("FRD-F07 approved by marczenn (v4)", self.notice()[2])


class InstallGitHook(Repo):
    def install(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["install-git-hook", "--project", str(self.repo), "--plugin-root", str(PLUGIN),
                         "--cwd", str(self.repo)])
        return code, out.getvalue() + err.getvalue()

    @property
    def hook(self):
        return self.repo / ".git" / "hooks" / "pre-commit"

    def test_fresh_repo(self):
        self.assertEqual(self.install(), (0, "Installed .git/hooks/pre-commit\n"))
        self.assertEqual(self.hook.read_text(), NOTICE.read_text())
        self.assertEqual(self.hook.stat().st_mode & 0o777, 0o755)

    def test_commit_goes_ahead_and_shows_the_notice(self):
        self.install()
        self.stage_approvals()
        out = git(self.repo, "commit", "-m", "approve")
        self.assertIn("speckled: this commit records:", out)
        self.assertIn("T-F07-03 marked Done", out)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_install_again_updates_in_place(self):
        self.install()
        self.hook.write_text(f"#!/bin/sh\n{NOTICE_MARKER}\n# an older version\n")
        self.assertEqual(self.install(), (0, "Installed .git/hooks/pre-commit\n"))
        self.assertEqual(self.hook.read_text(), NOTICE.read_text())
        self.assertEqual(sorted(p.name for p in self.hook.parent.iterdir() if not p.name.endswith(".sample")),
                         ["pre-commit"])

    def test_existing_foreign_hook_is_left_alone(self):
        self.hook.parent.mkdir(exist_ok=True)
        self.hook.write_text("#!/bin/sh\nnpm run lint\n")
        code, out = self.install()
        self.assertEqual(code, 0)
        self.assertIn("python3 .git/hooks/speckled-notice", out)
        self.assertEqual(self.hook.read_text(), "#!/bin/sh\nnpm run lint\n")
        self.assertEqual((self.hook.parent / "speckled-notice").read_text(), NOTICE.read_text())

    def test_hooks_path_set_prints_instructions_only(self):
        git(self.repo, "config", "core.hooksPath", ".githooks")
        code, out = self.install()
        self.assertEqual(code, 0)
        self.assertIn("core.hooksPath is set (.githooks)", out)
        self.assertIn("python3 .git/hooks/speckled-notice", out)
        self.assertFalse(self.hook.exists())
        self.assertFalse((self.repo / ".githooks").exists())

    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "speckled.yaml").write_text("repos: []\n")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["install-git-hook", "--project", tmp, "--plugin-root", str(PLUGIN), "--cwd", tmp])
            self.assertEqual(code, 1)
            self.assertIn("isn't a git repository", err.getvalue())


if __name__ == "__main__":
    unittest.main()
