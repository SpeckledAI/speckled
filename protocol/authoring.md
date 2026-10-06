# Speckled Authoring Protocol

How to write a document from a Speckled template, together with the human. This applies to every document-producing skill.

## Before writing

1. Read `documents.md` (next to this file) and the project's `speckled.yaml`.
2. Read the template the skill names. Each section has a `<!-- guide: ... -->` comment explaining what goes in it. Guide comments are instructions to you; never copy them into the output.
3. Read every input the skill lists (parent document, architecture document, affected code). If an input is missing, ask for it instead of guessing.
4. Check the parent's status (documents.md §5, rule 2).

## Modes

Ask which mode the user wants, unless they already said:

- **Guided (default):** go through the template one section group at a time. For each group:
  1. Present the drafted content.
  2. Give a short **Rationale**: choices made and what else you considered, assumptions, and anything the human should look at closely.
  3. List any **Questions** you need answered.
  4. Stop and wait. The human replies with changes, answers, or "next".
- **Draft-all:** write the whole document in one pass, then present a summary with every assumption and open question collected at the end. Use this only when the user asks for it.

In both modes, save progress to the output file as you go, with `status: draft`.

## Writing rules

- Put questions to the human in the document's Open Questions section, not only in the chat, so they survive the session.
- Mark every assumption inline as `**Assumption:**` so a reviewer can find them all.
- Stay in scope: the document covers what its parent asked for, nothing more. Put good ideas that are out of scope under "Out of Scope / Future".
- Be concrete. Prefer names, numbers, file paths and examples over adjectives.
- Leave out any template section that doesn't apply to this project, and say so in one line (e.g. "No UI changes; section omitted"). Don't pad sections.

## Finishing

1. Run the template's final **Self-Review** section if it has one, and fix what it finds.
2. Fill in the Constraints Check (documents.md §6).
3. Set `status: in-review`, update `updated`, save.
4. Tell the human: where the file is, the three to five things most worth their attention, and the command to approve it (`/speckled:approve <id>`).
