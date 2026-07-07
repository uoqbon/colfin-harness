"""Parser for the quote fragment (Pse_Quote_AU_DB.asp?q=SYMBOL).

The fragment has no per-field ids except `id="mytable"` (depth + OHLC grid),
so everything anchors on structure:

- header block (before mytable): company name in the first bold/text cell;
  last / net change / % change rendered as <font color=...> — the color
  encodes direction (red = down, green = up).
- mytable: rows whose 4 cells are all numeric are the 3 depth levels
  (Bid Vol · Bid Price · Offer Price · Offer Vol); the remaining rows are
  label/value pairs (Open, High, Low, Trades, Value, Vol).
"""

from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from colfin_harness.exceptions import ParseError, QuoteNotFound
from colfin_harness.parsing.util import to_decimal, to_int
from colfin_harness.schemas import OHLC, DepthLevel, Direction, Quote

_DOWN_COLORS = ("red", "#ff0000", "#cc0000", "#c00000")
_UP_COLORS = ("green", "#008000", "#00a000", "#00ff00")

_STAT_LABELS = {"open", "high", "low", "trades", "value", "vol", "volume"}


def direction_from(color: str | None, change: Decimal) -> Direction:
    c = (color or "").lower()
    if any(k in c for k in _DOWN_COLORS):
        return Direction.DOWN
    if any(k in c for k in _UP_COLORS):
        return Direction.UP
    if change > 0:
        return Direction.UP
    if change < 0:
        return Direction.DOWN
    return Direction.FLAT


def company_name_from(soup: BeautifulSoup, mytable: Tag) -> str:
    # First bold text outside mytable, else first non-numeric cell text.
    for b in soup.find_all(["b", "strong"]):
        if b.find_parent(id="mytable") is None:
            text = b.get_text(" ", strip=True)
            if text and to_decimal(text) is None:
                return text
    for td in soup.find_all("td"):
        if td.find_parent(id="mytable") is None and td.find("table") is None:
            text = td.get_text(" ", strip=True)
            if text and to_decimal(text) is None:
                return text
    raise ParseError("quote fragment: could not locate company name")


def parse_quote(html: str, symbol: str | None = None) -> Quote:
    soup = BeautifulSoup(html, "lxml")
    mytable = soup.find(id="mytable")
    if not isinstance(mytable, Tag):
        snippet = soup.get_text(" ", strip=True)[:120]
        raise QuoteNotFound(f"no quote table for {symbol!r}: {snippet}")

    # Header trio: the colored numeric values before mytable, in document
    # order, are last price, net change, % change.
    colored: list[tuple[str, Decimal]] = []
    for font in soup.find_all("font"):
        if font.find_parent(id="mytable") is not None or not font.get("color"):
            continue
        value = to_decimal(font.get_text(strip=True))
        if value is not None:
            colored.append((font["color"], value))
    if len(colored) < 3:
        raise ParseError(
            f"quote fragment for {symbol!r}: expected 3 colored header values "
            f"(last/change/%change), found {len(colored)}"
        )
    last, change, pct_change = (v for _, v in colored[:3])

    depth: list[DepthLevel] = []
    stats: dict[str, Decimal | None] = {}
    for tr in mytable.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        values = [to_decimal(c) for c in cells]
        if len(cells) == 4 and all(v is not None for v in values) and len(depth) < 3:
            depth.append(
                DepthLevel(
                    bid_volume=int(values[0]),
                    bid_price=values[1],
                    offer_price=values[2],
                    offer_volume=int(values[3]),
                )
            )
            continue
        for i, cell in enumerate(cells[:-1]):
            label = cell.rstrip(":").strip().lower()
            if label in _STAT_LABELS:
                stats[label] = to_decimal(cells[i + 1])

    volume = stats.get("vol", stats.get("volume"))
    trades = stats.get("trades")
    return Quote(
        symbol=symbol,
        company_name=company_name_from(soup, mytable),
        last=last,
        change=change,
        pct_change=pct_change,
        direction=direction_from(colored[1][0], change),
        depth=depth,
        ohlc=OHLC(open=stats.get("open"), high=stats.get("high"), low=stats.get("low")),
        trades=int(trades) if trades is not None else None,
        value=stats.get("value"),
        volume=int(volume) if volume is not None else None,
    )
