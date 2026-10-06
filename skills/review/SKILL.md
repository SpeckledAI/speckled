---
name: review
description: Architecture review of code changes or a design against the approved TDD, FRD and project constraints. Use when the human wants a second opinion on an implementation or a design before approving it.
argument-hint: "[task id | file | diff range | document id]"
---

# Architecture review

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the architect in `../../agents/architect.md`.
**Protocol:** `../../protocol/documents.md`.

1. Work out what to review from $ARGUMENTS. If nothing was given, review the uncommitted diff, or ask.
2. Load the governing documents: for code, the task, its TDD sections, FRD requirements, and `ARCH`; for a document, its parent.
3. Check, and report findings ranked by severity:
   1. **Correctness against the spec:** does it do what the task, TDD and FRD require, and nothing outside that scope?
   2. **Constraints:** is every constraint in `speckled.yaml` respected?
   3. **Security:** input validation, authorization, handling of secrets and personal data, injection risks.
   4. **Reliability and performance:** failure handling, idempotency, obvious inefficiencies.
   5. **Fit:** consistency with existing patterns in the codebase and with `ARCH`.
   6. **Tests:** do they actually verify the acceptance criteria?
4. For each finding give the location, what's wrong, a concrete scenario where it goes wrong, and the suggested fix. Say plainly if nothing significant was found.
5. Don't change code or documents yourself unless the human asks. The approval decision stays with the human.
