"""The sticky phNN node is assigned per login, not fixed.

A live session on 2026-07-10 landed on ph1.colfinancial.com instead of the
configured ph45 default, so the session layer must discover the node from the
post-login redirect, pin the httpx fast lane there, and remember it for the
next warm start. All offline per repo convention: fakes only, no network.
"""

import time

import httpx
import pytest

from colfin_harness.config import Settings
from colfin_harness.exceptions import LoginFailed, NodePinningError
from colfin_harness.session.manager import SessionManager, node_host


class _FakePage:
    def __init__(self, url):
        self.url = url


class _FakeResponse:
    def __init__(self, url, text):
        self.url = httpx.URL(url)
        self.text = text

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self._response


# -- node_host ---------------------------------------------------------------


def test_node_host_accepts_any_assigned_node():
    assert node_host("https://ph45.colfinancial.com/ape/x.asp") == "ph45.colfinancial.com"
    assert node_host("https://ph1.colfinancial.com/ape/x.asp?q=TEL") == "ph1.colfinancial.com"
    assert node_host("https://PH7.COLFINANCIAL.COM/") == "ph7.colfinancial.com"


def test_node_host_rejects_non_node_urls():
    assert node_host("https://www.colfinancial.com/ape/Final2/home/HOME_NL_MAIN.asp") is None
    assert node_host("about:blank") is None
    assert node_host("") is None
    # Lookalike hosts must not pass — the pattern anchors the full hostname.
    assert node_host("https://ph1.colfinancial.com.evil.example/") is None
    assert node_host("https://evilph1.colfinancial.com.example/") is None


# -- pinning -------------------------------------------------------------------


def test_pin_repoints_client_and_escape_check():
    mgr = SessionManager()
    mgr._pin("ph1.colfinancial.com")

    assert mgr._host == "ph1.colfinancial.com"
    assert mgr.node_base_url == "https://ph1.colfinancial.com"
    assert httpx.URL(str(mgr._client.base_url)).host == "ph1.colfinancial.com"
    assert "ph1.colfinancial.com" in mgr._client.headers["Referer"]

    # A response from the pinned node passes; one from any other node escapes.
    mgr._client = _FakeClient(_FakeResponse("https://ph1.colfinancial.com/x.asp", "ok"))
    assert mgr._get_fragment("/x.asp") == "ok"
    mgr._client = _FakeClient(_FakeResponse("https://ph45.colfinancial.com/x.asp", "ok"))
    with pytest.raises(NodePinningError):
        mgr._get_fragment("/x.asp")


# -- discovery at login --------------------------------------------------------


def test_await_auth_pins_and_caches_the_redirect_node(tmp_path, monkeypatch):
    cfg = Settings(node_cache_file=tmp_path / "node")
    mgr = SessionManager(cfg)
    monkeypatch.setattr(mgr, "is_authenticated", lambda: True)

    mgr._await_auth(_FakePage("https://ph1.colfinancial.com/ape/FINAL2_STARTER/HOME/HOME.asp"))

    assert mgr._host == "ph1.colfinancial.com"
    assert (tmp_path / "node").read_text().strip() == "ph1.colfinancial.com"


def test_await_auth_off_node_and_unauthenticated_fails_without_pinning(tmp_path, monkeypatch):
    # Stuck on the www login page with no live session (e.g. wrong password):
    # the handoff must fail at the deadline, and the off-node probe must not
    # have pinned or cached anything.
    cfg = Settings(node_cache_file=tmp_path / "node", auth_handoff_timeout_s=0.05)
    mgr = SessionManager(cfg)
    default_host = mgr._host
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(mgr, "is_authenticated", lambda: False)

    with pytest.raises(LoginFailed) as excinfo:
        mgr._await_auth(_FakePage("https://www.colfinancial.com/ape/Final2/home/HOME_NL_MAIN.asp"))
    assert mgr._host == default_host
    assert not (tmp_path / "node").exists()
    # The failure names the host the page was stuck on (host ONLY — the
    # login-flow URL's path/query must never leak into the message).
    assert "www.colfinancial.com" in str(excinfo.value)
    assert "HOME_NL_MAIN" not in str(excinfo.value)


def test_await_auth_accepts_cookie_handoff_when_redirect_never_ran(tmp_path, monkeypatch):
    """The client-JS navigation to the phNN node can fail while the cookie
    handoff succeeded (observed headless 2026-07-13). A successful probe of
    the CURRENT pin is accepted — but a probe must never pin a NEW node; only
    the redirect URL may do that."""
    cfg = Settings(node_cache_file=tmp_path / "node", auth_handoff_timeout_s=0.05)
    mgr = SessionManager(cfg)
    default_host = mgr._host
    monkeypatch.setattr(mgr, "is_authenticated", lambda: True)

    mgr._await_auth(_FakePage("https://www.colfinancial.com/ape/Final2/home/HOME_NL_MAIN.asp"))

    assert mgr._host == default_host  # pin unchanged — no new node invented
    assert (tmp_path / "node").read_text().strip() == default_host


def test_await_auth_restores_previous_pin_on_failure(tmp_path, monkeypatch):
    """A failed handoff must not leave the manager pinned to the node the
    redirect reached but never authenticated on — a caller surviving
    LoginFailed would otherwise run on a pin that disagrees with the cache."""
    cfg = Settings(node_cache_file=tmp_path / "node", auth_handoff_timeout_s=0.05)
    mgr = SessionManager(cfg)
    default_host = mgr._host
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(mgr, "is_authenticated", lambda: False)

    with pytest.raises(LoginFailed):
        mgr._await_auth(_FakePage("https://ph1.colfinancial.com/ape/FINAL2_STARTER/HOME/HOME.asp"))

    assert mgr._host == default_host
    assert httpx.URL(str(mgr._client.base_url)).host == default_host
    assert not (tmp_path / "node").exists()


# -- cookie mirroring ------------------------------------------------------------


def test_sync_cookies_replaces_stale_jar_entries():
    """Mirror means replace: a parent-domain cookie left from a previous
    login is a distinct jar entry a same-name host-only set() never
    overwrites, and the jar would send both values to the new node."""

    class _FakeContext:
        def cookies(self, url):
            return [
                {"name": "SID", "value": "fresh", "domain": "ph1.colfinancial.com", "path": "/"}
            ]

    mgr = SessionManager()
    mgr._pin("ph1.colfinancial.com")
    mgr._client.cookies.set("SID", "stale", domain=".colfinancial.com", path="/")
    mgr._context = _FakeContext()

    mgr._sync_cookies()

    jar = [(c.domain, c.name, c.value) for c in mgr._client.cookies.jar]
    assert jar == [("ph1.colfinancial.com", "SID", "fresh")]


# -- warm-start cache ------------------------------------------------------------


def test_apply_cached_node_pins_the_persisted_node(tmp_path):
    cache = tmp_path / "node"
    cache.write_text("ph7.colfinancial.com\n")
    mgr = SessionManager(Settings(node_cache_file=cache))

    mgr._apply_cached_node()

    assert mgr._host == "ph7.colfinancial.com"
    assert httpx.URL(str(mgr._client.base_url)).host == "ph7.colfinancial.com"


def test_apply_cached_node_ignores_missing_and_invalid_cache(tmp_path):
    mgr = SessionManager(Settings(node_cache_file=tmp_path / "absent"))
    default_host = mgr._host
    mgr._apply_cached_node()
    assert mgr._host == default_host

    # A tampered cache must not re-point the client at an arbitrary host.
    bad = tmp_path / "node"
    bad.write_text("evil.example.com")
    mgr = SessionManager(Settings(node_cache_file=bad))
    mgr._apply_cached_node()
    assert mgr._host == default_host

    # An oversized (tampered) cache is rejected without being slurped whole:
    # only a bounded prefix is read, which cannot match the phNN pattern.
    big = tmp_path / "big"
    big.write_text("ph1.colfinancial.com" + "x" * 10_000)
    mgr = SessionManager(Settings(node_cache_file=big))
    mgr._apply_cached_node()
    assert mgr._host == default_host
