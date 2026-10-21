"""Narrowing a run to one feature, or to a list of document IDs.

Why this module exists:
    `lint-chain` checks one feature's documents, and a caller that cares
    about one task's chain passes `scope=chain_for(corpus, "T-F08-03")`. Both run the
    same checks as a full run, then keep only the findings about those documents, and
    read only their part of the history, so a narrowed run is faster but never
    stricter or looser [T-F08-12].

What it does:
    `Scope.of(corpus, feature, ids)` gives what's in scope:
    - `--feature Fnn`: `FRD-Fnn`, `TDD-Fnn`, `TASKS-Fnn` and every `T-Fnn-*` task.
    - `ids`: those documents, and the tasks of any task list among them.
    - Both: the documents in both, and their tasks.
    `Scope.wants(finding)` keeps a finding whose subject is one of those documents or
    tasks (their parent checks included, since a parent check's subject is the child),
    or that's about a file in scope without a readable ID. Findings about the log and
    the project as a whole (`speckled.yaml`) are left out. `history-unavailable` is
    always kept: it says the run itself was incomplete.
    `Scope.globs` are the paths whose history is read: each document's current path,
    and every path protocol §4 allows its ID, with or without `completed/`. A document
    moved between those paths is followed as in a full run. One moved from anywhere
    else looks added, and one moved anywhere else looks deleted, so `lint` rereads the
    whole history when a narrowed one has a deletion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .corpus import COMPLETED, Corpus
from .history import _docs_prefix, _glob_matcher, glob_escape
from .report import Finding
from .structure import FEATURE_DOCS, FIXED

_FEATURE_DOC = re.compile(r"(FRD|TDD|TASKS)-(F\d{2,})")
_FOLDERS = dict(FEATURE_DOCS.values())   # "FRD" -> "frds"
_FILES = dict(FIXED.values())            # "BRIEF" -> "brief.md"
_ALWAYS = ("history-unavailable",)


@dataclass
class Scope:
    ids: set[str]
    tasks: set[str]
    task_prefix: str | None   # "T-F08-" for --feature F08
    globs: list[str]

    @classmethod
    def of(cls, corpus: Corpus, feature: str | None, ids=None) -> Scope:
        wanted: set[str] | None = None
        if feature is not None:
            wanted = {f"{prefix}-{feature}" for prefix in _FOLDERS}
        if ids is not None:
            wanted = set(ids) if wanted is None else wanted & set(ids)
        tasks = {task for id_ in wanted for doc in corpus.by_id.get(id_, [])
                 if doc.task_list is not None for task in doc.task_list.tasks}
        prefix = f"T-{feature}-" if feature is not None and f"TASKS-{feature}" in wanted else None
        return cls(wanted, tasks, prefix, _globs(corpus, wanted))

    def wants(self, finding: Finding) -> bool:
        if finding.rule in _ALWAYS or finding.subject in self.ids or finding.subject in self.tasks:
            return True
        if self.task_prefix is not None and finding.subject.startswith(self.task_prefix):
            return True
        # A file in scope whose ID can't be read: its subject is its path.
        return finding.subject == finding.file and _glob_matcher(self.globs)(finding.file)

    def documents(self, corpus: Corpus) -> int:
        """How many of the corpus's documents, readable or not, are in scope."""
        matches = _glob_matcher(self.globs)
        return (sum(1 for doc in corpus.docs.values() if doc.id in self.ids)
                + sum(1 for path, f in corpus.broken.items() if f.subject in self.ids or matches(path)))


def _globs(corpus: Corpus, ids: set[str]) -> list[str]:
    prefix = glob_escape(_docs_prefix(corpus.config.docs_dir))
    globs: set[str] = set()
    paths: set[str] = set()
    for id_ in ids:
        paths |= {doc.path for doc in corpus.by_id.get(id_, [])}
        paths |= {path for path, f in corpus.broken.items() if f.subject == id_}
        feature_doc = _FEATURE_DOC.fullmatch(id_)
        if feature_doc:
            folder, name = _FOLDERS[feature_doc.group(1)], f"{feature_doc.group(2)}-*.md"
            globs |= {f"{prefix}{folder}/{name}", f"{prefix}{folder}/{COMPLETED}/{name}",
                      f"{prefix}{COMPLETED}/{name}"}
        elif id_ in _FILES:
            globs |= {f"{prefix}{_FILES[id_]}", f"{prefix}{COMPLETED}/{_FILES[id_]}"}
    # A current path the names don't cover, such as a misnamed file, is added as it is.
    matches = _glob_matcher(sorted(globs))
    globs |= {glob_escape(path) for path in paths if not matches(path)}
    return sorted(globs)
