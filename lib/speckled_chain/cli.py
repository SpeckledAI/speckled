"""The `lint-chain` command line.

Why this module exists:
    `lint-chain` is how a human, or CI, checks the planning repo's record. This module
    turns arguments into a call to `lint()` and the report into output and an exit code.
    The checks themselves live in the package; the library API and the command always
    give the same findings.

What it does:
    - Finds the project: `--project DIR`, or the nearest folder upward from here that
      holds `speckled.yaml`.
    - Prints the text report, or JSON with `--json`. `--output FILE` also writes the
      JSON report; it's the only thing the command ever writes.
    - `--explain RULE` prints a rule's meaning and fix.

Exit codes: 0 no errors; 1 an error (or, with `--strict`, any finding); 2 couldn't run
(no `speckled.yaml`, an unusable config, git missing or failing, a read or write
failure); 64 usage error, as in
`speckled-gate`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import lint
from .config import ConfigError
from .history import GitError
from .rules import RULES, explain

USAGE_ERROR = 64
CANT_RUN = 2


class _Parser(argparse.ArgumentParser):
    """argparse, but usage errors exit with 64 (EX_USAGE) instead of 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(USAGE_ERROR, f"{self.prog}: error: {message}\n")


def _feature(value: str) -> str:
    if not re.fullmatch(r"F\d{2,}", value):
        raise argparse.ArgumentTypeError(f"expected a feature such as F08, not {value!r}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="lint-chain",
                     description="Check a Speckled planning repo's documents, approvals and history.")
    parser.add_argument("--project", metavar="DIR", help="the planning repo to check (skips looking upward)")
    parser.add_argument("--docs", action="store_true", help="only the checks that need no git history")
    parser.add_argument("--feature", metavar="Fnn", type=_feature, help="only this feature's documents and tasks")
    parser.add_argument("--json", action="store_true", help="print the JSON report instead of text")
    parser.add_argument("--output", metavar="FILE", help="also write the JSON report to FILE")
    parser.add_argument("--strict", action="store_true", help="warnings count as errors for the exit code")
    parser.add_argument("--explain", metavar="RULE", help="print a rule's meaning and how to fix it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.explain is not None:
        return _explain(args.explain)

    root = _find_root(args.project)
    if root is None:
        return CANT_RUN
    try:
        report = lint(root, history=not args.docs, feature=args.feature)
    except (ConfigError, GitError) as e:
        return _cant_run(str(e))
    except OSError as e:
        return _cant_run(str(e))

    document = report.to_json()
    if args.json:
        print(json.dumps(document, indent=2))
    else:
        sys.stdout.write(report.render_text(color=sys.stdout.isatty()))
    if args.output:
        try:
            Path(args.output).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            return _cant_run(f"couldn't write {args.output}: {e.strerror or e}")
    return report.exit_code(strict=args.strict)


def _explain(rule_id: str) -> int:
    try:
        sys.stdout.write(explain(rule_id))
    except KeyError:
        print(f"lint-chain: unknown rule {rule_id!r}. Rules: {', '.join(RULES)}.", file=sys.stderr)
        return USAGE_ERROR
    return 0


def _find_root(project: str | None) -> Path | None:
    """The planning repo's folder, or None after printing why there isn't one."""
    if project is not None:
        root = Path(project)
        if (root / "speckled.yaml").is_file():
            return root
        _cant_run(f"no speckled.yaml in {root}.")
        return None
    start = Path(os.getcwd())
    for folder in (start, *start.parents):
        if (folder / "speckled.yaml").is_file():
            return folder
    _cant_run(f"no speckled.yaml in {start} or its parents. Run it from the planning repo.")
    return None


def _cant_run(reason: str) -> int:
    print(f"lint-chain: {reason}", file=sys.stderr)
    return CANT_RUN


if __name__ == "__main__":
    sys.exit(main())
