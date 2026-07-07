"""Tool registry the VLM reasons over.

Gemma has no native function calling, so tools are described in the system
prompt and invoked via the JSON protocol in loop.py. Tool functions return a
ToolResult (or plain string); `images` lets a tool feed screenshots into the
model's next vision turn.
"""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    text: str
    images: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, str]  # arg name -> human description
    fn: Callable[..., ToolResult | str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def render_catalog(self) -> str:
        lines = []
        for tool in self._tools.values():
            params = ", ".join(f"{k}: {v}" for k, v in tool.parameters.items()) or "none"
            lines.append(f"- {tool.name}({params}): {tool.description}")
        return "\n".join(lines)


def build_default_registry(session, quotes, portfolio, order_entry) -> ToolRegistry:
    """Wire the standard tool set: read-only data, vision, and the gated
    order-entry probe. Nothing here can submit an order."""
    registry = ToolRegistry()

    def get_quote(symbol: str) -> str:
        return quotes.get_quote(symbol).model_dump_json()

    def get_stock_info(symbol: str) -> str:
        return quotes.get_stock_info(symbol).model_dump_json()

    def get_top_brokers(symbol: str) -> str:
        return quotes.get_top_brokers(symbol).model_dump_json()

    def get_trade_prices(symbol: str) -> str:
        return quotes.get_trade_prices(symbol).model_dump_json()

    def get_portfolio() -> str:
        return portfolio.get_portfolio().model_dump_json()

    def take_screenshot() -> ToolResult:
        path = session.screenshot()
        return ToolResult(
            text="Screenshot of the live COL page is attached as an image.",
            images=[str(path)],
        )

    def check_market_open() -> str:
        return "open" if order_entry.market_is_open() else "closed"

    registry.register(
        Tool(
            "get_quote",
            "Real-time PSE stock quote: last/change/%change, 3-level depth, OHLC, value, volume.",
            {"symbol": "PSE ticker, e.g. TEL"},
            get_quote,
        )
    )
    registry.register(
        Tool(
            "get_stock_info",
            "Detailed Quotes-tab stock info: 5-level bid/ask depth with order counts, "
            "last 5 trades with broker names, and stats (market cap, outstanding shares, "
            "board lot, floor/ceiling price, 52wk-style dynamic thresholds, foreign access).",
            {"symbol": "PSE ticker, e.g. TEL"},
            get_stock_info,
        )
    )
    registry.register(
        Tool(
            "get_top_brokers",
            "Today's top buying and selling brokers for a stock, with volumes, amounts, "
            "average prices, and % of market.",
            {"symbol": "PSE ticker, e.g. TEL"},
            get_top_brokers,
        )
    )
    registry.register(
        Tool(
            "get_trade_prices",
            "Today's per-price trade distribution for a stock (volume, amount, trades and "
            "% of value at each traded price, plus totals and average price).",
            {"symbol": "PSE ticker, e.g. TEL"},
            get_trade_prices,
        )
    )
    registry.register(
        Tool(
            "get_portfolio",
            "Account summary: cash balance, buying power, equity and mutual-fund holdings, P&L.",
            {},
            get_portfolio,
        )
    )
    registry.register(
        Tool(
            "take_screenshot",
            "Screenshot the live COL page for visual inspection (use when HTML data is ambiguous).",
            {},
            take_screenshot,
        )
    )
    registry.register(
        Tool(
            "check_market_open",
            "Whether COL's server-side gate currently allows order entry.",
            {},
            check_market_open,
        )
    )
    # Deliberately NOT registered: any tool that fills or submits an order.
    # Order entry beyond the market-status probe requires a human in the
    # browser (see colfin_harness.agents.order_entry).
    return registry
