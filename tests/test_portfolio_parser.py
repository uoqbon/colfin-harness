from decimal import Decimal

from colfin_harness.agents.portfolio import PORTFOLIO_PATH, PortfolioAgent
from colfin_harness.parsing.portfolio import parse_portfolio

from conftest import FakeSource


def test_parse_full_portfolio(fixture_html):
    p = parse_portfolio(fixture_html("portfolio_full.html"))

    assert p.cash.actual_balance == Decimal("125430.50")
    assert p.cash.buying_power == Decimal("250861.00")

    assert [h.code for h in p.equities] == ["TEL", "ALI"]
    tel = p.equities[0]
    assert tel.name == "PLDT Inc."
    assert tel.portfolio_pct == Decimal("60.89")
    assert tel.market_price == Decimal("1420.00")
    assert tel.average_price == Decimal("1380.00")
    assert tel.total_shares == Decimal("100")
    assert tel.market_value == Decimal("142000.00")
    assert tel.gain_loss == Decimal("4000.00")
    assert tel.pct_gain_loss == Decimal("2.90")

    # Accounting-style negatives: (3,840.00) and (5.50%)
    ali = p.equities[1]
    assert ali.gain_loss == Decimal("-3840.00")
    assert ali.pct_gain_loss == Decimal("-5.50")

    assert [f.code for f in p.mutual_funds] == ["CSGEF"]
    fund = p.mutual_funds[0]
    assert fund.navps == Decimal("1.2345")
    assert fund.total_shares == Decimal("20000.0000")

    assert p.equities_total.market_value == Decimal("208000.00")
    assert p.equities_total.gain_loss == Decimal("160.00")
    assert p.mutual_funds_total.market_value == Decimal("24690.00")

    assert p.totals.trade_value == Decimal("232690.00")
    assert p.totals.day_change_pct == Decimal("0.85")
    assert p.totals.day_change_amount == Decimal("1962.00")
    assert p.totals.gain_loss_pct == Decimal("-0.49")
    assert p.totals.gain_loss_amount == Decimal("-1150.00")


def test_parse_empty_portfolio(fixture_html):
    p = parse_portfolio(fixture_html("portfolio_empty.html"))

    assert p.cash.actual_balance == Decimal("50000.00")
    assert p.cash.buying_power == Decimal("100000.00")
    assert p.equities == []
    assert p.mutual_funds == []
    assert p.equities_total is None
    assert p.totals.trade_value == Decimal("0.00")


def test_portfolio_agent_requests_endpoint(fixture_html):
    source = FakeSource(fixture_html("portfolio_empty.html"))
    PortfolioAgent(source).get_portfolio()

    assert source.requests == [(PORTFOLIO_PATH, {})]
