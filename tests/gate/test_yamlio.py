"""Tests for lib/speckled_gate/yamlio.py and the bundled PyYAML [T-F07-02]."""
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from speckled_gate.yamlio import YamlError, loads

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "lib" / "speckled_gate" / "_vendor"

# Shaped like the README's example config: header comments, trailing comments,
# nested lists, a long plain value with an apostrophe, and a folded block.
SPECKLED_YAML = """\
# Acme planning repo, run with the Speckled plugin.
project: Acme Payments
docs_dir: docs
enforcement: off
repos:
  - ../acme-api    # code repo
constraints:
  - id: C1
    rule: Every payment requires explicit user confirmation, and a user's data never leaves their region.
  - id: C2
    rule: >
      No personal data in logs
      or queue payloads.
roles:
  brief: [alice]
  frd: [alice, bob]
"""

FRONT_MATTER = """\
id: FRD-F07
title: Approval Enforcement Hook
type: frd
parent_version: 3
status: approved
version: 4
updated: 2026-10-08
approvals:
  - {by: alice, role: frd, date: 2026-10-07, version: 1}
  - {by: alice, role: frd, date: 2026-10-08, version: 4, note: "Accepted, see §12"}
"""

FILL = {"nn": "07", "parent_version": "2", "date": "2026-10-08", "project": "Acme",
        "feature name": "Market Scanning", "slug": "pricing", "topic": "Pricing"}


def template_front_matter(path: Path) -> str:
    block = path.read_text().split("---\n")[1]
    return re.sub(r"\{\{([^}]+)\}\}", lambda m: FILL[m.group(1)], block)


class ReadsSpeckledFiles(unittest.TestCase):
    def test_speckled_yaml(self):
        self.assertEqual(loads(SPECKLED_YAML), {
            "project": "Acme Payments",
            "docs_dir": "docs",
            "enforcement": "off",
            "repos": ["../acme-api"],
            "constraints": [
                {"id": "C1", "rule": "Every payment requires explicit user confirmation, "
                                     "and a user's data never leaves their region."},
                {"id": "C2", "rule": "No personal data in logs or queue payloads.\n"},
            ],
            "roles": {"brief": ["alice"], "frd": ["alice", "bob"]},
        })

    def test_front_matter_with_flow_mapping_approvals(self):
        data = loads(FRONT_MATTER)
        self.assertEqual(data["version"], 4)
        self.assertEqual(data["updated"], "2026-10-08")
        self.assertEqual(data["approvals"], [
            {"by": "alice", "role": "frd", "date": "2026-10-07", "version": 1},
            {"by": "alice", "role": "frd", "date": "2026-10-08", "version": 4,
             "note": "Accepted, see §12"},
        ])

    def test_every_template_front_matter(self):
        templates = sorted((ROOT / "templates").glob("*.md"))
        self.assertTrue(templates)
        for path in templates:
            with self.subTest(template=path.name):
                data = loads(template_front_matter(path))
                self.assertEqual(data["status"], "draft")
                self.assertEqual(data["approvals"], [])
                self.assertIsInstance(data["updated"], str)


class KeepsTextAsWritten(unittest.TestCase):
    def test_bools_and_dates_stay_text(self):
        data = loads("a: off\nb: on\nc: yes\nd: no\ne: true\nf: False\ng: 2026-10-08\n")
        self.assertEqual(data, {"a": "off", "b": "on", "c": "yes", "d": "no",
                                "e": "true", "f": "False", "g": "2026-10-08"})

    def test_numbers_are_typed(self):
        self.assertEqual(loads("a: 12\nb: -3\nc: 1.5\n"), {"a": 12, "b": -3, "c": 1.5})

    def test_empty_document(self):
        self.assertEqual(loads("# only a comment\n\n"), {})


class ReportsErrorsWithLines(unittest.TestCase):
    CASES = [
        ("top-level list", "- a\n- b\n", 1, "mapping"),
        ("bad indentation", "a: 1\n  b: 2\n", 2, ""),
        ("unclosed bracket", "a: 1\nb: [1, 2\n", 3, ""),
        ("unclosed quote", 'a: 1\nb: "open\n', 3, ""),
        ("tab indentation", "a:\n\tb: 1\n", 2, ""),
    ]

    def test_errors(self):
        for name, text, line, reason in self.CASES:
            with self.subTest(name):
                with self.assertRaises(YamlError) as ctx:
                    loads(text)
                self.assertEqual(ctx.exception.line, line)
                self.assertIn(reason, ctx.exception.reason)
                self.assertTrue(str(ctx.exception).startswith(f"line {line}: "))

    def test_no_python_objects(self):
        with self.assertRaises(YamlError):
            loads("a: !!python/object/apply:os.system ['echo hi']\n")


class BundledCopy(unittest.TestCase):
    def test_manifest_matches_every_file(self):
        manifest = {}
        for line in (VENDOR / "MANIFEST.sha256").read_text().splitlines():
            digest, path = line.split(maxsplit=1)
            manifest[path[2:] if path.startswith("./") else path] = digest
        on_disk = {
            str(p.relative_to(VENDOR)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in VENDOR.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and p.name not in ("MANIFEST.sha256", "README.md")
        }
        self.assertEqual(on_disk, manifest)

    def test_c_binding_left_out(self):
        self.assertFalse((VENDOR / "yaml" / "cyaml.py").exists())

    def test_uses_bundled_copy_even_if_another_yaml_is_importable(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "yaml.py").write_text("raise ImportError('system yaml must not be used')\n")
            code = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]];"
                    "from speckled_gate import yamlio; print(yamlio.yaml.__file__)")
            out = subprocess.run([sys.executable, "-c", code, tmp, str(ROOT / "lib")],
                                 capture_output=True, text=True, check=True).stdout
        self.assertIn(str(Path("speckled_gate", "_vendor", "yaml")), out)


if __name__ == "__main__":
    unittest.main()
