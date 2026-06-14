# Contributing to colfin-harness

Thanks for your interest in improving `colfin-harness`. This is an independent,
unofficial project (see the [README](README.md) and [LICENSE](LICENSE)); please read
the safety contract below before opening a pull request — it is non-negotiable and PRs
that violate it will be rejected.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

This is a Python 3.12 project managed with [uv](https://docs.astral.sh/uv/)
(`.python-version` pins the interpreter).

```bash
uv sync          # create the venv and install deps + this package
uv run pytest    # run the test suite (offline, fixtures only — no network or model)
```

The tests run entirely against saved HTML fixtures: no live COL session, no network
access, and no model download are required. Playwright browsers are **not** needed to
run the tests.

## Safety contract — HARD RULE

This harness is deliberately built so that it **can never submit, modify, or cancel an
order.** Order entry stops at the wizard's Step 2 (preview/confirm), which is a mandatory
**human** checkpoint.

- `OrderEntryAgent.submit_order` raises `OrderSubmissionForbidden` **unconditionally**.
  `tests/test_order_entry_guard.py` enforces this.
- The model is **locked to the Google Gemma family on MLX**.
  `tests/test_model_selection.py` enforces this.
- **No credentials in code, config, tests, or environment variables** — and never a
  `COLFIN_PASSWORD` env var. Credentials are prompted at runtime and held in process
  memory only (see [Credentials and security](README.md#credentials-and-security)).

**PRs that add an order-submission bypass, a `confirmed=True` path, an order-filling
orchestrator tool, or that otherwise weaken the model-family lock will be rejected.**
Do not weaken or delete the guard tests. If you believe a guard genuinely needs to
change, open an issue to discuss it first — do not bundle it into an unrelated PR.

## Pull request requirements

Before opening a PR, please make sure:

1. **All tests pass** — `uv run pytest` is green. CI runs the same suite on every push
   and pull request to `main`; the guard tests above must stay passing.
2. **No secrets or account data** — no real COL credentials, account numbers, balances,
   or session cookies in code, config, tests, fixtures, logs, or PR text. Test fixtures
   in `tests/fixtures/` are **synthetic**; if you add a real fragment, scrub account
   numbers and balances first.
3. **You did not weaken the safety contract** (see above).
4. **Your commits are signed off** under the Developer Certificate of Origin (see below).

The [pull request template](.github/PULL_REQUEST_TEMPLATE.md) restates this checklist.

## Developer Certificate of Origin (DCO)

This project requires a **DCO sign-off** on every commit. The DCO
(<https://developercertificate.org/>) is a lightweight statement that you have the right
to submit the contribution under the project's [Apache-2.0 license](LICENSE).

Sign off your commits by adding a `Signed-off-by` line with `-s`:

```bash
git commit -s -m "Your commit message"
```

This appends a line like:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must match your real identity. To sign off commits you already made,
amend the last one with `git commit --amend -s`, or rebase to sign off a range.

## Conventions

- Money/price values are `Decimal`, parsed via `parsing/util.py:to_decimal` — reuse it
  rather than hand-rolling number parsing.
- Parsing stays **position/anchor based** (label text, table ids, leaf-`<tr>` rows, font
  color for direction) — the legacy ASP markup has no stable per-field ids on values.
- Agent tests inject fakes; they never open a live session.

See [CLAUDE.md](CLAUDE.md) and the `docs/` directory for the platform mapping and the
full set of architectural invariants.
