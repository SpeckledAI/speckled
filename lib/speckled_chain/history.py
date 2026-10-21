"""Read the planning repo's git history, once, as a list of document changes.

Why this module exists:
    Some rules are about history, not the current files: approvals are only ever
    appended, documents are moved but never deleted, and the log is append-only. This
    is the one module that runs git. It turns the history into `Change`s that the
    checks compare, so no check ever runs git itself [T-F08-08].

What it runs (and nothing else, so a repo's own config can't run code through it):
    - `git rev-parse --is-inside-work-tree`, `--is-shallow-repository` and
      `--verify HEAD`;
    - one `git log` over `docs_dir`, `speckled.yaml` and `.speckled/log.jsonl`, with
      `--raw -z` blob IDs;
    - one long-running `git cat-file --batch`, which reads each distinct blob once.
    No diff, textconv, filter or fsmonitor runs: `git status`, `diff`, `show` and
    `blame` are never used, and the working tree is read from disk. git always gets an
    argument list, never a shell; paths come from `-z` output and pathspecs follow
    `--`; `cat-file` is asked for blob IDs, never paths. Author names come from `%an`;
    email addresses are never requested.

How history is read:
    - `--parents` rewrites each commit's parents to the nearest commits the log
      lists, so a commit's documents are its first parent's plus its own changes,
      even when commits in between touched nothing tracked.
    - A merge is compared with its first parent only. Two approvals appended on two
      branches then reach `main` in an order that isn't a reorder, and anything a
      conflict resolution changed is still seen.
    - A document is the same document across moves and renames if its `id` is
      unchanged. A path that disappears is a deletion only if no file in that
      commit's tree still has that `id`. Research notes and files without a readable
      `id` are tracked by path, through git's rename detection, or as an exact move.
    - After the commits, the working tree is compared with `HEAD`, read from disk.
    - `added_in()` gives each approval the first commit that added it (see there).

Narrowing:
    `open_history(root, docs_dir, only=globs)` reads only the documents whose paths
    match `globs` (relative to the planning repo; `*` and `?` stay within one folder,
    and `\\` escapes the next character), plus `speckled.yaml` and the log. git gets
    them as `:(glob)` pathspecs, and the working tree is filtered the same way. A
    document that was moved from a path outside `globs` looks added, and one moved to
    such a path looks deleted, so the caller picks globs that cover every path a
    document could have had, and rereads in full if a narrowed history has a deletion.

What it gives:
    `open_history(root, docs_dir)` returns a `History`. Outside a git repository it
    has a `history-unavailable` warning and `status="none"`; in a shallow clone, a
    `history-unavailable` error and `status="shallow"`. A repo with no commits has no
    changes. Any git failure part-way raises `GitError` naming the command: a partial
    history is never returned. `git` missing raises `GitError` too, unless the folder
    isn't in a git repository at all.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from speckled_gate.docs import DocError, TaskList, front_matter, parse_task_list
from speckled_gate.yamlio import YamlError

from .corpus import _document_files, is_document_place
from .report import Finding
from .rules import RULES

CONFIG = "speckled.yaml"
LOG = ".speckled/log.jsonl"
# Regular files only: symlinks (120000) and submodules (160000) aren't documents.
_FILE_MODES = ("100644", "100755")
_FORMAT = "%x01%H%x00%P%x00%an%x00%aI"


class GitError(RuntimeError):
    """A git command couldn't run or failed. `command` is what it was, such as `git log`."""

    def __init__(self, command: str, reason: str):
        super().__init__(f"{command} failed: {reason}")
        self.command = command
        self.reason = reason


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]   # rewritten to commits in the log; the first is compared
    author: str                # `%an`, never an email address
    date: str                  # the author date, YYYY-MM-DD

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


@dataclass
class Version:
    """One document as it was at one commit, or in the working tree."""

    path: str                  # relative to the planning repo
    blob: str                  # git's object ID for its content (computed for the working tree)
    text: str
    meta: dict | None          # the front matter, or None if it can't be read
    task_list: TaskList | None = None

    @property
    def id(self) -> str | None:
        value = (self.meta or {}).get("id")
        return value if isinstance(value, str) and value else None

    @property
    def body(self) -> str:
        """Everything after the front matter (the whole text if there's none)."""
        lines = self.text.splitlines()
        if lines and lines[0].strip() == "---":
            for end in range(1, len(lines)):
                if lines[end].strip() == "---":
                    return "\n".join(lines[end + 1:])
        return self.text


@dataclass(frozen=True)
class Change:
    """A document changed by one commit (`commit=None`: the working tree, against `HEAD`).

    `doc` is the document's `id`, or, for a file tracked by path, the path it was first
    committed under. `old` is None for a new document, `new` None for a deleted one.
    """

    commit: Commit | None
    doc: str
    old: Version | None
    new: Version | None


@dataclass(frozen=True)
class BlobChange:
    """`speckled.yaml` or `.speckled/log.jsonl` changed (`commit=None`: the working tree)."""

    commit: Commit | None
    path: str
    old: str | None   # blob IDs, read through `History.reader`
    new: str | None


@dataclass
class History:
    status: str                                    # "full", "none" or "shallow"
    findings: list[Finding] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)       # oldest first, parents before children
    changes: list[Change] = field(default_factory=list)       # in commit order, then the working tree
    log_changes: list[BlobChange] = field(default_factory=list)
    reader: BlobReader | None = None
    head: str | None = None
    _config: dict[str, str | None] = field(default_factory=dict)   # commit -> speckled.yaml blob
    _added: dict[tuple, Commit] = field(default_factory=dict)

    def config_blob(self, commit: str) -> str | None:
        """The blob of `speckled.yaml` as of `commit`, or None if it didn't exist."""
        return self._config.get(commit)

    def added_in(self, entries_by_doc: dict[str, list[tuple]]) -> dict[tuple[str, tuple], Commit | None]:
        """The commit that added each entry; None if it isn't committed.

        `entries_by_doc` maps a `Change.doc` to entry keys from `entry_keys()`. An entry
        is added in the first non-merge commit where it appears and wasn't in that
        commit's parent. One that appears in a merge but in neither parent was added
        by the merge, as when it's written while resolving a conflict. Entries are
        matched by content, so if the same entry, word for word, is added on two
        unrelated branches, the earlier commit in history order is the one given.
        """
        return {(doc, key): self._added.get((doc, key))
                for doc, keys in entries_by_doc.items() for key in keys}


def entry_keys(version: Version | None) -> list[tuple]:
    """A key for each `approvals` entry and `Approved by` line in `version`, in file order.

    Keys compare the whole entry, so an edited entry has a new key. Approvals entries
    are `("approval", <entry as sorted JSON>)`; `Approved by` lines are
    `("approved-by", <task ID>, <name>, <date>, <note>)`.
    """
    if version is None:
        return []
    keys: list[tuple] = []
    approvals = (version.meta or {}).get("approvals")
    if isinstance(approvals, list):
        keys += [("approval", json.dumps(entry, sort_keys=True, default=str)) for entry in approvals]
    if version.task_list is not None:
        for task in version.task_list.tasks.values():
            keys += [("approved-by", task.id, a.name, a.date, a.note) for a in task.approved_by]
    return keys


# --- running git -----------------------------------------------------------------------

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run `git <args>` in `root`; raise GitError if `git` is missing."""
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except FileNotFoundError:
        raise GitError(f"git {args[0]}", "git isn't installed or isn't on PATH") from None


def _check(result: subprocess.CompletedProcess, command: str) -> bytes:
    if result.returncode != 0:
        reason = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(command, reason[0] if reason else f"exit status {result.returncode}")
    return result.stdout


class BlobReader:
    """One `git cat-file --batch` process. Each blob is read, and parsed, at most once."""

    def __init__(self, root: Path):
        self.root = root
        self.requests: list[str] = []   # blob IDs asked of git, in order
        self._data: dict[str, bytes] = {}
        self._parsed: dict[str, tuple] = {}
        self._process: subprocess.Popen | None = None

    def add(self, blob: str, data: bytes) -> None:
        """Content that didn't come from git (the working tree), under its object ID."""
        self._data.setdefault(blob, data)

    def read(self, blob: str) -> bytes:
        if blob not in self._data:
            self._data[blob] = self._fetch(blob)
        return self._data[blob]

    def version(self, path: str, blob: str) -> Version:
        """The document `path` with the content `blob`. Parsing is cached by blob."""
        if blob not in self._parsed:
            self._parsed[blob] = _parse(self.read(blob), path)
        text, meta, task_list = self._parsed[blob]
        return Version(path=path, blob=blob, text=text, meta=meta, task_list=task_list)

    def _fetch(self, blob: str) -> bytes:
        command = "git cat-file"
        try:
            if self._process is None:
                self._process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=self.root,
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                 stderr=subprocess.DEVNULL)
            self.requests.append(blob)
            self._process.stdin.write(blob.encode("ascii") + b"\n")
            self._process.stdin.flush()
            header = self._process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise GitError(command, f"object {blob} is missing or isn't a file")
            size = int(header[2])
            data = self._process.stdout.read(size + 1)[:size]
            if len(data) != size:
                raise GitError(command, f"object {blob} was cut short")
            return data
        except FileNotFoundError:
            raise GitError(command, "git isn't installed or isn't on PATH") from None
        except (OSError, ValueError) as e:
            raise GitError(command, str(e)) from None

    def close(self) -> None:
        if self._process is not None:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                self._process.kill()
                self._process.wait()
            self._process.stdout.close()
            self._process = None


def _parse(data: bytes, path: str) -> tuple[str, dict | None, TaskList | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "", None, None
    try:
        meta = front_matter(text)
    except YamlError:
        return text, None, None
    if not meta:
        return text, None, None
    task_list = None
    if meta.get("type") == "tasks":
        try:
            task_list = parse_task_list(text, path)
        except DocError:
            task_list = None
    return text, meta, task_list


# --- opening the history ---------------------------------------------------------------

def open_history(root: str | Path, docs_dir: str, only: list[str] | None = None) -> History:
    """Read the history of the planning repo at `root`, or of the documents matching `only`.

    Raises GitError on failure.
    """
    root = Path(root)
    try:
        inside = _git(root, "rev-parse", "--is-inside-work-tree")
    except GitError:
        if _in_a_repo(root):
            raise
        inside = None
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != b"true":
        return History("none", [_unavailable(
            "warning", "this folder isn't in a git repository, so history checks didn't run.")])

    shallow = _check(_git(root, "rev-parse", "--is-shallow-repository"), "git rev-parse")
    if shallow.strip() == b"true":
        return History("shallow", [_unavailable(
            "error", "this is a shallow clone, so history checks can't run. Fetch the full history; "
                     "in CI, check out with `fetch-depth: 0`.")])

    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if head.returncode != 0:
        return History("full")   # no commits yet: nothing to compare, nothing committed

    reader = BlobReader(root)
    try:
        history = _Walk(root, _docs_prefix(docs_dir), reader, head.stdout.decode("ascii").strip(), only).run()
    except BaseException:
        reader.close()
        raise
    reader.close()
    return history


def _in_a_repo(root: Path) -> bool:
    """Whether `root` looks like it's inside a git repository, without running git."""
    return any((folder / ".git").exists() for folder in (root.resolve(), *root.resolve().parents))


def _unavailable(severity: str, message: str) -> Finding:
    rule = RULES["history-unavailable"]
    return Finding("history-unavailable", severity, CONFIG, None, None, f"History: {message}", rule.fix)


def glob_escape(path: str) -> str:
    """`path` as a glob that matches only itself."""
    return re.sub(r"([*?\[\\])", r"\\\1", path)


def _glob_matcher(globs: list[str]):
    """A test for paths matching any of `globs`, as git's `:(glob)` pathspecs match them."""
    parts = []
    for glob in globs:
        out, i = [], 0
        while i < len(glob):
            c = glob[i]
            if c == "\\" and i + 1 < len(glob):
                out.append(re.escape(glob[i + 1]))
                i += 2
                continue
            out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
        parts.append("".join(out))
    pattern = re.compile("|".join(f"(?:{p})" for p in parts)) if parts else None
    return lambda path: pattern is not None and pattern.fullmatch(path) is not None


def _docs_prefix(docs_dir: str) -> str:
    """`docs_dir` as a path prefix: `docs/`, or "" for the repo's own folder."""
    parts = [p for p in docs_dir.replace("\\", "/").split("/") if p not in ("", ".")]
    return "/".join(parts) + "/" if parts else ""


@dataclass
class _Raw:
    """One `--raw` record: status letter, and the old and new side (None if absent)."""

    status: str
    old_path: str | None
    old_blob: str | None
    new_path: str | None
    new_blob: str | None


class _Walk:
    """Replays the log commit by commit, keeping each commit's tracked files (path -> blob)."""

    def __init__(self, root: Path, prefix: str, reader: BlobReader, head: str, only: list[str] | None = None):
        self.root = root
        self.prefix = prefix
        self.only = only
        self.matches = _glob_matcher(only) if only is not None else None
        self.reader = reader
        self.head = head
        self.history = History("full", reader=reader, head=head)
        self.trees: dict[str, dict[str, str]] = {}
        self.path_identity: dict[str, str] = {}   # path -> first path, for files tracked by path
        self.ids_in_tree: dict[str, dict[str, str]] = {}   # commit -> id -> path, built lazily

    def run(self) -> History:
        for commit, records in self._log():
            base = self.trees.get(commit.parents[0], {}) if commit.parents else {}
            tree = dict(base)
            renames = []
            for raw in records:
                if raw.old_path is not None:
                    tree.pop(raw.old_path, None)
                if raw.new_path is not None:
                    tree[raw.new_path] = raw.new_blob
                if raw.status == "R" and raw.old_path and raw.new_path:
                    renames.append((raw.old_path, raw.new_path))
            self.trees[commit.sha] = tree
            self.history.commits.append(commit)
            self.history._config[commit.sha] = tree.get(CONFIG)
            self._compare(commit, base, tree, renames)
        self._working_tree()
        # Read every config and log version now, so later checks never need git again.
        for blob in sorted({b for b in self.history._config.values() if b}
                           | {b for c in self.history.log_changes for b in (c.old, c.new) if b}):
            self.reader.read(blob)
        return self.history

    # --- the log ---------------------------------------------------------------------

    def _log(self):
        # `--relative`: paths relative to the planning repo, even inside a larger repository.
        args = ["-c", "core.quotepath=off", "log", "--full-history", "--topo-order", "--reverse", "--parents",
                "-M", "--raw", "-z", "--no-abbrev", "--relative", "--diff-merges=first-parent", f"--format={_FORMAT}",
                "--", *self._pathspecs(), CONFIG, LOG]
        out = _check(_git(self.root, *args), "git log")
        tokens = out.split(b"\0")
        i, commit, records = 0, None, []
        while i < len(tokens):
            token = tokens[i].lstrip(b"\n")
            if token.startswith(b"\x01") and i + 3 < len(tokens):
                if commit is not None:
                    yield commit, records
                sha = token[1:].decode("ascii")
                parents = tuple(tokens[i + 1].decode("ascii").split())
                author = tokens[i + 2].decode("utf-8", "replace")
                date = tokens[i + 3].decode("ascii")[:10]
                commit, records = Commit(sha, parents, author, date), []
                i += 4
            elif token.startswith(b":"):
                meta = token[1:].decode("ascii").split()
                status = meta[4][0]
                paths = 2 if status in "RC" else 1
                names = [_path(t) for t in tokens[i + 1:i + 1 + paths]]
                records.append(self._record(meta, status, names))
                i += 1 + paths
            else:
                i += 1
        if commit is not None:
            yield commit, records

    def _record(self, meta: list[str], status: str, names: list[str]) -> _Raw:
        old_mode, new_mode, old_blob, new_blob = meta[:4]
        old_path = names[0] if status != "A" else None
        new_path = names[-1] if status != "D" else None
        if status == "C":
            old_path = None   # a copy leaves the source where it is
        keep_old = old_path is not None and old_mode in _FILE_MODES and self._tracked(old_path)
        keep_new = new_path is not None and new_mode in _FILE_MODES and self._tracked(new_path)
        return _Raw(status, old_path if keep_old else None, old_blob if keep_old else None,
                    new_path if keep_new else None, new_blob if keep_new else None)

    def _pathspecs(self) -> list[str]:
        if self.only is None:
            return [self.prefix or "."]
        # No globs: nothing but the config and the log.
        return [f":(glob){glob}" for glob in self.only]

    def _tracked(self, path: str) -> bool:
        if path in (CONFIG, LOG):
            return True
        in_docs = path.startswith(self.prefix) and path.endswith(".md")
        return in_docs and (self.matches is None or self.matches(path))

    # --- comparing two trees ---------------------------------------------------------

    def _compare(self, commit: Commit | None, before: dict[str, str], after: dict[str, str],
                 renames: list[tuple[str, str]]) -> None:
        if before.get(LOG) != after.get(LOG):
            self.history.log_changes.append(BlobChange(commit, LOG, before.get(LOG), after.get(LOG)))

        changed = sorted(p for p in set(before) | set(after)
                         if p not in (CONFIG, LOG) and before.get(p) != after.get(p))
        olds = {p: self._version(p, before[p]) for p in changed if p in before}
        news = {p: self._version(p, after[p]) for p in changed if p in after}
        olds = {p: v for p, v in olds.items() if v is not None}
        news = {p: v for p, v in news.items() if v is not None}

        pairs: list[tuple[Version | None, Version | None]] = []
        # 1. The same path, edited.
        for path in sorted(set(olds) & set(news)):
            pairs.append((olds.pop(path), news.pop(path)))
        # 2. The same id, moved.
        new_by_id = {v.id: p for p, v in sorted(news.items()) if self._by_id(v)}
        for path, old in sorted(olds.items()):
            if self._by_id(old) and old.id in new_by_id:
                pairs.append((olds.pop(path), news.pop(new_by_id.pop(old.id))))
        # 3. Files tracked by path: git's renames, then exact moves.
        for src, dst in renames:
            if src in olds and dst in news:
                pairs.append((olds.pop(src), news.pop(dst)))
        new_by_blob = {v.blob: p for p, v in sorted(news.items())}
        for path, old in sorted(olds.items()):
            if old.blob in new_by_blob and new_by_blob[old.blob] in news:
                pairs.append((olds.pop(path), news.pop(new_by_blob.pop(old.blob))))
        # 4. A path that disappeared, whose id is still in the tree: not a deletion.
        for path, old in sorted(olds.items()):
            elsewhere = self._find_id(after, old.id) if self._by_id(old) else None
            pairs.append((old, elsewhere))
        for path, new in sorted(news.items()):
            pairs.append((None, new))

        for old, new in pairs:
            if old is not None and new is not None and old.blob == new.blob and old.path == new.path:
                continue
            doc = self._identity(old, new)
            change = Change(commit, doc, old, new)
            self.history.changes.append(change)
            if commit is not None:
                self._record_added(commit, change)

    @staticmethod
    def _by_id(version: Version) -> bool:
        """Whether a version is tracked by its `id` (research notes are tracked by path)."""
        return version.id is not None and (version.meta or {}).get("type") != "research"

    def _version(self, path: str, blob: str) -> Version | None:
        """The document at `path`, or None if the file isn't a document."""
        version = self.reader.version(path, blob)
        rel = path[len(self.prefix):]
        if version.meta is None and not is_document_place(rel) and not version.text.startswith("---"):
            return None
        return version

    def _find_id(self, tree: dict[str, str], id_: str) -> Version | None:
        for path in sorted(tree):
            if path in (CONFIG, LOG):
                continue
            version = self._version(path, tree[path])
            if version is not None and version.id == id_ and self._by_id(version):
                return version
        return None

    def _identity(self, old: Version | None, new: Version | None) -> str:
        for version in (new, old):
            if version is not None and self._by_id(version):
                return version.id
        first = self.path_identity.get(old.path, old.path) if old is not None else new.path
        if new is not None:
            self.path_identity[new.path] = first
        return first

    # --- added-in commits ------------------------------------------------------------

    def _record_added(self, commit: Commit, change: Change) -> None:
        before = set(entry_keys(change.old))
        others: set = set()
        if commit.is_merge:
            # Entries already in another parent were added there, not by the merge.
            for parent in commit.parents[1:]:
                others |= set(entry_keys(self._doc_in(parent, change.doc)))
        for key in entry_keys(change.new):
            if key in before or key in others:
                continue
            self.history._added.setdefault((change.doc, key), commit)

    def _doc_in(self, commit: str, doc: str) -> Version | None:
        tree = self.trees.get(commit, {})
        for path in sorted(tree):
            if path in (CONFIG, LOG):
                continue
            version = self._version(path, tree[path])
            if version is None:
                continue
            if (self._by_id(version) and version.id == doc) or self.path_identity.get(path, path) == doc:
                return version
        return None

    # --- the working tree ------------------------------------------------------------

    def _working_tree(self) -> None:
        head_tree = self._head_tree()
        disk: dict[str, str] = {}
        sha256 = len(self.head) == 64
        files = [self.root / CONFIG, self.root / LOG]
        docs_root = self.root / self.prefix if self.prefix else self.root
        files += [] if docs_root.is_symlink() else _document_files(docs_root)
        for file in files:
            if file.is_symlink() or not file.is_file():
                continue
            data = file.read_bytes()
            blob = _object_id(data, sha256)
            self.reader.add(blob, data)
            disk[file.relative_to(self.root).as_posix()] = blob
        disk = {p: b for p, b in disk.items() if self._tracked(p)}
        self._compare(None, head_tree, disk, renames=[])

    def _head_tree(self) -> dict[str, str]:
        """The tracked files at `HEAD`: those of the last commit in the log that HEAD descends from."""
        if self.head in self.trees:
            return self.trees[self.head]
        # HEAD itself touched nothing tracked. Every listed commit is its ancestor, and
        # merges are always listed, so exactly one listed commit has no listed child.
        parents = {p for c in self.history.commits for p in c.parents}
        tips = [c.sha for c in self.history.commits if c.sha not in parents]
        return self.trees[tips[-1]] if tips else {}


def _path(token: bytes) -> str:
    return token.decode("utf-8", "surrogateescape")


def _object_id(data: bytes, sha256: bool) -> str:
    """git's object ID for a file with this content."""
    digest = hashlib.sha256 if sha256 else hashlib.sha1
    return digest(b"blob %d\0" % len(data) + data).hexdigest()
