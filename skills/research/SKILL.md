---
name: research
description: Run market or competitor research, or write a research plan/prompt for deeper investigation. Use when a product or technical decision needs evidence.
argument-hint: "[topic]"
---

# Research

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the analyst in `../../agents/analyst.md`.
**Template:** `../../templates/research.md` → `<docs_dir>/research/<slug>.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.

1. Agree on the decision this research informs and the numbered questions it must answer. Topic: $ARGUMENTS
2. Ask which output the human wants:
   1. **Research now:** use the web search and fetch tools available to you, cite every source, and fill in the template.
   2. **Research plan:** write a self-contained prompt (objective, background, numbered questions, sources to use, analysis frameworks, expected deliverables, success criteria) for a deep-research tool or a human researcher. Save it in the same folder with `-plan` added to the file name.
3. Keep facts, estimates and opinions visibly separate. Record how recent and reliable each source is.
4. Hand off for approval.
