"""Read the parts of speckled.yaml that `lint-chain` needs.

Why this module exists:
    `lint-chain` needs the project's name, where its documents live, and who may
    approve each gate. The gate's own loader (`speckled_gate.project`) reads only the
    gate's settings and forgives mistakes so it never stops an engineer's work. The
    linter is the opposite: a malformed `roles` would make every approver check
    meaningless, so it stops (exit 2) and points at the line. YAML is still read
    through `speckled_gate.yamlio`, so both read the file the same way.

What it does:
    - `load_config(root)` returns `Config(project, docs_dir, roles)`.
      `project` defaults to the folder's name, `docs_dir` to `docs` and `roles` to `{}`.
    - Raises `ConfigError(reason, line)` for unreadable YAML, a `docs_dir` that isn't a
      string, a `roles` that isn't a mapping, or a role whose value isn't a list of
      strings. A missing file raises `OSError`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from speckled_gate.yamlio import YamlError, loads


class ConfigError(ValueError):
    """speckled.yaml can't be used. `line` is 1-based; `reason` says what's wrong there."""

    def __init__(self, reason: str, line: int):
        super().__init__(f"speckled.yaml line {line}: {reason}")
        self.reason = reason
        self.line = line


@dataclass(frozen=True)
class Config:
    project: str
    docs_dir: str  # relative to the planning repo, as written
    roles: dict[str, list[str]] = field(default_factory=dict)  # gate -> approver names


def load_config(root: str | Path) -> Config:
    root = Path(root)
    text = (root / "speckled.yaml").read_text(encoding="utf-8")
    try:
        data = loads(text)
    except YamlError as e:
        raise ConfigError(e.reason, e.line) from None

    project = data.get("project")
    project = root.resolve().name if project is None else str(project)

    docs_dir = data.get("docs_dir", "docs")
    if not isinstance(docs_dir, str) or not docs_dir.strip():
        raise ConfigError("docs_dir must be a folder name, such as docs", _line(text, "docs_dir"))

    roles = data.get("roles")
    if roles is None:
        roles = {}
    if not isinstance(roles, dict):
        raise ConfigError("roles must map each gate to a list of names, such as frd: [alice]",
                          _line(text, "roles"))
    roles_line = _line(text, "roles")
    checked = {}
    for gate, names in roles.items():
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ConfigError(f"roles.{gate} must be a list of names, such as [alice]",
                              _line(text, str(gate), after=roles_line, indented=True))
        checked[str(gate)] = list(names)
    return Config(project=project, docs_dir=docs_dir, roles=checked)


def _line(text: str, key: str, after: int = 0, indented: bool = False) -> int:
    """The 1-based line where `key:` is written (top level, or indented under `after`); 1 if not found."""
    indent = r"\s+" if indented else ""
    pattern = re.compile(rf"^{indent}['\"]?{re.escape(key)}['\"]?\s*:")
    for number, line in enumerate(text.splitlines(), 1):
        if number > after and pattern.match(line):
            return number
    return after or 1
