"""Performance budget for the registered hook, hooks/pretooluse.py: p95 <= 100 ms [T-F07-14] [T-F07-17] [T-F07-18].

Runs the hook as Claude Code does, a new process per tool call, against a project with
50 task lists of 10 tasks each and a valid active task, for an Edit to a governed file. A Read
(guard only, no gate) is timed too and reported, without a budget.

The budget is measured in rounds of 100 runs. If a round's p95 is over budget, the test
measures again, up to three rounds, and fails only if every round is over: shared CI
runners have bursts of slowness unrelated to the hook, and a real slowdown raises every
round (TDD-F07 R11).

Skipped unless SPECKLED_PERF=1 (CI sets it), so local test runs stay fast. Options:
    SPECKLED_PERF_PYTHON=/usr/bin/python3   time the hook under another interpreter
    SPECKLED_PERF_REPORT_ONLY=1             print one round's timings without asserting the budget
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from .fixtures import make_project
from .test_rules import task_list

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "pretooluse.py"
BUDGET_MS = 100
RUNS, WARMUP = 100, 5
ROUNDS = 3
LISTS, TASKS_PER_LIST = 50, 10


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def measure_rounds(measure, budget, rounds=ROUNDS) -> list:
    """Call measure() (one round's p95) until a p95 is within budget, at most `rounds` times.

    Returns every p95 measured, in order: the budget was met if the last one is within it.
    """
    p95s = []
    for _ in range(rounds):
        p95s.append(measure())
        if p95s[-1] <= budget:
            break
    return p95s


class MeasureRounds(unittest.TestCase):
    """The round logic, with stubbed p95s: no process is started."""

    def rounds(self, p95s):
        stub = iter(p95s)
        return measure_rounds(lambda: next(stub), BUDGET_MS)

    def test_first_round_within_budget(self):
        self.assertEqual(self.rounds([80]), [80])

    def test_second_round_within_budget(self):
        self.assertEqual(self.rounds([120, 90]), [120, 90])

    def test_every_round_over_budget(self):
        self.assertEqual(self.rounds([120, 130, 140]), [120, 130, 140])

    def test_never_more_than_three_rounds(self):
        self.assertEqual(self.rounds([120, 130, 140, 50]), [120, 130, 140])

    def test_budget_is_inclusive(self):
        self.assertEqual(self.rounds([BUDGET_MS, 50]), [BUDGET_MS])


@unittest.skipUnless(os.environ.get("SPECKLED_PERF") == "1", "set SPECKLED_PERF=1 to run")
class GateHookBudget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(os.path.realpath(self._tmp.name))
        files = {}
        for n in range(1, LISTS + 1):
            tasks = []
            for k in range(1, TASKS_PER_LIST + 1):
                task_id = f"T-F{n:02d}-{k:02d}"
                deps = [f"T-F{n:02d}-{k - 1:02d}"] if k > 1 else []
                # The active task is the last one of the last list: all its dependencies Done.
                status = "In progress" if (n, k) == (LISTS, TASKS_PER_LIST) else "Done"
                tasks.append((task_id, status, deps))
            files[f"plans/docs/tasks/F{n:02d}.md"] = task_list(f"TASKS-F{n:02d}", "approved", tasks)
        files["app/src/main.py"] = "print('hi')\n"
        paths = make_project(tmp, "project: Perf\nenforcement: block\nrepos:\n  - ../app\n",
                             code_repos=["app"], files=files)
        self.plans, self.data = paths.root, tmp / "plugin-data"
        (self.plans / ".speckled").mkdir()
        # As `activate` writes it: the task and the list holding it and its dependencies (D5).
        (self.plans / ".speckled" / "active-task").write_text(json.dumps({
            "v": 1, "task": f"T-F{LISTS:02d}-{TASKS_PER_LIST:02d}", "files": [f"tasks/F{LISTS:02d}.md"]}))
        self.edit, self.read = (json.dumps({
            "hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "perf",
            "cwd": str(self.plans), "tool_input": {"file_path": str(paths.repos["app"] / "src" / "main.py")}})
            for tool in ("Edit", "Read"))
        self.python = os.environ.get("SPECKLED_PERF_PYTHON") or sys.executable

    def tearDown(self):
        self._tmp.cleanup()

    def run_hook(self, payload) -> float:
        start = time.perf_counter()
        out = subprocess.run([self.python, str(HOOK), "--plugin-data", str(self.data)],
                             input=payload, text=True, capture_output=True)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""), "the call should be allowed")
        return elapsed

    def warm_up(self, payload):
        for _ in range(WARMUP):
            self.run_hook(payload)

    def timings(self, name, payload, label=""):
        """p95 over RUNS runs; p50, p95 and max printed for the hand-off."""
        times = [self.run_hook(payload) for _ in range(RUNS)]
        p50, p95 = percentile(times, 50), percentile(times, 95)
        print(f"\npretooluse.py, {name}{label}, with {self.python}: p50 {p50:.1f} ms, p95 {p95:.1f} ms, "
              f"max {max(times):.1f} ms ({RUNS} runs, {LISTS} task lists)", file=sys.stderr)
        return p95

    def test_p95_within_budget(self):
        self.warm_up(self.edit)
        if os.environ.get("SPECKLED_PERF_REPORT_ONLY") == "1":
            self.timings("Edit", self.edit)
            return
        rounds = iter(range(1, ROUNDS + 1))
        p95s = measure_rounds(lambda: self.timings("Edit", self.edit, f", round {next(rounds)}/{ROUNDS}"),
                              BUDGET_MS)
        self.assertLessEqual(p95s[-1], BUDGET_MS,
                             "p95 over budget in every round: " + ", ".join(f"{p:.1f} ms" for p in p95s))

    def test_read_reported(self):
        self.warm_up(self.read)
        self.timings("Read", self.read)  # guard only: reported, not asserted


if __name__ == "__main__":
    unittest.main()
