#!/usr/bin/env python3
# speckled pre-commit notice v1
"""Speckled commit-time notice (git pre-commit hook).

Why this file exists:
    Approvals are recorded by editing documents, and they enter history only when a
    human commits. This hook lists, at that moment, every approval and status change
    the commit records, so one the human didn't make stands out before it's committed.

What it does:
    Reads `git diff --cached -U0 -- <docs_dir>` in the planning repo and collects the
    added lines that:
      - add an entry under `approvals:`          -> "<id> approved by <by> (v<version>)"
      - set `status: approved` or `status: done` -> "<id> set to <status>"
      - set a task's status to Done              -> "<task id> marked Done"
      - add an `Approved by` line under a task   -> "<task id> approved by <name>"
        (folded into the Done line when the same task is also marked Done)
    It prints them to stderr under "speckled: this commit records:", or nothing if
    there are none.

It never blocks a commit: it always exits 0, including on any error.

`speckled-gate install-git-hook` copies this file into the planning repo's
`.git/hooks/`, so it must stay self-contained: standard library only, no import from
the plugin's `lib/`. The marker comment on line 2 is how the installer recognizes it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
APPROVAL = re.compile(r"^\+\s+- \{by:")
STATUS = re.compile(r"^\+status:\s*(approved|done)\b")
TASK_DONE = re.compile(r"^\+- \*\*Status:\*\*\s*Done\b")
APPROVED_BY = re.compile(r"^\+Approved by (.+?)(?: on \S+)?\s*$")
TASK_HEADING = re.compile(r"^### (T-[\w-]+?):")
FRONT_MATTER_ID = re.compile(r"^id:\s*['\"]?([^'\"\s#]+)")
DOCS_DIR = re.compile(r"^docs_dir:\s*['\"]?([^'\"#\n]+?)['\"]?\s*(?:#.*)?$", re.M)


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout


def docs_dir() -> str:
    try:
        with open("speckled.yaml", encoding="utf-8") as f:
            m = DOCS_DIR.search(f.read())
        return m.group(1).strip() if m else "docs"
    except OSError:
        return "docs"


def staged_lines(path: str) -> list[str]:
    """The file as it is in the index (what's being committed)."""
    try:
        return git("show", f":{path}").splitlines()
    except RuntimeError:
        return []


def doc_id(lines: list[str], path: str) -> str:
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            m = FRONT_MATTER_ID.match(line)
            if m:
                return m.group(1)
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def task_at(lines: list[str], line_no: int) -> str:
    """The nearest `### T-…` heading at or above 1-based `line_no`."""
    for line in reversed(lines[:line_no]):
        m = TASK_HEADING.match(line)
        if m:
            return m.group(1)
    return "a task"


def field(entry: str, name: str) -> str:
    m = re.search(rf"\b{name}:\s*['\"]?([^,'\"}}]+)", entry)
    return m.group(1).strip() if m else "?"


def items_for_file(path: str, diff_lines: list[str]) -> list[str]:
    lines = staged_lines(path)
    ident = doc_id(lines, path)
    items: list[str] = []
    done: dict[str, int] = {}          # task id -> index of its "marked Done" item
    approved_by: dict[str, str] = {}   # task id -> name, from "Approved by" lines
    line_no = 0
    for d in diff_lines:
        m = HUNK.match(d)
        if m:
            line_no = int(m.group(1))
            continue
        if not d.startswith("+") or d.startswith("+++"):
            continue
        if APPROVAL.match(d):
            items.append(f"{ident} approved by {field(d, 'by')} (v{field(d, 'version')})")
        elif STATUS.match(d):
            items.append(f"{ident} set to {STATUS.match(d).group(1)}")
        elif TASK_DONE.match(d):
            task = task_at(lines, line_no)
            done[task] = len(items)
            items.append(f"{task} marked Done")
        elif APPROVED_BY.match(d):
            approved_by[task_at(lines, line_no)] = APPROVED_BY.match(d).group(1)
        line_no += 1
    for task, name in approved_by.items():
        if task in done:
            items[done[task]] += f" (approved by {name})"
        else:
            items.append(f"{task} approved by {name}")
    return items


def collect() -> list[str]:
    os.chdir(git("rev-parse", "--show-toplevel").strip())  # raises outside a git repo
    diff = git("-c", "core.quotepath=off", "diff", "--cached", "-U0", "--no-color",
               "--no-ext-diff", "--", docs_dir())
    items: list[str] = []
    path, chunk = None, []
    for line in diff.splitlines() + ["diff --git end"]:
        if line.startswith("diff --git "):
            if path:
                items += items_for_file(path, chunk)
            path, chunk = None, []
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        else:
            chunk.append(line)
    return items


def main() -> int:
    try:
        items = collect()
        if items:
            print("speckled: this commit records:", file=sys.stderr)
            for item in items:
                print(f"  {item}", file=sys.stderr)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
