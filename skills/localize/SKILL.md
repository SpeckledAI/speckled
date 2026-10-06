---
name: localize
description: Find UI text that hasn't been translated and add translations for the languages the app already supports, following the project's existing i18n setup. Use when adding or auditing translations.
---

# Localize

1. Find the project's i18n setup and the languages it already supports. Don't add new languages unless asked.
2. Scan the UI code for text that isn't wrapped in the i18n system or is missing translations.
3. Add keys and translations, following the existing key naming and file structure. Point out any translation you're unsure of (idioms, legal text, domain terms) so a human can check it.
4. Note any i18n problems you see (locale detection, fallbacks, formatting of dates, numbers and currency, pluralization). Fix them only if they're small and clearly in scope; otherwise list them.
5. Hand over for review with a summary of the keys added per language.
