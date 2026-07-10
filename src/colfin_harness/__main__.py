"""Interactive entry point: ``python -m colfin_harness [--user ####-####]``.

Launches the persistent browser (automated login when the profile is cold — a
secure password prompt appears only then), ensures the local mlx_vlm.server is
running, and drops into a conversational REPL that carries context across
turns. Type ``exit`` (or Ctrl-D) to end the session.
"""

from __future__ import annotations

import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from colfin_harness.agents import OrderEntryAgent, PortfolioAgent, QuotesAgent, ResearchAgent
from colfin_harness.config import (
    DEFAULT_MODEL_ID,
    GEMMA_MLX_MODELS,
    Settings,
    resolve_model_id,
    settings as default_settings,
)

# Re-exported for backward compatibility (tests and callers import these here);
# the implementations moved to conversation.py so the Discord front-end shares
# them.
from colfin_harness.conversation import (  # noqa: F401
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    answer_task,
    trim_history,
)
from colfin_harness.credentials import prompt_credentials
from colfin_harness.exceptions import LoginFailed, SessionExpired
from colfin_harness.keychain import get_discord_bot_token
from colfin_harness.model import VLMRuntime
from colfin_harness.orchestrator import Orchestrator, Turn, build_default_registry
from colfin_harness.session import SessionManager

logger = logging.getLogger(__name__)

PROMPT = "colfin> "


def resolve_settings(headless: bool | None, model: str | None = None) -> Settings:
    """Resolve the runtime config, applying the ``--headless`` / ``--model`` overrides.

    A ``None`` for either flag means it was omitted, so the base settings stand
    (which honor ``COLFIN_HEADLESS`` / ``COLFIN_MODEL_ID``). An explicit value
    wins over the env default. ``model`` is resolved and locked to a Gemma-on-MLX
    repo here (``model_copy`` skips field validators, so we must call
    ``resolve_model_id`` ourselves); it raises ``ValueError`` on a rejected model.
    """
    updates: dict[str, object] = {}
    if headless is not None:
        updates["headless"] = headless
    if model is not None:
        updates["model_id"] = resolve_model_id(model)
    if not updates:
        return default_settings
    return default_settings.model_copy(update=updates)


def run_repl(
    orchestrator,
    session,
    history: list[Turn] | None = None,
    turn_lock: threading.Lock | None = None,
    turn_executor: ThreadPoolExecutor | None = None,
) -> None:
    """Read → answer → repeat until ``exit`` / EOF. Owns and trims the history.

    ``turn_lock`` is the process-wide serializer shared with the Discord bot —
    only one turn at a time may touch the single browser session/model server.
    ``turn_executor`` is the single thread the session's Playwright lives on;
    when given, turns are marshalled onto it (sync Playwright is thread-affine).
    """
    history = history if history is not None else []
    turn_lock = turn_lock if turn_lock is not None else threading.Lock()
    print("Ready. Ask a question, or type 'exit' to quit.")
    while True:
        try:
            task = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        task = task.strip()
        if not task:
            continue
        if task.lower() == "exit":
            break
        try:
            with turn_lock:
                if turn_executor is not None:
                    answer = turn_executor.submit(
                        answer_task, orchestrator, session, task, history
                    ).result()
                else:
                    answer = answer_task(orchestrator, session, task, history)
        except (SessionExpired, LoginFailed) as exc:
            print(f"Re-login failed: {exc}")
            break
        except Exception as exc:  # keep the REPL alive across tool/model blips
            print(f"Error: {type(exc).__name__}: {exc}")
            continue
        print(answer)
        history.append(Turn(task, answer))
        trim_history(history)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="colfin_harness")
    parser.add_argument(
        "--user", help="COL user ID (####-####); prompted if omitted and a login is needed"
    )
    parser.add_argument(
        "--stop-server",
        action="store_true",
        help="stop the model server on exit instead of leaving it warm for the next run",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="run the browser without a visible window (overrides COLFIN_HEADLESS); "
        "--no-headless forces a visible window. Omitted: honor COLFIN_HEADLESS "
        "(default: visible). Note the vision lane still screenshots the live frameset.",
    )
    parser.add_argument(
        "--model",
        metavar="ALIAS_OR_REPO",
        help="Gemma-on-MLX model to use: a built-in alias "
        f"({', '.join(sorted(GEMMA_MLX_MODELS))}) or a full 'mlx-community/…gemma…' "
        f"repo id. Overrides COLFIN_MODEL_ID. Default: {DEFAULT_MODEL_ID}. "
        "Locked to the Gemma family on MLX — see --list-models.",
    )
    parser.add_argument(
        "--discord",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="start the Discord bot front-end (token from the macOS Keychain item "
        "'colfin-discord-bot'); --no-discord disables it. Omitted: auto-start "
        "if and only if a Keychain token exists.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="list the built-in Gemma-on-MLX model aliases and exit",
    )
    args = parser.parse_args()

    if args.list_models:
        print("Built-in Gemma-on-MLX aliases (--model <alias>):")
        for alias, repo in sorted(GEMMA_MLX_MODELS.items()):
            default_tag = "  (default)" if repo == DEFAULT_MODEL_ID else ""
            print(f"  {alias:<12} → {repo}{default_tag}")
        print(
            "\nAny full 'mlx-community/…gemma…' (or other …mlx… Gemma) repo id is also "
            "accepted.\nThe harness is locked to the Google Gemma family on MLX."
        )
        return 0

    try:
        config = resolve_settings(args.headless, args.model)
    except ValueError as exc:
        parser.error(str(exc))  # prints to stderr, exits non-zero

    # Discord front-end resolution: explicit --discord demands a Keychain
    # token; --no-discord never starts it; omitted auto-starts iff a token
    # exists. The token stays in process memory — never env, disk, or logs.
    discord_token = get_discord_bot_token() if args.discord is not False else None
    if args.discord is True and discord_token is None:
        parser.error(
            "--discord requires a bot token in the macOS Keychain. Store one with:\n"
            "  security add-generic-password -s colfin-discord-bot -a bot -w"
        )
    if discord_token is not None:
        logger.info("Discord front-end starting (token found in Keychain).")
    else:
        logger.debug("Discord front-end disabled (no Keychain token or --no-discord).")

    runtime = VLMRuntime(config=config)
    session = SessionManager(config=config)
    # Sync Playwright is thread-affine: every call must come from the thread
    # that started it. All Playwright life — session start, every turn (REPL
    # and Discord alike), and teardown — runs on this single-worker executor,
    # which also makes turn serialization structural, not just lock-enforced.
    turn_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="colfin-turn")
    try:
        # The provider is invoked lazily, only when the profile is cold, so a
        # warm session never prompts for a password (the prompt reads stdin
        # from the turn thread; the main thread is blocked on the result).
        turn_executor.submit(
            session.start, credential_provider=lambda: prompt_credentials(args.user)
        ).result()
        registry = build_default_registry(
            session,
            QuotesAgent(session),
            PortfolioAgent(session),
            OrderEntryAgent(session),
            ResearchAgent(session),
        )
        orchestrator = Orchestrator(runtime, registry)
        runtime.ensure_server()  # warm the model before the first question
        # One lock for ALL front-ends: REPL and Discord turns never overlap on
        # the single browser session/model server.
        turn_lock = threading.Lock()
        if discord_token is not None:
            from colfin_harness.discord_bot import run_discord_bot

            threading.Thread(
                target=run_discord_bot,
                args=(discord_token, orchestrator, session, turn_lock, config, turn_executor),
                name="discord-bot",
                daemon=True,  # REPL exit ends the process; the bot dies with it
            ).start()
        run_repl(orchestrator, session, turn_lock=turn_lock, turn_executor=turn_executor)
    finally:
        # Teardown queues on the turn executor behind any in-flight Discord
        # turn, so the session is never closed under a running turn — and it
        # runs on the Playwright-owning thread, which sync Playwright requires.
        def _teardown() -> None:
            session.clear_credentials()
            session.close()

        try:
            turn_executor.submit(_teardown).result()
        finally:
            turn_executor.shutdown(wait=False, cancel_futures=True)
        if args.stop_server or not runtime.config.keep_model_server:
            runtime.stop_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
