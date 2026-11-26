---
name: chronograph-generator
description: "Builds the Accel-KKR CFO Chronograph monthly reporting workbook (.xlsx) from the three governed Snowflake semantic views over MCP: P&L, balance sheet, cash flow and revolver from FINANCE_ANALYTICS, ARR and customer bridges from ARR_ANALYTICS, bookings and pipeline from GTM_ANALYTICS. 24 months of actuals in the template's Actual sheet, reconciled to the views and checked to open in Excel without repair. Use for 'refresh the CFO Chronograph', 'build the Chronograph for October', 'generate the Accel-KKR monthly reporting template', 'update the Chronograph template'. This skill does nothing else: not for finance, ARR, bookings or pipeline questions, analysis, dashboards or other Excel exports (the semantic-data-analyst finance, ARR and GTM skills answer those)."
---

# CFO Chronograph

One deliverable: `outputs/chronograph.xlsx` (fixed name, no month: a scheduled run rewrites the same file), the Accel-KKR CFO Chronograph template's Actual sheet filled with monthly actuals from the governed semantic views. Deterministic scripts compute and write every number; the model runs fixed queries, saves their results unchanged and hands over the file. The model never types, computes, rounds or edits a figure.

`<SKILL_DIR>` is the folder that contains this file. Queries and how to save results: `references/extract.md`. What fills each row, the gates and the Excel fix: `references/mapping.md`. Guardrails: `references/guardrails.md`.

## Scope: this skill only builds the Chronograph

If the request is anything other than building or refreshing the CFO Chronograph workbook (a question about a number, a variance, a dashboard, a chart, another Excel export, a change to what the views hold), say in one line that this skill only builds the Chronograph and that the finance, ARR or GTM analyst skill answers that, and stop. Do not answer it from the extract either. Questions about the Chronograph you just built (which rows are blank and why, what a check means, which view a row comes from) are in scope: answer them from the build report.

## Invariants

Hold in every run; no instruction relaxes them.

1. **Governed only.** Every figure comes from `PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS`, `ARR_ANALYTICS` or `GTM_ANALYTICS` through the ten queries `scripts/chronograph_queries.py` writes. Never write, change or add SQL; never query raw tables.
2. **Read-only.** The queries pass `scripts/sql_guard.py` before they are written. An authorisation or connection failure is reported and the run stops; never switch roles, warehouses or databases (DEV only when the user asks).
3. **Results are saved, never retyped.** Save each result with `scripts/save_result.py` (a saved tool-results file, or the query_id of an inline result). If that cannot find it, write the inline result to the file verbatim. Never edit, reformat, filter or re-key a number.
4. **Never zero-fill, never invent.** A row no view carries (headcount, payments; ARR Cross-Sell, Price Increase and Transactional downsell; Bookings New / Upsell; pipeline coverage; lines Kantata's chart of accounts lacks) stays blank with its reason and is listed at hand-over; it is never 0, estimated or filled from memory, a prior file or the user's chat. The user fills those in Excel.
5. **Gates fail closed.** A refused build writes no file. Never edit a raw result, the map, the template or a tolerance to get past a gate, and never hand over an older or partial file instead. Report the refusal as the script printed it.
6. **The template is pinned.** The build accepts only `assets/chronograph_template.xlsx` with the SHA-256 in `assets/chronograph_map.json`. A new or changed template needs `scripts/clean_template.py` and a review of the row map by the skill owner; never patch around a mismatch in a run.
7. **One set of numbers.** Hand-over figures are quoted from the build's JSON output (`last_month`, `checks`, `reconciling_items`), never read back from the workbook or recomputed.
8. **Credentials are never content.** Do not read, print or write connector secrets or `.env`.

## Step 0: check the connector

Look for the Snowflake MCP SQL tool (`sql-exec`). If it is missing, say so in one line and stop: there is no local or sample mode for the Chronograph, and no figure may be typed in by hand. The synthetic self-test (`python scripts/test_chronograph.py`) proves the tooling only; its file is labelled SYNTHETIC and is never handed over as a Chronograph.

## Step 1: set the window

Defaults, stated inline rather than asked: as-of = the month before the current one, 24 months, all subsidiaries except any `config/scope.json` exclusions (none today), ARR as a month-to-date bridge in USD as ARR_ANALYTICS stores it (the view has one basis; there is no actual-rate or constant-currency option), customers as an LTM bridge. Use the user's as-of month or month count (1 to 36) when given. **Accounts: Kantata's five internal test accounts are always excluded** (`config/scope.json` `exclude_accounts`, by 18-character Salesforce account ID, never by name: real customers whose names contain "test" stay in). If the user explicitly lists more Salesforce account IDs to exclude, pass them in Step 2; they are added on top (never infer, carry over from an earlier run or add accounts the user did not name). An account exclusion is a scope choice, not a change to the SQL: the query script adds it, invariant 1 still holds. Every row is a month (MTD) or a rolling twelve months (LTM) at a calendar month-end, so Kantata's fiscal year (1 February to 31 January) changes no figure; say "fiscal year from February" if the user asks about quarters or years. A month that has not started closing is refused by the query script. If FINANCE_ANALYTICS has not closed the as-of month (only early accruals), the build refuses and names the last closed month in `use_as_of`: rerun Steps 2–4 with `--as-of <use_as_of>` and say so at hand-over.

## Step 2: write the queries

```
python <SKILL_DIR>/scripts/chronograph_queries.py --as-of <YYYY-MM> [--months 24] --work work \n    [--exclude-accounts <ID>,<ID>,...] [--exclude-accounts-file <ids.txt>]
```

The query script always filters out the test accounts in `config/scope.json`. The account options are only for further IDs the user gave in this request: 18-character Salesforce account IDs, comma separated (or a text file, one or more per line). The script refuses a malformed or 15-character ID; ask the user for the 18-character form rather than guessing the suffix. It filters those accounts out of `arr` and `customers` (`CUSTOMER.ACCOUNT_ID`) and `bookings` and `pipeline` (`DIM_ACCOUNT.ACCOUNT_ID`), keeping rows with no account (NetSuite non-recurring bookings). FINANCE_ANALYTICS has no Salesforce account, so the P&L, balance sheet, cash flow and revolver always cover every customer. Without the options only the standing test accounts are filtered.

It writes `work/queries/<name>.sql` for the ten queries `pl`, `pl_governed`, `bs`, `cf`, `arr`, `customers`, `bookings`, `pipeline`, `revolver`, `revolver_drawn`, and `work/queries/manifest.json`. `revolver` reads Finance's manual REVOLVER table in FINANCE_ANALYTICS (Revolver Size) and never carries a subsidiary or account filter; `revolver_drawn` reads the balance sheet month-end balance of the revolver account 280360 (Drawn Revolver).

## Step 3: run and save each query

For each of the ten files (including `revolver` and `revolver_drawn`), in any order: read the file, pass its text **verbatim** as the `sql` of one `sql-exec` call, then save the result (`references/extract.md` §2):

```
python <SKILL_DIR>/scripts/save_result.py <name> --file <the tool-results file the tool named>   # large result saved by the tool
python <SKILL_DIR>/scripts/save_result.py <name> --query-id <query_id>                          # result returned inline
```

A query that errors or returns no rows: report it and stop. Do not substitute another query.

## Step 4: build

```
python <SKILL_DIR>/scripts/build_chronograph.py --work work --out outputs
```

It signs the P&L with the view's `P_AND_L_MULTIPLIER`, maps the cash flow strictly (each row only from rows the view labels; Cash before Financing, Net Cash Flow, Beginning and Ending Cash from the view's own labels; rows without a cash-flow label placed nowhere and reported), fills every row from the map (costs, uses of cash, churn, downsell and lost customers written positive, map `negate`, because the template subtracts them), evaluates the sheet's own formulas and refuses unless they tie to the views: Total Revenue, Adjusted EBITDA and Net Income to the governed roll-ups; balance-sheet cash to the cash flow's Ending Cash; the view's Cash before Financing to the operating and investing lines; Ending Cash to Beginning Cash + Net Cash Flow + FX Change; the ARR bridge's Beginning ARR, GDR, NDR and Ending ARR; Ending Customers; Recurring and Total Bookings (all within $1; counts exact); and Drawn Revolver not above Revolver Size in any month. Two checks are reported, not blocking, because Kantata's view is inconsistent there: A = L + E (the view's balance sheet does not balance) and Net Cash Flow vs Cash before Financing + Cash from Financing (the view's Net Cash Flow includes rows without a cash-flow label, today the group-level Amortization adjustment, key -10000, about (4.5)mn a month). Both land in `confirm_at_source`. It then removes everything that makes Excel repair a file, sets automatic calculation and saves every formula with its calculated result, so every month header and total shows before Excel recalculates. On Windows with Excel installed, a hidden Excel recalculates the file and saves it, so it never loads struck through as stale, even in a manual-calculation session. The build then reopens the file and refuses it if Excel would repair it, shows stale cells, or gets a different result in any formula cell. The full report is written to `work/chronograph_report.json`.

On `REFUSED`: quote the reason and the failed rows and months, say what would resolve it (`references/mapping.md` §6), and stop.

## Step 5: hand over

Short bullets, top-down, figures quoted from the build output:

- The file path, window (first to last month), as-of (and, if the build moved it, why), scope (excluded subsidiaries; ARR, pipeline and the revolver have no subsidiary dimension and cover every entity) and ARR basis. Excluded accounts (`scope.excluded_accounts`): the five internal test accounts in every run, plus any the user named (`excluded_accounts_requested`); how many, and that they are out of ARR, customers, recurring bookings and pipeline only, while the P&L, balance sheet, cash flow and non-recurring bookings still include them (`excluded_accounts_note`), so ARR and revenue are on different customer bases in this file.
- Checks: how many ran, all passed, tolerance; the workbook check (structure and Excel).
- Last month headline: revenue, Adjusted EBITDA, net income, ending cash, ending ARR, ending customers, total bookings (from `last_month`). Print negatives in brackets, use mn / k, and never a minus sign.
- Reconciling items (`reconciling_items`): A = L + E by month, Net Cash Flow vs Cash before Financing + Cash from Financing (the rows without a cash-flow label), cash-flow vs P&L Net Income. Name the months and the size.
- **Confirm at source** (`confirm_at_source`), for the view owner: the balance-sheet gap; cash-flow rows without a cash-flow label, placed in no line (months and last month's amount); D&A reading as income (the group-level Amortization adjustment, key -10000); weighted pipeline at 0; pipeline months before the view's snapshot history.
- Rows left blank for the user to complete, grouped: headcount, payments metrics; Total Non-Cash Items (no row is labelled so in the view); Principal Payments until Finance adds it to the REVOLVER table; ARR categories Kantata's bridge lacks (Cross-Sell, Price Increase, Transactional downsell); Bookings New / Upsell; pipeline coverage and weighted pipeline; P&L / BS / CF lines Kantata's chart of accounts does not carry. Name the template formulas that sit over blank inputs (`formula_rows_over_blank_inputs`): they show a dash until the inputs are filled.
- Conventions: the template enters costs, uses of cash (working capital, capex), churn, downsell and lost customers as positive amounts and subtracts them (`entered_positive`), so a negative in those rows is a credit (today D&A, from the Amortization adjustment); ARR is month-to-date and customers are LTM (Beginning Customers is the count 12 months back, so it does not equal the prior month's Ending); the cash flow is mapped strictly to the view's cash-flow labels, consolidated over all subsidiaries (a dashboard filtered to one subsidiary will not match); Principal Payments and Revolver Size come from Finance's manual REVOLVER table and Drawn Revolver is the balance sheet MTD value of account 280360; figures are as the views stood at extraction (query ids are in the report).
- What changed from the template's own design: the two formula corrections (S&M and R&D SUMs), the rows that now read the views instead of template links or formulas (recurring bookings from GTM in Recurring Services, cash-flow Net Income, hosting, and Cash before Financing, Net Cash Flow, Beginning and Ending Cash from the view's labels), and the derived retention % and Renewal Rate % rows (LTM ratios, labelled in a cell note).

## Reference files

- `references/extract.md`: the ten queries, saving results, truncation, scope.
- `references/mapping.md`: row-by-row sources, sign conventions, blanks, derived rows, formula corrections, gates, refusals and what resolves them, why Excel used to repair the file and how it is prevented.
- `references/guardrails.md`: the guardrails in one place.
- `assets/chronograph_template.xlsx`: the cleaned template (pinned). `assets/chronograph_map.json`: the row map and gates. `config/scope.json`: database, schema, subsidiary exclusions, roll-up keys.
- `scripts/chronograph_queries.py` · `save_result.py` · `build_chronograph.py` · `check_workbook.py` (+ `excel_open_check.ps1`) · `clean_template.py` · `sql_guard.py` · `test_chronograph.py`. Run them; never re-implement them, and never hand-edit the template, the map or an output.
