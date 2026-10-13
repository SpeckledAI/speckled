"""Performance budget for hooks/gate.py: p95 <= 100 ms per decision [T-F07-14].

Runs the hook as Claude Code does, a new process per tool call, against a project with
50 task lists of 10 tasks each and a valid active task, for an Edit to a governed file.

Skipped unless SPECKLED_PERF=1 (CI sets it), so local test runs stay fast. Options:
    SPECKLED_PERF_PYTHON=/usr/bin/python3   time the hook under another interpreter
    SPECKLED_PERF_REPORT_ONLY=1             print the timings without asserting the budget
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

GATE = Path(__file__).resolve().parents[2] / "hooks" / "gate.py"
BUDGET_MS = 100
RUNS, WARMUP = 100, 5
LISTS, TASKS_PER_LIST = 50, 10


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


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
        self.payload = json.dumps({
            "hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "perf",
            "cwd": str(self.plans), "tool_input": {"file_path": str(paths.repos["app"] / "src" / "main.py")}})
        self.python = os.environ.get("SPECKLED_PERF_PYTHON") or sys.executable

    def tearDown(self):
        self._tmp.cleanup()

    def run_hook(self) -> float:
        start = time.perf_counter()
        out = subprocess.run([self.python, str(GATE), "--plugin-data", str(self.data)],
                             input=self.payload, text=True, capture_output=True)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""), "the edit should be allowed")
        return elapsed

    def test_p95_within_budget(self):
        for _ in range(WARMUP):
            self.run_hook()
        times = [self.run_hook() for _ in range(RUNS)]
        p50, p95 = percentile(times, 50), percentile(times, 95)
        print(f"\ngate.py with {self.python}: p50 {p50:.1f} ms, p95 {p95:.1f} ms, max {max(times):.1f} ms "
              f"({RUNS} runs, {LISTS} task lists)", file=sys.stderr)
        if os.environ.get("SPECKLED_PERF_REPORT_ONLY") != "1":
            self.assertLessEqual(p95, BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
