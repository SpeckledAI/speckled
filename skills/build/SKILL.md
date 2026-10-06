---
name: build
description: Implement one approved Speckled task together with the human, then hand it over for code review. Use when working through a task list.
argument-hint: "<task id, e.g. T-F07-03>"
---

# Build a task

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the engineer in `../../agents/dev.md`. You and the human are one development team.
**Protocol:** `../../protocol/documents.md`.

1. **Pick the task.** Task: $ARGUMENTS. If none was given, find the approved task lists, show the next Todo tasks whose dependencies are Done, and ask which one.
2. **Check the gate.** The task list must be `approved`, and every task this one depends on must be Done. If not, stop and explain what's blocking it. Continue only if the human explicitly says to, and record that override in your hand-off summary.
3. **Load context.** Read the task, the TDD sections and FRD requirements it cites, and the code it touches. Ask the human for anything else they want you to read.
4. **Clarify.** If anything is unclear, or the task conflicts with the real code, ask before writing code.
5. **Implement.** Stay within the task's scope and follow the codebase's patterns. Write the tests the task specifies. Run the project's lint and tests.
6. **Update status.** In the task list, set the task's status to `In review`. Never set it to Done.
7. **Hand off for review:**
   - What changed and why (by file).
   - How it was tested, with the results.
   - Anything that departs from the task or TDD, and why.
   - Open questions and follow-ups.
   - A suggested commit message that includes the task ID.
   Then ask the human to review. Once they've accepted the code, they record it with `/speckled:approve T-F<nn>-<kk>`.
