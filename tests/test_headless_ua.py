"""Headless UA normalization — COL's login backend never redirects a POST from
a "HeadlessChrome" user agent to the phNN app node (observed 2026-07-13), so
headless launches must present the build as regular Chrome. Pure string
transform only; the browser-launching discovery helper is not tested here
(tests run without Playwright browsers)."""

from colfin_harness.session.manager import normalize_user_agent

HEADLESS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) HeadlessChrome/149.0.7827.55 Safari/537.36"
)


def test_strips_headless_marker():
    ua = normalize_user_agent(HEADLESS_UA)
    assert "HeadlessChrome" not in ua
    assert "Chrome/149.0.7827.55" in ua  # version and the rest are preserved


def test_regular_chrome_ua_is_untouched():
    regular = HEADLESS_UA.replace("HeadlessChrome", "Chrome")
    assert normalize_user_agent(regular) == regular
