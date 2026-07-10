"""Harness configuration. All values overridable via COLFIN_* env vars."""

import logging
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The vision lane is locked to the Google Gemma family served via MLX (mlx-vlm).
# This is deliberate, not incidental: the orchestrator's fenced-JSON tool
# protocol is tuned for Gemma's lack of native function calling, and the runtime
# only knows how to drive an `mlx_vlm.server`. The model is configurable *within*
# that box — see `resolve_model_id` — but cannot leave it.
DEFAULT_MODEL_ID = "mlx-community/gemma-4-12B-it-8bit"

# Curated short aliases for known-good Gemma vision models on MLX, so callers can
# say `--model gemma-12b` instead of the full repo id. This is intentionally
# minimal — the guard in `resolve_model_id` accepts any Gemma-on-MLX repo, so new
# variants don't need an alias to be usable; add one here only for convenience.
GEMMA_MLX_MODELS: dict[str, str] = {
    "gemma-12b": DEFAULT_MODEL_ID,  # ~12.7 GB on disk, 8-bit; 16 GB RAM floor
}


def _is_gemma_mlx_repo(repo_id: str) -> bool:
    """True for a Hugging Face repo id that is both Gemma-family and MLX-format.

    Gemma: the model name contains ``gemma``. MLX: it lives under the
    ``mlx-community`` org (the canonical home for MLX conversions) or otherwise
    carries ``mlx`` in the id. This is a string guard, not a download — it keeps
    obviously-wrong choices (a base ``google/gemma-*`` repo, a non-Gemma model,
    a Llama MLX build) from ever reaching `mlx_vlm.server`.
    """
    rid = repo_id.strip().lower()
    org, slash, name = rid.partition("/")
    is_gemma = "gemma" in (name if slash else rid)
    is_mlx = org == "mlx-community" or "mlx" in rid
    return is_gemma and is_mlx


def resolve_model_id(value: str) -> str:
    """Resolve an alias or repo id to a full Gemma-on-MLX repo, enforcing the lock.

    Accepts a registered alias (see ``GEMMA_MLX_MODELS``) or any full repo id that
    passes ``_is_gemma_mlx_repo``. Raises ``ValueError`` for anything outside the
    Gemma + MLX box, so the same guard covers the default, the ``COLFIN_MODEL_ID``
    env var, the ``--model`` CLI flag, and direct ``Settings`` construction.
    """
    candidate = GEMMA_MLX_MODELS.get(value.strip(), value.strip())
    if not _is_gemma_mlx_repo(candidate):
        aliases = ", ".join(sorted(GEMMA_MLX_MODELS))
        raise ValueError(
            f"model {value!r} is not allowed: the harness is locked to the Google "
            f"Gemma family on MLX. Use a known alias ({aliases}) or a full "
            f"'mlx-community/…gemma…' (or other …mlx… gemma) repo id."
        )
    return candidate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COLFIN_")

    # ph45 is a sticky load-balancer node — the session cookie is only valid
    # there, so every request must stay pinned to this host.
    base_url: str = "https://ph45.colfinancial.com"
    app_root: str = "/ape/FINAL2_STARTER"

    # Public login page. It lives on www (not the ph45 node) — the app on ph45
    # only works once a session exists, so login starts here and hands the
    # session off to ph45.
    login_url: str = "https://www.colfinancial.com/ape/Final2/home/HOME_NL_MAIN.asp"

    # mlx-community/gemma-4-12B-it-8bit. NOTE: HF metadata reports ~3.37B
    # params, but the safetensors on disk total ~12.7 GB (3 shards) —
    # consistent with a real 12B model at 8-bit. Size RAM for ~13 GB of
    # weights: 16 GB unified memory is the floor, 24 GB+ comfortable.
    # Configurable via COLFIN_MODEL_ID (or --model), but locked to a Gemma-on-MLX
    # repo by the validator below; aliases like "gemma-12b" resolve to a full id.
    model_id: str = DEFAULT_MODEL_ID

    @field_validator("model_id")
    @classmethod
    def _lock_to_gemma_mlx(cls, value: str) -> str:
        return resolve_model_id(value)

    # The model is served out-of-process by `python -m mlx_vlm.server` so the
    # ~12.7 GB of weights load once and are reused across runs. The harness
    # health-checks this address and spawns a server only if none is running.
    model_server_host: str = "127.0.0.1"
    model_server_port: int = 8080
    # Cold start loads ~12.7 GB of weights — be generous before giving up.
    model_server_startup_timeout_s: float = 180.0
    # Generation on a 12B model is slow; kept separate from the 30s fragment
    # GET timeout (request_timeout_s) so model calls don't trip it.
    model_request_timeout_s: float = 120.0
    # Leave a server we spawned running on exit (reused next run) unless asked
    # to stop it. A reused server we did not start is never stopped.
    keep_model_server: bool = True

    # Persistent Chromium profile holding the authenticated COL session.
    # Lives outside the repo; never committed.
    profile_dir: Path = Path.home() / ".colfin-harness" / "profile"

    # Login is automated now, but keep a visible window by default: the user
    # may want to watch, and the vision lane screenshots the live frameset.
    headless: bool = False
    # Automated login authenticates in seconds; poll the cookie handoff to ph45
    # on a short fuse so a wrong password fails fast instead of hanging.
    auth_handoff_timeout_s: float = 30.0
    keepalive_interval_s: float = 240.0  # ping well inside the idle timeout
    request_timeout_s: float = 30.0

    # Discord front-end allowlist: comma-separated user-ID snowflakes
    # (COLFIN_DISCORD_ALLOWED_USERS). Empty means the bot answers no one —
    # it fails closed. The bot *token* is deliberately NOT a setting: env vars
    # leak into the model-server subprocess, so it comes from the macOS
    # Keychain only (see keychain.py).
    discord_allowed_users: str = ""

    @property
    def discord_allowed_user_ids(self) -> frozenset[int]:
        """The allowlist parsed to user IDs; blank entries are ignored.

        Non-numeric entries are skipped with a warning rather than raised —
        a typo must not crash the bot thread, and skipping fails closed.
        """
        ids: set[int] = set()
        for part in self.discord_allowed_users.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError:
                logging.getLogger(__name__).warning(
                    "ignoring invalid COLFIN_DISCORD_ALLOWED_USERS entry %r "
                    "(expected a numeric Discord user ID)",
                    part,
                )
        return frozenset(ids)

    # App landing page. Requesting the FINAL2_STARTER directory root itself
    # (app_root + "/") returns a 403 — there is no directory index — so all
    # navigation and the keep-alive ping must target this concrete page.
    @property
    def home_path(self) -> str:
        return f"{self.app_root}/HOME/HOME.asp"

    @property
    def home_url(self) -> str:
        return f"{self.base_url}{self.home_path}"

    @property
    def model_server_base_url(self) -> str:
        return f"http://{self.model_server_host}:{self.model_server_port}"


settings = Settings()
