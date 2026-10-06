# Speckled Document Protocol

Every document Speckled produces follows these rules. Skills reference this file; read it before creating or editing any Speckled document.

## 1. Project configuration

Settings live in `speckled.yaml` at the project root (created by `/speckled:init`). Read it first. If it is missing, stop and tell the user to run `/speckled:init`.

Key fields:

- `project` — the project name.
- `docs_dir` — where Speckled documents live (default `docs`).
- `repos` — the code repositories this project spans (paths relative to the project root, or absolute).
- `constraints` — the project's firm rules. Every FRD, TDD and task list must show how it respects them.
- `roles` — who approves each gate (names or handles of humans).

## 2. Layout

```
<docs_dir>/
  brief.md            # Project brief
  research/           # Market / competitor research
  pdrd.md             # Product Development Roadmap Document (source of truth)
  architecture.md     # Current-state architecture (what exists, not what's planned)
  frds/               # Feature Requirements Documents
  tdds/               # Technical Design Documents
  tasks/              # Development task lists
```

When a document's work is finished, move it into a `completed/` subfolder next to where it lives. Never delete or renumber it; it's part of the historical record.

## 3. Identifiers

- **Features** are numbered in the PDRD as `F01`, `F02`, … **Feature numbers are permanent.** Phases can be reordered, and features can be deferred or cut, but a number is never reused or changed, because FRDs, TDDs, tasks, commits and code comments refer to it.
- **Documents** take their feature's number: `FRD-F07`, `TDD-F07`, `TASKS-F07`. The brief is `BRIEF`, the PDRD is `PDRD`, the architecture document is `ARCH`.
- **Tasks** are numbered in dependency order within their list: `T-F07-01`, `T-F07-02`, …
- **Requirements** in an FRD are `FR1…`/`NFR1…`, cited from elsewhere as `FRD-F07/FR3`.
- File names: `frds/F07-<slug>.md`, `tdds/F07-<slug>.md`, `tasks/F07-<slug>.md`.

## 4. Front matter

Every document starts with YAML front matter:

```yaml
---
id: TDD-F07
title: Market Scanning
type: tdd                # brief | research | pdrd | arch | frd | tdd | tasks
feature: F07             # omit for brief, research, pdrd, arch
parent: FRD-F07          # the approved document this one was derived from
parent_version: 2        # the parent's version at the time this was drafted
status: draft            # draft | in-review | approved | done | superseded
version: 1
updated: 2026-09-30
approvals: []            # written ONLY by /speckled:approve
---
```

## 5. Status rules (the gates)

1. **Agents never approve.** No agent may set `status: approved` or write to `approvals`. Only `/speckled:approve`, run by a human, does that.
2. **Draft from approved parents only.** Before drafting an FRD, TDD or task list, check that the parent is `approved`. If it isn't, stop and say so. If the user explicitly tells you to go ahead anyway, continue and add this line directly under the title: `> ⚠️ Drafted from an unapproved parent (<parent id> v<version>, status <status>).`
3. **Hand-off.** When a draft is complete, set `status: in-review` and tell the user it's ready for them to approve with `/speckled:approve <id>`.
4. **Edits reopen review.** Changing the content of an `approved` document sets `status: in-review` and increments `version`. Keep the existing `approvals` entries; they record who approved which version.
5. **Staleness.** If a parent's current `version` is higher than a child's `parent_version`, the child may be out of date. Point this out whenever you notice it.
6. **Done.** A document becomes `done` when its work is complete (for example, every task in a task list is implemented and approved). Only a human marks work done, through `/speckled:approve`.

## 6. Constraints check

FRDs, TDDs and task lists end with a **Constraints Check** section. It lists each constraint from `speckled.yaml` and says how the document respects it, or "Not applicable" with a reason. Never quietly weaken a constraint. If a design needs an exception, record it as an open question for the human.

## 7. Traceability in code

Commits and PR titles made while implementing a task reference its ID, e.g. `feat(scanner): add universe filter [T-F07-03]`. Where a code comment explains why something exists, cite the feature or requirement (e.g. `// FRD-F07/FR3`).
