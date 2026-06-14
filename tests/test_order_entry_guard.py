"""The order-entry safety contract: the harness can never submit an order."""

from decimal import Decimal

import pytest

from colfin_harness.agents.order_entry import ORDER_STEP1_PATH, OrderEntryAgent
from colfin_harness.exceptions import MarketClosedError, OrderSubmissionForbidden
from colfin_harness.schemas import OrderDraft, OrderSide, OrderTerm

from conftest import FakeSource

DRAFT = OrderDraft(
    stock_code="TEL", side=OrderSide.BUY, quantity=10, price=Decimal("1400"), term=OrderTerm.DAY
)


def test_submit_order_always_raises(fixture_html):
    agent = OrderEntryAgent(FakeSource(fixture_html("market_closed.html")))
    with pytest.raises(OrderSubmissionForbidden):
        agent.submit_order()
    with pytest.raises(OrderSubmissionForbidden):
        agent.submit_order(DRAFT, confirmed=True, force=True)  # no bypass exists


def test_prepare_order_respects_server_market_gate(fixture_html):
    source = FakeSource(fixture_html("market_closed.html"))
    agent = OrderEntryAgent(source)

    with pytest.raises(MarketClosedError):
        agent.prepare_order(DRAFT)
    assert source.requests == [
        (ORDER_STEP1_PATH, {"StockCode": "TEL", "DAYGTC": "DAY"})
    ]
    assert agent.market_is_open() is False


def test_prepare_order_is_unmapped_even_when_market_open():
    # An open market returns a real form; field mapping is still a TODO, so
    # the stub must stop rather than guess at input names.
    agent = OrderEntryAgent(FakeSource("<form name='order'><input name='???'></form>"))

    assert agent.market_is_open() is True
    with pytest.raises(NotImplementedError):
        agent.prepare_order(DRAFT)
