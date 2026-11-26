# Extract: the ten queries and how to save them

## Contents
1. The queries
2. Saving a result
3. Truncation and errors
4. Scope and conventions

---

## 1. The queries

`scripts/chronograph_queries.py` writes them for one as-of month and window; never write or change SQL by hand. All are monthly and consolidated (no subsidiary, customer or product grain). For 24 months the balance sheet is the largest (about 2,200 rows, account-level L4) and the P&L about 900.

| Name | View › table | Grain | Metrics | Feeds |
|---|---|---|---|---|
| `pl` | FINANCE_ANALYTICS › INCOME_STATEMENT | month × COA L2..L6 × `P_AND_L_MULTIPLIER` (P&L, roll-up keys out); L6 kept only under the L5s in `scope.json` `pl_l6_kept_under_l5` (S&M Expense, R&D), summed to L5 elsewhere | `TOTAL_MTD` (unsigned; the multiplier signs it) | P&L rows |
| `pl_governed` | FINANCE_ANALYTICS › INCOME_STATEMENT | month | `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD` | P&L gates, closed-month check |
| `bs` | FINANCE_ANALYTICS › BALANCE_SHEET | month × COA L1..L4 (BS, roll-up keys out) | `ENDING_BALANCE_CONVERTED` | balance sheet rows |
| `cf` | FINANCE_ANALYTICS › CASH_FLOW | month × CASH_FLOW_L1..L3 × COA L1, L3 | `TOTAL_MTD` | cash flow rows and gates (strict: rows only from the view's cash-flow labels); the COA levels name the rows the view leaves without a cash-flow label in the report |
| `arr` | ARR_ANALYTICS › ARR_BRIDGE | month-end × CATEGORY | `TOTAL_MTD`, `TOTAL_LTM` | ARR bridge, retention % |
| `customers` | ARR_ANALYTICS › CUSTOMER_BRIDGE | month-end × CATEGORY | `TOTAL_LTM` (each category against the count 12 months back) | customer bridge, Renewal Rate % |
| `bookings` | GTM_ANALYTICS › BOOKINGS_OVERVIEW | month-end | `RECURRING_BOOKINGS_MTD`, `NON_RECURRING_BOOKINGS_MTD`, `TOTAL_BOOKINGS_MTD` | bookings |
| `pipeline` | GTM_ANALYTICS › PIPELINE_OVERVIEW | as-at date (month-ends used) | `OPEN_PIPELINE_VALUE_MTD`, `WEIGHTED_PIPELINE_VALUE_MTD` | pipeline (the view has no coverage metric) |
| `revolver` | FINANCE_ANALYTICS › REVOLVER (Finance's manual table `PROD_DB.MANUAL.REVOLVER`) | `METRIC` × month start | `REVOLVER_AMOUNT` (USD; METRIC values are separate measures, never added) | Liquidity: $ Revolver Size, Principal Payments (METRIC Principal Payments, blank until Finance adds it) |
| `revolver_drawn` | FINANCE_ANALYTICS › BALANCE_SHEET | month, `ACCOUNT_NUMBER` = 280360 (`scope.json` `revolver_drawn_account`) | `ENDING_BALANCE_CONVERTED` | Liquidity: $ Drawn Revolver (the balance sheet MTD value of account 280360) |

The manifest (`work/queries/manifest.json`) records the as-of month, window, ARR basis, scope, each query's SHA-256 and the columns its result must carry. The build refuses a result with other columns.

## 2. Saving a result

Run each `.sql` file's text verbatim as one `sql-exec` call. Then:

- **The tool saved the result to a file** ("Output has been saved to …tool-results/…txt"): `python scripts/save_result.py <name> --file "<that path>"`.
- **The result came back inline** (a JSON object starting `{"query_id": …`): `python scripts/save_result.py <name> --query-id <query_id>`. It finds the result in the Claude Code session transcript and writes it unchanged.
- **save_result cannot find it** (no transcript in this environment): write the inline JSON to `work/raw/<name>.json` exactly as returned, with the file tool. Do not reformat, round, drop rows or retype numbers. The gates refuse an altered result, and the retention % rows, which no gate covers, are only right if the ARR result is saved unchanged.

`save_result.py` refuses anything that is not a complete sql-exec result.

## 3. Truncation and errors

- The build refuses a result whose `numRows` differs from the rows it holds, or whose partitions are not all present. Re-run the query and save the whole result. Do not narrow the query: these queries are already consolidated. (The connector returns only the first part of a very large result; that is why `pl` sums Kantata's account-level L6 to L5 outside S&M and R&D. If a result is cut off again, it is a skill-owner change, not a run-time workaround.)
- A query error (authorisation, missing object, timeout) is a result: report it with the view and query name and stop. Do not try DEV, another role or a raw table.
- An empty result for a month in the window is refused by the build ("no data for …"). Either the view has not loaded that month (choose an earlier as-of) or the month is outside the view's history (fewer months).

## 4. Scope and conventions

- Database and schema: `config/scope.json` (`PROD_DB.SEMANTIC_VIEWS`). `DEV_DB` only when the user asks; then edit nothing else.
- Subsidiaries: every subsidiary except `exclude_subsidiaries` (none today; same list as the finance skill). The exclusion applies to FINANCE_ANALYTICS and to bookings; ARR_ANALYTICS, pipeline and the revolver have no subsidiary dimension and cover every entity as stored (the REVOLVER table relates to no other table, so its query never carries a subsidiary filter). Say so at hand-over.
- Accounts: Kantata's five internal test accounts (`config/scope.json` `exclude_accounts`) are excluded in every run, by 18-character Salesforce account ID only (never by name: real customers whose names contain "test" stay in). When the user explicitly lists more Salesforce account IDs, `chronograph_queries.py --exclude-accounts` / `--exclude-accounts-file` adds them. All of them go into one null-safe `NOT IN` on `CUSTOMER.ACCOUNT_ID` in `arr` and `customers` and on `DIM_ACCOUNT.ACCOUNT_ID` in `bookings` and `pipeline` (rows with no account, NetSuite non-recurring bookings, are kept). The four finance queries and `revolver` never change: FINANCE_ANALYTICS has no Salesforce account. IDs must be the 18-character form the views store; anything else is refused before a query is written. The list is recorded in the manifest (`exclude_accounts`, split into `exclude_accounts_default` and `exclude_accounts_requested`), the build report (`scope.excluded_accounts`) and the file's document properties. Say at hand-over that ARR and revenue then sit on different customer bases.
- Currency: Finance uses the converted (reporting-currency) columns. ARR is USD as ARR_ANALYTICS stores it (one basis; the view has no actual-rate or constant-currency variant), as a month-to-date bridge; the customer bridge is LTM counts. The revolver is USD as Finance enters it. Bookings and pipeline are booking ACV in USD.
- Pipeline is a month-end snapshot; the view's history starts later than the other sources (today February 2025). Earlier months in the window are blank and reported, not refused.
- Months: Finance is keyed by fiscal `PERIOD_START_DATE` and the revolver by `MONTH_START_DATE`; ARR, customers, bookings and pipeline by month-end date. The build aligns them by calendar month. Pipeline's "today" row is not a month-end and is ignored. No query reads a quarter- or year-to-date column (the view's fiscal year starts 1 February), so the Feb–Jan fiscal year changes no value in the workbook.
- Roll-up keys excluded from P&L and BS: `config/scope.json` `rollup_keys`.
