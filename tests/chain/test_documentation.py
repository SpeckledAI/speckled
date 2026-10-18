"""The rule registry and protocol §9 agree [T-F08-03].

`rules.py` is what `lint-chain` reports and `--explain` prints; protocol §9 is what
users read. This test fails if a rule, its default severity or its meaning differ.
It also keeps internal planning references out of both.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

from speckled_chain.rules import RULES, explain

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin" / "lint-chain"
INTERNAL_REFS = [re.compile(p) for p in (r"\bN?FR\d+\b", r"\b[DRS]\d+\b", r"FRD-F\d+/")]


def section(path: Path, heading: str) -> str:
    """The text under `heading` up to the next heading of the same level."""
    text = path.read_text(encoding="utf-8")
    level = heading.split(" ", 1)[0]
    start = text.index(heading + "\n")
    end = text.find(f"\n{level} ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def protocol_rules() -> list:
    """(rule, severity cell, meaning cell) for each row of §9's rules table."""
    text = section(ROOT / "protocol" / "documents.md", "## 9. Chain checks")
    table = text[text.index("### Rules\n"):]
    rows = []
    for line in table.splitlines():
        match = re.match(r"^\| `([a-z-]+)` \| (.+?) \| (.+) \|$", line)
        if match:
            rows.append(match.groups())
    return rows


class RegistryMatchesProtocol(unittest.TestCase):
    def test_header(self):
        text = section(ROOT / "protocol" / "documents.md", "## 9. Chain checks")
        self.assertIn("| Rule | Severity | Meaning |", text)

    def test_same_rules_in_the_same_order(self):
        self.assertEqual([row[0] for row in protocol_rules()], list(RULES))
        self.assertEqual(len(RULES), 24)

    def test_severity_and_meaning(self):
        for rule, severity, meaning in protocol_rules():
            with self.subTest(rule=rule):
                self.assertIn(RULES[rule].severity, severity)
                self.assertEqual(RULES[rule].meaning, meaning)

    def test_every_rule_has_a_meaning_and_fix(self):
        for rule in RULES.values():
            with self.subTest(rule=rule.id):
                self.assertIn(rule.severity, ("error", "warning"))
                self.assertTrue(rule.meaning.strip())
                self.assertTrue(rule.fix.strip())
                text = explain(rule.id)
                self.assertIn(rule.meaning, text)
                self.assertIn(rule.fix, text)


class NoInternalReferences(unittest.TestCase):
    def assertClean(self, text, where):
        for pattern in INTERNAL_REFS:
            self.assertIsNone(pattern.search(text), f"{where} cites {pattern.pattern}")

    def test_registry(self):
        for rule in RULES.values():
            with self.subTest(rule=rule.id):
                self.assertClean(rule.meaning, "meaning")
                self.assertClean(rule.fix, "fix")
                self.assertClean(explain(rule.id), "explain()")

    def test_protocol_section_9(self):
        text = section(ROOT / "protocol" / "documents.md", "## 9. Chain checks")
        for number, line in enumerate(text.splitlines(), 1):
            self.assertClean(line, f"§9 line {number}")

    def test_explain_output(self):
        for rule in RULES:
            with self.subTest(rule=rule):
                out = subprocess.run([sys.executable, str(BIN), "--explain", rule],
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(out.returncode, 0)
                self.assertClean(out.stdout, "--explain")

    def test_package_and_tests(self):
        files = [BIN, *sorted((ROOT / "lib" / "speckled_chain").glob("*.py")),
                 *sorted((ROOT / "tests" / "chain").glob("*.py"))]
        for path in files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for pattern in INTERNAL_REFS:
                    # This file names the patterns themselves; nothing else may match.
                    if path.name == "test_documentation.py":
                        text = text.replace(pattern.pattern, "")
                self.assertClean(text, path.name)


if __name__ == "__main__":
    unittest.main()
