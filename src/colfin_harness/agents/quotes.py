"""Read-only quotes agent (docs/read-only-agents.md, Agent 1)."""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.parsing.quotes import parse_quote
from colfin_harness.schemas import Quote

QUOTE_PATH = "/ape/FINAL2_STARTER/B_home_new/Pse_Quote_AU_DB.asp"


class QuotesAgent(BaseAgent):
    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.strip().upper()
        html = self._source.fetch_fragment(QUOTE_PATH, {"q": symbol})
        return parse_quote(html, symbol=symbol)
