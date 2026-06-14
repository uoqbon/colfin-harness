# COL Financial — Trade / Enter Order Map

Structural map of the **order-entry** surface. This is a **state-changing** surface — the
harness must keep a mandatory human-confirmation step before any submit. Nothing was
submitted while mapping this.

> ⚠️ **Partial map.** Captured at ~01:30 PHT on a weekend, when **the market is closed**.
> COL gates the order forms server-side: when closed, the endpoint returns only a warning
> and renders **no form fields**. The structural skeleton (endpoints, wizard flow, known
> params) is mapped below; **field-level mapping (input names/ids, dropdown options) must
> be completed during market hours.**

## Trade submenu (under `clickTable(3,1)`)

`Enter Order` · `View/Modify Order` · `Trading History` · `Portfolio` ·
`O-H Order` (off-hours) · `O-H View/Cancel` · `EIP Scheduler`

## Enter Order — regular (path: `trading_PCA3/`)

A **3-step wizard** — header reads `ENTER ORDER (Step 1 of 3)`. Expected flow:
Step 1 entry → Step 2 confirm/preview → Step 3 receipt (the explicit confirm step is the
natural human-approval gate for the harness).

Endpoints captured:

| Endpoint | Role | Known params |
|---|---|---|
| `trading_PCA3/Trd_frame.asp` | order frameset container | — |
| `trading_PCA3/Trd_EnterOrder.asp` | **Step 1 order form** | `StockCode`, `DAYGTC` (Day vs GTC order type) |
| `trading_PCA3/Trd_Quote.asp` | inline quote for the form | `Symbol` |

**Market-closed behavior:** `Trd_EnterOrder.asp` returns only
`"You can not place an order. The market is closed."` — no `<form>`, no inputs.

**Expected fields (to confirm during market hours):** Stock Code, Buy/Sell side,
Quantity, Price, Order type (Day/GTC via `DAYGTC`). Need to capture exact input
names/ids, the Step 2 confirm payload, and the submit method/endpoint.

## O-H Order — off-hours / queued (path: `aftertrade_PCA/`)

- `aftertrade_PCA/checkmarket.asp` — market-status gate. Currently returns
  `"OFF-HOURS MARKET IS CLOSED"` (off-hours trading has its own window, also closed now).
- The off-hours order form lives under `aftertrade_PCA/` and is the route to map order
  entry **when the regular market is closed but the off-hours window is open**.

## Related order-management surfaces (not yet mapped)

- `View/Modify Order` — amend/cancel working orders
- `O-H View/Cancel` — manage off-hours orders
- `Trading History` — filled/historical orders (read-only; good safe agent)
- `EIP Scheduler` — Easy Investment Program recurring buys

## Harness implications

1. **Order entry is hours-gated server-side** — the harness must check market status
   (`checkmarket.asp` pattern) before attempting entry, and surface "market closed" cleanly.
2. **Keep the wizard's Step 2 as the human-approval checkpoint** — the agent prepares
   Step 1, a human confirms before Step 2→3 commits the order.
3. **Field-level mapping is the open item** — revisit during PSE market hours
   (regular session ~09:30–15:30 PHT; next session after the Jun 12 holiday + weekend
   is Mon Jun 15) to capture input names, the confirm payload, and the submit endpoint.
