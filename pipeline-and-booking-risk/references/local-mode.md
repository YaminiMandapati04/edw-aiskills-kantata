# Local test mode

For testing when the Snowflake connection isn't available: the user uploads an Excel workbook whose sheets mirror the GTM view's logical tables, and the skill runs the same analysis over it with plain SQL. **Local results are test output, not governed answers.** Use this mode only when the user supplies a workbook or asks for a local test; if a live connector exists, use it.

## Contents
1. Workflow
2. Workbook layout
3. What differs from governed mode
4. Metric formulas in SQL
5. Verified example queries
6. Labelling rules

---

## 1. Workflow

All scripts are in `scripts/` and need only the packages in `requirements.txt` (SQLite is part of Python).

```bash
python scripts/local_data.py check  uploads/book.xlsx [more.xlsx]          # whether the workbook supports the GTM view
python scripts/local_data.py load   uploads/book.xlsx --db work/local.db   # one table per sheet
python scripts/local_data.py schema --db work/local.db                     # tables, columns, row counts
python scripts/local_data.py query  --db work/local.db --file work/q.sql   # read-only, guard-checked, row-capped
```

1. Run `check`. If the view comes back INCOMPLETE, say what's missing and answer only what the loaded sheets allow. Don't invent columns or fill gaps.
2. `load`, then `schema` to see the real column names. If the user's headers differ from §2, ask once for the mapping or rename in SQL (`SELECT col AS EXPECTED_NAME`); never guess a meaning.
3. Read `view-gtm.md` for **hierarchy, rules and cautions**: they apply in local mode too. Ignore its `SEMANTIC_VIEW(...)` templates and use §4–5 here.
4. Query, answer, and build outputs exactly as in `SKILL.md` B3–B4 (answers and bundle outputs) or A2 (the dashboard), with the labelling in §6.
5. Probe first: `SELECT DISTINCT` the key members (`STATUS`, `STAGE_NAME`, `BOOKING_METRIC`, `OPPORTUNITY_TYPE`) and the latest month with data, as in `semantic-views.md` §9.

For a first run without a client file, generate a synthetic workbook (invented data, internally consistent, with planted anomalies to find):

```bash
python scripts/make_sample_data.py            # writes assets/sample-data/gtm_sample.xlsx
```

The shipped sample is ready to use: `assets/sample-data/gtm_sample.xlsx`. Latest closed month in it is October 2026. **Never present sample figures as real.**

## 2. Workbook layout

One sheet per table, **row 1 = headers**, sheet and header names as below (case and spaces are normalised to `UPPER_SNAKE`). Sheets named `README…` or starting `_` are ignored. Extra sheets and columns are fine. `check` reports what's missing.

| Required sheets (columns) | Optional sheets (columns) |
|---|---|
| `BOOKING_LINES` (`BOOKING_DATE`, `BOOKING_METRIC`, `BOOKING_SOURCE`, `OPPORTUNITY_TYPE`, `PRODUCT`, `OPPORTUNITY_ID`, `ACCOUNT_NAME`, `SUBSIDIARY_NAME`, `BOOKING_ACV_USD`), `OPPORTUNITIES` (`OPPORTUNITY_ID`, `OPPORTUNITY_NAME`, `ACCOUNT_NAME`, `OWNER_NAME`, `PRODUCT`, `OPPORTUNITY_SOURCE`, `OPPORTUNITY_TYPE`, `STATUS`, `STAGE_NAME`, `STAGE_ORDER`, `CLOSE_DATE`, `CREATED_DATE`, `PIPELINE_CREATION_DATE`, `ACV_USD`, optional `DATA_REFRESHED_AT`, `REGION`) | `OPPORTUNITY_STAGE_HISTORY` (`OPPORTUNITY_ID`, `STAGE_RUN_NO`, `STAGE_NAME`, `STATUS`, `STAGE_START_DATE`, `STAGE_END_DATE`, `CLOSE_DATE` at the end of the run, `IS_CURRENT_STAGE`, `OWNER_NAME`) |

Booking lines follow the view: recurring lines have `BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)')`, an `OPPORTUNITY_TYPE` (New Customer or Upgrade / Renewal / Downgrade), an account, product and opportunity, and no subsidiary; non-recurring lines have `BOOKING_METRIC = 'Non-Recurring'`, a subsidiary and nothing else. There is no target sheet: the view holds no pipeline target.

Dates load as ISO text (`YYYY-MM-DD`), TRUE/FALSE as 1/0. Compare dates with string comparison on ISO text.

A real export from the warehouse can be used as the workbook as long as it follows this layout. Filter booking lines and opportunities to the periods needed before exporting.

## 3. What differs from governed mode

| Governed (Snowflake) | Local (workbook) |
|---|---|
| `SEMANTIC_VIEW(...)` applies metric logic | Plain SQL; you apply the formulas in §4 |
| Pre-aggregated marts (`BOOKINGS_OVERVIEW`, `PIPELINE_OVERVIEW`) with window twins | Not in the workbook: windows are computed from lines (`BOOKING_LINES`, `OPPORTUNITIES`) with date filters, on the fiscal year (1 January to 31 December) |
| Built-in open filter and weighting on opportunity metrics (`NOT IS_CLOSED`, `WEIGHTED_OPEN_PIPELINE_ACV`) | You apply it: `STATUS = 'Open'`, and weighted ACV = `ACV_USD * PROBABILITY / 100` |
| Dimension joins defined in the view | Names are already on the line sheets (`ACCOUNT_NAME`, `OWNER_NAME`, `PRODUCT`) |
| Currency: USD (`*_USD`) | Whatever the workbook holds; state it from the README or ask |
| Access control, row-level security | None. Don't upload client data to a place the user wouldn't normally share it |

The grain rules still apply: one window per question, weighted pipeline at one date, bookings and created pipeline over a range, never summing ratios or distinct counts across groups. Pipeline values are weighted (ACV × probability).

## 4. Metric formulas in SQL

| Governed metric | Local SQL |
|---|---|
| `TOTAL_BOOKINGS_<w>` and parts | `SUM(BOOKING_ACV_USD)` on `BOOKING_LINES` over the window's `BOOKING_DATE` range (QTD and YTD on the fiscal year: YTD from 1 January); new ARR = `BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)') AND OPPORTUNITY_TYPE = 'New Customer'`, upsell ARR = `… AND OPPORTUNITY_TYPE = 'Upgrade / Renewal / Downgrade'`, non-recurring = `'Non-Recurring'`; recurring = new ARR + upsell ARR; total = all three |
| Average deal value | recurring `SUM(BOOKING_ACV_USD)` ÷ `COUNT(DISTINCT OPPORTUNITY_ID)` over the window |
| `OPEN_PIPELINE_ACV`, `OPEN_OPPORTUNITIES` | `SUM(ACV_USD)`, `COUNT(DISTINCT OPPORTUNITY_ID)` where `STATUS = 'Open' AND STAGE_ORDER BETWEEN 2 AND 7 AND ACV_USD > 0` |
| `PIPELINE_CREATED_ACV`, `OPPORTUNITIES_CREATED` | `SUM(ACV_USD)`, `COUNT(DISTINCT OPPORTUNITY_ID)` over a `PIPELINE_CREATION_DATE` range |
| `WIN_RATE` | won ÷ (won + lost) over a `CLOSE_DATE` range, from `STATUS` |
| `WON_ACV_USD`, `LOST_ACV_USD` | `SUM(ACV_USD)` where `STATUS = 'Closed Won'` / `'Closed Lost'` over a `CLOSE_DATE` range |
| Days in a stage run | `julianday(STAGE_END_DATE) - julianday(STAGE_START_DATE)` on completed runs of `OPPORTUNITY_STAGE_HISTORY` |

## 5. Verified example queries

These run on the shipped sample workbook (SQLite dialect). Replace literals with real members after probing.

```sql
-- Bookings fiscal YTD (FY2026: Jan-Oct 2026) vs the same months of FY2025, by measure
SELECT BOOKING_METRIC, COALESCE(OPPORTUNITY_TYPE, '') AS type,
  ROUND(SUM(CASE WHEN BOOKING_DATE BETWEEN '2026-01-01' AND '2026-10-31' THEN BOOKING_ACV_USD END),0) AS fytd,
  ROUND(SUM(CASE WHEN BOOKING_DATE BETWEEN '2025-01-01' AND '2025-10-31' THEN BOOKING_ACV_USD END),0) AS py_fytd
FROM BOOKING_LINES GROUP BY 1, 2 ORDER BY 1, 2;
```

```sql
-- Weighted pipeline by stage (ACV x probability; Closed Lost is not open)
SELECT STAGE_ORDER, STAGE_NAME, COUNT(DISTINCT OPPORTUNITY_ID) AS opps, ROUND(SUM(ACV_USD * PROBABILITY / 100.0),0) AS weighted_acv,
       ROUND(SUM(ACV_USD),0) AS unweighted_acv
FROM OPPORTUNITIES WHERE STATUS = 'Open' AND ACV_USD <> 0 GROUP BY 1, 2 ORDER BY 1;
```

```sql
-- Open deals longest in their current stage, age measured against the data's own refresh date, not today's clock
SELECT h.OPPORTUNITY_NAME, h.STAGE_NAME, h.STAGE_START_DATE,
       CAST(julianday((SELECT MAX(DATA_REFRESHED_AT) FROM OPPORTUNITIES)) - julianday(h.STAGE_START_DATE) AS INTEGER) AS days_in_stage,
       ROUND(h.ACV_USD,0) AS acv
FROM OPPORTUNITY_STAGE_HISTORY h WHERE h.IS_CURRENT_STAGE = 1 AND h.STATUS = 'Open' ORDER BY days_in_stage DESC LIMIT 10;
```

```sql
-- Weighted pipeline by fiscal close quarter (fiscal year = calendar year: Q1 Jan-Mar ... Q4 Oct-Dec); no target, no ratio
SELECT 'FY' || strftime('%Y', CLOSE_DATE)
       || '-Q' || ((CAST(strftime('%m', CLOSE_DATE) AS INTEGER) - 1) / 3 + 1) AS fiscal_quarter,
       COUNT(DISTINCT OPPORTUNITY_ID) AS opps, ROUND(SUM(ACV_USD * PROBABILITY / 100.0),0) AS weighted_pipeline
FROM OPPORTUNITIES WHERE STATUS = 'Open' AND ACV_USD <> 0 GROUP BY 1 ORDER BY 1;
```

```sql
-- Win rate for fiscal year to date (FY2026)
SELECT ROUND(1.0 * SUM(STATUS = 'Closed Won') / NULLIF(SUM(STATUS IN ('Closed Won','Closed Lost')), 0), 4) AS win_rate,
       SUM(STATUS = 'Closed Won') AS won, SUM(STATUS = 'Closed Lost') AS lost
FROM OPPORTUNITIES
WHERE CLOSE_DATE BETWEEN '2026-01-01' AND '2026-10-31' AND STATUS IN ('Closed Won','Closed Lost');
```

## 6. Labelling rules

- Set `meta.data_mode` to `"local"` in the result bundle. Every output then carries a "LOCAL TEST DATA" banner, and the bundle **cannot** label a table `governed`: use `derived` (or `scenario`). `bundle.py` enforces this.
- In `meta.sources`, name the workbook file(s) and sheets, not a view. Do not write `PROD_DB.SEMANTIC_VIEWS...` for local data.
- The chat answer opens or closes with one line: "Local test data from <file>, not governed view output."
- Don't suggest the numbers match the governed view. They match only if the workbook was exported from it and the currency convention is the same.
- The guardrails apply unchanged: read-only, no raw dumps, row caps, honest gaps, no fabrication, Fact / Derived / Scenario labels.
