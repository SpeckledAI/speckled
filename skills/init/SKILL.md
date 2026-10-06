---
name: init
description: Set up Speckled in a project by creating speckled.yaml and the docs structure, and, for existing codebases, reading the code and docs. Use when starting to use Speckled in a repository.
---

# Set up Speckled

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

1. Read `../../protocol/documents.md`.
2. If `speckled.yaml` already exists at the project root, show it and ask what to change. Otherwise ask the user for these (numbered, with sensible defaults offered):
   1. Project name.
   2. Docs directory (default `docs`).
   3. Code repositories this project spans (default `.`). Multi-repo projects list each path.
   4. Firm constraints: rules the product and the AI must never break (e.g. "every trade requires user approval", "no PII in logs"). It's fine to start with none.
   5. Who approves each gate: `brief`, `pdrd`, `frd`, `tdd`, `tasks`, `code`. A solo developer can put themselves on all of them.
3. Write `speckled.yaml`:
   ```yaml
   project: <name>
   docs_dir: docs
   repos:
     - .
   constraints:
     - id: C1
       rule: <rule>
   roles:
     brief: [<name>]
     pdrd: [<name>]
     frd: [<name>]
     tdd: [<name>]
     tasks: [<name>]
     code: [<name>]
   ```
4. Create `<docs_dir>/{research,frds,tdds,tasks}`. Don't overwrite existing files.
5. **Existing codebase?** If the repos already contain code, offer to run `/speckled:map` to write `ARCH` before any design work. If there are existing docs (a README, specs, notes), read them and summarize what you learned.
6. Finish by showing the pipeline and the next step:
   `/speckled:brief` → `/speckled:pdrd` → `/speckled:frd` → `/speckled:tdd` → `/speckled:tasks` → `/speckled:build`, with `/speckled:approve` at every gate.
