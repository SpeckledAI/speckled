"""Tests for lib/speckled_chain/report.py [T-F08-03]."""
import json
import unittest

from speckled_chain.report import Finding, Report, plugin_version


def finding(rule="bad-id", severity="error", subject="FRD-F01", file="docs/frds/F01-x.md", line=3,
            message="m", **kw):
    return Finding(rule, severity, subject, file, line, message, "fix it", **kw)


def report(*findings):
    return Report(project="example", plugin_version="9.9.9", history="full", documents=4, commits=7,
                  findings=list(findings))


class SortOrder(unittest.TestCase):
    def test_errors_first_then_file_line_rule_subject_message(self):
        given = [
            finding(severity="warning", file="a.md", line=1),
            finding(file="b.md", line=2),
            finding(file="b.md", line=None),
            finding(file="a.md", line=9, rule="file-name"),
            finding(file="a.md", line=9, rule="bad-id", subject="TDD-F01"),
            finding(file="a.md", line=9, rule="bad-id", subject="FRD-F01", message="z"),
            finding(file="a.md", line=9, rule="bad-id", subject="FRD-F01", message="a"),
            finding(file=None, line=None, rule="history-unavailable"),
        ]
        got = [(f.severity, f.file, f.line, f.rule, f.subject, f.message) for f in report(*given).findings]
        self.assertEqual(got, [
            ("error", None, None, "history-unavailable", "FRD-F01", "m"),
            ("error", "a.md", 9, "bad-id", "FRD-F01", "a"),
            ("error", "a.md", 9, "bad-id", "FRD-F01", "z"),
            ("error", "a.md", 9, "bad-id", "TDD-F01", "m"),
            ("error", "a.md", 9, "file-name", "FRD-F01", "m"),
            ("error", "b.md", None, "bad-id", "FRD-F01", "m"),
            ("error", "b.md", 2, "bad-id", "FRD-F01", "m"),
            ("warning", "a.md", 1, "bad-id", "FRD-F01", "m"),
        ])

    def test_order_does_not_depend_on_input_order(self):
        given = [finding(file=f"{c}.md") for c in "cab"] + [finding(severity="warning")]
        self.assertEqual(report(*given).findings, report(*reversed(given)).findings)


class Json(unittest.TestCase):
    def test_schema_1_keys(self):
        data = report(finding(), finding(rule="warn-event", severity="warning")).to_json()
        self.assertEqual(list(data), ["schema", "tool", "plugin_version", "project", "history",
                                      "summary", "findings"])
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["tool"], "lint-chain")
        self.assertEqual(data["plugin_version"], "9.9.9")
        self.assertEqual(data["project"], "example")
        self.assertEqual(data["history"], "full")
        self.assertEqual(data["summary"], {"documents": 4, "commits": 7, "errors": 1, "warnings": 1,
                                           "warn_events": 1})
        self.assertEqual(list(data["findings"][0]),
                         ["rule", "severity", "subject", "file", "line", "message", "fix"])
        json.dumps(data)  # serializable

    def test_history_keys_only_when_set(self):
        f = finding(commit="a" * 40, by="alice", date="2026-10-12")
        self.assertEqual(list(f.to_json()), ["rule", "severity", "subject", "file", "line",
                                             "commit", "by", "date", "message", "fix"])
        self.assertNotIn("by", finding(commit="a" * 40).to_json())

    def test_null_file_and_line(self):
        f = finding(file=None, line=None).to_json()
        self.assertIsNone(f["file"])
        self.assertIsNone(f["line"])

    def test_plugin_version_from_manifest(self):
        self.assertRegex(plugin_version(), r"^\d+\.\d+\.\d+$")


class ExitCode(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(report().exit_code(), 0)
        self.assertEqual(report().exit_code(strict=True), 0)

    def test_error(self):
        self.assertEqual(report(finding()).exit_code(), 1)
        self.assertEqual(report(finding()).exit_code(strict=True), 1)

    def test_warning_only(self):
        warning = finding(severity="warning")
        self.assertEqual(report(warning).exit_code(), 0)
        self.assertEqual(report(warning).exit_code(strict=True), 1)


class Text(unittest.TestCase):
    def test_clean_run(self):
        self.assertEqual(report().render_text(),
                         "speckled lint-chain: example (4 documents, 7 commits of history)\n\n"
                         "No problems found.\n")

    def test_singular_counts(self):
        r = Report(project="p", plugin_version="1", history="full", documents=1, commits=1)
        self.assertIn("(1 document, 1 commit of history)", r.render_text())

    def test_findings_and_totals(self):
        text = report(finding(message="FRD-F01: bad"), finding(severity="warning", file=None)).render_text()
        lines = text.splitlines()
        self.assertTrue(lines[2].startswith("error    bad-id "))
        self.assertTrue(lines[2].endswith(" FRD-F01: bad"))
        self.assertEqual(lines[3].strip(), "docs/frds/F01-x.md:3")
        self.assertEqual(lines[4].strip(), "fix it")
        self.assertTrue(lines[5].startswith("warning  bad-id "))
        self.assertEqual(lines[6].strip(), "fix it")  # no location line without a file
        self.assertEqual(lines[-1], "1 error, 1 warning. Run lint-chain --explain <rule> for details.")
        self.assertNotIn("\033", text)

    def test_location_without_line(self):
        self.assertIn("docs/frds/F01-x.md\n", report(finding(line=None)).render_text())

    def test_colour_never_carries_meaning_alone(self):
        text = report(finding()).render_text(color=True)
        self.assertIn("\033[31m", text)
        self.assertIn("error", text)


if __name__ == "__main__":
    unittest.main()
