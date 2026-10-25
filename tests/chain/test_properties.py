"""Properties every report has, checked on every seeded-fault fixture [T-F08-12].

- Determinism: two runs on the same repo give byte-identical JSON, so two reports
  can be compared with a plain diff.
- Privacy: the JSON holds IDs, rule names, relative paths, commit IDs, author names
  and dates, never document text, an email address or an absolute path. The fixtures
  plant `SENTINEL` in every body, every `title` and an `Approved by` note, and give
  every author and committer an email address.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .fixtures import SENTINEL, PlanRepo, clean_project, git_env
from .test_cli import BIN, FAULTS, _seed


class Properties(unittest.TestCase):
    def check(self, repo: PlanRepo, tmp: Path, *argv: str) -> None:
        env = git_env(tmp)
        runs = [subprocess.run([sys.executable, str(BIN), "--json", *argv], cwd=repo.root, env=env,
                               capture_output=True, timeout=60) for _ in range(2)]
        first, second = (run.stdout for run in runs)
        self.assertIn(runs[0].returncode, (0, 1), runs[0].stderr)
        self.assertEqual(first, second)
        text = first.decode("utf-8")
        self.assertNotIn("@", text)
        self.assertNotIn(SENTINEL, text)
        for absolute in {str(tmp), str(tmp.resolve()), str(Path.home())}:
            self.assertNotIn(absolute, text)

    def test_every_seeded_fault(self):
        for fault in ("none",) + FAULTS:
            with self.subTest(fault), tempfile.TemporaryDirectory() as tmp:
                repo = clean_project(PlanRepo(tmp))
                if fault != "none":
                    _seed(repo, fault)
                self.check(repo, Path(tmp))
                self.check(repo, Path(tmp), "--feature", "F01")

    def test_plain_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = clean_project(PlanRepo(tmp, git=False))
            self.check(repo, Path(tmp))


if __name__ == "__main__":
    unittest.main()
