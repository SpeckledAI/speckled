---
name: frd
description: Write a Feature Requirements Document (FRD) for one PDRD feature, with testable requirements, UX, data, security, acceptance criteria and a constraints check. Requires an approved PDRD.
argument-hint: "<feature id, e.g. F07>"
---

# FRD

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the product manager in `../../agents/pm.md`.
**Template:** `../../templates/frd.md` → `<docs_dir>/frds/F<nn>-<slug>.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.
**Parent:** `PDRD` (must be approved).

1. Feature: $ARGUMENTS. Accept a feature ID (`F07`) or any of its document IDs (`FRD-F07`, `TDD-F07`, `TASKS-F07`), and use the feature number. If none was given, list the PDRD features that don't have an FRD yet, in phase order, and ask which one.
2. Check that the features it depends on are done or already have approved FRDs. If they aren't, point that out.
3. Read the PDRD entry, the brief, `ARCH` if it exists, and the FRDs of related features.
4. Ask the human to clarify anything ambiguous before drafting.
5. Draft with the human, then hand off for approval. Next step: `/speckled:tdd F<nn>`.
