# CLAUDE.md

Python multi-agent harness for the COL Financial trading platform (classic ASP frameset
app, no JSON API), driven by a local MLX vision-language model on Apple Silicon.
Read `docs/read-only-agents.md` and `docs/order-entry.md` before touching agents or
parsers — they are the source of truth for endpoints and markup structure.

## Safety contract (non-negotiable)

- **The harness must NEVER submit, modify, or cancel an order.** The order wizard's
  Step 2 (preview/confirm) is a mandatory human checkpoint.
- `OrderEntryAgent.submit_order` raises `OrderSubmissionForbidden` unconditionally.
  Do not add a bypass, a `confirmed=True` path, or an order-filling orchestrator tool.
  `tests/test_order_entry_guard.py` enforces this — keep those tests passing.
- Order entry is server-gated by market status; always check the gate before entry work.
- No credentials in code, config, or tests. Login is automated, but credentials are
  prompted at runtime and held **in process memory only** — passed straight to the
  Playwright form fill, never written to disk, logs, or `os.environ` (the model server
  is a subprocess and would inherit env vars; that's why env-var creds are forbidden —
  do not add a `COLFIN_PASSWORD`). The session itself lives in the persistent Playwright
  profile (`~/.colfin-harness/profile`, gitignored).

## Commands

```bash
uv sync                                # install (Python 3.12 via .python-version)
uv run playwright install chromium     # one-time browser install
uv run pytest                          # tests: fixtures only, no network/model needed
uv run python -m colfin_harness --user 1234-5678   # conversational REPL ('exit' to quit)
uv run python -m colfin_harness        # same, but prompts for the user ID when needed
```

The REPL auto-fills the login form (password via a secure no-echo prompt, only when the
profile is cold), ensures a local `mlx_vlm.server` is up (spawning one if absent, reusing
a warm one), then answers questions with conversational context carried across turns.

An optional Discord front-end **auto-starts iff** a bot token exists in the macOS
Keychain (`security add-generic-password -s colfin-discord-bot -a bot -w`); force with
`--discord` / `--no-discord`. It answers only user IDs in `COLFIN_DISCORD_ALLOWED_USERS`
(empty allowlist = answers no one), text only. The token comes from the Keychain **only**
— never env vars, config, or Settings fields. See `docs/discord-bot.md`.

## Architecture

- `src/colfin_harness/session/` — Playwright persistent profile. A cold profile is
  logged in automatically: `_login` fills the `id="login"` form (user ID split across
  `txtUser1`/`txtUser2`, password in `txtPassword`) from in-memory `Credentials` and
  submits; a warm profile skips login entirely. No captcha/2FA. Cookies are mirrored into
  an httpx client **pinned to the sticky `ph45` node** (`NodePinningError` if a request
  escapes). Keep-alive thread fights the idle timeout; `SessionExpired` on logout markers
  (the REPL can silently `relogin`). `screenshot()` refuses the login page so the vision
  lane never captures credentials.
- `src/colfin_harness/parsing/` — pure functions over HTML fragments, separate from
  agents so tests run against fixtures. **Parsing must stay position/anchor based**
  (label text, `id="mytable"`, leaf-`<tr>` rows, font color for direction) — the legacy
  ASP markup has no stable per-field ids on values.
- `src/colfin_harness/agents/` — thin agents over `FragmentSource` (anything with
  `fetch_fragment`); tests inject fakes, never a live session.
- `src/colfin_harness/conversation.py` — front-end-agnostic core (`answer_task`,
  `trim_history`) shared by the REPL and `discord_bot.py`. There is one browser session
  and one model server, so all front-ends serialize turns through a single shared
  `threading.Lock` created in `__main__`. `discord_bot.py` gates messages by allowlist
  (fail closed), keeps per-channel history, and runs turns on a 1-worker executor under
  that lock; `keychain.py` reads the bot token from the macOS Keychain (never env — the
  model subprocess inherits env vars).
- `src/colfin_harness/orchestrator/` — Gemma has **no native function calling**: tools
  are invoked via one fenced-JSON object per model turn, with defensive extraction and
  retry-with-error-feedback. New tools go in `tools.py:build_default_registry`.
- `src/colfin_harness/model/` — client for an out-of-process `mlx_vlm.server`.
  `MLXServerManager` health-checks `127.0.0.1:8080/v1/models`, spawns
  `python -m mlx_vlm.server` if none is running (reusing a warm one, stopping only one it
  spawned), and `VLMRuntime.generate` POSTs text+base64-image chat completions over httpx,
  keeping the `generate(prompt, images=[]) -> str` signature the orchestrator expects.
  Serving out-of-process means the ~12.7 GB of weights load once and survive across runs.
  The HF metadata for `gemma-4-12B-it-8bit` claims ~3.37B params; the weights on disk are
  actually ~12.7 GB (real 12B at 8-bit). Don't "correct" code comments to match the HF metadata.
  The `model_id` is configurable (`--model` / `COLFIN_MODEL_ID`, plus short aliases in
  `config.py:GEMMA_MLX_MODELS`) but **locked to the Google Gemma family on MLX** by
  `config.py:resolve_model_id` — a `field_validator` guards the default/env/constructor and
  the CLI guards the `model_copy` path (validators don't run on copies). The lock is
  intentional: the fenced-JSON tool protocol is tuned for Gemma's lack of function calling
  and the runtime only drives `mlx_vlm.server`. Keep `tests/test_model_selection.py` passing.

## Conventions

- Money/price values are `Decimal`, parsed via `parsing/util.py:to_decimal` — it handles
  thousands commas, `+`/`%` decoration, and accounting parens (`(3,500.00)` is negative;
  `(+1.07%)` is not). Reuse it; don't hand-roll number parsing.
- Test fixtures in `tests/fixtures/` are **synthetic**, built from the docs' field
  lists. When real fragments from a live session become available, save them as new
  fixtures (scrub account numbers/balances first) rather than editing the synthetic ones.
- Network access in tests is forbidden — parsers and protocol logic must test offline.

## Open items

- Order-entry field-level mapping (Step 1 input names, Step 2 confirm payload) is
  blocked on PSE market hours (~09:30–15:30 PHT) — see `docs/order-entry.md`.
- Off-hours order route (`aftertrade_PCA/`) is unmapped.
