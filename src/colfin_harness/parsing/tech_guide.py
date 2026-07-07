"""Parser for the Research-tab Technical Guide (docs/read-only-agents.md,
"Agent 3").

The guide is a frameset: TECHGUIDE_Top.asp carries the "As of:" publication
date and the sort headings, TECHGUIDE_Mid.asp the data table. Anchor is the
column-header row whose first cell reads "Ticker" — the table has no id.
Rows below it alternate between sector separators (a single td spanning the
row, e.g. "Index", "Banks") and 11-cell data rows:

    Ticker · Company Name · Price · Short Term · Medium Term · 52Wk High ·
    52Wk Low · % From 52Wk High · Trend Mode · Recommendation · Rating Initiated

Short/Medium Term values carry their role in a nested font color, mirroring
the two-tone "Support/Resistance" heading: red = the level is acting as
resistance, black = support.
"""

import re

from bs4 import BeautifulSoup, Tag

from colfin_harness.exceptions import ParseError
from colfin_harness.parsing.util import to_decimal
from colfin_harness.schemas import LevelRole, TechGuideEntry, TechnicalGuide

# Tickers are short uppercase codes (letters, digits on a few like 2GO).
# Rejects the "Ticker" header cell itself via the lowercase letters.
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,8}$")

_AS_OF_RE = re.compile(r"as of:?\s*([A-Za-z]+\.?\s+\d{1,2},\s*\d{4})", re.IGNORECASE)

_RED = {"red", "#ff0000"}


def _cells(tr: Tag) -> list[Tag]:
    return tr.find_all(["td", "th"], recursive=False)


def _text(td: Tag) -> str:
    return td.get_text(" ", strip=True)


def _level_role(td: Tag) -> LevelRole | None:
    """Role of a support/resistance cell, from the innermost colored font."""
    font = td.find("font", attrs={"color": True})
    if font is None:
        return None
    color = str(font.get("color", "")).lower()
    return LevelRole.RESISTANCE if color in _RED else LevelRole.SUPPORT


def _is_column_header(td: Tag) -> bool:
    """True for the data table's own "Ticker" cell — its row has the full 11
    columns. The floating sort menu on the same page also contains a bare
    "Ticker" cell, so text alone is not a safe anchor."""
    tr = td.find_parent("tr")
    return tr is not None and len(_cells(tr)) == 11


def parse_technical_guide(html: str) -> TechnicalGuide:
    """Parse the TECHGUIDE_Mid.asp document into sector-tagged entries."""
    soup = BeautifulSoup(html, "lxml")

    anchor = next(
        (td for td in soup.find_all("td") if _text(td) == "Ticker" and _is_column_header(td)),
        None,
    )
    if anchor is None:
        snippet = soup.get_text(" ", strip=True)[:120]
        raise ParseError(f"technical guide: no Ticker header row: {snippet}")
    table = anchor.find_parent("table")

    entries: list[TechGuideEntry] = []
    sector: str | None = None
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue  # rows of tables nested inside cells are not guide rows
        cells = _cells(tr)
        # Sector separator: one cell spanning the full row.
        if len(cells) == 1 and cells[0].get("colspan"):
            label = _text(cells[0])
            if label:
                sector = label
            continue
        if len(cells) != 11:
            continue
        ticker = _text(cells[0])
        company = _text(cells[1])
        if not company or not _TICKER_RE.match(ticker):
            continue  # header rows, spacers
        texts = [_text(td) for td in cells]
        # A level's role only exists alongside a level: a suspended stock's
        # "-" still sits in a black font, which must not read as "support".
        short_term = to_decimal(texts[3])
        medium_term = to_decimal(texts[4])
        entries.append(
            TechGuideEntry(
                ticker=ticker,
                company_name=company,
                sector=sector,
                price=to_decimal(texts[2]),
                short_term=short_term,
                short_term_role=_level_role(cells[3]) if short_term is not None else None,
                medium_term=medium_term,
                medium_term_role=_level_role(cells[4]) if medium_term is not None else None,
                week52_high=to_decimal(texts[5]),
                week52_low=to_decimal(texts[6]),
                pct_from_week52_high=to_decimal(texts[7]),
                trend=texts[8] or None,
                recommendation=texts[9] or None,
                rating_initiated=texts[10] or None,
            )
        )

    if not entries:
        raise ParseError("technical guide: Ticker header present but no data rows")
    return TechnicalGuide(entries=entries)


def parse_tech_guide_as_of(html: str) -> str | None:
    """Publication date ("As of: June 24, 2026") from TECHGUIDE_Top.asp."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = _AS_OF_RE.search(text)
    return match.group(1) if match else None
