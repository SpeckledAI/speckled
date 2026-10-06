# CLAUDE.md

## What this repo is

**Speckled** is a human-approved, spec-driven workflow for AI-assisted software development:
Brief → PDRD → FRD → TDD → Tasks → Code, with a human approval at every gate and a traceable chain from feature to commit.

This repo is the **public, Apache-2.0 Claude Code plugin** and nothing else. Speckled is developed with Speckled, but its planning (brief, PDRD, FRDs, TDDs, task lists, `speckled.yaml`) lives in the private sibling repo `../speckled-hq`. Sessions usually run from there, with this repo listed under `repos`.

**Never add product strategy here:** no brief or PDRD content, pricing, competitive analysis or business plans. This repo is public. Implementation work cites task IDs (`[T-F36-02]`) in commits; the documents those IDs refer to stay in `speckled-hq`.

## Layout

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.claude-plugin/marketplace.json` | Makes this repo its own marketplace (`speckled@speckled`) |
| `agents/` | Role definitions (analyst, pm, architect, planner, dev, designer). Used as subagents and as the role a skill takes on |
| `skills/<name>/SKILL.md` | Workflow steps, invoked as `/speckled:<name>` |
| `templates/` | Markdown document templates; `<!-- guide: -->` comments are instructions to the agent |
| `protocol/documents.md` | IDs, front matter, status and approval rules, traceability. **The core contract; read it first** |
| `protocol/authoring.md` | How a document is drafted with the human |
| `hooks/` | `guard.py` safety hook (blocks `rm -rf` and secret `.env` access) |
| `tests/` | Guard hook tests (`python3 -m unittest discover tests`) |

## Working on this repo

- Load the plugin locally: `claude --plugin-dir ~/Desktop/speckled` (from `speckled-hq`: `claude --plugin-dir ../speckled`), then `/speckled:<skill>`.
- Validate after changing plugin files: `claude plugin validate --strict .` (CI runs this; warnings fail it).
- This file lives in `.claude/` on purpose: a root `CLAUDE.md` fails strict validation.
- Bump `version` in `plugin.json` for every release, or installed users won't get the update.
- Skills refer to other plugin files by paths relative to the skill's own directory (`../../protocol/...`). Keep it that way so the plugin works wherever it's installed.
- Keep plugin content vendor-neutral (constraint C4): no project-, stack- or company-specific assumptions in agents, skills or templates.
- `hooks/guard.py` must run on Python 3.9+ with no dependencies.
