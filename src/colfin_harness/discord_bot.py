"""Discord front-end: a DM/mention-driven bot over the same conversation core
as the REPL.

Safety posture:

- Allowlist-gated and fail-closed: only DMs or @-mentions from user IDs in
  ``COLFIN_DISCORD_ALLOWED_USERS`` get an answer; an empty allowlist answers
  no one. Other bots (including this one) are always ignored.
- Text only. The bot never sends images, screenshots, or file attachments —
  the vision lane's screenshots stay on the operator's machine.
- One turn at a time. Turns run on a single-worker executor *and* under the
  process-wide ``turn_lock`` shared with the REPL, because there is exactly
  one browser session and one model server.
- The token never appears in logs, and the order-entry guard is untouched:
  this front-end only feeds tasks into the same orchestrator the REPL uses.

The message-handling decisions live in plain functions (``should_respond``,
``chunk_message``, ``strip_bot_mention``, ``record_turn``) so tests never
instantiate a discord.Client or touch the network.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import discord

from colfin_harness.config import Settings
from colfin_harness.conversation import answer_task, trim_history
from colfin_harness.exceptions import LoginFailed
from colfin_harness.orchestrator import Turn

logger = logging.getLogger(__name__)

DISCORD_MESSAGE_LIMIT = 2000

SESSION_DOWN_REPLY = (
    "The COL session is down and re-login failed — an operator needs to "
    "re-authenticate at the terminal before I can answer."
)


def should_respond(
    author_id: int,
    is_dm: bool,
    mentions_bot: bool,
    allowlist: frozenset[int],
    author_is_bot: bool = False,
) -> bool:
    """Gate a message: allowlisted humans only, via DM or @-mention.

    An empty allowlist answers no one — fail closed.
    """
    if author_is_bot:
        return False
    if author_id not in allowlist:
        return False
    return is_dm or mentions_bot


def strip_bot_mention(content: str, bot_user_id: int) -> str:
    """Remove the bot's mention tokens (``<@id>`` / ``<@!id>``) from a message."""
    return re.sub(rf"<@!?{bot_user_id}>", "", content).strip()


def chunk_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Split ``text`` into ≤``limit``-char chunks, breaking on newlines when
    possible. Concatenating the chunks reproduces ``text`` exactly."""
    chunks: list[str] = []
    while len(text) > limit:
        split = text.rfind("\n", 0, limit)
        cut = split + 1 if split != -1 else limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


def record_turn(histories: dict[int, list[Turn]], channel_id: int, task: str, answer: str) -> None:
    """Append a completed turn to the channel's independent history and trim it."""
    history = histories.setdefault(channel_id, [])
    history.append(Turn(task, answer))
    trim_history(history)


class ColfinDiscordBot(discord.Client):
    def __init__(
        self,
        *,
        orchestrator,
        session,
        turn_lock: threading.Lock,
        allowlist: frozenset[int],
        intents: discord.Intents,
        turn_executor: ThreadPoolExecutor | None = None,
    ) -> None:
        super().__init__(intents=intents)
        self._orchestrator = orchestrator
        self._session = session
        self._turn_lock = turn_lock
        self._allowlist = allowlist
        self._histories: dict[int, list[Turn]] = {}
        # Turns MUST run on the process-wide turn executor: sync Playwright is
        # thread-affine, so screenshots and relogin only work on the thread
        # that started the session (__main__ owns that executor and started
        # the session on it). The single worker also serializes turns before
        # the lock is ever contended.
        self._executor = turn_executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="discord-turn"
        )

    async def on_ready(self) -> None:
        logger.info("Discord bot connected as %s (allowlist: %d user(s))",
                    self.user, len(self._allowlist))

    async def on_message(self, message: discord.Message) -> None:
        bot_user = self.user
        if bot_user is None or message.author.id == bot_user.id:
            return
        is_dm = message.guild is None
        mentions_bot = any(u.id == bot_user.id for u in message.mentions)
        if not should_respond(
            message.author.id, is_dm, mentions_bot, self._allowlist,
            author_is_bot=message.author.bot,
        ):
            return
        task = strip_bot_mention(message.content, bot_user.id)
        if not task:
            return
        try:
            async with message.channel.typing():
                answer = await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._run_turn, message.channel.id, task
                )
        except LoginFailed:
            await message.channel.send(SESSION_DOWN_REPLY)
            return
        except Exception as exc:  # never let a turn crash the bot task
            logger.exception("Discord turn failed")
            # Type name only: exception text can embed request URLs and other
            # internals that must not persist on Discord's servers.
            await message.channel.send(
                f"Sorry, that failed ({type(exc).__name__}). Details are in the terminal log."
            )
            return
        # Text only, ever — no embeds, images, or file attachments.
        chunks = [c for c in chunk_message(answer) if c.strip()]
        for chunk in chunks or ["(no answer)"]:
            await message.channel.send(chunk)

    def _run_turn(self, channel_id: int, task: str) -> str:
        # Runs on the single turn-executor thread, under the lock shared with
        # the REPL: exactly one turn at a time touches the browser session /
        # model server, and the per-channel histories are only ever read and
        # mutated here — never concurrently from the event loop.
        with self._turn_lock:
            history = self._histories.setdefault(channel_id, [])
            answer = answer_task(self._orchestrator, self._session, task, history)
            record_turn(self._histories, channel_id, task, answer)
            return answer


def run_discord_bot(
    token: str,
    orchestrator,
    session,
    turn_lock: threading.Lock,
    settings: Settings,
    turn_executor: ThreadPoolExecutor | None = None,
) -> None:
    """Run the Discord client in the *current* thread until it stops.

    ``__main__`` calls this from a daemon background thread, so it creates its
    own event loop rather than using ``Client.run`` (which assumes the main
    thread for signal handling). ``turn_executor`` must be the process-wide
    turn executor when the session's Playwright was started on it.
    """
    allowlist = settings.discord_allowed_user_ids
    if not allowlist:
        logger.warning(
            "COLFIN_DISCORD_ALLOWED_USERS is empty or invalid — the Discord bot "
            "will answer NO ONE (fail closed). Set it to your Discord user ID "
            "to use the bot."
        )
    intents = discord.Intents.default()
    intents.message_content = True  # required to read DM/mention text
    client = ColfinDiscordBot(
        orchestrator=orchestrator,
        session=session,
        turn_lock=turn_lock,
        allowlist=allowlist,
        intents=intents,
        turn_executor=turn_executor,
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.start(token))
    except Exception:
        logger.exception("Discord bot stopped unexpectedly")
    finally:
        try:
            if not client.is_closed():
                loop.run_until_complete(client.close())
        finally:
            pending = asyncio.all_tasks(loop)
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
