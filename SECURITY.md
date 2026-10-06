# Security Policy

## Reporting a vulnerability

**Please don't report security issues in public issues, discussions or PRs.**

Report them privately through GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability): open the repository's **Security** tab and choose **Report a vulnerability**.

Include what's affected, steps to reproduce, and the impact you expect. We aim to acknowledge reports within 3 business days and to agree a disclosure timeline with you.

## In scope

Speckled's security model is mainly about **who can approve, and whether an approval can be trusted**. Examples of in-scope issues:

- Any way an agent, automation or prompt injection can record an approval, mark work done, or bypass a gate without a human.
- Any way to change or remove approval history without detection.
- Bypasses of the `hooks/guard.py` protections (recursive forced deletes, access to secret `.env` files).
- Skills or templates that lead agents to leak secrets or personal data.

## Supported versions

Only the latest release is supported while Speckled is pre-1.0.
