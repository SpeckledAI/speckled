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
      Raises `ConfigError`, `GitError` or `OSError` where the command exits 2. It never
      prints and never writes.
    - `chain_for(corpus, id) -> list[str]`: the IDs from a task or document up its
      chain, such as `T-F12-03` -> `[TASKS-F12, TDD-F12, FRD-F12, PDRD, BRIEF]`
      (`chain.py`).
    - `Finding`, `Report`: the results (`report.py`).
    - `RULES`, `explain`: the rule registry (`rules.py`).
"""
from __future__ import annotations

from pathlib import Path

from .approvals import check_approvers, current_roles
from .chain import chain_for, check_chain
from .config import ConfigError
from .corpus import Corpus, load_corpus
from .history import GitError, open_history
from .report import Finding, Report, plugin_version
from .rules import RULES, explain
from .structure import check_structure

__all__ = ["lint", "load_corpus", "chain_for", "Corpus", "Finding", "Report", "RULES", "explain",
           "ConfigError", "GitError"]


def lint(root: str | Path, *, history: bool = True, feature: str | None = None,
         scope=None) -> Report:
    """Check the planning repo at `root` and return the report."""
    corpus = load_corpus(root)
    findings = list(corpus.broken.values()) + check_structure(corpus) + check_chain(corpus)
    # Without history, approvers are checked against the current roles [T-F08-07].
    findings += check_approvers(corpus, current_roles(corpus))
    status, commits = "none", 0
    if history:
        past = open_history(corpus.root, corpus.config.docs_dir)
        findings += past.findings
        status, commits = past.status, len(past.commits)
    # The history checks, scoping and the log checks are added by later tasks [T-F08-08].
    return Report(project=corpus.config.project, plugin_version=plugin_version(), history=status,
                  documents=corpus.documents, commits=commits, findings=findings)
