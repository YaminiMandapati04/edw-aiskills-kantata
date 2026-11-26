# GTM Analytics (`GTM_ANALYTICS`)

Bookings and pipeline in one view, `PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS`. **Several grains; tables are joined only through shared dimensions, never fact to fact.** Deals only: leads are not in any table. KPI card metrics read the latest as-at date only.

Read `semantic-views.md` first for conventions, rules and the "words users say" table. `assets/semantic_view.yml` is the deployed definition, exported from Snowflake on 23 Nov 2026 (`SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS')`). Re-export it when the view changes.

**Three rules that hold everywhere:**
- **The fiscal year is the calendar year**, 1 January to 31 December, named by that year (January to December 2026 = FY2026; Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec). Build every QTD, YTD and LTM from monthly `_MTD` or from lines; never use the marts' `_QTD` / `_YTD` / `_LTM` (computed for one month's keys, so incomplete when rolled up).
- **Recurring bookings are won opportunity lines; non-recurring bookings are GL revenue.** Recurring = Salesforce closed-won opportunity lines on the close date, split by `BOOKING_METRIC` into ARR (New) (New Customer) and ARR (Upsell) (Upgrade, Renewal, Downgrade). Non-recurring = NetSuite one-time services revenue by subsidiary on the period end date.
- **Weighted pipeline, no targets.** Pipeline is read **weighted**: line ACV × Salesforce `PROBABILITY` ÷ 100 (`WEIGHTED_*`). Unweighted open pipeline is labelled context only. Pipeline created, won and lost ACV are unweighted (no weighted twin). The view holds no pipeline or bookings target, so there is no coverage ratio.

## Contents
1. What each table is for
2. Logical tables and grain
3. Joins and hierarchies
4. Metrics and derived KPIs
5. Query templates
6. Answer ladders
7. Dashboard coverage
8. Cautions

---

## 1. What each table is for

| Subject | Tables | Answers |
|---|---|---|
| Bookings | `BOOKINGS_OVERVIEW` (KPI mart), `BOOKING_LINES` (line detail) | Total, recurring (ARR (New), ARR (Upsell)) and non-recurring bookings by month; which products, product families, subsidiaries and accounts drove them |
| Pipeline KPIs | `PIPELINE_OVERVIEW` | Weighted and open pipeline (ACV), open count, average value, created value and count, at each month-end and today, with prior-year twins |
| Opportunity detail | `OPPORTUNITIES` | Current state of each opportunity line: stage, owner, source, type, product, probability, ACV, weighted ACV, won and lost |
| Stage movement | `OPPORTUNITY_STAGE_HISTORY` | Stage runs by opportunity × product: when each continuous stay in a stage started and ended, with owner, close date and ACV at the end of the run |
| Product | `DIM_PRODUCT` | Product name, family, line type and code for every fact table |

Not in the view: pipeline or bookings targets, loss reasons, subscription end date or state, activity or next steps, invoices, list price or discount. `REGION` exists but is always blank.

## 2. Logical tables and grain

| Table | Base | One row is | Notes |
|---|---|---|---|
| `BOOKINGS_OVERVIEW` | `REPORTING.RPT_GTM_BOOKINGS` | as-at month-end × `METRIC_NAME` × subsidiary × product × owner × account | Bookings KPIs at each completed month-end (from 31 Dec 2019), `IS_LATEST` on the last. `METRIC_NAME`: Total Bookings, Recurring Bookings, Non-Recurring Bookings, ARR (New), ARR (Upsell). Windows MTD / QTD / YTD / LTM and `PY` twins; only `_MTD` is used (§3) |
| `BOOKING_LINES` | `FACT_BOOKING` | one opportunity line item of a closed-won opportunity, or one monthly GL row | Salesforce rows: `BOOKING_SOURCE = 'Salesforce'`, `BOOKING_METRIC` ARR (New) (type New Customer) or ARR (Upsell) (Upgrade, Renewal, Downgrade), `PRODUCT` (Product2 name), `OPPORTUNITY_ID`, `OPPORTUNITY_LINE_ITEM_ID`, account and owner; no subsidiary. NetSuite rows: `'Non-Recurring'`, `'NetSuite'`, product One Time Services, one per month and subsidiary on the period end date; no account or opportunity. Fact `ACV_USD` (signed) |
| `PIPELINE_OVERVIEW` | `REPORTING.RPT_GTM_PIPELINE_OVERVIEW` | as-at date × `METRIC_NAME` × product × source × account × owner × close date × stage | Month-ends plus today (`IS_LATEST`). `METRIC_NAME`: Open Pipeline Value, **Weighted Pipeline Value**, Open Opportunities, Opportunities Created, Pipeline Created Value. Open metrics hold the same as-at level in every window. `OPPORTUNITY_ID` is filled only on the two count metrics (distinct count) |
| `OPPORTUNITIES` | `FACT_OPPORTUNITY` | one opportunity **line item** (plus one row for an opportunity with no lines) | **Current values only.** Attributes repeat on each line; `ACV_USD` is a line value (0 on an opportunity with no lines); counts are distinct opportunity IDs. Not deleted, not on a Test account. `PROBABILITY` (0–100) from Salesforce. `IS_ACTIVE_PIPELINE` = a pipeline stage and ACV > 0 (not the governed open filter, see Cautions) |
| `OPPORTUNITY_STAGE_HISTORY` | `REPORTING.RPT_GTM_PIPELINE_STAGE_HISTORY` | opportunity × product × stage run (`STAGE_RUN_NO`) | `STAGE_START_DATE`, `STAGE_END_DATE` (blank on the current run), `CLOSE_DATE` and `ACV_USD` at the end of the run, `STATUS`, `IS_CURRENT_STAGE`, milestone dates (blank until the stage-mapping milestone flags are filled). `ACV_USD` is not additive across runs; `CURRENT_ACV_USD` sums current-stage rows |
| `DIM_ACCOUNT` | `DIM_ACCOUNT` | Salesforce account | `ACCOUNT_NAME`, `INDUSTRY` |
| `DIM_DATE` | `DIM_DATE` | calendar day | Calendar year, quarter and month. With a calendar fiscal year, `YEAR` / `QUARTER` are the fiscal year and quarter |
| `DIM_PRODUCT` | `DIM_PRODUCT` | Salesforce Product2 (+ One Time Services) | `PRODUCT_NAME`, `PRODUCT_FAMILY`, `PRODUCT_LINE_TYPE`, `PRODUCT_CODE` |
| `DIM_STAGE_MAPPING` | `DIM_STAGE_MAPPING` | stage | `STAGE_ORDER` 1 (Stage 0) to 9 (Closed Won), `STAGE_TYPE`, `STATUS`, `IS_PIPELINE_STAGE` (Proposed Renewal to Invest), `IS_LEGACY_STAGE` |
| `DIM_SUBSIDIARY` | `DIM_SUBSIDIARY` | NetSuite subsidiary | Non-recurring rows only: Power Settlements, ENELYTIX |
| `DIM_USER` | `DIM_USER` | Salesforce user (opportunity owner) | Names are not unique; slice on `USER_KEY` |

## 3. Joins and hierarchies

```
BOOKINGS_OVERVIEW  --> DIM_DATE (DATE_KEY), DIM_ACCOUNT, DIM_PRODUCT (PRODUCT_KEY), DIM_SUBSIDIARY, DIM_USER (OWNER_KEY)
BOOKING_LINES      --> DIM_DATE (BOOKING_DATE -> DATE), DIM_ACCOUNT, DIM_PRODUCT, DIM_SUBSIDIARY, DIM_USER (OWNER_KEY)
PIPELINE_OVERVIEW  --> DIM_DATE (DATE_KEY), DIM_ACCOUNT, DIM_PRODUCT, DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
OPPORTUNITIES      --> DIM_DATE (PIPELINE_CREATION_DATE -> DATE), DIM_ACCOUNT, DIM_PRODUCT, DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
OPPORTUNITY_STAGE_HISTORY --> DIM_DATE (STAGE_START_DATE_KEY -> DATE_KEY), DIM_PRODUCT, DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
```

**`DIM_ACCOUNT` does not reach stage history**: take the account name from `OPPORTUNITIES` in a second statement and match on `OPPORTUNITY_ID`. `DIM_SUBSIDIARY` reaches only the bookings tables, and only NetSuite rows carry a subsidiary. `DIM_PRODUCT` reaches every fact table. `DIM_USER.ACCOUNT_KEY` and `DIM_ACCOUNT.USER_KEY` are attributes, not join paths.

| Hierarchy | Levels (top to bottom) | Notes |
|---|---|---|
| Bookings measure | Total Bookings › Recurring (Salesforce) and Non-Recurring (NetSuite) › under Recurring: ARR (New), ARR (Upsell) | Total = Recurring + Non-Recurring; Recurring = ARR (New) + ARR (Upsell) |
| Booking line | `BOOKING_SOURCE` › `BOOKING_METRIC` › `OPPORTUNITY_TYPE` › `PRODUCT_LINE_TYPE` › `PRODUCT_FAMILY` › `PRODUCT` › account › opportunity › line item | NetSuite rows stop at subsidiary |
| Pipeline status and stage | `STATUS` (Open, Closed Won, Closed Lost) › `STAGE_TYPE` (Open, Won, Lost) › `STAGE_NAME` (by `STAGE_ORDER`) | Stage 0, Proposed Renewal, Qualify, Discover, Align, Validate, Invest, Closed Lost, Closed Won. Late stage = Align onwards |
| Pipeline ownership | `OPPORTUNITY_SOURCE` › `OWNER_NAME` | `REGION` is always blank |
| Product | `PRODUCT_LINE_TYPE` › `PRODUCT_FAMILY` › `PRODUCT` (`DIM_PRODUCT`) | `PRODUCT_FAMILY` is also on `PIPELINE_OVERVIEW` and stage history |
| Window | MTD, QTD, YTD, LTM and prior-year twins `PYMTD`, `PYQTD`, `PYYTD`, `PYLTM` | **Only `_MTD` / `_PYMTD` are used**; QTD / YTD / LTM are summed from monthly `_MTD`. The stored `_QTD` / `_YTD` / `_LTM` are computed for one month's keys, so rolled up they come out incomplete |

## 4. Metrics and derived KPIs

| Table | Families | Notes |
|---|---|---|
| `BOOKINGS_OVERVIEW` (40) | `TOTAL_BOOKINGS_*`, `RECURRING_BOOKINGS_*`, `NON_RECURRING_BOOKINGS_*`, `ARR_NEW_*`, `ARR_UPSELL_*`, each MTD / QTD / YTD / LTM / PY twins | Use `_MTD` by `AS_OF_DATE` only, summed over the window's months. `_QTD` / `_YTD` / `_LTM` and their PY twins are not used |
| `BOOKING_LINES` (5) | `BOOKING_ACV_USD`, `ARR_NEW_ACV_USD`, `ARR_UPSELL_ACV_USD`, `NON_RECURRING_BOOKINGS_ACV_USD`, `BOOKING_LINE_COUNT` | `BOOKING_ACV_USD` mixes recurring and non-recurring unless filtered by `BOOKING_METRIC`. There is no booked-opportunity count metric: count `DISTINCT OPPORTUNITY_ID` outside the view call |
| `PIPELINE_OVERVIEW` (51) | **`WEIGHTED_PIPELINE_VALUE_*`**, `OPEN_PIPELINE_VALUE_*`, `OPEN_OPPORTUNITIES_*`, `AVG_OPPORTUNITY_VALUE_ACV_*` (unweighted), `PIPELINE_CREATED_ACV_*`, `OPPORTUNITIES_CREATED_*`, trend metrics **`WEIGHTED_PIPELINE_ACV_ASAT`**, `OPEN_PIPELINE_ACV_ASAT`, `OPEN_OPPORTUNITIES_ASAT` | Cards read `_MTD` / `_PYMTD` (pipeline is a point-in-time snapshot); `_QTD` / `_YTD` / `_LTM` are not used, and pipeline created is summed by month from `OPPORTUNITIES`. Weighted average value = weighted value ÷ open opportunities (derived). No target or coverage metric exists |
| `OPPORTUNITIES` (23) | **`WEIGHTED_OPEN_PIPELINE_ACV`**, `OPEN_PIPELINE_ACV`, `OPEN_OPPORTUNITIES`, `OPEN_OPPORTUNITIES_PRIOR_YEAR`, `AVERAGE_OPPORTUNITY_VALUE`(`_PRIOR_YEAR`), `PIPELINE_CREATED_ACV`, `OPPORTUNITIES_CREATED`, `CREATED_OPPORTUNITIES_*` (windows on `CURRENT_DATE()`), `WON_ACV_USD`, `WON_OPPORTUNITIES`, `LOST_ACV_USD`, `LOST_OPPORTUNITIES`, `WIN_RATE`, `TOTAL_ACV_USD`, `TOTAL_OPPORTUNITIES` | Counts are distinct opportunities. Open metrics filter `NOT IS_CLOSED AND PIPELINE_CREATION_DATE <= CURRENT_DATE()`; won / lost use `STATUS`. Fact `PROBABILITY` |
| `OPPORTUNITY_STAGE_HISTORY` (3) | `STAGE_CHANGES` (distinct stage runs), `OPPORTUNITIES_IN_HISTORY`, `CURRENT_ACV_USD` | Fact `ACV_USD` (end of run). Days in stage are computed |

| KPI | How |
|---|---|
| Bookings growth | Monthly `TOTAL_BOOKINGS_MTD` summed over the fiscal window (LTM = the last twelve months), against the same months a quarter or a year earlier |
| Recurring share | recurring ÷ total for the same months |
| New vs upsell | `ARR_NEW_MTD` / `ARR_UPSELL_MTD` by month, or `BOOKING_ACV_USD` on `BOOKING_LINES` by `BOOKING_METRIC` (and `OPPORTUNITY_TYPE` within ARR (Upsell)) |
| Average deal value | recurring `BOOKING_ACV_USD` ÷ distinct booked `OPPORTUNITY_ID` for the window (derived) |
| Weighted pipeline | `WEIGHTED_PIPELINE_VALUE_MTD` (card) or `WEIGHTED_OPEN_PIPELINE_ACV` (lines); a year earlier `WEIGHTED_PIPELINE_VALUE_PYMTD` |
| Weighting factor | weighted ÷ unweighted open pipeline at the same date (derived; 49% on 23 Nov 2026) |
| Conversion | `WIN_RATE` (count) for a `CLOSE_DATE` period; by value = won ÷ (won + lost) ACV (unweighted) |
| Sales cycle | days from `CREATED_DATE` to `CLOSE_DATE` on won opportunities (derived) |
| Days in stage | `DATEDIFF('day', STAGE_START_DATE, STAGE_END_DATE)` on completed runs (`STAGE_END_DATE IS NOT NULL`) |
| Stage age of an open deal (proxy for "stalled") | data as-at date − `STAGE_START_DATE` on `IS_CURRENT_STAGE = TRUE`, `STATUS = 'Open'` rows. **Derived proxy**: the view has no activity data |
| Close-date pushes | `CLOSE_DATE` at the end of consecutive runs (`STAGE_RUN_NO`) of one opportunity and product. Only visible at stage changes: a push within a stage shows only against today's close date |

## 5. Query templates

```sql
-- Monthly bookings by measure (one row per completed month-end); sum the months for fiscal QTD / YTD / LTM
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD, BOOKINGS_OVERVIEW.RECURRING_BOOKINGS_MTD,
             BOOKINGS_OVERVIEW.ARR_NEW_MTD, BOOKINGS_OVERVIEW.ARR_UPSELL_MTD,
             BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_PYMTD
  WHERE      BOOKINGS_OVERVIEW.AS_OF_DATE >= '<start>'
) ORDER BY AS_OF_DATE;
```

```sql
-- Fiscal year to date bookings (FY2026 = from 1 Jan 2026) against the same months a year earlier
SELECT SUM(IFF(AS_OF_DATE BETWEEN '2026-01-01' AND '<month-end>', TOTAL_BOOKINGS_MTD, 0)) AS FYTD,
       SUM(IFF(AS_OF_DATE BETWEEN '2025-01-01' AND DATEADD('year', -1, '<month-end>'), TOTAL_BOOKINGS_MTD, 0)) AS PY_FYTD
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD
  WHERE      BOOKINGS_OVERVIEW.AS_OF_DATE >= '2025-01-01'
);
```

```sql
-- ARR (New) vs ARR (Upsell) by opportunity type vs non-recurring, by month
SELECT DATE_TRUNC('month', BOOKING_DATE) AS MONTH, BOOKING_METRIC, OPPORTUNITY_TYPE, SUM(BOOKING_ACV_USD) AS ACV
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKING_LINES.BOOKING_DATE, BOOKING_LINES.BOOKING_METRIC, BOOKING_LINES.OPPORTUNITY_TYPE
  METRICS    BOOKING_LINES.BOOKING_ACV_USD
  WHERE      BOOKING_LINES.BOOKING_DATE BETWEEN '<start>' AND '<end>'
) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
```

```sql
-- Recurring bookings behind a month: by account, product family, product and opportunity
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS DIM_ACCOUNT.ACCOUNT_NAME, BOOKING_LINES.OPPORTUNITY_ID, DIM_PRODUCT.PRODUCT_FAMILY, BOOKING_LINES.PRODUCT,
             BOOKING_LINES.BOOKING_METRIC, BOOKING_LINES.OPPORTUNITY_TYPE
  METRICS    BOOKING_LINES.BOOKING_ACV_USD
  WHERE      BOOKING_LINES.BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)')
         AND BOOKING_LINES.BOOKING_DATE BETWEEN '<month start>' AND '<month end>'
) ORDER BY BOOKING_ACV_USD DESC LIMIT 25;
```

```sql
-- Pipeline cards today, WEIGHTED, against a year earlier (point-in-time: _MTD / _PYMTD; never the _QTD / _YTD / _LTM columns).
-- The unweighted open value comes along only as labelled context.
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  METRICS PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_PYMTD,
          PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_MTD, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_PYMTD,
          PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_PYMTD
  WHERE   PIPELINE_OVERVIEW.IS_LATEST = TRUE
);
-- pipeline created for a window: OPPORTUNITIES.PIPELINE_CREATED_ACV by month of PIPELINE_CREATION_DATE, summed over the window's months (unweighted)
```

```sql
-- Weighted pipeline trend at each month-end
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS PIPELINE_OVERVIEW.AS_OF_DATE
  METRICS    PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_ACV_ASAT, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_ASAT
  WHERE      PIPELINE_OVERVIEW.AS_OF_DATE >= '<start>'
) ORDER BY AS_OF_DATE;
```

```sql
-- Weighted pipeline by stage and fiscal (calendar) close quarter (today)
SELECT STAGE_ORDER, STAGE_NAME,
       'FY' || YEAR(CLOSE_DATE) || '-Q' || QUARTER(CLOSE_DATE) AS FISCAL_CLOSE_QUARTER,
       SUM(WEIGHTED_OPEN_PIPELINE_ACV) AS WEIGHTED_ACV, SUM(OPEN_PIPELINE_ACV) AS UNWEIGHTED_ACV, SUM(OPEN_OPPORTUNITIES) AS DEALS
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS OPPORTUNITIES.STAGE_ORDER, OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.CLOSE_DATE
  METRICS    OPPORTUNITIES.WEIGHTED_OPEN_PIPELINE_ACV, OPPORTUNITIES.OPEN_PIPELINE_ACV, OPPORTUNITIES.OPEN_OPPORTUNITIES
  WHERE      NOT OPPORTUNITIES.IS_CLOSED
) GROUP BY 1, 2, 3 ORDER BY 1, 3;
```

`SUM(OPEN_OPPORTUNITIES)` across close dates counts a deal once per close date, which matches the deal because each opportunity has one close date. Across products, use the governed metric without the product dimension.

```sql
-- Win rate and won / lost ACV by fiscal quarter of close and source (unweighted)
SELECT 'FY' || YEAR(CLOSE_DATE) || '-Q' || QUARTER(CLOSE_DATE) AS FISCAL_QUARTER,
       OPPORTUNITY_SOURCE, SUM(WON_OPPORTUNITIES) AS WON, SUM(LOST_OPPORTUNITIES) AS LOST,
       SUM(WON_ACV_USD) AS WON_ACV, SUM(LOST_ACV_USD) AS LOST_ACV
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS OPPORTUNITIES.CLOSE_DATE, OPPORTUNITIES.OPPORTUNITY_SOURCE
  METRICS    OPPORTUNITIES.WON_OPPORTUNITIES, OPPORTUNITIES.LOST_OPPORTUNITIES, OPPORTUNITIES.WON_ACV_USD, OPPORTUNITIES.LOST_ACV_USD
  WHERE      OPPORTUNITIES.STATUS <> 'Open' AND OPPORTUNITIES.CLOSE_DATE BETWEEN '<start>' AND '<end>'
) GROUP BY 1, 2 ORDER BY 1, 2;
```

```sql
-- Typical days in each stage (completed runs of at least a day)
SELECT STAGE_NAME, MEDIAN(DAYS) AS MEDIAN_DAYS, AVG(DAYS) AS MEAN_DAYS, COUNT(*) AS RUNS
FROM (SELECT DISTINCT OPPORTUNITY_ID, PRODUCT_KEY, STAGE_RUN_NO, STAGE_NAME, DATEDIFF('day', STAGE_START_DATE, STAGE_END_DATE) AS DAYS
      FROM SEMANTIC_VIEW(
        PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
        DIMENSIONS OPPORTUNITY_STAGE_HISTORY.OPPORTUNITY_ID, OPPORTUNITY_STAGE_HISTORY.PRODUCT_KEY, OPPORTUNITY_STAGE_HISTORY.STAGE_RUN_NO,
                   OPPORTUNITY_STAGE_HISTORY.STAGE_NAME, OPPORTUNITY_STAGE_HISTORY.STATUS,
                   OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE, OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE
        WHERE OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE IS NOT NULL AND OPPORTUNITY_STAGE_HISTORY.STATUS = 'Open'
          AND OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE >= '<start>'))
WHERE DAYS >= 1 GROUP BY 1 ORDER BY 1;
```

The fiscal quarter is the calendar quarter: `'FY' || YEAR(d) || '-Q' || QUARTER(d)` (for example 2026-08-15 → `FY2026-Q3`).

## 6. Answer ladders

| Question | Ladder (top to bottom) | Source |
|---|---|---|
| How are bookings tracking vs last year? | 1. Total bookings for the fiscal window vs the same months last year. 2. Recurring vs non-recurring. 3. ARR (New) vs ARR (Upsell). 4. By product family / product (recurring) and subsidiary (non-recurring) | `BOOKINGS_OVERVIEW` `_MTD`, `BOOKING_LINES` |
| Why did bookings go up? | 1. Confirm the move: window vs prior period. 2. ARR (New) vs ARR (Upsell) vs non-recurring. 3. By product, by subsidiary: contribution and share. 4. By account and deal. 5. One-off or repeat | `BOOKING_LINES` |
| Where is new business coming from? | 1. ARR (New) by month. 2. By product line type and product. 3. By account. 4. Deals and average deal value | `BOOKING_LINES` (`BOOKING_METRIC = 'ARR (New)'`) |
| How healthy is the pipeline? | 1. Weighted pipeline and open count vs a year earlier (unweighted as context). 2. By stage (`STAGE_ORDER`). 3. By fiscal close quarter. 4. By product family, source and owner | `PIPELINE_OVERVIEW`, `OPPORTUNITIES` |
| Do we have enough pipeline? | No target is in the view, so no coverage ratio. Give weighted pipeline closing in each fiscal quarter, late-stage share, and the straight-line range; say a target would be needed for coverage | `OPPORTUNITIES` |
| Which open pipeline looks at risk? | 1. Total weighted pipeline. 2. Weighted value past its expected close date, pushed out, or longer than typical in its stage (proxy, labelled). 3. High-value deals ($100k ACV or more) among them | `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY` |
| Win rate and why we lose? | 1. Win rate for the `CLOSE_DATE` period, by count and by value. 2. By product, source, owner. 3. Lost ACV by stage lost at (**no loss reason in the view**) | `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY` |
| Where are deals getting stuck? | 1. Median and P90 days per stage from completed runs. 2. By stage and product. 3. By owner. 4. Longest-running open deals | `OPPORTUNITY_STAGE_HISTORY` |
| Which deals might close this quarter? | 1. Weighted pipeline with a close date in the current quarter. 2. By stage (late stage = Align onwards) and probability. 3. By owner. 4. The deals | `OPPORTUNITIES` |
| Which customers are stuck, and what is at stake? | 1. Median completed stay per stage. 2. Open deals whose current stage is longer than 2× the median of other accounts' stays. 3. Their weighted ACV | `OPPORTUNITY_STAGE_HISTORY`, `OPPORTUNITIES` |
| How did one deal progress? | 1. Opportunity summary. 2. Stage runs in order (`STAGE_RUN_NO`) by product. 3. Owner, close date and ACV at the end of each run | `OPPORTUNITY_STAGE_HISTORY` |

## 7. Dashboard coverage

| Page | Visual | Status |
|---|---|---|
| 1. Bookings | Cards: Total, Recurring, ARR (New), ARR (Upsell), Non-recurring with prior year; monthly trend; product and subsidiary filters | Yes. QTD, YTD and LTM summed from monthly `_MTD` |
| | Average deal value | Derived (`BOOKING_LINES`) |
| 2. Pipeline Overview | Cards with prior year; pipeline value trend; created trend; pipeline by stage and close quarter | Yes, **weighted** ACV (unweighted as context). No target or coverage (none in the view) |
| 3. Opportunities Details | Opportunity summary (dates, stage, source, product, type, owner, value, probability); stage history | Yes (stage runs by product). Loss reason: **not available** |

The Power BI pages show the trend and the tables. The GTM dashboard (`dashboards.md`) reads the same tables and adds the diagnosis: what moved bookings, whether it repeats, what the pipeline could deliver, and what to decide.

## 8. Cautions

- **Windows from `_MTD` only.** Build bookings QTD, YTD and LTM from monthly `_MTD` and read pipeline from `_MTD` / `_PYMTD` at one date; never use or roll up a mart's `_QTD` / `_YTD` / `_LTM` (computed for one month's keys, so incomplete). Label every period with its fiscal year (FY2026 = calendar 2026).
- **The latest month may not be closed.** `BOOKINGS_OVERVIEW` publishes a month-end as soon as the month ends; its non-recurring revenue arrives when NetSuite closes the month. Use the latest month NetSuite has closed.
- **Recurring and non-recurring carry different dimensions.** Account, owner and opportunity exist only on recurring rows; subsidiary only on non-recurring rows; non-recurring rows carry the product One Time Services. An account cut covers recurring bookings only; say so.
- **Weighted by default.** Report pipeline weighted (`WEIGHTED_*`, ACV × `PROBABILITY` ÷ 100) and say so. Never add weighted to unweighted. Created, won and lost ACV are unweighted.
- **Use the governed open filter.** Open metrics use `NOT IS_CLOSED` (and `PIPELINE_CREATION_DATE <= today`); `IS_ACTIVE_PIPELINE` is narrower (pipeline stage and ACV > 0) and does not tie to the card.
- **Line-item grain.** `OPPORTUNITIES` and stage history repeat opportunity attributes on each product line. ACV adds across lines; counts are distinct opportunities. Never sum counts across product rows of the same deal.
- **No targets.** There is no pipeline or bookings target in the view: never state coverage or attainment.
- **Cards vs trends.** Card metrics return one value per as-at date: filter `IS_LATEST = TRUE` (bookings: last month-end; pipeline: today). Trend metrics (`*_ASAT`) need one date per bar.
- **Closed periods use `CLOSE_DATE`; created periods use `PIPELINE_CREATION_DATE`** (equal to the created date).
- **`CREATED_OPPORTUNITIES_*` on `OPPORTUNITIES` are windowed on `CURRENT_DATE()`**, not on a month-end: for a closed month use `OPPORTUNITIES_CREATED` by month of `PIPELINE_CREATION_DATE`.
- **Stage-history values are not additive across runs.** Use `IS_CURRENT_STAGE = TRUE` (or `CURRENT_ACV_USD`) for totals.
- **Days in stage is computed, not stored.** Use completed runs for typical stays; the current run is still open.
- **Owner names aren't unique.** Slice on `USER_KEY` (`OWNER_KEY`) when ranking reps.
