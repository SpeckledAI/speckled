"""Chain checks: every document cites the right parent, and that parent was approved.

Why this module exists:
    Speckled's record is a chain: BRIEF -> PDRD -> FRD -> TDD -> task list. A document
    whose parent is missing, of the wrong kind, or was never approved breaks the link
    between a line of code and the decision behind it. These checks read only the
    corpus, so they also run with `--docs` [T-F08-06].

What it does:
    - `check_chain(corpus)` returns the findings for these rules, skipping broken files
      (their one finding is already in `corpus.broken`). BRIEF, ARCH and research notes
      have no parent, so they aren't checked.
        - `parent-missing`: no `parent`, or no document has that ID. If a broken file
          could be the parent, it isn't reported: that file has its own finding.
        - `parent-wrong-type`: the parent isn't the one protocol §4's table expects:
          `BRIEF` for the PDRD, `PDRD` for an FRD, and the same feature's FRD or TDD
          for a TDD or task list.
        - `parent-unapproved`: the parent isn't `approved` or `done` and has no
          `approvals` entries. An error, or a warning if the child has the protocol §5
          rule 2 line.
        - `parent-reopened`: the parent has `approvals` entries but is now `draft`,
          `in-review` or `superseded`. A warning: revising an approved parent is normal.
      A parent that is `approved` with no entries counts as approved, since humans may
      set the status by hand. A `parent_version` below the parent's `version` isn't a
      finding: staleness isn't checked.
    - `chain_for(corpus, id)` gives the IDs from a document up to the top of its chain.
      A task ID starts at its task list. It stops at a missing parent, never loops,
      and raises KeyError for an ID that isn't in the corpus.

Messages quote only structured values (IDs, statuses), never a title or body text.
"""
from __future__ import annotations

import re

from .corpus import COMPLETED, Corpus, Doc
from .report import Finding
from .rules import RULES
from .structure import FEATURE_DOCS, STATUSES, _feature_of, _finding, _id_feature

APPROVED = ("approved", "done")
# The expected parent's type for each type that has one.
PARENT_TYPE = {"pdrd": "brief", "frd": "pdrd", "tdd": "frd", "tasks": "tdd"}
_TASK_ID = re.compile(r"T-F\d{2,}-\d{2,}")


def check_chain(corpus: Corpus) -> list[Finding]:
    findings: list[Finding] = []
    for doc in corpus.docs.values():
        if doc.type in PARENT_TYPE:
            findings += _parent(doc, corpus)
    return findings


def _expected_parent(doc: Doc) -> str | None:
    """The parent ID protocol §4's table gives `doc`, or None if its feature isn't known."""
    kind = PARENT_TYPE[doc.type]
    if kind == "brief":
        return "BRIEF"
    if kind == "pdrd":
        return "PDRD"
    feature = _feature_of(doc) or _id_feature(doc)
    return f"{FEATURE_DOCS[kind][0]}-{feature}" if feature else None


def _parent(doc: Doc, corpus: Corpus) -> list[Finding]:
    parent_id = doc.meta.get("parent")
    expected = _expected_parent(doc)
    if not (isinstance(parent_id, str) and parent_id):
        return [_finding("parent-missing", doc.subject, doc.path, 1 if parent_id is None else doc.line("parent"),
                         f"{doc.subject} has no parent; it should be {expected or 'set'}.")]
    line = doc.line("parent")
    if parent_id not in corpus.by_id:
        if _maybe_broken(parent_id, corpus):
            return []
        return [_finding("parent-missing", doc.subject, doc.path, line,
                         f"{doc.subject}: parent {parent_id} isn't the id of any document.")]

    parent = corpus.by_id[parent_id][0]
    if (expected is not None and parent_id != expected) or parent.type != PARENT_TYPE[doc.type]:
        should = expected or f"a document of type {PARENT_TYPE[doc.type]}"
        return [_finding("parent-wrong-type", doc.subject, doc.path, line,
                         f"{doc.subject}: parent {parent_id} should be {should}.")]

    status = parent.meta.get("status")
    approvals = parent.meta.get("approvals")
    # A missing or invalid status already has its own `front-matter` finding on the parent.
    if status in APPROVED or status not in STATUSES:
        return []
    if not (isinstance(approvals, list) and approvals):
        severity = "warning" if doc.rule2_line else RULES["parent-unapproved"].severity
        return [Finding("parent-unapproved", severity, doc.subject, doc.path, line,
                        f"{doc.subject}: parent {parent_id} is {status} and has never been approved.",
                        RULES["parent-unapproved"].fix)]
    return [_finding("parent-reopened", doc.subject, doc.path, line,
                     f"{doc.subject}: parent {parent_id} was approved before but is now {status}.")]


def _maybe_broken(parent_id: str, corpus: Corpus) -> bool:
    """Whether a broken file could be the document `parent_id`, by its subject or path."""
    docs_dir = corpus.config.docs_dir.strip("/")
    prefix = f"{re.escape(docs_dir)}/" if docs_dir and docs_dir != "." else ""
    fixed = {"BRIEF": "brief", "PDRD": "pdrd", "ARCH": "architecture"}
    feature_doc = re.fullmatch(r"(FRD|TDD|TASKS)-(F\d{2,})", parent_id)
    pattern = None
    if parent_id in fixed:
        pattern = rf"{prefix}(?:{COMPLETED}/)?{fixed[parent_id]}\.md"
    elif feature_doc:
        folder = dict(FEATURE_DOCS.values())[feature_doc.group(1)]
        pattern = rf"{prefix}{folder}/(?:{COMPLETED}/)?{feature_doc.group(2)}-[^/]*\.md"
    return any(finding.subject == parent_id or (pattern is not None and re.fullmatch(pattern, path))
               for path, finding in corpus.broken.items())


def chain_for(corpus: Corpus, id_: str) -> list[str]:
    """The IDs from `id_` up its chain of parents: `T-F12-03` -> `[TASKS-F12, TDD-F12, FRD-F12, PDRD, BRIEF]`.

    A task ID starts at the task list that holds it. Raises KeyError if no document or
    task has that ID.
    """
    doc = _task_list_of(corpus, id_) if _TASK_ID.fullmatch(id_) else None
    if doc is None:
        if id_ not in corpus.by_id:
            raise KeyError(id_)
        doc = corpus.by_id[id_][0]
    chain = [doc.id]
    while True:
        parent_id = doc.meta.get("parent")
        if not (isinstance(parent_id, str) and parent_id in corpus.by_id) or parent_id in chain:
            return chain
        chain.append(parent_id)
        doc = corpus.by_id[parent_id][0]


def _task_list_of(corpus: Corpus, task_id: str) -> Doc | None:
    """The first task list, by path, that holds `task_id`."""
    for doc in corpus.docs.values():
        if doc.task_list is not None and doc.id is not None and task_id in doc.task_list.tasks:
            return doc
    return None
