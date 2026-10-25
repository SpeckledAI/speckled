"""Structure checks: front matter, IDs, file names, features, tasks and dependencies.

Why this module exists:
    Before the chain or the history can be checked, each document has to say what it
    is, in the shape protocol §3, §4 and §8 give, and its tasks have to fit together.
    These checks read only the corpus, so they also run with `--docs` [T-F08-05].

What it does:
    `check_structure(corpus)` returns the findings for these rules, skipping broken
    files (their one finding is already in `corpus.broken`):
    - `front-matter`: a required field for the document's `type` is missing, or a
      value is invalid (type, status, versions, dates, approvals entries, feature).
      A missing `parent` is left to the chain check (`parent-missing`), so it isn't
      reported twice.
    - `bad-id`: the `id` doesn't have its type's shape, `feature` doesn't match it,
      a task heading isn't a well-formed task ID, or a task belongs to another feature.
      Research IDs are free-form.
    - `duplicate-id`: on every file after the first with the same `id`, by path.
    - `file-name`: the file isn't at the path its `id` and `type` give.
    - `unknown-feature`: an FRD, TDD or task list names a feature the PDRD doesn't list.
    - `task-format`: an `Approved by` line that doesn't have the protocol's shape.
      (A task list the gate can't read at all is already a broken file.)
    - `duplicate-task`: a task ID in more than one list, on every list after the first.
    - `dependency-missing`: a `Depends on` ID that isn't a task anywhere. IDs from a
      feature whose task list is broken aren't reported: that list has its own finding.
    - `dependency-cycle`: once per cycle, on its lowest task ID.

Messages quote only structured values (IDs, statuses, field names, paths), never a
title, body text or the text of an `Approved by` line, which may hold a note.
"""
from __future__ import annotations

import re
from datetime import date

from .corpus import COMPLETED, Corpus, Doc
from .report import Finding
from .rules import RULES

TYPES = ("brief", "research", "pdrd", "arch", "frd", "tdd", "tasks")
STATUSES = ("draft", "in-review", "approved", "done", "superseded")
COMMON_FIELDS = ("id", "title", "type", "status", "version", "updated", "approvals")
# Fields each type adds. `parent` is required too, but the chain check reports it.
TYPE_FIELDS = {
    "brief": (), "research": (), "arch": (),
    "pdrd": ("parent_version",),
    "frd": ("feature", "parent_version"),
    "tdd": ("feature", "parent_version"),
    "tasks": ("feature", "parent_version"),
}
APPROVAL_FIELDS = ("by", "role", "date", "version")
# Documents with a fixed ID and file name, and the feature documents' prefix and folder.
FIXED = {"brief": ("BRIEF", "brief.md"), "pdrd": ("PDRD", "pdrd.md"), "arch": ("ARCH", "architecture.md")}
FEATURE_DOCS = {"frd": ("FRD", "frds"), "tdd": ("TDD", "tdds"), "tasks": ("TASKS", "tasks")}

FEATURE = re.compile(r"F\d{2,}")
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_FEATURE_FILE = re.compile(rf"(F\d{{2,}})-{SLUG}\.md")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TASK_ID = re.compile(r"T-(F\d{2,})-\d{2,}")
_TASK_HEADING_START = re.compile(r"^### T-")
_TASK_HEADING = re.compile(r"^### T-F\d{2,}-\d{2,}:")
_BLOCK_END = re.compile(r"^#{1,3} ")
_DEPENDS_LINE = re.compile(r"^- \*\*Depends on:\*\*")


def check_structure(corpus: Corpus) -> list[Finding]:
    findings: list[Finding] = []
    for doc in corpus.docs.values():
        findings += _front_matter(doc)
        findings += _ids(doc)
        findings += _file_name(doc)
        findings += _feature_known(doc, corpus)
        findings += _approved_by_lines(doc)
    findings += _duplicate_ids(corpus)
    findings += _tasks(corpus)
    return findings


def _finding(rule: str, subject: str, file: str, line: int | None, message: str) -> Finding:
    return Finding(rule, RULES[rule].severity, subject, file, line, message, RULES[rule].fix)


def _quote(value) -> str:
    """A short structured value for a message: `'Doing'`, or the kind of value it is."""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return f"'{value}'"
    return {list: "a list", dict: "a mapping", bool: "true/false"}.get(type(value), "an empty value")


def _whole_number(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_date(value) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _feature_of(doc: Doc) -> str | None:
    """The document's `feature`, if it's well-formed."""
    value = doc.meta.get("feature")
    return value if isinstance(value, str) and FEATURE.fullmatch(value) else None


def _id_feature(doc: Doc) -> str | None:
    """The feature in a feature document's `id` (`FRD-F07` -> `F07`), if it has the right shape."""
    if doc.type not in FEATURE_DOCS or doc.id is None:
        return None
    prefix = FEATURE_DOCS[doc.type][0]
    match = re.fullmatch(rf"{prefix}-(F\d{{2,}})", doc.id)
    return match.group(1) if match else None


# --- front-matter ----------------------------------------------------------------------

def _front_matter(doc: Doc) -> list[Finding]:
    out = []

    def bad(key: str, message: str, line: int | None = None) -> None:
        out.append(_finding("front-matter", doc.subject, doc.path,
                            doc.line(key) if line is None else line, f"{doc.subject}: {message}"))

    meta = doc.meta
    kind = meta.get("type")
    known = isinstance(kind, str) and kind in TYPES
    required = COMMON_FIELDS + (TYPE_FIELDS[kind] if known else ())
    for key in required:
        if key not in meta or meta[key] is None:
            bad(key, f"front matter is missing '{key}'.", line=1)

    if "type" in meta and meta["type"] is not None and not known:
        bad("type", f"unknown type {_quote(kind)} (use {', '.join(TYPES)}).")
    if "id" in meta and meta["id"] is not None and doc.id is None:
        bad("id", "'id' must be text.")
    if "title" in meta and meta["title"] is not None and not (isinstance(meta["title"], str) and meta["title"].strip()):
        bad("title", "'title' must be text.")
    status = meta.get("status")
    if status is not None and status not in STATUSES:
        bad("status", f"unknown status {_quote(status)} (use {', '.join(STATUSES)}).")
    for key in ("version", "parent_version"):
        if meta.get(key) is not None and not _whole_number(meta[key]):
            bad(key, f"'{key}' must be a whole number of 1 or more, not {_quote(meta[key])}.")
    if meta.get("updated") is not None and not _is_date(meta["updated"]):
        bad("updated", f"'updated' must be a date written YYYY-MM-DD, not {_quote(meta['updated'])}.")
    if known and kind in FEATURE_DOCS and meta.get("feature") is not None and _feature_of(doc) is None:
        bad("feature", f"'feature' must be F and two or more digits, such as F07, not {_quote(meta['feature'])}.")

    approvals = meta.get("approvals")
    if approvals is not None and not isinstance(approvals, list):
        bad("approvals", "'approvals' must be a list.")
    elif approvals:
        for number, (entry, line) in enumerate(zip(approvals, doc.approval_lines), start=1):
            for problem in _approval_problems(entry):
                bad("approvals", f"approval {number} {problem}.", line=line)
    return out


def _approval_problems(entry) -> list[str]:
    if not isinstance(entry, dict):
        return ["must be a mapping with by, role, date and version"]
    problems = [f"is missing '{key}'" for key in APPROVAL_FIELDS if entry.get(key) is None]
    for key in ("by", "role"):
        value = entry.get(key)
        if value is not None and not (isinstance(value, str) and value.strip()):
            problems.append(f"has a '{key}' that isn't text")
    if entry.get("date") is not None and not _is_date(entry["date"]):
        problems.append(f"has a 'date' that isn't written YYYY-MM-DD: {_quote(entry['date'])}")
    if entry.get("version") is not None and not _whole_number(entry["version"]):
        problems.append(f"has a 'version' that isn't a whole number of 1 or more: {_quote(entry['version'])}")
    return problems


# --- IDs, file names and features ------------------------------------------------------

def _ids(doc: Doc) -> list[Finding]:
    out = []
    kind = doc.type
    if doc.id is not None and kind in FIXED and doc.id != FIXED[kind][0]:
        out.append(_finding("bad-id", doc.subject, doc.path, doc.line("id"),
                            f"{doc.id}: a document of type {kind} has the id {FIXED[kind][0]}."))
    if doc.id is not None and kind in FEATURE_DOCS:
        prefix = FEATURE_DOCS[kind][0]
        id_feature = _id_feature(doc)
        if id_feature is None:
            out.append(_finding("bad-id", doc.subject, doc.path, doc.line("id"),
                                f"{doc.id}: a document of type {kind} has an id like {prefix}-F07."))
        feature = _feature_of(doc)
        if id_feature and feature and id_feature != feature:
            out.append(_finding("bad-id", doc.subject, doc.path, doc.line("feature"),
                                f"{doc.id}: feature {feature} doesn't match the id's {id_feature}."))
    if kind == "tasks":
        out += _task_ids(doc)
    return out


def _task_ids(doc: Doc) -> list[Finding]:
    """Task headings that aren't well-formed, and tasks from another feature."""
    out = []
    in_fence = False
    for number, line in enumerate(doc.text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and _TASK_HEADING_START.match(line) and not _TASK_HEADING.match(line):
            out.append(_finding("bad-id", doc.subject, doc.path, number,
                                f"{doc.subject}: a task heading isn't written `### T-Fnn-kk: <title>`, "
                                "so it isn't read as a task."))
    feature = _feature_of(doc) or _id_feature(doc)
    if feature and doc.task_list:
        for task in doc.task_list.tasks.values():
            task_feature = _TASK_ID.fullmatch(task.id).group(1)
            if task_feature != feature:
                out.append(_finding("bad-id", task.id, doc.path, task.line,
                                    f"{task.id} is in {doc.subject}, whose feature is {feature}."))
    return out


def _file_name(doc: Doc) -> list[Finding]:
    kind = doc.type
    folder, name = (doc.rel.rsplit("/", 1) if "/" in doc.rel else ("", doc.rel))
    if kind in FIXED:
        expected_folder, pattern, shown = "", re.escape(FIXED[kind][1]), FIXED[kind][1]
    elif kind == "research":
        expected_folder, pattern, shown = "research", r"[^/]+\.md", "research/<name>.md"
    elif kind in FEATURE_DOCS:
        expected_folder = FEATURE_DOCS[kind][1]
        feature = _id_feature(doc)
        pattern = rf"{feature or 'F[0-9]{2,}'}-{SLUG}\.md"
        shown = f"{expected_folder}/{feature or 'Fnn'}-<slug>.md"
    else:
        return []
    allowed = {expected_folder, f"{expected_folder}/{COMPLETED}".lstrip("/")}
    if folder in allowed and re.fullmatch(pattern, name):
        return []
    docs_dir = doc.path[: len(doc.path) - len(doc.rel)]
    return [_finding("file-name", doc.subject, doc.path, doc.line("id"),
                     f"{doc.subject} should be at {docs_dir}{shown} (or in a {COMPLETED}/ folder next to it), "
                     f"not {doc.path}.")]


def _feature_known(doc: Doc, corpus: Corpus) -> list[Finding]:
    feature = _feature_of(doc)
    if doc.type not in FEATURE_DOCS or feature is None or not corpus.pdrd_read:
        return []
    if feature in corpus.features:
        return []
    return [_finding("unknown-feature", doc.subject, doc.path, doc.line("feature"),
                     f"{doc.subject}: feature {feature} isn't a `### {feature}:` heading in the PDRD.")]


def _duplicate_ids(corpus: Corpus) -> list[Finding]:
    out = []
    for id_, docs in corpus.by_id.items():
        first = docs[0]
        for doc in docs[1:]:
            out.append(_finding("duplicate-id", id_, doc.path, doc.line("id"),
                                f"{id_} is also the id of {first.path}."))
    return out


# --- tasks -----------------------------------------------------------------------------

def _approved_by_lines(doc: Doc) -> list[Finding]:
    out = []
    if doc.task_list is None:
        return out
    for task in doc.task_list.tasks.values():
        for approved in task.approved_by:
            if approved.name is None:
                out.append(_finding("task-format", task.id, doc.path, approved.line,
                                    f"{task.id}: an `Approved by` line isn't "
                                    "`Approved by <name> on <YYYY-MM-DD>` with an optional `(<note>)`."))
    return out


def _tasks(corpus: Corpus) -> list[Finding]:
    """`duplicate-task`, `dependency-missing` and `dependency-cycle`, across every list."""
    out = []
    seen: dict[str, tuple[Doc, object]] = {}   # task ID -> its first (list, task), by path
    for doc in corpus.docs.values():
        if doc.task_list is None:
            continue
        for task in doc.task_list.tasks.values():
            if task.id in seen:
                out.append(_finding("duplicate-task", task.id, doc.path, task.line,
                                    f"{task.id} is also in {seen[task.id][0].subject} ({seen[task.id][0].path})."))
            else:
                seen[task.id] = (doc, task)

    unreadable = _broken_task_features(corpus)
    graph: dict[str, list[str]] = {}
    for task_id, (doc, task) in seen.items():
        graph[task_id] = []
        for dep in task.depends_on:
            if dep in seen:
                graph[task_id].append(dep)
            elif _TASK_ID.fullmatch(dep).group(1) not in unreadable:
                out.append(_finding("dependency-missing", task_id, doc.path, _depends_line(doc, task),
                                    f"{task_id} depends on {dep}, which isn't a task in any list."))

    for cycle in _cycles(graph):
        doc, task = seen[cycle[0]]
        out.append(_finding("dependency-cycle", cycle[0], doc.path, _depends_line(doc, task),
                            f"{cycle[0]} is in a dependency cycle: {' -> '.join(cycle)}."))
    return out


def _broken_task_features(corpus: Corpus) -> set[str]:
    """Features whose task list couldn't be read, from the broken file's name or subject."""
    features = set()
    for path, finding in corpus.broken.items():
        match = (re.search(r"(?:^|/)tasks/(?:completed/)?(F\d{2,})-[^/]*$", path)
                 or re.fullmatch(r"TASKS-(F\d{2,})", finding.subject))
        if match:
            features.add(match.group(1))
    return features


def _depends_line(doc: Doc, task) -> int:
    """The line of the task's first `Depends on` line, or its heading if it has none."""
    lines = doc.text.splitlines()
    for number in range(task.line + 1, len(lines) + 1):
        line = lines[number - 1]
        if _BLOCK_END.match(line):
            break
        if _DEPENDS_LINE.match(line):
            return number
    return task.line


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """One cycle per strongly connected component that has one, starting and ending at its lowest ID.

    Tarjan's algorithm, iterative so a long chain of tasks can't hit Python's recursion limit.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)

    for start in sorted(graph):
        if start in index:
            continue
        visit(start)
        work = [(start, iter(graph[start]))]
        while work:
            node, edges = work[-1]
            for nxt in edges:
                if nxt not in index:
                    visit(nxt)
                    work.append((nxt, iter(graph[nxt])))
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(component)

    cycles = []
    for component in components:
        lowest = min(component)
        if len(component) == 1 and lowest not in graph[lowest]:
            continue
        cycles.append(_cycle_through(lowest, set(component), graph))
    return sorted(cycles)


def _cycle_through(start: str, members: set[str], graph: dict[str, list[str]]) -> list[str]:
    """The shortest path from `start` back to itself within `members`, as a list of IDs."""
    came_from: dict[str, str] = {}
    queue = [start]
    for node in queue:
        for nxt in sorted(graph[node]):
            if nxt == start:
                path = [node]
                while path[-1] != start:
                    path.append(came_from[path[-1]])
                return path[::-1] + [start]
            if nxt in members and nxt not in came_from:
                came_from[nxt] = node
                queue.append(nxt)
    return [start, start]  # not reached for a real component
