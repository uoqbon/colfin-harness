"""Parsers for the Quotes-tab surfaces (docs/read-only-agents.md, "Quotes tab").

Three fragments, all anchor/position based like the rest of parsing/:

- Pse_Quote_2_DB.asp?q=SYM — `id="mytable"` depth grid (5 rows of 6 numeric
  cells: bid orders/size/price, ask price/size/orders), a "Last 5 Trades"
  table, and a label/value stats table. Last/Change/%Change carry direction
  in the font color, same encoding as the home quote box.
- TOPBUYER.asp / TOPSELLER.asp?varstock=SYM — a "TOP BUYERS"/"TOP SELLERS"
  title table and a 6-column broker table (rank · broker · vol · amt · ave ·
  % mkt).
- TRADEPRICES.asp — company-name header and a 6-column per-price table
  (rank · price · volume · amount · trades · percent) ending in a `Totals`
  row whose price cell reads `<ave>(ave)`.
"""

import re

from bs4 import BeautifulSoup, Tag

from colfin_harness.exceptions import ParseError, QuoteNotFound
from colfin_harness.parsing.quotes import company_name_from, direction_from
from colfin_harness.parsing.util import to_decimal, to_int
from colfin_harness.schemas import (
    BrokerActivity,
    BrokerActivityRow,
    BrokerSide,
    StockDepthLevel,
    StockInfo,
    StockStats,
    TradePriceRow,
    TradePrices,
    TradeTick,
)

# Stats-table labels -> StockStats fields. Label text is the anchor; the value
# is the row's other cell.
_STAT_FIELDS = {
    "previous": "previous",
    "open": "open",
    "high": "high",
    "low": "low",
    "value": "value",
    "trades": "trades",
    "volume": "volume",
    "outstanding": "outstanding",
    "market capitalization": "market_cap",
    "boardlot": "board_lot",
    "fluctuation": "fluctuation",
    "floor price": "floor_price",
    "ceilingprice": "ceiling_price",
    "dyn t low": "dyn_t_low",
    "dyn t high": "dyn_t_high",
    "par value": "par_value",
    "margin rate %": "margin_rate_pct",
}
_TEXT_STAT_FIELDS = {
    "inst. status": "inst_status",
    "market status": "market_status",
    "open to foreigners": "open_to_foreigners",
}
_INT_STATS = {"trades", "volume", "outstanding", "board_lot"}

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}")
_AS_OF_RE = re.compile(r"as of\s+(.+?)\s*$", re.IGNORECASE)


def _cells(tr: Tag) -> list[str]:
    return [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]


def _row_font_color(tr: Tag) -> str | None:
    for font in tr.find_all("font"):
        color = font.get("color")
        if color and color.lower() not in ("#ffffff", "white"):
            return color
    return None


def parse_stock_info(html: str, symbol: str | None = None) -> StockInfo:
    soup = BeautifulSoup(html, "lxml")
    mytable = soup.find(id="mytable")
    if not isinstance(mytable, Tag):
        snippet = soup.get_text(" ", strip=True)[:120]
        raise QuoteNotFound(f"no stock-info table for {symbol!r}: {snippet}")

    depth: list[StockDepthLevel] = []
    for tr in mytable.find_all("tr"):
        cells = _cells(tr)
        values = [to_decimal(c) for c in cells]
        # Cap like parse_quote does: a widened grid must degrade, not crash
        # against the schema's max_length.
        if len(cells) == 6 and all(v is not None for v in values) and len(depth) < 5:
            depth.append(
                StockDepthLevel(
                    bid_orders=int(values[0]),
                    bid_volume=int(values[1]),
                    bid_price=values[2],
                    offer_price=values[3],
                    offer_volume=int(values[4]),
                    offer_orders=int(values[5]),
                )
            )

    last_trades: list[TradeTick] = []
    for table in soup.find_all("table"):
        if "last 5 trades" not in table.get_text(" ", strip=True).lower():
            continue
        for tr in table.find_all("tr"):
            cells = _cells(tr)
            if len(cells) != 5 or not _TIME_RE.match(cells[0]):
                continue
            volume, price = to_int(cells[1]), to_decimal(cells[2])
            if volume is None or price is None:
                continue
            last_trades.append(
                TradeTick(
                    time=cells[0].strip(),
                    volume=volume,
                    price=price,
                    buyer=cells[3],
                    seller=cells[4],
                )
            )
        break

    # Stats table: 2-cell label/value rows anywhere outside mytable. The
    # header trio (Last/Change/%Change) lives here too, with direction in
    # the value's font color.
    stats = StockStats()
    header: dict[str, tuple[Tag, str]] = {}
    for tr in soup.find_all("tr"):
        if tr.find_parent(id="mytable") is not None:
            continue
        cells = _cells(tr)
        if len(cells) != 2:
            continue
        label, raw = cells[0].rstrip(":").strip().lower(), cells[1]
        if label in ("last", "change", "%change"):
            header[label] = (tr, raw)
        elif label in _STAT_FIELDS:
            value = to_decimal(raw)
            field = _STAT_FIELDS[label]
            if value is not None:
                setattr(stats, field, int(value) if field in _INT_STATS else value)
        elif label in _TEXT_STAT_FIELDS:
            setattr(stats, _TEXT_STAT_FIELDS[label], raw.strip() or None)

    missing = [k for k in ("last", "change", "%change") if k not in header]
    if missing:
        raise ParseError(f"stock-info fragment for {symbol!r}: missing stats rows {missing}")
    last = to_decimal(header["last"][1])
    change = to_decimal(header["change"][1])
    pct_change = to_decimal(header["%change"][1])
    if last is None or change is None or pct_change is None:
        raise ParseError(f"stock-info fragment for {symbol!r}: non-numeric last/change row")

    return StockInfo(
        symbol=symbol,
        company_name=company_name_from(soup, mytable),
        last=last,
        change=change,
        pct_change=pct_change,
        direction=direction_from(_row_font_color(header["last"][0]), change),
        depth=depth,
        last_trades=last_trades,
        stats=stats,
    )


def parse_broker_activity(html: str, symbol: str | None = None) -> BrokerActivity:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    lowered = text.lower()
    if "top buyers" in lowered:
        side = BrokerSide.BUYERS
    elif "top sellers" in lowered:
        side = BrokerSide.SELLERS
    else:
        raise ParseError(f"broker-activity fragment for {symbol!r}: no TOP BUYERS/SELLERS title")

    rows: list[BrokerActivityRow] = []
    for tr in soup.find_all("tr"):
        cells = _cells(tr)
        if len(cells) != 6:
            continue
        rank = to_int(cells[0])
        volume, amount = to_int(cells[2]), to_decimal(cells[3])
        average, pct = to_decimal(cells[4]), to_decimal(cells[5])
        if None in (rank, volume, amount, average, pct):
            continue  # header row, or the empty bare-fetch table
        rows.append(
            BrokerActivityRow(
                rank=rank,
                broker=cells[1].strip(),
                volume=volume,
                amount=amount,
                average_price=average,
                pct_market=pct,
            )
        )

    as_of = _AS_OF_RE.search(text)
    return BrokerActivity(
        symbol=symbol,
        side=side,
        rows=rows,
        as_of=as_of.group(1) if as_of else None,
    )


def parse_trade_prices(html: str, symbol: str | None = None) -> TradePrices:
    soup = BeautifulSoup(html, "lxml")

    rows: list[TradePriceRow] = []
    result = TradePrices(symbol=symbol)
    for tr in soup.find_all("tr"):
        cells = _cells(tr)
        if len(cells) != 6:
            continue
        if cells[0].strip().lower() == "totals":
            result.average_price = to_decimal(cells[1].replace("(ave)", ""))
            result.total_volume = to_int(cells[2])
            result.total_amount = to_decimal(cells[3])
            result.total_trades = to_int(cells[4])
            continue
        rank = to_int(cells[0])
        price, volume = to_decimal(cells[1]), to_int(cells[2])
        amount, trades, pct = to_decimal(cells[3]), to_int(cells[4]), to_decimal(cells[5])
        if None in (rank, price, volume, amount, trades, pct):
            continue  # header row
        rows.append(
            TradePriceRow(
                price=price, volume=volume, amount=amount, trades=trades, pct_of_value=pct
            )
        )
    if not rows and result.total_volume is None:
        raise ParseError(f"trade-prices fragment for {symbol!r}: no per-price rows found")
    result.rows = rows

    # Company name: the gray header line's bold text. The data table (class
    # "reference") also bolds its column headers and Totals row, so only look
    # outside it — better no name than "Price".
    for b in soup.find_all(["b", "strong"]):
        if b.find_parent("table", class_="reference") is not None:
            continue
        name = b.get_text(" ", strip=True)
        if name and to_decimal(name) is None:
            result.company_name = name
            break
    return result
