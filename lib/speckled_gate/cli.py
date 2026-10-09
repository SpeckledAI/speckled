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

Every subcommand also takes `--project <dir>` (skip discovery and use this planning
repo), `--plugin-root` and `--plugin-data`. A usage error exits with 64.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .log import LOG, display_path
from .project import Project, find_project, load_project, registry_path
from .rules import actions_for, active_task, decide, message, validate_task

USAGE_ERROR = 64
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
        for action in actions_for(args.tool, tool_input, project, args.cwd):
            verdict = decide(project, action)
            if verdict.ok:
                continue
            repo, path = display_path(project, action.path) if action.path else ("", "")
            result["violations"].append({"rule": verdict.rule, "repo": repo, "path": path,
                                         "message": message(verdict, project.enforcement, project)})
        if result["violations"]:
            result["decision"] = project.enforcement
    print(json.dumps(result, indent=2))
    return 0


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

    task = active_task(project)
    if task is None:
        print("Active task:   none (set one with /speckled:build <task-id>)")
    else:
        verdict = validate_task(project, task)
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
