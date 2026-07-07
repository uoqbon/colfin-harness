"""Read-only quotes agent (docs/read-only-agents.md, Agent 1 + Quotes tab)."""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.parsing.quotes import parse_quote
from colfin_harness.parsing.stock_info import (
    parse_broker_activity,
    parse_stock_info,
    parse_trade_prices,
)
from colfin_harness.schemas import Quote, StockInfo, TopBrokers, TradePrices

QUOTE_PATH = "/ape/FINAL2_STARTER/B_home_new/Pse_Quote_AU_DB.asp"

# Quotes-tab surfaces. STOCK_INFO_PATH?q=SYM also sets the server-side
# "current stock" session state that TRADE_PRICES_PATH renders.
STOCK_INFO_PATH = "/ape/FINAL2_STARTER/quotes/Pse_Quote_2_DB.asp"
TOP_BUYER_PATH = "/ape/FINAL2_STARTER/quotes/TOPBUYER.asp"
TOP_SELLER_PATH = "/ape/FINAL2_STARTER/quotes/TOPSELLER.asp"
TRADE_PRICES_PATH = "/ape/FINAL2_STARTER/quotes/TRADEPRICES.asp"


class QuotesAgent(BaseAgent):
    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.strip().upper()
        html = self._source.fetch_fragment(QUOTE_PATH, {"q": symbol})
        return parse_quote(html, symbol=symbol)

    def get_stock_info(self, symbol: str) -> StockInfo:
        """Full Quotes-tab quote: 5-level depth with order counts, last 5
        trades with broker names, and the 23-row stats table."""
        symbol = symbol.strip().upper()
        html = self._source.fetch_fragment(STOCK_INFO_PATH, {"q": symbol})
        return parse_stock_info(html, symbol=symbol)

    def get_top_brokers(self, symbol: str) -> TopBrokers:
        """Top buying and selling brokers for the symbol (Buyers/Sellers tab)."""
        symbol = symbol.strip().upper()
        buyers = parse_broker_activity(
            self._source.fetch_fragment(TOP_BUYER_PATH, {"varstock": symbol}), symbol=symbol
        )
        sellers = parse_broker_activity(
            self._source.fetch_fragment(TOP_SELLER_PATH, {"varstock": symbol}), symbol=symbol
        )
        return TopBrokers(symbol=symbol, buyers=buyers, sellers=sellers)

    def get_trade_prices(self, symbol: str) -> TradePrices:
        """Per-price trade distribution (Trade Prices tab).

        TRADEPRICES.asp takes no symbol — it renders the session's server-side
        "current stock", which only the stock-info fetch sets. The two requests
        must stay back-to-back for the same symbol; anything interleaved that
        quotes another symbol would repoint the shared state.
        """
        symbol = symbol.strip().upper()
        self._source.fetch_fragment(STOCK_INFO_PATH, {"q": symbol})
        html = self._source.fetch_fragment(TRADE_PRICES_PATH)
        return parse_trade_prices(html, symbol=symbol)
