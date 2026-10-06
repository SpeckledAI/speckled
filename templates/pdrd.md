---
id: PDRD
title: {{project}} Product Development Roadmap
type: pdrd
parent: BRIEF
parent_version: {{parent_version}}
status: draft
version: 1
updated: {{date}}
approvals: []
---

# {{project}}: Product Development Roadmap Document

<!-- guide: The PDRD is the project's source of truth for scope. It is derived from the approved brief. Downstream, one FRD is written per feature. -->

## 1. Goals
<!-- guide: Bullet list of one-line outcomes this roadmap delivers if it succeeds, for users and for the business. -->

## 2. Background
<!-- guide: 1-2 paragraphs. What problem this solves and why now, drawn from the brief without repeating the goals. -->

## 3. Product Principles and Constraints
<!-- guide: The firm rules (mirrors speckled.yaml `constraints`) and the few product principles that guide trade-offs. Every feature below must respect them. -->

## 4. Phases
<!-- guide: Order phases by (1) legal and compliance needs, (2) technical dependencies, (3) value toward a usable MVP. For each phase use the block below. -->

### Phase {{n}}: {{phase name}}
- **Objectives:** <!-- guide: technical and business outcomes this phase achieves -->
- **Features:** <!-- guide: feature IDs in this phase, e.g. F01, F02 -->
- **Exit criteria:** <!-- guide: how we know the phase is done; must be testable -->
- **Why this comes now:** <!-- guide: the dependency or business reason for its position -->

## 5. Features
<!-- guide: One block per feature. IDs are permanent: F01, F02, ... Never renumber or reuse an ID, even if a feature moves phase or is cut (mark it Cut or Deferred instead). -->

### F{{nn}}: {{feature name}}
- **Phase:** {{n}} · **Priority:** Critical | High | Medium | Low · **Status:** Planned | In progress | Done | Deferred | Cut
- **Depends on:** <!-- guide: feature IDs or external dependencies -->
- **Description:** <!-- guide: what it does and for whom -->
- **Key capabilities:**
  <!-- guide: nested list; each capability, with specifics underneath -->
- **Why essential:** <!-- guide: bullet list -->
- **Technical considerations:** <!-- guide: high level only; split backend, frontend and infrastructure; preferences for the architect, not decisions -->
- **Success signal:** <!-- guide: the metric that shows this feature works -->

## 6. Out of Scope / Future
<!-- guide: Features explicitly not in this roadmap, with a one-line reason each. -->

## 7. Risks
<!-- guide: Numbered. For each risk: likelihood, impact, and how we'll reduce it. -->

## 8. Open Questions
<!-- guide: Numbered decisions the human needs to make. -->

## 9. Self-Review
<!-- guide: Before handing off, check and record the result: (a) no feature or phase depends on anything that comes later, (b) every feature has an ID, phase, priority and success signal, (c) every constraint is respected, (d) the MVP is the smallest set of features that is still useful. List any changes you made because of this review, and why. -->
