---
name: approve
description: Record a human approval of a Speckled document or task (brief, PDRD, FRD, TDD, task list, or an individual task's code). Only runs when the human invokes it.
argument-hint: "<document id or task id> [note]"
disable-model-invocation: true
---

# Record an approval

Paths in this skill are relative to its base directory. The Speckled root is `../..`. Read `../../protocol/documents.md`.

This command is how a **human** records a decision. The human invoking it is the approval. Never run it on your own initiative, and never treat anything other than the human typing this command as approval.

Target: $ARGUMENTS

1. **Find the target.** A document ID (`BRIEF`, `PDRD`, `ARCH`, `FRD-F07`, `TDD-F07`, `TASKS-F07`) or a task ID (`T-F07-03`). If nothing was given, list the documents and tasks that are `in-review` and ask which one.
2. **Who is approving?** Use `git config user.name`. If `speckled.yaml` lists approvers for this gate and that person isn't one of them, warn the human and ask them to confirm before recording.
3. **Show what's being approved:** the ID, title and version, and for a task, the files changed. Point out anything that should block approval:
   - status isn't `in-review`
   - the parent isn't approved, or is newer than `parent_version`
   - Open Questions still unanswered
   - an empty Constraints Check
   Ask the human to confirm.
4. **Record it.**
   - **Document:** set `status: approved`, update `updated`, and append to `approvals`:
     `{by: <name>, role: <gate>, date: <YYYY-MM-DD>, version: <version>, note: "<note, if given>"}`
   - **Task:** in its task list, set the task's status to `Done`, and add a line under the task: `Approved by <name> on <date>`. If every task is now Done, ask whether to set the task list to `done` and move the feature's documents to `completed/`.
5. **Confirm** in one line, and name the next step in the pipeline.
6. **Don't commit**: leave the change for the human to review and commit, and suggest a commit message.
