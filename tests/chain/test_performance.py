"""Performance budget for bin/lint-chain: a full run <= 5 s and `--docs` <= 1 s [T-F08-14].

Runs `bin/lint-chain` as a user or CI would, a new process per run, on a planning repo
with 50 documents and 500 commits: a brief, a roadmap, an architecture document,
23 research notes, and a full chain (FRD, TDD and task list) for each of 8 features.
Documents are about the size of real ones, and the history has what real histories have:
documents added, edits re-approved in the same commit, task statuses changed, `Approved
by` lines added, finished features moved into `completed/`, research notes revised and
log lines appended. The whole history is valid, so the run reports no problems.

The history is written with one `git fast-import` stream, which is much faster than 500
`git commit` calls, in the isolated environment of `fixtures.py`.

Each budget is measured in rounds of one run. If a round is over budget, the test runs it
again, up to three rounds, and fails only if every round is over: shared CI runners have
bursts of slowness unrelated to the linter, and a real slowdown raises every round.

Skipped unless SPECKLED_PERF=1 (CI sets it), so local test runs stay fast. Options:
    SPECKLED_PERF_PYTHON=/usr/bin/python3   time the linter under another interpreter
    SPECKLED_PERF_REPORT_ONLY=1             print one round's timings without asserting the budgets
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from .fixtures import (AUTHOR, BASE_TIME, COMMITTER, LOG, SENTINEL, PlanRepo, approval, arch, brief, frd, git_env,
                       log_line, pdrd, research, task, tasks, tdd)
from .test_cli import BIN

FULL_BUDGET_S, DOCS_BUDGET_S = 5.0, 1.0
ROUNDS = 3
DOCUMENTS, COMMITS = 50, 500
FEATURES = [f"F{n:02d}" for n in range(1, 9)]
COMPLETED = FEATURES[:4]  # finished, and moved into completed/
TASKS_PER_LIST = 12
RESEARCH_NOTES = DOCUMENTS - 3 - 3 * len(FEATURES)

PARAGRAPH = ("The requirement is described here in enough detail for an engineer to build it without guessing: "
             "what the user does, what the system shows in return, which inputs are valid, what happens when "
             "one isn't, and how a reviewer can tell from the running product that it works as intended. "
             f"{SENTINEL}.\n\n")


def prose(heading: str, size: int) -> str:
    """A body of about `size` bytes: a heading, then numbered sections of plain paragraphs."""
    sections, n = [f"# {heading}\n\n"], 0
    while sum(map(len, sections)) < size:
        n += 1
        sections.append(f"## Section {n}\n\n{PARAGRAPH}{PARAGRAPH}")
    return "".join(sections)


def task_list(feature: str, statuses: list, done: bool = False) -> str:
    """TASKS-<feature> with tasks in `statuses`; Done tasks carry their `Approved by` line.

    Each task gets a detailed description in place of the fixture's one-line one, so the
    list is about the size of a real one.
    """
    specs = [task(f"T-{feature}-{k:02d}", status,
                  depends_on=[f"T-{feature}-{k - 1:02d}"] if k > 1 else [],
                  approved_by=["Approved by alice on 2026-10-02"] if status == "Done" else [])
             for k, status in enumerate(statuses, start=1)]
    text = tasks(feature, tasks=specs, parent_version=2, **({"status": "done"} if done else {}))
    return text.replace(f"What to build {SENTINEL}.", "**Context**\n\n" + PARAGRAPH * 10 + "**Steps**")


class History:
    """A planning repo's history as a list of commits, written out as a fast-import stream."""

    def __init__(self):
        self.commits = []  # (message, {path: text, or None to delete it})

    def commit(self, message: str, changes: dict) -> None:
        self.commits.append((message, changes))

    def stream(self) -> bytes:
        out = []

        def data(text: str) -> None:
            raw = text.encode("utf-8")
            out.append(b"data %d\n%s\n" % (len(raw), raw))

        for minute, (message, changes) in enumerate(self.commits):
            stamp = f"{BASE_TIME + 60 * minute} +0000"
            out.append(f"commit refs/heads/main\nauthor {AUTHOR[0]} <{AUTHOR[1]}> {stamp}\n"
                       f"committer {COMMITTER[0]} <{COMMITTER[1]}> {stamp}\n".encode("utf-8"))
            data(message)
            for path, text in changes.items():
                if text is None:
                    out.append(f"D {path}\n".encode("utf-8"))
                else:
                    out.append(f"M 100644 inline {path}\n".encode("utf-8"))
                    data(text)
        return b"".join(out)


def build_history(config: str) -> History:
    history = History()
    log = []

    def append_log(task_id: str) -> dict:
        log.append(log_line("block", rule="git-commit", tool="Bash", repo="", paths=[], task=task_id))
        return {LOG: "".join(log)}

    history.commit("Add the brief", {"speckled.yaml": config, "docs/brief.md": brief(body=prose("BRIEF", 14_000))})
    features = "\n## Features\n\n" + "".join(f"### {f}: Example feature {f}\n\n{PARAGRAPH * 20}" for f in FEATURES)
    history.commit("Add the PDRD", {"docs/pdrd.md": pdrd(FEATURES, body=prose("PDRD", 30_000) + features)})
    history.commit("Add ARCH", {"docs/architecture.md": arch(body=prose("ARCH", 26_000))})
    notes = [f"docs/research/note-{n:02d}.md" for n in range(1, RESEARCH_NOTES + 1)]
    for n, path in enumerate(notes, start=1):
        history.commit(f"Research note {n}", {path: research(f"R-{n:02d}", body=prose(f"R-{n:02d}", 5_000))})

    for f in FEATURES:
        paths = {kind: f"docs/{kind}/{f}-example.md" for kind in ("frds", "tdds", "tasks")}
        body = prose(f"FRD-{f}", 30_000)
        history.commit(f"FRD-{f}", {paths["frds"]: frd(f, body=body)})
        reapproved = frd(f, version=2, approvals=[approval("frd"), approval("frd", version=2)],
                         body=body + PARAGRAPH)
        history.commit(f"FRD-{f} v2", {paths["frds"]: reapproved})
        design = tdd(f, parent_version=2, body=prose(f"TDD-{f}", 50_000))
        history.commit(f"TDD-{f}", {paths["tdds"]: design})
        statuses = ["Todo"] * TASKS_PER_LIST
        history.commit(f"TASKS-{f}", {paths["tasks"]: task_list(f, statuses)})
        for k in range(TASKS_PER_LIST):
            task_id = f"T-{f}-{k + 1:02d}"
            for status in ("In progress", "In review", "Done"):
                statuses[k] = status
                changes = {paths["tasks"]: task_list(f, statuses)}
                if status == "In progress":
                    changes.update(append_log(task_id))
                history.commit(f"{task_id} {status}", changes)
        if f in COMPLETED:
            texts = {"frds": reapproved, "tdds": design, "tasks": task_list(f, statuses, done=True)}
            moves = {}
            for kind, path in paths.items():
                moves[path] = None
                moves[path.replace(f"/{kind}/", f"/{kind}/completed/")] = texts[kind]
            history.commit(f"Complete {f}", moves)

    # Research notes revised and the log appended until there are COMMITS commits.
    revisions = {path: research(f"R-{n:02d}", body=prose(f"R-{n:02d}", 5_000)) for n, path in enumerate(notes, 1)}
    while len(history.commits) < COMMITS:
        n = len(history.commits)
        if n % 2:
            path = notes[n % len(notes)]
            revisions[path] += PARAGRAPH
            history.commit(f"Revise {path}", {path: revisions[path]})
        else:
            history.commit("Log", append_log(f"T-{FEATURES[-1]}-01"))
    return history


def measure_rounds(measure, budget: float, rounds: int = ROUNDS) -> list:
    """Call measure() (one round's time) until a time is within budget, at most `rounds` times.

    Returns every time measured, in order: the budget was met if the last one is within it.
    """
    times = []
    for _ in range(rounds):
        times.append(measure())
        if times[-1] <= budget:
            break
    return times


class MeasureRounds(unittest.TestCase):
    """The round logic, with stubbed times: no process is started."""

    def rounds(self, times):
        stub = iter(times)
        return measure_rounds(lambda: next(stub), FULL_BUDGET_S)

    def test_second_round_within_budget(self):
        self.assertEqual(self.rounds([6.0, 4.0]), [6.0, 4.0])

    def test_never_more_than_three_rounds(self):
        self.assertEqual(self.rounds([6.0, 7.0, 8.0, 1.0]), [6.0, 7.0, 8.0])


@unittest.skipUnless(os.environ.get("SPECKLED_PERF") == "1", "set SPECKLED_PERF=1 to run")
class LintChainBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        repo = PlanRepo(os.path.realpath(cls._tmp.name))
        stream = build_history((repo.root / "speckled.yaml").read_text(encoding="utf-8")).stream()
        env = git_env(repo.tmp)
        for args, stdin in ((["fast-import", "--quiet"], stream), (["reset", "-q", "--hard"], None)):
            subprocess.run(["git", *args], cwd=repo.root, env=env, input=stdin, check=True,
                           capture_output=True, timeout=300)
        cls.root, cls.env = repo.root, env
        cls.python = os.environ.get("SPECKLED_PERF_PYTHON") or sys.executable

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_lint(self, *argv) -> subprocess.CompletedProcess:
        out = subprocess.run([self.python, str(BIN), *argv], cwd=self.root, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual((out.returncode, out.stderr), (0, ""), out.stdout)
        return out

    def test_fixture_size(self):
        commits = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=self.root, env=self.env, check=True,
                                 capture_output=True, text=True).stdout
        self.assertEqual(int(commits), COMMITS)
        summary = json.loads(self.run_lint("--json").stdout)["summary"]
        self.assertEqual(summary, {"documents": DOCUMENTS, "commits": COMMITS, "errors": 0, "warnings": 0,
                                   "warn_events": 0})

    def timed(self, name, argv, label="") -> float:
        start = time.perf_counter()
        out = self.run_lint(*argv)
        elapsed = time.perf_counter() - start
        self.assertIn("No problems found.", out.stdout)
        print(f"\nlint-chain, {name}{label}, with {self.python}: {elapsed:.2f} s "
              f"({DOCUMENTS} documents, {COMMITS} commits)", file=sys.stderr)
        return elapsed

    def check_budget(self, name, argv, budget):
        if os.environ.get("SPECKLED_PERF_REPORT_ONLY") == "1":
            self.timed(name, argv)
            return
        rounds = iter(range(1, ROUNDS + 1))
        times = measure_rounds(lambda: self.timed(name, argv, f", round {next(rounds)}/{ROUNDS}"), budget)
        self.assertLessEqual(times[-1], budget,
                             f"{name} over {budget:.0f} s in every round: " + ", ".join(f"{t:.2f} s" for t in times))

    def test_full_run_within_budget(self):
        self.check_budget("full run", [], FULL_BUDGET_S)

    def test_docs_within_budget(self):
        self.check_budget("--docs", ["--docs"], DOCS_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
