"""Read-only Market Information agent (docs/read-only-agents.md,
"Market Information sub-tab").

Market-wide surfaces under Quotes → Market Information. All three are plain
cookie-authenticated GETs returning HTML fragments; none take parameters."""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.parsing.market_info import (
    parse_gainers_losers,
    parse_market_summary,
    parse_most_active,
)
from colfin_harness.schemas import GainersLosers, MarketSummary, MostActive

MARKET_SUMMARY_PATH = "/ape/FINAL2_STARTER/quotes/INDEX_AU_2DB.asp"
GAINERS_LOSERS_PATH = "/ape/FINAL2_STARTER/quotes/PSE_GainerLoser_2.asp"
MOST_ACTIVE_PATH = "/ape/FINAL2_STARTER/quotes/Pse_MostActive_2.asp"


class MarketInfoAgent(BaseAgent):
    def get_market_summary(self) -> MarketSummary:
        """PSE indices (composite, all-shares, six sectors), market status,
        and exchange-wide breadth (trades/value/volume, up/down/unchanged
        volume, advances/declines/unchanged)."""
        return parse_market_summary(self._source.fetch_fragment(MARKET_SUMMARY_PATH))

    def get_gainers_losers(self) -> GainersLosers:
        """Today's top 20 gainers and top 20 losers by % change."""
        return parse_gainers_losers(self._source.fetch_fragment(GAINERS_LOSERS_PATH))

    def get_most_active(self) -> MostActive:
        """Today's 20 most active stocks by trade value, with OHLC."""
        return parse_most_active(self._source.fetch_fragment(MOST_ACTIVE_PATH))
