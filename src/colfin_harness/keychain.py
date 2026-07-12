"""macOS Keychain lookups for the Discord bot token.

The token is a credential, so the project's credential rules apply: it is read
from the Keychain at runtime and held in process memory only — never logged,
never written to disk, and never placed in ``os.environ`` (the mlx_vlm.server
model subprocess inherits the environment, which is exactly why env-var
credentials are forbidden here).

Store the token once with::

    security add-generic-password -s colfin-discord-bot -a bot -w
"""

import shutil
import subprocess
import sys

DISCORD_TOKEN_SERVICE = "colfin-discord-bot"


def get_discord_bot_token() -> str | None:
    """Return the Discord bot token from the macOS Keychain, or ``None``.

    ``None`` means "no token available": not on macOS, no ``security`` binary,
    or no Keychain item for the service (nonzero exit). The caller decides
    whether that is an error (explicit ``--discord``) or just "bot disabled".
    """
    if sys.platform != "darwin":
        return None
    if shutil.which("security") is None:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", DISCORD_TOKEN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    token = result.stdout.strip()
    return token or None
