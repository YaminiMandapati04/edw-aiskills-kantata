# ARR view detail

Detail for `ARR_ANALYTICS`. The registry (`semantic-views.md`) sets the connection; this file covers tables, grain, hierarchies, metrics, query templates and answer ladders.

**Status: populated from the MCP tool description and ARR domain conventions. All table names and metric names are marked verify until `DESCRIBE SEMANTIC VIEW` confirms them on first run. Trust the live definition over this file where they differ.**

## Contents
1. Table inventory
2. Grain and joins
3. Hierarchies and dimensions
4. Metric catalogue
5. Query templates
6. Answer ladders
7. Cautions

---

## 1. Table inventory

| Table (expected name) | Grain | Purpose |
|---|---|---|
| `ARR_OVERVIEW` | One row per customer × month-end | Ending ARR, starting ARR, growth rate, NRR, GRR — the KPI mart |
| `ARR_WATERFALL` | One row per customer × movement type × month-end | New, expansion, contraction, churn movements; the bridge table |
| `LOGO_METRICS` | One row per month-end | Net logo adds, new logos, churned logos, total active logos |
| `CUSTOMER_ARR` | One row per customer × month-end | Customer-level ARR balance for drill-through |

**verify** — confirm these names and their columns with `DESCRIBE SEMANTIC VIEW` on the first run. Adjust the templates in §5 to match.

## 2. Grain and joins

- KPI marts (`ARR_OVERVIEW`, `LOGO_METRICS`) aggregate to the period level; use `IS_LATEST = TRUE` to read the most recent month-end card, or filter by `AS_OF_DATE` for a time series.
- `ARR_WATERFALL` has one row per movement per customer per month. Never sum all rows without filtering on `MOVEMENT_TYPE` — that would double-count customers who both expand and have a base ARR row (if the view stores starting ARR as a movement type).
- `CUSTOMER_ARR` is the drill table; cap at 100 rows.
- Do not join tables in `SEMANTIC_VIEW(...)` unless the view's own join is implied by selecting dimensions from multiple tables. If a bridge statement requires both a movement dimension and a customer dimension, check whether a single table carries both before running two queries.

## 3. Hierarchies and dimensions

| Dimension | Available on | Members (verify) |
|---|---|---|
| `AS_OF_DATE` | All tables | Month-end dates |
| `MOVEMENT_TYPE` | `ARR_WATERFALL` | Expected: `New`, `Expansion`, `Contraction`, `Churn` — **probe before filtering** |
| `CUSTOMER_ID` / `COMPANY_NAME` | `ARR_WATERFALL`, `CUSTOMER_ARR` | All active/former customers |
| `SEGMENT` | `ARR_OVERVIEW`, `ARR_WATERFALL` | Expected: Enterprise, Mid-Market, SMB or similar — **probe** |
| `PRODUCT` | `ARR_OVERVIEW`, `ARR_WATERFALL` | Product or product family — **probe** |

## 4. Metric catalogue

**verify** — confirm metric names with `DESCRIBE SEMANTIC VIEW`. The names below follow the tool description and common ARR conventions.

| Metric | Table | Definition | Notes |
|---|---|---|---|
| `STARTING_ARR_USD` | `ARR_OVERVIEW` | ARR at the start of the period | Equal to prior month's `ENDING_ARR_USD` |
| `ENDING_ARR_USD` | `ARR_OVERVIEW` | ARR at the end of the period | The primary balance metric |
| `NEW_ARR_USD` | `ARR_WATERFALL` | ARR added from first-time customers | Additive; positive |
| `EXPANSION_ARR_USD` | `ARR_WATERFALL` | ARR added by existing customers increasing their subscription | Additive; positive |
| `CONTRACTION_ARR_USD` | `ARR_WATERFALL` | ARR lost from existing customers reducing (not cancelling) | Magnitude; displayed in brackets |
| `CHURNED_ARR_USD` | `ARR_WATERFALL` | ARR lost from customers who fully cancelled | Magnitude; displayed in brackets |
| `NET_NEW_ARR_USD` | `ARR_OVERVIEW` or derived | New + Expansion − Contraction − Churn | Derived if not in the view; label as such |
| `NRR` | `ARR_OVERVIEW` | (Starting ARR + Expansion − Contraction − Churn) ÷ Starting ARR, trailing 12M | Rate; non-additive across groups |
| `GRR` | `ARR_OVERVIEW` | (Starting ARR − Contraction − Churn) ÷ Starting ARR, trailing 12M | Rate; non-additive; excludes expansion |
| `ARR_GROWTH_RATE` | `ARR_OVERVIEW` | (Ending ARR − Prior-year Ending ARR) ÷ Prior-year Ending ARR | Rate; derived if not in the view |
| `TOTAL_LOGOS` | `LOGO_METRICS` | Active customer count at month-end | |
| `NEW_LOGOS` | `LOGO_METRICS` | New customers added in the period | |
| `CHURNED_LOGOS` | `LOGO_METRICS` | Customers who fully cancelled in the period | Magnitude; displayed in brackets |
| `NET_LOGO_ADDS` | `LOGO_METRICS` | New Logos − Churned Logos | Derived if not in the view |
| `LOGO_CHURN_RATE` | `LOGO_METRICS` or derived | Churned Logos ÷ Starting Logos | Rate; non-additive |

## 5. Query templates

Adjust table names, dimension names and metric names to match the live `DESCRIBE` output before using.

**Every query** also carries the standing test-account exclusion inside its `WHERE` (`python scripts/account_scope.py clause` prints it; `account_scope.py check` refuses a query without it). The live view's fact tables are `ARR_BRIDGE` and `CUSTOMER_BRIDGE`, both joined to `CUSTOMER`, so for example:

```sql
SELECT * FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS ARR_BRIDGE.MONTH_END_DATE, ARR_BRIDGE.CATEGORY
    METRICS    ARR_BRIDGE.TOTAL_MTD
    WHERE      ARR_BRIDGE.MONTH_END_DATE = '2026-09-30'
      AND (CUSTOMER.ACCOUNT_ID IS NULL OR CUSTOMER.ACCOUNT_ID NOT IN ('0010Z000023uvjkQAA', '0013r00002nUO7SAAW', '0013r00002nUOBtAAO', '0013r00002fqSchAAE', '0013r00002fpJz4AAE'))
)
ORDER BY 2;
```

The templates below omit the filter for brevity; add it to each.

**5a. Current ARR and NRR (KPI card)**
```sql
SELECT AS_OF_DATE,
       ENDING_ARR_USD,
       NRR,
       GRR,
       ARR_GROWTH_RATE
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS ARR_OVERVIEW.AS_OF_DATE
    METRICS    ARR_OVERVIEW.ENDING_ARR_USD,
               ARR_OVERVIEW.NRR,
               ARR_OVERVIEW.GRR,
               ARR_OVERVIEW.ARR_GROWTH_RATE
    WHERE      ARR_OVERVIEW.IS_LATEST = TRUE
);
```

**5b. ARR bridge for a single month**
```sql
SELECT AS_OF_DATE,
       MOVEMENT_TYPE,
       SUM(MOVEMENT_ARR_USD) AS MOVEMENT_ARR_USD
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS ARR_WATERFALL.AS_OF_DATE,
               ARR_WATERFALL.MOVEMENT_TYPE
    METRICS    ARR_WATERFALL.MOVEMENT_ARR_USD
    WHERE      ARR_WATERFALL.AS_OF_DATE = '2026-10-31'
)
GROUP BY AS_OF_DATE, MOVEMENT_TYPE
ORDER BY MOVEMENT_TYPE;
```

**5c. Monthly ARR trend (last 24 months)**
```sql
SELECT AS_OF_DATE,
       ENDING_ARR_USD,
       NRR,
       NET_NEW_ARR_USD
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS ARR_OVERVIEW.AS_OF_DATE
    METRICS    ARR_OVERVIEW.ENDING_ARR_USD,
               ARR_OVERVIEW.NRR,
               ARR_OVERVIEW.NET_NEW_ARR_USD
    WHERE      ARR_OVERVIEW.AS_OF_DATE >= DATEADD(MONTH, -24, CURRENT_DATE())
)
ORDER BY AS_OF_DATE;
```

**5d. ARR by segment**
```sql
SELECT AS_OF_DATE,
       SEGMENT,
       ENDING_ARR_USD,
       NRR
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS ARR_OVERVIEW.AS_OF_DATE,
               ARR_OVERVIEW.SEGMENT
    METRICS    ARR_OVERVIEW.ENDING_ARR_USD,
               ARR_OVERVIEW.NRR
    WHERE      ARR_OVERVIEW.IS_LATEST = TRUE
)
ORDER BY ENDING_ARR_USD DESC;
```

**5e. Churned customers (drill)**
```sql
SELECT COMPANY_NAME,
       AS_OF_DATE,
       CHURNED_ARR_USD
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS CUSTOMER_ARR.COMPANY_NAME,
               CUSTOMER_ARR.AS_OF_DATE
    METRICS    CUSTOMER_ARR.CHURNED_ARR_USD
    WHERE      CUSTOMER_ARR.AS_OF_DATE BETWEEN '2026-07-31' AND '2026-09-30'
      AND      CUSTOMER_ARR.CHURNED_ARR_USD > 0
)
ORDER BY CHURNED_ARR_USD DESC
LIMIT 100;
```

## 6. Answer ladders

The view's top-down hierarchy for each domain:

**ARR balance:**
Total Ending ARR → by segment → by product → customer list

**ARR movements (bridge):**
Net New ARR → movement type (New / Expansion / Contraction / Churn) → segment / product cut → customer list → (view stops here; no subscription-line grain)

**Retention:**
NRR (total) → by segment → by product → customer-level expansion / contraction / churn → (view stops here)

**Logos:**
Total active logos → new logos / churned logos → customer list → (view stops here)

## 7. Cautions

- **Bridge foot-check is mandatory.** Before presenting a bridge, verify: Starting ARR + New + Expansion − Contraction − Churn = Ending ARR. If the numbers do not foot, say by how much and do not present the bridge as reconciled.
- **Partial months.** The current open month may appear in the view with partial data. Label it; exclude it from bridge and retention calculations unless the user asks for it.
- **NRR window definition.** NRR is typically computed over a trailing 12-month window, but the view may use a different definition. Read the metric comment in `DESCRIBE` and state the definition in every NRR answer.
- **Customer key mismatch across views.** `ARR_ANALYTICS` uses a subscription/billing system customer key; `GTM_ANALYTICS` uses a Salesforce account key. Do not join or compare customer lists across views without a data-team–managed mapping.
- **New ARR ≠ New bookings.** New ARR is the ARR amount that went live (subscription started). New bookings ACV (GTM) is the ACV at the time of signing. These differ by timing and sometimes scope; never equate them without a reconciliation.
- **Contraction magnitude.** The view may store Contraction ARR as a positive number (the reduction amount) or as a negative number. Probe the sign on first run and state it in the bridge; in the displayed bridge always show Contraction and Churn in brackets.
