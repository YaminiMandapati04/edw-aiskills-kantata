# Query playbook (ARR)

These are recipes for each question type against `PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS`. The templates themselves are in `view-arr.md` §5, all verified live. Every statement goes through `python scripts/sql_guard.py` first, and the warehouse is `MCP_WH`.

## Contents
1. Discovery and base form
2. Pulse
3. Why / driver
4. Bridge, drills and translational downsell
5. Customer counts
6. Product
7. Trend
8. Sanity checks
9. When the view can't answer

---

## 1. Discovery and base form

```sql
DESCRIBE SEMANTIC VIEW PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;
SHOW SEMANTIC METRICS IN PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;
```

```sql
SELECT <dims>, <metrics>
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS <table>.<dim>, ...
  METRICS    <table>.<metric>, ...
  WHERE      ARR_WATERFALL.ARR_MONTH_END = '2026-11-30')
ORDER BY ... LIMIT 100;
```

- Metrics aggregate to the listed dimensions. The `WHERE` inside `SEMANTIC_VIEW` filters dimensions. Filter metric results in an outer `WHERE`.
- Mixing `ARR_WATERFALL` metrics with `CUSTOMER_BRIDGE` metrics in one call is not supported. Query them separately and join on the month in an outer query.
- Product dimensions work only with `ARR_BY_PRODUCT.TOTAL_ARR`.

## 2. Pulse

"What is our ARR?" Read `TOTAL_ENDING_ARR` at the latest month end, and also at the prior month end and the same month last year (`TOTAL_PY_MTD` with `CATEGORY = 'Ending ARR'`, or query that date). Report the level, MoM and YoY change in $ and %, and the latest NDR % and GDR % (5c). Say USD at the monthly average rate.

## 3. Why / driver

1. Run the bridge for the window (5a or 5b) and confirm it ties.
2. Rank the movements by absolute size: New, Upsell, Downsell (Op), Downsell (Transl), Churn. Compare with the prior month or prior year to find what changed.
3. Drill the largest movement by `SEGMENT`, `CUSTOMER_SOURCE` or `INDUSTRY` (5h pattern), then by customer (5d), capped at 100.
4. State the concentration (top 3 customers' share of the movement). Name a business reason only when a field shows it. Otherwise, name who can confirm it (Customer Success, RevOps, Revenue Accounting).

## 4. Bridge, drills and translational downsell

**Standard presentation** (always in this order):

| Line | Source |
|---|---|
| Beginning ARR | `TOTAL_BEGINNING_ARR` / CATEGORY 'Beginning ARR' |
| New | `TOTAL_NEW_ARR` |
| Upsell | `TOTAL_UPSELL_ARR` |
| Downsell (Operational) | `TOTAL_DOWNSELL_ARR` / CATEGORY 'Downsell' |
| Downsell (Translational) | `TOTAL_FX_ARR` / CATEGORY 'FX' |
| Churn | `TOTAL_CHURN_ARR` |
| **Ending ARR** | `TOTAL_ENDING_ARR`, which must equal the sum of the lines above |

Optional memo lines: Total Downsell (Op + Transl, derived), Net new ARR (`NET_NEW_ARR`, excludes Translational), GDR $ / %, NDR $ / %.

Never show a separate FX, currency, adjustment or "other" step. If the tie-out (5a `TIE_OUT`) is not 0 within $0.01, stop and report the gap.

**4b Drills.** Use 5d with the category filter: 'New', 'Upsell', 'Downsell', 'Churn' or 'FX'. Each customer list must sum to the category total. Show "All other" for the remainder beyond the cap.

**4c Translational.** Use 5e by `CUSTOMER_SOURCE` and then 5d with `CATEGORY = 'FX'` by customer. Translational downsell comes from non-USD contracts (APAC, EMEA, Multiple), so Yes Energy- and RTO-only customers normally show 0. An FX gain is a positive Translational downsell, a favourable offset: say "favourable" rather than calling it upsell.

## 5. Customer counts

Use 5f. For QTD, YTD or LTM, use the window metrics at the window's last month end, never a sum of months. Logo churn rate = −Lost ÷ Beginning for the same window (derived). Pair the counts with dollars when the question is about retention health: one large customer can move the dollars while the counts barely change.

## 6. Product

Use 5g. Product family ARR is a balance. The change between two month ends is *derived* and includes translational effects. It is not a New, Upsell or Downsell split, so say that once. The families sum to Ending ARR; keep Unmapped and the negative families.

## 7. Trend

Use 5a over 13 to 24 months. Ending ARR is a line (balances, one per month). Bridge flows are columns. A rolling 12-month view is `TOTAL_LTM` by CATEGORY at each month end. Call a change persistent only when 3 or more consecutive months show it.

## 8. Sanity checks

1. The bridge ties, and the per-customer drill sums to its category.
2. Product families at a month end sum to `TOTAL_ENDING_ARR`.
3. `NET_CUSTOMER_CHANGE` = Ending − Beginning customers.
4. Balances are not added across months, and customer windows are not summed.
5. The latest month is labelled partial if open.

## 9. When the view can't answer

Use `semantic-views.md` §8 and the standard replies in `question-patterns.md` §4.
