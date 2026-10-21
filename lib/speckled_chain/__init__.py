"""speckled_chain: checks that a planning repo's record is intact.

Why this package exists:
    The gate (`speckled_gate`) decides, one tool call at a time, whether an agent may
    act. This package looks at the whole planning repo afterwards: whether every
    document is well-formed, cites an approved parent, and was approved by someone
    listed in `speckled.yaml`, whether the history keeps approvals and the enforcement
    log append-only, and which actions the gate let through in `warn` mode.
    It only reads; it never blocks anything. Protocol §9 lists its rules.

    It's a separate package so the hook's imports and start-up time stay unchanged.
    It reuses the gate's parsers (`speckled_gate.yamlio`, `speckled_gate.docs`), so the
    linter and the hook always agree on what a file says.

What it exports:
    - `load_corpus(root) -> Corpus`: the config and every document, parsed once
      (`corpus.py`).
    - `lint(root, *, history=True, feature=None, scope=None) -> Report`: run the checks
      (see there). Raises `ConfigError`, `GitError` or `OSError` where the command exits
      2. It never prints and never writes.
    - `chain_for(corpus, id) -> list[str]`: the IDs from a task or document up its
      chain, such as `T-F12-03` -> `[TASKS-F12, TDD-F12, FRD-F12, PDRD, BRIEF]`
      (`chain.py`).
    - `Finding`, `Report`: the results (`report.py`): `Report.findings`,
      `Report.to_json()` and `Report.exit_code(strict=False)`.
    - `RULES`, `explain`: the rule registry (`rules.py`).
    - `ConfigError`, `GitError`: why a run couldn't happen.
"""
from __future__ import annotations

from pathlib import Path

from .approvals import check_append_only, check_approvers, check_reopened, current_roles, history_roles
from .chain import chain_for, check_chain
from .config import ConfigError
from .corpus import Corpus, load_corpus
from .enforcement_log import check_log_history, check_log_now
from .history import GitError, open_history
from .report import Finding, Report, plugin_version
from .rules import RULES, explain
from .scope import Scope
from .structure import check_structure

__all__ = ["lint", "load_corpus", "chain_for", "Corpus", "Finding", "Report", "RULES", "explain",
           "ConfigError", "GitError"]


def lint(root: str | Path, *, history: bool = True, feature: str | None = None,
         scope=None) -> Report:
    """Check the planning repo at `root` and return the report.

    - `history=False` runs only the checks that need no history, and starts no git
      process (`--docs`).
    - `feature="F08"` keeps only the findings about `FRD-F08`, `TDD-F08`, `TASKS-F08`
      and the `T-F08-*` tasks, including their parent checks (`--feature`).
    - `scope=[ids]`, such as `chain_for(corpus, "T-F08-03")`, keeps only the findings
      about those documents and their tasks.
    With `feature` or `scope`, every check still runs, so the findings kept are the
    ones a full run gives for those documents. Findings about the log and the project
    as a whole are left out. The history read is narrowed to the paths the scoped
    documents have or could have had (`scope.py`). If that narrowed history shows a
    scoped document deleted, it may only have been moved from a path outside it, so the
    whole history is read instead.
    """
    corpus = load_corpus(root)
    narrow = Scope.of(corpus, feature, scope) if feature is not None or scope is not None else None
    findings = list(corpus.broken.values()) + check_structure(corpus) + check_chain(corpus)
    status, commits = "none", 0
    past = None
    if history:
        past = open_history(corpus.root, corpus.config.docs_dir, only=narrow.globs if narrow else None)
        if narrow is not None and any(change.new is None for change in past.changes):
            past = open_history(corpus.root, corpus.config.docs_dir)
    if past is not None:
        findings += past.findings
        status, commits = past.status, len(past.commits)
    if status == "full":
        # Each approval is checked against the roles of the commit that added it [T-F08-09].
        roles_for, added = history_roles(corpus, past)
        findings += check_approvers(corpus, roles_for, added) + check_append_only(past)
        # Edits to approved or done documents reopen review [T-F08-10].
        findings += check_reopened(past)
        # The enforcement log is only appended to [T-F08-11].
        findings += check_log_history(past.log_changes, past.reader)
    else:
        # Without history, approvers are checked against the current roles [T-F08-07].
        findings += check_approvers(corpus, current_roles(corpus))
    # Every log line is valid, and every warn event is reported, with or without history [T-F08-11].
    findings += check_log_now(corpus.root)
    documents = corpus.documents
    if narrow is not None:
        findings = [f for f in findings if narrow.wants(f)]
        documents = narrow.documents(corpus)
    return Report(project=corpus.config.project, plugin_version=plugin_version(), history=status,
                  documents=documents, commits=commits, findings=findings)
