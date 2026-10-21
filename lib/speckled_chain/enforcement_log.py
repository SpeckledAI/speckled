"""Enforcement log checks: the gate's log is only appended to, and every line is valid.

Why this module exists:
    `.speckled/log.jsonl` is the record of every action the gate allowed in `warn` mode
    and every block (protocol §8). That record only means something if nobody edits
    it, and if every bypass it holds is seen. Protocol §9 ("Append-only rules", "A
    valid log line") gives the rules [T-F08-11].

What it does:
    `check_log_history(log_changes, reader)` compares each version of the log from
    history, and the working tree against `HEAD`, with the one before it:
    - `log-edited`: the old version's lines aren't a line-for-line prefix of the new
      one's. One finding per change, at the first line that was changed or removed. A
      merge is compared with its first parent, so a fault a merge repeats is reported
      once, at the commit that made it.
    `check_log_now(root)` reads the log as it is on disk. A missing log isn't a finding.
    - `log-malformed`: a line isn't valid log format v1. One finding per line, naming
      the first field that's wrong. Extra fields are allowed, and `rule` may be any
      non-empty string, so a log written by a newer gate stays valid.
    - `warn-event`: a valid `mode: warn` line, as a warning that names its time,
      person, rule, task, repo and paths. `block` lines are valid and aren't reported.

Messages name fields and line numbers, and a warn event's values, which the gate
writes as metadata (protocol §8: never file contents, command text, email addresses
or absolute paths). A malformed line's values aren't quoted: they're not known to be
metadata.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .approvals import _at
from .history import LOG, BlobChange, BlobReader
from .report import Finding
from .structure import _finding

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_STRINGS = ("by", "tool", "repo", "agent")
_SHOWN_PATHS = 3   # a warn event names at most this many paths, then how many more


# --- append-only ---------------------------------------------------------------------

def check_log_history(log_changes: list[BlobChange], reader: BlobReader | None) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple] = set()
    for change in log_changes:
        if change.old is None or reader is None:
            continue   # a new log: nothing was committed before it
        old = reader.read(change.old).splitlines()
        new = reader.read(change.new).splitlines() if change.new is not None else []
        broken = _first_broken(old, new)
        if broken is None:
            continue
        what, index = broken
        # Keyed by the line broken, so a merge that repeats a branch's edit isn't reported again.
        key = (what, index, hashlib.sha256(old[index]).hexdigest())
        if key in seen:
            continue
        seen.add(key)
        where = f" in commit {change.commit.sha[:7]}" if change.commit else " in the working tree"
        if change.new is None:
            message = f"{LOG} was deleted{where}, removing its {_lines(len(old))}."
        elif what == "removed at end" and len(old) - index > 1:
            message = f"{LOG}: committed lines {index + 1}-{len(old)} were removed{where}."
        elif what == "removed at end":
            message = f"{LOG}: committed line {index + 1} was removed{where}."
        else:
            message = f"{LOG}: committed line {index + 1} was {what}{where}."
        line = index + 1 if index < len(new) else None
        findings.append(_at(_finding("log-edited", LOG, LOG, line, message), change.commit))
    return findings


def _first_broken(old: list[bytes], new: list[bytes]) -> tuple[str, int] | None:
    """Where `old` stops being a prefix of `new`: ("changed" | "removed" | "removed at end", index)."""
    for i, line in enumerate(old):
        if i >= len(new):
            return "removed at end", i
        if new[i] != line:
            # The next committed line moved up into this one's place: this one was removed.
            following = old[i + 1] if i + 1 < len(old) else None
            return ("removed" if following is not None and new[i] == following else "changed"), i
    return None


def _lines(n: int) -> str:
    return f"{n} line" + ("" if n == 1 else "s")


# --- the log as it is now ------------------------------------------------------------

def check_log_now(root: str | Path) -> list[Finding]:
    path = Path(root) / LOG
    if path.is_symlink() or not path.is_file():
        return []
    findings: list[Finding] = []
    for number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        entry, problem = _parse(raw)
        if problem is not None:
            findings.append(_finding("log-malformed", LOG, LOG, number,
                                     f"{LOG}: line {number} isn't valid log format v1: {problem}."))
        elif entry["mode"] == "warn":
            findings.append(_finding("warn-event", LOG, LOG, number, _warn_message(entry)))
    return findings


def _parse(raw: bytes) -> tuple[dict | None, str | None]:
    """The line as a mapping, or None and what's wrong with it (protocol §9, "A valid log line")."""
    try:
        entry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "it isn't JSON"
    if not isinstance(entry, dict):
        return None, "it isn't a JSON object"
    v = entry.get("v")
    if not (isinstance(v, int) and not isinstance(v, bool) and v == 1):
        return None, "`v` isn't 1" if "v" in entry else "`v` is missing"
    if not _is_ts(entry.get("ts")):
        return None, "`ts` isn't a UTC time YYYY-MM-DDTHH:MM:SSZ"
    if entry.get("mode") not in ("warn", "block"):
        return None, "`mode` isn't `warn` or `block`"
    for key in _STRINGS:
        if not isinstance(entry.get(key), str):
            return None, f"`{key}` isn't a string"
    paths = entry.get("paths")
    if not (isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
        return None, "`paths` isn't a list of strings"
    if "task" not in entry or not (entry["task"] is None or isinstance(entry["task"], str)):
        return None, "`task` isn't a string or null"
    rule = entry.get("rule")
    if not (isinstance(rule, str) and rule.strip()):
        return None, "`rule` isn't a non-empty string"
    return entry, None


def _is_ts(value) -> bool:
    if not (isinstance(value, str) and _TS.match(value)):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _warn_message(entry: dict) -> str:
    task = f"task {entry['task']}" if entry["task"] else "no active task"
    message = (f"{entry['ts']}: {entry['by']}'s {entry['tool']} was allowed in warn mode "
               f"(rule {entry['rule']}, {task})")
    paths = entry["paths"]
    if paths:
        shown = ", ".join(paths[:_SHOWN_PATHS])
        more = f" and {len(paths) - _SHOWN_PATHS} more" if len(paths) > _SHOWN_PATHS else ""
        message += f" on {entry['repo'] or 'the planning repo'}: {shown}{more}"
    return message + "."
