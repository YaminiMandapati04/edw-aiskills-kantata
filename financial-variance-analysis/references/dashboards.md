# The Finance diagnostic dashboard

One deliverable: a single offline HTML file with three tabs (Summary, Drivers, Outlook) that says what moved in the P&L, what is good and what is bad, what is driving it, whether it persists, and what management must decide. The Power BI pages already show the trend and the variance tables; this dashboard reads them and adds the diagnosis. Its charts and tables are the supporting evidence a reader drills into, not the headline.

Layout (renderer 1.5.0; regions in `dashboard-contract.md` §4): the Summary opens with 3 to 5 insight bullets (each a bold conclusion, the observation, then what it means): the net-income lead, reviewed conclusions when a diagnosis is admitted, engine insights on persistence, concentration, margin trend, mix and budget bias, and the full-year implication. Every bullet is built by the engine with its figures registered, and clicking it opens the evidence at the level of its claim (a revenue-led lead opens revenue by L4 driver, then accounts, with costs alongside). Then a P&L strip in order of calculation, the drivers that moved net income and the decisions for management (one fact-built question per material driver). Every driver drill is a reconciling table (top accounts, the remainder, the total = the driver's movement) with a comparator-to-actual waterfall, then a top-down Department › Account split; accounts active in only one period carry a 'New this period' or 'Not this period' chip. Drivers and Outlook are chart-led. Every figure opens a drawer with the detail as charts and short bullets. A collapsible, tab-aware glossary at the foot defines every label on the open tab, or on the whole page. The look follows the reference report design system: dark-grey banner, lime accent, mono labels, dark table headers. Negatives print in brackets; the wording is favourable / unfavourable / in line, never "adverse".

## Contents
1. When to build it
2. The query
3. The pipeline
4. Options
5. Hand-over
6. What it does not do

---

## 1. When to build it

Build it when the user asks for the month-end finance review, the finance dashboard, "how are we doing and why", the variance analysis for a period, what is driving EBITDA, or a management readout. A one-off question ("why is EBITDA below budget?") is answered in chat first (`SKILL.md` Steps 2 to 4); offer the dashboard in one line. ARR and GTM dashboards are not built: those questions use the chat workflow and, for files, the result bundle (`output-formats.md`).

Ask once, in one short question, before querying: the whole income statement (all subsidiaries, recommended) or one subsidiary. Never choose a subset yourself.

## 2. The query

Read `view-finance.md` (mart layer, hierarchy, account grain, negative keys, cautions) and probe the latest closed period and the fiscal-year end as in `semantic-views.md` §9. The scope is every subsidiary **except** those in `config/scope.json` (`exclude_subsidiaries`, none today); the user may add or lift exclusions, and the page names them. Every statement below uses the same `WHERE` scope:

```sql
-- <SCOPE>
         AND ACCOUNT.FINANCIAL_STATEMENT = 'P&L'
         AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-6','-8','-9','-10','-11','-12','-15','-19','-100','-1000')   -- roll-ups only
      -- AND (SUBSIDIARY.SUBSIDIARY_NAME IS NULL OR SUBSIDIARY.SUBSIDIARY_NAME NOT IN ('<excluded>'))   only when config/scope.json lists exclusions;
      --     keep the IS NULL arm: the capitalisation adjustments carry no subsidiary and a bare NOT IN drops them
```

**Probes.** (1) Negative keys: `SELECT DISTINCT CHART_OF_ACCOUNT_KEY, ACCOUNT_NAME, ACCOUNT_TYPE, COA_MAPPING_L2` for keys `LIKE '-%'`; every one must be a listed roll-up (`ACCOUNT_TYPE` `Subtotal`) or a capitalisation key (`config/scope.json` `capitalisation_keys`: `-8001`, `-8002`, `-8003`); the build refuses any other. (1a) Adjustment types: `SELECT DISTINCT INCOME_STATEMENT.ADJUSTMENT_TYPE` over the range; every non-null value must be in `config/scope.json` `adjustment_types` (`Pro Forma Actuals`, `Pro Forma Adjustments`, `Adjustment for Capitalized expenses`). The build refuses an unknown one rather than drop it. (2) The account-key count for `--expect-accounts`: `COUNT(DISTINCT CHART_OF_ACCOUNT_KEY)` under the scope over the whole range. (3) For each month, `COUNT(*)` of the data query below with the same scope: the `--expect-rows` of that month's file.

**The data query** returns one row per month x subsidiary x account key x class x department (about 1,500 rows a month in production). Run it from at least 24 months before the as-of month **through the fiscal year end** (budget columns are populated for future months; the outlook needs them, and the build ignores the stray actuals of an open month), **one month per statement**:

```sql
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD, PERIOD.PERIOD_START_DATE, PERIOD.PERIOD_END_DATE, PERIOD.YEAR, PERIOD.QUARTER,
             SUBSIDIARY.SUBSIDIARY_NAME,
             ACCOUNT.CHART_OF_ACCOUNT_KEY, ACCOUNT.ACCOUNT_NUMBER, ACCOUNT.ACCOUNT_NAME, ACCOUNT.ACCOUNT_TYPE, ACCOUNT.P_AND_L_MULTIPLIER,
             ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3, ACCOUNT.COA_MAPPING_L4, ACCOUNT.COA_MAPPING_L5, ACCOUNT.COA_MAPPING_L6,
             CLASSIFICATION.CLASS_NAME, DEPARTMENT.DEPARTMENT_NAME, INCOME_STATEMENT.ADJUSTMENT_TYPE
  METRICS    INCOME_STATEMENT.TOTAL_MTD, INCOME_STATEMENT.TOTAL_PY_MTD, INCOME_STATEMENT.TOTAL_BUDGET_MTD
  WHERE      PERIOD.PERIOD_START_DATE = '<month start>'
             <SCOPE>
);
```

**Signs and adjustments.** The view stores P&L values unsigned; `P_AND_L_MULTIPLIER` gives each account its profit orientation (revenue +1, costs −1; the capitalisation keys `-8001` / `-8002` / `-8003` carry −1 like any expense). The build multiplies actual, prior year and budget by it, so the accounts sum to net income; never drop the column. `INCOME_STATEMENT.ADJUSTMENT_TYPE` is part of the grain: each adjustment type is its own row. **Never filter it out.** The adjustment rows are inside the governed `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD` and `NET_INCOME_MTD`, so dropping them breaks the tie-out. Two kinds: (i) pro forma (`Pro Forma Actuals` on ordinary accounts with a subsidiary; `Pro Forma Adjustments`, cost reclasses near nil); (ii) the capitalisation of software (`-8001`, R&D) and commissions (`-8002`, S&M) inside Adjusted EBITDA, reversed on `-8003` below EBITDA, with no subsidiary (shown under "Group level (no subsidiary)"). The build reports them in QC (`adjustments_included`; it warns if the capitalisation does not net to zero at net income) and per lens in `lenses[*].adjustments`. Elimination entities (`xElim - …`, `… - xElim (…)`, `Elimination`) are ordinary subsidiaries in the view and are included in the consolidated totals.

`COA_MAPPING_L5` / `L6` are live (16-Nov-2026): the engine carries them under each L4 driver (L4 › L5 › L6 › account; a level that repeats its parent is collapsed; each level foots to the one above or the build refuses), splits revenue by product line and the operating expenses by sub-group (in the payload and the brief; the page shows them in each driver's By sub-group drill, not as separate panels). An extract without the two columns still builds, with drills stopping at L4 (QC `l5_footing` NOT_RUN).

**The governed query** (one statement, every month in the extract): the view's own monthly roll-ups by month and subsidiary, which the build reconciles the extract against (tolerance $1, fail closed). Only the `_MTD` metrics are read: every QTD / YTD / LTM window is the sum of `TOTAL_MTD` over its months, so a window ties whenever its months tie (the `window_tie_out` data check reports this). The view's `_QTD` / `_YTD` / `_LTM` columns are not queried: each is tagged to the account keys present in one month, so keys from earlier months drop out and the column comes out incomplete:

```sql
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD_START_DATE, SUBSIDIARY.SUBSIDIARY_NAME
  METRICS    INCOME_STATEMENT.REVENUE_MTD, INCOME_STATEMENT.ADJUSTED_EBITDA_MTD, INCOME_STATEMENT.NET_INCOME_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '<first month>' AND '<as-of month>'
      -- AND (SUBSIDIARY.SUBSIDIARY_NAME IS NULL OR SUBSIDIARY.SUBSIDIARY_NAME NOT IN ('<excluded>'))   only when config/scope.json lists exclusions
);
```

**The GL memo extract (§2a).** The view's `TRANSACTIONS_AND_ADJUSTMENTS.MEMO` is the free-text NetSuite memo of each GL line (on a manual adjustment, the adjustment reason): what the person who posted the line called it. The review uses it as evidence of what a movement was. One statement per month, from the first month of the data query **to the as-of month** (memos exist for actuals only), with the same scope as the data query:

```sql
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD_START_DATE, SUBSIDIARY.SUBSIDIARY_NAME, ACCOUNT.CHART_OF_ACCOUNT_KEY,
             TRANSACTIONS_AND_ADJUSTMENTS.SOURCE_TYPE, TRANSACTIONS_AND_ADJUSTMENTS.MEMO
  METRICS    TRANSACTIONS_AND_ADJUSTMENTS.TOTAL_IS_CONVERTED_AMT, TRANSACTIONS_AND_ADJUSTMENTS.TRANSACTION_LINE_COUNT
  WHERE      PERIOD.PERIOD_START_DATE = '<month start>' AND ACCOUNT.FINANCIAL_STATEMENT = 'P&L'
             -- AND ACCOUNT.CHART_OF_ACCOUNT_KEY < '8'   /   >= '8'   when the month is over about 1,800 rows (two statements)
);
```

`TOTAL_IS_CONVERTED_AMT` is `TOTAL_MTD` x `P_AND_L_MULTIPLIER` (profit-oriented, verified to the cent against the mart on 20-Nov-2026), so the build reconciles every account-month of memos to the actuals within $1 and refuses on a gap. Probe the row count per month first (`COUNT(*)` grouped by `PERIOD_START_DATE`, and by the key half for a large month); a result over about 300k characters is cut at the first partition and `result_to_csv.py --expect-rows` refuses it, so split it. PROD has no separate year-end adjustment period (probed 23-Nov-2026: every `PERIOD_START_DATE` is a month start). If one appears, extract it as `work/memo-<YYYY-MM-DD>.csv`; the build folds it into its month. Manual adjustment rows (`SOURCE_TYPE = ADJUSTMENT`) have a NULL memo and reconcile as a blank-memo group. Convert each result with `python scripts/result_to_csv.py table <result> work/memo-<YYYY-MM>.csv --expect-rows <N>` and pass them all with `--memos work/memo-*.csv`. Without memos the build still runs (QC `gl_memos` NOT_RUN) and the review reads the statement marts only.

**Extraction mechanics.** `sql-exec` returns only the **first result partition** inline; a large result is written to a tool-results file, and a multi-partition result is silently cut off. So: one month per statement; convert each saved result with `python scripts/result_to_csv.py table <result> work/finance-rows-<YYYY-MM>.csv --expect-rows <N>` (N from that month's `COUNT(*)` probe); never accept a file whose declared `numRows` exceeds the rows present (the script refuses it, and refuses a row-count mismatch). Save the governed result the same way as `work/finance-governed.csv`. The build refuses a cut-off result (`--expect-accounts`), overlapping chunks, missing months, an unknown negative key, or any month x subsidiary that does not tie to the governed roll-ups.

## 3. The pipeline

Scripts are in `scripts/` (run them from there or with the full path; Python from `requirements.txt`). Every script fails closed and prints JSON.

| Phase | Command | Produces |
|---|---|---|
| P1 Extract | §2: the probes, the data query one month per statement, the governed query, the GL memo extract (§2a) | `work/finance-rows-*.csv`, `work/finance-governed.csv`, `work/memo-*.csv` |
| P2 Analyze | `python analyze_finance.py --rows work/finance-rows-*.csv --governed work/finance-governed.csv --memos work/memo-*.csv --out work/finance_payload.json --as-of <YYYY-MM> --expect-accounts <N> [options]` | `finance_payload.json` (contract `sda.finance-analysis/1.5.0`): lenses, bridge, layers, signals, insights, explanations, actions, outlook, QC, headline; validated on write |
| P3 Validate | `python validate_finance_payload.py work/finance_payload.json` | OK or the invariant that failed (bridge, footing, tiers, provenance, hash) |
| P4 Diagnose (required for the Month and Year-to-date views on the page's basis, `MTD_py` and `YTD_py` by default; one `diagnosis.json` per view, `--lens` on the brief) | read `specialists/driver-review.md`, then `specialists/readout.md`; read evidence only through `python finance_brief.py work/finance_payload.json brief` and its `driver`, `account`, `resolve` ops; write `work/diagnosis.json` | the model's findings and readout for the primary lens |
| P5 Admit | `python validate_finance_diagnosis.py --payload work/finance_payload.json --diagnosis work/diagnosis_mtd.json` (and `_ytd`) | ADMITTED, or the reasons; fix the diagnosis, never the payload |
| P6 Render | `python render_finance_dashboard.py --payload work/finance_payload.json --diagnosis work/diagnosis_mtd.json work/diagnosis_ytd.json --out outputs/` | `outputs/budget_vs_actuals_readout.html` (fixed name, no month: a scheduled run rewrites the same file), one self-contained file under the 16 MB Artifact limit (the RENDERED JSON's `embed` reports the stage and sizes; refused with gate `size` if it cannot fit). Refused when the Month or Year-to-date review is missing; `--allow-missing-review` publishes anyway with a visible notice, and you say so at hand-over |
| P7 Hand over | §5 | |

`analyze_finance.py` rebuilds everything from the rows; a changed extract, scope, threshold or as-of changes `analysis_hash`, and a diagnosis written against the old hash is refused at P5. Rerun P4 after any P2 change.

Local test mode (a finance workbook laid out as in `local-mode.md`, no connector): `--workbook path/finance_sample.xlsx` instead of `--rows`. The page then carries the LOCAL TEST DATA banner and QC marks the mode. `python test_finance_pipeline.py` runs the whole pipeline on the synthetic sample and checks the rendered page; add `--scale` to check a ~1,700-account page against the 16 MB limit.

## 4. Options

| Option | Use |
|---|---|
| `--as-of YYYY-MM` | the analysis month (default: the latest month with actuals); later months are budget only |
| `--expect-accounts N` | from the account probe; the build stops on a mismatch |
| `--subsidiary "<name>"` | one subsidiary (the page states the scope); default is all subsidiaries in scope |
| `--exclude-subsidiary "<name>"` | leave a subsidiary out (repeatable), on top of `config/scope.json`; add it to the query `WHERE` too |
| `--no-default-exclusions` | lift the `config/scope.json` exclusions (the governed reconciliation still applies) |
| `--memos <files>` | the GL memo extract, one file per month (§2a); reconciled to the actuals ($1 per account-month, refused on a gap); adds `memo_evidence` to every lens and `memos` (run-rate months, one-offs, restricted terms), never embedded in the page |
| `--governed <file>` | the governed roll-ups by month x subsidiary (required with `--rows`) |
| `--window MTD\|QTD\|YTD\|LTM --basis budget\|py` | the lens the page opens on and the diagnosis is written for (default Month vs Prior year; pass `--basis budget` to open on budget, the layers in `finance-analysis.md` §7 still read Month vs Budget whatever the primary lens) |
| `--materiality executive=,management=,management_pct=,monitoring=` | dollar thresholds; default scaled to LTM revenue and disclosed |
| `--expense-sign negative\|positive` | declare how expenses are stored in actuals and prior year; default detected from the data and flagged in QC |
| `--budget-sign negative\|positive` | declare how expenses are stored in the budget; default detected from the budget itself. A sign that differs from actuals is normalised, not an error; QC reports it |
| `--scope-note`, `--title`, `--source` | page text |

## 5. Hand-over

- Hand over the **single `.html` file** and its path. Do not zip or split it; it opens in any browser and works offline.
- Say the scope as the page states it ("All subsidiaries (N)", with "excluding …" when any are excluded, or the one chosen), the as-of month, the lens it opens on, and whether the page is AI reviewed ("Data verified, not yet AI reviewed" otherwise). Say the QC status and the caveats that matter (sign convention detected, no fiscal-year budget in the extract, cut-off check not run). If the render's `embed.stage` is `B`, say that immaterial accounts show no drill-down evidence or run-rate detail, and how many (`embed.accounts_trimmed`).
- Quote figures from the payload or the brief, never from the page, and never claim to have viewed it. Lead with the headline from `finance_brief.py ... headline` and the two or three follow-up items.
- Say whether the review used the GL memos (QC `gl_memos`) and for which months; memos describe postings, they are not dispositions, and the page shows no memo text or names.
- State the limits once: owners are suggested, dates are rule-generated, forecast credit is 0, no business cause is verified by the ledger; transaction-level evidence needs the GL drill in chat.

## 6. What it does not do

- It does not go through the result bundle, `bundle.py` or `verify_outputs.py`; its integrity comes from the payload invariants, the diagnosis gate and the render-stage checks.
- No price, volume, mix or FX split (no grain in the marts); no transactions (drill the TRANSACTIONS table in chat); no location (subsidiary, class and department are carried as drill detail); no management forecast or mitigation (none is supplied); no dispositions (a named person records those outside the page).
- Do not edit the files under `artifacts/finance_analytics/` for one request: the renderer is shared. Change it only to improve the dashboard for everyone, bump `VERSION`, and rerun `test_finance_pipeline.py`.
