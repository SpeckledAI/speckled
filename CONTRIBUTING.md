# Contributing to Speckled

Thanks for helping. Speckled is built with Speckled: the maintainers plan every feature through the same brief → roadmap → requirements → design → tasks pipeline the plugin teaches, and every change is reviewed against an approved plan.

## Ways to contribute

- **Report a bug:** open an issue using the *Bug report* template.
- **Propose a change to a skill, template or the protocol:** open an issue using the *Proposal* template first. These files shape how every user's agents behave, so changes are discussed before a PR is opened.
- **Fix a typo or a small, clear bug:** open a PR directly.
- **Build a larger feature:** open a *Proposal* issue first. Larger features go through the Speckled pipeline (requirements → design → tasks) before implementation, and a maintainer approves each step.

## Development setup

```bash
git clone <repo-url> Speckled
cd your-test-project
claude --plugin-dir /path/to/speckled     # load your working copy
```

Before opening a PR:

```bash
claude plugin validate --strict /path/to/speckled   # manifest, marketplace, skills and agents
python3 -m unittest discover tests                   # guard hook tests
```

If you changed `hooks/guard.py`, keep it dependency-free and Python 3.9+ compatible, and add test cases for the new behavior.

## Ground rules for plugin content

- **Vendor-neutral.** Agents, skills and templates must not assume a particular language, framework, cloud, company or AI vendor.
- **Humans approve.** No change may let an agent record an approval, or weaken the status rules in `protocol/documents.md`.
- **Paths stay relative.** Skills refer to other plugin files by paths relative to their own directory (`../../protocol/...`), so the plugin works wherever it's installed.
- **Keep it short.** Every line in a skill or template costs tokens in every user's session. Say it once, clearly.

## Pull requests

- One concern per PR. Reference the issue, or the Speckled task ID (`T-F07-03`), in the title.
- Explain what changed and why, and how you tested it (for skill changes: a sample session or the document it produced).
- **Sign off every commit** with `git commit -s`. This certifies the [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or have the right to submit it under the project's license.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By taking part, you agree to uphold it.
