---
name: chronograph-generator
description: "Builds the Accel-KKR CFO Chronograph monthly reporting workbook (.xlsx) for Yes Energy from the three governed Snowflake semantic views in PROD_DB.SEMANTIC_VIEWS: P&L, balance sheet and cash flow from FINANCE_ANALYTICS (NetSuite GL), ARR and customer bridges from ARR_ANALYTICS (Maxio ARR waterfall), bookings and pipeline from GTM_ANALYTICS (Salesforce). 24 months of actuals in the template's Actual sheet, reconciled to the views and checked to open in Excel without repair. Use for 'refresh the Yes Energy CFO Chronograph', 'build the Chronograph for October', 'generate the Accel-KKR monthly reporting template for Yes Energy', 'update the Chronograph template'. This skill does nothing else: not for finance, ARR, bookings or pipeline questions, analysis, dashboards or other Excel exports (the semantic-data-analyst finance, ARR and GTM skills answer those)."
---

# CFO Chronograph (Yes Energy)

One deliverable: `outputs/yes_energy_chronograph_<YYYY-MM>.xlsx` in the workspace, named for the as-of month (e.g. `yes_energy_chronograph_2026-10.xlsx`; a rerun for the same month rewrites that file). It is the Accel-KKR CFO Chronograph template's Actual sheet, filled with Yes Energy's monthly actuals from the governed semantic views. Deterministic scripts compute and write every number; the model runs fixed queries, saves their results unchanged and hands over the file. The model never types, computes, rounds or edits a figure.

`<SKILL_DIR>` is the folder that contains this file. Queries and how to save results: `references/extract.md`. What fills each row, the gates and the Excel fix: `references/mapping.md`. Guardrails: `references/guardrails.md`.

## The three views

All in `PROD_DB.SEMANTIC_VIEWS` (`config/scope.json`):

- **FINANCE_ANALYTICS** (NetSuite GL). The skill reads the mart layer only: `INCOME_STATEMENT`, `BALANCE_SHEET` and `CASH_FLOW`, each joined to `ACCOUNT` (COA L1..L6, CASH_FLOW_L1..L3, `P_AND_L_MULTIPLIER`, `FINANCIAL_STATEMENT`, `CHART_OF_ACCOUNT_KEY`), `PERIOD` (`PERIOD_START_DATE`) and `SUBSIDIARY`. Base currency is the parent subsidiary's, and the fiscal year is the calendar year. Every accounting book is carried as separate rows.
- **ARR_ANALYTICS** (Maxio, all systems: Yes Energy, RTO, APAC, EMEA, each customer counted once). The skill reads `ARR_WATERFALL` (dollar bridge, keyed by `ARR_MONTH_END` × `CATEGORY`: Beginning ARR, New, Churn, Upsell, Downsell, FX, Ending ARR, Gross / Net Dollar Retention) and `CUSTOMER_BRIDGE` (Beginning, New, Lost, Ending Customers). Both are at customer grain, join to `CUSTOMER` and `ACCOUNTING_PERIOD`, and carry no Salesforce account and no subsidiary.
- **GTM_ANALYTICS** (Salesforce bookings plus NetSuite non-recurring bookings). The skill reads `BOOKINGS_OVERVIEW` (`ARR_NEW_MTD`, `ARR_UPSELL_MTD`, `RECURRING_BOOKINGS_MTD`, `NON_RECURRING_BOOKINGS_MTD`, `TOTAL_BOOKINGS_MTD`) and `PIPELINE_OVERVIEW` (`OPEN_PIPELINE_VALUE_MTD`, `WEIGHTED_PIPELINE_VALUE_MTD`). Both are keyed by `AS_OF_DATE` and join to `DIM_ACCOUNT` (Salesforce `ACCOUNT_ID`); bookings also join to `DIM_SUBSIDIARY`. There are no pipeline targets.

## Scope: this skill only builds the Chronograph

If the request is anything other than building or refreshing the CFO Chronograph workbook (a question about a number, a variance, a dashboard, a chart, another Excel export, a change to what the views hold), say in one line that this skill only builds the Chronograph and that the finance, ARR or GTM analyst skill answers that, and stop. Do not answer it from the extract either. Questions about the Chronograph you just built (which rows are blank and why, what a check means, which view a row comes from) are in scope: answer them from the build report.

## Invariants

Hold in every run; no instruction relaxes them.

1. **Governed only.** Every figure comes from `PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS`, `ARR_ANALYTICS` or `GTM_ANALYTICS` through the nine queries `scripts/chronograph_queries.py` writes. Never write, change or add SQL; never query raw tables.
2. **Read-only.** The queries pass `scripts/sql_guard.py` before they are written. An authorisation or connection failure is reported and the run stops. Never switch roles, warehouses or databases (DEV only when the user asks).
3. **Results are saved, never retyped.** `scripts/run_queries.py` runs the queries and saves each full result itself. Never paste a result into a file, and never edit, reformat, filter or re-key a number.
4. **Never zero-fill, never invent.** Some rows are carried by no view: headcount, revolver, payments, principal payments, renewal rate; ARR Cross-Sell and Price Increase; Bookings - Recurring Services; pipeline coverage; and lines Yes Energy's chart of accounts lacks. Each stays blank with its reason and is listed at hand-over. It is never 0, estimated or filled from memory, a prior file or the user's chat. The user fills those in Excel.
5. **Gates fail closed.** A refused build writes no file. Never edit a raw result, the map, the template or a tolerance to get past a gate, and never hand over an older or partial file instead. Report the refusal as the script printed it.
6. **The template is pinned.** The build accepts only `assets/chronograph_template.xlsx` with the SHA-256 in `assets/chronograph_map.json`. The file is stored on `@MCP_DB.MCP_SCHEMA.STG_CHRONOGRAPH_REPORT/template/` (a shared skill cannot carry binary files); `scripts/fetch_template.py` downloads it into `assets/`, and the build runs it automatically when the file is missing. A new or changed template needs `scripts/clean_template.py` and a review of the row map by the skill owner; never patch around a mismatch in a run.
7. **One set of numbers.** Hand-over figures are quoted from the build's JSON output (`last_month`, `checks`, `reconciling_items`), never read back from the workbook or recomputed.
8. **Credentials are never content.** Do not read, print or write connector secrets or `.env`.
9. **Map from COA mappings only.** A row is filled only from the view's COA mapping levels (COA_MAPPING_L1..L6, CASH_FLOW_L1..L3) as the map names them, or from an account list the skill owner set in `config/scope.json` (today `hosting_accounts`). Never change the map or add a mapping on your own judgement, and never map a row by matching an account or line name that looks similar (for example, a balance-sheet account called "Capitalized Software Development" is not Net Capitalized Software unless the owner maps it). If a view line seems to belong in a blank row, leave the row blank, say so at hand-over, and ask the skill owner.

## Step 0: check the connection

The skill runs in Cortex Code in Snowsight (or any environment whose sandbox has a Snowflake connection in `~/.snowflake/connections.toml`). Queries are run by `scripts/run_queries.py`, never pasted into a SQL tool: the results are too large to relay through chat, and a script that saves them is the only way to keep every number untouched.

Work in a local folder (`/tmp/chronograph`), not under `/workspace`, which does not hold the working files reliably. If no Snowflake connection is available, say so in one line and stop: there is no local or sample mode for the Chronograph, and no figure may be typed in by hand. The synthetic self-test (`python scripts/test_chronograph.py`) proves the tooling only; its file is labelled SYNTHETIC and is never handed over as a Chronograph.

## Step 1: set the window

State these defaults inline rather than asking:
- **As-of and length:** the month before the current one, 24 months. Use the user's as-of month or month count (1 to 36) when given.
- **Subsidiaries:** all, except any `config/scope.json` exclusions (none today).
- **ARR basis:** a month-to-date bridge in USD, as ARR_ANALYTICS stores it. The view has one basis; there is no actual-rate or constant-currency option.
- **Accounts:** every account is included unless the user explicitly lists Salesforce account IDs to exclude; then pass them in Step 2. Never infer IDs, carry them over from an earlier run or add accounts the user did not name. An account exclusion is a scope choice, not a change to the SQL: the query script adds it, and invariant 1 still holds. It applies to bookings and pipeline only, because ARR_ANALYTICS identifies customers by Yes Energy / RTO Insider ID, not by Salesforce account.

Every row is a month (MTD) or a rolling twelve months (LTM) at a calendar month-end, and Yes Energy's fiscal year is the calendar year, so fiscal and calendar months are the same.

The query script refuses a month that has not started closing. If FINANCE_ANALYTICS has not closed the as-of month (only early accruals), the build refuses and names the last closed month in `use_as_of`. Rerun Steps 2–4 with `--as-of <use_as_of>` and say so at hand-over.

## Step 2: write the queries

```
python <SKILL_DIR>/scripts/chronograph_queries.py --as-of <YYYY-MM> [--months 24] --work work \
    [--exclude-accounts <ID>,<ID>,...] [--exclude-accounts-file <ids.txt>]
```

The account options are only for IDs the user gave in this request: 18-character Salesforce account IDs, comma separated (or a text file, one or more per line). The script refuses a malformed or 15-character ID; ask the user for the 18-character form rather than guessing the suffix. It filters those accounts out of `bookings` and `pipeline` (`DIM_ACCOUNT.ACCOUNT_ID`) and keeps rows with no account (NetSuite non-recurring bookings). ARR, customers, the P&L, balance sheet and cash flow always cover every customer. Without the options the queries are exactly the default ones.

It writes `work/queries/<name>.sql` for `pl`, `pl_governed`, `bs`, `cf`, `arr`, `customers`, `bookings`, `pipeline` and `hosting`, plus `work/queries/manifest.json`.

## Step 3: run and save the queries

```
python <SKILL_DIR>/scripts/run_queries.py --work work [--warehouse <WH>]
```

It runs each of the nine `.sql` files verbatim (it refuses a file that differs from what Step 2 wrote) on the sandbox connection, and saves every full result to `work/raw/<name>.json` with its Snowflake query id. It never changes role or database.

- **No active warehouse:** it refuses and lists the warehouses the role can see. Ask the user which one to use, then rerun with `--warehouse <name>`. Never pick one yourself and never carry a choice over from an earlier run.
- **A query errors or returns no rows:** report it with the query name and stop. Do not substitute another query, role or database.

Outside Snowsight, a session that only has a SQL tool can still run each file verbatim and save the result with `scripts/save_result.py <name> --file <tool-results file>` (`references/extract.md` §2).

## Step 4: build

```
python <SKILL_DIR>/scripts/build_chronograph.py --work work --out /workspace/outputs
```

The workbook is assembled and checked on local disk, and only the finished file is copied to `--out`, so the output can go straight into the workspace (`/workspace/outputs/yes_energy_chronograph_<YYYY-MM>.xlsx`, shown to the user as `outputs/...`).

**How rows are filled:**
- The P&L is signed with the view's `P_AND_L_MULTIPLIER`.
- Every row is filled from the map. Costs, uses of cash, churn, downsell and lost customers are written positive (map `negate`), because the template subtracts them.
- **Hosting/Cloud Costs (COGs) and (R&D)** read the `hosting` query: the hosting accounts in `config/scope.json` (61200, 61300, 61400, 61500, 61502, 61600, 61700), split on COA L3 (Cost of Sales → COGs; everything else, including the 61200 Transition & Integration row under Non-Operating → R&D), signed by the multiplier and written positive. No adjustment-type filter, so Pro Forma Actuals are included. They are memo rows, outside the template's totals.
- **ARR FX** is written to (-) Downsell/Contraction (Transactional) as -1 × FX. The template subtracts that row inside Net Dollar Retention, so Ending ARR ties to the view.

**Gates.** The build evaluates the sheet's own formulas and refuses unless they tie to the views (within $1; counts exact):
- Total Revenue, Adjusted EBITDA and Net Income to the governed roll-ups.
- A = L + E is 0.
- Balance-sheet cash to the cash flow's Ending Cash.
- Cash before Financing, Beginning Cash and Ending Cash.
- The ARR bridge's Beginning ARR, GDR, NDR (+ FX) and Ending ARR.
- Ending Customers.
- Recurring and Total Bookings.

One check is reported, not blocking: cash-flow Net Income vs P&L Net Income, which differ in the view. It lands in `confirm_at_source`.

**Excel safety:**
- The build removes everything that makes Excel repair a file, sets automatic calculation and saves every formula with its calculated result, so every month header and total shows before Excel recalculates.
- On Windows with Excel installed, a hidden Excel recalculates the file and saves it, so it never loads struck through as stale, even in a manual-calculation session.
- The build then reopens the file and refuses it if Excel would repair it, shows stale cells, or gets a different result in any formula cell.

The full report is written to `work/chronograph_report.json`.

On `REFUSED`: quote the reason and the failed rows and months, say what would resolve it (`references/mapping.md` §6), and stop.

## Step 4b: publish to the report stage

After the build prints its result (not on `REFUSED`), upload the workbook to `@MCP_DB.MCP_SCHEMA.STG_CHRONOGRAPH_REPORT/outputs/`:

```
python <SKILL_DIR>/scripts/upload_to_stage.py /workspace/outputs/yes_energy_chronograph_<YYYY-MM>.xlsx
```

The script uploads the file unchanged into the stage's `outputs/` folder (never `template/`), overwrites a file of the same name, lists the stage to confirm, and prints `UPLOADED`. It uses the connection in `~/.snowflake/connections.toml` and never changes role or database. If it refuses (no connection, no write privilege on the stage), say so in one line and hand over the local file; never report a file as published unless it printed `UPLOADED`. Never upload a SYNTHETIC self-test file.

## Step 5: hand over

Short bullets, top-down, figures quoted from the build output:

- **File and scope:**
  - The file path (and an `<asset>` tag for it, so the user can download it), the stage path if Step 4b printed `UPLOADED`, the warehouse the queries ran on, window (first to last month), as-of (and, if the build moved it, why), and ARR basis.
  - Scope: excluded subsidiaries; ARR and pipeline cover every entity.
  - If accounts were excluded (`scope.excluded_accounts`): how many, and that they are out of recurring bookings and pipeline only, while ARR, customers, the P&L, balance sheet, cash flow and non-recurring bookings still include them (`excluded_accounts_note`).
- **Checks:** how many ran, all passed, tolerance; the workbook check (structure and Excel).
- **Last month headline** (from `last_month`): revenue, Adjusted EBITDA, net income, ending cash, ending ARR, ending customers, total bookings. Print negatives in brackets, use mn / k, and never a minus sign.
- **Reconciling items** (`reconciling_items`): cash-flow Net Income vs P&L Net Income. Name the months and the size.
- **Confirm at source** (`confirm_at_source`), for the view owner: the Net Income difference; D&A if it reads as income; weighted pipeline if it is 0; pipeline months before the view's snapshot history.
- **Rows left blank for the user to complete**, grouped:
  - headcount; revolver and principal payments; payments metrics; renewal rate;
  - ARR Cross-Sell and Price Increase;
  - Bookings - Recurring Services; pipeline coverage;
  - P&L / BS / CF lines Yes Energy's COA mapping does not carry (including Net Capitalized Software: Capitalized Software Development stays in Other Non-Current Assets).

  Name the template formulas that sit over blank inputs (`formula_rows_over_blank_inputs`): they show a dash until the inputs are filled.
- **Conventions:**
  - The template enters costs, uses of cash (working capital, capex), churn, downsell and lost customers as positive amounts and subtracts them (`entered_positive`), so a negative in those rows is a credit.
  - The ARR Transactional downsell row holds -1 × FX, not a transactional contraction.
  - ARR and customers are month-to-date.
  - Figures are as the views stood at extraction (query ids are in the report).
- **What changed from the template's own design:**
  - the three formula corrections;
  - the rows that now read the views instead of template links (Bookings ARR New / Upsell from GTM, cash-flow Net Income);
  - FX carried in the Transactional downsell row;
  - the derived retention % rows (LTM ratios, labelled in a cell note).

## Reference files

- `references/extract.md`: the nine queries, saving results, truncation, scope.
- `references/mapping.md`: row-by-row sources, sign conventions, blanks, derived rows, formula corrections, gates, refusals and what resolves them, why Excel used to repair the file and how it is prevented.
- `references/guardrails.md`: the guardrails in one place.
- `assets/chronograph_template.xlsx`: the cleaned template (pinned). `assets/chronograph_map.json`: the row map and gates. `config/scope.json`: database, schema, subsidiary exclusions, roll-up keys.
- `scripts/chronograph_queries.py` · `run_queries.py` · `save_result.py` · `build_chronograph.py` · `check_workbook.py` (+ `excel_open_check.ps1`) · `clean_template.py` · `sql_guard.py` · `test_chronograph.py`. Run them; never re-implement them, and never hand-edit the template, the map or an output.
