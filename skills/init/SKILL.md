---
name: init
description: Set up Speckled in a project by creating its planning repo with speckled.yaml and the docs structure, and, for existing codebases, reading the code and docs. Use when starting to use Speckled in a repository.
---

# Set up Speckled

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

1. Read `../../protocol/documents.md`.
2. **Find or create the planning repo.** Plans live in their own private repo next to the code repos, never inside them, so they stay private even when the code is public. `speckled.yaml` sits at the planning repo's root, and its `repos` lists the code repos only.
   - **`speckled.yaml` exists here:** this is the planning repo. Show the file and ask what to change (the questions in step 3 are a checklist), apply the changes, then continue from step 5. Don't create another repo. If `enforcement` is `warn` or `block`, remind the human that the gate protects `speckled.yaml`, so they make the edits themselves.
   - **Otherwise** (usually you're in a code repo), explain the layout above, then ask the questions in step 3. Propose `../<project>-plans` as the planning repo, with the project name in lowercase and hyphenated; the human can choose another path. If that folder already has a `speckled.yaml`, it's an existing planning repo: say so, create nothing, and tell the human to run `/speckled:init` from there instead.
3. Ask the user for these (numbered, with sensible defaults offered):
   1. Project name.
   2. Planning repo path (default `../<project>-plans`).
   3. Docs directory inside the planning repo (default `docs`).
   4. Code repositories this project spans (default: the current repo). Write each as a path relative to the planning repo, for example `../app`. Multi-repo projects list each one.
   5. Firm constraints: rules the product and the AI must never break (e.g. "every trade requires user approval", "no PII in logs"). It's fine to start with none.
   6. Who approves each gate: `brief`, `pdrd`, `frd`, `tdd`, `tasks`, `code`. A solo developer can put themselves on all of them.
   7. Enforcement mode, which controls how the agent's work is checked:
      - `off`: nothing is checked; the workflow is guidance only.
      - `warn`: agents work freely. Code changes outside an approved task go ahead, but the agent is told and the change is logged. Agents still can't commit, push, open pull requests or change the gate's settings.
      - `block`: the same as `warn`, and also refuses agent code changes outside an approved, active task.

      Suggest `warn` for every project. `block` is for teams that want agents to change code only for an approved task; it's their choice, not the default.
4. Create the planning repo folder if it's new and run `git init` in it. Write `speckled.yaml` at its root, with the chosen enforcement mode:
   ```yaml
   project: <name>
   docs_dir: docs
   enforcement: off
   repos:
     - ../<code repo>
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
5. Create `<docs_dir>/{research,frds,tdds,tasks}` in the planning repo. Don't overwrite existing files.
6. **Commit-time notice.** If `enforcement` isn't `off`, run `../../bin/speckled-gate install-git-hook --project <planning repo>` and report what it printed: either the hook was installed, or the line the human needs to add to their own hook.
7. **Existing codebase?** If the code repos already contain code, offer to run `/speckled:map` (from the planning repo, step 8) to write `ARCH` before any design work. If there are existing docs (a README, specs, notes), read them and summarize what you learned.
8. Finish by printing the command that starts Speckled sessions, from the planning repo with each code repo added:
   `cd <planning repo> && claude --add-dir <code repo> [--add-dir <code repo> ...]`

   Then show the pipeline and the next step:
   `/speckled:brief` → `/speckled:pdrd` → `/speckled:frd` → `/speckled:tdd` → `/speckled:tasks` → `/speckled:build`, with `/speckled:approve` at every gate.
