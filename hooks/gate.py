#!/usr/bin/env python3
"""Speckled gate: the Claude Code PreToolUse hook that enforces approvals.

Why this file exists:
    The gate's rules live in `lib/speckled_gate` and know nothing about Claude Code.
    This adapter connects them: it reads the tool call Claude Code is about to make,
    asks the rules about it, and answers in the way Claude Code understands.

What it does, per tool call:
    1. Reads the hook payload (JSON on stdin). Unreadable payload: allow (exit 0).
    2. Finds the Speckled project from the session's folder. None, or enforcement off:
       allow, with no output, exactly as if the gate weren't installed (NFR6).
    3. Turns the tool call into actions and judges each one.
    4. No violations: allow, with no output.
       block mode: print the first violation's message on stderr and exit 2. Claude Code
         stops the call and shows the message to the model.
       warn mode: log each violation to `.speckled/log.jsonl`, then allow, printing the
         message as `additionalContext` (for the model) and `systemMessage` (for the
         user). Never `permissionDecision`: "allow" would skip the user's permission
         prompt, and the gate only ever restricts.

Failing closed: once enforcement is known to be on, an unexpected error blocks the
call (exit 2) with a message saying how to switch the gate off. Claude Code treats a
crashed hook as "continue", so failing open would turn every bug into a silent bypass.

Usage (hooks/hooks.json): python3 gate.py --plugin-data "${CLAUDE_PLUGIN_DATA}"
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

INTERNAL_ERROR = ("speckled: internal error — set enforcement: off in speckled.yaml to continue, "
                  "and please report this.")


def main(argv: list[str]) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except Exception:
        return 0  # a Claude Code problem, not a project state: allow

    enforcing = False
    try:
        from speckled_gate import log
        from speckled_gate.project import find_project, refresh_registry
        from speckled_gate.rules import actions_for, decide, message

        cwd = payload.get("cwd") or os.getcwd()
        project = find_project(cwd, PLUGIN_ROOT, _plugin_data(argv))
        if project is None or project.enforcement == "off":
            return 0
        enforcing = True
        refresh_registry(project)
        if os.environ.get("SPECKLED_TEST_INTERNAL_ERROR"):
            raise RuntimeError("injected by a test")

        tool = payload.get("tool_name", "")
        actions = actions_for(tool, payload.get("tool_input") or {}, project, cwd)
        violations = [v for v in (decide(project, a) for a in actions) if not v.ok]
        if not violations:
            return 0

        if project.enforcement == "block":
            print(message(violations[0], "block", project), file=sys.stderr)
            return 2

        # warn: allowed, logged, and the model and the user are told.
        text = message(violations[0], "warn", project)
        try:
            by, agent = log.git_user(project.root), payload.get("agent_type") or "main"
            for v in violations:
                paths = [v.action.path] if v.action and v.action.path else []
                log.append(project, log.entry(project, mode="warn", rule=v.rule, tool=tool,
                                              paths=paths, task=v.task, by=by, agent=agent))
        except OSError as e:
            text += f" (not logged: {e.strerror or e})"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": text},
                          "systemMessage": text}))
        return 0
    except Exception:
        if enforcing:
            print(INTERNAL_ERROR, file=sys.stderr)
            return 2
        return 0


def _plugin_data(argv: list[str]) -> str | None:
    """--plugin-data <dir> from the hook command, else $CLAUDE_PLUGIN_DATA."""
    if "--plugin-data" in argv:
        i = argv.index("--plugin-data")
        if i + 1 < len(argv) and argv[i + 1] and "${" not in argv[i + 1]:
            return argv[i + 1]
    return os.environ.get("CLAUDE_PLUGIN_DATA") or None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
