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


# --- Quotes tab: stock information (quotes/Pse_Quote_2_DB.asp) -------------


class StockDepthLevel(BaseModel):
    """One row of the Quotes-tab depth grid — like DepthLevel but the grid
    also shows how many posted orders sit at each price."""

    bid_orders: int
    bid_volume: int
    bid_price: Decimal
    offer_price: Decimal
    offer_volume: int
    offer_orders: int


class TradeTick(BaseModel):
    """A row of the Last 5 Trades table. Broker names arrive truncated to
    8 chars by the platform; kept verbatim."""

    time: str
    volume: int
    price: Decimal
    buyer: str
    seller: str


class StockStats(BaseModel):
    """The 23-row label/value stats table on the Quotes-tab stock page."""

    previous: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    value: Decimal | None = None
    trades: int | None = None
    volume: int | None = None
    outstanding: int | None = None
    market_cap: Decimal | None = None
    inst_status: str | None = None
    market_status: str | None = None
    board_lot: int | None = None
    fluctuation: Decimal | None = None
    floor_price: Decimal | None = None
    ceiling_price: Decimal | None = None
    dyn_t_low: Decimal | None = None
    dyn_t_high: Decimal | None = None
    par_value: Decimal | None = None
    margin_rate_pct: Decimal | None = None
    open_to_foreigners: str | None = None


class StockInfo(BaseModel):
    symbol: str | None = None
    company_name: str
    last: Decimal
    change: Decimal
    pct_change: Decimal
    direction: Direction
    depth: list[StockDepthLevel] = Field(default_factory=list, max_length=5)
    last_trades: list[TradeTick] = Field(default_factory=list)
    stats: StockStats = Field(default_factory=StockStats)


class BrokerSide(str, Enum):
    BUYERS = "buyers"
    SELLERS = "sellers"


class BrokerActivityRow(BaseModel):
    rank: int
    broker: str  # truncated to 12 chars by the platform; kept verbatim
    volume: int
    amount: Decimal
    average_price: Decimal
    pct_market: Decimal


class BrokerActivity(BaseModel):
    symbol: str | None = None
    side: BrokerSide
    rows: list[BrokerActivityRow] = Field(default_factory=list)
    as_of: str | None = None  # "Values displayed as of <time>"


class TopBrokers(BaseModel):
    symbol: str | None = None
    buyers: BrokerActivity
    sellers: BrokerActivity


class TradePriceRow(BaseModel):
    price: Decimal
    volume: int
    amount: Decimal
    trades: int
    pct_of_value: Decimal


class TradePrices(BaseModel):
    symbol: str | None = None
    company_name: str | None = None
    rows: list[TradePriceRow] = Field(default_factory=list)
    average_price: Decimal | None = None
    total_volume: int | None = None
    total_amount: Decimal | None = None
    total_trades: int | None = None


# --- Research: Technical Guide (Research/TECHGUIDE_Mid.asp) -----------------


class LevelRole(str, Enum):
    """What a support/resistance level is currently acting as. Encoded by the
    nested font color on the value: red = resistance, black = support."""

    SUPPORT = "support"
    RESISTANCE = "resistance"


class TechGuideEntry(BaseModel):
    """One row of the Technical Guide table. Trend and recommendation are the
    platform's own vocabulary, kept verbatim (observed: trend UP | DOWN |
    SIDEWAYS; recommendation BUY | HOLD | SELL | SELL INTO STRENGTH | LIGHTEN |
    RANGE TRADE | TAKE PROFITS)."""

    ticker: str
    company_name: str
    sector: str | None = None  # the guide's own grouping, incl. "Index"
    price: Decimal | None = None
    short_term: Decimal | None = None
    short_term_role: LevelRole | None = None
    medium_term: Decimal | None = None
    medium_term_role: LevelRole | None = None
    week52_high: Decimal | None = None
    week52_low: Decimal | None = None
    pct_from_week52_high: Decimal | None = None
    trend: str | None = None
    recommendation: str | None = None
    rating_initiated: str | None = None  # date the recommendation first triggered


class TechnicalGuide(BaseModel):
    as_of: str | None = None  # publication date from the header fragment
    entries: list[TechGuideEntry] = Field(default_factory=list)


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
