"""The rules `lint-chain` reports, and how to fix each one.

Why this module exists:
    Every finding names one rule, and protocol §9 documents them. Keeping the list
    in code, rather than parsing the protocol at run time, means the plugin's Markdown
    is never a runtime input. `tests/chain/test_documentation.py` fails if this list
    and protocol §9's table disagree, so the two can't drift [T-F08-03].

What it does:
    - `RULES` maps each rule ID to its `Rule`, in the protocol table's order.
      `severity` is the default; a check passes another severity where the protocol
      says so (`parent-unapproved`, `history-unavailable`).
    - `meaning` is the rule's Meaning cell in protocol §9, word for word.
    - `explain(rule_id)` is the text `lint-chain --explain <rule>` prints.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # "error" or "warning": the default
    meaning: str
    fix: str


def _rules(*rows: tuple[str, str, str, str]) -> dict[str, Rule]:
    return {row[0]: Rule(*row) for row in rows}


RULES: dict[str, Rule] = _rules(
    ("front-matter", "error",
     "Front matter missing, unreadable, missing a required field, or with an invalid value.",
     "Add or correct the front matter so it has every field protocol §4 requires for its `type`, "
     "each with a valid value."),
    ("bad-id", "error",
     "A document or task ID isn't well-formed, doesn't match its `type` or `feature`, "
     "or a task ID belongs to another feature.",
     "Use the ID shape protocol §3 gives for the document's `type`, with the document's own feature number."),
    ("duplicate-id", "error",
     "Two documents have the same `id`.",
     "Give each document its own `id`. If one file is an accidental copy, keep only the original."),
    ("file-name", "error",
     "The file isn't where its `id` and `type` say it should be.",
     "Move or rename the file to the path protocol §4 gives for its `id` and `type`."),
    ("unknown-feature", "error",
     "An FRD, TDD or task list names a feature that isn't a `### Fnn:` heading in the PDRD.",
     "Add the feature to the PDRD as a `### Fnn: <name>` heading, or correct the document's `feature`."),
    ("task-format", "error",
     "The task list breaks the strict task format, or an `Approved by` line isn't "
     "`Approved by <name> on <YYYY-MM-DD>` with an optional `(<note>)`.",
     "Follow the strict task format (protocol §8), and write approvals as "
     "`Approved by <name> on <YYYY-MM-DD>`, optionally followed by `(<note>)`."),
    ("duplicate-task", "error",
     "A task ID appears in more than one task list.",
     "Keep each task in one task list, with an ID from that list's feature."),
    ("dependency-missing", "error",
     "A `Depends on` ID isn't a task in any list.",
     "Correct the ID in `Depends on`, or add the missing task."),
    ("dependency-cycle", "error",
     "Tasks depend on each other in a cycle. Reported once, on the cycle's lowest task ID.",
     "Remove one of the dependencies so the tasks can be done in order."),
    ("parent-missing", "error",
     "No `parent`, or no document has that ID.",
     "Set `parent` to the ID the protocol §4 table gives for this `type`, and check that document exists."),
    ("parent-wrong-type", "error",
     "The parent isn't the expected kind or feature (§4 table).",
     "Set `parent` to the expected document: `BRIEF` for the PDRD, `PDRD` for an FRD, "
     "and the same feature's FRD or TDD for a TDD or task list."),
    ("parent-unapproved", "error",
     "The parent isn't `approved` or `done`, and has no `approvals` entries.",
     "Approve the parent first. To go ahead anyway, add the protocol §5 rule 2 line under the title, "
     "which makes this a warning."),
    ("parent-reopened", "warning",
     "The parent was approved before (it has `approvals` entries) but is now `draft`, "
     "`in-review` or `superseded`.",
     "Once the parent is approved again, check that this document still matches it."),
    ("approver-not-listed", "error",
     "An `approvals` entry's `by` isn't under `roles.<role>`, or an `Approved by` name isn't "
     "under `roles.code`, as of the commit that added it.",
     "List the approver under that gate in `roles` in `speckled.yaml`, or have a listed approver "
     "record a new approval. Never edit the existing one."),
    ("approval-role-mismatch", "error",
     "An entry's `role` isn't the gate for the document's `type`.",
     "Record a new approval whose `role` is the gate for this document's `type`."),
    ("gate-without-approvers", "warning",
     "Approvals were recorded on a gate that has no `roles` entry in `speckled.yaml`, so their "
     "approvers can't be checked. One finding per gate, naming how many approvals it covers; the fix "
     "is to add the gate under `roles`. Those approvals aren't reported as `approver-not-listed`.",
     "Add the gate under `roles` in `speckled.yaml`, listing who may approve it."),
    ("approval-edited", "error",
     "A committed `approvals` entry or `Approved by` line was changed or reordered.",
     "Restore the original entry; record a new approval instead of editing one."),
    ("approval-removed", "error",
     "A committed `approvals` entry or `Approved by` line was removed.",
     "Restore the removed entry. Approvals are only ever added."),
    ("document-deleted", "error",
     "A committed document was deleted, not moved.",
     "Restore the document. To retire it, change its `status` and move it, for example into `completed/`."),
    ("edited-without-review", "error",
     "A commit changed an approved or done document's content without reopening review or "
     "recording a new approval (§5 rule 4).",
     "Raise `version` and set `status` to `in-review` or `draft`, or record an approval for the "
     "new version in the same commit."),
    ("log-edited", "error",
     "A committed line of `.speckled/log.jsonl` was changed or removed.",
     "Restore the log's committed lines. The log is only ever appended to."),
    ("log-malformed", "error",
     "A log line isn't valid log format v1.",
     "Restore the line as the gate wrote it. Protocol §8 describes log format v1."),
    ("warn-event", "warning",
     "An action the gate allowed in `warn` mode.",
     "Check the action was intended; nothing needs changing. To stop such actions, "
     "set `enforcement: block` in `speckled.yaml`."),
    ("history-unavailable", "error",
     "History checks couldn't run.",
     "Run it in a git checkout of the planning repo with its full history; in CI, check out with "
     "`fetch-depth: 0`. Outside a git repository this is a warning, and in a shallow clone an error."),
)


def explain(rule_id: str) -> str:
    """The text `--explain` prints. Raises KeyError for an unknown rule."""
    rule = RULES[rule_id]
    return (f"{rule.id} (default severity: {rule.severity})\n\n"
            f"{rule.meaning}\n\n"
            f"Fix: {rule.fix}\n")
