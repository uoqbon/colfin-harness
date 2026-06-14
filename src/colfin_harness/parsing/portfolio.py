"""Parser for the portfolio fragment (As_CashBalStockPos_MF.asp).

The page is deeply nested legacy-ASP tables with no per-field ids. Strategy
(per docs/read-only-agents.md):

- walk only *leaf* <tr> rows — rows containing no nested <table>;
- a holding row has >= 11 cells and a 2–5 char uppercase code in column 2;
- section boundaries and totals anchor on label text in document order:
  Actual Balance / Buying Power → TOTAL EQUITIES → TOTAL MUTUAL FUNDS →
  TOTAL PORTFOLIO TRADE VALUE / DAY CHANGE / PORTFOLIO GAIN/LOSS.
  Rows before the TOTAL EQUITIES marker are equities; after it, mutual funds.
"""

import re

from bs4 import BeautifulSoup

from colfin_harness.parsing.util import numbers_in, to_decimal
from colfin_harness.schemas import (
    CashBalance,
    EquityHolding,
    MutualFundHolding,
    Portfolio,
    PortfolioTotals,
    SectionTotal,
)

_CODE_RE = re.compile(r"^[A-Z0-9]{2,5}$")


def _leaf_rows(soup: BeautifulSoup) -> list[list[str]]:
    rows = []
    for tr in soup.find_all("tr"):
        if tr.find("table") is None:
            rows.append([td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])])
    return rows


def _section_total(cells: list[str]) -> SectionTotal:
    nums = numbers_in(cells)
    return SectionTotal(
        market_value=nums[0] if nums else None,
        gain_loss=nums[1] if len(nums) > 1 else None,
        pct_gain_loss=nums[2] if len(nums) > 2 else None,
    )


def _pct_and_amount(cells: list[str]) -> tuple:
    """Split a totals row into (percentage, amount) using the % sign as anchor."""
    pct = amount = None
    for cell in cells:
        value = to_decimal(cell)
        if value is None:
            continue
        if "%" in cell and pct is None:
            pct = value
        elif amount is None:
            amount = value
    return pct, amount


def _cash(rows: list[list[str]], idx: int) -> CashBalance:
    # Values sit either in the cells right of the labels, or in the next
    # leaf row aligned under them.
    nums = numbers_in(rows[idx])
    if not nums and idx + 1 < len(rows):
        nums = numbers_in(rows[idx + 1])
    return CashBalance(
        actual_balance=nums[0] if nums else None,
        buying_power=nums[1] if len(nums) > 1 else None,
    )


def _holding_fields(cells: list[str]) -> dict:
    return dict(
        action=cells[0] or None,
        code=cells[1],
        name=cells[2],
        portfolio_pct=to_decimal(cells[3]),
        average_price=to_decimal(cells[5]),
        total_shares=to_decimal(cells[6]),
        uncommitted_shares=to_decimal(cells[7]),
        market_value=to_decimal(cells[8]),
        gain_loss=to_decimal(cells[9]),
        pct_gain_loss=to_decimal(cells[10]),
    )


def parse_portfolio(html: str) -> Portfolio:
    soup = BeautifulSoup(html, "lxml")
    rows = _leaf_rows(soup)

    portfolio = Portfolio()
    in_funds = False  # flips at the TOTAL EQUITIES marker

    for idx, cells in enumerate(rows):
        if not cells:
            continue
        joined = " ".join(cells).upper()

        if "ACTUAL BALANCE" in joined:
            portfolio.cash = _cash(rows, idx)
        elif "TOTAL PORTFOLIO TRADE VALUE" in joined:
            nums = numbers_in(cells)
            portfolio.totals.trade_value = nums[0] if nums else None
        elif "TOTAL EQUITIES" in joined:
            portfolio.equities_total = _section_total(cells)
            in_funds = True
        elif "TOTAL MUTUAL FUNDS" in joined:
            portfolio.mutual_funds_total = _section_total(cells)
        elif "DAY CHANGE" in joined:
            pct, amount = _pct_and_amount(cells)
            portfolio.totals.day_change_pct = pct
            portfolio.totals.day_change_amount = amount
        elif "PORTFOLIO GAIN/LOSS" in joined:
            pct, amount = _pct_and_amount(cells)
            portfolio.totals.gain_loss_pct = pct
            portfolio.totals.gain_loss_amount = amount
        elif len(cells) >= 11 and _CODE_RE.match(cells[1]):
            fields = _holding_fields(cells)
            if in_funds:
                portfolio.mutual_funds.append(
                    MutualFundHolding(navps=to_decimal(cells[4]), **fields)
                )
            else:
                portfolio.equities.append(
                    EquityHolding(market_price=to_decimal(cells[4]), **fields)
                )

    return portfolio
