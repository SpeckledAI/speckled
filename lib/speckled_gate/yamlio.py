"""Read speckled.yaml and document front matter.

Why this module exists:
    The hook for the gate that enforces approvals has to read two kinds of YAML before it can decide anything:
    `speckled.yaml` top level speckled config (enforcement mode, repos, roles) and the front matter at the top
    of every Speckled document (status, version, approvals). Python's standard
    library has no YAML parser, and a plugin has no install step, so PyYAML is
    bundled, unmodified, under `_vendor/yaml` (see `_vendor/README.md`). Every other
    part of the gate reads YAML through `loads()` here, never through PyYAML directly.

What it does:
    - Loads YAML safely: plain data only (mappings, lists, strings, numbers). Tags that
      would build Python objects, such as `!!python/object`, are refused.
    - Keeps values as their author wrote them. By default PyYAML turns `yes`, `no`,
      `on` and `off` into True/False and `2026-10-08` into a date object. That would
      make `enforcement: off` read as False, and dates compare differently from the
      strings Speckled writes. Both conversions are switched off. Integers and floats
      are still read as numbers (`version: 4` is 4).
    - Requires the top level to be a mapping, because every Speckled file is one.
    - Reports problems as `YamlError(line, reason)`, so a message can point the human
      to the exact line to fix.
"""
from __future__ import annotations

# The bundled copy, never a `yaml` module installed on the user's machine, so the
# gate behaves the same everywhere.
from ._vendor import yaml

# PyYAML's tags for the two conversions we switch off (see the module docstring).
_KEEP_AS_TEXT = {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}


class YamlError(ValueError):
    """A file couldn't be read. `line` is 1-based; `reason` says what's wrong there."""

    def __init__(self, line: int, reason: str):
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason


class _Loader(yaml.SafeLoader):
    """SafeLoader without the bool and timestamp resolvers."""


# A resolver decides which type a plain value becomes (for example "off" -> bool).
# Give _Loader its own copy of SafeLoader's table without the two we don't want, so
# SafeLoader itself is left untouched.
_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag not in _KEEP_AS_TEXT]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def loads(text: str) -> dict:
    """Parse `text` and return the top-level mapping (`{}` for an empty document)."""
    try:
        data = yaml.load(text, Loader=_Loader)
    except yaml.MarkedYAMLError as e:
        # PyYAML marks are 0-based; the problem mark is where parsing failed, and the
        # context mark (when present) is where the broken construct started.
        mark = e.problem_mark or e.context_mark
        line = mark.line + 1 if mark else 1
        raise YamlError(line, e.problem or e.context or "invalid YAML") from None
    except yaml.YAMLError as e:
        raise YamlError(1, str(e)) from None
    if data is None:
        # An empty file, or one with only comments.
        return {}
    if not isinstance(data, dict):
        raise YamlError(1, "the document must be a mapping, not a list or a single value")
    return data
