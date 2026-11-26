# Local test mode

For testing when the Snowflake connection isn't available: the user uploads an Excel workbook whose sheets mirror the Finance view's logical tables, and the skill runs the same analysis over it with plain SQL. **Local results are test output, not governed answers.** Use this mode only when the user supplies a workbook or asks for a local test; if a live connector exists, use it.

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
python scripts/local_data.py check  uploads/book.xlsx [more.xlsx]          # whether the workbook supports the Finance view
python scripts/local_data.py load   uploads/book.xlsx --db work/local.db   # one table per sheet
python scripts/local_data.py schema --db work/local.db                     # tables, columns, row counts
python scripts/local_data.py query  --db work/local.db --file work/q.sql   # read-only, guard-checked, row-capped
```

1. Run `check`. If the Finance view comes back INCOMPLETE, say what's missing and answer only what the loaded sheets allow. Don't invent columns or fill gaps.
2. `load`, then `schema` to see the real column names. If the user's headers differ from §2, ask once for the mapping or rename in SQL (`SELECT col AS EXPECTED_NAME`); never guess a meaning.
3. Read `view-finance.md` for **hierarchy, rules and cautions**: they apply in local mode too. Ignore its `SEMANTIC_VIEW(...)` templates and use §4–5 here.
4. Query, answer, and build outputs exactly as in `SKILL.md` Steps 4–5, with the labelling in §6.
5. Probe first: `SELECT DISTINCT` the key members (`PERIOD`, `FINANCIAL_STATEMENT`, `COA_MAPPING_L3`) and the latest period with data, as in `semantic-views.md` §9.

For a first run without a client file, generate a synthetic workbook (invented data, internally consistent, with planted anomalies to find):

```bash
python scripts/make_sample_data.py            # writes assets/sample-data/finance_sample.xlsx
```

The shipped sample is ready to use: `assets/sample-data/finance_sample.xlsx`. Latest closed month in it is October 2026. **Never present sample figures as real.**

## 2. Workbook layout

One sheet per table, **row 1 = headers**, sheet and header names as below (case and spaces are normalised to `UPPER_SNAKE`). Sheets named `README…` or starting `_` are ignored. Extra sheets and columns are fine. `check` reports what's missing.

| View | Required sheets (columns) | Optional sheets |
|---|---|---|
| Finance | `ACCOUNT` (`CHART_OF_ACCOUNT_KEY`, `ACCOUNT_NAME`, `FINANCIAL_STATEMENT`, `COA_MAPPING_L1..L6` (`L5` / `L6` optional; the sample workbook carries them, with rows where L6 repeats L5 and a product line with no 2026 activity); for cash flow also `CASH_FLOW_L1..L3`), `PERIOD` (`ACCOUNTING_PERIOD_KEY`, `PERIOD`, `PERIOD_START_DATE`, `PERIOD_END_DATE`, `YEAR`), `SUBSIDIARY` (`SUBSIDIARY_KEY`, `SUBSIDIARY_NAME`), `INCOME_STATEMENT` (the three keys plus `MTD`, `QTD`, `YTD`, `LTM`, `PY_MTD`, `PY_YTD`, `BUDGET_MTD`, `BUDGET_YTD`, as the view carries them; only `MTD`, `PY_MTD`, `BUDGET_MTD` are used; optional `CLASS_NAME`, `DEPARTMENT_NAME` for the drill) | `GOVERNED` (`PERIOD_START_DATE`, `SUBSIDIARY_NAME`, `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD`: when present the dashboard build reconciles to it and refuses on a gap; when absent QC marks the check not run), `ACCOUNT.ACCOUNT_NUMBER`, `BALANCE_SHEET`, `CASH_FLOW` (keys plus `MTD`, `PY_MTD`, `BUDGET_MTD`), `TRANSACTIONS` (`TRANSACTION_ID`, `TRANSACTION_LINE_ID`, keys, `TRANSACTION_DATE`, `TRANSACTION_TYPE`, `AMOUNT`, `CUSTOMER_NAME`, `CURRENCY_CODE`) |

Dates load as ISO text (`YYYY-MM-DD`), TRUE/FALSE as 1/0. Compare dates with string comparison on ISO text.

A real export from the warehouse can be used as the workbook as long as it follows this layout. The finance marts hold one row per account × subsidiary × period, so the sheets will be large: filter to the periods needed before exporting.

## 3. What differs from governed mode

| Governed (Snowflake) | Local (workbook) |
|---|---|
| `SEMANTIC_VIEW(...)` applies metric logic | Plain SQL; you apply the formulas in §4 |
| Dimension joins defined in the view | You join on the keys in §2, many-to-one from fact to dimension |
| Sign conventions from the view | Whatever the workbook holds. **Check the sign of one known account before labelling variances.** The shipped finance sample uses revenue positive, expenses negative |
| Currency: converted reporting currency | Whatever the workbook holds; state it from the README or ask |
| Access control, row-level security | None. Don't upload client data to a place the user wouldn't normally share it |

The grain rules still apply: windows summed from `MTD` / `PY_MTD` / `BUDGET_MTD` over their months (never the `QTD` / `YTD` / `LTM` / `PY_YTD` / `BUDGET_YTD` columns), balances at one date, flows over a range, roll-up rows (`-8`, `-9`, `-3`, `-1000`) beside real accounts, never summing ratios.

## 4. Metric formulas in SQL

| Governed metric | Local SQL |
|---|---|
| `REVENUE_<w>`, `ADJUSTED_EBITDA_<w>`, `NET_INCOME_<w>` | `SUM(CASE WHEN CHART_OF_ACCOUNT_KEY = '-8' / '-9' / '-3' THEN MTD END)` on `INCOME_STATEMENT` joined to `PERIOD`, filtered to the window's months (one month for MTD; the quarter's, the year's or the last twelve for QTD / YTD / LTM) |
| `REVENUE_BUDGET_YTD` | sum of `BUDGET_MTD` over the window's months; prior year is the sum of `PY_MTD` over the same months |
| Costs and detail lines | `SUM(<w>)` joined to `ACCOUNT`, grouped by `COA_MAPPING_L3` / `L4` / `ACCOUNT_NAME`, with `CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-8','-9','-19','-100')` |
| `GROSS_MARGIN_MTD` | (revenue + cost of sales) ÷ revenue on MTD, signs as stored |
| `ENDING_BALANCE` | `SUM(MTD)` on `BALANCE_SHEET`, one period, filtered to an account or mapping |
| `ENDING_CASH_MTD`, `NET_CASH_FLOW_MTD` | `SUM(CASE WHEN CHART_OF_ACCOUNT_KEY = '-11' / '-12' THEN MTD END)` on `CASH_FLOW` |
| Cash flow section | `SUM(MTD)` on `CASH_FLOW` joined to `ACCOUNT`, grouped by `CASH_FLOW_L1/L2/L3`, summed over months for a quarter or YTD |

## 5. Verified example queries

These run on the shipped finance sample workbook (SQLite dialect). Replace literals with real members after probing.

```sql
-- P&L actual vs budget vs prior year for a month, by account category (real accounts only)
SELECT a.COA_MAPPING_L3, ROUND(SUM(i.MTD),0) AS actual, ROUND(SUM(i.BUDGET_MTD),0) AS budget, ROUND(SUM(i.PY_MTD),0) AS py
FROM INCOME_STATEMENT i
JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = i.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD = 'Oct 2026' AND a.FINANCIAL_STATEMENT = 'P&L' AND a.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-8','-9','-19','-100')
GROUP BY a.COA_MAPPING_L3 ORDER BY a.COA_MAPPING_L3;
```

```sql
-- Headline cards (YTD): revenue, budget, prior year, Adjusted EBITDA, net income
-- fiscal year to date, Feb–Oct 2026 = FY2027: MTD / BUDGET_MTD / PY_MTD summed over the window's months, never the YTD columns
SELECT SUM(CASE WHEN i.CHART_OF_ACCOUNT_KEY='-8' THEN i.MTD END) AS revenue_ytd,
       SUM(CASE WHEN i.CHART_OF_ACCOUNT_KEY='-8' THEN i.BUDGET_MTD END) AS revenue_budget_ytd,
       SUM(CASE WHEN i.CHART_OF_ACCOUNT_KEY='-8' THEN i.PY_MTD END) AS revenue_py_ytd,
       SUM(CASE WHEN i.CHART_OF_ACCOUNT_KEY='-9' THEN i.MTD END) AS ebitda_ytd,
       SUM(CASE WHEN i.CHART_OF_ACCOUNT_KEY='-3' THEN i.MTD END) AS net_income_ytd
FROM INCOME_STATEMENT i JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
WHERE p.YEAR = 2027 AND p.PERIOD_START_DATE <= '2026-10-01';
```

```sql
-- Top 5 variances by real account (subtotals excluded), largest absolute first
SELECT a.ACCOUNT_NAME, a.COA_MAPPING_L3, ROUND(SUM(i.MTD),0) AS actual, ROUND(SUM(i.BUDGET_MTD),0) AS budget,
       ROUND(SUM(i.MTD) - SUM(i.BUDGET_MTD),0) AS variance
FROM INCOME_STATEMENT i JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = i.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD = 'Oct 2026' AND a.FINANCIAL_STATEMENT = 'P&L' AND a.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-8','-9','-19','-100')
GROUP BY a.ACCOUNT_NAME, a.COA_MAPPING_L3 ORDER BY ABS(SUM(i.MTD) - SUM(i.BUDGET_MTD)) DESC LIMIT 5;
```

```sql
-- GL lines behind one account for a period, largest first, then tie to the mart (both must be equal)
SELECT t.TRANSACTION_ID, t.TRANSACTION_LINE_ID, t.TRANSACTION_DATE, t.TRANSACTION_TYPE, t.CUSTOMER_NAME, t.AMOUNT
FROM TRANSACTIONS t JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = t.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = t.ACCOUNTING_PERIOD_KEY
WHERE a.ACCOUNT_NAME = 'Marketing Programs' AND p.PERIOD = 'Oct 2026' AND t.CURRENCY_CODE = 'USD'
ORDER BY ABS(t.AMOUNT) DESC LIMIT 100;

SELECT (SELECT ROUND(SUM(t.AMOUNT),2) FROM TRANSACTIONS t JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = t.CHART_OF_ACCOUNT_KEY
        JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = t.ACCOUNTING_PERIOD_KEY
        WHERE a.ACCOUNT_NAME = 'Marketing Programs' AND p.PERIOD = 'Oct 2026') AS gl_total,
       (SELECT ROUND(SUM(i.MTD),2) FROM INCOME_STATEMENT i JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = i.CHART_OF_ACCOUNT_KEY
        JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
        WHERE a.ACCOUNT_NAME = 'Marketing Programs' AND p.PERIOD = 'Oct 2026') AS mart_total;
```

```sql
-- Cash flow by statement section, with ending cash alongside
SELECT p.PERIOD_END_DATE, a.CASH_FLOW_L1, ROUND(SUM(c.MTD),0) AS amount
FROM CASH_FLOW c JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = c.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = c.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD_END_DATE >= '2026-05-31' AND a.CASH_FLOW_L1 IN ('Cash from Operations','Cash from Investing','Cash from Financing')
GROUP BY p.PERIOD_END_DATE, a.CASH_FLOW_L1 ORDER BY 1, 2;

SELECT p.PERIOD_END_DATE, ROUND(SUM(c.MTD),0) AS ending_cash FROM CASH_FLOW c
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = c.ACCOUNTING_PERIOD_KEY
WHERE c.CHART_OF_ACCOUNT_KEY = '-11' GROUP BY p.PERIOD_END_DATE ORDER BY 1 DESC LIMIT 12;
```

```sql
-- Balance sheet at a month-end by line
SELECT a.COA_MAPPING_L2, a.COA_MAPPING_L3, ROUND(SUM(b.MTD),0) AS balance, ROUND(SUM(b.PY_MTD),0) AS prior_year
FROM BALANCE_SHEET b JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = b.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = b.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD = 'Oct 2026' AND a.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-8','-9','-19','-100') GROUP BY 1, 2 ORDER BY 1, 2;
```

## 6. Labelling rules

- Set `meta.data_mode` to `"local"` in the result bundle. Every output then carries a "LOCAL TEST DATA" banner, and the bundle **cannot** label a table `governed`: use `derived` (or `scenario`). `bundle.py` enforces this.
- In `meta.sources`, name the workbook file(s) and sheets, not the view. Do not write `PROD_DB.SEMANTIC_VIEWS...` for local data.
- The chat answer opens or closes with one line: "Local test data from <file>, not governed view output."
- Don't suggest the numbers match the governed view. They match only if the workbook was exported from it and the sign and currency conventions are the same.
- The guardrails apply unchanged: read-only, no raw dumps, row caps, honest gaps, no fabrication, Fact / Derived / Scenario labels.
