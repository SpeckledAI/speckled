"""speckled_chain: checks that a planning repo's record is intact.

Why this package exists:
    The gate (`speckled_gate`) decides, one tool call at a time, whether an agent may
    act. This package looks at the whole planning repo afterwards: whether every
    document is well-formed, cites an approved parent, and was approved by someone
    listed in `speckled.yaml`, and whether the history keeps approvals append-only.
    It only reads; it never blocks anything. Protocol §9 lists its rules.

    It's a separate package so the hook's imports and start-up time stay unchanged.
    It reuses the gate's parsers (`speckled_gate.yamlio`, `speckled_gate.docs`), so the
    linter and the hook always agree on what a file says.

What it exports:
    - `lint(root, *, history=True, feature=None, scope=None) -> Report`: run the checks.
      Raises `ConfigError` or `OSError` where the command exits 2. It never prints and
      never writes.
    - `Finding`, `Report`: the results (`report.py`).
    - `RULES`, `explain`: the rule registry (`rules.py`).
"""
from __future__ import annotations

from pathlib import Path

from .config import ConfigError, load_config
from .report import Finding, Report, plugin_version
from .rules import RULES, explain

__all__ = ["lint", "Finding", "Report", "RULES", "explain", "ConfigError"]


def lint(root: str | Path, *, history: bool = True, feature: str | None = None,
         scope=None) -> Report:
    """Check the planning repo at `root` and return the report."""
    config = load_config(root)
    # The corpus and the checks are added by later tasks [T-F08-03].
    return Report(project=config.project, plugin_version=plugin_version(), history="none",
                  documents=0, commits=0, findings=[])
