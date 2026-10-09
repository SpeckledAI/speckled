"""The enforcement log: a committed, append-only record of warn-mode events.

Why this module exists:
    In warn mode the gate lets an action through that it would otherwise block. The
    team, and later the traceability linter, need to see every such action, so each
    one is appended to `.speckled/log.jsonl` in the planning repo, which is committed.

What it does:
    - `entry()` builds one log entry in format version 1 (documented in the protocol):
      {"v", "ts", "mode", "by", "tool", "repo", "paths", "task", "rule", "agent"}
    - `append()` adds it to the log as a single line, creating `.speckled/` and its
      `.gitignore` if needed.
    - `git_user()` reads `git config user.name` for the `by` field.

What's never logged: file contents, command text (commands can contain secrets),
email addresses and absolute paths (they'd expose folder names). Paths are written
relative to their code repo, `repo` as it appears in speckled.yaml. Paths outside the
code repos are written relative to the planning repo (`repo: "."`), to the home folder
(`~/...`), or as a bare file name.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .project import Project, repo_for

VERSION = 1
LOG = Path(".speckled") / "log.jsonl"
_GITIGNORE = "active-task\n*.tmp\n"
_MAX_PATHS = 20  # keeps each entry well under 4 KB, so one write is one line


def entry(project: Project, *, mode: str, rule: str, tool: str, paths: list[str],
          task: str | None, by: str, agent: str) -> dict:
    """One log entry (format version 1). `paths` may be absolute; they're made relative."""
    repo, shown = _relative_paths(project, paths[:_MAX_PATHS])
    return {"v": VERSION, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": mode, "by": by, "tool": tool, "repo": repo, "paths": shown,
            "task": task, "rule": rule, "agent": agent}


def append(project: Project, item: dict) -> None:
    """Append `item` to the log as one line. Raises OSError; the caller decides what to do."""
    folder = project.root / ".speckled"
    folder.mkdir(exist_ok=True)
    gitignore = folder / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE)
    line = (json.dumps(item, ensure_ascii=False, separators=(", ", ": ")) + "\n").encode("utf-8")
    fd = os.open(project.root / LOG, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)  # one write: concurrent sessions never interleave a line
    finally:
        os.close(fd)


def git_user(cwd: str | Path | None = None) -> str:
    """`git config user.name`, or "" if git isn't available or it isn't set."""
    try:
        out = subprocess.run(["git", "config", "user.name"], cwd=cwd, capture_output=True,
                             text=True, timeout=2)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def display_path(project: Project, path: str) -> tuple[str, str]:
    """`path` as the log and the CLI show it: (repo, path relative to that repo)."""
    repo, shown = _relative_paths(project, [path])
    return repo, shown[0]


def _relative_paths(project: Project, paths: list[str]) -> tuple[str, list[str]]:
    """The repo (as written in speckled.yaml) and the paths relative to it."""
    repo, shown = "", []
    for path in paths:
        found = repo_for(project, path)
        if found:
            repo = repo or found[0]
            shown.append(found[1])
            continue
        real = Path(os.path.realpath(path))
        for base, label in ((project.root, "."), (project.home, "~")):
            try:
                rel = real.relative_to(base).as_posix()
                shown.append(rel if label == "." else f"~/{rel}")
                repo = repo or (label if label == "." else "")
                break
            except ValueError:
                continue
        else:
            shown.append(real.name)
    return repo, shown
