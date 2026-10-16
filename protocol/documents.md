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

The `lint-chain` command checks a planning repo against the rules in this file; §9 lists what it checks.

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
  - A feature number `Fnn` is `F` followed by two or more digits (`F07`, `F123`).
  - The PDRD lists each feature as a heading `### Fnn: <name>`, for example `### F07: Market Scanning`. These headings are the project's features; an FRD, TDD or task list may only name one of them.
- **Documents** take their feature's number: `FRD-F07`, `TDD-F07`, `TASKS-F07`. The brief is `BRIEF`, the PDRD is `PDRD`, the architecture document is `ARCH`.
- **Research notes** (`type: research`) have free-form IDs. Their `id` isn't checked for format or matched against the file name.
- **Tasks** are numbered in dependency order within their list: `T-F07-01`, `T-F07-02`, … The number after the feature is two or more digits, and the feature is the list's own.
- **Requirements** in an FRD are `FR1…`/`NFR1…`, cited from elsewhere as `FRD-F07/FR3`.
- File names: `frds/Fnn-<slug>.md`, `tdds/Fnn-<slug>.md`, `tasks/Fnn-<slug>.md`, where `<slug>` is `[a-z0-9]+(-[a-z0-9]+)*` (lowercase words joined by single hyphens, such as `market-scanning`). §4 lists every document's expected path.

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

Every document has `id`, `title`, `type`, `status`, `version`, `updated` and `approvals`. Each `type` adds the fields below and fixes its `id`, path and `parent`. Paths are relative to `docs_dir`, and each may also sit under a `completed/` subfolder (§2), for example `frds/completed/F07-market-scanning.md`.

| `type` | Required fields beyond `id, title, type, status, version, updated, approvals` | Expected `id` | Expected path | Expected `parent` |
|---|---|---|---|---|
| `brief` | — | `BRIEF` | `brief.md` | none |
| `pdrd` | `parent`, `parent_version` | `PDRD` | `pdrd.md` | `BRIEF` |
| `arch` | — | `ARCH` | `architecture.md` | none |
| `research` | — | any (not checked) | `research/*.md` | none (not checked) |
| `frd` | `feature`, `parent`, `parent_version` | `FRD-Fnn` | `frds/Fnn-<slug>.md` | `PDRD` |
| `tdd` | `feature`, `parent`, `parent_version` | `TDD-Fnn` | `tdds/Fnn-<slug>.md` | `FRD-Fnn` |
| `tasks` | `feature`, `parent`, `parent_version` | `TASKS-Fnn` | `tasks/Fnn-<slug>.md` | `TDD-Fnn` |

Field and value rules:

- `Fnn` is the same in `feature`, the `id` and the file name (§3).
- `status` is one of `draft`, `in-review`, `approved`, `done` or `superseded`.
- `version` and `parent_version` are whole numbers of 1 or more.
- `updated` and `approvals[].date` are dates written `YYYY-MM-DD`.
- Each `approvals` entry has `by`, `role`, `date` and `version`, and may have a `note`:

  ```yaml
  approvals:
    - {by: alice, role: tdd, date: 2026-10-01, version: 2}
  ```

  `role` is the gate for the document's `type` (the key under `roles` in `speckled.yaml`), and `version` is the document version that was approved.

## 5. Status rules (the gates)

1. **Agents never approve.** Agents record approvals, set `approved` or `done`, or mark tasks Done only when a human runs `/speckled:approve`.
2. **Draft from approved parents only.** Before drafting an FRD, TDD or task list, check that the parent is `approved`. If it isn't, stop and say so. If the user explicitly tells you to go ahead anyway, continue and add this line directly under the title: `> ⚠️ Drafted from an unapproved parent (<parent id> v<version>, status <status>).`
3. **Hand-off.** When a draft is complete, set `status: in-review` and tell the user it's ready for them to approve with `/speckled:approve <id>`.
4. **Edits reopen review.** Changing the content of an `approved` or `done` document sets `status: in-review` (or `draft`) and increments `version`. Keep the existing `approvals` entries; they record who approved which version. The content is the body, everything after the front matter. These changes don't count as changing it:
   - **Task progress** in a task list: a task's `- **Status:**` value, a table cell whose whole value is a task status, and `Approved by` lines (§9). Example: moving `T-F07-03` from `In review` to `Done` and adding `Approved by alice on 2026-10-02`.
   - **An edit and its re-approval in the same commit**: `version` goes up and an `approvals` entry for the new version is appended, so the document can stay `approved`. Example: fixing a requirement in `FRD-F07` v2 and committing it as v3 with alice's v3 approval.
   - **Whitespace-only changes**: runs of spaces, tabs and line breaks count as one space. Example: rewrapping a paragraph without changing a word.
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

## 9. Chain checks

`lint-chain` reads the planning repo and its git history and reports where the record breaks these rules. It only reads, and it blocks nothing. Each finding names one rule from the table below.

### Which files are documents

- `brief.md`, `pdrd.md` and `architecture.md` in `docs_dir`.
- Every `.md` file in `research/`, `frds/`, `tdds/` and `tasks/`, and in a `completed/` subfolder of any of them or of `docs_dir`.

A file in one of these places without front matter is a `front-matter` error. Other `.md` files in `docs_dir` are ignored if they have no front matter. Symlinks are skipped.

### Expected parents

Each document's `parent` is the one the §4 table gives for its `type`: the PDRD's is `BRIEF`, an FRD's is `PDRD`, and a TDD's or task list's is the FRD or TDD of the same feature. The brief and `ARCH` have no parent, and research notes' parents aren't checked.

A parent counts as approved if its `status` is `approved` or `done`, or if it has at least one `approvals` entry. A child of a parent that was never approved is an error, unless the child carries the §5 rule 2 line, which makes it a warning.

### The `Approved by` line

When a human approves a task's code, `/speckled:approve` adds this line inside the task's block (§8, Strict task format), on a line of its own:

```markdown
Approved by alice on 2026-10-02
```

The shape is exactly `Approved by <name> on <YYYY-MM-DD>`. A line inside a task that starts `Approved by` and doesn't match it is a `task-format` error.

### Approvers

- An `approvals` entry's `by` is listed under `roles.<role>` in `speckled.yaml`, and its `role` is the gate for the document's `type`.
- An `Approved by` name is listed under `roles.code`.
- Each entry is checked against `roles` as it stood in the commit that added it, so removing an approver later doesn't invalidate their past approvals. An entry that isn't committed yet is checked against the current `roles`.
- If approvals are recorded on a gate that has no `roles` entry, their names can't be checked. That's one `gate-without-approvers` warning per gate, not an error per approval.

### Append-only rules

- `approvals` entries and `Approved by` lines are never changed, reordered or removed once committed. New ones are added at the end.
- Documents are moved (for example into `completed/`), never deleted. A document is tracked by its `id` across moves and renames, so a path that disappears is a deletion only if no file in that commit still has that `id`. Research notes and files without a readable `id` are tracked by path.
- Lines of `.speckled/log.jsonl` are never changed or removed.

These rules hold across the planning repo's history and from the last commit to the working tree. Each commit is compared with its parent, and a merge with its first parent. History can't be checked in a shallow clone, so CI needs a full checkout.

### Rules

| Rule | Severity | Meaning |
|---|---|---|
| `front-matter` | error | Front matter missing, unreadable, missing a required field, or with an invalid value. |
| `bad-id` | error | A document or task ID isn't well-formed, doesn't match its `type` or `feature`, or a task ID belongs to another feature. |
| `duplicate-id` | error | Two documents have the same `id`. |
| `file-name` | error | The file isn't where its `id` and `type` say it should be. |
| `unknown-feature` | error | An FRD, TDD or task list names a feature that isn't a `### Fnn:` heading in the PDRD. |
| `task-format` | error | The task list breaks the strict task format, or an `Approved by` line isn't `Approved by <name> on <YYYY-MM-DD>`. |
| `duplicate-task` | error | A task ID appears in more than one task list. |
| `dependency-missing` | error | A `Depends on` ID isn't a task in any list. |
| `dependency-cycle` | error | Tasks depend on each other in a cycle. Reported once, on the cycle's lowest task ID. |
| `parent-missing` | error | No `parent`, or no document has that ID. |
| `parent-wrong-type` | error | The parent isn't the expected kind or feature (§4 table). |
| `parent-unapproved` | error, or warning with the rule-2 line | The parent isn't `approved` or `done`, and has no `approvals` entries. |
| `parent-reopened` | warning | The parent was approved before (it has `approvals` entries) but is now `draft`, `in-review` or `superseded`. |
| `approver-not-listed` | error | An `approvals` entry's `by` isn't under `roles.<role>`, or an `Approved by` name isn't under `roles.code`, as of the commit that added it. |
| `approval-role-mismatch` | error | An entry's `role` isn't the gate for the document's `type`. |
| `gate-without-approvers` | warning | Approvals were recorded on a gate that has no `roles` entry in `speckled.yaml`, so their approvers can't be checked. One finding per gate, naming how many approvals it covers; the fix is to add the gate under `roles`. Those approvals aren't reported as `approver-not-listed`. |
| `approval-edited` | error | A committed `approvals` entry or `Approved by` line was changed or reordered. |
| `approval-removed` | error | A committed `approvals` entry or `Approved by` line was removed. |
| `document-deleted` | error | A committed document was deleted, not moved. |
| `edited-without-review` | error | A commit changed an approved or done document's content without reopening review or recording a new approval (§5 rule 4). |
| `log-edited` | error | A committed line of `.speckled/log.jsonl` was changed or removed. |
| `log-malformed` | error | A log line isn't valid log format v1. |
| `warn-event` | warning | An action the gate allowed in `warn` mode. |
| `history-unavailable` | warning (no git repo); error (shallow clone) | History checks couldn't run. |

`lint-chain --explain <rule>` prints a rule's meaning and how to fix it.

### A valid log line

A line of `.speckled/log.jsonl` is valid log format v1 (§8) if it's a JSON object with:

- `v` equal to `1`;
- `ts`: a string `YYYY-MM-DDTHH:MM:SSZ`;
- `mode`: `warn` or `block`;
- `by`, `tool`, `repo` and `agent`: strings;
- `paths`: a list of strings;
- `task`: a string or `null`;
- `rule`: a non-empty string. It isn't checked against §8's list, so a log written by a newer gate stays valid.

Extra fields are allowed. `block` lines are valid and aren't reported; each `warn` line is a `warn-event` warning.

### Report JSON, schema 1

`lint-chain --json` prints, and `--output <file>` writes:

```json
{
  "schema": 1,
  "tool": "lint-chain",
  "plugin_version": "0.4.0",
  "project": "example",
  "history": "full",
  "summary": {"documents": 24, "commits": 112, "errors": 1, "warnings": 1, "warn_events": 1},
  "findings": [
    {"rule": "approval-edited", "severity": "error", "subject": "FRD-F07",
     "file": "docs/frds/F07-market-scanning.md", "line": 14,
     "commit": "a1b2c3d4e5f6...", "by": "alice", "date": "2026-10-12",
     "message": "FRD-F07: approval 2 (alice, v2) was changed in a1b2c3d.",
     "fix": "Restore the original entry; record a new approval instead of editing one."}
  ]
}
```

- `project` is `project` from `speckled.yaml`. `plugin_version` is the plugin's version.
- `history` is `full`, `none` (not a git repo, or `--docs`) or `shallow`.
- `subject` is a document or task ID. For a file without a readable ID, it's the file path.
- `file` is relative to the planning repo, with forward slashes. `line` is 1-based, or `null`.
- `commit` (the full SHA), `by` and `date` appear only on findings from history. `by` is a git author or approver name, never an email address.
- Adding a field or a rule is a compatible change. Renaming or removing one bumps `schema`.

### What messages may quote

A finding's message may quote short structured values: front-matter fields other than `title`, task statuses, IDs and approver names, for example `unknown status 'Doing'`. It never quotes body text or titles. The report never contains email addresses or absolute paths, so it can be stored or shared without the documents' contents.
