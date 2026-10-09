"""Describe what a shell command would do to files and to git.

Why this module exists:
    Agents often change files with shell commands rather than file-editing tools (asked
    to edit a file, a model may well use `sed -i`). The gate has to see those writes,
    and the guard hook has to see recursive deletes and secret `.env` access. Both use
    this module, so the command is understood the same way everywhere.

What it does:
    `actions(command)` returns a list of ShellAction describing the command: which files
    it would write, move or delete, whether it commits, pushes or opens a pull request,
    and whether it tries to switch hooks off. It only *describes*; deciding whether that
    is allowed belongs to the rules module. It never reads speckled.yaml or the disk.

How:
    1. A pre-pass turns unquoted newlines into `;` and drops heredoc bodies, so each
       line is its own command and the text fed to `cat <<EOF` isn't read as commands.
       It also pulls out command substitutions (`$( … )` and backticks), which run even
       inside double quotes (`echo "done: $(rm -rf x)"`), and analyses each one as a
       command of its own. Single-quoted text stays inert, as it does in the shell.
    2. `shlex` splits the text into words and operators; operators (`;`, `&&`, `|`, ...)
       separate commands.
    3. Wrappers such as `sudo`, `env`, `xargs` are unwrapped to find the real program,
       and `bash -c "..."` strings are analysed recursively.
    4. Redirects (`>`, `>>`, ...) become writes; the program and its arguments are
       matched against a table of known writers.

Limits (documented, not hidden): programs not in the table produce nothing, so a script
(`python gen.py`) that writes files isn't seen. The server-side check is the backstop.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass

# Set when a command couldn't be tokenized (for example an unclosed quote). The caller
# treats an empty result plus this as "not recognized".
last_error: str | None = None

_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
_WRAPPERS = {"sudo", "env", "nohup", "time", "command", "exec", "xargs", "nice", "stdbuf"}
# Wrapper options that take a separate value, so the value isn't mistaken for the program.
_WRAPPER_ARGS = {
    "sudo": {"-u", "-g", "-C", "-p", "-h", "-U", "-r", "-t"},
    "env": {"-u", "-C", "-S"},
    "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a"},
    "nice": {"-n"},
}
_SHELLS = {"bash", "sh", "zsh", "dash"}
_MAX_DEPTH = 3

_SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")
_ENV_NAME = re.compile(r"\.env(\..+)?")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1")


@dataclass(frozen=True)
class ShellAction:
    """One thing a command would do.

    kind: write, delete, move, git-commit, git-push, pull-request, hooks-disabled,
          hooks-path, rm-recursive-force or reads-secret-env.
    target: the path as written in the command (joined onto any `cd` earlier in the
            same command), or None when the command affects files it doesn't name.
    detail: extra context, e.g. "patch", "repo-wide", "find", "xargs".
    """

    kind: str
    target: str | None = None
    detail: str = ""


def actions(command: str) -> list[ShellAction]:
    """Everything `command` would do that the gate or the guard cares about."""
    global last_error
    last_error = None
    return _analyse(command, depth=0)


def split_commands(command: str) -> list[list[str]]:
    """The command's simple commands, each as a list of words ([] if it can't be read).

    Command substitutions are replaced by a placeholder word; use `actions()` to see
    what they do.
    """
    return _split(command)[0]


def _split(command: str) -> tuple[list[list[str]], list[str]]:
    """The simple commands, plus the text of every command substitution found."""
    global last_error
    prepared, substitutions = _prepare(command)
    try:
        lex = shlex.shlex(prepared, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError as e:
        last_error = str(e)
        return [], []
    commands, current = [], []
    for i, token in enumerate(tokens):
        if token in _SEPARATORS or token == "$":
            if current:
                commands.append(current)
            current = []
            continue
        # A file-descriptor number right before a redirect ("2" in "2>err.log") isn't an
        # argument of the command.
        if token.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in _REDIRECTS | {">&", "<"}:
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands, substitutions


# --- pre-pass ------------------------------------------------------------------------

# Stands in for a command substitution, so the outer command keeps its shape.
_SUBST = "__speckled_substitution__"


def _prepare(command: str) -> tuple[str, list[str]]:
    """Prepare `command` for shlex.

    - Unquoted newlines become ';' so each line is its own command.
    - Heredoc bodies are dropped: they're input text, not commands.
    - Command substitutions (`$( … )` and backticks) run, even inside double quotes:
      each is replaced by a placeholder word and its inner command is returned, to be
      analysed separately. Text in single quotes is left alone, as the shell does.
    """
    out, quote, i = [], None, 0
    substitutions: list[str] = []
    heredoc_ends: list[str] = []
    text = command
    while i < len(text):
        c = text[i]
        if quote != "'":
            inner, end = _substitution_at(text, i)
            if inner is not None:
                substitutions.append(inner)
                out.append(_SUBST)
                i = end
                continue
        if quote:
            if c == "\\" and quote == '"':
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(c)
            i += 1
            continue
        if c in "'\"":
            quote = c
        elif c == "\\" and text[i + 1:i + 2] == "\n":
            i += 2  # line continuation
            continue
        elif c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
            m = _HEREDOC.match(text, i)
            if m:
                heredoc_ends.append(m.group(2))
                out.append("<< " + m.group(2))
                i = m.end()
                continue
        elif c == "\n":
            out.append(" ; ")
            i += 1
            # Skip heredoc bodies, each up to its closing delimiter line.
            while heredoc_ends:
                end = text.find("\n", i)
                line = text[i:] if end == -1 else text[i:end]
                i = len(text) if end == -1 else end + 1
                if line.strip() == heredoc_ends[0]:
                    heredoc_ends.pop(0)
                if i >= len(text):
                    break
            continue
        out.append(c)
        i += 1
    return "".join(out), substitutions


def _substitution_at(text: str, i: int) -> tuple[str | None, int]:
    """If a command substitution starts at `i`, return its inner text and end index."""
    if text[i] == "`":
        j = i + 1
        while j < len(text) and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        if j >= len(text):
            return None, i  # unclosed: leave it for shlex to report
        return text[i + 1:j], j + 1
    if text.startswith("$(", i) and not text.startswith("$((", i):  # $(( )) is arithmetic
        depth, j, quote = 1, i + 2, None
        while j < len(text):
            c = text[j]
            if quote:
                if c == quote:
                    quote = None
                elif c == "\\" and quote == '"':
                    j += 1
            elif c in "'\"":
                quote = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return text[i + 2:j], j + 1
            j += 1
        return None, i  # unclosed
    return None, i


# --- analysis ------------------------------------------------------------------------

def _analyse(command: str, depth: int) -> list[ShellAction]:
    found: list[ShellAction] = []
    cwd = ""  # directory changed into by an earlier `cd` in the same command
    commands, substitutions = _split(command)
    # Command substitutions run first, wherever they appear in the command.
    if depth < _MAX_DEPTH:
        for inner in substitutions:
            found += _analyse(inner, depth + 1)
    for words in commands:
        words, redirect_targets = _take_redirects(words)
        found += [ShellAction("write", _join(cwd, t)) for t in redirect_targets
                  if t not in ("/dev/null",)]
        found += [ShellAction("reads-secret-env", _join(cwd, t)) for t in redirect_targets
                  if _is_secret_env(t)]
        words = _unwrap(words)
        if not words:
            continue
        program, args = posixpath.basename(words[0]), words[1:]
        if program == "cd":
            target = args[0] if args else ""
            cwd = target if target.startswith(("/", "~")) else _join(cwd, target)
            continue
        if program in _SHELLS and depth < _MAX_DEPTH:
            script = _shell_c_argument(args)
            if script is not None:
                found += [_rebase(a, cwd) for a in _analyse(script, depth + 1)]
                continue
        found += [_rebase(a, cwd) for a in _program_actions(program, args, words[0] == "xargs")]
        if program not in ("echo", "printf"):
            found += [ShellAction("reads-secret-env", _join(cwd, w))
                      for w in args if not w.startswith("-") and _is_secret_env(w)]
    return found


def _take_redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """Remove redirects from `words`; return the remaining words and the write targets."""
    rest, targets, i = [], [], 0
    while i < len(words):
        w = words[i]
        if w in _REDIRECTS and i + 1 < len(words):
            targets.append(words[i + 1])
            i += 2
        elif w in (">&", "<", "<<", "<<<") and i + 1 < len(words):
            if w == "<":
                rest.append(words[i + 1])  # input files are still arguments (secret check)
            i += 2
        else:
            rest.append(w)
            i += 1
    return rest, targets


def _unwrap(words: list[str]) -> list[str]:
    """Skip VAR=value assignments and wrapper programs to reach the real program."""
    i, saw_xargs = 0, False
    while i < len(words):
        w = words[i]
        if "=" in w and not w.startswith("-") and re.match(r"^[A-Za-z_]\w*=", w):
            i += 1
            continue
        name = posixpath.basename(w)
        if name in _WRAPPERS:
            saw_xargs = saw_xargs or name == "xargs"
            i += 1
            takes_value = _WRAPPER_ARGS.get(name, set())
            while i < len(words) and (words[i].startswith("-") or
                                      (name == "env" and re.match(r"^[A-Za-z_]\w*=", words[i]))):
                i += 2 if words[i] in takes_value else 1
            if name == "time" and i < len(words) and words[i] == "-p":
                i += 1
            continue
        break
    rest = words[i:]
    # Mark commands run by xargs: their real arguments arrive on stdin.
    return (["xargs"] + rest) if saw_xargs and rest else rest


def _shell_c_argument(args: list[str]) -> str | None:
    """The string passed to `-c` (also in combined flags like `-lc`), if any."""
    for i, a in enumerate(args):
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and i + 1 < len(args):
            return args[i + 1]
    return None


def _program_actions(program: str, args: list[str], via_xargs: bool) -> list[ShellAction]:
    if program == "xargs":
        # `xargs rm -rf`: the real program follows; its targets come from stdin.
        if not args:
            return []
        inner = _program_actions(posixpath.basename(args[0]), args[1:], True)
        return inner
    positional = _positional(args)
    detail = "xargs" if via_xargs else ""

    if program == "tee":
        return [ShellAction("write", f) for f in positional]
    if program == "sed" and _has_in_place(args, "sed"):
        return [ShellAction("write", f) for f in _sed_files(args)]
    if program == "perl" and _has_in_place(args, "perl"):
        return [ShellAction("write", f) for f in _perl_files(args)]
    if program in ("cp", "install"):
        dest = _target_dir(args) or (positional[-1] if len(positional) >= 2 else None)
        if program == "install" and "-d" in args:
            return [ShellAction("write", f) for f in positional]
        return [ShellAction("write", dest, detail)] if dest or via_xargs else []
    if program == "mv":
        dest = _target_dir(args)
        sources = positional if dest else positional[:-1]
        dest = dest or (positional[-1] if len(positional) >= 2 else None)
        out = [ShellAction("move", s) for s in sources]
        return out + ([ShellAction("write", dest, detail)] if dest or via_xargs else [])
    if program in ("rm", "rmdir", "unlink", "shred"):
        out = [ShellAction("delete", f) for f in positional]
        if not positional and via_xargs:
            out.append(ShellAction("delete", None, "xargs"))
        if program == "rm" and _recursive_force(args):
            out.append(ShellAction("rm-recursive-force", None, detail))
        return out
    if program in ("touch", "mkdir"):
        return [ShellAction("write", f) for f in _positional(args, takes_value={"-m", "-r", "-d", "-t"})]
    if program == "truncate":
        return [ShellAction("write", f) for f in _positional(args, takes_value={"-s", "-r"})]
    if program == "ln":
        dest = _target_dir(args) or (positional[-1] if positional else None)
        return [ShellAction("write", dest)] if dest else []
    if program == "dd":
        return [ShellAction("write", a[3:]) for a in args if a.startswith("of=")]
    if program == "patch":
        return [ShellAction("write", None, "patch")]
    if program == "find":
        if "-delete" in args or any(a in ("-exec", "-execdir") and i + 1 < len(args)
                                    and posixpath.basename(args[i + 1]) == "rm"
                                    for i, a in enumerate(args)):
            return [ShellAction("delete", None, "find"), ShellAction("rm-recursive-force", None, "find")]
        return []
    if program == "git":
        return _git_actions(args)
    if program == "gh":
        if positional[:2] in (["pr", "create"], ["pr", "merge"]):
            return [ShellAction("pull-request")]
        return []
    if program == "hub" and positional[:1] == ["pull-request"]:
        return [ShellAction("pull-request")]
    if program == "claude":
        if any(a == "--settings" or a.startswith("--settings=") or "disableAllHooks" in a for a in args):
            return [ShellAction("hooks-disabled")]
        return []
    return []


def _git_actions(args: list[str]) -> list[ShellAction]:
    """git subcommands that change files, commit, push or move the hooks folder."""
    i, repo = 0, ""
    # Global options before the subcommand: -C <dir>, -c <key=value>, --flags.
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-C", "-c") and i + 1 < len(args):
            if args[i] == "-C":
                repo = _join(repo, args[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(args):
        return []
    sub, rest = args[i], args[i + 1:]
    positional = _positional(rest)
    if sub == "commit":
        return [ShellAction("git-commit")]
    if sub == "push":
        return [ShellAction("git-push")]
    if sub == "apply":
        return [ShellAction("write", repo or None, "patch")]
    if sub == "config":
        if any(a.lower() == "core.hookspath" for a in rest):
            return [ShellAction("hooks-path")]
        return []
    if sub == "reset" and "--hard" in rest:
        return [ShellAction("write", repo or None, "repo-wide")]
    if sub == "clean" and any(a.startswith("-") and not a.startswith("--") and "f" in a or a == "--force"
                              for a in rest):
        return [ShellAction("write", repo or None, "repo-wide")]
    if sub == "stash" and positional[:1] in (["pop"], ["apply"]):
        return [ShellAction("write", repo or None, "repo-wide")]
    if sub in ("checkout", "restore"):
        if "--" in rest:
            paths = rest[rest.index("--") + 1:]
        elif sub == "restore":
            paths = _positional(rest, takes_value={"-s", "--source"})
        else:
            paths = [p for p in positional if p == "."]
        out = []
        for p in paths:
            if p == ".":
                out.append(ShellAction("write", repo or None, "repo-wide"))
            else:
                out.append(ShellAction("write", _join(repo, p)))
        return out
    return []


# --- helpers -------------------------------------------------------------------------

def _positional(args: list[str], takes_value: set[str] = frozenset()) -> list[str]:
    """Arguments that aren't options; everything after `--` counts."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return out + args[i + 1:]
        if a.startswith("-") and a != "-":
            i += 2 if a in takes_value else 1
            continue
        out.append(a)
        i += 1
    return out


def _target_dir(args: list[str]) -> str | None:
    """The value of -t DIR / --target-directory=DIR (cp, mv, install, ln)."""
    for i, a in enumerate(args):
        if a == "-t" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--target-directory="):
            return a.split("=", 1)[1]
    return None


def _recursive_force(args: list[str]) -> bool:
    """Same rule as guard.py: rm with both a recursive and a force flag."""
    short = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    long_flags = {a for a in args if a.startswith("--")}
    recursive = "r" in short.lower() or "--recursive" in long_flags
    force = "f" in short or "--force" in long_flags
    return recursive and force


def _has_in_place(args: list[str], program: str) -> bool:
    for a in args:
        if a.startswith("--in-place"):
            return True
        if a.startswith("-") and not a.startswith("--") and "i" in a[1:]:
            # sed -i, -i.bak, -Ei; perl -i, -pi, -pi.bak
            return True
    return False


def _sed_files(args: list[str]) -> list[str]:
    """sed's file arguments: the script is the first positional unless -e/-f give it."""
    explicit_script = any(a in ("-e", "-f", "--expression", "--file") or
                          a.startswith(("--expression=", "--file=")) for a in args)
    positional = _positional(args, takes_value={"-e", "-f", "--expression", "--file", "-l"})
    # macOS sed takes the backup suffix as its own word: `sed -i '' 's/a/b/' f`.
    positional = [p for p in positional if p != ""]
    return positional if explicit_script else positional[1:]


def _perl_files(args: list[str]) -> list[str]:
    """perl's file arguments: skip options and the -e/-E code that follows them."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return out + args[i + 1:]
        if a.startswith("-") and a != "-":
            # "-e" or a bundle ending in e ("-pe", "-pie") takes the next word as code.
            i += 2 if a.rstrip("0123456789.bak").endswith(("e", "E")) else 1
            continue
        out.append(a)
        i += 1
    return out


def _is_secret_env(word: str) -> bool:
    name = posixpath.basename(word)
    return bool(_ENV_NAME.fullmatch(name)) and not name.endswith(_SAFE_ENV_SUFFIXES)


def _join(base: str, path: str) -> str:
    if not base or path.startswith(("/", "~")):
        return path
    return posixpath.normpath(posixpath.join(base, path))


def _rebase(action: ShellAction, cwd: str) -> ShellAction:
    """Join an action's relative target onto a directory changed into with `cd`."""
    if not cwd:
        return action
    if action.target is None:
        # A repo-wide or patch action after `cd x` happens in x.
        if action.kind == "write":
            return ShellAction(action.kind, cwd, action.detail)
        return action
    return ShellAction(action.kind, _join(cwd, action.target), action.detail)
