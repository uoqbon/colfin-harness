## Summary

<!-- What does this PR change, and why? -->

## Related issues

<!-- e.g. Closes #123 -->

## Checklist

- [ ] **Safety guard intact** — this PR does **not** add an order-submission bypass, a
      `confirmed=True` path, an order-filling orchestrator tool, or otherwise weaken the
      rule that the harness never submits, modifies, or cancels an order.
      `tests/test_order_entry_guard.py` is unchanged or still enforces the guard.
- [ ] **Model lock intact** — this PR does not weaken the Google-Gemma-on-MLX model lock;
      `tests/test_model_selection.py` still passes.
- [ ] **No secrets or account data** — no real COL credentials, account numbers,
      balances, or session cookies in code, config, tests, fixtures, logs, or this PR's
      text. Any new fixtures are synthetic and scrubbed.
- [ ] **Tests pass** — `uv run pytest` is green locally and in CI.
- [ ] **DCO sign-off** — all commits are signed off (`git commit -s`); see
      [CONTRIBUTING.md](../CONTRIBUTING.md#developer-certificate-of-origin-dco).

## Notes for reviewers

<!-- Anything reviewers should pay special attention to. -->
