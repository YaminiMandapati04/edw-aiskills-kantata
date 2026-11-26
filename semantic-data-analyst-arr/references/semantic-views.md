# Semantic view registry (ARR)

**Status: built from the live `DESCRIBE SEMANTIC VIEW PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS` and probes run 2026-11-23 (latest month end 2026-11-30).** The live definition wins if it changes.

This skill queries **one view**, `ARR_ANALYTICS`: the Maxio ARR waterfall and customer count bridges for Yes Energy, joined to the unified customer, product family, NetSuite accounting period and calendar dimensions. Bookings and pipeline belong to the GTM skill. P&L, balance sheet, cash and budget belong to the finance skill.

## Contents
1. Connection defaults
2. Conventions
3. Routing
4. Words users say
5. Rules that always hold
6. The view at a glance
7. Drill-through paths
8. Across views, and what cannot be answered
9. First-run probes
10. Approved example questions

---

## 1. Connection defaults

| Setting | Default |
|---|---|
| Database / schema / view | `PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS` (`DEV_DB` only when the user asks) |
| Warehouse | `MCP_WH`. Pass it on every `sql-exec` call, or `USE WAREHOUSE MCP_WH;` in Snowsight. |
| Role | The read-only connector role. Never switch. |
| Secrets (`SERVER_URL`, `OAUTH_*`) | Never read, print, log or write them. Don't open `.env`. |
| Row cap for row-level output | 100 |

## 2. Conventions

| Convention | Value |
|---|---|
| Currency | USD, actual currency converted at the **monthly average rate**. State it. |
| Scale | `mn` with one decimal at $1mn or more, otherwise `k`. Negatives in brackets. |
| Calendar | **Fiscal = calendar year** (Jan–Dec). `ACCOUNTING_PERIOD.FISCAL_QUARTER_YEAR` reads "Q4 2026" and `FISCAL_MONTH_YEAR` reads "November 2026". `CALENDAR.CALENDAR_MONTH_YEAR` reads "NOV-2026". YTD opens at 31 Dec of the prior year. |
| Latest period | The latest month end in the data (2026-11-30 at build). Compare it with today's date and say when the open month is partial. |
| Signs as stored | Beginning, New, Upsell and Ending are positive. Downsell and Churn are **negative**. FX is signed. Lost Customers is negative. |
| Bridge lines shown | Beginning ARR · New · Upsell · Downsell (Operational) = `Downsell` · Downsell (Translational) = `FX` · Churn · Ending ARR |
| No adjustments | Manual ARR adjustments are part of ARR, not a category. Never add an adjustment or "FX" line. |
| Retention | Gross Dollar Retention and Net Dollar Retention are **dollar** metrics. The % versions are derived (÷ Beginning ARR, same window). Give one decimal. |
| Customer | The unified customer across the Yes Energy, RTO, APAC and EMEA Maxio systems, counted once. A customer is active when total ARR > $10. |
| Renewal carry | ARR of a customer with an open Salesforce renewal opportunity is carried for up to 12 months after its subscriptions end. A carried renewal that runs out becomes Churn. |

## 3. Routing

| The user asks about | Logical table | Metrics |
|---|---|---|
| Ending / beginning ARR, ARR bridge, New, Upsell, Downsell, Churn, FX, net new ARR, GDR, NDR | `ARR_WATERFALL` | `TOTAL_*_ARR`, `NET_NEW_ARR`, `GROSS_/NET_DOLLAR_RETENTION`, `TOTAL_MTD/QTD/YTD/LTM` + `TOTAL_PY_*`, `YOY_MTD_GROWTH` |
| Customer counts: beginning, new, lost, ending, net change | `CUSTOMER_BRIDGE` | `TOTAL_BEGINNING/NEW/LOST/ENDING_CUSTOMERS`, `NET_CUSTOMER_CHANGE`, `TOTAL_MTD/QTD/YTD/LTM` + PY |
| ARR by product family, customer × product | `ARR_BY_PRODUCT` | `TOTAL_ARR` (a balance) |
| Cuts by customer, segment, industry, type, source system | `CUSTOMER` dims | joins to all three facts |
| Product family | `PRODUCT.PRODUCT_FAMILY` | `ARR_BY_PRODUCT` only |
| Fiscal period labels | `ACCOUNTING_PERIOD` | both bridges only |
| Calendar labels | `CALENDAR` | `ARR_BY_PRODUCT` only |
| Bookings, pipeline | GTM skill | |
| Revenue, EBITDA, cash, budget | Finance skill | |

## 4. Words users say

| User says | Means |
|---|---|
| ARR, current ARR, closing ARR | `TOTAL_ENDING_ARR` at the latest month end |
| opening ARR | `TOTAL_BEGINNING_ARR` for the window |
| new ARR, new logo ARR | `TOTAL_NEW_ARR`: a new customer whose first contract starts this month. A zero-ARR contract that later converts is Upsell. |
| expansion, upsell, cross-sell | `TOTAL_UPSELL_ARR` |
| downsell, contraction | Downsell (Operational) = `TOTAL_DOWNSELL_ARR`. **Total** downsell/contraction = Operational + Translational (derived). |
| FX, currency impact, translational | **Downsell (Translational)** = `TOTAL_FX_ARR`. Never call it a separate FX line. |
| churn, lost ARR | `TOTAL_CHURN_ARR`: the customer's ARR ended and never comes back |
| net new ARR | `NET_NEW_ARR` = New + Upsell + Downsell (Operational) + Churn, **excluding** Translational. Ending − Beginning = Net new ARR + Downsell (Translational). |
| GRR, gross retention, GDR | `GROSS_DOLLAR_RETENTION` ($). GDR % = ÷ Beginning ARR. |
| NRR, net retention, NDR | `NET_DOLLAR_RETENTION` ($). NDR % = ÷ Beginning ARR. Excludes New and Translational. |
| logos, customers, customer count | `CUSTOMER_BRIDGE` metrics |
| logo churn rate | −`TOTAL_LOST_CUSTOMERS` ÷ `TOTAL_BEGINNING_CUSTOMERS` (derived) |
| segment | `CUSTOMER.SEGMENT`: Physical, Financial, or NULL (RTO-only customers; show as "Not set") |
| system, instance, RTO | `CUSTOMER.CUSTOMER_SOURCE`: Yes Energy, RTO, APAC, EMEA, Multiple |
| product | `PRODUCT.PRODUCT_FAMILY` (balance only; includes "Unmapped") |
| this quarter / YTD / LTM | Calendar = fiscal. Use `TOTAL_QTD` / `TOTAL_YTD` / `TOTAL_LTM` by `CATEGORY` at the window's last month end. |

## 5. Rules that always hold

| Rule | What goes wrong if ignored |
|---|---|
| The bridge ties: Ending = Beginning + New + Upsell + Downsell (Op) + Churn + Downsell (Transl) | A bridge that doesn't tie implies a missing or invented movement |
| FX only ever appears as Downsell (Translational) | Breaks the agreed reporting presentation |
| Balances are read at one month end | Summing ending ARR across months multiplies ARR |
| Filter `CATEGORY` or use per-category metrics with `TOTAL_MTD/QTD/YTD/LTM` | `TOTAL_MTD` summed over all categories adds Beginning, Ending and retention rows together |
| Customer-count windows are independent | Summing 3 months of new customers double-counts a customer who came and went |
| Bridge categories have no product grain | Showing "churn by product" from the bridge is impossible. Use product balances (derived). |
| GDR/NDR % are not additive | Averaging segment rates misstates the total |

## 6. The view at a glance

| | `ARR_ANALYTICS` |
|---|---|
| Source | Maxio (Yes Energy, RTO, APAC, EMEA instances). Renewal carry from Salesforce. Fiscal calendar from NetSuite. |
| Base tables | `PROD_DB.REPORTING.RPT_ARR_BRIDGE`, `PROD_DB.REPORTING.RPT_CUSTOMER_BRIDGE`, `PROD_DB.GOLD.FACT_ARR`, `PROD_DB.GOLD.DIM_MAXIO_CUSTOMER`, `PROD_DB.GOLD.DIM_MAXIO_PRODUCT`, `PROD_DB.GOLD.DIM_DATE`, `PROD_DB.GOLD.DIM_ACCOUNTING_PERIOD` |
| Grain | Customer × category × month (bridges). Customer × product family × month (ARR by product). |
| Time | Month-end dates. MTD / QTD / YTD / LTM plus prior year. |

## 7. Drill-through paths

| Domain | Hop | From → To | Filter carried |
|---|---|---|---|
| Bridge | 1 | Ending ARR → bridge category | window |
| Bridge | 2 | category → segment / source system / industry / customer type | window, category |
| Bridge | 3 | attribute → customer (≤100 rows) | window, category, attribute |
| Translational | 1 | Downsell (Translational) → source system (APAC / EMEA / Multiple carry FX) | window |
| Translational | 2 | source → customer | window, source |
| Customers | 1 | net change → new / lost | window |
| Customers | 2 | new / lost → customer list | window, category |
| Product | 1 | Ending ARR → product family (balance) | month end |
| Product | 2 | product family → customer | month end, family |

Customer is the finest grain. There is no subscription, invoice or contract grain.

## 8. Across views, and what cannot be answered

| Ask | Why not | Offer instead |
|---|---|---|
| New / Upsell / Downsell / Churn by product | Buckets are decided on customer total | Product balance change between month ends (derived) |
| Invoice, subscription line, contract detail | No such grain | Customer-level movements |
| ARR by region | No region dimension | Source system (APAC, EMEA, Yes Energy, RTO) as a proxy, labelled |
| Cohort retention curves | No first-ARR-date dimension | Customer bridge new/lost trend. A cohort is derived only if built from monthly customer balances, labelled. |
| Renewal win/loss rate, bookings | GTM data | GTM skill |
| CAC, LTV, payback | Needs finance cost | Finance skill plus ARR inputs |
| ARR target / budget variance | No ARR plan in the view | Prior month / prior year |
| FX at constant currency rates | Only the FX movement is held | Downsell (Translational) by month and source |

## 9. First-run probes

```sql
DESCRIBE SEMANTIC VIEW PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;

-- Latest month end and its bridge (should tie)
SELECT * FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_WATERFALL.ARR_MONTH_END
  METRICS ARR_WATERFALL.TOTAL_BEGINNING_ARR, ARR_WATERFALL.TOTAL_ENDING_ARR, ARR_WATERFALL.TOTAL_FX_ARR)
ORDER BY ARR_MONTH_END DESC LIMIT 1;

-- Category members
SELECT * FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_WATERFALL.CATEGORY METRICS ARR_WATERFALL.TOTAL_MTD
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30');
```

Known members at build:
- ARR categories: Beginning ARR, New, Upsell, Downsell, Churn, FX, Ending ARR, Gross Dollar Retention, Net Dollar Retention.
- Customer categories: Beginning Customers, New Customers, Lost Customers, Ending Customers.
- Segments: Physical, Financial, NULL.
- Sources: Yes Energy, RTO, APAC, EMEA, Multiple.
- About 45 product families, including Unmapped.

## 10. Approved example questions

- What is our ARR at the end of November, and how is it moving?
- Walk me through the Q4 2026 ARR bridge, including the translational downsell.
- What are YTD gross and net dollar retention, in dollars and %, vs last year?
- Which customers drove the November downsell?
- How much ARR did FX take off this year, and in which Maxio system?
- How many customers did we add and lose YTD?
- What is ARR by product family, and which families grew most since December?
- How does ARR split between the Physical and Financial segments?
