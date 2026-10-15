# Speckled Document Protocol

Every document Speckled produces follows these rules. Skills reference this file; read it before creating or editing any Speckled document.

## 1. Project configuration

Settings live in `speckled.yaml` at the root of the project's **planning repo** (created by `/speckled:init`; see §8). Read it first. If it is missing, stop and tell the user to run `/speckled:init`.

Key fields:

- `project` — the project name.
- `docs_dir` — where Speckled documents live, relative to the planning repo (default `docs`).
- `repos` — the code repositories this project spans (paths relative to the planning repo, or absolute). Code repos only; the planning repo is never listed.
- `constraints` — the project's firm rules. Every FRD, TDD and task list must show how it respects them.
- `roles` — who approves each gate (names or handles of humans).
- `enforcement`, `enforcement_exempt` — whether the approval gate is enforced in code (§8).

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

1. **Agents never approve.** Agents record approvals, set `approved` or `done`, or mark tasks Done only when a human runs `/speckled:approve`.
2. **Draft from approved parents only.** Before drafting an FRD, TDD or task list, check that the parent is `approved`. If it isn't, stop and say so. If the user explicitly tells you to go ahead anyway, continue and add this line directly under the title: `> ⚠️ Drafted from an unapproved parent (<parent id> v<version>, status <status>).`
3. **Hand-off.** When a draft is complete, set `status: in-review` and tell the user it's ready for them to approve with `/speckled:approve <id>`.
4. **Edits reopen review.** Changing the content of an `approved` document sets `status: in-review` and increments `version`. Keep the existing `approvals` entries; they record who approved which version.
5. **Staleness.** If a parent's current `version` is higher than a child's `parent_version`, the child may be out of date. Point this out whenever you notice it.
6. **Done.** A document becomes `done` when its work is complete (for example, every task in a task list is implemented and approved). Only a human marks work done, through `/speckled:approve`.
7. Humans commit. Agents never commit, push or open pull requests. They leave every change uncommitted in the working tree, list the changed files, suggest a commit message. The human reviews the diff and commits it. 

## 6. Constraints check

FRDs, TDDs and task lists end with a **Constraints Check** section. It lists each constraint from `speckled.yaml` and says how the document respects it, or "Not applicable" with a reason. Never quietly weaken a constraint. If a design needs an exception, record it as an open question for the human.

## 7. Traceability in code

Commits and PR titles made while implementing a task reference its ID, e.g. `feat(scanner): add universe filter [T-F07-03]`. Where a code comment explains why something exists, cite the feature or requirement (e.g. `// FRD-F07/FR3`) and the commit messages agents suggest for them.

## 8. Enforcement

With enforcement on, a hook checks every change an agent makes in code against the approved task it's working on. The checks run in code, not only in the agent's instructions.

### The planning repo

Plans live in a dedicated **planning repo** next to the code repos, never inside them, so they stay private even when the code is public. `speckled.yaml` sits at its root, `docs_dir` is inside it, and `repos` lists the code repos only. Sessions start in the planning repo, with each code repo added: `cd <planning repo> && claude --add-dir <code repo>`. A session started in a code repo can't change code or the gate's controls while enforcement is on.

### Settings

```yaml
enforcement: block          # off | warn | block; missing means off
enforcement_exempt:         # optional; patterns relative to each code repo's root
  - "*.lock"
```

- `off`: nothing is checked.
- `warn`: an action that breaks a **task rule** goes ahead; the agent is told, and the action is logged. An action that breaks a **hard rule** is still stopped and logged.
- `block`: an action that breaks any rule is stopped and logged, with a message saying what to do next.
- An unrecognised value counts as `block`.
- `enforcement_exempt` patterns use Python `fnmatch` on the file's path relative to its code repo, with forward slashes. `*` also matches `/`, so `docs/*` covers every file under `docs/`. Files that match are free to change without an active task. The default is no exemptions.

Agents can't change `speckled.yaml` while enforcement is on; the human edits it.

### What's checked

Every file a change touches falls into one of three groups:

- **Protected** (the gate's own controls): `speckled.yaml`, `.speckled/`, the planning repo's `.git/hooks/`, Claude Code settings files (`.claude/settings.json` and `.claude/settings.local.json` in the planning and code repos, and `~/.claude/settings.json`), git's `core.hooksPath` setting, and the plugin's own files and data folder. Agents never change these.
- **Governed** (code): any file in a listed code repo that isn't exempt. A change needs a valid **active task**: its task list is `approved`, the task is `In progress` or `In review`, and every task it depends on exists and is `Done`.
- **Free**: everything else, including documents in the planning repo.

Agents never commit, push or open pull requests, whatever the files.

### Rules

Every block or warning names one rule. **Hard** rules guard what only humans may do and the gate itself: they block in `warn` as well as `block`, and their message never suggests `warn`. **Task** rules guard agent code changes: `warn` lets them through and logs them, `block` stops them.

| Rule | Kind | Meaning |
|---|---|---|
| `config-unreadable` | hard | `speckled.yaml` or a task list can't be read. Code and protected files are blocked until a human fixes it. |
| `protected-path` | hard | The action would change one of the gate's controls. |
| `hooks-disabled-session` | hard | The action would start a Claude Code session with hooks switched off. |
| `git-commit`, `git-push`, `pull-request` | hard | Agents don't commit, push or open pull requests. |
| `wrong-start-folder` | task | The session started in a code repo instead of the planning repo, and the action changes code. |
| `no-active-task` | task | No task is active, or the active task isn't in any task list. |
| `task-list-not-approved` | task | The active task's list isn't `approved`. |
| `task-not-started` | task | The active task is `Todo`. |
| `task-done` | task | The active task is `Done`. |
| `dependency-not-done` | task | A task the active task depends on isn't `Done`. |
| `dependency-missing` | task | A task the active task depends on isn't in any task list. |

The safety guard's blocks also appear in the log, when enforcement is on, as `recursive-delete` (a recursive forced delete) and `secret-env-file` (access to a secret `.env` file). The guard blocks these whatever the mode, and with enforcement off too.

### `.speckled/` in the planning repo

| File | Committed | Contents |
|---|---|---|
| `.gitignore` | Yes | `active-task` and `*.tmp`. |
| `active-task` | No (per developer) | `{"v": 1, "task": "T-F07-03", "activated_at": "<UTC time>", "by": "<git user.name>", "files": ["tasks/F07-<slug>.md"]}`. Written only by `speckled-gate activate`, which `/speckled:build` runs. `files` lists the task lists (relative to `docs_dir`) that hold the task and its dependencies, so each check reads only those. It's a hint: if those files no longer hold the task or a dependency, every task list is read instead, and a marker without `files` works the same way. |
| `log.jsonl` | Yes | The enforcement log, one JSON object per line: every action allowed in `warn` mode and every block. Append-only. |

### Log format, version 1

```json
{"v": 1, "ts": "2026-10-08T14:03:11Z", "mode": "warn", "by": "alice",
 "tool": "Edit", "repo": "../app", "paths": ["src/main.py"],
 "task": "T-F07-03", "rule": "task-done", "agent": "main"}
{"v": 1, "ts": "2026-10-15T09:12:40Z", "mode": "block", "by": "alice",
 "tool": "Bash", "repo": "", "paths": [],
 "task": "T-F07-03", "rule": "git-commit", "agent": "main"}
```

- `v`: the format version. `ts`: UTC time. `mode`: the outcome, `warn` (allowed and logged) or `block` (stopped). `by`: `git config user.name`.
- `tool`: the tool the agent used. `repo`: the code repo as written in `repos`. `paths`: the files, relative to `repo`.
- `task`: the active task, or `null`. `rule`: one of the rules above, or one of the guard's. `agent`: `main`, or the subagent's type.
- Actions without file paths (commits, pushes, pull requests, the guard's shell blocks) have `repo: ""` and `paths: []`.
- Never logged: file contents, command text, email addresses or absolute paths.
- Adding a field or a rule value is a compatible change. Renaming or removing a field bumps `v`.

### Strict task format

The hook reads task lists, so each task's lines must keep this shape:

```markdown
### T-F07-03: Title
- **Depends on:** T-F07-01, T-F07-02
- **Status:** In progress
```

- A task is a `### T-Fnn-kk:` heading and everything up to the next `##` or `###` heading.
- `Status` is the first `- **Status:**` line in the task: exactly `Todo`, `In progress`, `In review` or `Done` (case doesn't matter). Any other value makes the list unreadable.
- `Depends on` is every task ID on the first `- **Depends on:**` line; other text, such as `none`, is ignored. A dependency can be in another feature's task list.
- Task lists are the `.md` files in `<docs_dir>/tasks/` and `<docs_dir>/tasks/completed/` with `type: tasks` in their front matter.

### YAML

`speckled.yaml` and front matter are read as standard YAML, with one difference: values such as `off`, `yes` and dates (`2026-10-08`) stay text instead of becoming booleans or dates. Quote any other value that must stay text, such as a name that looks like a number or `null`.
