# The GTM diagnostic dashboard

> **Status: live on governed data, with the AI review.**
> - **Live:** `scripts/build_gtm_dashboard.py --extracts work/gtm-live` builds from the governed extracts in §2. The loader is `scripts/gtm/live.py`; the engine is `scripts/gtm/engine.py`, with tie-outs to both KPI marts; the renderer is `artifacts/gtm_analytics/`.
> - **Local:** `scripts/build_sample_dashboard.py` builds the same page from a workbook, with the LOCAL TEST DATA banner.
> - **AI review:** Claude writes the review for the opening view (`references/diagnosis.md`), the gate admits it, and the page says "AI reviewed". `test_gtm_pipeline.py` is not yet written.
> - **Recurring:** the page is the skill's main deliverable, rebuilt every month once the month closes (§7). The run asks no questions and fails closed.
> - A request for the GTM review or dashboard is never answered with the bundle-path review pack.

One deliverable: a single offline HTML file with three tabs (Pipeline, Bookings, Outlook) that tells the reader whether bookings growth is real and repeatable, what drives it, what the pipeline could deliver in the quarters ahead, and what management must decide. The Power BI GTM pages already show the trend and the tables; this dashboard reads the same tables and adds the diagnosis. Charts and tables are the evidence a reader drills into, not the headline.

Layout (regions in `dashboard-contract.md` §4): each tab opens with 3 to 5 insight bullets, each a bold conclusion, the observation, then what it means. They cover the bookings lead, quality and concentration, pipeline risk and conversion; reviewed conclusions are added when a diagnosis is admitted. Then a KPI strip in order of build-up, "what moved bookings" and the decisions for management. Every figure opens a drawer with the detail as charts and short bullets. A collapsible glossary table at the foot defines each tag. Negatives print in brackets; the wording is favourable / unfavourable / in line, never "adverse"; `mn` not `mm`.

**Yes Energy ground rules** (they hold on every page):
- **Fiscal year 1 January to 31 December**, named by that calendar year: January to December 2026 is FY2026. Fiscal quarters are Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec, labelled `FY2026-Q3`. Quarter to date, year to date, close quarters and the rest-of-year scenario are all fiscal.
- **Recurring bookings** are Salesforce closed-won opportunity lines (ARR (New) and ARR (Upsell)) on the close date, split into *New ARR* and *Upsell ARR* by `BOOKING_LINES.OPPORTUNITY_TYPE`. **Non-recurring bookings** are NetSuite non-recurring revenue from the income statement, by subsidiary, on the period end date.
- **Pipeline values are weighted (ACV × probability).** The view holds **no pipeline or bookings target**, so there is no coverage ratio, floor or "created vs target" anywhere.

## Contents
1. When to build it
2. The queries
3. The pipeline
4. Options
5. Hand-over
6. What it does not do
7. The recurring run

---

## 1. When to build it

Build it:
- **On schedule.** The recurring monthly run (§7), or any request to "run this month's GTM dashboard".
- **On request.** The GTM review, the GTM or bookings dashboard, "how is go-to-market doing and why", or a management readout on bookings and pipeline.

A one-off question ("why did bookings go up?") is answered in chat (`SKILL.md` Part B); offer the dashboard in one line.

Scope is all subsidiaries and products unless the request names one product (a Yes Energy product). Then filter the extracts to it and pass `--scope-label`. Don't ask about scope, and never choose a subset yourself.

## 2. The queries

Read `view-gtm.md`, then fix the dates:
- **`<M1>`, the analysis month-end:** the latest month-end NetSuite has closed. Probe `BOOKINGS_OVERVIEW` at `IS_LATEST = TRUE` with `TOTAL_BOOKINGS_MTD` and `NON_RECURRING_BOOKINGS_MTD`. The mart publishes a month-end as soon as the calendar month ends, before NetSuite closes it: on 23 Nov 2026 the latest was 31 Oct with $208k of non-recurring revenue (June to September ran $265k to $749k a month). When the latest month's non-recurring bookings are near zero, `<M1>` is the month-end before. The build applies the same rule (QC `as_of_complete`).
- **`<M0>`:** the first day of the month 23 months before `<M1>`.
- **`<TODAY>`:** the pipeline as-at (the `PIPELINE_OVERVIEW` row with `IS_LATEST = TRUE`).

Run the statements below through `sql_guard.py`. Save each sql-exec result as returned, as JSON, under `work/gtm-live/` with the name shown: write it with the Write tool from the result in the conversation (the JSON object with `result_set`). Every statement reads `FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS …)`; in the table, `…` stands for that opening. Keep the column aliases exactly as written: the loader reads them by name.

| File | Statement |
|---|---|
| `gtm-lines-<n>.json` | `SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS BOOKING_LINES.BOOKING_DATE, BOOKING_LINES.BOOKING_METRIC, BOOKING_LINES.OPPORTUNITY_TYPE, BOOKING_LINES.PRODUCT, BOOKING_LINES.OPPORTUNITY_ID, DIM_SUBSIDIARY.SUBSIDIARY_NAME, DIM_ACCOUNT.ACCOUNT_NAME METRICS BOOKING_LINES.BOOKING_ACV_USD WHERE BOOKING_LINES.BOOKING_DATE BETWEEN '<chunk start>' AND '<chunk end>')`. `BOOKING_METRIC` is `ARR (New)`, `ARR (Upsell)` or `Non-Recurring`. One chunk per month, 24 for 24 months (about 250 rows a month on 23 Nov 2026: 763 lines in Jul–Sep 2026); split a heavy month (quarter-end) in two halves |
| `gtm-open-<n>.json` | `SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.OPPORTUNITY_ID, OPPORTUNITIES.OPPORTUNITY_NAME, OPPORTUNITIES.ACCOUNT_NAME, OPPORTUNITIES.OWNER_NAME, OPPORTUNITIES.PRODUCT, OPPORTUNITIES.OPPORTUNITY_SOURCE, OPPORTUNITIES.OPPORTUNITY_TYPE, OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.STAGE_ORDER, OPPORTUNITIES.CLOSE_DATE, OPPORTUNITIES.CREATED_DATE, OPPORTUNITIES.PIPELINE_CREATION_DATE, OPPORTUNITIES.DATA_REFRESHED_AT METRICS OPPORTUNITIES.OPEN_PIPELINE_ACV, OPPORTUNITIES.WEIGHTED_OPEN_PIPELINE_ACV WHERE NOT OPPORTUNITIES.IS_CLOSED)`. **Weighted:** the engine uses `WEIGHTED_OPEN_PIPELINE_ACV` (line ACV × `PROBABILITY` ÷ 100); `OPEN_PIPELINE_ACV` is kept only as unweighted context and to drop zero-ACV rows. Filter on `NOT IS_CLOSED` (the governed open metrics' own filter), not `IS_ACTIVE_PIPELINE`: only that ties to the `PIPELINE_OVERVIEW` card ($14.26mn weighted, 1,599 deals on 23 Nov 2026; `IS_ACTIVE_PIPELINE` gives $14.97mn and 357 deals). `PIPELINE_CREATION_DATE` equals `CREATED_DATE`. One row per open deal and product (about 1,600 to 2,500 rows): chunk by close month so each result stays under 250 rows |
| `gtm-conv-source.json` | `SELECT DATE_TRUNC('month', CLOSE_DATE) AS CLOSE_MONTH, OPPORTUNITY_SOURCE, SUM(WON_ACV_USD) AS WON_ACV_USD, SUM(LOST_ACV_USD) AS LOST_ACV_USD, SUM(WON_OPPORTUNITIES) AS WON_OPPORTUNITIES, SUM(LOST_OPPORTUNITIES) AS LOST_OPPORTUNITIES FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.CLOSE_DATE, OPPORTUNITIES.OPPORTUNITY_SOURCE METRICS OPPORTUNITIES.WON_ACV_USD, OPPORTUNITIES.LOST_ACV_USD, OPPORTUNITIES.WON_OPPORTUNITIES, OPPORTUNITIES.LOST_OPPORTUNITIES WHERE OPPORTUNITIES.CLOSE_DATE BETWEEN '<M0>' AND '<TODAY>' AND OPPORTUNITIES.STATUS <> 'Open') GROUP BY 1, 2` |
| `gtm-conv-product.json` | the same statement with `OPPORTUNITIES.PRODUCT` (and `PRODUCT` in the SELECT and GROUP BY) in place of the source |
| `gtm-created.json` | `SELECT DATE_TRUNC('month', PIPELINE_CREATION_DATE) AS CREATED_MONTH, SUM(PIPELINE_CREATED_ACV) AS PIPELINE_CREATED_ACV, SUM(OPPORTUNITIES_CREATED) AS OPPORTUNITIES_CREATED FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.PIPELINE_CREATION_DATE METRICS OPPORTUNITIES.PIPELINE_CREATED_ACV, OPPORTUNITIES.OPPORTUNITIES_CREATED WHERE OPPORTUNITIES.PIPELINE_CREATION_DATE BETWEEN '<M0>' AND '<TODAY>') GROUP BY 1`. Pipeline created is unweighted (the view has no weighted twin) |
| `gtm-stage-current-<n>.json` | `WITH h AS (SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITY_STAGE_HISTORY.OPPORTUNITY_ID, OPPORTUNITY_STAGE_HISTORY.STAGE_RUN_NO, OPPORTUNITY_STAGE_HISTORY.STAGE_NAME, OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE, OPPORTUNITY_STAGE_HISTORY.CLOSE_DATE, OPPORTUNITY_STAGE_HISTORY.STATUS, OPPORTUNITY_STAGE_HISTORY.IS_CURRENT_STAGE)) SELECT OPPORTUNITY_ID, STAGE_RUN_NO, STAGE_NAME, STAGE_START_DATE, CLOSE_DATE, IS_CURRENT_STAGE FROM h QUALIFY MAX(IFF(IS_CURRENT_STAGE AND STATUS = 'Open', 1, 0)) OVER (PARTITION BY OPPORTUNITY_ID) = 1`: every stage run of the open opportunities. The current run gives the stage start; the close date at the end of each run gives the pushes (about 1,100 rows): four chunks, adding `AND MOD(ABS(HASH(OPPORTUNITY_ID)), 4) = <0..3>` after the `QUALIFY` |
| `gtm-stage-medians.json` (optional) | One statement; the medians are computed in Snowflake because stage history is too large to extract. `WITH runs AS (SELECT DISTINCT OPPORTUNITY_ID, STAGE_RUN_NO, STAGE_NAME, DATEDIFF('day', STAGE_START_DATE, STAGE_END_DATE) AS DAYS FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITY_STAGE_HISTORY.OPPORTUNITY_ID, OPPORTUNITY_STAGE_HISTORY.STAGE_RUN_NO, OPPORTUNITY_STAGE_HISTORY.STAGE_NAME, OPPORTUNITY_STAGE_HISTORY.STATUS, OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE, OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE WHERE OPPORTUNITY_STAGE_HISTORY.STAGE_END_DATE IS NOT NULL AND OPPORTUNITY_STAGE_HISTORY.STAGE_START_DATE >= '<M0>' AND OPPORTUNITY_STAGE_HISTORY.STATUS = 'Open')), acct AS (SELECT DISTINCT OPPORTUNITY_ID, ACCOUNT_NAME FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.OPPORTUNITY_ID, OPPORTUNITIES.ACCOUNT_NAME)), stays AS (SELECT r.STAGE_NAME, a.ACCOUNT_NAME, r.DAYS FROM runs r LEFT JOIN acct a ON a.OPPORTUNITY_ID = r.OPPORTUNITY_ID WHERE r.DAYS >= 1), open_accts AS (SELECT DISTINCT STAGE_NAME, ACCOUNT_NAME FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.ACCOUNT_NAME WHERE NOT OPPORTUNITIES.IS_CLOSED)) SELECT o.STAGE_NAME, o.ACCOUNT_NAME, MEDIAN(s.DAYS) AS MEDIAN_DAYS, COUNT(s.DAYS) AS STAYS FROM open_accts o JOIN stays s ON s.STAGE_NAME = o.STAGE_NAME AND (s.ACCOUNT_NAME IS NULL OR s.ACCOUNT_NAME <> o.ACCOUNT_NAME) GROUP BY 1, 2 UNION ALL SELECT STAGE_NAME, NULL, MEDIAN(DAYS), COUNT(*) FROM stays GROUP BY 1`. Rows with a blank account are the stage medians; the others are, per stage and account with an open deal, the median of **other** accounts' stays. Without it (and without `gtm-stage-p90`), nothing is flagged stuck |
| `gtm-stage-p90.json` (optional) | `WITH runs AS (` the `runs` above with `STAGE_END_DATE BETWEEN '<M0>' AND '<TODAY>'` in place of the start-date filter `) SELECT STAGE_NAME, PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY DAYS) AS P90_DAYS, PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY DAYS) AS P75_DAYS, AVG(DAYS) AS MEAN_DAYS, COUNT(*) AS RUNS FROM runs WHERE DAYS >= 1 GROUP BY 1`. When supplied, "stuck" is a deal older in its stage than the 90th percentile of completed stays (at least 30 stays), instead of 2× the median |
| `gtm-lost-<n>.json` (optional) | `SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.OPPORTUNITY_ID, OPPORTUNITIES.OPPORTUNITY_NAME, OPPORTUNITIES.ACCOUNT_NAME, OPPORTUNITIES.OWNER_NAME, OPPORTUNITIES.PRODUCT, OPPORTUNITIES.OPPORTUNITY_SOURCE, OPPORTUNITIES.OPPORTUNITY_TYPE, OPPORTUNITIES.CLOSE_DATE METRICS OPPORTUNITIES.LOST_ACV_USD WHERE OPPORTUNITIES.STATUS = 'Closed Lost' AND OPPORTUNITIES.CLOSE_DATE BETWEEN '<chunk start>' AND '<chunk end>')`. About 2,900 deals over 25 months (about 140 characters a row): monthly chunks (about 120 rows each). Without it, the Lost section says "not supplied" |
| `gtm-lost-stage.json` (optional) | `WITH h AS (SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITY_STAGE_HISTORY.OPPORTUNITY_ID, OPPORTUNITY_STAGE_HISTORY.STAGE_RUN_NO, OPPORTUNITY_STAGE_HISTORY.STAGE_NAME, OPPORTUNITY_STAGE_HISTORY.STATUS, OPPORTUNITY_STAGE_HISTORY.IS_CURRENT_STAGE, OPPORTUNITY_STAGE_HISTORY.CLOSE_DATE)) SELECT OPPORTUNITY_ID, STAGE_NAME AS PREVIOUS_STAGE_NAME FROM h WHERE STATUS = 'Open' AND OPPORTUNITY_ID IN (SELECT OPPORTUNITY_ID FROM h WHERE IS_CURRENT_STAGE AND STATUS = 'Closed Lost' AND CLOSE_DATE BETWEEN '<M0>' AND '<TODAY>') QUALIFY ROW_NUMBER() OVER (PARTITION BY OPPORTUNITY_ID ORDER BY STAGE_RUN_NO DESC) = 1`: the last open stage before each loss |
| `gtm-velocity.json` (optional) | `WITH o AS (SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.OPPORTUNITY_ID, OPPORTUNITIES.CREATED_DATE, OPPORTUNITIES.CLOSE_DATE METRICS OPPORTUNITIES.WON_ACV_USD WHERE OPPORTUNITIES.STATUS = 'Closed Won' AND OPPORTUNITIES.CLOSE_DATE BETWEEN '<M0>' AND '<TODAY>')), d AS (SELECT OPPORTUNITY_ID, MIN(CREATED_DATE)::DATE AS C, MAX(CLOSE_DATE) AS X, SUM(WON_ACV_USD) AS ACV FROM o GROUP BY 1) SELECT DATE_TRUNC('month', X) AS CLOSE_MONTH, IFF(ACV >= 100000, 'hv', 'std') AS BAND, COUNT_IF(X > C) AS WON_OPPS, COUNT_IF(X = C) AS SAME_DAY, SUM(IFF(X > C, DATEDIFF('day', C, X), 0)) AS SUM_DAYS, SUM(IFF(X > C, ACV, 0)) AS WON_ACV FROM d WHERE X >= C AND ACV > 0 GROUP BY 1, 2`: days to win per closed-won opportunity (created to close), by close month and size band. Same-day wins carry no sales cycle and are counted apart; credits and zero-ACV wins are left out. Without it the Pipeline tab has no days-to-win card |
| `gtm-conv-size.json` (optional) | `SELECT DATE_TRUNC('month', CLOSE_DATE) AS CLOSE_MONTH, SUM(IFF(WON_ACV_USD > 0, WON_ACV_USD, 0)) AS WON_ACV_POS, SUM(IFF(LOST_ACV_USD > 0, LOST_ACV_USD, 0)) AS LOST_ACV_POS, SUM(IFF(WON_ACV_USD < 0, WON_ACV_USD, 0)) AS WON_NEG_ACV, COUNT_IF(WON_ACV_USD >= 5000) AS WON_5K, COUNT_IF(LOST_ACV_USD >= 5000) AS LOST_5K FROM SEMANTIC_VIEW(… DIMENSIONS OPPORTUNITIES.OPPORTUNITY_ID, OPPORTUNITIES.CLOSE_DATE METRICS OPPORTUNITIES.WON_ACV_USD, OPPORTUNITIES.LOST_ACV_USD WHERE OPPORTUNITIES.STATUS <> 'Open' AND OPPORTUNITIES.CLOSE_DATE BETWEEN '<M0>' AND '<TODAY>') GROUP BY 1`: win rate by value on positive-ACV deals, and by count on deals of $5k or more |
| `gtm-cards.json` | `SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS PIPELINE_OVERVIEW.AS_OF_DATE METRICS PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_PYMTD, PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_PYMTD, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_MTD, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_PYMTD WHERE PIPELINE_OVERVIEW.IS_LATEST = TRUE)`. **Weighted pipeline is the headline:** the loader puts `WEIGHTED_PIPELINE_VALUE_*` in place of the open value (the unweighted value is kept as context) and the average deal value becomes weighted value ÷ open deals. Pipeline is a point-in-time snapshot, read from `_MTD` / `_PYMTD`; the `_QTD` / `_YTD` / `_LTM` columns are not used. Pipeline created comes from the monthly lines (`gtm-created.json`), not the cards. On 23 Nov 2026: weighted $14.26mn (a year earlier $15.17mn), unweighted $29.15mn, 1,599 deals |
| `gtm-cards-snapshot.json` | the same statement `WHERE PIPELINE_OVERVIEW.AS_OF_DATE = '<M1>'`: the headline pipeline at the bookings month-end. Without it QC `as_of_alignment` fails |
| `gtm-snapshot-ecq.json` (recommended) | `SELECT STAGE_NAME, CLOSE_DATE, SUM(WEIGHTED_PIPELINE_ACV_ASAT) AS WEIGHTED_PIPELINE_ACV_ASAT, SUM(OPEN_PIPELINE_ACV_ASAT) AS OPEN_PIPELINE_ACV_ASAT, SUM(OPEN_OPPORTUNITIES_ASAT) AS OPEN_OPPORTUNITIES_ASAT FROM SEMANTIC_VIEW(… DIMENSIONS PIPELINE_OVERVIEW.STAGE_NAME, PIPELINE_OVERVIEW.CLOSE_DATE METRICS PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_ACV_ASAT, PIPELINE_OVERVIEW.OPEN_PIPELINE_ACV_ASAT, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_ASAT WHERE PIPELINE_OVERVIEW.AS_OF_DATE = '<M1>') GROUP BY 1, 2 HAVING SUM(OPEN_OPPORTUNITIES_ASAT) > 0`: the month-end snapshot by stage and close date, weighted. The engine buckets `WEIGHTED_PIPELINE_ACV_ASAT` into past due (close date before `<M1>`), the fiscal (calendar) close quarters and later, and builds the stage × quarter table from it, so both foot to the weighted snapshot card ($14.00mn weighted, 1,571 deals at 31 Oct 2026; QC `close_quarters_foot`). Chunk by close month if it passes 250 rows. Without it, the close quarters, "Closing in" and the scenario read the current-state deal list (as at today) and start at today's fiscal quarter, while the headline pipeline stays at `<M1>`; the page labels each date |
| `gtm-bookings-mart.json` | `SELECT * FROM SEMANTIC_VIEW(… DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE METRICS BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD WHERE BOOKINGS_OVERVIEW.AS_OF_DATE BETWEEN '<M0>' AND '<M1>')`: one row per month-end (tie-out). Only `_MTD` is used: fiscal QTD / YTD / LTM are sums of these months; the mart's `_QTD` / `_YTD` / `_LTM` are never used or rolled up (each is computed for one month's keys, so rolled up it comes out incomplete) |

**Keep every result small enough to come back in the conversation: about 40,000 characters (roughly 250 rows) at most.** A larger result does not appear in the conversation: Claude Code saves it to a file in its own `.claude/…/tool-results/` folder, and copying it from there asks for permission every time (Claude Code protects its own folder as sensitive). The chunk sizes above keep every extract under the limit on Yes Energy's volumes; if a result still comes back as a saved file, re-run that statement in smaller chunks rather than copying the file. The sql-exec tool also caps a result at about 300k characters and reports the full `numRows`: the loader compares the two and refuses a short file. Never edit a file by hand. Booking-line chunks must not overlap and must leave no month out.

Not extracted, because the view does not hold them: pipeline targets and coverage, loss reasons, subscription end date or state. Do not use any mart's `_QTD` / `_YTD` / `_LTM` columns or their PY twins (windows are summed from `_MTD`). `ARR_NEW_*` / `ARR_UPSELL_*` on `BOOKINGS_OVERVIEW` are real (Recurring = ARR (New) + ARR (Upsell)) and may be used at `_MTD` for a tie-out.

**Facts of the live view the build relies on** (checked on PROD_DB, 23 Nov 2026):
- **Bookings.** `BOOKING_LINES` rows are Salesforce recurring lines, one per closed-won opportunity line item (`BOOKING_SOURCE = 'Salesforce'`; `BOOKING_METRIC = 'ARR (New)'` for `OPPORTUNITY_TYPE` New Customer, `'ARR (Upsell)'` for Upgrade, Renewal or Downgrade; a Yes Energy product such as PowerSignals:User License or DataSignals Cloud, an opportunity and an account, no subsidiary) and NetSuite non-recurring lines (`'Non-Recurring'`, `BOOKING_SOURCE = 'NetSuite'`, product One Time Services, one per month and subsidiary (Power Settlements, ENELYTIX) on the period end date, no account or opportunity). The build ties the lines to `TOTAL_BOOKINGS_MTD` every month. A recurring line with an unknown metric or opportunity type stops the build.
- **Measures.** New ARR (`arr_new`, ARR (New)) + Upsell ARR (`arr_upsell`, ARR (Upsell)) = Recurring; Recurring + Non-recurring = Total. Customers, concentration and the average deal value read recurring lines only; a "deal" is one booked opportunity.
- **Conversion.** Win rate counts distinct opportunities through the governed `WON_` and `LOST_` metrics (`STATUS` Closed Won / Closed Lost); unweighted. There is no loss reason in the view.
- **Stages** (`DIM_STAGE_MAPPING.STAGE_ORDER`): Stage 0 (1), Proposed Renewal (2), Qualify (3), Discover (4), Align (5), Validate (6), Invest (7), then Closed Lost (8) / Closed Won (9). Weighted pipeline is every open stage (`NOT IS_CLOSED`); Stage 0 carries 0% probability, so it adds deals but no weighted value. Late stage is Align onwards (`STAGE_ORDER` 5).
- **Fiscal windows from `_MTD`.** The fiscal year is the calendar year (Q1 Jan–Mar … Q4 Oct–Dec). Bookings QTD, YTD and LTM are built from the monthly lines and tied month by month to `TOTAL_BOOKINGS_MTD`; weighted pipeline is read from `_MTD` / `_PYMTD` at one as-at date. No mart `_QTD` / `_YTD` / `_LTM` column is used (computed for one month's keys, so incomplete when rolled up).
- **Pipeline risk** (the first tab; `scripts/gtm/engine.py` constants):
  - *Recurring ACV* = the opportunity line ACV (estimated product ARR change), **weighted** by probability: all of it is recurring; new ARR (New Customer) vs upsell ARR (Upgrade, Renewal, Downgrade) by `OPPORTUNITY_TYPE`.
  - *Not closing* = open and past the expected close date, or the close date pushed out at least once (a later `CLOSE_DATE` at the end of a stage run than at the end of the run before, or today's close date later than the last one recorded).
  - *Stuck* = in the current stage longer than the 90th percentile of completed stays (`gtm-stage-p90`), or 2× the median stay of other accounts' deals (`gtm-stage-medians`). A stay is at least 1 day: same-day pass-throughs would pull every median towards 0. Potential loss = the weighted recurring ACV of those deals.
  - *High value* = open deals of $100k ACV or more.
  - *Lost* = closed-lost deals per window against the same months last quarter; ties to the governed `LOST_ACV_USD` total (QC `lost_tie_out`).

## 3. The pipeline

Scripts are in `scripts/`. Every script fails closed and prints JSON.

| Phase | Command | Produces |
|---|---|---|
| P1 Extract | the statements above | `work/gtm-live/*.json` |
| P2–P3 Analyze and render (built) | `python build_gtm_dashboard.py --extracts work/gtm-live [--expect-as-of YYYY-MM] [--as-of YYYY-MM] [--window …] [--payload-out work/gtm_payload.json]` | `outputs/yes_energy_pipeline_risk_readout.html`. The run refuses a failed bridge, a failed identity, a capped extract, an unknown opportunity type or (with `--expect-as-of`) the wrong month. It prints the headline, the QC checks (mart tie-out, weighted pipeline, lost, as-of alignment) and `since_last` (§7) |
| P4 Diagnose | read `specialists/driver-review.md`, then `specialists/readout.md`; read evidence only through `python gtm_brief.py work/gtm_payload.json brief` (and `refs`, `resolve`); write `work/diagnosis_qtd.json` | the findings and readout for the opening view |
| P5 Admit | `python validate_gtm_diagnosis.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json` | ADMITTED, or the reasons; fix the diagnosis, never the payload |
| P6 Render with the review | `python render_gtm_dashboard.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json --out outputs/yes_energy_pipeline_risk_readout.html` (or `build_gtm_dashboard.py ... --diagnosis work/diagnosis_qtd.json`) | `outputs/yes_energy_pipeline_risk_readout.html`, one self-contained file marked "AI reviewed" |
| P7 Hand over | §5 | |

P2–P3 without `--diagnosis` writes the payload (`--payload-out`) and no page: the opening view needs an admitted review first; `--allow-missing-review` publishes the engine reading alone, marked \"This view not AI reviewed\". `build_gtm_dashboard.py` rebuilds everything from the rows each time. A changed extract, scope, threshold or as-of changes `analysis_hash`, and the gate then refuses the old review as stale: rerun P4 to P6.

Local test mode (a GTM workbook laid out as in `local-mode.md`, no connector): `python build_sample_dashboard.py [--workbook path/gtm_sample.xlsx] [--out path]`. Windows are computed from the line sheets, the page carries the LOCAL TEST DATA banner and QC marks the mode. Pass `--out`: the default writes to the repository's `docs/` folder.

## 4. Options

Options of `build_gtm_dashboard.py`:

| Option | Use |
|---|---|
| `--extracts <folder>` | the saved §2 results (required) |
| `--expect-as-of YYYY-MM` | the month a recurring run is for; refuses, with no file, when the extracts close on another month (§7) |
| `--previous auto\|none\|<page>` | the earlier page to compare with (default `auto`: the previous month's page, `outputs/previous/yes_energy_pipeline_risk_readout.html`, or the page at `--out` when it is for an earlier month) |
| `--as-of YYYY-MM` | the analysis month (default: the latest month in the booking lines that NetSuite has closed) |
| `--window MTD\|QTD\|YTD\|LTM` | the lens the page opens on (default fiscal Quarter to date vs Prior quarter; fiscal Year to date has no prior-quarter lens, so a requested YTD opens on Quarter to date) |
| `--scope-label "<product>"` | the product the extracts were filtered to; default is all products and subsidiaries |
| `--out`, `--payload-out`, `--title`, `--source` | output paths and page text |

Materiality is fixed by rule (1% of last-twelve-month bookings a month, scaled to the window; management 5×, executive 10×) and disclosed on the page. There is no coverage floor: the view holds no target.

## 5. Hand-over

- Hand over the **single `.html` file** and its path. Do not zip or split it; it opens in any browser and works offline. The page embeds the whole payload and stays well under the 16 MB Artifact limit (about 0.3 MB; every deal and customer list is capped); the build's JSON line gives `bytes`, and a page over the limit is refused with no file written.
- Say the scope, the as-of month and its fiscal quarter (for example "September 2026, FY2026-Q3"), the lens it opens on, and whether the AI review was admitted ("AI reviewed", or "not AI reviewed" with the reason). Say the QC status and the caveats that matter (mart-to-lines tie-out, an analysis month stepped back because NetSuite had not closed, data refresh lag).
- Quote figures from the build's JSON line or the payload (`--payload-out`), never from the page, and never claim to have viewed it. Lead with the headline, then the two or three decisions, then "Since last month" on a recurring run (§7).
- State the limits once: owners are suggested, dates are rule-generated, the next-quarter figure is a mechanical scenario with forecast credit 0, no business cause is verified, "stalled" deals are a stage-age proxy (the view has no activity data), and there is no target or coverage (the view holds none).

## 6. What it does not do

- It does not go through the result bundle, `bundle.py` or `verify_outputs.py`; its integrity comes from the payload invariants, the diagnosis gate and the render-stage checks.
- No bookings plan, budget or pipeline target (none exists), so no coverage ratio; no weighted pipeline; no invoice detail; no renewal pipeline or renewal win rate (renewals are not in the view); no loss reasons; no activity or next-step data; no ARR, revenue or retention (other skills); no management forecast.
- Do not edit the files under `artifacts/gtm_analytics/` for one request: the renderer is shared. Change it only to improve the dashboard for everyone, bump `VERSION`, and rebuild the sample page (`build_sample_dashboard.py --out <scratch path>`) to check it.

## 7. The recurring run

The dashboard is rebuilt every month, after the month closes in NetSuite. A run may be unattended (a scheduled routine), so it asks no questions. It either writes this month's page or stops with a one-line reason and writes nothing.

**When.** The bookings mart publishes a month-end as soon as the calendar month ends, but its non-recurring revenue is complete only once NetSuite closes the month (Finance's latest closed month). Schedule the run after the NetSuite close, about the third week of the month. `<RUN>` is the month the run is for: the previous calendar month. Running early is harmless: the run stops at step 1 and the next run picks the month up.

**Steps**
1. **The month has closed.** Probe `SELECT * FROM SEMANTIC_VIEW(PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE METRICS BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD, BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD WHERE BOOKINGS_OVERVIEW.AS_OF_DATE >= '<RUN month-start minus 6 months>')`. If `<RUN>`'s month-end is missing, or its non-recurring bookings are below a tenth of the usual month (the median of the six before), stop: "`<RUN>` hasn't closed in NetSuite yet (non-recurring <amount>); no page built".
2. **Extract.** Run the §2 statements for `<M1>` = that month-end into a fresh `work/gtm-live/` (clear the old files first, so last month's extracts can't mix in). Use all products and subsidiaries; split capped results as §2 says.
3. **Build.** `python scripts/build_gtm_dashboard.py --extracts work/gtm-live --expect-as-of <RUN>`. The page goes to `outputs/yes_energy_pipeline_risk_readout.html`; the name never carries the month, so a scheduled daily run always rewrites the same file. A rerun overwrites the page, so fix the data and run again rather than editing anything.
4. **Hand over** (§5), adding the `since_last` lines from the JSON output under "Since last month". Say "first run" when there is no earlier page, and give the reason when the comparison is unavailable. Report a WARN check rather than hiding it.

**Since last month** (`scripts/gtm/compare.py`). The previous run's page embeds its payload, so it is the record; no state file is kept. When a run is for a later month than the page already at `outputs/yes_energy_pipeline_risk_readout.html`, that page is first copied to `outputs/previous/yes_energy_pipeline_risk_readout.html`; every run in the new month compares with that copy. The comparison covers four areas, all computed in Python and quoted as printed:
- the last-twelve-month lens (`LTM_pq`): bookings by measure, average deal value, created pipeline, win rate, and growth on the prior quarter. That lens never resets at a fiscal year or quarter boundary.
- weighted pipeline and the open count.
- the weighted pipeline dated to close in the current fiscal quarter.
- decisions newly raised or no longer raised, and changed QC checks.

The page itself is unchanged. Keep `outputs/` between runs so the comparison has a predecessor. A page on another contract version or data mode is not compared, and the output says why: pages built before renderer 1.7.0 (contract 1.0.0, prior-year basis) are not compared with later ones.

**A stop is a result.** A stop from steps 1 or 3 is reported in one line with its reason. Never fall back to an older month, a partial extract or local data to produce a page.
