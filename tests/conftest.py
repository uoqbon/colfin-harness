from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def load(name: str) -> str:
        return (FIXTURES / name).read_text()

    return load


class FakeSource:
    """FragmentSource stand-in: replays canned HTML, records requests."""

    def __init__(self, html: str):
        self.html = html
        self.requests: list[tuple[str, dict]] = []

    def fetch_fragment(self, path, params=None):
        self.requests.append((path, dict(params or {})))
        return self.html
