# COL Financial — Read-Only Agent Map

Mapping of the **Portfolio** and **Quotes** read-only surfaces on the authenticated COL
Financial platform, captured for the agent harness.

## Platform context (shared by all agents)

- **App style:** classic ASP frameset app under `https://ph45.colfinancial.com/ape/FINAL2_STARTER/`.
  `ph45` is a sticky load-balancer node — the session is pinned to it.
- **Auth:** server-side **HttpOnly session cookie** (not visible to JS, not in URLs).
  Every data endpoint is a plain `GET` that relies on the cookie being sent
  (`credentials: include`). There is **no token in the query string** and **no JSON API**.
- **Data shape:** endpoints return **HTML fragments**, not JSON. Agents parse the HTML.
- **Session timeout:** an idle watchdog (`CheckSessionTimeout`) logs the session out;
  the harness must keep the session warm and detect/re-auth on expiry.
- **Top-nav mechanism:** `headern` frame exposes `clickTable(row, col)`:
  `Home=1,1` · `Quotes=2,1` · `Trade=3,1` · `Research=4,1` · `StreetSmart=5,1`.

---

## Agent 1 — Quotes (read-only)

Fetches a real-time stock quote with depth and OHLC.

- **Endpoint:** `GET ape/FINAL2_STARTER/B_home_new/Pse_Quote_AU_DB.asp?q=<SYMBOL>`
  (e.g. `?q=TEL`). Cookie-authenticated. Returns an HTML fragment.
- **UI path (fallback / interactive):** quote box in the header — text input `T1`,
  button `B1`; or call `showQuotes2()` in the `Pse_Quote_AU.asp` frame.
- **Response fields (from the fragment):**
  - Company name (e.g. `PLDT Inc.`)
  - Last price, net change, % change — **font color encodes direction** (red = down, green = up)
  - `id="mytable"` holds the depth + OHLC grid:
    - 3 levels of: Bid Vol · Bid Price · Offer Price · Offer Vol
    - Open · High · Low · Trades · Value · Vol
- **Related market-data endpoints (same pattern):**
  - `B_home_new/MA.asp?_=<ts>` — Most Active (polled; cache-buster `_` timestamp).
    Tabs in UI: Actives / Gainers / Losers / Markets.
- **Parse note:** values are positional table cells (not `id`-tagged), so parse the
  fragment by table/row position or by the `mytable` id, not by per-field ids.

### Quotes tab (top-nav `clickTable(2,1)`) — mapped 2026-07-07 from a live session

The Quotes tab's **Stock Information → Stock** page (`quotes/Pse_Quote.asp`, body frame
`quotes/PSE_QUOTE_2.ASP`) is a richer quote surface than the header quote box. Sub-tabs:
Stock · Buyers/Sellers · Trade Prices · I-Charts · Profile · Dividends · News ·
Valuations · Highlights · Research.

**Working data endpoints** (all cookie-authenticated GETs returning HTML fragments):

| Endpoint | Params | Content |
|---|---|---|
| `quotes/Pse_Quote_2_DB.asp` | `q=<SYMBOL>` (+ optional `_` cache-buster) | Full quote: company name, 5-level bid/ask depth **with posted-order counts**, Last 5 Trades (time/volume/price/buyer/seller broker names, 8-char truncated), and a 23-row stats table |
| `quotes/TOPBUYER.asp` | `varstock=<SYMBOL>` (**required** — bare returns an empty table) | Top buying brokers: rank, broker (12-char truncated), Buy Vol, Buy Amt, Buy Ave, % Mkt |
| `quotes/TOPSELLER.asp` | `varstock=<SYMBOL>` (required) | Top selling brokers, same columns (Sell \*) |
| `quotes/TRADEPRICES.asp` | **none — ignores all params** | Per-price trade distribution: rank, Price, Volume, Amount, Trades, Percent + a `Totals` row (`<price>(ave)` in the price cell) |

**Session-stateful protocol:** fetching `Pse_Quote_2_DB.asp?q=SYM` also sets the
server-side "current stock" for the session; `TRADEPRICES.asp` renders whatever that
state points at. So a trade-prices fetch must be **sequenced immediately after the quote
fetch for the same symbol** (the shared session state is a cross-request race otherwise).
The UI shell (`PSE_QUOTE_2.ASP`) polls `Pse_Quote_2_DB.asp` via jQuery ("Auto Update"),
mirroring the home page's `Pse_Quote_AU.asp`/`Pse_Quote_AU_DB.asp` split.

**Stats-table labels** (label/value rows, in order): Previous, Last, Change, %Change,
Open, High, Low, Value, Trades, Volume, Outstanding, Market Capitalization,
Inst. Status, Market Status, BoardLot, Fluctuation, Floor Price, CeilingPrice,
Dyn T Low, Dyn T High, Par Value, Margin Rate %, Open to Foreigners.
Last/Change/%Change render as `<font color=red|green>` (direction encoding); Inst./
Market Status and Open to Foreigners are text values.

**Depth grid (`id="mytable"`):** two header rows, then 5 data rows of 6 cells:
`bid orders · bid size · bid price · ask price · ask size · ask orders`.
Bid cells render green, ask cells red, order counts neutral — colors are decoration
here, not direction.

**Invalid symbol:** `Pse_Quote_2_DB.asp?q=<bad>` returns a ~780-byte stub with **no
`mytable`** (just the stylesheet and an empty shell) — same detection as the home quote.

**Unavailable (server-disabled as of mapping):** Profile / Dividends / News /
Valuations / Highlights all redirect to `XML/function_unavailable.asp`; their direct
endpoints (`XML/CompanyProfile_2.asp`, `XML/DividendHistory_2.asp`,
`XML/CompanyHeadline_2.asp`, `XML/CompanyValuation_2.asp`,
`XML/FinancialHighlights_2.asp`) return "This page is currently unavailable."
I-Charts is a chart applet (`CHART_APPLE/`), not a parseable data surface.

Real scrubbed fixtures from this mapping: `tests/fixtures/stock_info.html`,
`top_buyers.html`, `top_sellers.html`, `trade_prices.html`, `stock_info_invalid.html`
(query strings stripped from attribute URLs; no account data appears on these pages).

---

## Agent 2 — Portfolio / Account Summary (read-only)

Returns cash balance, equity holdings, mutual-fund holdings, and P&L.

- **Endpoint:** `GET ape/FINAL2_STARTER/trading_PCA3/As_CashBalStockPos_MF.asp`
  (Cash Balance + Stock Positions + Mutual Funds). Cookie-authenticated. HTML fragment.
- **UI path:** `clickTable(3,1)` (Trade) → click **Portfolio** in the Trade submenu.
- **Sections & columns:**
  - **Cash Balance:** `Actual Balance`, `Buying Power`
  - **Equities** (one row per holding):
    `Action(BUY|SELL)` · `Stock Code` · `Stock Name` · `Portfolio %` · `Market Price` ·
    `Average Price` · `Total Shares` · `Uncommitted Shares` · `Market Value` ·
    `Gain/Loss` · `%Gain/Loss`
    — followed by `TOTAL EQUITIES` and `TOTAL EQUITIES GAIN/LOSS`
  - **Mutual Funds** (one row per fund):
    `Action` · `Fund Code` · `Fund Name` · `Portfolio %` · `NAVPS` · `Average Price` ·
    `Total Shares` · `Uncommitted Shares` · `Market Value` · `Gain/Loss` · `%Gain/Loss`
    — followed by `TOTAL MUTUAL FUNDS` and gain/loss
  - **Totals:** `TOTAL PORTFOLIO TRADE VALUE`, `DAY CHANGE` (% + amount),
    `PORTFOLIO GAIN/LOSS` (% + amount)
- **Parse note:** tables are nested; parse **leaf `<tr>` rows** (rows containing no nested
  `<table>`). A holding row has a 2–5 char uppercase code in column 2.
- **Adjacent read-only links on this page** (candidate future agents): Trading History,
  View Monthly Account Ledger (current/historical), View IPO Request Status,
  View Tender Offer, View Rights Offer, View Portfolio Summary Reports,
  Transaction Invoice (Daily/Historical), Withdrawal Status.

---

## Harness implications

1. **Both agents are pure `GET` + HTML-parse** against the endpoints above — no UI driving
   required once a session cookie exists. This is the efficient path; the frame/UI route is
   the fallback for debugging.
2. **Session management is the central concern:** capture the HttpOnly cookie from a
   logged-in browser, keep it warm against the idle timeout, pin requests to the `ph45`
   node, and detect logout. Login is automated (no captcha/2FA): the harness fills the
   `id="login"` form from in-memory credentials, so a detected logout can be re-authed
   without a human.
3. **Parsing should be position/anchor based**, tolerant of the legacy ASP markup
   (no stable per-field ids on values).
4. These two are the safe foundation. Order entry (Trade → Enter Order) is a separate,
   state-changing surface and must keep a mandatory human-confirmation step.
