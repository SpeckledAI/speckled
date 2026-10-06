#!/usr/bin/env python3
"""Speckled safety guard (PreToolUse hook).

Blocks two classes of tool call before they run:
  1. Recursive forced deletes (rm -rf and equivalents).
  2. Reading or writing secret env files (.env, .env.local, ...); example files
     such as .env.example / .env.sample / .env.template stay allowed.

Exit code 2 blocks the call and shows the message to the model. Any unexpected
input fails open (exit 0) so a malformed payload never wedges a session.
"""
from __future__ import annotations

import json
import re
import sys

SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")

# A path segment that is a secret env file: .env or .env.<anything> that isn't a safe example suffix.
ENV_FILE = re.compile(r"(?:^|[\s/'\"=<>])(\.env(?:\.[\w.-]+)?)(?=$|[\s'\";|&)])")


def is_secret_env(name: str) -> bool:
    return not name.endswith(SAFE_ENV_SUFFIXES)


def mentions_secret_env(text: str) -> bool:
    return any(is_secret_env(m.group(1)) for m in ENV_FILE.finditer(text))


def is_recursive_force_rm(command: str) -> bool:
    for segment in re.split(r"&&|\|\||;|\|", command):
        tokens = segment.split()
        # Skip env assignments and sudo-style prefixes to find the program.
        while tokens and (tokens[0] in ("sudo", "command", "exec") or "=" in tokens[0]):
            tokens = tokens[1:]
        if not tokens or tokens[0].rsplit("/", 1)[-1] != "rm":
            continue
        flags = "".join(t.lstrip("-") for t in tokens[1:] if t.startswith("-") and not t.startswith("--"))
        long_flags = {t for t in tokens[1:] if t.startswith("--")}
        recursive = "r" in flags.lower() or "--recursive" in long_flags
        force = "f" in flags or "--force" in long_flags
        if recursive and force:
            return True
    return False


def check(tool: str, tool_input: dict) -> str | None:
    if tool == "Bash":
        command = tool_input.get("command", "")
        if is_recursive_force_rm(command):
            return "Recursive forced delete (rm -rf) is blocked. Delete specific paths, or ask the human to run it."
        if mentions_secret_env(command):
            return "Access to secret .env files is blocked. Use .env.example for templates."
    elif tool in ("Read", "Edit", "MultiEdit", "Write"):
        name = tool_input.get("file_path", "").rsplit("/", 1)[-1]
        if re.fullmatch(r"\.env(\..+)?", name) and is_secret_env(name):
            return "Access to secret .env files is blocked. Use .env.example for templates."
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
