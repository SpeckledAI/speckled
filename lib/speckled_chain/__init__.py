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
    - `load_corpus(root) -> Corpus`: the config and every document, parsed once
      (`corpus.py`).
    - `lint(root, *, history=True, feature=None, scope=None) -> Report`: run the checks.
      Raises `ConfigError` or `OSError` where the command exits 2. It never prints and
      never writes.
    - `Finding`, `Report`: the results (`report.py`).
    - `RULES`, `explain`: the rule registry (`rules.py`).
"""
from __future__ import annotations

from pathlib import Path

from .config import ConfigError
from .corpus import Corpus, load_corpus
from .report import Finding, Report, plugin_version
from .rules import RULES, explain
from .structure import check_structure

__all__ = ["lint", "load_corpus", "Corpus", "Finding", "Report", "RULES", "explain", "ConfigError"]


def lint(root: str | Path, *, history: bool = True, feature: str | None = None,
         scope=None) -> Report:
    """Check the planning repo at `root` and return the report."""
    corpus = load_corpus(root)
    findings = list(corpus.broken.values()) + check_structure(corpus)
    # History, scoping and the remaining checks are added by later tasks [T-F08-05].
    return Report(project=corpus.config.project, plugin_version=plugin_version(), history="none",
                  documents=corpus.documents, commits=0, findings=findings)
