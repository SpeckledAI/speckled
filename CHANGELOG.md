# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-10-25

`lint-chain` checks a planning repo's record: that documents are well-formed, each was drafted from an approved parent, approvals were made by listed approvers and only ever added, approved documents weren't changed without a new review, and the enforcement log was only appended to. It reads the repo and its git history and changes nothing. A GitHub Action runs it in CI. From this release, every release is tagged `vX.Y.Z`.

### Added
- `bin/lint-chain`, the command, with `--docs`, `--feature`, `--json`, `--output`, `--strict` and `--explain`, and exit codes `0`, `1`, `2` and `64`. [T-F08-03] [T-F08-12]
- `speckled_chain`, a standard-library Python package with the checks, usable as a library (`lint`, `load_corpus`, `chain_for`). It reads `speckled.yaml` and front matter with the bundled PyYAML. [T-F08-03] [T-F08-05] [T-F08-06] [T-F08-07] [T-F08-12]
- Checks of the history: approvals and `Approved by` lines only ever added, approvers listed as of the commit that added them, documents moved rather than deleted, and edits to approved documents reviewed again. History is read with one `git log` and one `git cat-file` process. [T-F08-08] [T-F08-09] [T-F08-10]
- Checks of `.speckled/log.jsonl`: lines never changed or removed, every line valid log format v1, and each `warn` line reported. [T-F08-11]
- The `lint-chain` GitHub Action (`actions/lint-chain`), a composite action that needs no token, with a CI job that runs it on a seeded fault and on the fix. [T-F08-13]
- Protocol §9 Chain checks: which files are documents, expected parents, the `Approved by` line, approvers, the append-only rules, every rule, a valid log line, and the JSON report. [T-F08-01]
- Test fixtures that build planning repos with real git history, and a performance test on 50 documents and 500 commits. [T-F08-04] [T-F08-14]

### Changed
- Protocol §3 and §4: how the PDRD lists features, which folders hold documents, and that research note IDs are free-form. §5 rule 4 says which changes don't count as editing an approved document: task progress, an edit re-approved in the same commit, and whitespace. [T-F08-01]
- `speckled_gate` parses each task's `Approved by` lines, including an optional note in brackets. The gate's behaviour is unchanged: a malformed line never makes it block. [T-F08-02]
- `/speckled:approve` writes the exact `Approved by` shape, with a note in brackets after the date. The README describes `lint-chain`, the Action and their limits. [T-F08-15]

## [0.3.0] - 2026-10-15

In `warn` mode, agents can no longer commit, push, open pull requests or change the gate's settings: those rules now block in both modes. Every block is now logged. `/speckled:init` suggests `warn` for every project. Projects with enforcement off are unaffected.

### Changed
- `/speckled:init` suggests `warn` for every project, and describes `block` as also refusing agent code changes outside an approved task. Protocol §8 and the README describe hard and task rules, the logged blocks and `mode` as the outcome. [T-F07-21]
- The gate's rules now have a kind: hard rules (protected files, sessions without hooks, commit, push, pull request, unreadable config) and task rules. `speckled-gate check` gives `block` for a hard rule in `warn` mode too, and reports each violation's `kind`. Hard rules are checked before the start-folder rule, and their messages no longer suggest `warn`. [T-F07-19]
- The hook acts on the rule kind: in `warn` mode, agents can no longer commit, push, open pull requests or change the gate's settings. Every block is now logged in `.speckled/log.jsonl` with `mode: block`, including the safety guard's blocks when enforcement is on; a block stands even if the log can't be written. [T-F07-20]

## [0.2.0] - 2026-10-12

### Added
- Approval enforcement: an opt-in `PreToolUse` hook (`hooks/gate.py`) that checks code changes against an approved, active task, protects the gate's own settings, and stops agents committing, pushing or opening pull requests. `enforcement: off | warn | block` and `enforcement_exempt` in `speckled.yaml`. [T-F07-06] [T-F07-08]
- `speckled_gate`, a standard-library Python package with the decision logic, usable without Claude Code, with a bundled, unmodified PyYAML 6.0.3 for reading `speckled.yaml` and front matter. [T-F07-02] [T-F07-03] [T-F07-05] [T-F07-06]
- Shell command analysis shared by both hooks: writes, deletes, moves, commits, pushes and pull requests, including through `bash -c`, `xargs` and command substitutions. [T-F07-04]
- `speckled-gate` command line: `check`, `status`, `activate` and `install-git-hook`. [T-F07-07] [T-F07-09] [T-F07-11]
- Warn mode logs each allowed violation to `.speckled/log.jsonl` (log format v1, documented in the protocol). [T-F07-06]
- `/speckled:build` activates the task before implementing it. [T-F07-09]
- Commit-time notice: an optional git pre-commit hook for the planning repo that lists the approvals and status changes in each commit, without blocking it. [T-F07-11]
- Protocol §8 Enforcement: the planning repo, settings, rules, `.speckled/`, log format and the strict task format. [T-F07-13]

### Changed
- `/speckled:init` creates a dedicated planning repo next to the code repos (`../<project>-plans` by default), lists only code repos under `repos`, asks for the enforcement mode, and prints the command to start sessions. [T-F07-12]
- The guard hook uses the shared shell analysis, covers `Grep`, `Glob`, `NotebookEdit` and `PowerShell`, and catches recursive deletes through `bash -c`, `xargs` and `find -delete`. Harmless mentions of `.env`, such as in an `echo`, are no longer blocked. [T-F07-10]
- Protocol §5 rule 1: agents record approvals and mark work done only when a human runs `/speckled:approve`. Each agent's boundaries say the same. [T-F07-13]
- The task list template uses the strict `Depends on` and `Status` lines the hook reads. [T-F07-13]
- The guard and the gate run in one `PreToolUse` hook process, `hooks/pretooluse.py`, the guard first, so each tool call starts Python once. Read, Grep and Glob calls don't load the gate. [T-F07-17]
- The performance test measures the hook in up to three rounds and passes when one round's p95 is within budget, so bursts of slowness on shared CI runners don't fail it. The budget is unchanged. [T-F07-18]

### Fixed
- `.env.dist` is treated as a safe example file everywhere, and the README lists all four safe suffixes. [T-F07-10]
- A garbled sentence in the dev agent's instructions. [T-F07-13]
- The guard never allows `rm -rf`: it loads only the shell analysis, so faults elsewhere in the gate can't switch it off, and if the shell analysis itself can't load or fails, a simpler check still blocks recursive forced deletes. [T-F07-17]

## [0.1.0] - 2026-10-06

### Added
- Claude Code plugin with six role agents: analyst, pm, architect, planner, dev, designer.
- Pipeline skills: `init`, `brief`, `research`, `pdrd`, `frd`, `map`, `tdd`, `tasks`, `build`, `review`, `explain`, `pair`, `design`, `localize`.
- `approve`: a human-only skill (disabled for model invocation) that records approvals with approver, gate, date and version.
- Document protocol: permanent feature IDs, front matter, status gates, constraints check, traceability conventions.
- Markdown templates: brief, research, PDRD, FRD, TDD, task list, architecture.
- `guard.py` safety hook that blocks recursive forced deletes and access to secret `.env` files.
- Protocol rule that agents never commit, push or open pull requests; humans review and commit every change.
- `frd`, `tdd` and `tasks` accept a feature ID or any of its document IDs, and the README documents their no-argument behaviour.
