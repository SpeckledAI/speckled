#!/usr/bin/env python3
"""Speckled PreToolUse hook: runs the safety guard, then the approval gate.

Why this file exists:
    Claude Code starts a new process for every hook on every tool call. One entry that
    runs both checks starts Python once instead of twice, and lets Read, Grep and Glob
    calls skip the gate entirely.

What it does, per tool call:
    1. Reads the hook payload (JSON on stdin). Unreadable payload: allow (exit 0).
    2. Runs guard.check(). If it blocks, asks the gate to log the block (only in a
       Speckled project with enforcement on, as `recursive-delete` or `secret-env-file`),
       then prints its message on stderr and exits 2, whatever the enforcement mode and
       whether or not logging worked. Any error in the guard means no verdict, as in
       guard.py.
    3. Read, Grep and Glob can't change anything: allow without loading the gate.
    4. Otherwise imports the gate and returns gate.run(). If the gate can't be imported,
       enforcement is unknown: allow, as when lib/ is missing. Once the gate runs, its
       own fail-closed handling applies.

Keep this file small: a fault here stops both checks. The gate is imported inside a
`try` so broken gate code can't stop the guard. guard.py and gate.py still run on their
own.

Usage (hooks/hooks.json): python3 pretooluse.py --plugin-data "${CLAUDE_PLUGIN_DATA}"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

READ_ONLY_TOOLS = ("Read", "Grep", "Glob")


def main(argv: list[str]) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except Exception:
        return 0  # a Claude Code problem, not a project state: allow

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    tool = payload.get("tool_name", "")
    try:
        import guard
        reason = guard.check(tool, payload.get("tool_input") or {})
    except Exception:
        reason = None
    if reason:
        _log_guard_block(payload, reason, argv)
        print(f"speckled guard: {reason}", file=sys.stderr)
        return 2

    if tool in READ_ONLY_TOOLS:
        return 0
    try:
        import gate
    except Exception:
        return 0
    return gate.run(payload, argv)


def _log_guard_block(payload: dict, reason: str, argv: list[str]) -> None:
    """Ask the gate to log the guard's block. The block stands whatever happens."""
    try:
        import guard
        rule = {guard.RM_MESSAGE: "recursive-delete", guard.ENV_MESSAGE: "secret-env-file"}.get(reason)
        if rule:
            import gate
            gate.log_guard_block(payload, rule, argv)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
