"""The rule registry, protocol §9 and the README agree [T-F08-03] [T-F08-15].

`rules.py` is what `lint-chain` reports and `--explain` prints; protocol §9 is what
users read. This test fails if a rule, its default severity or its meaning differ.
The README must describe every rule, the command and the release tags. Internal
planning references are kept out of all of them.
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


LINT_CHAIN_SECTION = "## Checking the record: `lint-chain`"


class ReadmeDescribesLintChain(unittest.TestCase):
    def test_section_names_every_rule(self):
        text = section(ROOT / "README.md", LINT_CHAIN_SECTION)
        for rule in RULES:
            with self.subTest(rule=rule):
                self.assertIn(f"`{rule}`", text)
        self.assertIn("(protocol/documents.md)", text)

    def test_section_states_the_limits(self):
        text = section(ROOT / "README.md", LINT_CHAIN_SECTION)
        self.assertIn("Approver names aren't verified", text)
        self.assertIn("Rewritten history can't be detected", text)

    def test_section_is_in_contents(self):
        contents = section(ROOT / "README.md", "## Contents")
        self.assertIn("(#checking-the-record-lint-chain)", contents)

    def test_what_this_plugin_runs(self):
        self.assertIn("`bin/lint-chain`", section(ROOT / "README.md", "## What this plugin runs"))

    def test_release_rule_tags_releases(self):
        self.assertIn("`vX.Y.Z`", (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"))


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

    def test_readme_section_and_action_readme(self):
        texts = {"README.md": section(ROOT / "README.md", LINT_CHAIN_SECTION),
                 "actions/lint-chain/README.md": (ROOT / "actions" / "lint-chain" / "README.md").read_text(
                     encoding="utf-8")}
        for where, text in texts.items():
            with self.subTest(where=where):
                self.assertClean(text, where)

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
