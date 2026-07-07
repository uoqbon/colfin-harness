class HarnessError(Exception):
    """Base for all harness errors."""


class ParseError(HarnessError):
    """An HTML fragment did not match the expected structure."""


class QuoteNotFound(ParseError):
    """Quote fragment has no data table — unknown symbol or empty response."""


class StaleTradePrices(ParseError):
    """TRADEPRICES.asp returned a different company than the one just quoted —
    the server-side "current stock" state was repointed between the two
    fetches, so the data would be mislabeled."""


class SessionExpired(HarnessError):
    """The COL session cookie is no longer valid; re-login required."""


class LoginFailed(HarnessError):
    """Automated login filled the form and submitted, but the session never
    authenticated within the handoff window — typically wrong credentials or a
    changed login-page layout. The message never echoes the credentials."""


class NodePinningError(HarnessError):
    """A request escaped the sticky ph45 load-balancer node."""


class MarketClosedError(HarnessError):
    """COL's server-side gate rejected order entry because the market is closed."""


class OrderSubmissionForbidden(HarnessError):
    """Raised unconditionally on any order-submit path.

    The harness NEVER submits orders. A human must complete the wizard's
    Step 2 (preview/confirm) in the browser themselves.
    """


class ProtocolError(HarnessError):
    """The VLM's reply did not contain a valid tool-call JSON object."""


class OrchestrationError(HarnessError):
    """The tool-calling loop could not make progress."""
