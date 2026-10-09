"""Find the Speckled project and sort paths into protected, governed or free.

Why this module exists:
    Before the gate can judge an action it has to know which project the session is in
    and what the action touches. Plans live in a dedicated planning repo (with
    `speckled.yaml` at its root) next to the code repos it lists under `repos`. A
    session may start in either, so the planning repo has to be found from both.

What it does:
    - `find_project()` finds the planning repo by looking upward from the session's
      folder for `speckled.yaml`, and loads it into a `Project`. Speckled sessions start
      in the planning repo. If a session starts in one of the project's code repos
      instead, a small registry on this machine (`${CLAUDE_PLUGIN_DATA}/projects.json`)
      still connects it to its planning repo, and the project is marked `wrong_start`,
      so the rules can block code edits and say where to start rather than letting the
      session silently bypass the gate.
    - `refresh_registry()` records the project's code repos in that registry, from a
      normal start only.
    - `classify()` puts a path in one of three groups:
        protected  the gate's own controls; agents may never change them
        governed   code in a listed repo; changes need a valid active task
        free       everything else, including documents in the planning repo

Failing closed:
    A broken `speckled.yaml` must not switch the gate off (NFR4). If the file can't be
    read but still contains `enforcement: warn` or `block`, the project keeps that mode
    and records the error; since its repos are then unknown, everything outside the
    planning repo counts as governed. An unrecognised mode is treated as `block`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from .shell import _SUBST
from .yamlio import YamlError, loads

CONFIG = "speckled.yaml"
MODES = ("off", "warn", "block")
_RAW_MODE = re.compile(r"^enforcement:\s*['\"]?(warn|block)\b", re.MULTILINE)
# On macOS and Windows file names are case-insensitive, so compare them that way (S7).
_CASE_INSENSITIVE = sys.platform in ("darwin", "win32")


@dataclass
class Project:
    """A Speckled project, as loaded from its planning repo's `speckled.yaml`."""

    root: Path                       # the planning repo (real path)
    enforcement: str                 # "off", "warn" or "block"
    docs_dir: Path                   # absolute, inside the planning repo
    repos: list[Path]                # code repos (real paths); empty if unknown
    repo_names: list[str]            # the same repos as written in speckled.yaml (for logs)
    exempt: list[str]                # enforcement_exempt patterns
    plugin_root: Path | None = None  # ${CLAUDE_PLUGIN_ROOT}
    plugin_data: Path | None = None  # ${CLAUDE_PLUGIN_DATA}
    home: Path = field(default_factory=Path.home)
    config_error: str | None = None  # why speckled.yaml couldn't be used, if it couldn't
    # Set when the session started in a code repo instead of the planning repo: the
    # code repo's path. Speckled sessions start in the planning repo, so the rules
    # block governed and protected actions from a wrong start (TDD-F07 D4).
    wrong_start: Path | None = None

    @property
    def repos_unknown(self) -> bool:
        """True when the config couldn't be read, so the code repos aren't known."""
        return self.config_error is not None and not self.repos


# --- finding and loading -------------------------------------------------------------

def find_project(cwd: str | Path, plugin_root: str | Path | None = None,
                 plugin_data: str | Path | None = None,
                 home: str | Path | None = None) -> Project | None:
    """The project the session in `cwd` belongs to, or None if it isn't using Speckled.

    Speckled sessions start in the planning repo. A session that started in one of the
    project's code repos is still recognised (through the registry), so it isn't a
    silent way around the gate, but it's marked as a wrong start.
    """
    start = _real(cwd)
    # 1. The session is inside the planning repo (or below it): the normal start.
    root = _upward(start, lambda d: (d / CONFIG).is_file())
    if root is not None:
        return load_project(root, plugin_root, plugin_data, home)
    # 2. The session is inside a code repo: look its git root up in the registry.
    if plugin_data:
        git_root = _upward(start, lambda d: (d / ".git").exists())
        if git_root is not None:
            root = _registry_lookup(Path(plugin_data), git_root)
            if root is not None:
                project = load_project(root, plugin_root, plugin_data, home)
                project.wrong_start = git_root
                return project
    return None


def load_project(root: str | Path, plugin_root=None, plugin_data=None, home=None) -> Project:
    """Load `<root>/speckled.yaml`. Never raises for a bad config; see `config_error`."""
    root = _real(root)
    base = dict(root=root, docs_dir=root / "docs", repos=[], repo_names=[], exempt=[],
                plugin_root=_real(plugin_root) if plugin_root else None,
                plugin_data=_real(plugin_data) if plugin_data else None,
                home=_real(home) if home else _real(Path.home()))
    try:
        text = (root / CONFIG).read_text(encoding="utf-8")
    except OSError as e:
        return Project(enforcement="block", config_error=f"{CONFIG}: {e.strerror}", **base)
    try:
        config = loads(text)
    except YamlError as e:
        # Unreadable: keep a mode the author clearly set, so the gate stays on (NFR4).
        found = _RAW_MODE.search(text)
        mode = found.group(1) if found else "off"
        return Project(enforcement=mode, config_error=f"{CONFIG}: {e}", **base)

    mode = str(config.get("enforcement", "off") or "off").lower()
    if mode not in MODES:
        return Project(enforcement="block", **base,
                       config_error=f"{CONFIG}: enforcement must be off, warn or block, not '{mode}'")
    if mode == "off":
        return Project(enforcement="off", **base)

    names = config.get("repos") or []
    exempt = config.get("enforcement_exempt") or []
    if not (isinstance(names, list) and isinstance(exempt, list)):
        return Project(enforcement=mode, **base,
                       config_error=f"{CONFIG}: repos and enforcement_exempt must be lists")
    base.update(docs_dir=root / str(config.get("docs_dir") or "docs"),
                repos=[_real(root / str(n)) for n in names],
                repo_names=[str(n) for n in names],
                exempt=[str(p) for p in exempt])
    return Project(enforcement=mode, **base)


# --- registry ------------------------------------------------------------------------

def registry_path(plugin_data: str | Path) -> Path:
    return Path(plugin_data) / "projects.json"


def refresh_registry(project: Project) -> None:
    """Record this project's code repos in the machine-local registry. Never raises.

    Only from a normal start: a wrong start was found through the registry already.
    """
    if (project.enforcement == "off" or not project.plugin_data or not project.repos
            or project.wrong_start is not None):
        return
    try:
        path = registry_path(project.plugin_data)
        entries = _read_registry(path)
        for repo in project.repos:
            entries[str(repo)] = str(project.root)
        # Drop entries whose planning repo no longer has speckled.yaml.
        entries = {r: home for r, home in entries.items() if (Path(home) / CONFIG).is_file()}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"v": 1, "repos": entries}, indent=1, sort_keys=True))
        os.replace(tmp, path)  # atomic: readers never see a half-written file
    except (OSError, ValueError):
        pass  # the registry only helps discovery; failing to write it changes nothing


def _read_registry(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        repos = data.get("repos", {}) if data.get("v") == 1 else {}
        return {str(k): str(v) for k, v in repos.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _registry_lookup(plugin_data: Path, git_root: Path) -> Path | None:
    for repo, home in _read_registry(registry_path(plugin_data)).items():
        if _same(Path(repo), git_root) and (Path(home) / CONFIG).is_file():
            return Path(home)
    return None


# --- classifying paths ---------------------------------------------------------------

def classify(project: Project, path: str | Path, cwd: str | Path | None = None) -> str:
    """"protected", "governed" or "free" for `path` (relative paths are taken from `cwd`)."""
    raw = str(path)
    if _SUBST in raw:
        # Part of the path comes from a command's output, so where it points is unknown.
        return "governed"
    target = _real(Path(cwd or os.getcwd()) / os.path.expanduser(raw))

    if any(_matches(target, p, tree) for p, tree in _protected(project)):
        return "protected"
    if project.repos_unknown:
        # Config unreadable: anything outside the planning repo may be code (NFR4).
        return "free" if _within(target, project.root) else "governed"
    for repo in project.repos:
        if _within(target, repo):
            rel = _relative(target, repo)
            if any(fnmatch(rel, pattern) for pattern in project.exempt):
                return "free"
            return "governed"
    return "free"


def repo_for(project: Project, path: str | Path) -> tuple[str, str] | None:
    """(repo as written in speckled.yaml, path relative to it) if `path` is in a code repo."""
    target = _real(path)
    for repo, name in zip(project.repos, project.repo_names):
        if _within(target, repo):
            return name, _relative(target, repo)
    return None


def _protected(project: Project) -> list[tuple[Path, bool]]:
    """The protected paths (TDD-F07 §7 S3), each with True if everything under it counts."""
    root = project.root
    entries = [(root / CONFIG, False), (root / ".speckled", True), (root / ".git" / "hooks", True),
               (project.home / ".claude" / "settings.json", False)]
    for folder in [root, *project.repos]:
        entries += [(folder / ".claude" / "settings.json", False),
                    (folder / ".claude" / "settings.local.json", False)]
    if project.plugin_data:
        entries.append((project.plugin_data, True))
    if project.plugin_root:
        if any(_within(project.plugin_root, repo) for repo in project.repos):
            # Dogfooding (D10): the plugin is itself a listed code repo, so its code is
            # governed like any other; only the file that loads the hooks stays protected.
            entries.append((project.plugin_root / "hooks" / "hooks.json", False))
        else:
            entries.append((project.plugin_root, True))
    return [(_real(p), tree) for p, tree in entries]


# --- path helpers --------------------------------------------------------------------

def _real(path) -> Path:
    """Absolute path with symlinks and `..` resolved; missing parts are kept as written."""
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _key(path: Path) -> str:
    text = str(path)
    return text.lower() if _CASE_INSENSITIVE else text


def _same(a: Path, b: Path) -> bool:
    return _key(a) == _key(b)


def _within(path: Path, folder: Path) -> bool:
    """True if `path` is `folder` or anything under it."""
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def _matches(path: Path, protected: Path, tree: bool) -> bool:
    return _within(path, protected) if tree else _same(path, protected)


def _relative(path: Path, folder: Path) -> str:
    rel = str(path)[len(str(folder)):].lstrip(os.sep)
    return rel.replace(os.sep, "/")


def _upward(start: Path, found) -> Path | None:
    for folder in [start, *start.parents]:
        if found(folder):
            return folder
    return None
