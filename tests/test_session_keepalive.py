"""Keep-alive must ping via httpx without touching the Playwright context.

Regression guard for the greenlet "Cannot switch to a different thread" error:
the background keep-alive thread previously re-synced cookies from the
Playwright context, whose sync API is bound to the main thread.
"""

import httpx

from colfin_harness.session.manager import SessionManager


class _BoomContext:
    """Stand-in Playwright context that explodes if cookies() is accessed."""

    def cookies(self, *args, **kwargs):
        raise AssertionError("the keep-alive thread must not touch the Playwright context")


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


def test_keep_warm_serializes_against_relogin_lock():
    """keep_warm must take the session lock so a ping can never straddle a
    relogin()'s node re-pin (stale-host NodePinningError / bounced ping)."""
    import threading

    mgr = SessionManager()
    mgr._context = _BoomContext()
    home_url = f"{mgr.config.base_url}{mgr.config.home_path}"
    mgr._client = _FakeClient(_FakeResponse(home_url, "<html>Actual Balance ...</html>"))

    with mgr._session_lock:  # simulate a relogin in progress
        ping = threading.Thread(target=mgr.keep_warm)
        ping.start()
        ping.join(timeout=0.2)
        assert ping.is_alive(), "keep_warm must block while relogin holds the lock"
        assert mgr._client.calls == []
    ping.join(timeout=5)
    assert not ping.is_alive()
    assert mgr._client.calls[0][0] == mgr.config.home_path


def test_keep_warm_pings_home_via_httpx_without_playwright():
    mgr = SessionManager()
    mgr._context = _BoomContext()
    home_url = f"{mgr.config.base_url}{mgr.config.home_path}"
    mgr._client = _FakeClient(_FakeResponse(home_url, "<html>Actual Balance ...</html>"))

    mgr.keep_warm()  # would raise via _BoomContext if it synced browser cookies

    assert mgr._client.calls[0][0] == mgr.config.home_path


def test_fetch_fragment_still_syncs_cookies(monkeypatch):
    # The agent path (main thread) DOES re-sync browser cookies before the GET.
    mgr = SessionManager()
    synced = {"n": 0}
    monkeypatch.setattr(mgr, "_sync_cookies", lambda: synced.__setitem__("n", synced["n"] + 1))
    url = f"{mgr.config.base_url}/some/path.asp"
    mgr._client = _FakeClient(_FakeResponse(url, "<html>ok</html>"))

    mgr.fetch_fragment("/some/path.asp")

    assert synced["n"] == 1
