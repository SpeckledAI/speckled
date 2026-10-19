"""Builders for test planning repos with a real git history [T-F08-04].

The gate's fixtures (`tests/gate/fixtures.py`) fake `.git` folders. The linter reads
history, so these build real repos: commits, moves, deletions, branches and merges,
shallow clones, and plain folders with no git at all.

Isolation:
    - git always runs with an argument list, never through a shell.
    - The user's git config can't leak in: no system config, an empty global config,
      `HOME` set to the temporary folder, and every inherited `GIT_*` variable removed
      (a `GIT_DIR` from a surrounding hook would otherwise point git at another repo).
    - `GIT_CEILING_DIRECTORIES` stops git from looking above the temporary folder, so a
      fixture never finds, or touches, a real repo.
    - Authors, committers and dates are fixed: each commit is one minute after the
      previous one, so histories are the same on every run and machine.

Documents:
    `brief()`, `pdrd()`, `arch()`, `research()`, `frd()`, `tdd()` and `tasks()` return
    Markdown with valid front matter, approved by `alice` by default. Keyword arguments
    override front-matter fields, and `body` replaces the body. Every title and body
    contains `SENTINEL`, so a privacy test can check that no report quotes them.
    `clean_project(repo)` commits one complete, valid chain.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SENTINEL = "zq-sentinel-text"

AUTHOR = ("Fixture Author", "author@example.invalid")
COMMITTER = ("Fixture Committer", "committer@example.invalid")
# The first commit's time; each later commit is one minute after the previous one.
BASE_TIME = int(datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc).timestamp())
DATE = "2026-10-01"
GATES = ("brief", "pdrd", "arch", "frd", "tdd", "tasks", "code")


def git_env(home: Path, minute: int = 0, author: str | None = None) -> dict:
    """An environment for git that ignores the user's own config and fixes the times."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    stamp = f"@{BASE_TIME + 60 * minute} +0000"
    global_config = home / "gitconfig"
    if not global_config.exists():
        global_config.write_text("", encoding="utf-8")
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(global_config),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CEILING_DIRECTORIES": str(home.parent),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": author or AUTHOR[0],
        "GIT_AUTHOR_EMAIL": AUTHOR[1],
        "GIT_COMMITTER_NAME": COMMITTER[0],
        "GIT_COMMITTER_EMAIL": COMMITTER[1],
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "LC_ALL": "C",
    })
    return env


def git(repo: Path, *args: str, home: Path, minute: int = 0, author: str | None = None) -> str:
    """Run `git <args>` in `repo` with the isolated environment; return its stdout."""
    out = subprocess.run(["git", *args], cwd=repo, env=git_env(home, minute, author),
                         check=True, capture_output=True, text=True, timeout=60)
    return out.stdout


_run_git = git   # for PlanRepo, whose `git` argument hides this function


def _inside_temp(path: Path) -> Path:
    """`path`, resolved, refusing anything outside the system's temporary folder."""
    resolved = path.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if resolved != temp and temp not in resolved.parents:
        raise ValueError(f"fixtures are built only under {temp}, not {resolved}")
    return resolved


class PlanRepo:
    """A planning repo at `<tmp>/plans`, with `speckled.yaml` and, by default, git.

    `nested=True` puts it at `<tmp>/repo/plans`, a folder inside a larger git repository
    whose root is `<tmp>/repo`. `object_format="sha256"` makes a SHA-256 repository.
    """

    def __init__(self, tmp, roles: dict | None = None, docs_dir: str = "docs", git: bool = True,
                 project: str = "example", nested: bool = False, object_format: str | None = None):
        self.tmp = _inside_temp(Path(tmp))
        self.git_root = self.tmp / "repo" if nested else self.tmp / "plans"
        self.root = self.git_root / "plans" if nested else self.git_root
        self.docs_dir = docs_dir
        self.has_git = git
        self.minute = 0
        self.root.mkdir(parents=True)
        if roles is None:
            roles = {gate: ["alice"] for gate in GATES}
        lines = [f"project: {project}", f"docs_dir: {docs_dir}", "roles:"]
        lines += [f"  {gate}: {json.dumps(names)}" for gate, names in roles.items()]
        self.write("speckled.yaml", "\n".join(lines) + "\n")
        if git:
            init = ["init", "-q", "--template=", "-b", "main"]
            if object_format:
                init.append(f"--object-format={object_format}")
            _run_git(self.git_root, *init, home=self.tmp)
            self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, author: str | None = None) -> str:
        if not self.has_git:
            raise RuntimeError("this fixture has no git repo")
        return git(self.root, *args, home=self.tmp, minute=self.minute, author=author)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def doc(self, rel: str) -> str:
        """`rel` under `docs_dir`, as a path relative to the repo."""
        return f"{self.docs_dir}/{rel}"

    def commit(self, message: str, author: str | None = None) -> str:
        """Stage everything and commit it; return the new commit's SHA."""
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, author=author)
        self.minute += 1
        return self.head()

    def move(self, src: str, dst: str) -> None:
        target = self.root / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.root / src).rename(target)

    def delete(self, rel: str) -> None:
        (self.root / rel).unlink()

    def branch(self, name: str) -> None:
        self.git("branch", name)

    def checkout(self, name: str) -> None:
        self.git("checkout", "-q", name)

    def merge(self, name: str, message: str | None = None) -> str:
        """Merge `name` into the current branch with a merge commit; return its SHA."""
        self.git("merge", "-q", "--no-ff", "-m", message or f"Merge {name}", name)
        self.minute += 1
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def shallow_clone(self, dest, depth: int = 1) -> Path:
        """A `--depth` clone of this repo at `dest`, through a file:// URL so it's really shallow."""
        dest = _inside_temp(Path(dest).parent) / Path(dest).name
        git(self.tmp, "clone", "-q", f"--depth={depth}", self.root.as_uri(), str(dest), home=self.tmp)
        return dest


# --- documents -----------------------------------------------------------------------

def approval(role: str, by: str = "alice", date: str = DATE, version: int = 1, note: str | None = None) -> dict:
    entry = {"by": by, "role": role, "date": date, "version": version}
    if note is not None:
        entry["note"] = note
    return entry


_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")


def _value(value) -> str:
    """A YAML scalar: plain when safe, otherwise JSON-quoted (JSON strings are valid YAML)."""
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    text = str(value)
    return text if _PLAIN.match(text) and not text.endswith(" ") else json.dumps(text)


def _front_matter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if key == "approvals":
            if not value:
                lines.append("approvals: []")
                continue
            lines.append("approvals:")
            for entry in value:
                inner = ", ".join(f"{k}: {_value(v)}" for k, v in entry.items())
                lines.append(f"  - {{{inner}}}")
        else:
            lines.append(f"{key}: {_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _document(fields: dict, body: str, overrides: dict) -> str:
    """Front matter from `fields` updated by `overrides` (a value of None drops the field)."""
    body = overrides.pop("body", body)
    merged = {**fields, **overrides}
    if "approvals" not in overrides:
        approved = merged.get("status") in ("approved", "done")
        merged["approvals"] = [approval(merged["type"], version=merged.get("version", 1))] if approved else []
    merged = {k: v for k, v in merged.items() if v is not None}
    return _front_matter(merged) + "\n" + body


def _base(id_: str, type_: str, title: str) -> dict:
    return {"id": id_, "title": f"{title} {SENTINEL}", "type": type_, "feature": None,
            "parent": None, "parent_version": None, "status": "approved", "version": 1,
            "updated": DATE}


def _body(heading: str) -> str:
    return f"# {heading}\n\nBody text {SENTINEL}.\n"


def brief(**kw) -> str:
    return _document(_base("BRIEF", "brief", "Example brief"), _body("BRIEF"), kw)


def pdrd(features=("F01",), **kw) -> str:
    fields = {**_base("PDRD", "pdrd", "Example roadmap"), "parent": "BRIEF", "parent_version": 1}
    body = _body("PDRD") + "\n## Features\n\n" + "".join(
        f"### {f}: Example feature {f}\n\nWhat it does {SENTINEL}.\n\n" for f in features)
    return _document(fields, body, kw)


def arch(**kw) -> str:
    return _document(_base("ARCH", "arch", "Example architecture"), _body("ARCH"), kw)


def research(id_: str, **kw) -> str:
    fields = {**_base(id_, "research", "Example research"), "status": "draft"}
    return _document(fields, _body(id_), kw)


def _feature_doc(prefix: str, type_: str, feature: str, parent: str, title: str, body: str, kw: dict) -> str:
    fields = {**_base(f"{prefix}-{feature}", type_, title), "feature": feature, "parent": parent,
              "parent_version": 1}
    return _document(fields, body, kw)


def frd(feature: str = "F01", **kw) -> str:
    return _feature_doc("FRD", "frd", feature, "PDRD", "Example requirements", _body(f"FRD-{feature}"), kw)


def tdd(feature: str = "F01", **kw) -> str:
    return _feature_doc("TDD", "tdd", feature, f"FRD-{feature}", "Example design", _body(f"TDD-{feature}"), kw)


@dataclass
class TaskSpec:
    id: str
    status: str = "Todo"
    depends_on: tuple = ()
    approved_by: list = field(default_factory=list)  # whole lines, e.g. "Approved by alice on 2026-10-02"

    def markdown(self) -> str:
        lines = [f"### {self.id}: Example task {SENTINEL}",
                 "- **Owner:** agent",
                 f"- **Depends on:** {', '.join(self.depends_on) or 'none'}",
                 f"- **Status:** {self.status}", ""]
        if self.approved_by:
            lines += [*self.approved_by, ""]
        lines += [f"What to build {SENTINEL}.", ""]
        return "\n".join(lines)


def task(id_: str, status: str = "Todo", depends_on=(), approved_by=()) -> TaskSpec:
    return TaskSpec(id_, status, tuple(depends_on), list(approved_by))


def tasks(feature: str = "F01", tasks=None, **kw) -> str:
    """A task list in the strict task format, with a summary table of the tasks' statuses."""
    specs = tasks if tasks is not None else [task(f"T-{feature}-01")]
    table = ["| Task | Depends on | Status |", "|---|---|---|"]
    table += [f"| {t.id} | {', '.join(t.depends_on) or 'none'} | {t.status} |" for t in specs]
    body = (_body(f"TASKS-{feature}") + "\n" + "\n".join(table) + "\n\n## Tasks\n\n"
            + "\n".join(t.markdown() for t in specs))
    return _feature_doc("TASKS", "tasks", feature, f"TDD-{feature}", "Example tasks", body, kw)


def log_line(mode: str = "warn", rule: str = "no-active-task", **kw) -> str:
    """One line of `.speckled/log.jsonl` in log format v1."""
    entry = {"v": 1, "ts": "2026-10-02T10:00:00Z", "mode": mode, "by": "alice", "tool": "Edit",
             "repo": "../app", "paths": ["src/main.py"], "task": "T-F01-02", "rule": rule, "agent": "main"}
    entry.update(kw)
    return json.dumps(entry) + "\n"


CLEAN_COMMITS = 6
CLEAN_FILES = {
    "speckled.yaml",
    "docs/brief.md",
    "docs/pdrd.md",
    "docs/frds/F01-example.md",
    "docs/tdds/F01-example.md",
    "docs/tasks/F01-example.md",
    ".speckled/log.jsonl",
}


def clean_project(repo: PlanRepo) -> PlanRepo:
    """Write and commit one full valid chain, one document per commit, then the log.

    BRIEF -> PDRD -> FRD-F01 -> TDD-F01 -> TASKS-F01, with T-F01-01 Done (its
    `Approved by` line has a note) and T-F01-02 In progress. The log has one `warn`
    line and one `block` line.
    """
    steps = [
        ("brief.md", brief()),
        ("pdrd.md", pdrd()),
        ("frds/F01-example.md", frd()),
        ("tdds/F01-example.md", tdd()),
        ("tasks/F01-example.md", tasks(tasks=[
            task("T-F01-01", "Done", approved_by=[f"Approved by alice on 2026-10-02 ({SENTINEL} checked)"]),
            task("T-F01-02", "In progress", depends_on=["T-F01-01"]),
        ])),
    ]
    for rel, text in steps:
        repo.write(repo.doc(rel), text)
        if repo.has_git:
            repo.commit(f"Add {rel}")
    repo.write(".speckled/log.jsonl", log_line("warn") + log_line("block", rule="git-commit", tool="Bash",
                                                                   repo="", paths=[]))
    if repo.has_git:
        repo.commit("Log")
    return repo
