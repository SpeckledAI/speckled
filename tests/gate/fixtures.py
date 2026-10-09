"""Builders for test projects: a planning repo plus code repos in a temporary folder."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    tmp: Path                  # the temporary folder holding everything
    root: Path                 # the planning repo (tmp/plans)
    repos: dict[str, Path]     # code repos by name (tmp/<name>)


def make_project(tmp, yaml_text: str, code_repos=("app",), files: dict | None = None) -> Paths:
    """Create `tmp/plans` (with `speckled.yaml` and `docs/tasks/`) and `tmp/<repo>` folders.

    Every repo gets a `.git` folder so it looks like a git repo; no real git is needed.
    `files` maps paths relative to `tmp` to their content.
    """
    tmp = Path(tmp)
    root = tmp / "plans"
    (root / "docs" / "tasks").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "speckled.yaml").write_text(yaml_text)
    repos = {}
    for name in code_repos:
        repo = tmp / name
        (repo / ".git").mkdir(parents=True)
        repos[name] = repo
    for rel, content in (files or {}).items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return Paths(tmp, root, repos)
