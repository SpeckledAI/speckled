"""Find and parse every document in a planning repo, once.

Why this module exists:
    Every check reads the same documents, so they're found and parsed here once and
    shared as a `Corpus`. Parsing goes through the gate's own code
    (`speckled_gate.docs.front_matter` and `parse_task_list`), so the linter and the
    hook never disagree about what a file says, or about whether it can be read.

What it does:
    - `load_corpus(root)` reads `speckled.yaml`, then finds the documents under
      `docs_dir` (protocol §9, "Which files are documents"):
        - `brief.md`, `pdrd.md` and `architecture.md` in `docs_dir`;
        - every `.md` file in `research/`, `frds/`, `tdds/` and `tasks/`, and in a
          `completed/` folder under any of them or under `docs_dir`.
      A file in those places without front matter is a `front-matter` error. Any other
      `.md` file under `docs_dir` is a document only if it opens with front matter.
      Symlinks and anything that isn't a regular file are skipped, so a link can't
      make the linter read outside the repo.
    - A file that can't be read gives exactly one finding (`front-matter` or
      `task-format`) and goes into `Corpus.broken` instead of `Corpus.docs`, so the
      other checks skip it and still check every other file [T-F08-05].
    - `Corpus.features` are the `### Fnn:` headings in `pdrd.md`.

Messages quote only structured values (IDs, statuses, field names), never a title or
body text (protocol §9, "What messages may quote").
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from speckled_gate.docs import DocError, TaskList, front_matter, parse_task_list
from speckled_gate.yamlio import YamlError

from .config import Config, load_config
from .report import Finding
from .rules import RULES

TOP_LEVEL = ("brief.md", "pdrd.md", "architecture.md")
FOLDERS = ("research", "frds", "tdds", "tasks")
COMPLETED = "completed"
# Fields the gate's task-list parser requires before it reads any task.
_TASK_LIST_FIELDS = ("id", "status", "version")

_FEATURE_HEADING = re.compile(r"^### (F\d{2,}):")
_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
_LIST_ITEM = re.compile(r"^\s*-(\s|$)")
_TITLE = re.compile(r"^# \S")
# Protocol §5 rule 2: "> ⚠️ Drafted from an unapproved parent (...)". The emoji's
# variation selector is optional, since editors don't always keep it.
_RULE2 = re.compile(r"^>\s*⚠️?\s*Drafted from an unapproved parent\b")


@dataclass
class Doc:
    """One readable document."""

    path: str            # relative to the planning repo, with forward slashes
    rel: str             # relative to `docs_dir`, with forward slashes
    meta: dict           # the front matter
    text: str
    lines: dict[str, int] = field(default_factory=dict)       # top-level front-matter key -> line
    approval_lines: list[int] = field(default_factory=list)   # line of each `approvals` entry
    task_list: TaskList | None = None   # for `type: tasks`
    rule2_line: bool = False            # the §5 rule 2 line is directly under the title
    body_start: int = 1                 # first line after the front matter

    @property
    def id(self) -> str | None:
        value = self.meta.get("id")
        return value if isinstance(value, str) and value else None

    @property
    def type(self):
        return self.meta.get("type")

    @property
    def subject(self) -> str:
        return self.id or self.path

    def line(self, key: str) -> int:
        """The line where front-matter `key` is written, or line 1 if it isn't."""
        return self.lines.get(key, 1)

    @property
    def body(self) -> str:
        return "\n".join(self.text.splitlines()[self.body_start - 1:])


@dataclass
class Corpus:
    config: Config
    root: Path
    docs: dict[str, Doc] = field(default_factory=dict)          # by path, sorted
    by_id: dict[str, list[Doc]] = field(default_factory=dict)   # by id, each list sorted by path
    features: set[str] = field(default_factory=set)
    pdrd_read: bool = False   # whether `pdrd.md` was readable, so `features` means something
    broken: dict[str, Finding] = field(default_factory=dict)    # by path: the file's one finding

    @property
    def documents(self) -> int:
        return len(self.docs) + len(self.broken)


def load_corpus(root: str | Path) -> Corpus:
    """Read `speckled.yaml` and every document under `docs_dir`.

    Raises `ConfigError` or `OSError` as `load_config` does.
    """
    root = Path(root)
    config = load_config(root)
    corpus = Corpus(config=config, root=root)
    docs_root = root / config.docs_dir
    for file in _document_files(docs_root):
        rel = file.relative_to(docs_root).as_posix()
        path = file.relative_to(root).as_posix()
        doc = _read(file, path, rel, corpus)
        if doc is not None:
            corpus.docs[path] = doc
    for doc in corpus.docs.values():
        if doc.id is not None:
            corpus.by_id.setdefault(doc.id, []).append(doc)
    pdrd = next((d for d in corpus.docs.values() if d.rel == "pdrd.md"), None)
    if pdrd is not None:
        corpus.pdrd_read = True
        corpus.features = pdrd_features(pdrd.text)
    return corpus


def is_document_place(rel: str) -> bool:
    """Whether a file at `rel` (relative to `docs_dir`) is a document, front matter or not."""
    parts = rel.split("/")
    if len(parts) == 1:
        return parts[0] in TOP_LEVEL
    if parts[0] == COMPLETED:
        return len(parts) == 2
    if parts[0] in FOLDERS:
        return len(parts) == 2 or (len(parts) == 3 and parts[1] == COMPLETED)
    return False


def _document_files(docs_root: Path) -> list[Path]:
    """Every regular, non-symlink `.md` file under `docs_root`, sorted by path."""
    if docs_root.is_symlink() or not docs_root.is_dir():
        return []
    found = []
    # os.walk doesn't descend into symlinked folders.
    for folder, _dirs, files in os.walk(docs_root):
        for name in files:
            file = Path(folder) / name
            if name.endswith(".md") and not file.is_symlink() and file.is_file():
                found.append(file)
    return sorted(found, key=lambda f: f.relative_to(docs_root).as_posix())


def _read(file: Path, path: str, rel: str, corpus: Corpus) -> Doc | None:
    """The parsed document, or None if it isn't one or is broken (then it's in `corpus.broken`)."""
    def broken(rule: str, line: int, message: str, subject: str = path) -> None:
        corpus.broken[path] = Finding(rule, RULES[rule].severity, subject, path, line,
                                      message, RULES[rule].fix)

    in_place = is_document_place(rel)
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        if in_place:
            broken("front-matter", 1, f"{path} isn't valid UTF-8 text.")
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        if in_place:
            broken("front-matter", 1, f"{path} has no front matter.")
        return None

    try:
        meta = front_matter(text)
    except YamlError as e:
        broken("front-matter", e.line, f"{path}: front matter can't be read: {e.reason}.")
        return None
    end = next(n for n in range(1, len(lines)) if lines[n].strip() == "---")
    doc = Doc(path=path, rel=rel, meta=meta, text=text, body_start=end + 2)
    _field_lines(doc, lines[1:end])
    doc.rule2_line = _has_rule2_line(lines[end + 1:])

    if meta.get("type") == "tasks":
        try:
            doc.task_list = parse_task_list(text, path)
        except DocError as e:
            # The gate can't read this list either. A missing list field is a
            # front-matter problem; anything else is the task format.
            missing = [k for k in _TASK_LIST_FIELDS if k not in meta]
            if missing:
                broken("front-matter", e.line, f"{doc.subject}: front matter is missing '{missing[0]}'.",
                       doc.subject)
            else:
                broken("task-format", e.line, f"{doc.subject}: {e.reason}.", doc.subject)
            return None
    return doc


def _field_lines(doc: Doc, block: list[str]) -> None:
    """Record the line of each top-level key, and of each `approvals` entry.

    Front matter starts on line 2 of the file. A flow-style list
    (`approvals: [{...}, {...}]`) puts every entry on the `approvals` line.
    """
    in_approvals = False
    for offset, line in enumerate(block):
        number = offset + 2
        key = _TOP_KEY.match(line)
        if key:
            doc.lines.setdefault(key.group(1), number)
            in_approvals = key.group(1) == "approvals"
        elif in_approvals and _LIST_ITEM.match(line):
            doc.approval_lines.append(number)
    approvals = doc.meta.get("approvals")
    count = len(approvals) if isinstance(approvals, list) else 0
    if len(doc.approval_lines) != count:
        doc.approval_lines = [doc.line("approvals")] * count


def _has_rule2_line(body: list[str]) -> bool:
    """Whether the first non-blank line after the `# ` title is the §5 rule 2 line."""
    lines = iter(body)
    for line in lines:
        if _TITLE.match(line):
            break
    else:
        return False
    for line in lines:
        if line.strip():
            return bool(_RULE2.match(line.strip()))
    return False


def pdrd_features(text: str) -> set[str]:
    """The `### Fnn:` headings in the PDRD, outside ``` code blocks."""
    features = set()
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        heading = None if in_fence else _FEATURE_HEADING.match(line)
        if heading:
            features.add(heading.group(1))
    return features
