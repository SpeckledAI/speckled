"""Findings, and the report `lint-chain` prints.

Why this module exists:
    The text report is for humans, and the JSON report (protocol §9, schema 1) is for
    CI and other tools. Both come from the same `Report`, in the same order, so two
    runs on the same repo give byte-identical output and a diff of two reports shows
    only what changed.

What it does:
    - `Finding`: one broken rule, at a file and line. `commit`, `by` and `date` are set
      only on findings from history.
    - `Report`: the findings plus a summary. It sorts them on construction: errors
      first, then file, line (`None` first), rule, subject and message.
    - `to_json()` gives schema 1; `render_text()` gives the text report;
      `exit_code(strict)` gives 1 if there's an error (or, with `strict`, any finding).
    - Nothing here quotes document text: messages are built by the checks, which may
      quote only structured values (protocol §9, "What messages may quote").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1
# lib/speckled_chain/report.py -> the plugin's root folder
_PLUGIN_JSON = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"

_RED, _YELLOW, _RESET = "\033[31m", "\033[33m", "\033[0m"
_RULE_WIDTH = 22  # the longest rule ID, `gate-without-approvers`
_INDENT = " " * (9 + _RULE_WIDTH + 1)


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # "error" or "warning"
    subject: str   # a document or task ID, or the file's path if it has no readable ID
    file: str | None  # relative to the planning repo, with forward slashes
    line: int | None  # 1-based
    message: str
    fix: str
    commit: str | None = None
    by: str | None = None
    date: str | None = None

    def to_json(self) -> dict:
        out = {"rule": self.rule, "severity": self.severity, "subject": self.subject,
               "file": self.file, "line": self.line}
        for key in ("commit", "by", "date"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        out["message"] = self.message
        out["fix"] = self.fix
        return out


def _sort_key(f: Finding):
    return (f.severity != "error", f.file or "", f.line is not None, f.line or 0,
            f.rule, f.subject, f.message)


@dataclass
class Report:
    project: str
    plugin_version: str
    history: str  # "full", "none" or "shallow"
    documents: int
    commits: int
    findings: list[Finding] = field(default_factory=list)

    def __post_init__(self):
        self.findings = sorted(self.findings, key=_sort_key)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return len(self.findings) - self.errors

    @property
    def warn_events(self) -> int:
        return sum(1 for f in self.findings if f.rule == "warn-event")

    def exit_code(self, strict: bool = False) -> int:
        if self.errors or (strict and self.findings):
            return 1
        return 0

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA,
            "tool": "lint-chain",
            "plugin_version": self.plugin_version,
            "project": self.project,
            "history": self.history,
            "summary": {"documents": self.documents, "commits": self.commits, "errors": self.errors,
                        "warnings": self.warnings, "warn_events": self.warn_events},
            "findings": [f.to_json() for f in self.findings],
        }

    def render_text(self, color: bool = False) -> str:
        """The text report. Colour only highlights the severity word, which is always there."""
        lines = [f"speckled lint-chain: {self.project} ({_count(self.documents, 'document')}, "
                 f"{_count(self.commits, 'commit')} of history)", ""]
        for f in self.findings:
            severity = f"{f.severity:<8}"
            if color:
                severity = (_RED if f.severity == "error" else _YELLOW) + severity + _RESET
            lines.append(f"{severity} {f.rule:<{_RULE_WIDTH}} {f.message}")
            if f.file:
                lines.append(_INDENT + (f"{f.file}:{f.line}" if f.line is not None else f.file))
            if f.fix:
                lines.append(_INDENT + f.fix)
        if self.findings:
            lines += ["", f"{_count(self.errors, 'error')}, {_count(self.warnings, 'warning')}. "
                          "Run lint-chain --explain <rule> for details."]
        else:
            lines.append("No problems found.")
        return "\n".join(lines) + "\n"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def plugin_version() -> str:
    """The plugin's version from `.claude-plugin/plugin.json`, or "unknown"."""
    try:
        return str(json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"
