"""Approval checks: every approval was recorded by someone listed for its gate, and kept.

Why this module exists:
    An approval is only worth something if the person who gave it may approve that
    gate, and if it can't be quietly changed afterwards. `speckled.yaml`'s `roles` lists
    who may approve each one, and protocol §9 ("Approvers", "Append-only rules") says
    how each approval is checked [T-F08-07, T-F08-09].

What it does:
    `check_approvers(corpus, roles_for, added=None)` returns the findings for these
    rules, skipping broken files and entries that aren't well-formed (those have a
    `front-matter` or `task-format` finding already):
    - `approval-role-mismatch`: an `approvals` entry's `role` isn't the gate for the
      document's `type`. The gate is the `type` itself, the key under `roles`. Its name
      isn't also checked: one wrong entry gives one finding.
    - `approver-not-listed`: the gate is under `roles`, but the entry's `by` isn't in
      its list. A task's `Approved by` name is checked against `roles.code`.
    - `gate-without-approvers`: approvals were recorded on a gate with no `roles`
      entry. One warning per gate, counting its approvals, and none of them is
      reported as `approver-not-listed`.
    `roles_for(entry)` gives the `roles` an entry is checked against: an `approvals`
    mapping or a task's `ApprovedBy`. Without history that's the current `roles`
    (`current_roles`). With history, `history_roles` gives `roles` as of the commit
    that added the entry, so removing an approver later doesn't invalidate their past
    approvals, and adding one later doesn't make an earlier approval valid. `added`
    gives that commit, which `approver-not-listed` findings then carry.

    `check_append_only(history)` compares each change from history, and the working
    tree against `HEAD`:
    - `approval-edited`: a committed `approvals` entry or `Approved by` line was
      changed or moved. Entries are compared field for field; `Approved by` lines
      per task, by position. All the entries moved in one document (or task) by one
      change are one finding, which says when a new entry was put before them.
    - `approval-removed`: one was removed.
    - `document-deleted`: a committed document was deleted, not moved (moves are
      already followed by `history.py`).
    A fault repeated by a merge, which is compared with its first parent, is reported
    once, at the commit that made it. A version whose approvals or tasks can't be read
    isn't compared; the next readable one is compared with the last readable one
    before it, so breaking a file can't hide a removal.

Messages quote only structured values (IDs, gates, approver names, commit IDs), never a
title, body text or an approval's note.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Callable

from .config import ConfigError, parse_config
from .corpus import Corpus, Doc, _field_lines
from .history import Change, Commit, History, Version, entry_keys
from .report import Finding
from .structure import TYPES, _finding

CODE = "code"
CONFIG = "speckled.yaml"

RolesFor = Callable[[object], dict]
AddedIn = Callable[[object], "Commit | None"]


def current_roles(corpus: Corpus) -> RolesFor:
    """A `roles_for` that checks every entry against the current `roles`."""
    return lambda entry: corpus.config.roles


def check_approvers(corpus: Corpus, roles_for: RolesFor, added: AddedIn | None = None) -> list[Finding]:
    findings: list[Finding] = []
    unlisted: dict[str, int] = {}   # gate with no `roles` entry -> approvals recorded on it

    def check(name: str, gate: str, entry, subject: str, file: str, line: int, what: str) -> None:
        roles = roles_for(entry)
        if gate not in roles:
            unlisted[gate] = unlisted.get(gate, 0) + 1
        elif name not in roles[gate]:
            commit = added(entry) if added else None
            when = (f"who wasn't listed under roles.{gate} in commit {commit.sha[:7]}, which added it"
                    if commit else f"who isn't listed under roles.{gate}")
            findings.append(_at(_finding("approver-not-listed", subject, file, line,
                                         f"{subject}: {what} is by '{name}', {when}."), commit))

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


# --- roles as of each entry's commit -------------------------------------------------

def history_roles(corpus: Corpus, history: History) -> tuple[RolesFor, AddedIn]:
    """A `roles_for` that uses `roles` as of the commit that added each entry, and that commit.

    An entry that isn't committed yet, or whose commit's `speckled.yaml` is missing or
    can't be read, is checked against the current `roles`, which are already validated.
    """
    # The history's name for the document now at each path: its id, or its first path.
    names: dict[str, str] = {}
    for change in history.changes:
        if change.new is not None:
            names[change.new.path] = change.doc

    # check_approvers hands back the corpus's own entry objects, so they're keyed by identity.
    keys: dict[int, tuple[str, tuple]] = {}
    wanted: dict[str, list[tuple]] = {}
    for doc in corpus.docs.values():
        name = names.get(doc.path)
        if name is None:
            continue
        entries = _entries(doc.meta) or []
        if doc.task_list is not None:
            entries += [a for task in doc.task_list.tasks.values() for a in task.approved_by]
        version = Version(doc.path, "", doc.text, doc.meta, doc.task_list)
        for entry, key in zip(entries, entry_keys(version)):
            keys[id(entry)] = (name, key)
            wanted.setdefault(name, []).append(key)
    commits = history.added_in(wanted)

    def added(entry) -> Commit | None:
        key = keys.get(id(entry))
        return commits.get(key) if key else None

    parsed: dict[str, dict | None] = {}   # speckled.yaml blob -> its roles, or None if unreadable

    def roles_for(entry) -> dict:
        commit = added(entry)
        blob = history.config_blob(commit.sha) if commit else None
        if blob is None or history.reader is None:
            return corpus.config.roles
        if blob not in parsed:
            try:
                parsed[blob] = parse_config(history.reader.read(blob).decode("utf-8"), corpus.root).roles
            except (ConfigError, UnicodeDecodeError):
                parsed[blob] = None
        roles = parsed[blob]
        return corpus.config.roles if roles is None else roles

    return roles_for, added


# --- append-only ---------------------------------------------------------------------

def check_append_only(history: History) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple] = set()

    def report(key: tuple, finding: Finding, commit: Commit | None) -> None:
        if key not in seen:
            seen.add(key)
            findings.append(_at(finding, commit))

    by_commit: dict[str | None, list[Change]] = {}
    for change in history.changes:
        by_commit.setdefault(change.commit.sha if change.commit else None, []).append(change)
    # Each commit's last readable version of each document, following first parents as
    # the history does, so a version that can't be read is compared past, not skipped.
    readable: dict[str, dict[str, Version]] = {}
    for commit in history.commits:
        base = readable.get(commit.parents[0], {}) if commit.parents else {}
        readable[commit.sha] = _replay(by_commit.get(commit.sha, []), base, report)
    _replay(by_commit.get(None, []), readable.get(_head(history), {}), report)
    return findings


def _replay(changes: list[Change], readable: dict[str, Version], report) -> dict[str, Version]:
    """Check one commit's changes against `readable`; return `readable` as of that commit."""
    if not changes:
        return readable
    readable = dict(readable)
    for change in changes:
        old, new = change.old, change.new
        if old is None and new is None:
            continue
        where = f" in commit {change.commit.sha[:7]}" if change.commit else " in the working tree"
        if new is None:
            subject = old.id or old.path
            report(("document-deleted", change.doc),
                   _finding("document-deleted", subject, old.path, None,
                            f"{subject} was deleted{where}, not moved."), change.commit)
            readable.pop(change.doc, None)
            continue
        if not _readable(new):
            continue   # compared once it's readable again
        before = old if old is not None and _readable(old) else readable.get(change.doc)
        if before is not None:
            _check_approvals(change, before, where, report)
            _check_approved_by(change, before, where, report)
        readable[change.doc] = new
    return readable


def _readable(version: Version) -> bool:
    """Whether a version's approvals, and its tasks if it's a task list, can be read."""
    if _entries(version.meta) is None:
        return False
    return version.meta.get("type") != "tasks" or version.task_list is not None


def _head(history: History) -> str | None:
    """The listed commit `HEAD` is at, or the last one it descends from if it touched nothing tracked."""
    if any(c.sha == history.head for c in history.commits):
        return history.head
    parents = {p for c in history.commits for p in c.parents}
    tips = [c.sha for c in history.commits if c.sha not in parents]
    return tips[-1] if tips else None


def _check_approvals(change: Change, old: Version, where: str, report) -> None:
    new = change.new
    before, after = _entries(old.meta), _entries(new.meta)
    subject = new.id or new.path
    key_line, lines = _lines(new)

    def label(i: int) -> str:
        by = before[i].get("by") if isinstance(before[i], dict) else None
        return f"approval {i + 1}" + (f" (by '{by}')" if _text(by) else "")

    def line(j: int | None) -> int:
        return lines[j] if j is not None and j < len(lines) else key_line

    def key(i: int) -> str:
        return json.dumps(before[i], sort_keys=True, default=str)

    _report_broken(_broken(before, after), "approval", "approvals", label, line, key,
                   subject, new.path, change, where, report)


def _check_approved_by(change: Change, old: Version, where: str, report) -> None:
    if old.task_list is None or change.new.task_list is None:
        return
    for task_id, task in old.task_list.tasks.items():
        if not task.approved_by:
            continue
        now = change.new.task_list.tasks.get(task_id)
        after = now.approved_by if now is not None else []
        before = [(a.name, a.date, a.note) for a in task.approved_by]

        def label(i: int, task=task) -> str:
            name = task.approved_by[i].name
            return f"`Approved by` line {i + 1}" + (f" (by '{name}')" if name else "")

        def line(j: int | None, after=after, now=now) -> int | None:
            return after[j].line if j is not None else (now.line if now is not None else None)

        _report_broken(_broken(before, [(a.name, a.date, a.note) for a in after]),
                       "`Approved by` line", "`Approved by` lines", label, line, before.__getitem__,
                       task_id, change.new.path, change, where, report, part=task_id)


def _report_broken(broken, noun: str, nouns: str, label, line, key, subject: str, path: str,
                   change: Change, where: str, report, part: str = "approval") -> None:
    """Report what `_broken` found: one finding per changed or removed entry, and one for any moves.

    Moves are one finding, so an entry added before the committed ones doesn't give a
    finding for each entry it pushed along.
    """
    moved = [(i, j) for what, i, j in broken if what == "moved"]
    inserted = any(what == "inserted" for what, _i, _j in broken)
    for what, i, j in broken:
        if what in ("changed", "removed"):
            rule = "approval-removed" if what == "removed" else "approval-edited"
            report((rule, change.doc, part, key(i)),
                   _finding(rule, subject, path, line(j), f"{subject}: {label(i)} was {what}{where}."),
                   change.commit)
    if not moved:
        return
    if len(moved) == 1:
        (i, j), = moved
        what = f"{label(i)} was moved to position {j + 1}"
    else:
        what = f"{nouns} {_join([str(i + 1) for i, _j in moved])} were moved"
    message = f"{subject}: {what}{where}."
    if inserted:
        message = (f"{subject}: {what}, because an entry was added before "
                   f"{'it' if len(moved) == 1 else 'them'}{where}. New {nouns} go at the end.")
    report(("approval-edited", change.doc, part, "moved", tuple(key(i) for i, _j in moved)),
           _finding("approval-edited", subject, path, line(moved[0][1]), message), change.commit)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _broken(old: list, new: list) -> list[tuple[str, int, int | None]]:
    """How `old` stopped being a prefix of `new`: (what, index in old, index in new).

    `what` is "changed" (another entry is in its place), "moved" or "removed" for an old
    entry, or "inserted" (index in old None) for a new entry placed before an old one.
    An entry shifted only because one before it was removed isn't also reported as moved.
    """
    free = list(range(len(new)))   # positions in `new` not matched to an old entry
    match: dict[int, int] = {}
    for i, entry in enumerate(old):
        j = i if i in free and new[i] == entry else next((j for j in free if new[j] == entry), None)
        if j is not None:
            match[i] = j
            free.remove(j)
    out: list[tuple[str, int, int | None]] = []
    removed = 0
    for i in range(len(old)):
        if i in match:
            if match[i] != i - removed:
                out.append(("moved", i, match[i]))
        elif i in free:
            free.remove(i)
            out.append(("changed", i, i))
        else:
            removed += 1
            out.append(("removed", i, None))
    last = max(match.values(), default=-1)
    out += [("inserted", None, j) for j in free if j < last]
    return out


def _entries(meta: dict | None) -> list | None:
    """A version's `approvals` entries ([] if there are none), or None if they can't be read."""
    if meta is None:
        return None
    approvals = meta.get("approvals")
    if approvals is None:
        return []
    return list(approvals) if isinstance(approvals, list) else None


def _lines(version: Version) -> tuple[int, list[int]]:
    """The line of `approvals:` in `version`, and of each of its entries."""
    doc = Doc(path=version.path, rel="", meta=version.meta or {}, text=version.text)
    lines = version.text.splitlines()
    end = next((n for n in range(1, len(lines)) if lines[n].strip() == "---"), len(lines))
    _field_lines(doc, lines[1:end])
    return doc.line("approvals"), doc.approval_lines


def _at(finding: Finding, commit: Commit | None) -> Finding:
    """`finding`, carrying the commit it was found in (its ID, author name and date)."""
    if commit is None:
        return finding
    return replace(finding, commit=commit.sha, by=commit.author, date=commit.date)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
