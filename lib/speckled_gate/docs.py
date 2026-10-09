"""Read Speckled documents: front matter and task lists.

Why this module exists:
    The hook gate needs to know, for any eng task ID, whether its task list is approved,
    what the task's status is, and which tasks it depends on (the code gate). That
    information lives in Markdown documents in the planning repo, so this module turns
    it into data the gate can check.

What it does:
    - `front_matter()` reads the YAML block at the top of any Speckled document
      (id, type, status, version, approvals), through `yamlio`.
    - `parse_task_list()` reads one task list: its front matter, plus every task in the
      strict task format from the protocol:

          ### T-F07-03: Title
          - **Depends on:** T-F07-01, T-F07-02      (task IDs, or "none")
          - **Status:** In progress                 (Todo | In progress | In review | Done)

    - `load_task_lists()` reads every task list in `<docs_dir>/tasks/` and
      `<docs_dir>/tasks/completed/`, skipping other documents.
    - `find_task()` looks a task ID up across all lists, because a task can depend on
      a task in another feature's list.

Design rules:
    - The parsing functions are pure (text in, data out), so other features can reuse
      them; `load_task_lists` is the thin wrapper that reads the files.
    - Anything that doesn't follow the format raises DocError naming the file and line,
      because the gate must not guess about approvals. A typo in a status blocks edits
      until it's fixed; it never silently changes what the gate allows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .yamlio import YamlError, loads

# A task ID: feature number and task number, e.g. T-F07-03 (more digits allowed).
TASK_ID = re.compile(r"T-F\d{2,}-\d{2,}")
# Lines of the strict task format.
_TASK_HEADING = re.compile(r"^### (T-F\d{2,}-\d{2,}):")    # "### T-F07-03: Title"
_BLOCK_END = re.compile(r"^#{1,3} ")                       # any heading of level 1-3
_STATUS_LINE = re.compile(r"^- \*\*Status:\*\*\s*(.+?)\s*$")
_DEPENDS_LINE = re.compile(r"^- \*\*Depends on:\*\*(.*)$")
# The four allowed statuses, keyed by lower case so "done" or "IN REVIEW" are accepted
# and stored in their canonical spelling.
_STATUSES = {s.lower(): s for s in ("Todo", "In progress", "In review", "Done")}


class DocError(ValueError):
    """A document doesn't follow the format.

    `path` is the file, `line` is 1-based, and `reason` says what's wrong, so the gate's
    message can tell the human exactly where to look (shown as `path:line: reason`).
    """

    def __init__(self, path: str, line: int, reason: str):
        super().__init__(f"{path}:{line}: {reason}")
        self.path = path
        self.line = line
        self.reason = reason


@dataclass
class Task:
    """One task, as the gate needs it."""

    id: str                 # "T-F07-03"
    status: str             # "Todo", "In progress", "In review" or "Done"
    depends_on: list[str]   # task IDs this task waits for; [] if none
    line: int               # line of the task's heading, for error messages


@dataclass
class TaskList:
    """One task list document (TASKS-Fnn) and its tasks."""

    id: str                 # front-matter id, e.g. "TASKS-F07"
    status: str             # the list's own status; only "approved" opens the code gate
    version: int
    path: str               # the file it was read from, for error messages
    tasks: dict[str, Task] = field(default_factory=dict)   # by task ID, in file order


def front_matter(text: str) -> dict:
    """The YAML between a leading `---` line and the next `---` line ({} if none).

    Raises YamlError with the line number in the whole file, not in the YAML block.
    """
    lines = text.splitlines()
    # Front matter only counts if it opens on the very first line.
    if not lines or lines[0].strip() != "---":
        return {}
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            try:
                return loads("\n".join(lines[1:end]))
            except YamlError as e:
                # The YAML block starts on line 2 of the file.
                raise YamlError(e.line + 1, e.reason) from None
    raise YamlError(1, "front matter isn't closed with a '---' line")


def parse_task_list(text: str, path: str) -> TaskList:
    """Parse a task list's front matter and its tasks.

    Reads the file line by line. A `### T-Fnn-kk:` heading starts a task; within it,
    the first `Status` line and the first `Depends on` line are recorded; the task ends
    at the next heading of level 1-3. `path` is only used in error messages.
    """
    # 1. Front matter: the list's id, status and version are required.
    try:
        meta = front_matter(text)
    except YamlError as e:
        raise DocError(path, e.line, e.reason) from None
    for key in ("id", "status", "version"):
        if key not in meta:
            raise DocError(path, 1, f"front matter is missing '{key}'")
    task_list = TaskList(id=str(meta["id"]), status=str(meta["status"]),
                         version=meta["version"], path=path)

    # 2. Tasks.
    current = None  # the task being read: {"id", "line", "status", "depends_on"}
    in_fence = False  # inside a ``` code block

    def finish():
        """Check the task just read and add it to the list."""
        if current is None:
            return
        if current["status"] is None:
            raise DocError(path, current["line"], f"{current['id']} has no '- **Status:**' line")
        if current["id"] in task_list.tasks:
            raise DocError(path, current["line"], f"{current['id']} appears more than once")
        task_list.tasks[current["id"]] = Task(current["id"], current["status"],
                                              current["depends_on"] or [], current["line"])

    for number, line in enumerate(text.splitlines(), start=1):
        # Headings inside ``` code blocks are examples, not tasks.
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # A task runs until the next heading of level 1-3; deeper headings belong to it.
        if _BLOCK_END.match(line):
            finish()
            heading = _TASK_HEADING.match(line)
            current = ({"id": heading.group(1), "line": number, "status": None, "depends_on": None}
                       if heading else None)
            continue
        if current is None:
            continue  # outside any task (overview, coverage, ...)
        # The first Status line is the task's status; later ones are ignored.
        status = _STATUS_LINE.match(line)
        if status and current["status"] is None:
            value = status.group(1)
            if value.lower() not in _STATUSES:
                raise DocError(path, number, f"unknown status '{value}' for {current['id']} "
                                             "(use Todo, In progress, In review or Done)")
            current["status"] = _STATUSES[value.lower()]
            continue
        depends = _DEPENDS_LINE.match(line)
        if depends and current["depends_on"] is None:
            # Only the first "Depends on" line counts; "none" (or any text) gives [].
            current["depends_on"] = TASK_ID.findall(depends.group(1))
    finish()  # the last task in the file
    return task_list


def load_task_lists(docs_dir: str | Path) -> list[TaskList]:
    """Every task list in `<docs_dir>/tasks/` and `<docs_dir>/tasks/completed/`.

    Markdown files whose front matter isn't `type: tasks` are skipped. A file whose
    front matter can't be read raises DocError, since it might be a task list.
    """
    root = Path(docs_dir) / "tasks"
    # Finished features move to completed/; their tasks can still be dependencies.
    files = sorted(root.glob("*.md")) + sorted((root / "completed").glob("*.md"))
    lists = []
    for file in files:
        text = file.read_text(encoding="utf-8")
        try:
            kind = front_matter(text).get("type")
        except YamlError as e:
            raise DocError(str(file), e.line, e.reason) from None
        if kind == "tasks":
            lists.append(parse_task_list(text, str(file)))
    return lists


def find_task(lists: list[TaskList], task_id: str) -> tuple[TaskList, Task] | None:
    """The task list and task for `task_id`, or None if no list has it."""
    for task_list in lists:
        task = task_list.tasks.get(task_id)
        if task:
            return task_list, task
    return None
