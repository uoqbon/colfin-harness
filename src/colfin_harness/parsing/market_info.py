"""Parsers for the Quotes tab's Market Information pages (docs/read-only-agents.md,
"Market Information sub-tab"). Mapped 2026-07-10 from a live session.

Three fragments, anchor/position based like the rest of parsing/:

- INDEX_AU_2DB.asp (Summary) — `id="mytable"` holds the Market Indices grid
  (Index · Previous · Current · %Change · Change; 8 rows: PSE Composite,
  All Shares, and the six sector indices) and a label/value breadth table
  (Total Trades/Value/Volume, Up/Down/Unch Volume, Advances/Declines/
  Unchanged). A "Market Status: <text>" header line sits above the grid.
- PSE_GainerLoser_2.asp — two 21-row tables: `id="mytable"` (Top Gainers) and
  `id="mytable2"` (Top Losers); 6 columns: # · Stock Code · Last · Change ·
  %Change · Value. Losers carry explicit minus signs.
- Pse_MostActive_2.asp — `id="mytable"`, 20 rows by trade value; 10 columns:
  # · Stock Code · Last · Change · %Change · High · Low · Open · Volume · Value.

Font colors (green/red/#FF6600) decorate direction but the sign always lives
in the text — except on the Summary grid, where positives print unsigned and
the color is the sign authority: parsed change/%change are re-signed to match
it. Halted/suspended rows print '-' values; they are kept with None fields
rather than dropped, so a rank gap always means a shape change.
"""

from bs4 import BeautifulSoup, Tag

from colfin_harness.exceptions import ParseError
from colfin_harness.parsing.quotes import direction_from
from colfin_harness.parsing.util import to_decimal, to_int
from colfin_harness.schemas import (
    Direction,
    GainersLosers,
    IndexQuote,
    MarketBreadth,
    MarketSummary,
    MostActive,
    MostActiveRow,
    MoverRow,
)

# Breadth-table labels -> MarketBreadth fields.
_BREADTH_FIELDS = {
    "total trades": ("total_trades", to_int),
    "total value": ("total_value", to_decimal),
    "total volume": ("total_volume", to_int),
    "up volume": ("up_volume", to_int),
    "down volume": ("down_volume", to_int),
    "unch volume": ("unchanged_volume", to_int),
    "advances": ("advances", to_int),
    "declines": ("declines", to_int),
    "unchanged": ("unchanged", to_int),
}

_MARKET_STATUS_PREFIX = "market status:"


def _cells(tr: Tag) -> list[str]:
    return [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]


def _cell_font_color(tr: Tag, index: int) -> str | None:
    tds = tr.find_all(["td", "th"])
    if index >= len(tds):
        return None
    font = tds[index].find("font")
    return font.get("color") if font is not None else None


def parse_market_summary(html: str) -> MarketSummary:
    soup = BeautifulSoup(html, "lxml")
    mytable = soup.find(id="mytable")
    if not isinstance(mytable, Tag):
        snippet = soup.get_text(" ", strip=True)[:120]
        raise ParseError(f"market-summary fragment: no indices table: {snippet}")

    indices: list[IndexQuote] = []
    for tr in mytable.find_all("tr"):
        cells = _cells(tr)
        if len(cells) != 5:
            continue
        previous, current = to_decimal(cells[1]), to_decimal(cells[2])
        pct_change, change = to_decimal(cells[3]), to_decimal(cells[4])
        if previous is None or current is None:
            continue  # header row
        # Positives print unsigned here, so the font color (green/red) is the
        # sign authority — with current - previous, computable on every row,
        # breaking a colorless tie. Re-sign the printed values to match, or an
        # unsigned down-row would report a positive change with direction=down.
        direction = direction_from(_cell_font_color(tr, 3), current - previous)
        if direction is Direction.DOWN:
            if change is not None and change > 0:
                change = -change
            if pct_change is not None and pct_change > 0:
                pct_change = -pct_change
        indices.append(
            IndexQuote(
                name=cells[0].replace("\xa0", " ").strip(),
                previous=previous,
                current=current,
                change=change,
                pct_change=pct_change,
                direction=direction,
            )
        )
    if not indices:
        raise ParseError("market-summary fragment: indices table had no data rows")

    breadth = MarketBreadth()
    for tr in soup.find_all("tr"):
        if tr.find_parent(id="mytable") is not None:
            continue
        cells = _cells(tr)
        if len(cells) != 2:
            continue
        label = cells[0].rstrip(":").strip().lower()
        if label in _BREADTH_FIELDS:
            field, convert = _BREADTH_FIELDS[label]
            value = convert(cells[1])
            if value is not None:
                setattr(breadth, field, value)

    market_status = None
    for text in soup.stripped_strings:
        lowered = text.lower()
        if lowered.startswith(_MARKET_STATUS_PREFIX):
            market_status = text[len(_MARKET_STATUS_PREFIX) :].strip() or None
            break

    return MarketSummary(market_status=market_status, indices=indices, breadth=breadth)


def _parse_mover_table(table: Tag) -> list[MoverRow]:
    rows: list[MoverRow] = []
    for tr in table.find_all("tr"):
        cells = _cells(tr)
        if len(cells) != 6:
            continue
        # Data rows anchor on rank + symbol so a halted stock's '-' values
        # keep their row (as Nones) instead of silently shrinking the top 20.
        rank, symbol = to_int(cells[0]), cells[1].strip()
        if rank is None or not symbol:
            continue  # header row
        rows.append(
            MoverRow(
                rank=rank,
                symbol=symbol,
                last=to_decimal(cells[2]),
                change=to_decimal(cells[3]),
                pct_change=to_decimal(cells[4]),
                value=to_decimal(cells[5]),
            )
        )
    return rows


def parse_gainers_losers(html: str) -> GainersLosers:
    """Both tables must exist even when empty (pre-open renders headers only);
    a missing table means the page shape changed and should fail loudly."""
    soup = BeautifulSoup(html, "lxml")
    gainers_table = soup.find(id="mytable")
    losers_table = soup.find(id="mytable2")
    if not isinstance(gainers_table, Tag) or not isinstance(losers_table, Tag):
        snippet = soup.get_text(" ", strip=True)[:120]
        raise ParseError(f"gainers-losers fragment: missing mytable/mytable2: {snippet}")
    return GainersLosers(
        gainers=_parse_mover_table(gainers_table),
        losers=_parse_mover_table(losers_table),
    )


def parse_most_active(html: str) -> MostActive:
    soup = BeautifulSoup(html, "lxml")
    mytable = soup.find(id="mytable")
    if not isinstance(mytable, Tag):
        snippet = soup.get_text(" ", strip=True)[:120]
        raise ParseError(f"most-active fragment: no data table: {snippet}")

    rows: list[MostActiveRow] = []
    for tr in mytable.find_all("tr"):
        cells = _cells(tr)
        if len(cells) != 10:
            continue
        # Same rank + symbol anchor as the mover tables: '-' values on a
        # halted stock become Nones, not a dropped row.
        rank, symbol = to_int(cells[0]), cells[1].strip()
        if rank is None or not symbol:
            continue  # header row
        change = to_decimal(cells[3])
        # A halted row's '-' cell can keep its old font color; a color with no
        # number is not a direction signal, so don't let it contradict the
        # None change.
        direction = (
            direction_from(_cell_font_color(tr, 3), change)
            if change is not None
            else Direction.FLAT
        )
        rows.append(
            MostActiveRow(
                rank=rank,
                symbol=symbol,
                last=to_decimal(cells[2]),
                change=change,
                pct_change=to_decimal(cells[4]),
                direction=direction,
                high=to_decimal(cells[5]),
                low=to_decimal(cells[6]),
                open=to_decimal(cells[7]),
                volume=to_int(cells[8]),
                value=to_decimal(cells[9]),
            )
        )
    return MostActive(rows=rows)
