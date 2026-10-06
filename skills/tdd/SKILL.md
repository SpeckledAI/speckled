---
name: tdd
description: Write a Technical Design Document (TDD) for an approved FRD, covering design, data model, interfaces, security, reliability, testing, rollout, and a traceability table. Use when a feature's requirements are approved and need a technical design.
argument-hint: "<feature id, e.g. F07>"
---

# TDD

Paths in this skill are relative to its base directory. The Speckled root is `../..`.

**Role:** act as the architect in `../../agents/architect.md`.
**Template:** `../../templates/tdd.md` → `<docs_dir>/tdds/F<nn>-<slug>.md`
**Protocol:** follow `../../protocol/authoring.md` and `../../protocol/documents.md`.
**Parent:** `FRD-F<nn>` (must be approved).

1. Feature: $ARGUMENTS. If none was given, list the approved FRDs that don't have a TDD yet, and ask which one.
2. **Freshness check:** if `ARCH` is missing, or its latest Change Log entry is older than the most recent code changes in the affected repos (check `git log`), recommend running `/speckled:map` first, and ask whether to continue.
3. Read the FRD, `ARCH`, the PDRD entry, and **the actual code** the feature touches.
4. Ask the human to clarify anything ambiguous in the FRD before designing.
5. Draft with the human. Every Must requirement appears in the traceability table.
6. Hand off for approval. Next step: `/speckled:tasks F<nn>`.
