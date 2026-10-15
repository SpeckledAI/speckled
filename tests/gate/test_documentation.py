"""The documentation names every rule the gate can report [T-F07-13].

Rule values are part of the log format, so protocol §8 and the README's
Troubleshooting must list each one that `rules.py` can produce.
"""
import re
import unittest
from pathlib import Path

from speckled_gate import rules

ROOT = Path(__file__).resolve().parents[2]


def rule_values() -> set:
    source = (ROOT / "lib" / "speckled_gate" / "rules.py").read_text(encoding="utf-8")
    return set(re.findall(r'Verdict\("([a-z-]+)"', source)) | set(rules._ALWAYS.values())


def section(path: Path, heading: str) -> str:
    """The text under `heading` up to the next heading of the same level."""
    text = path.read_text(encoding="utf-8")
    level = heading.split(" ", 1)[0]
    start = text.index(heading + "\n")
    end = text.find(f"\n{level} ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


class RulesAreDocumented(unittest.TestCase):
    def test_the_rule_list_is_complete(self):
        # Guards the extraction itself: these are the rules of log format v1.
        self.assertEqual(rule_values(), {
            "wrong-start-folder", "config-unreadable", "protected-path", "hooks-disabled-session",
            "git-commit", "git-push", "pull-request", "no-active-task", "task-list-not-approved",
            "task-not-started", "task-done", "dependency-not-done", "dependency-missing"})

    def test_protocol_section_8(self):
        text = section(ROOT / "protocol" / "documents.md", "## 8. Enforcement")
        for rule in sorted(rule_values()):
            with self.subTest(rule=rule):
                self.assertIn(f"`{rule}`", text)

    def test_readme_troubleshooting(self):
        text = section(ROOT / "README.md", "## Troubleshooting")
        for rule in sorted(rule_values()):
            with self.subTest(rule=rule):
                self.assertIn(f"`{rule}`", text)


if __name__ == "__main__":
    unittest.main()
