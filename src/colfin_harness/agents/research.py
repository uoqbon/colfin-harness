"""Read-only research agent (docs/read-only-agents.md, Agent 3).

Covers the Research tab's Technical Guide — COL's published per-stock
technical view (support/resistance levels, trend, recommendation). Purely
informational: nothing here touches order entry.
"""

from colfin_harness.agents.base import BaseAgent
from colfin_harness.parsing.tech_guide import parse_tech_guide_as_of, parse_technical_guide
from colfin_harness.schemas import TechnicalGuide

# The guide page (Research > Technicals > Technical Guide) is a frameset:
# the Mid frame holds the data table, the Top frame the "As of" date.
TECH_GUIDE_PATH = "/ape/FINAL2_STARTER/Research/TECHGUIDE_Mid.asp"
TECH_GUIDE_HEADER_PATH = "/ape/FINAL2_STARTER/Research/TECHGUIDE_Top.asp"


class ResearchAgent(BaseAgent):
    def get_technical_guide(self) -> TechnicalGuide:
        """The full Technical Guide: every covered stock (and index), grouped
        by the guide's own sectors, plus the publication date.

        The date matters: the guide is refreshed on COL's schedule, not
        intraday, so callers should surface as_of next to any recommendation.
        """
        guide = parse_technical_guide(self._source.fetch_fragment(TECH_GUIDE_PATH))
        guide.as_of = parse_tech_guide_as_of(
            self._source.fetch_fragment(TECH_GUIDE_HEADER_PATH)
        )
        return guide
