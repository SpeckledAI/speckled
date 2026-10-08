---
name: tasks
description: Break an approved TDD into small, dependency-ordered development tasks, each with steps, tests, and acceptance criteria, that an engineer or AI agent can implement and a human can review in one sitting.
argument-hint: "<feature id, e.g. F07>"
---

# Task breakdown

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the planner in `../../agents/planner.md`. You never modify application code.
**Template:** `../../templates/tasks.md` → `<docs_dir>/tasks/F<nn>-<slug>.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.
**Parent:** `TDD-F<nn>` (must be approved).

1. Feature: $ARGUMENTS. Accept a feature ID (`F07`) or any of its document IDs (`FRD-F07`, `TDD-F07`, `TASKS-F07`), and use the feature number. If none was given, list the approved TDDs that don't have a task list yet, and ask which one.
2. Read the TDD, its FRD, `ARCH`, and the code in the affected repos.
3. Ask the human to clarify anything ambiguous in the TDD.
4. Draft the tasks: in dependency order, one concern each, backend, frontend and integration kept separate, work only a human can do assigned to a human, and every TDD section covered.
5. Hand off for approval. Next step: `/speckled:build T-F<nn>-01`.
