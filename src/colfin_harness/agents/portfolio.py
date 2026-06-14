"""Read-only portfolio / account-summary agent (docs/read-only-agents.md, Agent 2)."""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.parsing.portfolio import parse_portfolio
from colfin_harness.schemas import Portfolio

PORTFOLIO_PATH = "/ape/FINAL2_STARTER/trading_PCA3/As_CashBalStockPos_MF.asp"


class PortfolioAgent(BaseAgent):
    def get_portfolio(self) -> Portfolio:
        html = self._source.fetch_fragment(PORTFOLIO_PATH)
        return parse_portfolio(html)
