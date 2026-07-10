"""Playwright-backed session management for COL Financial.

Auth model (see docs/read-only-agents.md): the session is an HttpOnly cookie
minted by logging in on the public login page. The platform has no captcha/2FA,
so the harness automates the login: it launches a *persistent* Chromium profile
and, when the profile isn't already authenticated, fills the login form from
in-memory `Credentials` and submits it. Once a session exists it:

- exports the context's cookies into an httpx client pinned to the sticky
  ph45 load-balancer node for fast HTML-fragment GETs;
- keeps the session warm against the idle timeout with periodic pings;
- detects logout in responses (the REPL can silently re-login from the held
  credentials);
- serves screenshots of the live frameset for the VLM lane — but never of the
  login page, which would expose the user ID.

Credentials are handled in memory only and used solely for the login `fill()`;
they are never written to disk, env, logs, or the profile. A warm profile skips
login entirely and never needs them.
"""

import logging
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from colfin_harness.config import Settings, settings as default_settings
from colfin_harness.credentials import Credentials
from colfin_harness.exceptions import LoginFailed, NodePinningError, SessionExpired

logger = logging.getLogger(__name__)

# Heuristic logout signatures in fragment responses. The platform's idle
# watchdog is CheckSessionTimeout; an expired session bounces to the login
# page rather than returning data.
LOGOUT_MARKERS = (
    "session has expired",
    "session expired",
    "please log in",
    "please login",
    "login.asp",
    "you have been logged out",
)

# Endpoints used as probes; cheap and read-only.
_PORTFOLIO_PROBE = "/ape/FINAL2_STARTER/trading_PCA3/As_CashBalStockPos_MF.asp"

# Positive auth signal: an unauthenticated request can still come back 200
# (redirected to a public page with none of the logout markers), so "no
# logout marker" is not enough — the probe must contain actual portfolio
# content before we treat the session as live.
_AUTH_MARKERS = ("actual balance", "buying power")


def looks_logged_out(fragment: str) -> bool:
    lowered = fragment.lower()
    return any(marker in lowered for marker in LOGOUT_MARKERS)


class SessionManager:
    def __init__(self, config: Settings | None = None, credentials: Credentials | None = None):
        self.config = config or default_settings
        self._host = httpx.URL(self.config.base_url).host
        self._login_host = httpx.URL(self.config.login_url).host
        self._credentials = credentials
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.request_timeout_s,
            follow_redirects=True,
            headers={"Referer": self.config.home_url},
        )
        self._playwright = None
        self._context = None
        self._stop_keepalive = threading.Event()
        self._keepalive_thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self, credential_provider: Callable[[], Credentials] | None = None) -> None:
        """Launch the persistent profile and ensure an authenticated session.

        A warm profile goes straight to the app on ph45 and never needs
        credentials. A cold profile triggers automated login: credentials come
        from the constructor or, if absent, from ``credential_provider`` (called
        lazily so the password is only requested when login is actually needed).
        """
        from playwright.sync_api import sync_playwright

        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.config.profile_dir),
            headless=self.config.headless,
            viewport={"width": 1280, "height": 900},
        )
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        if self.is_authenticated():
            page.goto(self.config.home_url)
        else:
            if self._credentials is None:
                if credential_provider is None:
                    raise LoginFailed(
                        "no live session and no credentials available for automated login"
                    )
                self._credentials = credential_provider()
            page.goto(self.config.login_url)
            self._login(page)
        self.start_keepalive()

    def clear_credentials(self) -> None:
        """Drop the held password reference (called on REPL teardown)."""
        if self._credentials is not None:
            self._credentials.clear()

    def close(self) -> None:
        self._stop_keepalive.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=5)
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._client.close()

    def __enter__(self) -> "SessionManager":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _login(self, page) -> None:
        """Fill and submit the COL login form, then confirm the cookie handoff.

        The user ID's two halves go to txtUser1/txtUser2; the password to
        txtPassword. We submit by pressing Enter in the password field so the
        form's natural submit path (default button / onsubmit) fires. On
        success the page is moved onto the authenticated app so the vision lane
        never lingers on the credential-bearing login page.
        """
        creds = self._credentials
        if creds is None:  # defensive: start()/relogin() guarantee this
            raise LoginFailed("no credentials provided for automated login")
        try:
            page.wait_for_selector("#login", timeout=self.config.request_timeout_s * 1000)
        except Exception as exc:  # PlaywrightTimeoutError, but keep imports lazy
            raise LoginFailed(
                "login form (id='login') not found — the login page layout may have changed"
            ) from exc
        user1, user2 = creds.user_parts()
        page.fill("#login input[name='txtUser1']", user1)
        page.fill("#login input[name='txtUser2']", user2)
        page.fill("#login input[name='txtPassword']", creds.password)
        # If the live page has no default submit button, switch this to clicking
        # the specific control or `page.locator("#login").evaluate("f=>f.submit()")`.
        page.press("#login input[name='txtPassword']", "Enter")
        self._await_auth()
        # Land on the app home page (ph45) — mirrors the warm-profile path and
        # gets the browser off the login page before any screenshot tool can
        # fire. Must be HOME/HOME.asp: the FINAL2_STARTER directory root 403s.
        page.goto(self.config.home_url)

    def _await_auth(self) -> None:
        """Poll until the session cookie authenticates against ph45, on a short
        fuse so a wrong password fails fast. Never echoes the credentials."""
        deadline = time.monotonic() + self.config.auth_handoff_timeout_s
        while time.monotonic() < deadline:
            if self.is_authenticated():
                logger.info("Session is live.")
                return
            time.sleep(2)
        raise LoginFailed(
            f"login did not authenticate within {self.config.auth_handoff_timeout_s:.0f}s — "
            "the user ID or password may be wrong, or the login page changed"
        )

    def relogin(self) -> None:
        """Re-run automated login after a mid-session expiry (one silent retry
        from the REPL). Raises LoginFailed if no credentials are held."""
        if self._credentials is None:
            raise LoginFailed("session expired and no credentials are held for re-login")
        if self._context is None or not self._context.pages:
            raise LoginFailed("no live browser context for re-login")
        page = self._context.pages[0]
        page.goto(self.config.login_url)
        self._login(page)

    def is_authenticated(self) -> bool:
        try:
            self._sync_cookies()
            response = self._client.get(_PORTFOLIO_PROBE)
        except httpx.HTTPError:
            return False
        if response.status_code != 200 or response.url.host != self._host:
            # Unauthenticated requests get bounced off the ph45 node.
            return False
        text = response.text.lower()
        return any(m in text for m in _AUTH_MARKERS) and not looks_logged_out(text)

    # -- fragment fetching (fast lane) ----------------------------------------

    def _sync_cookies(self) -> None:
        """Mirror the Playwright context's cookies (incl. HttpOnly session
        cookie, which the browser API exposes to automation) into httpx."""
        if self._context is None:
            return
        for cookie in self._context.cookies(self.config.base_url):
            self._client.cookies.set(
                cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"]
            )

    def fetch_fragment(self, path: str, params: Mapping[str, str] | None = None) -> str:
        """GET an HTML fragment, pinned to ph45, with logout detection.

        Re-syncs the browser cookies first, so this touches the Playwright
        context and **must only be called from the thread that ran start()**
        (the sync API is bound to the greenlet that created it) — in the CLI
        that is the single turn-executor thread owned by ``__main__``, which
        all REPL and Discord turns run on. The background keep-alive uses the
        httpx-only path instead.
        """
        self._sync_cookies()
        return self._get_fragment(path, params)

    def _get_fragment(self, path: str, params: Mapping[str, str] | None = None) -> str:
        """The httpx half of a fragment GET — no Playwright access, so it is
        safe to call from the keep-alive thread."""
        response = self._client.get(path, params=dict(params or {}))
        if response.url.host != self._host:
            raise NodePinningError(
                f"request to {path} escaped {self._host} → {response.url.host}; "
                "the session is only valid on the sticky node"
            )
        response.raise_for_status()
        if looks_logged_out(response.text):
            raise SessionExpired(
                f"logout detected while fetching {path} — re-login required "
                "in the browser window"
            )
        return response.text

    # -- keep-alive ------------------------------------------------------------

    def keep_warm(self) -> None:
        # Runs on a background thread, so it MUST NOT touch the Playwright
        # context (the sync API is single-threaded — cross-thread access raises
        # "greenlet.error: Cannot switch to a different thread"). The session
        # cookie already lives in the httpx jar and httpx keeps it fresh from
        # Set-Cookie, so ping with httpx alone. Home page, not the 403 dir root.
        self._get_fragment(self.config.home_path)

    def start_keepalive(self) -> None:
        if self._keepalive_thread is not None:
            return
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, name="colfin-keepalive", daemon=True
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self) -> None:
        while not self._stop_keepalive.wait(self.config.keepalive_interval_s):
            try:
                self.keep_warm()
                logger.debug("keep-alive ping ok")
            except SessionExpired:
                logger.warning("keep-alive detected logout; manual re-login required")
            except Exception as exc:  # keep the thread alive across blips
                logger.warning("keep-alive ping failed: %s", exc)

    # -- vision lane -------------------------------------------------------------

    def screenshot(self, path: str | Path | None = None) -> Path:
        """Capture the live frameset for the VLM. Returns the PNG path.

        Refuses to capture the login page: it shows the user ID, and the image
        would be base64'd straight into a model request. After login the page is
        moved onto the app, so this only trips if the session bounced back to
        login mid-flight — exactly when we must not screenshot.
        """
        if self._context is None or not self._context.pages:
            raise RuntimeError("no live browser page; call start() first")
        page = self._context.pages[0]
        if httpx.URL(page.url).host == self._login_host:
            raise RuntimeError(
                "refusing to screenshot the login page (it would expose credentials)"
            )
        if path is None:
            path = Path(tempfile.mkstemp(prefix="colfin-", suffix=".png")[1])
        path = Path(path)
        page.screenshot(path=str(path), full_page=True)
        return path
