---
name: map
description: Write or refresh ARCH, the current-state architecture document (what exists, including technical debt), by analyzing the project's repositories. Use before design work on an existing codebase, or when ARCH is stale.
---

# Map the architecture

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the architect in `../../agents/architect.md`.
**Template:** `../../templates/architecture.md` → `<docs_dir>/architecture.md`
**Protocol:** follow `../../protocol/documents.md`.

1. Ask the human whether to focus on specific areas (e.g. the ones an upcoming feature touches) or cover everything. For large codebases, recommend focusing.
2. For every repo in `speckled.yaml`, examine it directly: structure, manifests and lockfiles (for real versions), entry points, config and environment, build, CI, tests, data schemas and migrations, external integrations.
3. Ask about knowledge the code doesn't show: undocumented rules, fragile areas, known debt.
4. Record what actually exists. Point to files instead of copying them. Add a Change Log row.
5. If `ARCH` already exists, update it in place and summarize what changed.
6. Hand off for approval.
