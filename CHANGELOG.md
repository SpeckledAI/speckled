# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - Unreleased

### Added
- Claude Code plugin with six role agents: analyst, pm, architect, planner, dev, designer.
- Pipeline skills: `init`, `brief`, `research`, `pdrd`, `frd`, `map`, `tdd`, `tasks`, `build`, `review`, `explain`, `pair`, `design`, `localize`.
- `approve`: a human-only skill (disabled for model invocation) that records approvals with approver, gate, date and version.
- Document protocol: permanent feature IDs, front matter, status gates, constraints check, traceability conventions.
- Markdown templates: brief, research, PDRD, FRD, TDD, task list, architecture.
- `guard.py` safety hook that blocks recursive forced deletes and access to secret `.env` files.
- Protocol rule that agents never commit, push or open pull requests; humans review and commit every change.
