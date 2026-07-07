"""Quotes-tab parsers and agent, against real scrubbed fixtures (TEL,
captured 2026-07-07 — see docs/read-only-agents.md, "Quotes tab")."""

from decimal import Decimal

import pytest

from colfin_harness.agents.quotes import (
    STOCK_INFO_PATH,
    TOP_BUYER_PATH,
    TOP_SELLER_PATH,
    TRADE_PRICES_PATH,
    QuotesAgent,
)
from colfin_harness.exceptions import ParseError, QuoteNotFound
from colfin_harness.parsing.stock_info import (
    parse_broker_activity,
    parse_stock_info,
    parse_trade_prices,
)
from colfin_harness.schemas import BrokerSide, Direction

from conftest import FakeSource


# --- stock info -------------------------------------------------------------


def test_parse_stock_info_header_and_direction(fixture_html):
    info = parse_stock_info(fixture_html("stock_info.html"), symbol="TEL")

    assert info.symbol == "TEL"
    assert info.company_name == "PLDT Inc."
    assert info.last == Decimal("1156.0000")
    assert info.change == Decimal("-5.0000")
    assert info.pct_change == Decimal("-0.43")
    assert info.direction is Direction.DOWN


def test_parse_stock_info_depth_has_order_counts(fixture_html):
    info = parse_stock_info(fixture_html("stock_info.html"), symbol="TEL")

    assert len(info.depth) == 5
    top = info.depth[0]
    assert top.bid_orders == 7
    assert top.bid_volume == 980
    assert top.bid_price == Decimal("1156.0000")
    assert top.offer_price == Decimal("1157.0000")
    assert top.offer_volume == 210
    assert top.offer_orders == 8
    assert info.depth[4].offer_price == Decimal("1162.0000")


def test_parse_stock_info_last_trades(fixture_html):
    info = parse_stock_info(fixture_html("stock_info.html"), symbol="TEL")

    assert len(info.last_trades) == 5
    first = info.last_trades[0]
    assert first.time == "14:07:22"
    assert first.volume == 20
    assert first.price == Decimal("1156.0000")
    assert first.buyer == "ABACUS S"
    assert first.seller == "PHILIPPI"


def test_parse_stock_info_stats(fixture_html):
    stats = parse_stock_info(fixture_html("stock_info.html"), symbol="TEL").stats

    assert stats.previous == Decimal("1161.0000")
    assert stats.open == Decimal("1160.0000")
    assert stats.high == Decimal("1164.0000")
    assert stats.low == Decimal("1154.0000")
    assert stats.value == Decimal("42584870")
    assert stats.trades == 1082
    assert stats.volume == 36765
    assert stats.outstanding == 216055775
    assert stats.market_cap == Decimal("249760475900")
    assert stats.inst_status == "Authorized"
    assert stats.market_status == "Continuous trading"
    assert stats.board_lot == 5
    assert stats.fluctuation == Decimal("1.0000")
    assert stats.floor_price == Decimal("812.7000")
    assert stats.ceiling_price == Decimal("1741.5000")
    assert stats.dyn_t_low == Decimal("1040.4000")
    assert stats.dyn_t_high == Decimal("1271.6000")
    assert stats.par_value == Decimal("5.0000")
    assert stats.margin_rate_pct == Decimal("100")
    assert stats.open_to_foreigners == "YES"


def test_parse_stock_info_invalid_symbol_raises(fixture_html):
    with pytest.raises(QuoteNotFound):
        parse_stock_info(fixture_html("stock_info_invalid.html"), symbol="ZZZZ")


# --- top buyers / sellers ---------------------------------------------------


def test_parse_top_buyers(fixture_html):
    activity = parse_broker_activity(fixture_html("top_buyers.html"), symbol="TEL")

    assert activity.side is BrokerSide.BUYERS
    assert activity.as_of == "2:08:31 PM"
    assert len(activity.rows) == 20
    first = activity.rows[0]
    assert first.rank == 1
    assert first.broker == "COL FINANCIA"
    assert first.volume == 6580
    assert first.amount == Decimal("7631025")
    assert first.average_price == Decimal("1159.7302")
    assert first.pct_market == Decimal("17.86")


def test_parse_top_sellers_broker_with_comma(fixture_html):
    activity = parse_broker_activity(fixture_html("top_sellers.html"), symbol="TEL")

    assert activity.side is BrokerSide.SELLERS
    assert len(activity.rows) == 18
    assert activity.rows[0].broker == "MACQUARIE CA"
    # broker-name commas must not be mistaken for number formatting
    assert activity.rows[10].broker == "CAMPOS, LANU"
    assert activity.rows[10].volume == 500


def test_parse_broker_activity_without_title_raises():
    with pytest.raises(ParseError):
        parse_broker_activity("<html><body><table></table></body></html>")


# --- trade prices -----------------------------------------------------------


def test_parse_trade_prices_rows_and_totals(fixture_html):
    prices = parse_trade_prices(fixture_html("trade_prices.html"), symbol="TEL")

    assert prices.company_name == "PLDT Inc."
    assert len(prices.rows) == 11
    first = prices.rows[0]
    assert first.price == Decimal("1154.0000")
    assert first.volume == 20
    assert first.amount == Decimal("23080")
    assert first.trades == 2
    assert first.pct_of_value == Decimal("0.0542")

    assert prices.average_price == Decimal("1158.2312")
    assert prices.total_volume == 36765
    assert prices.total_amount == Decimal("42582370")
    assert prices.total_trades == 1082


def test_parse_trade_prices_empty_raises():
    with pytest.raises(ParseError):
        parse_trade_prices("<html><body></body></html>", symbol="TEL")


# --- agent request protocol ---------------------------------------------------


class SequencedSource:
    """FragmentSource fake keyed by path, recording request order."""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.requests: list[tuple[str, dict]] = []

    def fetch_fragment(self, path, params=None):
        self.requests.append((path, dict(params or {})))
        return self.responses[path]


def test_agent_stock_info_uses_q_param(fixture_html):
    source = FakeSource(fixture_html("stock_info.html"))
    info = QuotesAgent(source).get_stock_info("tel")

    assert source.requests == [(STOCK_INFO_PATH, {"q": "TEL"})]
    assert info.symbol == "TEL"


def test_agent_top_brokers_fetches_both_sides(fixture_html):
    source = SequencedSource(
        {
            TOP_BUYER_PATH: fixture_html("top_buyers.html"),
            TOP_SELLER_PATH: fixture_html("top_sellers.html"),
        }
    )
    top = QuotesAgent(source).get_top_brokers("tel")

    assert source.requests == [
        (TOP_BUYER_PATH, {"varstock": "TEL"}),
        (TOP_SELLER_PATH, {"varstock": "TEL"}),
    ]
    assert top.buyers.side is BrokerSide.BUYERS
    assert top.sellers.side is BrokerSide.SELLERS


def test_agent_trade_prices_sets_current_stock_first(fixture_html):
    """TRADEPRICES.asp renders the server-side "current stock", which only the
    stock-info fetch sets — the agent must sequence the two."""
    source = SequencedSource(
        {
            STOCK_INFO_PATH: fixture_html("stock_info.html"),
            TRADE_PRICES_PATH: fixture_html("trade_prices.html"),
        }
    )
    prices = QuotesAgent(source).get_trade_prices("tel")

    assert source.requests == [
        (STOCK_INFO_PATH, {"q": "TEL"}),
        (TRADE_PRICES_PATH, {}),
    ]
    assert prices.symbol == "TEL"
    assert prices.total_trades == 1082
