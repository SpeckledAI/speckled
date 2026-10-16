"""The `speckled-gate` command line.

Why this module exists:
    The gate's decision has to be usable outside Claude Code: by adapters for other
    coding agents, by tests, and by a human wondering why something was blocked. This
    is that entry point. It makes the same decision as the Claude Code hook, because
    both call the same functions.

What it does:
    - `speckled-gate check --tool <name> --input <json> [--cwd <dir>]` judges one tool
      call and prints the result as JSON. It's the stable contract other integrations
      call, so it never writes anything (not even the warn log) and always exits 0.
    - `speckled-gate status` explains what the gate sees right now: the project, the
      mode, the active task and whether it's valid, the log and the registry entry.
    - `speckled-gate activate <task-id>` makes a task the active task, after checking in
      code that it may be worked on now. `/speckled:build` runs it; it's the only way
      the active-task marker changes. Exit 0 if activated, 1 (with the reason) if not.
    - `speckled-gate install-git-hook` copies the commit-time notice
      (`hooks/pre-commit-notice.py`) into the planning repo's `.git/hooks/pre-commit`.
      It never replaces a hook it didn't install, and never installs one when
      `core.hooksPath` is set: in both cases it copies the script beside them as
      `.git/hooks/speckled-notice` and prints the line for the human to add.

Every subcommand also takes `--project <dir>` (skip discovery and use this planning
repo), `--plugin-root` and `--plugin-data`. A usage error exits with 64.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .docs import find_task, load_task_lists
from .log import LOG, display_path, git_user
from .project import Project, find_project, load_project, registry_path
from .rules import actions_for, activate, active_marker, decide, message, outcome, validate_task

USAGE_ERROR = 64
NOTICE_MARKER = "# speckled pre-commit notice v1"
# lib/speckled_gate/cli.py -> the plugin's root folder
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class _Parser(argparse.ArgumentParser):
    """argparse, but usage errors exit with 64 (EX_USAGE) instead of 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(USAGE_ERROR, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command == "status":
        return _status(args)
    if args.command == "activate":
        return _activate(args)
    if args.command == "install-git-hook":
        return _install_git_hook(args)
    _parser().error("choose a command")  # unreachable: argparse requires one
    return USAGE_ERROR


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="the planning repo to use (skips discovery)")
    common.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT") or str(_PLUGIN_ROOT))
    common.add_argument("--plugin-data", default=os.environ.get("CLAUDE_PLUGIN_DATA"))
    common.add_argument("--cwd", default=os.getcwd(), help="the session's folder (default: here)")

    parser = _Parser(prog="speckled-gate", description="Speckled's approval gate.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    check = commands.add_parser("check", parents=[common], help="judge one tool call; print JSON")
    check.add_argument("--tool", required=True, help="tool name, e.g. Edit or Bash")
    check.add_argument("--input", required=True, help="the tool's input, as JSON")
    commands.add_parser("status", parents=[common], help="show what the gate sees")
    activate_cmd = commands.add_parser("activate", parents=[common], help="make a task the active task")
    activate_cmd.add_argument("task_id", help="e.g. T-F07-03")
    commands.add_parser("install-git-hook", parents=[common],
                        help="install the commit-time notice in the planning repo")
    return parser


def _project(args) -> Project | None:
    if args.project:
        return load_project(args.project, args.plugin_root, args.plugin_data)
    return find_project(args.cwd, args.plugin_root, args.plugin_data)


# --- check ---------------------------------------------------------------------------

def _check(args) -> int:
    try:
        tool_input = json.loads(args.input)
        if not isinstance(tool_input, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        _parser().error(f"--input must be a JSON object ({e})")
    project = _project(args)
    result = {"decision": "ok", "violations": []}
    if project is not None and project.enforcement != "off":
        verdicts = [decide(project, a) for a in actions_for(args.tool, tool_input, project, args.cwd)]
        # The same outcome the hook acts on: hard rules block in warn mode too.
        result["decision"] = outcome(project.enforcement, verdicts)
        for verdict in verdicts:
            if verdict.ok:
                continue
            action = verdict.action
            repo, path = display_path(project, action.path) if action and action.path else ("", "")
            result["violations"].append({"rule": verdict.rule, "kind": "hard" if verdict.hard else "task",
                                         "repo": repo, "path": path,
                                         "message": message(verdict, result["decision"], project)})
    print(json.dumps(result, indent=2))
    return 0


# --- activate ------------------------------------------------------------------------

def _activate(args) -> int:
    """`activate <task-id>`: exit 0 and confirm, or exit 1 with the reason."""
    project = _project(args)
    if project is None:
        print(f"No Speckled project found from {args.cwd}. Run this in the planning repo.", file=sys.stderr)
        return 1
    verdict = activate(project, args.task_id, by=git_user(project.root))
    if not verdict.ok:
        reason = message(verdict, "block", project).split("\n")[:2]
        print(f"Not activated ({verdict.rule}): {reason[0].split(': ', 2)[-1]}", file=sys.stderr)
        print(reason[1], file=sys.stderr)
        return 1
    task_list, _ = find_task(load_task_lists(project.docs_dir), args.task_id)
    print(f"Active task: {args.task_id} ({task_list.id} v{task_list.version}, {task_list.status})")
    return 0


# --- install-git-hook ----------------------------------------------------------------

def _install_git_hook(args) -> int:
    """Install the notice as `.git/hooks/pre-commit`, or say how to add it by hand."""
    project = _project(args)
    if project is None:
        print(f"No Speckled project found from {args.cwd}. Run this in the planning repo.", file=sys.stderr)
        return 1
    source = Path(args.plugin_root) / "hooks" / "pre-commit-notice.py"
    try:
        hooks_dir = _git_dir(project.root) / "hooks"
        hooks_path = _git(project.root, "config", "core.hooksPath")
        hook = hooks_dir / "pre-commit"
        foreign = hook.exists() and NOTICE_MARKER not in hook.read_text(encoding="utf-8", errors="replace")
        if hooks_path or foreign:
            _copy(source, hooks_dir / "speckled-notice")
            where = f"core.hooksPath is set ({hooks_path})" if hooks_path else "A pre-commit hook already exists"
            print(f"{where}, so Speckled didn't install its own. To see the commit-time notice, "
                  "add this line to your pre-commit hook:")
            print("  python3 .git/hooks/speckled-notice")
            return 0
        _copy(source, hook)
    except OSError as e:
        print(f"Couldn't install the git hook: {e}", file=sys.stderr)
        return 1
    print("Installed .git/hooks/pre-commit")
    return 0


def _git(cwd: Path, *args: str) -> str:
    """git's output, stripped; "" if the command fails (e.g. an unset config key)."""
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        raise OSError(f"git {' '.join(args)}: {e}") from e
    return out.stdout.strip() if out.returncode == 0 else ""


def _git_dir(root: Path) -> Path:
    """The repo's shared git folder (`.git`, also from a worktree)."""
    common = _git(root, "rev-parse", "--git-common-dir")
    if not common:
        raise OSError(f"{root} isn't a git repository")
    return (root / common).resolve()


def _copy(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.chmod(0o755)
    os.replace(tmp, dest)


# --- status --------------------------------------------------------------------------

def _status(args) -> int:
    project = _project(args)
    if project is None:
        print(f"No Speckled project found from {args.cwd}.")
        print("Speckled sessions start in the planning repo (the folder with speckled.yaml).")
        return 0
    print(f"Planning repo: {project.root}")
    mode = project.enforcement
    print(f"Enforcement:   {mode}" + (f" (config problem: {project.config_error})" if project.config_error else ""))
    if project.wrong_start is not None:
        print(f"Started in:    {project.wrong_start}, a code repo: start sessions in the planning repo")
    if mode == "off":
        print("The gate is off: nothing is checked.")
        return 0
    print("Code repos:    " + (", ".join(project.repo_names) or "(none listed)"))

    task, files = active_marker(project)
    if task is None:
        print("Active task:   none (set one with /speckled:build <task-id>)")
    else:
        verdict = validate_task(project, task, files)
        if verdict.ok:
            print(f"Active task:   {task}, valid")
        else:
            reason = message(verdict, mode, project).split("\n")[0].split(": ", 2)[-1]
            print(f"Active task:   {task}, not valid now ({verdict.rule}): {reason}")

    log = project.root / LOG
    if log.exists():
        count = sum(1 for _ in log.open(encoding="utf-8"))
        print(f"Log:           {log} ({count} entries)")
    else:
        print(f"Log:           {log} (not created yet)")
    print(f"Registry:      {_registry_line(project, args.cwd)}")
    return 0


def _registry_line(project: Project, cwd: str) -> str:
    if not project.plugin_data:
        return "not available (no plugin data folder)"
    path = registry_path(project.plugin_data)
    try:
        repos = json.loads(path.read_text(encoding="utf-8")).get("repos", {})
    except (OSError, ValueError):
        return f"{path} (empty)"
    mine = [repo for repo, home in repos.items() if Path(home) == project.root]
    return f"{path} ({len(mine)} code repo(s) recorded for this project)"


if __name__ == "__main__":
    sys.exit(main())
