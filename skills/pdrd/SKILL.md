---
name: pdrd
description: Draft or revise the Product Development Roadmap Document (PDRD), the phased roadmap of permanently numbered features that serves as the project's source of truth. Requires an approved brief.
---

# PDRD

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the product manager in `../../agents/pm.md`.
**Template:** `../../templates/pdrd.md` → `<docs_dir>/pdrd.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.
**Parent:** `BRIEF` (must be approved; see the protocol's status rules).

1. Read the brief, any research, `speckled.yaml` constraints, and `ARCH` if it exists.
2. **New PDRD:** propose the phases first and get agreement, then write the features phase by phase.
   **Revision:** keep every existing feature ID. New features get the next unused number. Cut or deferred features keep their ID and get a status instead of being removed. Say which FRDs, TDDs and task lists the change affects.
3. Run the template's Self-Review.
4. Hand off for approval. Next step: `/speckled:frd <feature id>`, usually the first feature in Phase 1.
