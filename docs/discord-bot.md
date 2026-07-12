# Discord bot front-end

An optional Discord front-end over the same conversation core as the terminal
REPL. Ask the bot questions in a DM (or by @-mentioning it in a server) and it
answers using the same orchestrator, single browser session, and local model —
one turn at a time, serialized with the REPL.

The safety contract is unchanged: the bot can never submit, modify, or cancel
an order (the order-entry guard sits below every front-end), it only ever sends
**text** — never screenshots, images, or attachments — and it answers only
allowlisted users.

## 1. Create the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
   and click **New Application**; name it (e.g. `colfin-harness`).
2. In **Bot**:
   - **Uncheck "Public Bot"** — only you should be able to invite it.
   - Under *Privileged Gateway Intents*, **enable "Message Content Intent"**
     (the bot needs to read the text of your DMs/mentions).
   - Click **Reset Token** and copy the token — you'll store it in the
     Keychain in the next step. Treat it like a password.
3. In **OAuth2 → URL Generator**:
   - Scopes: just **`bot`**.
   - Bot permissions: **Send Messages** and **Read Message History** only.
   - Open the generated URL and invite the bot to a private server you control
     (or skip the server and use DMs only — DMs work once you share a server).

## 2. Store the token in the macOS Keychain

```bash
security add-generic-password -s colfin-discord-bot -a bot -w
```

The `-w` with no value makes `security` prompt for the token interactively, so
it never lands in your shell history. The harness reads it back at startup with
`security find-generic-password -s colfin-discord-bot -w` and holds it in
process memory only — it is never written to disk, logs, config, or environment
variables (the model-server subprocess inherits the environment, which is why
env-var credentials are forbidden in this project).

To replace the token later: `security delete-generic-password -s
colfin-discord-bot`, then add it again.

## 3. Allowlist yourself

The bot answers **only** user IDs listed in `COLFIN_DISCORD_ALLOWED_USERS`
(comma-separated Discord snowflakes). If the list is empty, the bot starts but
answers **no one** — it fails closed and logs a warning.

To find your user ID: Discord **Settings → Advanced → enable Developer Mode**,
then right-click your own name anywhere and choose **Copy User ID**.

```bash
export COLFIN_DISCORD_ALLOWED_USERS="123456789012345678"   # your ID; comma-separate several
```

(This env var carries only user IDs — never put the token in the environment.)

## 4. Run

```bash
uv run python -m colfin_harness --user 1234-5678
```

- **Default (no flag):** the Discord front-end auto-starts if and only if a
  Keychain token exists. No token → REPL only.
- **`--discord`:** require the bot; exits with an error (and the
  `security add-generic-password` command to fix it) if no token is found.
- **`--no-discord`:** never start the bot, even if a token exists.

The bot runs in a daemon thread alongside the terminal REPL; exiting the REPL
ends the process and the bot with it. The COL login flow is unchanged — the
password is still prompted at the terminal on a cold profile.

## Usage

- **DM the bot**, or **@-mention it** in a channel it can read.
- Each channel (and each DM) keeps its own conversation history, trimmed to the
  same bounds as the REPL.
- Turns are slow (tens of seconds on the local 12B model) and strictly
  serialized across Discord and the REPL — the bot shows a typing indicator
  while it works.
- Long answers are split at Discord's 2000-character message limit.
- If the COL session expires mid-turn the harness re-logins silently once; if
  that fails the bot replies that an operator is needed at the terminal.

## Privacy note

Answers — balances, positions, order status — **transit and persist on
Discord's servers** like any other Discord message. Use DMs or a private
server you control, keep "Public Bot" unchecked, and keep the allowlist tight.
Do not invite the bot to shared servers.
