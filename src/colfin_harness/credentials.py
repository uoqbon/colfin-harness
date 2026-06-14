"""In-memory credential handling for automated COL Financial login.

Credentials are entered at runtime and held only in process memory. They are
passed straight to the Playwright login form and are never written to disk, to
``os.environ`` (the model server runs as a subprocess and would inherit env
vars), to logs, or to config. They are needed only to mint the session cookie
at login; the warm cookie carries auth for the rest of the session, so a
``Credentials`` is kept around solely to allow a silent re-login if the idle
watchdog expires the session mid-conversation.
"""

import getpass
import re
from dataclasses import dataclass

USER_ID_PROMPT = "COL user ID (####-####): "
PASSWORD_PROMPT = "Password: "

# COL user IDs are two 4-digit groups joined by a dash; the two halves map onto
# the login form's txtUser1 / txtUser2 inputs (see docs/read-only-agents.md).
USER_ID_PATTERN = re.compile(r"^\d{4}-\d{4}$")


def validate_user_id(raw: str) -> str:
    """Return the normalised ####-#### user ID, or raise ValueError."""
    candidate = raw.strip()
    if not USER_ID_PATTERN.match(candidate):
        raise ValueError(
            f"user ID must look like ####-#### (two 4-digit groups), got {candidate!r}"
        )
    return candidate


@dataclass(repr=False)
class Credentials:
    """A COL user ID + password held in memory only.

    ``clear()`` drops the password reference so it is not reused or logged.
    Python ``str`` objects cannot be securely zeroed in place, so the real
    guarantee is "never persisted anywhere", not "scrubbed from memory".
    """

    user_id: str
    password: str

    def user_parts(self) -> tuple[str, str]:
        """Split the user ID into the txtUser1 / txtUser2 halves."""
        first, second = self.user_id.split("-", 1)
        return first, second

    def clear(self) -> None:
        self.password = ""

    def __repr__(self) -> str:  # never leak the password in logs/tracebacks
        shown = "***" if self.password else "<cleared>"
        return f"Credentials(user_id={self.user_id!r}, password={shown})"


def prompt_credentials(user_id: str | None = None) -> Credentials:
    """Resolve a valid user ID (re-prompting as needed), then read the password
    with no echo. This is the only I/O boundary; tests monkeypatch ``input`` and
    ``getpass.getpass``."""
    validated: str | None = None
    if user_id is not None:
        try:
            validated = validate_user_id(user_id)
        except ValueError as exc:
            print(exc)
    while validated is None:
        try:
            validated = validate_user_id(input(USER_ID_PROMPT))
        except ValueError as exc:
            print(exc)
    password = getpass.getpass(PASSWORD_PROMPT)
    return Credentials(user_id=validated, password=password)
