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
