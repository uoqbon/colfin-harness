"""Market Information parsers and agent, against real scrubbed fixtures
(captured 2026-07-10 — see docs/read-only-agents.md, "Market Information")."""

from decimal import Decimal

import pytest

from colfin_harness.agents.market_info import (
    GAINERS_LOSERS_PATH,
    MARKET_SUMMARY_PATH,
    MOST_ACTIVE_PATH,
    MarketInfoAgent,
)
from colfin_harness.exceptions import ParseError
from colfin_harness.parsing.market_info import (
    parse_gainers_losers,
    parse_market_summary,
    parse_most_active,
)
from colfin_harness.schemas import Direction

from conftest import FakeSource


# --- market summary -----------------------------------------------------------


def test_parse_market_summary_indices(fixture_html):
    summary = parse_market_summary(fixture_html("market_summary.html"))

    assert [i.name for i in summary.indices] == [
        "PSE Composite",
        "All Shares",
        "Financials",
        "Industrial",
        "Holding Firms",
        "Property",
        "Service",
        "Mining and Oil",
    ]
    psei = summary.indices[0]
    assert psei.previous == Decimal("6223.87")
    assert psei.current == Decimal("6286.70")
    assert psei.pct_change == Decimal("1.01")
    assert psei.change == Decimal("62.83")
    assert psei.direction is Direction.UP


def test_parse_market_summary_down_row_is_resigned(fixture_html):
    """Summary positives print unsigned, so a red unsigned row must not only
    read as DOWN — its change/%change must come back negative, or the payload
    handed to the model contradicts itself."""
    html = (
        fixture_html("market_summary.html")
        .replace('color="green">1.01', 'color="red">1.01')
        .replace('color="green">62.83', 'color="red">62.83')
    )
    psei = parse_market_summary(html).indices[0]

    assert psei.direction is Direction.DOWN
    assert psei.change == Decimal("-62.83")
    assert psei.pct_change == Decimal("-1.01")


def test_parse_market_summary_colorless_tiebreak_uses_current_minus_previous(fixture_html):
    """With an unrecognized font color, current - previous — not the unsigned
    printed change — must decide the direction (and re-sign the values)."""
    html = (
        fixture_html("market_summary.html")
        .replace('color="green">1.01', 'color="#123456">1.01')
        .replace('color="green">62.83', 'color="#123456">62.83')
        # previous > current: a down move that still prints unsigned
        .replace(">6,223.87<", ">6,349.53<")
    )
    psei = parse_market_summary(html).indices[0]

    assert psei.previous == Decimal("6349.53")
    assert psei.current == Decimal("6286.70")
    assert psei.direction is Direction.DOWN
    assert psei.change == Decimal("-62.83")
    assert psei.pct_change == Decimal("-1.01")


def test_parse_market_summary_breadth(fixture_html):
    breadth = parse_market_summary(fixture_html("market_summary.html")).breadth

    assert breadth.total_trades == 81173
    assert breadth.total_value == Decimal("6775041069.50")
    assert breadth.total_volume == 1131732160
    assert breadth.up_volume == 652807725
    assert breadth.down_volume == 302918075
    assert breadth.unchanged_volume == 176006360
    assert breadth.advances == 102
    assert breadth.declines == 82
    assert breadth.unchanged == 61


def test_parse_market_summary_market_status(fixture_html):
    summary = parse_market_summary(fixture_html("market_summary.html"))

    assert summary.market_status == "Closed..."


def test_parse_market_summary_empty_raises():
    with pytest.raises(ParseError):
        parse_market_summary("<html><body></body></html>")


# --- gainers / losers -----------------------------------------------------------


def test_parse_gainers_losers_shapes(fixture_html):
    gl = parse_gainers_losers(fixture_html("gainers_losers.html"))

    assert len(gl.gainers) == 20
    assert len(gl.losers) == 20
    assert [r.rank for r in gl.gainers] == list(range(1, 21))


def test_parse_gainers_first_row(fixture_html):
    top = parse_gainers_losers(fixture_html("gainers_losers.html")).gainers[0]

    assert top.symbol == "NI"  # trailing space in the cell must be stripped
    assert top.last == Decimal("0.4600")
    assert top.change == Decimal("0.0700")
    assert top.pct_change == Decimal("17.95")
    assert top.value == Decimal("46000")


def test_parse_losers_have_negative_changes(fixture_html):
    losers = parse_gainers_losers(fixture_html("gainers_losers.html")).losers

    assert losers[0].symbol == "RRHI"
    assert losers[0].change == Decimal("-8.7500")
    assert losers[0].pct_change == Decimal("-18.72")
    assert all(r.change < 0 for r in losers)
    # comma-formatted price on the last row
    assert losers[19].symbol == "GLOBB"
    assert losers[19].last == Decimal("1988.0000")


def test_parse_gainers_losers_missing_table_raises(fixture_html):
    html = fixture_html("gainers_losers.html").replace('id="mytable2"', 'id="other"')
    with pytest.raises(ParseError):
        parse_gainers_losers(html)


def test_parse_gainers_halted_row_kept_with_none_values(fixture_html):
    """A halted stock's '-' values must keep their row (as Nones) — the top-20
    list silently shrinking would be indistinguishable from a shape change."""
    html = (
        fixture_html("gainers_losers.html")
        .replace('color="#008000">0.4600', 'color="#008000">-')
        .replace('color="#008000">0.0700', 'color="#008000">-')
        .replace('color="#008000">17.95%', 'color="#008000">-')
    )
    gainers = parse_gainers_losers(html).gainers

    assert len(gainers) == 20
    halted = gainers[0]
    assert halted.symbol == "NI"
    assert halted.rank == 1
    assert halted.last is None
    assert halted.change is None
    assert halted.pct_change is None
    assert halted.value == Decimal("46000")


def test_parse_gainers_losers_headers_only_is_empty_not_error():
    """Pre-open, the tables render with headers and no data rows — that is a
    legitimate empty result, not a parse failure."""
    header = (
        "<tr><th>#</th><th>Stock Code</th><th>Last</th>"
        "<th>Change</th><th>%Change</th><th>Value</th></tr>"
    )
    html = (
        "<html><body>"
        f'<table id="mytable">{header}</table>'
        f'<table id="mytable2">{header}</table>'
        "</body></html>"
    )
    gl = parse_gainers_losers(html)

    assert gl.gainers == []
    assert gl.losers == []


# --- most active -----------------------------------------------------------------


def test_parse_most_active_rows(fixture_html):
    active = parse_most_active(fixture_html("most_active.html"))

    assert len(active.rows) == 20
    first = active.rows[0]
    assert first.rank == 1
    assert first.symbol == "ICT"
    assert first.last == Decimal("985.0000")
    assert first.change == Decimal("13.5000")
    assert first.pct_change == Decimal("1.39")
    assert first.direction is Direction.UP
    assert first.high == Decimal("987.5000")
    assert first.low == Decimal("950.5000")
    assert first.open == Decimal("963.0000")
    assert first.volume == 2505100
    assert first.value == Decimal("2446265600")


def test_parse_most_active_down_and_flat_rows(fixture_html):
    rows = parse_most_active(fixture_html("most_active.html")).rows

    plus = next(r for r in rows if r.symbol == "PLUS")
    assert plus.change == Decimal("-0.4800")
    assert plus.direction is Direction.DOWN
    # unchanged stocks render 0.0000 in #FF6600, neither red nor green
    mynld = next(r for r in rows if r.symbol == "MYNLD")
    assert mynld.change == Decimal("0.0000")
    assert mynld.direction is Direction.FLAT


def test_parse_most_active_halted_row_kept_with_none_values(fixture_html):
    html = (
        fixture_html("most_active.html")
        .replace('color="green"><b>985.0000</b>', 'color="green"><b>-</b>')
        .replace('color="green">13.5000', 'color="green">-')
        .replace('color="green">1.39%', 'color="green">-')
    )
    rows = parse_most_active(html).rows

    assert len(rows) == 20
    halted = rows[0]
    assert halted.symbol == "ICT"
    assert halted.last is None
    assert halted.change is None
    assert halted.pct_change is None
    assert halted.volume == 2505100  # untouched cells still parse


def test_parse_most_active_empty_raises():
    with pytest.raises(ParseError):
        parse_most_active("<html><body></body></html>")


# --- agent request protocol -------------------------------------------------------


def test_agent_paths_take_no_params(fixture_html):
    for method, path, fixture in [
        ("get_market_summary", MARKET_SUMMARY_PATH, "market_summary.html"),
        ("get_gainers_losers", GAINERS_LOSERS_PATH, "gainers_losers.html"),
        ("get_most_active", MOST_ACTIVE_PATH, "most_active.html"),
    ]:
        source = FakeSource(fixture_html(fixture))
        getattr(MarketInfoAgent(source), method)()
        assert source.requests == [(path, {})]
