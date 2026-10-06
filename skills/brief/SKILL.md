---
name: brief
description: Draft or update the project brief (problem, users, solution, metrics, MVP scope, business model, constraints) with the human. First step of the Speckled pipeline.
---

# Project brief

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the analyst in `../../agents/analyst.md`.
**Template:** `../../templates/brief.md` → `<docs_dir>/brief.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.

1. Ask the human to describe the idea in their own words, and to share any notes, research or existing documents.
2. Read anything in `<docs_dir>/research/`.
3. Draft the brief with the human. Push back on vague problems, unmeasurable goals and oversized MVPs.
4. Suggest adding the brief's Constraints to `speckled.yaml` if they aren't there yet. Ask before editing it.
5. Hand off for approval. Next step after approval: `/speckled:pdrd`.
