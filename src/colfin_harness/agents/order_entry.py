"""Order-entry agent — STUB ONLY. This agent NEVER submits orders.

Safety contract (locked architecture decision):
- The 3-step wizard's Step 2 (preview/confirm) is a mandatory HUMAN
  checkpoint. The harness may at most prepare Step 1; a human completes
  Step 2 → 3 in the browser themselves.
- ``submit_order`` raises unconditionally. Do not "fix" this.

Structural map from docs/order-entry.md (captured while the market was
closed, so field-level mapping is incomplete):

- ``trading_PCA3/Trd_frame.asp``        — wizard frameset container
- ``trading_PCA3/Trd_EnterOrder.asp``   — Step 1 form; params ``StockCode``,
  ``DAYGTC`` (Day vs GTC). When the market is closed the server returns only
  "You can not place an order. The market is closed." with no form fields.
- ``trading_PCA3/Trd_Quote.asp``        — inline quote; param ``Symbol``
- ``aftertrade_PCA/checkmarket.asp``    — off-hours market-status gate
  ("OFF-HOURS MARKET IS CLOSED" when shut)

TODO (blocked on PSE market hours, ~09:30–15:30 PHT): capture Step 1 input
names/ids and dropdown options, the Step 2 confirm payload, and the submit
method/endpoint. Until then ``prepare_order`` stops after the market gate.
"""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.exceptions import MarketClosedError, OrderSubmissionForbidden
from colfin_harness.schemas import OrderDraft

ORDER_FRAME_PATH = "/ape/FINAL2_STARTER/trading_PCA3/Trd_frame.asp"
ORDER_STEP1_PATH = "/ape/FINAL2_STARTER/trading_PCA3/Trd_EnterOrder.asp"
ORDER_QUOTE_PATH = "/ape/FINAL2_STARTER/trading_PCA3/Trd_Quote.asp"
OFFHOURS_GATE_PATH = "/ape/FINAL2_STARTER/aftertrade_PCA/checkmarket.asp"

_CLOSED_MARKERS = (
    "market is closed",
    "off-hours market is closed",
    "you can not place an order",
)


def _market_closed(fragment: str) -> bool:
    lowered = fragment.lower()
    return any(marker in lowered for marker in _CLOSED_MARKERS)


class OrderEntryAgent(BaseAgent):
    """Encodes the wizard flow but stops hard before anything state-changing."""

    def market_is_open(self) -> bool:
        """COL gates order forms server-side; probe Step 1 for the gate."""
        fragment = self._source.fetch_fragment(ORDER_STEP1_PATH)
        return not _market_closed(fragment)

    def offhours_window_is_open(self) -> bool:
        fragment = self._source.fetch_fragment(OFFHOURS_GATE_PATH)
        return not _market_closed(fragment)

    def prepare_order(self, draft: OrderDraft) -> None:
        """Load the Step 1 form for a draft order. Never goes further.

        Raises MarketClosedError when the server gate is shut, and
        NotImplementedError otherwise — the Step 1 field mapping is the open
        TODO above and must be captured during market hours before this can
        fill anything.
        """
        fragment = self._source.fetch_fragment(
            ORDER_STEP1_PATH,
            {"StockCode": draft.stock_code.strip().upper(), "DAYGTC": draft.term.value},
        )
        if _market_closed(fragment):
            raise MarketClosedError(
                "COL rejected order entry: the market is closed. "
                "Off-hours route exists (aftertrade_PCA/) but is unmapped."
            )
        raise NotImplementedError(
            "Step 1 field mapping is not captured yet (market-hours TODO in "
            "docs/order-entry.md). Even once it is, Step 2 confirm stays a "
            "human-only checkpoint."
        )

    def submit_order(self, *args: object, **kwargs: object) -> None:
        """Permanent hard stop — see the safety contract in the module docstring."""
        raise OrderSubmissionForbidden(
            "The harness never submits orders. A human must review the "
            "wizard's Step 2 preview in the browser and submit there."
        )
