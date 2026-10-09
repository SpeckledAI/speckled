"""Speckled gate: decides whether an agent's action is allowed under the project's approvals.

Standard library only, plus the bundled PyYAML, Python 3.9+. The public API:

    find_project(cwd, plugin_root, plugin_data)  -> Project | None
    actions_for(tool_name, tool_input, project, cwd) -> list[Action]
    decide(project, action)                        -> Verdict
    message(verdict, mode, project)                -> str
"""

__version__ = "0.2.0"

from .project import Project, find_project  # noqa: E402
from .rules import Action, Verdict, actions_for, decide, message  # noqa: E402

__all__ = ["Project", "find_project", "Action", "Verdict", "actions_for", "decide", "message"]
