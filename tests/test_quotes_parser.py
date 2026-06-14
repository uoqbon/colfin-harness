from decimal import Decimal

import pytest

from colfin_harness.agents.quotes import QUOTE_PATH, QuotesAgent
from colfin_harness.exceptions import QuoteNotFound
from colfin_harness.parsing.quotes import parse_quote
from colfin_harness.schemas import Direction

from conftest import FakeSource


def test_parse_quote_up(fixture_html):
    quote = parse_quote(fixture_html("quote_up.html"), symbol="TEL")

    assert quote.symbol == "TEL"
    assert quote.company_name == "PLDT Inc."
    assert quote.last == Decimal("1420.00")
    assert quote.change == Decimal("15.00")
    assert quote.pct_change == Decimal("1.07")
    assert quote.direction is Direction.UP

    assert len(quote.depth) == 3
    top = quote.depth[0]
    assert top.bid_volume == 1200
    assert top.bid_price == Decimal("1419.00")
    assert top.offer_price == Decimal("1421.00")
    assert top.offer_volume == 800

    assert quote.ohlc.open == Decimal("1410.00")
    assert quote.ohlc.high == Decimal("1425.00")
    assert quote.ohlc.low == Decimal("1405.00")
    assert quote.trades == 1234
    assert quote.value == Decimal("185430210.50")
    assert quote.volume == 130500


def test_parse_quote_down_direction_and_negatives(fixture_html):
    quote = parse_quote(fixture_html("quote_down.html"), symbol="ALI")

    assert quote.company_name == "Ayala Land, Inc."
    assert quote.last == Decimal("27.50")
    assert quote.change == Decimal("-0.45")
    assert quote.pct_change == Decimal("-1.61")
    assert quote.direction is Direction.DOWN
    assert quote.depth[2].offer_volume == 120000


def test_parse_quote_invalid_symbol_raises(fixture_html):
    with pytest.raises(QuoteNotFound):
        parse_quote(fixture_html("quote_invalid.html"), symbol="XXXX")


def test_quotes_agent_requests_endpoint_with_symbol(fixture_html):
    source = FakeSource(fixture_html("quote_up.html"))
    quote = QuotesAgent(source).get_quote("tel")

    assert source.requests == [(QUOTE_PATH, {"q": "TEL"})]
    assert quote.symbol == "TEL"
