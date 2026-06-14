# Security Policy

## Reporting a vulnerability

**Please report security vulnerabilities privately — do not open a public issue.**

Use GitHub's private vulnerability reporting for this repository:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability** (under *Advisories* / *Private vulnerability
   reporting*).
3. Fill in the advisory form with the details below.

This routes the report directly and privately to the maintainer. If private reporting is
not enabled or you cannot access it, open an issue that says only *"requesting a private
security contact"* (with **no** technical or account details) and wait for a private
channel before sharing specifics.

### NEVER include real account data in a report

This project drives a live brokerage platform. When reporting a vulnerability — or
attaching logs, screenshots, HTML fragments, or reproduction steps — you must **NEVER**
paste:

- real COL Financial **credentials** (user ID or password),
- **account numbers**,
- portfolio **balances**, positions, or any other personal account data,
- live **session cookies** or tokens.

Redact all of the above before submitting. If a reproduction genuinely needs sample
markup, use **synthetic** data (as in `tests/fixtures/`) with account numbers and
balances scrubbed. A report that contains real secrets or account data may be closed
without action and asked to be resubmitted after redaction.

### What to include

- A description of the issue and its impact.
- Steps to reproduce (with redacted/synthetic data only).
- Affected version or commit, and your environment if relevant.
- Any suggested fix or mitigation.

## Disclosure window

- We aim to **acknowledge** your report within **3 business days**.
- We aim to provide an initial **assessment** within **10 business days**.
- We follow **coordinated disclosure**: please give us up to **90 days** to release a
  fix before any public disclosure. We will keep you updated on progress and coordinate
  the disclosure timing with you, and we are happy to credit you (with your consent).

## Supported versions

This project is pre-1.0 and ships from `main`. Security fixes are applied to the latest
commit on `main`; please upgrade to the latest `main` before reporting, and verify the
issue still reproduces there.

| Version        | Supported          |
| -------------- | ------------------ |
| `main` (latest)| :white_check_mark: |
| older commits  | :x:                |

## A note on scope

This is an **independent, unofficial** project and is **not affiliated with COL
Financial**. Reports about COL Financial's own platform, website, or infrastructure
should go to COL Financial directly — this policy covers only the code in *this*
repository.
