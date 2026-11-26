# Extract: the nine queries and how to save them

## Contents
1. The queries
2. Saving a result
3. Truncation and errors
4. Scope and conventions

---

## 1. The queries

`scripts/chronograph_queries.py` writes them for one as-of month and window; never write or change SQL by hand. All are monthly and consolidated (no subsidiary, customer or product grain). For 24 months the balance sheet is the largest (about 2,400 rows, account-level L4, mostly the individual bank accounts under Cash & Equivalents) and the P&L about 720.

| Name | View › table | Grain | Metrics | Feeds |
|---|---|---|---|---|
| `pl` | FINANCE_ANALYTICS › INCOME_STATEMENT | month × COA L2..L6 × `P_AND_L_MULTIPLIER` (P&L, roll-up keys out); L6 kept only under the L5s in `scope.json` `pl_l6_kept_under_l5` (S&M Expense, R&D), summed to L5 elsewhere | `TOTAL_MTD` (unsigned; the multiplier signs it) | P&L rows |
| `pl_governed` | FINANCE_ANALYTICS › INCOME_STATEMENT | month | `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD` | P&L gates, closed-month check |
| `bs` | FINANCE_ANALYTICS › BALANCE_SHEET | month × COA L1..L4 (BS, roll-up keys out) | `ENDING_BALANCE_CONVERTED` | balance sheet rows |
| `cf` | FINANCE_ANALYTICS › CASH_FLOW | month × CASH_FLOW_L1..L3 × COA L1, L3 | `TOTAL_MTD` | cash flow rows and gates (every Yes Energy cash-flow row carries a label; the COA levels are kept so a future unlabelled row is caught) |
| `arr` | ARR_ANALYTICS › ARR_WATERFALL | month-end (`ARR_MONTH_END`, returned as `MONTH_END_DATE`) × CATEGORY (Beginning ARR, New, Churn, Upsell, Downsell, FX, Ending ARR, Gross / Net Dollar Retention) | `TOTAL_MTD`, `TOTAL_LTM` | ARR bridge, retention % |
| `customers` | ARR_ANALYTICS › CUSTOMER_BRIDGE | month-end (`ARR_MONTH_END`, returned as `MONTH_END_DATE`) × CATEGORY | `TOTAL_MTD` | customer bridge |
| `bookings` | GTM_ANALYTICS › BOOKINGS_OVERVIEW | month-end | `ARR_NEW_MTD`, `ARR_UPSELL_MTD`, `RECURRING_BOOKINGS_MTD`, `NON_RECURRING_BOOKINGS_MTD`, `TOTAL_BOOKINGS_MTD` | bookings |
| `hosting` | FINANCE_ANALYTICS › INCOME_STATEMENT | month × BUCKET (COGS where COA L3 = Cost of Sales, R&D otherwise) × `P_AND_L_MULTIPLIER`, for `ACCOUNT.ACCOUNT_NUMBER` in `scope.json` `hosting_accounts` | `TOTAL_MTD` (unsigned; no adjustment-type filter) | Hosting/Cloud Costs (COGs) and (R&D) memo rows |
| `pipeline` | GTM_ANALYTICS › PIPELINE_OVERVIEW | as-at date (month-ends used) | `OPEN_PIPELINE_VALUE_MTD`, `WEIGHTED_PIPELINE_VALUE_MTD` | pipeline (the view has no coverage metric) |

The manifest (`work/queries/manifest.json`) records the as-of month, window, ARR basis, scope, each query's SHA-256 and the columns its result must carry. The build refuses a result with other columns.

## 2. Running and saving the results

**In Cortex Code in Snowsight (default):** `python scripts/run_queries.py --work work [--warehouse <WH>]`. It checks each `.sql` file against the SHA-256 in the manifest, runs it verbatim on the sandbox's Snowflake connection, and writes the complete result to `work/raw/<name>.json` in the sql-exec shape the build reads, with the real query id. Numbers are kept as the exact decimal strings Snowflake returns. If the connection has no active warehouse it refuses and lists the visible ones; the user chooses, and the run is repeated with `--warehouse`.

**Elsewhere, with only a SQL tool:** run each `.sql` file's text verbatim as one call, then:
- the tool saved the result to a file: `python scripts/save_result.py <name> --file "<that path>"`;
- the result came back inline: `python scripts/save_result.py <name> --query-id <query_id>` (finds it in a Claude Code session transcript).

`save_result.py` refuses anything that is not a complete sql-exec result. Never write a result by hand.

## 3. Truncation and errors

- The build refuses a result whose `numRows` differs from the rows it holds, or whose partitions are not all present. Re-run the query and save the whole result. Do not narrow the query: these queries are already consolidated. (The connector returns only the first part of a very large result; that is why `pl` sums to L5 everywhere except the L6 under S&M and R&D. If a result is cut off again, it is a skill-owner change, not a run-time workaround.)
- A query error (authorisation, missing object, timeout) is a result: report it with the view and query name and stop. Do not try DEV, another role or a raw table.
- An empty result for a month in the window is refused by the build ("no data for …"). Either the view has not loaded that month (choose an earlier as-of) or the month is outside the view's history (fewer months).

## 4. Scope and conventions

- Database and schema: `config/scope.json` (`PROD_DB.SEMANTIC_VIEWS`). `DEV_DB` only when the user asks; then edit nothing else.
- Subsidiaries: every subsidiary except `exclude_subsidiaries` (none today; same list as the finance skill). The exclusion applies to FINANCE_ANALYTICS and to bookings; ARR_ANALYTICS and pipeline have no subsidiary dimension and cover every entity as stored. Say so at hand-over.
- Accounts: every account by default. When the user explicitly lists Salesforce account IDs, `chronograph_queries.py --exclude-accounts` / `--exclude-accounts-file` adds a null-safe `NOT IN` on `DIM_ACCOUNT.ACCOUNT_ID` to `bookings` and `pipeline` (rows with no account, NetSuite non-recurring bookings, are kept). The four finance queries and `arr` / `customers` never change: FINANCE_ANALYTICS has no Salesforce account, and ARR_ANALYTICS keys its unified customer by `YES_ENERGY_CUSTOMER_ID` / `RTO_INSIDER_ID`, not a Salesforce account. IDs must be the 18-character form the views store; anything else is refused before a query is written. The list is recorded in the manifest, the build report (`scope.excluded_accounts`) and the file's document properties. Say at hand-over that bookings and pipeline then sit on a different customer base from ARR and revenue.
- Currency: Finance uses the converted (reporting-currency) columns. ARR is USD as ARR_ANALYTICS stores it (one basis; the view has no actual-rate or constant-currency variant), as a month-to-date bridge across every Maxio system (Yes Energy, RTO, APAC, EMEA), each customer counted once; the currency movement on non-USD ARR is its own FX category. The bridge is at customer grain, so it cannot be sliced by product. Bookings and pipeline are booking ACV in USD.
- Pipeline is a month-end snapshot; today its history starts January 2024, so a 24-month window is fully covered. Months before the history are blank and reported, not refused.
- Months: Finance is keyed by fiscal `PERIOD_START_DATE`; ARR, customers, bookings and pipeline by month-end date. The build aligns them by calendar month. Pipeline's "today" row is not a month-end and is ignored. No query reads a quarter- or year-to-date column. Yes Energy's NetSuite fiscal year is the calendar year (PERIOD.MONTH 1 = January), so fiscal and calendar months are the same.
- Hosting accounts: `config/scope.json` `hosting_accounts` (61200 Cloud, 61300 Managed Hosting, 61400 Server Equipment, 61500 Server Software, 61502 DR/HA Solution, 61600 Database Monitoring/Admin, 61700 DS Hard/Software Fees), set by Yes Energy finance. Only the skill owner changes the list.
- Roll-up keys excluded from P&L and BS: `config/scope.json` `rollup_keys` (Gross Profit, Gross Profit %, Total Revenue, Adjusted EBITDA (%), Net Income (%), PF Adjusted EBITDA, Total Debt). Keys -8001 / -8002 / -8003 (capitalised software, commissions and their reversal) and -20001 / -20002 / -20003 (retained earnings, cumulative translation adjustment, current-year net income) are real rows and stay in.
