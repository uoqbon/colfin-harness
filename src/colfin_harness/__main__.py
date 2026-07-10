"""Interactive entry point: ``python -m colfin_harness [--user ####-####]``.

Launches the persistent browser (automated login when the profile is cold — a
secure password prompt appears only then), ensures the local mlx_vlm.server is
running, and drops into a conversational REPL that carries context across
turns. Type ``exit`` (or Ctrl-D) to end the session.
"""

import argparse
import logging

from colfin_harness.agents import (
    MarketInfoAgent,
    OrderEntryAgent,
    PortfolioAgent,
    QuotesAgent,
    ResearchAgent,
)
from colfin_harness.config import (
    DEFAULT_MODEL_ID,
    GEMMA_MLX_MODELS,
    Settings,
    resolve_model_id,
    settings as default_settings,
)
from colfin_harness.credentials import prompt_credentials
from colfin_harness.exceptions import LoginFailed, SessionExpired
from colfin_harness.model import VLMRuntime
from colfin_harness.orchestrator import Orchestrator, Turn, build_default_registry
from colfin_harness.session import SessionManager

logger = logging.getLogger(__name__)

PROMPT = "colfin> "
# Bound the carried context so it can't blow the 12B model's window: keep the
# most recent turns within a turn-count and a rough char budget, oldest first.
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 6000


def trim_history(history: list[Turn]) -> None:
    while len(history) > MAX_HISTORY_TURNS:
        history.pop(0)
    while history and sum(len(t.question) + len(t.answer) for t in history) > MAX_HISTORY_CHARS:
        history.pop(0)


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


def answer_task(orchestrator, session, task: str, history: list[Turn]) -> str:
    """Run one task; on a mid-session expiry, re-login once and retry."""
    try:
        return orchestrator.run(task, history=history)
    except SessionExpired:
        print("Session expired — re-authenticating…")
        session.relogin()  # raises LoginFailed if no credentials are held
        return orchestrator.run(task, history=history)


def run_repl(orchestrator, session, history: list[Turn] | None = None) -> None:
    """Read → answer → repeat until ``exit`` / EOF. Owns and trims the history."""
    history = history if history is not None else []
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

    runtime = VLMRuntime(config=config)
    session = SessionManager(config=config)
    try:
        # The provider is invoked lazily, only when the profile is cold, so a
        # warm session never prompts for a password.
        session.start(credential_provider=lambda: prompt_credentials(args.user))
        registry = build_default_registry(
            session,
            QuotesAgent(session),
            PortfolioAgent(session),
            OrderEntryAgent(session),
            ResearchAgent(session),
            MarketInfoAgent(session),
        )
        orchestrator = Orchestrator(runtime, registry)
        runtime.ensure_server()  # warm the model before the first question
        run_repl(orchestrator, session)
    finally:
        if args.stop_server or not runtime.config.keep_model_server:
            runtime.stop_server()
        session.clear_credentials()
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
