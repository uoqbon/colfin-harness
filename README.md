# colfin-harness

> **⚠️ Independent, unofficial project — please read before using.** Not affiliated
> with, endorsed by, or supported by COL Financial. Intended for **personal and
> educational use**, against **your own account, at your own risk**. **You alone are
> responsible** for complying with COL Financial's
> [Terms and Conditions](https://www.colfinancial.com/ape/Final2/home/terms_and_conditions.asp)
> and applicable Philippine law — programmatic access like this **may conflict with
> those terms**. Provided **"AS IS", with no warranty**; **nothing here is financial,
> investment, or legal advice.** Full terms: [Legal and disclaimer](#legal-and-disclaimer)
> · licensed under [Apache-2.0](LICENSE) (see also [NOTICE](NOTICE)).

A local multi-agent harness for the [COL Financial](https://www.colfinancial.com) online
trading platform, driven by a Google Gemma vision-language model running on Apple Silicon
via [mlx-vlm](https://github.com/Blaizzy/mlx-vlm). The model is configurable within the
Gemma-on-MLX family — `mlx-community/gemma-4-e4b-it-8bit` is the default, and any Gemma
build published for MLX works (see [Choosing the model](#choosing-the-model)).

The platform is a classic ASP frameset app with no JSON API: data endpoints are plain
cookie-authenticated GETs returning HTML fragments. The harness combines **DOM parsing**
(structured data from those fragments) with **vision** (Playwright screenshots fed to the
VLM for ambiguous UI/state). See [docs/read-only-agents.md](docs/read-only-agents.md) and
[docs/order-entry.md](docs/order-entry.md) for the platform mapping.

## ⚠️ Safety policy (non-negotiable)

- **This harness never submits orders.** Order entry is a 3-step wizard; Step 2
  (preview/confirm) is a mandatory **human** checkpoint. `OrderEntryAgent.submit_order`
  raises unconditionally and no order-filling tool is exposed to the model.
- Read-only agents (quotes, portfolio) are fully implemented and safe.
- No credentials live in code, config, or environment variables. Login is automated from
  a user ID + password you enter at runtime and hold **in process memory only**; the live
  session lives in the persistent Playwright profile (`~/.colfin-harness/profile`,
  gitignored). See [Credentials and security](#credentials-and-security).

## Requirements

- Apple Silicon Mac, with enough unified memory for whichever Gemma model you run
  (see [Choosing the model](#choosing-the-model)). **RAM note for the default,**
  `gemma-4-e4b-it-8bit`**:** Hugging Face metadata claims ~2.57B params, but the
  safetensors on disk total **~8.9 GB** (verified against the repo's shards) — the
  E-series is a MatFormer/elastic checkpoint larger than its effective param count
  suggests. 12 GB unified memory is workable; 16 GB+ recommended. Lighter quants
  (`…-4bit`/`…-6bit`) need less; heavier variants (the `gemma-12b` alias at ~12.7 GB, or
  `gemma-4-31b-it-*`) need more.
- Python 3.11–3.13 (managed via [uv](https://docs.astral.sh/uv/); `.python-version` pins 3.12).
- A COL Financial account. Login is automated from credentials you enter at runtime; they
  are held in process memory only and never written to disk (see
  [Credentials and security](#credentials-and-security)).

## Setup

```bash
uv sync                                  # creates .venv, installs deps + this package
uv run playwright install chromium       # browser for the session manager
```

## Usage

```bash
uv run python -m colfin_harness "How is my portfolio doing today?"
```

First run (cold profile): the harness prompts for your COL user ID and reads your password
with a no-echo prompt, opens a Chromium window at the COL login page (on
`www.colfinancial.com` — the in-app `ph45` URLs only work once a session exists), and
**auto-fills and submits the login form** for you (the platform has no captcha/2FA). It
then detects the live session, keeps it warm against the idle timeout, and proceeds. The
profile persists, so later (warm) runs reuse the session and skip login entirely — no
credential prompt. See [Credentials and security](#credentials-and-security).

Run the browser without a visible window with `--headless` (equivalently
`COLFIN_HEADLESS=true`); `--no-headless` forces a visible window even when the env var
is set. Headless runs use the full Chromium build in headless mode (not Playwright's
stripped "headless shell") with a normalized user agent, so the requests COL sees are
identical to a headed run — the login backend never completes the post-login redirect
for a browser that is detectably headless (`HeadlessChrome` user agent or `Sec-CH-UA`,
missing `Accept-Language`). The vision lane still screenshots the live frameset in headless mode, but you
won't be able to watch — so prefer a headed run the first time, when a cold profile
needs an automated login.

```bash
uv run python -m colfin_harness --headless --user 1234-5678
```

### Discord bot front-end (optional)

The harness can also answer over Discord, using the same orchestrator and session as the
REPL (turns are strictly serialized across both). It **auto-starts iff** a bot token
exists in the macOS Keychain (`security add-generic-password -s colfin-discord-bot -a bot
-w`) and answers only user IDs allowlisted in `COLFIN_DISCORD_ALLOWED_USERS` — an empty
allowlist answers no one. Force it on/off with `--discord` / `--no-discord`. The bot
sends **text only** (never screenshots or attachments), and the token is read from the
Keychain at runtime — never from env vars, config, or disk. Setup, allowlisting, and
privacy notes: [docs/discord-bot.md](docs/discord-bot.md).

### Choosing the model

The vision model is configurable, but **locked to the Google Gemma family on MLX** — the
orchestrator's fenced-JSON tool protocol is tuned for Gemma (which has no native function
calling) and the runtime only drives an `mlx_vlm.server`, so other families/frameworks are
rejected rather than silently mis-served. Select one with `--model` (equivalently
`COLFIN_MODEL_ID`):

```bash
uv run python -m colfin_harness --list-models          # show built-in aliases
uv run python -m colfin_harness --model gemma-12b       # a short alias (heavier sibling)
uv run python -m colfin_harness --model mlx-community/gemma-4-12B-it-4bit   # any Gemma-on-MLX repo
```

`--model` accepts either a built-in alias (e.g. `gemma-e4b` → the default
`mlx-community/gemma-4-e4b-it-8bit`, or `gemma-12b` → the heavier
`mlx-community/gemma-4-12B-it-8bit`) or any full Gemma repo published for MLX (an
`mlx-community/…gemma…` repo, or another id carrying `mlx`). Lighter quants
(`…-4bit`/`…-6bit`) trade accuracy for a smaller RAM footprint; larger siblings
(`gemma-4-31b-it-*`) need considerably more. A non-Gemma or non-MLX model is rejected up
front. Whichever you pick must be one `mlx_vlm.server` can serve — see the RAM note above.

### The model server lifecycle

The model runs out-of-process in a local `mlx_vlm.server`, and **by default it keeps
running after you exit** the REPL. This is intentional: the ~8.9 GB of weights stay
loaded, so the next run reuses the warm server instead of paying the cold start again. On
startup the harness health-checks the address (`127.0.0.1:8080`), reuses a warm server if
one is up, and spawns one only if none is.

To stop the server when the session ends:

```bash
uv run python -m colfin_harness --stop-server          # stop on exit, this run only
COLFIN_KEEP_MODEL_SERVER=false uv run python -m colfin_harness   # same, persistently
```

**Caveat:** stop-on-exit only terminates a server *this* run spawned. A server that was
already running when you started (i.e. reused from a previous session) is deliberately left
running even with `--stop-server`. To kill a lingering one manually:

```bash
pkill -f mlx_vlm.server
```

Programmatic use:

```python
from colfin_harness.agents import PortfolioAgent, QuotesAgent
from colfin_harness.session import SessionManager

with SessionManager() as session:
    print(QuotesAgent(session).get_quote("TEL"))
    print(PortfolioAgent(session).get_portfolio())
```

## Architecture

| Piece | Module | Notes |
|---|---|---|
| Session manager | `colfin_harness.session` | Persistent Playwright profile; manual login bootstrap; cookies mirrored into an httpx client **pinned to the sticky `ph45` node**; keep-alive thread; logout detection |
| Model runtime | `colfin_harness.model` | Lazy mlx-vlm wrapper: `generate(prompt, images=[])` |
| Quotes agent | `colfin_harness.agents.quotes` | `Pse_Quote_AU_DB.asp?q=SYM` → `Quote` (last/change/%, 3-level depth, OHLC, value, volume) |
| Portfolio agent | `colfin_harness.agents.portfolio` | `As_CashBalStockPos_MF.asp` → `Portfolio` (cash, equities, mutual funds, totals, P&L) |
| Order entry | `colfin_harness.agents.order_entry` | **Stub.** Wizard endpoints/params encoded; market-status gate works; field mapping is a market-hours TODO; submit path raises forever |
| Orchestrator | `colfin_harness.orchestrator` | ReAct-style loop; Gemma lacks native function calling, so tools are invoked via one fenced-JSON object per turn with defensive parsing + retries |

Parsing is **position/anchor based** (label text, the `mytable` id, leaf-`<tr>` rows,
font colors for direction) because the legacy ASP markup has no stable per-field ids.

## Credentials and security

No credentials are ever stored in code, config, environment variables, or the repo.

- **Automated login, in memory only.** When the Playwright profile is cold, the harness
  prompts for your COL user ID and reads your password with a no-echo prompt (`getpass`).
  They are wrapped in a `Credentials` object held **only in process memory**, passed
  straight to the Playwright form fill (`txtUser1`/`txtUser2` for the two halves of the
  user ID, `txtPassword` for the password), and never written to disk, logs, config, or
  `os.environ`. `Credentials.__repr__` masks the password so it cannot leak into
  tracebacks or log lines.
- **No password env var, by design.** The MLX vision model is served by a **subprocess**
  that would inherit the harness's environment, so a `COLFIN_PASSWORD` is deliberately
  unsupported — credentials must never reach the model process.
- **The session lives in the browser profile.** Auth is carried by the session cookie
  inside the persistent Chromium profile at `~/.colfin-harness/profile` (gitignored,
  outside the repo). Warm runs reuse that session and **skip login entirely** — no prompt,
  no credentials in memory at all. The held `Credentials` exists only to allow one silent
  re-login if the idle watchdog expires the session mid-conversation, and is cleared on
  teardown.
- **Cookies are pinned to one node.** The platform's `ph45` load-balancer node is sticky —
  the cookie is only valid there — so the mirrored httpx client refuses any request that
  would escape that host (`NodePinningError`).
- **The vision lane never sees the login page.** `screenshot()` refuses to capture the
  login page, and the login flow moves the browser off that page before any screenshot can
  run, so the user ID is never fed to the VLM.
- **Everything runs locally.** The vision model is a local `mlx_vlm.server` bound to
  `127.0.0.1`; no account data or screenshots leave your machine.

Stated plainly: Python `str` objects cannot be securely zeroed in memory, so the guarantee
is **"never persisted anywhere"**, not "scrubbed from RAM." Treat the machine running the
harness as trusted, and keep the gitignored profile directory protected like any other
logged-in browser session.

## Tests

Parser and protocol tests run against saved HTML fixtures — no live session, no network,
no model download:

```bash
uv run pytest
```

## Open items

- Order-entry field mapping (input names, Step 2 confirm payload) — blocked on PSE market
  hours (~09:30–15:30 PHT); see [docs/order-entry.md](docs/order-entry.md).
- Off-hours order route (`aftertrade_PCA/`) unmapped.
- Candidate future read-only agents: Trading History, account ledger, IPO/tender/rights
  status (listed in [docs/read-only-agents.md](docs/read-only-agents.md)).

## Legal and disclaimer

This is an **independent, unofficial** project. It is **not affiliated with, endorsed by,
or supported by COL Financial Group, Inc.** "COL Financial" and related names and marks
belong to their respective owners.

By using this software you accept that **you alone are responsible for complying with COL
Financial's [Terms and Conditions](https://www.colfinancial.com/ape/Final2/home/terms_and_conditions.asp)**
and all applicable laws and exchange/broker rules. **Read those terms before you run
anything here.** They are restrictive: among other things they limit the platform to your
**personal, non-commercial use**, prohibit redistributing platform content to third
parties, and prohibit **"data mining, data harvesting, data extracting or any other
similar activity."** A tool that programmatically reads and parses platform pages may not
be permitted under those terms — **whether your particular use is allowed is your call to
make, not this project's.**

To stay within the spirit of the personal-use and safety constraints, the harness is
deliberately built to:

- run entirely on your own machine, under **your own account**, for your **own personal,
  non-commercial** use — it is not a redistribution, resale, or bulk-collection tool;
- **never place, modify, or cancel an order** — order entry stops at the mandatory human
  preview/confirm checkpoint (see the **Safety policy** section above);
- keep all data and screenshots local (the vision model runs on `127.0.0.1`).

Even so, automated access can carry consequences COL may impose at its discretion — up to
**account suspension or IP blocking** — and COL provides the platform **"as is," without
warranties** of accuracy, timeliness, or fitness for any purpose. Use at your own risk.

**No warranty.** This software is provided "AS IS", without warranty of any kind, express
or implied. The authors and contributors accept no liability for any loss, damage, account
action, or financial loss arising from its use. Nothing here is financial, investment, or
legal advice.

**License and third-party components.** This project is released under the
[Apache License 2.0](LICENSE). It *drives* Google's **Gemma** vision-language model and
uses **[mlx-vlm](https://github.com/Blaizzy/mlx-vlm)** for local inference — neither the
model nor any weights are included or redistributed here. You download the Gemma weights
yourself from Hugging Face, and your use of Gemma is subject to
[Google's Gemma Terms of Use](https://ai.google.dev/gemma/terms). See [NOTICE](NOTICE) for
the full third-party attributions.
