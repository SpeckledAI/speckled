"""Decide whether an agent's action is allowed, and explain why not.

Why this module exists:
    This is the heart of the gate. Everything else either feeds actions in (the
    Claude Code hook, the CLI) or acts on the answer (block, warn and log). Keeping the
    decision in one pure function means every agent integration gets the same answer.

What it does:
    - `actions_for()` turns one tool call (Edit, Write, Bash, ...) into `Action`s: the
      files it would change, and whether it commits, pushes, opens a pull request or
      tries to switch the gate off.
    - `decide()` judges one action against the project and returns a `Verdict`:
      ok, or a violation naming the rule it breaks.
    - `outcome()` says what happens to a tool call given its verdicts and the mode:
      hard rules block in either mode; task rules warn in warn mode.
    - `message()` turns a violation into the short message the agent and the human
      see: what's wrong, what to do next, and, for a task rule, how a human can bypass it.

The order of checks (hard rules first):
    0. a broken speckled.yaml blocks governed and protected files (`config-unreadable`);
    a. the gate's own controls are never changed by agents (`protected-path`);
    b. agents don't commit, push, open pull requests or start sessions without hooks;
    c. a session started outside the planning repo may not change code
       (`wrong-start-folder`);
    d. files outside the code repos (including the planning docs) are free;
    e. code in a listed repo needs a valid active task: its list approved, the task
       In progress or In review, and every task it depends on Done. A task list that
       can't be read gives `config-unreadable`.

`decide()` and `message()` read files but never write them. The only writers are
`log.append` (the warn log) and `activate()` (the active-task marker).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import shell
from .docs import DocError, TaskList, find_task, load_task_list, load_task_lists
from .log import speckled_folder
from .project import Project, classify, repo_for

# Shell actions the gate acts on; rm -rf and secret .env access are the guard hook's job.
_FILE_KINDS = {"write", "delete", "move"}
# Shell action kind -> rule, for actions that are wrong whatever file they touch.
_ALWAYS = {"git-commit": "git-commit", "git-push": "git-push", "pull-request": "pull-request",
           "hooks-disabled": "hooks-disabled-session", "hooks-path": "protected-path"}
_MCP_PR = re.compile(r"(create|merge).*pull_?request", re.IGNORECASE)
_MCP_PUSH = re.compile(r"push|commit|create_or_update_file", re.IGNORECASE)


@dataclass(frozen=True)
class Action:
    """One thing a tool call would do. `path` is absolute, or None for git and PR actions."""

    kind: str               # write, delete, move, git-commit, git-push, pull-request, ...
    path: str | None
    tool: str               # the tool name, e.g. "Edit" or "Bash"
    detail: str = ""


@dataclass
class Verdict:
    """The answer for one action: ok (rule is None) or the rule it breaks."""

    rule: str | None = None
    action: Action | None = None
    task: str | None = None          # the active task, when it matters to the message
    facts: dict = field(default_factory=dict)  # details for the message (list id, dependency, ...)

    @property
    def ok(self) -> bool:
        return self.rule is None

    @property
    def hard(self) -> bool:
        """A hard rule blocks in warn mode too."""
        return self.rule in HARD_RULES


OK = Verdict()

# Rules that guard what only humans may do and the gate itself: they block whatever the
# mode. Every other rule is a task rule, which warn mode allows and logs.
HARD_RULES = frozenset({"protected-path", "hooks-disabled-session", "git-commit", "git-push",
                        "pull-request", "config-unreadable"})


def outcome(mode: str, verdicts: list[Verdict]) -> str:
    """What happens to a tool call: "ok", "warn" (allowed and logged) or "block"."""
    violations = [v for v in verdicts if not v.ok]
    if not violations:
        return "ok"
    if mode == "block" or any(v.hard for v in violations):
        return "block"
    return "warn"


def first_to_show(verdicts: list[Verdict]) -> Verdict:
    """The violation whose message is shown: the first hard one, else the first one."""
    violations = [v for v in verdicts if not v.ok]
    return next((v for v in violations if v.hard), violations[0])


# --- tool call -> actions --------------------------------------------------------------

def actions_for(tool_name: str, tool_input: dict, project: Project, cwd: str) -> list[Action]:
    """The actions one tool call would take. Relative paths are resolved against `cwd`."""
    if tool_name in ("Edit", "MultiEdit", "Write"):
        return _file_action(tool_input.get("file_path"), tool_name, cwd)
    if tool_name == "NotebookEdit":
        return _file_action(tool_input.get("notebook_path"), tool_name, cwd)
    if tool_name == "Bash":
        return _shell_actions(tool_input.get("command", ""), tool_name, cwd, files=True)
    if tool_name == "PowerShell":
        # Only git and pull-request commands are recognised in PowerShell.
        return _shell_actions(tool_input.get("command", ""), tool_name, cwd, files=False)
    if tool_name.startswith("mcp__"):
        name = tool_name.split("__")[-1]
        if _MCP_PR.search(name):
            return [Action("pull-request", None, tool_name)]
        if _MCP_PUSH.search(name):
            return [Action("git-push", None, tool_name)]
    return []


def _file_action(path, tool: str, cwd: str) -> list[Action]:
    if not path:
        return []
    return [Action("write", _absolute(path, cwd), tool)]


def _shell_actions(command: str, tool: str, cwd: str, files: bool) -> list[Action]:
    out = []
    for a in shell.actions(command):
        if a.kind in _ALWAYS:
            out.append(Action(a.kind, None, tool, a.detail))
        elif files and a.kind in _FILE_KINDS:
            # A command that changes files it doesn't name (git reset --hard, a patch,
            # find -delete, xargs rm) is taken to act on the repo it runs in.
            path = a.target if a.target is not None else str(_git_root(cwd))
            out.append(Action(a.kind, _absolute(path, cwd), tool, a.detail))
    return out


def _absolute(path: str, cwd: str) -> str:
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(cwd, path)


def _git_root(cwd: str) -> Path:
    start = Path(cwd)
    for folder in [start, *start.parents]:
        if (folder / ".git").exists():
            return folder
    return start


# --- deciding --------------------------------------------------------------------------

def decide(project: Project, action: Action) -> Verdict:
    """Whether `action` is allowed in `project`."""
    if project.enforcement == "off":
        return OK
    group = classify(project, action.path) if action.path else None
    touches_controls_or_code = group in ("protected", "governed")

    # Hard rules first, so warn mode can never let one through.
    # 0. A broken config blocks governed and protected files.
    if project.config_error and touches_controls_or_code:
        return Verdict("config-unreadable", action, facts={"error": project.config_error})
    # a. The gate's own controls.
    if group == "protected":
        return Verdict("protected-path", action)
    # b. Actions that are never the agent's to take.
    if action.kind in _ALWAYS:
        return Verdict(_ALWAYS[action.kind], action)
    # c. Wrong start folder: code edits only (protected files got protected-path above).
    if project.wrong_start is not None and group == "governed":
        return Verdict("wrong-start-folder", action)
    # d. Free files: the planning repo and anything outside the code repos.
    if group != "governed":
        return OK
    # e. Code: needs a valid active task.
    return _check_active_task(project, action)


def validate_task(project: Project, task_id: str | None, files: list[str] | None = None) -> Verdict:
    """Whether `task_id` may be worked on now; shared by `decide` and task activation.

    `files` (from the active-task marker) names the task lists that hold the
    task and its dependencies. Only those are read, freshly each time; if they no longer
    hold what was recorded, every list is read instead. The verdict is the same either
    way, except that a broken list the task doesn't need is never read.
    """
    if not task_id:
        return Verdict("no-active-task")
    try:
        lists = _recorded_lists(project, task_id, files) if files else None
        if lists is None:
            lists = load_task_lists(project.docs_dir)
    except DocError as e:
        return Verdict("config-unreadable", facts={"error": str(e)})
    return _judge(lists, task_id)


def _recorded_lists(project: Project, task_id: str, files: list[str]) -> list[TaskList] | None:
    """The recorded task lists, or None if they don't hold the task and its dependencies."""
    lists = []
    for name in files:
        try:
            task_list = load_task_list(project.docs_dir / name)
        except OSError:
            return None  # moved or deleted since activation
        if task_list is None:
            return None
        lists.append(task_list)
    found = find_task(lists, task_id)
    if found is None or any(find_task(lists, dep) is None for dep in found[1].depends_on):
        return None
    return lists


def _judge(lists: list[TaskList], task_id: str) -> Verdict:
    """The code-gate checks for `task_id`, against already loaded task lists."""
    found = find_task(lists, task_id)
    if found is None:
        return Verdict("no-active-task", task=task_id, facts={"unknown": task_id})
    task_list, task = found
    if task_list.status != "approved":
        return Verdict("task-list-not-approved", task=task_id,
                       facts={"list": task_list.id, "status": task_list.status})
    if task.status == "Todo":
        return Verdict("task-not-started", task=task_id)
    if task.status == "Done":
        return Verdict("task-done", task=task_id)
    for dep in task.depends_on:
        dep_found = find_task(lists, dep)
        if dep_found is None:
            return Verdict("dependency-missing", task=task_id,
                           facts={"dependency": dep, "list": task_list.id})
        if dep_found[1].status != "Done":
            return Verdict("dependency-not-done", task=task_id,
                           facts={"dependency": dep, "status": dep_found[1].status})
    return Verdict(task=task_id)


def active_task(project: Project) -> str | None:
    """The task in `.speckled/active-task`, or None if there isn't a readable one."""
    return active_marker(project)[0]


def active_marker(project: Project) -> tuple[str | None, list[str] | None]:
    """The active task and its recorded task-list files (None if absent or malformed)."""
    try:
        data = json.loads((project.root / ".speckled" / "active-task").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    task = data.get("task")
    if not (isinstance(task, str) and _is_task_id(task)):
        return None, None
    files = data.get("files")
    if not (isinstance(files, list) and files and all(_is_task_file(f) for f in files)):
        files = None
    return task, files


def _is_task_file(name) -> bool:
    """A relative path under `tasks/` with no `..`, as `activate` records them."""
    if not isinstance(name, str):
        return False
    path = PurePosixPath(name)
    return (not path.is_absolute() and path.parts[:1] == ("tasks",) and ".." not in path.parts
            and path.suffix == ".md")


def _is_task_id(text: str) -> bool:
    return re.fullmatch(r"T-F\d{2,}-\d{2,}", text) is not None


def activate(project: Project, task_id: str, by: str = "") -> Verdict:
    """Make `task_id` the active task, if it may be worked on now.

    Why: tells the hook gate which approved task the current code changes belong to. A
    tool call doesn't say why a file is being changed, so the gate needs this to check
    every code edit against a task: its parent list approved, the task In progress or In review,
    and every task it depends on Done. Once the task is Done (or its list is reopened),
    the next edit is blocked, so work can't drift past the plan.

    How: validates in code with `validate_task()`, the same check every governed edit
    gets. In order, the first failure refuses activation: the task lists can be read
    (config-unreadable); the task is in one of them (no-active-task); its list is
    approved (task-list-not-approved); the task is In progress or In review, not Todo
    (task-not-started) or Done (task-done); every dependency exists (dependency-missing)
    and is Done (dependency-not-done). Only on success does it write
    `.speckled/active-task`, atomically, including the task-list files that hold the
    task and its dependencies, so later checks read only those. On failure
    the marker is left unchanged. The marker is per developer (git-ignored), because two
    people on the same repo work on different tasks. `/speckled:build` runs this through
    `speckled-gate activate`; it's the only way the marker changes, and the agent's own
    writes to it are blocked as a protected path.
    """
    verdict = validate_task(project, task_id)
    if not verdict.ok:
        return verdict
    folder = speckled_folder(project)
    marker = folder / "active-task"
    tmp = folder / "active-task.tmp"
    tmp.write_text(json.dumps({
        "v": 1, "task": task_id, "by": by,
        "activated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": _files_for(project, task_id),
    }) + "\n")
    os.replace(tmp, marker)
    return verdict


def _files_for(project: Project, task_id: str) -> list[str]:
    """The task lists holding `task_id` and its dependencies, relative to `docs_dir`."""
    lists = load_task_lists(project.docs_dir)
    task_list, task = find_task(lists, task_id)
    holders = [task_list] + [find_task(lists, dep)[0] for dep in task.depends_on]
    files = [Path(os.path.relpath(t.path, project.docs_dir)).as_posix() for t in holders]
    return list(dict.fromkeys(files))  # without duplicates, in order


def _check_active_task(project: Project, action: Action) -> Verdict:
    verdict = validate_task(project, *active_marker(project))
    verdict.action = action
    return verdict


# --- messages --------------------------------------------------------------------------

def message(verdict: Verdict, mode: str, project: Project) -> str:
    """The message for a violation: reason, next step, and the bypass.

    `mode` is what happens to the call: pass `outcome()`, not the project's setting, so
    a hard rule in warn mode is shown as a block. A blocked hard rule gets two lines:
    warn mode wouldn't allow it, so the message never suggests it.
    """
    reason, next_step = _explain(verdict, project)
    if verdict.hard and mode == "block":
        return "\n".join([f"speckled: blocked: {reason}", next_step])
    if mode == "warn":
        return "\n".join([f"speckled (warn): would block: {reason}", next_step, "Allowed and logged."])
    return "\n".join([f"speckled: blocked: {reason}", next_step,
                      "To bypass, a human can set enforcement: warn in speckled.yaml."])


def _explain(v: Verdict, project: Project) -> tuple[str, str]:
    where = _display(project, v.action.path) if v.action and v.action.path else ""
    task, facts = v.task, v.facts
    if v.rule == "wrong-start-folder":
        add_dir = os.path.relpath(project.wrong_start, project.root)
        return (f"this session started in {project.wrong_start}, not in the planning repo.",
                f"Start Speckled sessions in the planning repo: cd {project.root} && claude --add-dir {add_dir}")
    if v.rule == "config-unreadable":
        error = facts.get("error") or "speckled.yaml or a task list could not be read"
        return (f"{error}.",
                "Ask the human to fix that file.")
    if v.rule == "protected-path":
        what = where or "the gate's settings"
        return f"agents can't change {what}.", "Ask the human to make this change."
    if v.rule == "hooks-disabled-session":
        return ("agents can't start a Claude Code session with hooks switched off.",
                "Ask the human to run it.")
    if v.rule in ("git-commit", "git-push", "pull-request"):
        verb = {"git-commit": "commit", "git-push": "push", "pull-request": "open pull requests"}[v.rule]
        return (f"agents don't {verb}; the human reviews and commits.",
                "Leave the changes in the working tree and suggest a commit message.")
    if v.rule == "no-active-task":
        if facts.get("unknown"):
            reason = f"the active task {facts['unknown']} isn't in any task list."
        else:
            reason = f"no active task for {where}." if where else "no active task."
        return reason, _ready_hint(project)
    if v.rule == "task-list-not-approved":
        return (f"{facts['list']} isn't approved (status: {facts['status']}).",
                f"Ask the human to run /speckled:approve {facts['list']}.")
    if v.rule == "task-not-started":
        return f"{task} is Todo.", f"Start it with /speckled:build {task}."
    if v.rule == "task-done":
        return f"{task} is Done.", _ready_hint(project)
    if v.rule == "dependency-not-done":
        return (f"{task} depends on {facts['dependency']}, which is {facts['status']}.",
                f"Finish and approve {facts['dependency']} first.")
    if v.rule == "dependency-missing":
        return (f"{task} depends on {facts['dependency']}, which isn't in any task list.",
                f"Fix the Depends on line in {facts['list']}.")
    return f"{v.rule}.", "Ask the human."


def ready_tasks(project: Project, limit: int = 3) -> list[str]:
    """Tasks that can start now: in approved lists, Todo or In progress, dependencies Done."""
    try:
        lists = load_task_lists(project.docs_dir)
    except DocError:
        return []
    ready = []
    for task_list in lists:
        if task_list.status != "approved":
            continue
        for task in task_list.tasks.values():
            if task.status in ("Todo", "In progress") and _deps_done(lists, task.depends_on):
                ready.append(task.id)
    return sorted(ready)[:limit]


def _deps_done(lists: list[TaskList], deps: list[str]) -> bool:
    for dep in deps:
        found = find_task(lists, dep)
        if found is None or found[1].status != "Done":
            return False
    return True


def _ready_hint(project: Project) -> str:
    ready = ready_tasks(project)
    if not ready:
        return "No approved task is ready to start; plan one with /speckled:tasks."
    return f"Ready to start: {', '.join(ready)}. Run /speckled:build <task-id>."


def _display(project: Project, path: str) -> str:
    """A short, relative form of `path` for messages."""
    found = repo_for(project, path)
    if found:
        name, rel = found
        return f"{rel} (in {name})"
    try:
        rel = Path(os.path.realpath(path)).relative_to(project.root)
        return str(rel)
    except ValueError:
        return path
