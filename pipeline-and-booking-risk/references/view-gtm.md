# GTM Analytics (`GTM_ANALYTICS`)

Bookings and pipeline in one view, `PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS`. **Several grains; tables are joined only through shared dimensions, never fact to fact.** Deals only: leads are not in any table. KPI card metrics read the latest as-at date only.

Read `semantic-views.md` first for conventions, rules and the "words users say" table. `assets/semantic_view.yml` is the deployed definition, exported from Snowflake on 18 Nov 2026 (`SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW`); re-export it when the view changes.

**Three rules that hold everywhere:**
- **Fiscal year 1 February to 31 January**, named by the year it ends (February 2026 to January 2027 = FY2027; Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan). Build every QTD, YTD and LTM from monthly `_MTD` or from lines; never use the marts' `_QTD` / `_YTD` / `_LTM` (computed for one month's keys, so incomplete when rolled up). `BOOKINGS_OVERVIEW` windows and `DIM_DATE` quarter and year are also **calendar**.
- **Recurring bookings are won opportunities; non-recurring bookings are income-statement revenue.** Recurring = Salesforce won New Sales and Seat Expansion opportunities at blended ARR on the close date. Non-recurring = NetSuite non-recurring revenue by subsidiary on the period end date.
- **Unweighted pipeline, no targets.** Read open pipeline at face value; the `WEIGHTED_PIPELINE_VALUE_*` metrics are not used. The view holds no pipeline or bookings target, so there is no coverage ratio.

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
| Bookings | `BOOKINGS_OVERVIEW` (KPI mart), `BOOKING_LINES` (line detail) | Total, recurring and non-recurring bookings by month; new sales vs seat expansion (lines, by `OPPORTUNITY_TYPE`); which products, subsidiaries and accounts drove them |
| Pipeline KPIs | `PIPELINE_OVERVIEW` | Open pipeline (ACV), open count, average value, created value and count, at each month-end and today, with fiscal windows and prior-year twins |
| Opportunity detail | `OPPORTUNITIES` | Current state of each opportunity: stage, owner, source, type, product, region, ACV, won and lost |
| Stage movement | `OPPORTUNITY_STAGE_HISTORY` | Stage runs: when each continuous stay in a stage started and ended, with owner, close date and ACV at the end of the run |

Not in the view: pipeline or bookings targets, loss reasons, subscription type or state, renewal opportunities, activity or next steps, invoices, list price or discount.

## 2. Logical tables and grain

| Table | Base | One row is | Notes |
|---|---|---|---|
| `BOOKINGS_OVERVIEW` | `REPORTING.RPT_GTM_BOOKINGS` | as-at month-end × `METRIC_NAME` × subsidiary × product × account × owner | Bookings KPIs at each completed month-end, `IS_LATEST` on the last. `METRIC_NAME`: Total Bookings, Recurring Bookings, Recurring Services (= Recurring Bookings), Non-Recurring Bookings, ARR (New) and ARR (Upsell) (**always 0**). Windows MTD / QTD / YTD / LTM and `PY` twins are **calendar**; only `_MTD` is used (§3) |
| `BOOKING_LINES` | `GOLD.FACT_BOOKING` | one booking | Salesforce lines: `BOOKING_METRIC = 'Recurring Services'`, `BOOKING_SOURCE = 'Salesforce'`, `OPPORTUNITY_TYPE` New Sales or Seat Expansion, `PRODUCT` SX or OX, `OPPORTUNITY_ID`, account and owner; no subsidiary. NetSuite lines: `'Non-Recurring'`, `'NetSuite'`, one per month and subsidiary on the period end date; no account, product or opportunity. Fact `ACV_USD` |
| `PIPELINE_OVERVIEW` | `REPORTING.RPT_GTM_PIPELINE_OVERVIEW` | as-at date × `METRIC_NAME` × opportunity × product × source × region × account × owner × close date × stage | Month-ends plus today (`IS_LATEST`). `METRIC_NAME`: Open Pipeline Value, Open Opportunities, Weighted Pipeline Value (not used), Opportunities Created, Pipeline Created Value. Windows are **fiscal**; open metrics hold the same as-at level in every window |
| `OPPORTUNITIES` | `GOLD.FACT_OPPORTUNITY` | one opportunity | **Current values only.** Scope: New Sales and Seat Expansion opportunities of the Corporate, Enterprise and Large Enterprise segments, not deleted, not test, not Duplicate. `IS_ACTIVE_PIPELINE` = a pipeline stage (01 to 06) and ACV above 0. `ACV_USD` is blended ARR |
| `OPPORTUNITY_STAGE_HISTORY` | `REPORTING.RPT_GTM_PIPELINE_STAGE_HISTORY` | opportunity × stage run (`STAGE_RUN_NO`; one continuous stay in a stage) | `STAGE_START_DATE`, `STAGE_END_DATE` (blank on the current run), `CLOSE_DATE` and `ACV_USD` at the end of the run, `STATUS`, `IS_CURRENT_STAGE`, milestone dates (04 - PROPOSE, 06 - NEGOTIATE). `ACV_USD` is not additive across runs |
| `DIM_ACCOUNT` | `GOLD.DIM_ACCOUNT` | Salesforce account | `ACCOUNT_NAME`, `INDUSTRY`; reaches bookings (Salesforce lines), opportunities and pipeline overview |
| `DIM_DATE` | `GOLD.DIM_DATE` | calendar day | **Calendar** year, quarter and month only: never use its quarter or year for fiscal periods |
| `DIM_STAGE_MAPPING` | `GOLD.DIM_STAGE_MAPPING` | stage | `STAGE_ORDER` 1 (00 - PROSPECT) to 9 (07 - CLOSE (LOST)), `STAGE_TYPE`, `STATUS`, `IS_PIPELINE_STAGE` (01 to 06), `IS_LEGACY_STAGE` |
| `DIM_SUBSIDIARY` | `GOLD.DIM_SUBSIDIARY` | NetSuite subsidiary | Non-recurring lines only: three legal entities |
| `DIM_USER` | `GOLD.DIM_USER` | Salesforce user (opportunity owner) | Names are not unique; slice on `USER_KEY` |

## 3. Joins and hierarchies

```
BOOKINGS_OVERVIEW  --> DIM_DATE (DATE_KEY), DIM_ACCOUNT, DIM_SUBSIDIARY, DIM_USER (OWNER_KEY)
BOOKING_LINES      --> DIM_DATE (BOOKING_DATE -> DATE), DIM_ACCOUNT, DIM_SUBSIDIARY, DIM_USER (OWNER_KEY)
PIPELINE_OVERVIEW  --> DIM_DATE (DATE_KEY), DIM_ACCOUNT, DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
OPPORTUNITIES      --> DIM_DATE (PIPELINE_CREATION_DATE -> DATE), DIM_ACCOUNT, DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
OPPORTUNITY_STAGE_HISTORY --> DIM_DATE (STAGE_START_DATE_KEY -> DATE_KEY), DIM_STAGE_MAPPING, DIM_USER (OWNER_KEY)
```

**`DIM_ACCOUNT` does not reach stage history**: take the account name from `OPPORTUNITIES` in a second statement and match on `OPPORTUNITY_ID`. `DIM_SUBSIDIARY` reaches only the bookings tables, and only NetSuite lines carry a subsidiary. `DIM_USER.ACCOUNT_KEY` and `DIM_ACCOUNT.USER_KEY` are attributes, not join paths.

| Hierarchy | Levels (top to bottom) | Notes |
|---|---|---|
| Bookings measure | Total Bookings › Recurring (Salesforce) and Non-Recurring (NetSuite) › under Recurring: New Sales, Seat Expansion (`BOOKING_LINES.OPPORTUNITY_TYPE`) | Total = Recurring + Non-Recurring, to the cent. The view's ARR (New) / ARR (Upsell) are 0: split recurring by `OPPORTUNITY_TYPE` on lines |
| Booking line | `BOOKING_SOURCE` › `BOOKING_METRIC` › `OPPORTUNITY_TYPE` › `PRODUCT` (SX, OX) › account › opportunity | NetSuite lines stop at subsidiary |
| Pipeline status and stage | `STATUS` (Open, Closed Won, Closed Lost) › `STAGE_TYPE` (Open, Won, Lost) › `STAGE_NAME` (by `STAGE_ORDER`) | Stages `00 - PROSPECT`, `01 - ENGAGE`, `02 - DISCOVER`, `03 - EVALUATE`, `04 - PROPOSE`, `05 - SECURE`, `06 - NEGOTIATE`, `07 - CLOSE (WON)`, `07 - CLOSE (LOST)`. Late stage = 04 - PROPOSE onwards |
| Pipeline ownership | `REGION` (NorAm, EMEA) › `OPPORTUNITY_SOURCE` › `OWNER_NAME` | Sources: Marketing, Expansion/Renewal, Sales, Operations, a few others and blank |
| Pipeline product | `PRODUCT` (OX, SX, Undecided, Unassigned) | `PRODUCT_FAMILY` repeats `PRODUCT` on pipeline overview and stage history |
| Window | MTD, QTD, YTD, LTM and prior-year twins `PYMTD`, `PYQTD`, `PYYTD`, `PYLTM` | **Only `_MTD` / `_PYMTD` are used**; QTD / YTD / LTM are summed from monthly `_MTD` over the fiscal months. The stored `_QTD` / `_YTD` / `_LTM` (pipeline: fiscal; bookings: calendar) are not used: computed for one month's keys, so rolled up they come out incomplete |

## 4. Metrics and derived KPIs

| Table | Families | Notes |
|---|---|---|
| `BOOKINGS_OVERVIEW` (48) | `TOTAL_BOOKINGS_*`, `RECURRING_BOOKINGS_*`, `RECURRING_SERVICES_*`, `NON_RECURRING_BOOKINGS_*`, `ARR_NEW_*`, `ARR_UPSELL_*`, each MTD / QTD / YTD / LTM / PY twins | Use `_MTD` by `AS_OF_DATE` only, summed over the window's months; `_QTD` / `_YTD` / `_LTM` and their PY twins are not used (see Window above; `_QTD` / `_YTD` are also calendar); `ARR_NEW_*` / `ARR_UPSELL_*` are always 0 |
| `BOOKING_LINES` (6) | `BOOKING_ACV_USD`, `NON_RECURRING_BOOKINGS_ACV_USD`, `BOOKED_OPPORTUNITIES`, `BOOKING_LINE_COUNT`, `ARR_NEW_ACV_USD` / `ARR_UPSELL_ACV_USD` (always 0) | `BOOKING_ACV_USD` mixes recurring and non-recurring unless filtered by `BOOKING_METRIC` |
| `PIPELINE_OVERVIEW` (50) | `OPEN_PIPELINE_VALUE_*`, `OPEN_OPPORTUNITIES_*`, `AVG_OPPORTUNITY_VALUE_ACV_*`, `PIPELINE_CREATED_ACV_*`, `OPPORTUNITIES_CREATED_*` (fiscal windows and PY twins), trend metrics `OPEN_PIPELINE_ACV_ASAT`, `OPEN_OPPORTUNITIES_ASAT`; `WEIGHTED_PIPELINE_VALUE_*` | Cards read `_MTD` / `_PYMTD` (open pipeline is a point-in-time snapshot; `_MTD` equals `_QTD` at every as-at date, checked 2026-11-19); `_QTD` / `_YTD` / `_LTM` are not used, and pipeline created is summed by month from `OPPORTUNITIES`. Weighted metrics are not used (unweighted pipeline). No target or coverage metric exists |
| `OPPORTUNITIES` (12) | `OPEN_PIPELINE_ACV`, `OPEN_OPPORTUNITIES`, `AVERAGE_OPPORTUNITY_VALUE`, `PIPELINE_CREATED_ACV`, `OPPORTUNITIES_CREATED`, `WON_ACV_USD`, `WON_OPPORTUNITIES`, `LOST_ACV_USD`, `LOST_OPPORTUNITIES`, `WIN_RATE`, `TOTAL_ACV_USD`, `TOTAL_OPPORTUNITIES` | Counts are distinct opportunities |
| `OPPORTUNITY_STAGE_HISTORY` (2) | `STAGE_CHANGES` (stage runs), `OPPORTUNITIES_IN_HISTORY` | Fact `ACV_USD` (end of run). Days in stage are computed |

| KPI | How |
|---|---|
| Bookings growth | Monthly `TOTAL_BOOKINGS_MTD` summed over the fiscal window (LTM = the last twelve months), against the same months a quarter or a year earlier |
| Recurring share | recurring ÷ total for the same months |
| New sales vs seat expansion | `BOOKING_ACV_USD` on `BOOKING_LINES` where `BOOKING_METRIC = 'Recurring Services'`, by `OPPORTUNITY_TYPE` |
| Average deal value | recurring `BOOKING_ACV_USD` ÷ `BOOKED_OPPORTUNITIES` for the window (derived) |
| Conversion | `WIN_RATE` (count) for a `CLOSE_DATE` period; by value = won ÷ (won + lost) ACV |
| Sales cycle | days from `CREATED_DATE` to `CLOSE_DATE` on won opportunities (derived) |
| Days in stage | `DATEDIFF('day', STAGE_START_DATE, STAGE_END_DATE)` on completed runs (`STAGE_END_DATE IS NOT NULL`) |
| Stage age of an open deal (proxy for "stalled") | data as-at date − `STAGE_START_DATE` on `IS_CURRENT_STAGE = TRUE`, `STATUS = 'Open'` rows. **Derived proxy**: the view has no activity data |
| Close-date pushes | `CLOSE_DATE` at the end of consecutive runs (`STAGE_RUN_NO`) of one opportunity. Only visible at stage changes: a push within a stage shows only against today's close date |

## 5. Query templates

```sql
-- Monthly bookings by measure (one row per completed month-end); sum the months for fiscal QTD / YTD / LTM
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD, BOOKINGS_OVERVIEW.RECURRING_BOOKINGS_MTD,
             BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_PYMTD
  WHERE      BOOKINGS_OVERVIEW.AS_OF_DATE >= '<start>'
) ORDER BY AS_OF_DATE;
```

```sql
-- Fiscal year to date bookings (FY2027 = from 1 Feb 2026) against the same months a year earlier
SELECT SUM(IFF(AS_OF_DATE BETWEEN '2026-02-01' AND '<month-end>', TOTAL_BOOKINGS_MTD, 0)) AS FYTD,
       SUM(IFF(AS_OF_DATE BETWEEN '2025-02-01' AND DATEADD('year', -1, '<month-end>'), TOTAL_BOOKINGS_MTD, 0)) AS PY_FYTD
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD
  WHERE      BOOKINGS_OVERVIEW.AS_OF_DATE >= '2025-02-01'
);
```

```sql
-- New sales vs seat expansion vs non-recurring, by month
SELECT DATE_TRUNC('month', BOOKING_DATE) AS MONTH, BOOKING_METRIC, OPPORTUNITY_TYPE, SUM(BOOKING_ACV_USD) AS ACV
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKING_LINES.BOOKING_DATE, BOOKING_LINES.BOOKING_METRIC, BOOKING_LINES.OPPORTUNITY_TYPE
  METRICS    BOOKING_LINES.BOOKING_ACV_USD
  WHERE      BOOKING_LINES.BOOKING_DATE BETWEEN '<start>' AND '<end>'
) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
```

```sql
-- Recurring bookings behind a month: by account, product and opportunity
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS DIM_ACCOUNT.ACCOUNT_NAME, BOOKING_LINES.OPPORTUNITY_ID, BOOKING_LINES.PRODUCT, BOOKING_LINES.OPPORTUNITY_TYPE
  METRICS    BOOKING_LINES.BOOKING_ACV_USD
  WHERE      BOOKING_LINES.BOOKING_METRIC = 'Recurring Services'
         AND BOOKING_LINES.BOOKING_DATE BETWEEN '<month start>' AND '<month end>'
) ORDER BY BOOKING_ACV_USD DESC LIMIT 25;
```

```sql
-- Pipeline cards today, unweighted, against a year earlier (point-in-time: _MTD / _PYMTD; never the _QTD / _YTD / _LTM columns)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  METRICS PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_PYMTD,
          PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_MTD, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_PYMTD,
          PIPELINE_OVERVIEW.AVG_OPPORTUNITY_VALUE_ACV_MTD, PIPELINE_OVERVIEW.AVG_OPPORTUNITY_VALUE_ACV_PYMTD
  WHERE   PIPELINE_OVERVIEW.IS_LATEST = TRUE
);
-- pipeline created for a window: OPPORTUNITIES.PIPELINE_CREATED_ACV by month of PIPELINE_CREATION_DATE, summed over the window's months
```

```sql
-- Open pipeline trend at each month-end
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS PIPELINE_OVERVIEW.AS_OF_DATE
  METRICS    PIPELINE_OVERVIEW.OPEN_PIPELINE_ACV_ASAT, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_ASAT
  WHERE      PIPELINE_OVERVIEW.AS_OF_DATE >= '<start>'
) ORDER BY AS_OF_DATE;
```

```sql
-- Open pipeline by stage and fiscal close quarter (today)
SELECT STAGE_ORDER, STAGE_NAME,
       'FY' || (YEAR(CLOSE_DATE) + IFF(MONTH(CLOSE_DATE) >= 2, 1, 0)) || '-Q' || (FLOOR(MOD(MONTH(CLOSE_DATE) + 10, 12) / 3) + 1) AS FISCAL_CLOSE_QUARTER,
       SUM(OPEN_PIPELINE_ACV) AS OPEN_ACV, SUM(OPEN_OPPORTUNITIES) AS DEALS
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS OPPORTUNITIES.STAGE_ORDER, OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.CLOSE_DATE
  METRICS    OPPORTUNITIES.OPEN_PIPELINE_ACV, OPPORTUNITIES.OPEN_OPPORTUNITIES
  WHERE      OPPORTUNITIES.IS_ACTIVE_PIPELINE = TRUE
) GROUP BY 1, 2, 3 ORDER BY 1, 3;
```

```sql
-- Win rate and won / lost ACV by fiscal quarter of close and source
SELECT 'FY' || (YEAR(CLOSE_DATE) + IFF(MONTH(CLOSE_DATE) >= 2, 1, 0)) || '-Q' || (FLOOR(MOD(MONTH(CLOSE_DATE) + 10, 12) / 3) + 1) AS FISCAL_QUARTER,
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
FROM (SELECT DISTINCT OPPORTUNITY_ID, STAGE_RUN_NO, STAGE_NAME, DATEDIFF('day', STAGE_START_DATE, STAGE_END_DATE) AS DAYS
      FROM SEMANTIC_VIEW(
        PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
        DIMENSIONS OPPORTUNITY_STAGE_HISTORY.OPPORTUNITY_ID, OPPORTUNITY_STAGE_HISTORY.STAGE_RUN_NO, OPPORTUNITY_STAGE_HISTORY.STAGE_NAME,
                   OPPORTUNITY_STAGE_HISTORY.STATUS, OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE, OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE
        WHERE OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE IS NOT NULL AND OPPORTUNITY_STAGE_HISTORY.STATUS = 'Open'
          AND OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE >= '<start>'))
WHERE DAYS >= 1 GROUP BY 1 ORDER BY 1;
```

The fiscal quarter expression maps February to Q1 and January to Q4 of the fiscal year that ends in that January.

## 6. Answer ladders

| Question | Ladder (top to bottom) | Source |
|---|---|---|
| How are bookings tracking vs last year? | 1. Total bookings for the fiscal window vs the same months last year. 2. Recurring vs non-recurring. 3. New sales vs seat expansion. 4. By product (recurring) and subsidiary (non-recurring) | `BOOKINGS_OVERVIEW` `_MTD`, `BOOKING_LINES` |
| Why did bookings go up? | 1. Confirm the move: window vs prior period. 2. New sales vs seat expansion vs non-recurring. 3. By product, by subsidiary: contribution and share. 4. By account and deal. 5. One-off or repeat | `BOOKING_LINES` |
| Where is new business coming from? | 1. New sales by month. 2. By product. 3. By account. 4. Deals and average deal value | `BOOKING_LINES` (`OPPORTUNITY_TYPE = 'New Sales'`) |
| How healthy is the pipeline? | 1. Open pipeline, open count and average value vs a year earlier. 2. By stage (`STAGE_ORDER`). 3. By fiscal close quarter. 4. By product, source and region | `PIPELINE_OVERVIEW`, `OPPORTUNITIES` |
| Do we have enough pipeline? | No target is in the view, so no coverage ratio. Give open pipeline closing in each fiscal quarter, late-stage share, and the straight-line range at the last-twelve-month win rate; say a target would be needed for coverage | `OPPORTUNITIES` |
| Which open pipeline looks at risk? | 1. Total open pipeline. 2. Value past its expected close date, pushed out, or longer than typical in its stage (proxy, labelled). 3. High-value deals ($100k or more) among them | `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY` |
| Win rate and why we lose? | 1. Win rate for the `CLOSE_DATE` period, by count and by value. 2. By product, source, region, owner. 3. Lost ACV by stage lost at (**no loss reason in the view**) | `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY` |
| Where are deals getting stuck? | 1. Median and P90 days per stage from completed runs. 2. By stage and product. 3. By owner. 4. Longest-running open deals | `OPPORTUNITY_STAGE_HISTORY` |
| Which deals might close this quarter? | 1. Open pipeline with a close date in the current fiscal quarter. 2. By stage (late stage = 04 - PROPOSE onwards). 3. By owner. 4. The deals | `OPPORTUNITIES` |
| Which customers are stuck, and what is at stake? | 1. Median completed stay per stage. 2. Open deals whose current stage is longer than 2× the median of other accounts' stays. 3. Their ACV | `OPPORTUNITY_STAGE_HISTORY`, `OPPORTUNITIES` |
| How did one deal progress? | 1. Opportunity summary. 2. Stage runs in order (`STAGE_RUN_NO`). 3. Owner, close date and ACV at the end of each run | `OPPORTUNITY_STAGE_HISTORY` |

## 7. Dashboard coverage

| Page | Visual | Status |
|---|---|---|
| 1. Bookings | Cards: Total, Recurring, Non-recurring with prior year; monthly trend; product and subsidiary filters | Yes. QTD, YTD and LTM summed fiscally from monthly `_MTD`; new sales vs seat expansion from lines (the ARR (New) / ARR (Upsell) rows are 0) |
| | Average deal value | Derived (`BOOKING_LINES`) |
| 2. Pipeline Overview | Cards with prior year; pipeline value trend; created trend; open pipeline by stage and close quarter | Yes, unweighted ACV, fiscal windows. No target or coverage (none in the view) |
| 3. Opportunities Details | Opportunity summary (dates, stage, source, product, type, region, owner, value); stage history | Yes (stage runs; milestone dates). Loss reason: **not available** |

The Power BI pages show the trend and the tables. The GTM dashboard (`dashboards.md`) reads the same tables and adds the diagnosis: what moved bookings, whether it repeats, what the pipeline could deliver, and what to decide.

## 8. Cautions

- **Windows from `_MTD` only.** Build bookings QTD, YTD and LTM from monthly `_MTD` over the fiscal months and read open pipeline from `_MTD` / `_PYMTD` at one date; never use or roll up a mart's `_QTD` / `_YTD` / `_LTM` (computed for one month's keys, so incomplete). `DIM_DATE` quarter and year (and the bookings `_QTD` / `_YTD`) are calendar: label every period with its fiscal year (FY2027).
- **The latest month may not be closed.** `BOOKINGS_OVERVIEW` publishes a month-end as soon as the month ends; its non-recurring revenue arrives when NetSuite closes the month (on 18 Nov 2026, October showed $417). Use the latest month NetSuite has closed.
- **ARR (New) and ARR (Upsell) are 0.** Split recurring bookings by `BOOKING_LINES.OPPORTUNITY_TYPE`.
- **Recurring and non-recurring carry different dimensions.** Account, product and opportunity exist only on recurring lines; subsidiary only on non-recurring lines. A product or account cut covers recurring bookings only; say so.
- **Unweighted only.** Don't use `WEIGHTED_PIPELINE_VALUE_*` or `STAGE_PROBABILITY` (the probabilities are not maintained).
- **No targets.** There is no pipeline or bookings target in the view: never state coverage or attainment.
- **Distinct counts.** Count metrics are distinct opportunities; never sum counts across product or stage rows of the same deal.
- **The pipeline filter is built in.** Open metrics need `IS_ACTIVE_PIPELINE` (a pipeline stage and ACV above 0). Renewal opportunities are not in the view.
- **Cards vs trends.** Card metrics return one value per as-at date: filter `IS_LATEST = TRUE` (bookings: last month-end; pipeline: today). Trend metrics (`*_ASAT`) need one date per bar.
- **Closed periods use `CLOSE_DATE`; created periods use `PIPELINE_CREATION_DATE`** (the date the deal reached 03 - EVALUATE).
- **Stage-history values are not additive across runs.** Use `IS_CURRENT_STAGE = TRUE` for totals.
- **Days in stage is computed, not stored.** Use completed runs for typical stays; the current run is still open.
- **Owner names aren't unique.** Slice on `USER_KEY` (`OWNER_KEY`) when ranking reps.
