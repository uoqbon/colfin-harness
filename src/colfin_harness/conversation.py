"""Front-end-agnostic conversation core shared by the REPL and the Discord bot.

There is one browser session (pinned to the sticky ph45 node) and one model
server, and ``orchestrator.run`` is blocking and slow — so every front-end
funnels its turns through ``answer_task`` and serializes them with a shared
``threading.Lock`` owned by ``__main__``. This module holds only the pieces
that must behave identically across front-ends: running one turn (with the
single silent re-login on expiry) and bounding the carried history.
"""

import logging

from colfin_harness.exceptions import SessionExpired
from colfin_harness.orchestrator import Turn

logger = logging.getLogger(__name__)

# Bound the carried context so it can't blow the 12B model's window: keep the
# most recent turns within a turn-count and a rough char budget, oldest first.
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 6000


def trim_history(history: list[Turn]) -> None:
    while len(history) > MAX_HISTORY_TURNS:
        history.pop(0)
    while history and sum(len(t.question) + len(t.answer) for t in history) > MAX_HISTORY_CHARS:
        history.pop(0)


def answer_task(orchestrator, session, task: str, history: list[Turn]) -> str:
    """Run one task; on a mid-session expiry, re-login once and retry."""
    try:
        return orchestrator.run(task, history=history)
    except SessionExpired:
        # logger, not print: this also runs on the Discord turn thread, where a
        # print would corrupt the operator's REPL prompt line.
        logger.info("Session expired — re-authenticating…")
        session.relogin()  # raises LoginFailed if no credentials are held
        return orchestrator.run(task, history=history)
