# ARR view detail

The view is `PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS`. This file is built from the live `DESCRIBE` on 2026-11-23, and every template below was run live.

## Contents
1. Tables and relationships
2. Grain rules
3. Dimensions
4. Metric catalogue
5. Verified query templates
6. Answer ladders
7. Cautions

---

## 1. Tables and relationships

| Logical table | Base table | PK | Grain |
|---|---|---|---|
| `ARR_WATERFALL` | `PROD_DB.REPORTING.RPT_ARR_BRIDGE` | `ARR_BRIDGE_KEY` | customer × category × month end (USD) |
| `CUSTOMER_BRIDGE` | `PROD_DB.REPORTING.RPT_CUSTOMER_BRIDGE` | `CUSTOMER_BRIDGE_KEY` | customer × category × month end (1 / 0 / −1) |
| `ARR_BY_PRODUCT` | `PROD_DB.GOLD.FACT_ARR` | `ARR_KEY` | customer × product family × month end. Closing balance on a dense grid, where a month with no ARR is 0 |
| `CUSTOMER` | `PROD_DB.GOLD.DIM_MAXIO_CUSTOMER` | `CUSTOMER_KEY` | unified customer |
| `PRODUCT` | `PROD_DB.GOLD.DIM_MAXIO_PRODUCT` | `PRODUCT_KEY` | product family (incl. manual adjustments' family and Unmapped) |
| `CALENDAR` | `PROD_DB.GOLD.DIM_DATE` | `DATE_KEY` (unique `DATE`) | day |
| `ACCOUNTING_PERIOD` | `PROD_DB.GOLD.DIM_ACCOUNTING_PERIOD` | `ACCOUNTING_PERIOD_KEY` | NetSuite month-length period |

| Relationship | From → To | Key |
|---|---|---|
| `ARR_WATERFALL_TO_CUSTOMER` | ARR_WATERFALL → CUSTOMER | `CUSTOMER_KEY` |
| `ARR_WATERFALL_TO_ACCOUNTING_PERIOD` | ARR_WATERFALL → ACCOUNTING_PERIOD | `ACCOUNTING_PERIOD_KEY` |
| `CUSTOMER_BRIDGE_TO_CUSTOMER` | CUSTOMER_BRIDGE → CUSTOMER | `CUSTOMER_KEY` |
| `CUSTOMER_BRIDGE_TO_ACCOUNTING_PERIOD` | CUSTOMER_BRIDGE → ACCOUNTING_PERIOD | `ACCOUNTING_PERIOD_KEY` |
| `ARR_BY_PRODUCT_TO_CUSTOMER` | ARR_BY_PRODUCT → CUSTOMER | `CUSTOMER_KEY` |
| `ARR_BY_PRODUCT_TO_PRODUCT` | ARR_BY_PRODUCT → PRODUCT | `PRODUCT_KEY` |
| `ARR_BY_PRODUCT_TO_CALENDAR` | ARR_BY_PRODUCT → CALENDAR | `MONTH_END_DATE` = `DATE` |

Not related: the bridges have no path to `PRODUCT` or `CALENDAR`, and `ARR_BY_PRODUCT` has no path to `ACCOUNTING_PERIOD`. Use the bridges' `ARR_MONTH_END` and `ARR_BY_PRODUCT.MONTH_END_DATE` as the time keys. Calendar = fiscal, so labels can be built from the date.

## 2. Grain rules

- **`ARR_WATERFALL`.** Each row is one category for one customer in one month. Use the per-category metrics, or `TOTAL_MTD/QTD/YTD/LTM` grouped by `CATEGORY`. Never sum `TOTAL_MTD` without `CATEGORY`, because it adds Beginning, Ending and the retention rows together.
- **`CUSTOMER_BRIDGE`.** Its QTD, YTD and LTM windows are independent counts. Never add months.
- **`ARR_BY_PRODUCT`.** `TOTAL_ARR` is a balance: read it at one month end, or group by month. Summed over product families, it equals `ARR_WATERFALL` Ending ARR (verified for Nov-26: $113,581,499.57).

## 3. Dimensions

| Dimension | Table | Values / notes |
|---|---|---|
| `ARR_MONTH_END` | ARR_WATERFALL, CUSTOMER_BRIDGE | month-end DATE |
| `CATEGORY` | ARR_WATERFALL | Beginning ARR, New, Upsell, Downsell, Churn, FX, Ending ARR, Gross Dollar Retention, Net Dollar Retention |
| `CATEGORY` | CUSTOMER_BRIDGE | Beginning Customers, New Customers, Lost Customers, Ending Customers |
| `MONTH_END_DATE` | ARR_BY_PRODUCT | month-end DATE |
| `CUSTOMER_NAME` | CUSTOMER | Yes Energy name, else RTO name |
| `CUSTOMER_SOURCE` | CUSTOMER | Yes Energy, RTO, APAC, EMEA, Multiple |
| `SEGMENT` | CUSTOMER | Physical, Financial, NULL (RTO-only) |
| `CUSTOMER_TYPE` | CUSTOMER | Yes Energy only; NULL for RTO-only customers |
| `INDUSTRY` | CUSTOMER | Yes Energy value, else RTO |
| `IS_YES_ENERGY_ACTIVE`, `IS_RTO_ACTIVE` | CUSTOMER | BOOLEAN active flags in each instance |
| `YES_ENERGY_CUSTOMER_ID`, `RTO_INSIDER_ID` | CUSTOMER | IDs (do not put them in shared files) |
| `PRODUCT_FAMILY` | PRODUCT | about 45 families, e.g. PowerSignals, Trading Regions, SettleCore, QuickSignals, Unmapped |
| `FISCAL_MONTH_YEAR` / `FISCAL_QUARTER_YEAR` / `FISCAL_YEAR` | ACCOUNTING_PERIOD | "November 2026" / "Q4 2026" / 2026 |
| `CALENDAR_MONTH_YEAR` / `CALENDAR_QUARTER_YEAR` / `CALENDAR_YEAR` | CALENDAR | "NOV-2026" / "Q4-2026" / 2026 |

## 4. Metric catalogue

**ARR_WATERFALL (USD, MTD unless noted)**

| Metric | Presented as | Definition / sign |
|---|---|---|
| `TOTAL_BEGINNING_ARR` | Beginning ARR | last month's closing ARR. + |
| `TOTAL_NEW_ARR` | New | first contract starts this month. + |
| `TOTAL_UPSELL_ARR` | Upsell | increase from existing customers, excl. FX. + |
| `TOTAL_DOWNSELL_ARR` | **Downsell (Operational)** | decrease from customers still active, excl. FX. − |
| `TOTAL_FX_ARR` | **Downsell (Translational)** | USD change on existing contracts from exchange rates only (monthly average rates). Signed: loss −, gain + |
| `TOTAL_CHURN_ARR` | Churn | ARR ended and never returns. − |
| `TOTAL_ENDING_ARR` | Ending ARR | closing balance |
| `NET_NEW_ARR` | Net new ARR | New + Upsell + Downsell (Op) + Churn, **excl. Translational** |
| `GROSS_DOLLAR_RETENTION` | GDR ($) | Beginning + Churn + Downsell (Op). GDR % = ÷ Beginning (derived) |
| `NET_DOLLAR_RETENTION` | NDR ($) | GDR + Upsell. NDR % = ÷ Beginning (derived) |
| `TOTAL_MTD` / `TOTAL_QTD` / `TOTAL_YTD` / `TOTAL_LTM` | window by `CATEGORY` | not pre-filtered; group by CATEGORY |
| `TOTAL_PY_MTD` / `_QTD` / `_YTD` / `_LTM` | prior-year twins | same month 12 months earlier |
| `YOY_MTD_GROWTH` | YoY change | SUM(MTD) − SUM(PY_MTD); use with a CATEGORY filter |

Derived (always labelled):
- Total Downsell = Downsell (Op) + Downsell (Transl).
- Ending − Beginning = Net new ARR + Downsell (Transl).
- Gross churn rate = −(Churn + Downsell (Op)) ÷ Beginning.
- YoY ARR growth % = Ending ÷ PY Ending − 1.

**CUSTOMER_BRIDGE (counts)**

`TOTAL_BEGINNING_CUSTOMERS`, `TOTAL_NEW_CUSTOMERS` (+), `TOTAL_LOST_CUSTOMERS` (−) and `TOTAL_ENDING_CUSTOMERS`. `NET_CUSTOMER_CHANGE` = New + Lost. There are also `TOTAL_MTD/QTD/YTD/LTM` and PY twins by `CATEGORY`. A customer is active when ARR > $10.

**ARR_BY_PRODUCT**

`TOTAL_ARR` is the closing ARR balance: subscription + renewal carry + manual adjustment balance.

## 5. Verified query templates

Prefix with `USE WAREHOUSE MCP_WH;` in Snowsight. Set the dates to the user's window.

**5a. Monthly bridge, presented**
```sql
SELECT ARR_MONTH_END,
       TOTAL_BEGINNING_ARR                         AS BEGINNING_ARR,
       TOTAL_NEW_ARR                               AS NEW_ARR,
       TOTAL_UPSELL_ARR                            AS UPSELL_ARR,
       TOTAL_DOWNSELL_ARR                          AS DOWNSELL_OPERATIONAL,
       TOTAL_FX_ARR                                AS DOWNSELL_TRANSLATIONAL,
       TOTAL_CHURN_ARR                             AS CHURN_ARR,
       TOTAL_ENDING_ARR                            AS ENDING_ARR,
       TOTAL_BEGINNING_ARR + TOTAL_NEW_ARR + TOTAL_UPSELL_ARR + TOTAL_DOWNSELL_ARR
         + TOTAL_FX_ARR + TOTAL_CHURN_ARR - TOTAL_ENDING_ARR AS TIE_OUT   -- must be 0
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_WATERFALL.ARR_MONTH_END
  METRICS ARR_WATERFALL.TOTAL_BEGINNING_ARR, ARR_WATERFALL.TOTAL_NEW_ARR, ARR_WATERFALL.TOTAL_UPSELL_ARR,
          ARR_WATERFALL.TOTAL_DOWNSELL_ARR, ARR_WATERFALL.TOTAL_FX_ARR, ARR_WATERFALL.TOTAL_CHURN_ARR,
          ARR_WATERFALL.TOTAL_ENDING_ARR
  WHERE ARR_WATERFALL.ARR_MONTH_END BETWEEN '2025-12-31' AND '2026-11-30')
ORDER BY ARR_MONTH_END;
```

**5b. QTD / YTD / LTM bridge with prior year** (swap `TOTAL_QTD` for `TOTAL_YTD` or `TOTAL_LTM`, and the matching PY metric)
```sql
SELECT CASE CATEGORY WHEN 'FX' THEN 'Downsell (Translational)'
                     WHEN 'Downsell' THEN 'Downsell (Operational)' ELSE CATEGORY END AS LINE,
       TOTAL_QTD AS CY, TOTAL_PY_QTD AS PY
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_WATERFALL.CATEGORY
  METRICS ARR_WATERFALL.TOTAL_QTD, ARR_WATERFALL.TOTAL_PY_QTD
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30')
ORDER BY ARRAY_POSITION(CATEGORY::VARIANT, ARRAY_CONSTRUCT('Beginning ARR','New','Upsell','Downsell','FX','Churn','Ending ARR','Gross Dollar Retention','Net Dollar Retention'));
```
For Q4 2026 at Nov-26 (QTD = Oct–Nov), the tie-out is 114,651,189.36 + 335,608.37 + 2,369,435.05 − 3,221,746.57 − 69,488.78 − 483,497.86 = 113,581,499.57.

**5c. Retention $ and %**
```sql
SELECT GROSS_DOLLAR_RETENTION, NET_DOLLAR_RETENTION, TOTAL_BEGINNING_ARR,
       GROSS_DOLLAR_RETENTION / NULLIF(TOTAL_BEGINNING_ARR,0) AS GDR_PCT,
       NET_DOLLAR_RETENTION  / NULLIF(TOTAL_BEGINNING_ARR,0) AS NDR_PCT
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  METRICS ARR_WATERFALL.GROSS_DOLLAR_RETENTION, ARR_WATERFALL.NET_DOLLAR_RETENTION, ARR_WATERFALL.TOTAL_BEGINNING_ARR
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30');
```
For YTD or LTM percentages, use 5b's window rows: 'Gross Dollar Retention' ÷ 'Beginning ARR'. For example, YTD Nov-26 GDR = 92.74mn ÷ 104.90mn = 88.4%, and NDR = 105.2%.

**5d. Customer drill for one category** (Downsell (Op) shown; swap the metric for New / Upsell / Churn / FX)
```sql
SELECT CUSTOMER_NAME, SEGMENT, CUSTOMER_SOURCE, TOTAL_DOWNSELL_ARR AS DOWNSELL_OPERATIONAL
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS CUSTOMER.CUSTOMER_NAME, CUSTOMER.SEGMENT, CUSTOMER.CUSTOMER_SOURCE
  METRICS ARR_WATERFALL.TOTAL_DOWNSELL_ARR
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30' AND ARR_WATERFALL.CATEGORY = 'Downsell')
WHERE DOWNSELL_OPERATIONAL <> 0
ORDER BY DOWNSELL_OPERATIONAL
LIMIT 100;
```
For a multi-month drill, use `BETWEEN` on `ARR_MONTH_END`, because flows add across months.

**5e. Downsell (Translational) by source system**
```sql
SELECT CUSTOMER_SOURCE, TOTAL_FX_ARR AS DOWNSELL_TRANSLATIONAL, TOTAL_ENDING_ARR
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS CUSTOMER.CUSTOMER_SOURCE
  METRICS ARR_WATERFALL.TOTAL_FX_ARR, ARR_WATERFALL.TOTAL_ENDING_ARR
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30')
ORDER BY DOWNSELL_TRANSLATIONAL;
```
In Nov-26, APAC (12.3k), EMEA (6.6k) and Multiple (3.1k) carried all of the translational downsell. Yes Energy and RTO had none.

**5f. Customer counts, window**
```sql
SELECT CATEGORY, TOTAL_MTD, TOTAL_QTD, TOTAL_YTD, TOTAL_PY_YTD
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS CUSTOMER_BRIDGE.CATEGORY
  METRICS CUSTOMER_BRIDGE.TOTAL_MTD, CUSTOMER_BRIDGE.TOTAL_QTD, CUSTOMER_BRIDGE.TOTAL_YTD, CUSTOMER_BRIDGE.TOTAL_PY_YTD
  WHERE CUSTOMER_BRIDGE.ARR_MONTH_END = '2026-11-30');
```

**5g. ARR by product family at two month ends**
```sql
SELECT PRODUCT_FAMILY, MONTH_END_DATE, TOTAL_ARR
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS PRODUCT.PRODUCT_FAMILY, ARR_BY_PRODUCT.MONTH_END_DATE
  METRICS ARR_BY_PRODUCT.TOTAL_ARR
  WHERE ARR_BY_PRODUCT.MONTH_END_DATE IN ('2025-12-31','2026-11-30'))
ORDER BY PRODUCT_FAMILY, MONTH_END_DATE;
```
Pivot the two dates in an outer query. The change is *derived*, a balance difference that includes FX, so it is not New or Upsell.

**5h. Segment bridge** (segment NULL shown as "Not set")
```sql
SELECT COALESCE(SEGMENT,'Not set') AS SEGMENT, TOTAL_BEGINNING_ARR, TOTAL_NEW_ARR, TOTAL_UPSELL_ARR,
       TOTAL_DOWNSELL_ARR AS DOWNSELL_OPERATIONAL, TOTAL_FX_ARR AS DOWNSELL_TRANSLATIONAL,
       TOTAL_CHURN_ARR, TOTAL_ENDING_ARR
FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS CUSTOMER.SEGMENT
  METRICS ARR_WATERFALL.TOTAL_BEGINNING_ARR, ARR_WATERFALL.TOTAL_NEW_ARR, ARR_WATERFALL.TOTAL_UPSELL_ARR,
          ARR_WATERFALL.TOTAL_DOWNSELL_ARR, ARR_WATERFALL.TOTAL_FX_ARR, ARR_WATERFALL.TOTAL_CHURN_ARR,
          ARR_WATERFALL.TOTAL_ENDING_ARR
  WHERE ARR_WATERFALL.ARR_MONTH_END = '2026-11-30');
```

## 6. Answer ladders

- **Balance:** Ending ARR → segment / source system → customer. Use product family via `ARR_BY_PRODUCT`.
- **Bridge:** Ending − Beginning → category (New, Upsell, Downsell (Op), Downsell (Transl), Churn) → segment / industry / source → customer (stop).
- **Retention:** NDR % → GDR % → Churn and Downsell (Op) → customer.
- **Customers:** Net change → New / Lost → customer list.

## 7. Cautions

- **Nov-26 downsell is concentrated.** Operational downsell was ($2.80mn), led by three customers at ($1.60mn). Check concentration before calling it a trend.
- **Renewal carry.** A customer can stay in ARR for up to 12 months after its subscriptions end. A sudden churn may be a carry running out.
- **Upsell from zero.** A zero-ARR contract that converts is Upsell, not New.
- **NULL segment / type.** RTO-only customers have no segment (about $16.5mn at Nov-26). Show them as "Not set".
- **Product "Portal/Access Fee" can be negative**, and **"Unmapped"** exists. Keep both in totals so the product split foots.
- **Open month.** If the latest month end is after today's date or still open, label it partial.
