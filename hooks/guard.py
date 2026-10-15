#!/usr/bin/env python3
"""Speckled safety guard (PreToolUse hook).

Blocks two classes of tool call before they run:
  1. Recursive forced deletes (rm -rf and equivalents, also through bash -c, xargs and
     find -delete).
  2. Reading or writing secret env files (.env, .env.local, ...), through shell
     commands, file tools, Grep, Glob and NotebookEdit; example files such as
     .env.example / .env.sample / .env.template / .env.dist stay allowed.

Shell commands are read with the plugin's shared tokenizer (lib/speckled_gate/shell.py),
so a mention of .env inside an echo isn't mistaken for access. The guard runs whether
or not enforcement is on; it never reads speckled.yaml.

Exit code 2 blocks the call and shows the message to the model. Any unexpected
input fails open (exit 0) so a malformed payload never wedges a session. If the
tokenizer can't be imported or fails on a command, a coarse check still blocks
recursive forced deletes, erring towards blocking; other shell commands are allowed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
try:
    from speckled_gate import shell
except Exception:
    shell = None

SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")

RM_MESSAGE = "Recursive forced delete (rm -rf) is blocked. Delete specific paths, or ask the human to run it."
ENV_MESSAGE = "Access to secret .env files is blocked. Use .env.example for templates."


def is_secret_env(name: str) -> bool:
    return not name.endswith(SAFE_ENV_SUFFIXES)


def is_secret_env_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return bool(re.fullmatch(r"\.env(\..+)?", name)) and is_secret_env(name)


def glob_targets_secret_env(pattern: str) -> bool:
    """True if a glob's file-name part names .env files that aren't examples.

    Brace alternatives are checked one by one: "{.env,*.ts}" targets .env.
    """
    name = pattern.rsplit("/", 1)[-1]
    return any(part.startswith(".env") and is_secret_env(part) for part in re.split(r"[{},\s]", name))


def looks_like_rm_rf(command: str) -> bool:
    """A coarse check for when the tokenizer can't be used. Errs towards blocking:
    `git commit -m "rm -rf docs"` is blocked too."""
    for segment in re.split(r"[;&|()`\n]", command):
        words = [w.strip("'\"") for w in segment.split()]
        for i, word in enumerate(words):
            program, args = word.rsplit("/", 1)[-1], words[i + 1:]
            if program == "find" and "-delete" in args:
                return True
            if program != "rm":
                continue
            short = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
            if ("r" in short.lower() or "--recursive" in args) and ("f" in short or "--force" in args):
                return True
    return False


def check(tool: str, tool_input: dict) -> str | None:
    if tool in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        try:
            kinds = {a.kind for a in shell.actions(command)}
        except Exception:  # no tokenizer, or it failed: still never allow rm -rf
            return RM_MESSAGE if looks_like_rm_rf(command) else None
        if "rm-recursive-force" in kinds:
            return RM_MESSAGE
        if "reads-secret-env" in kinds:
            return ENV_MESSAGE
    elif tool in ("Read", "Edit", "MultiEdit", "Write"):
        if is_secret_env_path(tool_input.get("file_path", "")):
            return ENV_MESSAGE
    elif tool == "NotebookEdit":
        if is_secret_env_path(tool_input.get("notebook_path", "")):
            return ENV_MESSAGE
    elif tool == "Grep":
        if is_secret_env_path(tool_input.get("path") or "") or glob_targets_secret_env(tool_input.get("glob") or ""):
            return ENV_MESSAGE
    elif tool == "Glob":
        if glob_targets_secret_env(tool_input.get("pattern") or ""):
            return ENV_MESSAGE
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        reason = check(payload.get("tool_name", ""), payload.get("tool_input") or {})
    except Exception:
        sys.exit(0)
    if reason:
        print(f"speckled guard: {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
