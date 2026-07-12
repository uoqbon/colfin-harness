"""Playwright-backed session management for COL Financial.

Auth model (see docs/read-only-agents.md): the session is an HttpOnly cookie
minted by logging in on the public login page. The platform has no captcha/2FA,
so the harness automates the login: it launches a *persistent* Chromium profile
and, when the profile isn't already authenticated, fills the login form from
in-memory `Credentials` and submits it. Once a session exists it:

- discovers the sticky load-balancer node (phNN.colfinancial.com) the login
  redirect landed on — the assigned node varies per login (ph45 and ph1 have
  both been observed) — and exports the context's cookies into an httpx
  client pinned to that node for fast HTML-fragment GETs;
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
import re
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


# Sticky load-balancer nodes look like phNN.colfinancial.com. Which node a
# login is assigned varies (ph45 and ph1 have both been observed), so the node
# is discovered from the post-login redirect rather than trusted from config.
# The same pattern validates the persisted node cache, so a tampered cache
# file cannot re-point the pinned client at an arbitrary host.
_NODE_HOST_RE = re.compile(r"ph\d+\.colfinancial\.com")


def normalize_user_agent(user_agent: str) -> str:
    """Rewrite a headless Chromium UA to its regular-Chrome equivalent."""
    return user_agent.replace("HeadlessChrome", "Chrome")


def _headless_user_agent(playwright) -> str:
    """Discover the current headless build's real UA from a throwaway browser
    (it changes with every Chromium bump, so it can't be hardcoded) and
    normalize it. Costs one extra ~fast headless launch, headless mode only.

    Scope: this patches the ``User-Agent`` request header and
    ``navigator.userAgent``. Sec-CH-UA client hints and Accept-Language are
    handled separately, by launching the full Chromium build
    (``channel="chromium"``) instead of the headless shell — see start().
    """
    browser = playwright.chromium.launch(headless=True, channel="chromium")
    try:
        ua = browser.new_page().evaluate("navigator.userAgent")
    finally:
        browser.close()
    normalized = normalize_user_agent(ua)
    if "headless" in normalized.lower():
        # Chromium renamed its headless marker and the rewrite missed it —
        # login will likely stall at _await_auth. Say so instead of failing
        # silently. (A UA string is not a secret; logging it is fine.)
        logger.warning(
            "user agent still carries a headless marker after normalization: %s", normalized
        )
    return normalized


def _url_host(url: str) -> str:
    """The bare host of *url* for diagnostics, ``"?"`` if unparsable. Host
    only, ever — login-flow paths/query strings must never reach a log or
    exception message."""
    try:
        return httpx.URL(url).host or "?"
    except Exception:
        return "?"


def node_host(url: str) -> str | None:
    """The sticky ``phNN.colfinancial.com`` host of *url*, or None if the URL
    is not on an app node (login page on www, blank page, garbage)."""
    try:
        host = httpx.URL(url).host
    except Exception:
        return None
    host = (host or "").lower()
    return host if _NODE_HOST_RE.fullmatch(host) else None


class SessionManager:
    def __init__(self, config: Settings | None = None, credentials: Credentials | None = None):
        self.config = config or default_settings
        # Provisional pin: the configured default node. start() re-pins to the
        # cached node (warm profile) or the node discovered at login.
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
        # Serializes keep-alive pings against relogin() and cookie re-mirrors:
        # a re-login may re-pin to a new node mid-run, and a ping in flight
        # across that re-pin (or across a jar rebuild in _sync_cookies) would
        # trip the escape check or go out with a torn cookie jar. Re-entrant
        # because relogin holds it while _login → is_authenticated →
        # _sync_cookies acquires it again on the same thread.
        self._session_lock = threading.RLock()

    # -- node pinning ----------------------------------------------------------

    @property
    def node_base_url(self) -> str:
        """Base URL of the node the session is currently pinned to."""
        return f"https://{self._host}"

    @property
    def _node_home_url(self) -> str:
        return f"{self.node_base_url}{self.config.home_path}"

    def _pin(self, host: str) -> None:
        """Re-point the fast lane at *host*: fragment GETs, the keep-alive and
        the NodePinningError escape check all follow the pinned host."""
        self._host = host
        self._client.base_url = self.node_base_url
        self._client.headers["Referer"] = self._node_home_url

    def _apply_cached_node(self) -> None:
        """Pin to the node persisted by the previous login, if any. A warm
        profile's session is only valid on the node that minted it, so probing
        the configured default would falsely look logged-out after a node
        change. Invalid or missing cache content is ignored."""
        try:
            # Bounded read: a valid cache is one short hostname, so never
            # slurp an oversized (tampered) file into memory.
            with self.config.node_cache_file.open() as fh:
                cached = fh.read(256).strip()
        except OSError:
            return
        host = node_host(f"https://{cached}/")
        if host is None:
            logger.warning(
                "ignoring node cache %s: %r is not a phNN.colfinancial.com host",
                self.config.node_cache_file,
                cached,
            )
            return
        if host != self._host:
            logger.info("Using cached session node %s", host)
            self._pin(host)

    def _cache_node(self, host: str) -> None:
        try:
            self.config.node_cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.config.node_cache_file.write_text(f"{host}\n")
        except OSError as exc:  # cache is an optimization; never fail login on it
            logger.warning("could not persist session node to %s: %s",
                           self.config.node_cache_file, exc)

    # -- lifecycle -----------------------------------------------------------

    def start(self, credential_provider: Callable[[], Credentials] | None = None) -> None:
        """Launch the persistent profile and ensure an authenticated session.

        A warm profile goes straight to the app on its cached sticky node and
        never needs credentials. A cold profile triggers automated login:
        credentials come from the constructor or, if absent, from
        ``credential_provider`` (called lazily so the password is only
        requested when login is actually needed).
        """
        from playwright.sync_api import sync_playwright

        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, object] = {}
        if self.config.headless:
            # COL's login backend answers a headless browser's POST without
            # ever redirecting to the phNN app node (observed 2026-07-13:
            # identical login timed out headless, succeeded headed). Playwright's
            # default headless=True runs the stripped "headless shell" build,
            # which is detectably different on the wire even with a rewritten
            # user agent: it omits Accept-Language entirely and brands
            # Sec-CH-UA as "HeadlessChrome" (measured against a local capture
            # server). channel="chromium" runs the FULL Chromium build in its
            # headless mode instead, whose request headers are identical to a
            # headed run; the UA string is the one remaining tell, normalized
            # below.
            launch_kwargs["channel"] = "chromium"
            launch_kwargs["user_agent"] = _headless_user_agent(self._playwright)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.config.profile_dir),
            headless=self.config.headless,
            viewport={"width": 1280, "height": 900},
            **launch_kwargs,
        )
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        # Probe the node the previous login was pinned to — a warm session is
        # invalid on any other node, so probing the default would force a
        # needless re-login after a node change.
        self._apply_cached_node()
        if self.is_authenticated():
            page.goto(self._node_home_url)
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
        txtPassword. We submit exactly the way the page's own LOG IN button
        does — its onclick runs ``CheckSubmit()``, which clicks the hidden
        ``cmdLogOn`` submit control — rather than relying on Enter-key
        implicit form submission, which depends on a rendering-sensitive
        default-button rule (the submit control is display:none) and is the
        kind of corner that can behave differently headless. The
        redirect lands the browser on the sticky phNN node assigned to this
        login — that host is discovered, pinned, and cached before the cookie
        handoff is confirmed. On success the page is moved onto the
        authenticated app so the vision lane never lingers on the
        credential-bearing login page.
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
        # Log the login flow's document requests while we wait for the handoff
        # (method/host/path/status ONLY — never query strings, never bodies:
        # the credentials travel in the POST body, which is never touched).
        def _log_login_response(response) -> None:
            try:
                if response.request.resource_type == "document":
                    url = httpx.URL(response.url)
                    logger.debug(
                        "login flow: %s %s%s -> %s",
                        response.request.method, url.host, url.path, response.status,
                    )
            except Exception:  # diagnostics must never break the login
                pass

        page.on("response", _log_login_response)
        try:
            # The same call the page's own LOG IN button makes (CheckSubmit()).
            # The control is display:none, so it must be clicked via the DOM —
            # Playwright's click() would wait for visibility forever.
            page.evaluate("document.getElementById('cmdLogOn').click()")
            self._await_auth(page)
        finally:
            page.remove_listener("response", _log_login_response)
        # Land on the app home page (on the discovered node) — mirrors the
        # warm-profile path and gets the browser off the login page before any
        # screenshot tool can fire. Must be HOME/HOME.asp: the FINAL2_STARTER
        # directory root 403s.
        page.goto(self._node_home_url)

    def _await_auth(self, page) -> None:
        """Poll until the login authenticates, on a short fuse so a wrong
        password fails fast.

        The post-login redirect URL is the authoritative node signal: when the
        page lands on a phNN host, that node is pinned and cached. But the
        navigation is client-JS driven and can fail while the cookie handoff
        itself succeeded (observed headless 2026-07-13: session live, page
        parked on www) — so when the page stays off-node, the CURRENT pin is
        probed as a fallback. A successful probe is safe to accept: it demands
        a 200 from the pinned host without redirecting off it, which the
        sticky-node cookie only produces on the right node. A new node is
        still never pinned from a probe — only from the redirect. Restores the
        previous pin if the handoff fails, so a caller that survives
        LoginFailed isn't left on a half-migrated pin that disagrees with the
        node cache. Never echoes the credentials."""
        previous = self._host
        deadline = time.monotonic() + self.config.auth_handoff_timeout_s
        while time.monotonic() < deadline:
            # Read the URL once per poll: the page navigates concurrently, and
            # two reads in one iteration can describe two different pages.
            page_url = page.url
            host = node_host(page_url)
            if host is not None and host != self._host:
                logger.info("Login assigned to node %s; pinning session there", host)
                self._pin(host)
            if self.is_authenticated():
                self._cache_node(self._host)
                if host is None:
                    logger.info(
                        "Session is live on %s while the browser page is still on %s — "
                        "accepting the cookie handoff without waiting for the "
                        "client-side navigation.",
                        self._host, _url_host(page_url),
                    )
                else:
                    logger.info("Session is live on %s.", self._host)
                return
            logger.debug("login handoff pending; browser page is on %s", _url_host(page_url))
            time.sleep(2)
        if self._host != previous:
            self._pin(previous)
        # Captured fresh at failure time — the last in-loop reading could be a
        # whole poll interval stale.
        raise LoginFailed(
            f"login did not authenticate within {self.config.auth_handoff_timeout_s:.0f}s — "
            "the user ID or password may be wrong, the login page changed, or the "
            "redirect never reached a phNN.colfinancial.com app node "
            f"(browser page ended on host {_url_host(page.url)!r})"
        )

    def relogin(self) -> None:
        """Re-run automated login after a mid-session expiry (one silent retry
        from the REPL). Raises LoginFailed if no credentials are held."""
        if self._credentials is None:
            raise LoginFailed("session expired and no credentials are held for re-login")
        if self._context is None or not self._context.pages:
            raise LoginFailed("no live browser context for re-login")
        page = self._context.pages[0]
        with self._session_lock:  # keep the keep-alive out while we may re-pin
            page.goto(self.config.login_url)
            self._login(page)

    def is_authenticated(self) -> bool:
        try:
            self._sync_cookies()
            response = self._client.get(_PORTFOLIO_PROBE)
        except httpx.HTTPError:
            return False
        if response.status_code != 200 or response.url.host != self._host:
            # Unauthenticated requests get bounced off the sticky node.
            return False
        text = response.text.lower()
        return any(m in text for m in _AUTH_MARKERS) and not looks_logged_out(text)

    # -- fragment fetching (fast lane) ----------------------------------------

    def _sync_cookies(self) -> None:
        """Mirror the Playwright context's cookies (incl. HttpOnly session
        cookie, which the browser API exposes to automation) into httpx.

        Mirror means *replace*, not merge: a cookie the browser has since
        dropped or re-scoped (e.g. a parent-domain `.colfinancial.com` cookie
        from a previous login next to the new host-only one — reachable once
        a re-login re-pins to a different node) is a distinct jar entry that
        `set()` would never overwrite, and the jar would send both values.
        The lock keeps a keep-alive ping from going out mid-rebuild.
        """
        if self._context is None:
            return
        with self._session_lock:
            self._client.cookies.jar.clear()
            for cookie in self._context.cookies(self.node_base_url):
                self._client.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"]
                )

    def fetch_fragment(self, path: str, params: Mapping[str, str] | None = None) -> str:
        """GET an HTML fragment, pinned to the discovered sticky node, with
        logout detection.

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
        # The lock keeps the ping from straddling a relogin()'s node re-pin.
        with self._session_lock:
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
