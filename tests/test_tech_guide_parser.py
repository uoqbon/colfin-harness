"""Technical Guide parser, agent, and tool (docs/read-only-agents.md,
"Agent 3"). Fixtures are synthetic, built from the 2026-07-07 live mapping."""

from decimal import Decimal

import pytest

from colfin_harness.agents.research import (
    TECH_GUIDE_HEADER_PATH,
    TECH_GUIDE_PATH,
    ResearchAgent,
)
from colfin_harness.exceptions import ParseError
from colfin_harness.parsing.tech_guide import parse_tech_guide_as_of, parse_technical_guide
from colfin_harness.schemas import LevelRole


# --- parser -----------------------------------------------------------------


def test_parse_entries_and_sectors(fixture_html):
    guide = parse_technical_guide(fixture_html("tech_guide.html"))

    assert [e.ticker for e in guide.entries] == ["PASHR", "PCOMP", "AUB", "DHI", "ZHI"]
    assert [e.sector for e in guide.entries] == [
        "Index",
        "Index",
        "Banks",
        "Banks",
        "Selected",
    ]


def test_parse_entry_fields(fixture_html):
    guide = parse_technical_guide(fixture_html("tech_guide.html"))
    aub = guide.entries[2]

    assert aub.ticker == "AUB"
    assert aub.company_name == "ASIA UNITED BANK"
    assert aub.price == Decimal("44.30")
    assert aub.short_term == Decimal("43.7902")
    assert aub.medium_term == Decimal("43.3315")
    assert aub.week52_high == Decimal("57.00")
    assert aub.week52_low == Decimal("36.15")
    assert aub.pct_from_week52_high == Decimal("-22.28")
    assert aub.trend == "UP"
    assert aub.recommendation == "HOLD"
    assert aub.rating_initiated == "6/10/2026"


def test_parse_level_roles_follow_font_color(fixture_html):
    """Black level values are acting support, red ones resistance — the same
    two-tone encoding as the "Support/Resistance" column heading."""
    guide = parse_technical_guide(fixture_html("tech_guide.html"))
    aub = guide.entries[2]  # price above both levels
    dhi = guide.entries[3]  # price below both levels

    assert aub.short_term_role is LevelRole.SUPPORT
    assert aub.medium_term_role is LevelRole.SUPPORT
    assert dhi.short_term_role is LevelRole.RESISTANCE
    assert dhi.medium_term_role is LevelRole.RESISTANCE


def test_parse_index_rows_are_entries_too(fixture_html):
    """The guide covers the PSE indices under an "Index" sector; they parse
    like stocks (thousands commas in prices, no ticker link)."""
    guide = parse_technical_guide(fixture_html("tech_guide.html"))
    pashr = guide.entries[0]

    assert pashr.sector == "Index"
    assert pashr.price == Decimal("3393")
    assert pashr.short_term == Decimal("3354")
    assert pashr.recommendation == "SELL INTO STRENGTH"


def test_parse_sub_peso_prices(fixture_html):
    zhi = parse_technical_guide(fixture_html("tech_guide.html")).entries[4]

    assert zhi.price == Decimal("0.0540")
    assert zhi.short_term == Decimal("0.0542")
    assert zhi.pct_from_week52_high == Decimal("-44.33")


def test_parse_header_rows_are_not_entries(fixture_html):
    """Neither the group-header row nor the "Ticker" column-header row may
    leak into the entries."""
    guide = parse_technical_guide(fixture_html("tech_guide.html"))

    assert all(e.ticker.isupper() for e in guide.entries)
    assert "Ticker" not in [e.ticker for e in guide.entries]


def test_parse_suspended_row_has_no_level_role(fixture_html):
    """A '-' level still renders inside a black font; that must not read as
    "acting support" — no value, no role."""
    html = fixture_html("tech_guide.html").replace(">44.30<", ">-<").replace(">43.7902<", ">-<")
    aub = [e for e in parse_technical_guide(html).entries if e.ticker == "AUB"][0]

    assert aub.price is None
    assert aub.short_term is None
    assert aub.short_term_role is None
    # the intact medium-term level keeps its role
    assert aub.medium_term == Decimal("43.3315")
    assert aub.medium_term_role is LevelRole.SUPPORT


def test_parse_ignores_rows_of_nested_tables(fixture_html):
    """An 11-cell row belonging to a table nested inside a data cell must not
    become a fake entry (leaf-row convention, cf. the portfolio parser)."""
    nested = "<table><tr>" + "<td>X1</td>" * 11 + "</tr></table>"
    html = fixture_html("tech_guide.html").replace(
        '<TD><font face="Helvetica" style="font-size: 11px">ASIA UNITED BANK</font></TD>',
        f"<TD>{nested}<font face=\"Helvetica\" style=\"font-size: 11px\">ASIA UNITED BANK</font></TD>",
        1,
    )
    guide = parse_technical_guide(html)

    assert [e.ticker for e in guide.entries] == ["PASHR", "PCOMP", "AUB", "DHI", "ZHI"]


def test_parse_anchors_past_a_menu_ticker_cell(fixture_html):
    """The live mid page has a floating sort menu that also contains a bare
    "Ticker" cell; if it ever precedes the data table, the anchor must skip it."""
    menu = "<table><tr><td>Ticker</td><td>Trend Mode</td></tr></table>"
    html = fixture_html("tech_guide.html").replace('<div align="center">', f'<div align="center">{menu}', 1)
    guide = parse_technical_guide(html)

    assert len(guide.entries) == 5


def test_parse_without_ticker_header_raises():
    with pytest.raises(ParseError):
        parse_technical_guide("<html><body><table><tr><td>nope</td></tr></table></body></html>")


def test_parse_header_only_table_raises(fixture_html):
    """A guide page with the header but no data rows (e.g. mid-publish) must
    fail loudly, not return an empty guide."""
    html = fixture_html("tech_guide.html")
    start = html.index("<TR>\n<TD colspan=\"11\"")
    end = html.index("</TABLE>")
    with pytest.raises(ParseError):
        parse_technical_guide(html[:start] + html[end:])


def test_parse_as_of_date(fixture_html):
    assert parse_tech_guide_as_of(fixture_html("tech_guide_top.html")) == "June 24, 2026"


def test_parse_as_of_missing_is_none():
    assert parse_tech_guide_as_of("<html><body>TECHNICAL GUIDE</body></html>") is None


# --- agent ------------------------------------------------------------------


class SequencedSource:
    """FragmentSource fake keyed by path, recording request order."""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.requests: list[tuple[str, dict]] = []

    def fetch_fragment(self, path, params=None):
        self.requests.append((path, dict(params or {})))
        return self.responses[path]


def _sequenced(fixture_html) -> SequencedSource:
    return SequencedSource(
        {
            TECH_GUIDE_PATH: fixture_html("tech_guide.html"),
            TECH_GUIDE_HEADER_PATH: fixture_html("tech_guide_top.html"),
        }
    )


def test_agent_fetches_table_then_header(fixture_html):
    source = _sequenced(fixture_html)
    guide = ResearchAgent(source).get_technical_guide()

    assert source.requests == [
        (TECH_GUIDE_PATH, {}),
        (TECH_GUIDE_HEADER_PATH, {}),
    ]
    assert guide.as_of == "June 24, 2026"
    assert len(guide.entries) == 5


# --- orchestrator tool --------------------------------------------------------


def _guide_tool(fixture_html):
    from colfin_harness.orchestrator.tools import build_default_registry

    registry = build_default_registry(
        None, None, None, None, ResearchAgent(_sequenced(fixture_html))
    )
    return registry.get("get_technical_guide").fn


def test_tool_symbol_filter_returns_single_entry(fixture_html):
    result = _guide_tool(fixture_html)(symbol="aub")

    assert '"ticker":"AUB"' in result
    assert "PASHR" not in result
    assert "June 24, 2026" in result


def test_tool_unknown_symbol_is_message_not_error(fixture_html):
    result = _guide_tool(fixture_html)(symbol="XXXX")

    assert "No Technical Guide entry" in result
    assert "XXXX" in result


def test_tool_recommendation_filter(fixture_html):
    result = _guide_tool(fixture_html)(recommendation="sell into strength")

    assert '"ticker":"PASHR"' in result
    assert '"ticker":"ZHI"' in result
    assert "AUB" not in result


def test_tool_no_args_returns_overview_not_dump(fixture_html):
    result = _guide_tool(fixture_html)()

    assert "5 entries" in result
    assert "HOLD (1): AUB" in result
    # overview lists tickers, not full serialized entries
    assert '"short_term"' not in result
