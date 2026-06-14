from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class FragmentSource(Protocol):
    """Anything that can GET a cookie-authenticated HTML fragment.

    SessionManager satisfies this in production; tests pass a fake backed by
    fixture files, so agents never need a live session.
    """

    def fetch_fragment(self, path: str, params: Mapping[str, str] | None = None) -> str: ...


class BaseAgent:
    def __init__(self, source: FragmentSource):
        self._source = source
