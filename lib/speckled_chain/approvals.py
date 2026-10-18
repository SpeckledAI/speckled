"""Approval checks: every approval was recorded by someone listed for its gate.

Why this module exists:
    An approval is only worth something if the person who gave it may approve that
    gate. `speckled.yaml`'s `roles` lists who may approve each one, and protocol §9
    ("Approvers") says how each approval is checked against it [T-F08-07].

What it does:
    `check_approvers(corpus, roles_for)` returns the findings for these rules, skipping
    broken files and entries that aren't well-formed (those have a `front-matter` or
    `task-format` finding already):
    - `approval-role-mismatch`: an `approvals` entry's `role` isn't the gate for the
      document's `type`. The gate is the `type` itself, the key under `roles`. Its name
      isn't also checked: one wrong entry gives one finding.
    - `approver-not-listed`: the gate is under `roles`, but the entry's `by` isn't in
      its list. A task's `Approved by` name is checked against `roles.code`.
    - `gate-without-approvers`: approvals were recorded on a gate with no `roles`
      entry. One warning per gate, counting its approvals, and none of them is
      reported as `approver-not-listed`.
    `roles_for(entry)` gives the `roles` an entry is checked against: an `approvals`
    mapping or a task's `ApprovedBy`. Without history that's the current `roles`.
    With history, it's `roles` as of the commit that added the entry, so removing an
    approver later doesn't invalidate their past approvals.

Messages quote only structured values (IDs, gates, approver names), never a title,
body text or an approval's note.
"""
from __future__ import annotations

from typing import Callable

from .corpus import Corpus
from .report import Finding
from .structure import TYPES, _finding

CODE = "code"
CONFIG = "speckled.yaml"

RolesFor = Callable[[object], dict]


def current_roles(corpus: Corpus) -> RolesFor:
    """A `roles_for` that checks every entry against the current `roles`."""
    return lambda entry: corpus.config.roles


def check_approvers(corpus: Corpus, roles_for: RolesFor) -> list[Finding]:
    findings: list[Finding] = []
    unlisted: dict[str, int] = {}   # gate with no `roles` entry -> approvals recorded on it

    def check(name: str, gate: str, entry, subject: str, file: str, line: int, what: str) -> None:
        roles = roles_for(entry)
        if gate not in roles:
            unlisted[gate] = unlisted.get(gate, 0) + 1
        elif name not in roles[gate]:
            findings.append(_finding("approver-not-listed", subject, file, line,
                                     f"{subject}: {what} is by '{name}', who isn't listed under roles.{gate}."))

    for doc in corpus.docs.values():
        approvals = doc.meta.get("approvals")
        if doc.type in TYPES and isinstance(approvals, list):
            for number, (entry, line) in enumerate(zip(approvals, doc.approval_lines), start=1):
                by, role = (entry.get("by"), entry.get("role")) if isinstance(entry, dict) else (None, None)
                if not (_text(by) and _text(role)):
                    continue
                if role != doc.type:
                    findings.append(_finding("approval-role-mismatch", doc.subject, doc.path, line,
                                             f"{doc.subject}: approval {number} has role '{role}', but the gate "
                                             f"for type {doc.type} is '{doc.type}'."))
                    continue
                check(by, role, entry, doc.subject, doc.path, line, f"approval {number}")
        if doc.task_list is not None:
            for task in doc.task_list.tasks.values():
                for approved in task.approved_by:
                    if approved.name is not None:
                        check(approved.name, CODE, approved, task.id, doc.path, approved.line,
                              "an `Approved by` line")

    for gate, count in sorted(unlisted.items()):
        approvals = "approval" if count == 1 else "approvals"
        findings.append(_finding("gate-without-approvers", CONFIG, CONFIG, None,
                                 f"Gate '{gate}' has no `roles` entry in {CONFIG}, so {count} {approvals} "
                                 "on it can't be checked."))
    return findings


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
