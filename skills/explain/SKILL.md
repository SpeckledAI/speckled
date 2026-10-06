---
name: explain
description: Explain the most recent change, or a piece of code, in depth, as if training a junior engineer, covering what was done, why, the alternatives, and the concepts involved. Use when the human wants to learn from or fully understand a change.
argument-hint: "[what to explain]"
---

# Explain

Explain $ARGUMENTS, or, if nothing was given, the most recent change you made. Write for a capable junior engineer:

1. **What changed**, walking through the code step by step with file and line references.
2. **Why**: the requirement or task behind it (cite the IDs) and the reasoning behind each significant decision.
3. **Alternatives** considered and their trade-offs.
4. **Concepts**: any pattern, library behavior or language feature that's needed to understand it, explained plainly.
5. **Risks and how to verify**: what could go wrong, and how to test or check it.

Be thorough but concrete. Prefer the actual code over abstractions.
