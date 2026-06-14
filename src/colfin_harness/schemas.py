"""Typed models for data parsed off COL Financial HTML fragments."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

# --- Quotes ---------------------------------------------------------------


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class DepthLevel(BaseModel):
    bid_volume: int
    bid_price: Decimal
    offer_price: Decimal
    offer_volume: int


class OHLC(BaseModel):
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None


class Quote(BaseModel):
    symbol: str | None = None
    company_name: str
    last: Decimal
    change: Decimal
    pct_change: Decimal
    direction: Direction
    depth: list[DepthLevel] = Field(default_factory=list, max_length=3)
    ohlc: OHLC = Field(default_factory=OHLC)
    trades: int | None = None
    value: Decimal | None = None
    volume: int | None = None


# --- Portfolio ------------------------------------------------------------


class CashBalance(BaseModel):
    actual_balance: Decimal | None = None
    buying_power: Decimal | None = None


class EquityHolding(BaseModel):
    action: str | None = None  # the BUY | SELL link cell, kept verbatim
    code: str
    name: str
    portfolio_pct: Decimal | None = None
    market_price: Decimal | None = None
    average_price: Decimal | None = None
    total_shares: Decimal | None = None
    uncommitted_shares: Decimal | None = None
    market_value: Decimal | None = None
    gain_loss: Decimal | None = None
    pct_gain_loss: Decimal | None = None


class MutualFundHolding(BaseModel):
    action: str | None = None
    code: str
    name: str
    portfolio_pct: Decimal | None = None
    navps: Decimal | None = None
    average_price: Decimal | None = None
    total_shares: Decimal | None = None
    uncommitted_shares: Decimal | None = None
    market_value: Decimal | None = None
    gain_loss: Decimal | None = None
    pct_gain_loss: Decimal | None = None


class SectionTotal(BaseModel):
    market_value: Decimal | None = None
    gain_loss: Decimal | None = None
    pct_gain_loss: Decimal | None = None


class PortfolioTotals(BaseModel):
    trade_value: Decimal | None = None
    day_change_pct: Decimal | None = None
    day_change_amount: Decimal | None = None
    gain_loss_pct: Decimal | None = None
    gain_loss_amount: Decimal | None = None


class Portfolio(BaseModel):
    cash: CashBalance = Field(default_factory=CashBalance)
    equities: list[EquityHolding] = Field(default_factory=list)
    mutual_funds: list[MutualFundHolding] = Field(default_factory=list)
    equities_total: SectionTotal | None = None
    mutual_funds_total: SectionTotal | None = None
    totals: PortfolioTotals = Field(default_factory=PortfolioTotals)


# --- Order entry (draft only — never submitted) -----------------------------


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderTerm(str, Enum):
    # Maps to the DAYGTC query param on Trd_EnterOrder.asp.
    DAY = "DAY"
    GTC = "GTC"


class OrderDraft(BaseModel):
    """A would-be order. The harness only ever prepares Step 1 of the wizard;
    Step 2 (preview/confirm) is the mandatory human checkpoint."""

    stock_code: str
    side: OrderSide
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    term: OrderTerm = OrderTerm.DAY
