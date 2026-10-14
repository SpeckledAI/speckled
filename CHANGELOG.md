# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
