"""Speckled gate: decides whether an agent's action is allowed under the project's approvals.

Standard library only, plus the bundled PyYAML, Python 3.9+. The public API:

    find_project(cwd, plugin_root, plugin_data)  -> Project | None
    actions_for(tool_name, tool_input, project, cwd) -> list[Action]
    decide(project, action)                        -> Verdict
    message(verdict, mode, project)                -> str

The API is loaded on first use, so importing one module (the guard's
`from speckled_gate import shell`) doesn't load the rest: a fault in the rules or the
YAML loader can't stop the guard blocking `rm -rf`, and the guard starts faster.
"""

__version__ = "0.2.0"

_API = {"Project": "project", "find_project": "project", "Action": "rules", "Verdict": "rules",
        "actions_for": "rules", "decide": "rules", "message": "rules"}

__all__ = list(_API)


def __getattr__(name):
    if name in _API:
        from importlib import import_module
        return getattr(import_module(f".{_API[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
