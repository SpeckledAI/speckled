"""Tests for lib/speckled_chain/enforcement_log.py, through `lint` [T-F08-11].

`AppendOnly` builds real git histories from the clean fixture project, whose log has
one `warn` line and one `block` line. `Lines` needs no history, so it runs as
`--docs` does.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speckled_chain import lint

from .fixtures import LOG, SENTINEL, PlanRepo, clean_project, git_env, log_line

LOG_RULES = {"log-edited", "log-malformed", "warn-event"}
WARN = log_line("warn")
BLOCK = log_line("block", rule="git-commit", tool="Bash", repo="", paths=[])


class AppendOnly(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, git_env(Path(tmp.name)), clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repo = clean_project(PlanRepo(tmp.name))

    def edited(self, history: bool = True):
        report = lint(self.repo.root, history=history)
        self.assertNotIn("@", json.dumps(report.to_json()))
        return [f for f in report.findings if f.rule == "log-edited"]

    def assertEdited(self, *expected):
        """The `log-edited` findings are exactly `expected`: (line, commit or None)."""
        found = self.edited()
        self.assertEqual(sorted((f.line or 0, f.commit or "") for f in found),
                         sorted((line or 0, commit or "") for line, commit in expected))
        for f in found:
            self.assertEqual((f.severity, f.subject, f.file), ("error", LOG, LOG))
        return found

    def test_clean_project(self):
        self.assertEdited()

    def test_appending_is_fine(self):
        self.repo.write(LOG, WARN + BLOCK + log_line("warn", rule="task-done"))
        self.repo.commit("Append")
        self.repo.write(LOG, WARN + BLOCK + log_line("warn", rule="task-done") + BLOCK)
        self.assertEdited()

    def test_commit_that_edits_a_line(self):
        self.repo.write(LOG, log_line("warn", by="bob") + BLOCK)
        sha = self.repo.commit("Edit the log", author="mallory")
        (finding,) = self.assertEdited((1, sha))
        self.assertEqual((finding.by, finding.date), ("mallory", "2026-10-01"))
        self.assertIn("line 1 was changed", finding.message)
        self.assertIn(sha[:7], finding.message)

    def test_commit_that_removes_a_line(self):
        self.repo.write(LOG, BLOCK)
        sha = self.repo.commit("Remove the warn line")
        (finding,) = self.assertEdited((1, sha))
        self.assertIn("line 1 was removed", finding.message)

    def test_commit_that_removes_the_last_lines(self):
        self.repo.write(LOG, WARN)
        sha = self.repo.commit("Remove the block line")
        (finding,) = self.assertEdited((None, sha))
        self.assertIn("committed line 2 was removed", finding.message)

    def test_emptying_the_log(self):
        self.repo.write(LOG, "")
        (finding,) = self.assertEdited((None, None))
        self.assertIn("committed lines 1-2 were removed", finding.message)

    def test_commit_that_deletes_the_log(self):
        self.repo.delete(LOG)
        sha = self.repo.commit("Delete the log")
        (finding,) = self.assertEdited((None, sha))
        self.assertIn("was deleted", finding.message)
        self.assertIn("2 lines", finding.message)

    def test_uncommitted_edit(self):
        self.repo.write(LOG, WARN + log_line("block", rule="git-push"))
        (finding,) = self.assertEdited((2, None))
        self.assertIn("in the working tree", finding.message)
        self.assertIsNone(finding.by)

    def test_edit_on_a_branch_is_reported_once_after_the_merge(self):
        self.repo.branch("tamper")
        self.repo.checkout("tamper")
        self.repo.write(LOG, log_line("warn", task=None) + BLOCK)
        sha = self.repo.commit("Edit on a branch")
        self.repo.checkout("main")
        self.repo.merge("tamper")
        self.assertEdited((1, sha))

    def test_docs_only_skips_history(self):
        self.repo.write(LOG, BLOCK)
        self.repo.commit("Remove the warn line")
        self.assertEqual(self.edited(history=False), [])

    def test_a_broken_line_is_compared_byte_for_byte(self):
        self.repo.write(LOG, WARN + BLOCK + "not json\n")
        self.repo.commit("Append a broken line")
        self.repo.write(LOG, WARN + BLOCK + "not json!\n")
        sha = self.repo.commit("Edit it")
        self.assertEdited((3, sha))


class Lines(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = clean_project(PlanRepo(tmp.name, git=False))

    def write_log(self, *lines: str) -> None:
        self.repo.write(LOG, "".join(lines))

    def report(self):
        report = lint(self.repo.root, history=False)
        self.assertNotIn(SENTINEL, json.dumps(report.to_json()))
        return report

    def findings(self):
        """The log's findings as (rule, severity, line)."""
        return sorted((f.rule, f.severity, f.line) for f in self.report().findings if f.rule in LOG_RULES)

    def assertMalformed(self, line: str, problem: str):
        self.write_log(BLOCK, line)
        self.assertEqual(self.findings(), [("log-malformed", "error", 2)])
        (finding,) = [f for f in self.report().findings if f.rule == "log-malformed"]
        self.assertEqual((finding.subject, finding.file), (LOG, LOG))
        self.assertIn(problem, finding.message)

    def test_clean_project_has_one_warn_event(self):
        self.assertEqual(self.findings(), [("warn-event", "warning", 1)])
        self.assertEqual(self.report().to_json()["summary"]["warn_events"], 1)

    def test_missing_log_is_not_a_finding(self):
        self.repo.delete(LOG)
        self.assertEqual(self.findings(), [])

    def test_empty_log(self):
        self.write_log()
        self.assertEqual(self.findings(), [])

    # --- log-malformed ---------------------------------------------------------------

    def test_not_json(self):
        self.assertMalformed(f"{SENTINEL}\n", "isn't JSON")

    def test_not_an_object(self):
        self.assertMalformed(json.dumps([SENTINEL]) + "\n", "isn't a JSON object")

    def test_blank_line(self):
        self.assertMalformed("\n", "isn't JSON")

    def test_not_utf8(self):
        self.repo.write(LOG, BLOCK)
        with open(self.repo.root / LOG, "ab") as f:
            f.write(b"\xff\xfe\n")
        self.assertEqual(self.findings(), [("log-malformed", "error", 2)])

    def test_version_2(self):
        self.assertMalformed(log_line(v=2), "`v` isn't 1")

    def test_version_true(self):
        self.assertMalformed(log_line(v=True), "`v` isn't 1")

    def test_version_missing(self):
        entry = json.loads(WARN)
        del entry["v"]
        self.assertMalformed(json.dumps(entry) + "\n", "`v` is missing")

    def test_bad_ts(self):
        for ts in ("2026-10-02 10:00:00", "2026-10-02T10:00:00+00:00", "2026-13-02T10:00:00Z",
                   "2026-2-2T10:00:00Z", 1760000000, SENTINEL):
            with self.subTest(ts=ts):
                self.assertMalformed(log_line(ts=ts), "`ts`")

    def test_mode_allow(self):
        self.assertMalformed(log_line(mode="allow"), "`mode` isn't `warn` or `block`")

    def test_paths_not_a_list(self):
        self.assertMalformed(log_line(paths=f"src/{SENTINEL}.py"), "`paths` isn't a list of strings")

    def test_paths_not_strings(self):
        self.assertMalformed(log_line(paths=["src/main.py", 3]), "`paths` isn't a list of strings")

    def test_empty_rule(self):
        for rule in ("", "  ", None):
            with self.subTest(rule=rule):
                self.assertMalformed(log_line(rule=rule), "`rule` isn't a non-empty string")

    def test_string_fields(self):
        for key in ("by", "tool", "repo", "agent"):
            with self.subTest(key=key):
                self.assertMalformed(log_line(**{key: None}), f"`{key}` isn't a string")

    def test_task_not_a_string(self):
        self.assertMalformed(log_line(task=3), "`task` isn't a string or null")

    def test_task_missing(self):
        entry = json.loads(WARN)
        del entry["task"]
        self.assertMalformed(json.dumps(entry) + "\n", "`task` isn't a string or null")

    def test_malformed_warn_line_is_not_a_warn_event(self):
        self.write_log(log_line("warn", rule=""))
        self.assertEqual(self.findings(), [("log-malformed", "error", 1)])

    # --- valid lines -----------------------------------------------------------------

    def test_unknown_future_rule_is_valid(self):
        self.write_log(log_line("block", rule="some-future-rule"))
        self.assertEqual(self.findings(), [])

    def test_extra_fields_are_valid(self):
        self.write_log(log_line("block", session="abc", reason={"kind": "x"}))
        self.assertEqual(self.findings(), [])

    def test_block_lines_are_not_reported(self):
        self.write_log(BLOCK, log_line("block", rule="recursive-delete", task=None),
                       log_line("block", rule="secret-env-file"))
        self.assertEqual(self.findings(), [])

    # --- warn-event ------------------------------------------------------------------

    def test_each_warn_line_is_one_warn_event(self):
        self.write_log(WARN, BLOCK,
                       log_line("warn", ts="2026-10-03T11:22:33Z", by="bob", rule="task-done", task="T-F01-01"),
                       log_line("warn", rule="no-active-task", task=None, repo="", paths=[]))
        report = self.report()
        events = [f for f in report.findings if f.rule == "warn-event"]
        self.assertEqual([(f.severity, f.line) for f in events], [("warning", 1), ("warning", 3), ("warning", 4)])
        self.assertEqual(report.to_json()["summary"]["warn_events"], 3)
        self.assertEqual(report.exit_code(), 0)

        first, second, third = (f.message for f in events)
        for part in ("2026-10-02T10:00:00Z", "alice", "Edit", "no-active-task", "T-F01-02", "../app",
                     "src/main.py"):
            self.assertIn(part, first)
        for part in ("2026-10-03T11:22:33Z", "bob", "task-done", "T-F01-01"):
            self.assertIn(part, second)
        self.assertIn("no active task", third)
        for f in events:
            self.assertIsNone(f.commit)

    def test_warn_event_names_at_most_three_paths(self):
        self.write_log(log_line("warn", paths=["a.py", "b.py", "c.py", "d.py", "e.py"]))
        (finding,) = [f for f in self.report().findings if f.rule == "warn-event"]
        self.assertIn("a.py, b.py, c.py and 2 more", finding.message)
        self.assertNotIn("d.py", finding.message)

    def test_symlinked_log_is_not_read(self):
        target = self.repo.tmp / "elsewhere.jsonl"
        target.write_text("not json\n", encoding="utf-8")
        self.repo.delete(LOG)
        (self.repo.root / LOG).symlink_to(target)
        self.assertEqual(self.findings(), [])


if __name__ == "__main__":
    unittest.main()
