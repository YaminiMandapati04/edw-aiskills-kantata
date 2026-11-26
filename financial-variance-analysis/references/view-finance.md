# Finance Analytics (`FINANCE_ANALYTICS`)

NetSuite general-ledger view. Two ways in: **pre-aggregated statement marts** for fast standard-calendar answers, and a **live GL fact** for drill-down. Picking the wrong layer is the main way to get a wrong answer.

Read `semantic-views.md` first for conventions, rules and the "words users say" table.

**Deployed definition.** `PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS`, checked with `GET_DDL` on 17-Nov-2026: 13 logical tables, 24 relationships, the 33 + 11 + 6 + 6 metrics below. Marts read `PROD_DB.REPORTING.RPT_*`; the GL fact and every dimension read `PROD_DB.GOLD.*`. The `DEV_DB` copy is identical apart from the database name. Hierarchy members and negative keys below were probed in PROD the same day.

## Contents
1. Choose the layer
2. Logical tables and grain
3. Joins and hierarchies
4. Metrics and derived KPIs
5. Query templates
6. Answer ladders
7. Dashboard coverage
8. Cautions

---

## 1. Choose the layer

| Layer | Tables | Use when | Not for |
|---|---|---|---|
| Statement marts | `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW` | Standard-calendar MTD, QTD, YTD, LTM, prior-year and **budget** lookups; fast; the default for "how are we doing" | Anything that must trace to transactions (every mart metric is NOT drillable); custom date ranges |
| Live GL | `TRANSACTIONS` | "What transactions made up X", custom date ranges, AR/AP open items, by customer / location / currency | Budget comparisons (no budget on this table) |

Don't combine mart and GL metrics in one query; they meet only through shared dimensions. **Always answer from the mart first and drill to the GL second**, and tie the GL back to the mart number.

On the **live GL**, metrics are either **cumulative** (balances: filter `PERIOD_START_DATE <= :date`, summed since inception) or **flow** (activity: filter to *exactly* the requested range). Using the wrong filter shape gives a wrong number. "YTD revenue" on the GL sums only that year's periods.

On the **marts**, **use only the `_MTD` columns** (`TOTAL_MTD`, `REVENUE_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD` …). For a flow, filter `PERIOD` to the window's months and sum: MTD = the as-of month; fiscal QTD = the months of the same `PERIOD.YEAR` and `QUARTER` up to the as-of period; fiscal YTD = every month of the as-of `PERIOD.YEAR` up to it (the fiscal year is the calendar year); LTM = the last twelve months. Prior year and budget for any window are `TOTAL_PY_MTD` / `TOTAL_BUDGET_MTD` summed over the same months. **Never use or roll up the marts' `_QTD` / `_YTD` / `_LTM` columns or their PY / budget twins:** each is tagged to the account keys present in that one month, so keys that posted in an earlier month but not in the month queried drop out and the window comes out incomplete (checked live, Oct-2026 consolidated: the view's `ADJUSTED_EBITDA_YTD` 10.45mn against 7.72mn from the calendar Jan–Oct `_MTD` months; `NET_INCOME_LTM` 66.36mn against 17.08mn; `REVENUE_LTM` 105.33mn against 107.04mn). Balance-sheet balances are the exception: read them at one date (`ENDING_BALANCE*` at the as-of period); a balance-sheet `_MTD` is a month-end balance and is never summed across months.

## 2. Logical tables and grain

| Table | Base | One row is | Notes |
|---|---|---|---|
| `INCOME_STATEMENT` | `REPORTING.RPT_INCOME_STATEMENT` | account × class × department × subsidiary × accounting book × period | MTD, QTD, YTD, LTM, prior-year, budget columns; only the `_MTD` ones are used (§1). Not drillable. |
| `BALANCE_SHEET` | `REPORTING.RPT_BALANCE_SHEET` | same keys | Month-end balance (`MTD`, `CONVERTED_MTD`), budget, prior year (plain and converted). Not drillable. |
| `CASH_FLOW` | `REPORTING.RPT_CASH_FLOW` | same keys plus currency | Monthly only: `MTD`, `CONVERTED_MTD`, `PY_MTD`, `PY_CONVERTED_MTD`, `BUDGET_MTD`. Every cash-flow metric reads the converted columns. |
| `TRANSACTIONS` | `GOLD.FACT_TRANSACTION` | one GL transaction line | Raw `AMOUNT`, `OPEN_AMOUNT`, `QUANTITY`. Drillable. |
| `ACCOUNT` | `GOLD.DIM_COA` | one account | Real accounts plus negative-key rows (roll-ups, equity plugs; §3). |
| `PERIOD` | `GOLD.DIM_ACCOUNTING_PERIOD` | one fiscal period | `PERIOD_START_DATE` drives cumulative and flow filters. |
| `CALENDAR` | `GOLD.DIM_DATE` | one calendar day | Joins `TRANSACTIONS.TRANSACTION_DATE` only. |
| `SUBSIDIARY`, `DEPARTMENT`, `CLASSIFICATION` | `GOLD.DIM_SUBSIDIARY`, `DIM_DEPARTMENT`, `DIM_CLASS` | one member | Marts and GL both reach these. |
| `LOCATION`, `CURRENCY`, `CUSTOMER` | `GOLD.DIM_LOCATION`, `DIM_CURRENCY`, `DIM_ENTITY` | one member | **GL only.** `CUSTOMER` is the entity (customer, vendor, counterparty) via `CUSTOMER_KEY → ENTITY_KEY`; `CUSTOMER_NAME` is `ENTITY_TITLE`. |

`ACCOUNTING_BOOK_KEY` is in the mart keys but no book dimension is exposed (open item 2).

## 3. Joins and hierarchies

```
INCOME_STATEMENT --+
BALANCE_SHEET -----+--> ACCOUNT (CHART_OF_ACCOUNT_KEY), PERIOD (ACCOUNTING_PERIOD_KEY),
CASH_FLOW ---------+    SUBSIDIARY, DEPARTMENT, CLASSIFICATION
TRANSACTIONS ------> the same five, plus LOCATION, CURRENCY, CUSTOMER, CALENDAR (TRANSACTION_DATE -> DATE)
```

Marts cannot be sliced by location, currency, customer or calendar date. "Revenue by customer" or "by location" must go to the GL.

**Hierarchies, top to bottom**

| Hierarchy | Levels | Notes |
|---|---|---|
| Chart of accounts (GAAP) | `FINANCIAL_STATEMENT` (P&L or BS) › `COA_MAPPING_L1` › `L2` › `L3` › `L4` › `L5` › `L6` › `ACCOUNT_NUMBER` / `ACCOUNT_NAME` (within `SUBSIDIARY_NAME`) › `CLASS_NAME` › `TRANSACTION_ID` / `TRANSACTION_LINE_ID` | Members as stored in PROD (the view's column comments are older and differ; trust these). **Balance sheet:** L1 `Assets` › L2 `Current Assets` (L3 `Cash & Equivalents`, `Accounts Receivable`, `Other Current Assets`), `Non-Current Assets` (L3 `Goodwill & Intangibles`, `Net Capitalized Software`, `Net Fixed Assets`, `Other Non-Current Assets`); L1 `Total Liabilities & Share Holder Equity` › L2 `Liabilities` › L3 `Current Liabilities` (L4 `Accounts Payable`, `Accrued Expenses`, `Accrued Interest`, `Deferred Revenue`, `Other Current Liabilities`, `Short Term Debt`), L3 `Long-Term Liabilities` (L4 `Senior Debt`, `Subordinate Debt`, `Other Long-Term Liabilities`); L2 `Equity` › L3 `Total Equity` (L4 `Members' Equity`). So current and long-term liabilities are **L3**, and AP, deferred revenue and debt are **L4**. **P&L:** L1 `Net Income` › L2 `Adjusted EBITDA` (L3 `Revenue`, `Cost of Sales`, `Operating Expenses`) and `Total Non-Operating Income (Expense)` (L3 repeats L2; L4 `Depreciation & Amortization`, `Interest Expense`, `Interest Income`, `Income Taxes`, `Other Non-Operating Income & Expense`, `Reversal of Capitalized Portions`). L4 under Revenue: `Recurring Revenue`, `Non-Recurring Revenue`; under Cost of Sales: `Recurring COGs`, `Non-Recurring COGs` (lower-case s); under OpEx: `Fully loaded S&M Expense`, `Fully loaded R&D`, `Total G&A`. There is no `Synergies and Strategic Investments` L2 in the data, and no `COGS`, `OpEx`, `Depreciation`, `Interest` or `Taxes` L3. |
| Cash flow statement | `CASH_FLOW_L1` › `L2` › `L3` | L1: Cash from Operations, Investing, Financing, FX Change, plus labels Beginning Cash, Ending Cash, Net Cash Flow, Cash before Financing. L2 e.g. Change in Working Capital, Capital Expenditures, Change in Debt. L3 mirrors L2 except Income from Operations splits into Net Income and Total Non-Cash Items. `CASH_FLOW_SORT_L1..L3` are display order only, never filters. |
| Fiscal time | `PERIOD.YEAR` › `QUARTER` › `MONTH` (`PERIOD`, `PERIOD_START_DATE`, `PERIOD_END_DATE`) | Marts and GL both. Fiscal year = calendar year (Jan 2026 = YEAR 2026, QUARTER 1). Sum `_MTD` by `YEAR` / `QUARTER` for fiscal windows; the marts' `_QTD` / `_YTD` / `_LTM` metrics are not used (§1). |
| Calendar time (GL only) | `CALENDAR.YEAR` › `QUARTER_YEAR` › `MONTH_YEAR` › `DATE` | Custom ranges on `TRANSACTION_DATE`. |
| Organisation | `SUBSIDIARY_FULL_NAME` / `SUBSIDIARY_NAME`; `DEPARTMENT_FULL_NAME` › `DEPARTMENT_NAME`; `LOCATION_FULL_NAME` › `LOCATION_NAME`; `CLASS_NAME` | Full-name columns carry the path (`DEPARTMENT_FULL_NAME` e.g. `Sales & Marketing : 200 - Sales`). Department and class split the income-statement metrics, budget and prior year included. Depth is not exported: probe members before promising a level. |

**Account grain.** `CHART_OF_ACCOUNT_KEY` is **account x class**, not the account: one account can carry several keys (one per class, including a blank class), and the budget often sits on the blank-class key only. Rank, sum and compare at **account number + name within subsidiary**, with class (and department) beneath it as drill detail; compare against budget at the budget's own grain (summed across classes, and across subsidiaries where the budget is held on one entity). Comparing key by key manufactures variances: the blank-class key alone can show a large shortfall against the full budget while the account as a whole is close to it.

**Below L4.** `COA_MAPPING_L5` and `L6` are live (confirmed 16-Nov-2026). Revenue: L4 Recurring Revenue › L5 `SaaS - Subscription` › L6 product lines (`<product> - recurring`); L4 Non-Recurring Revenue › L5 `One-time Services` (L6 `<product>`) and `Perpetual License` (L6 `<product> - Licenses`, `License Revenue`). Probe the live product-line names before quoting them. Cost of sales: L4 Recurring COGs › L5 `Operational Services` / `Royalties` / `Web Hosting`. OpEx: Fully loaded S&M Expense › `S&M Expense` › `Sales Expense` / `Marketing Expense` / `Other S&M Expense`; Fully loaded R&D › `R&D` › `Engineering Expense` / `Product Expense` / `Other R&D Expense`; Total G&A › `Finance Department` / `HR Department` / `IT Department` / `Other G&A Spend`. Non-operating: Other Non-Operating Income & Expense › `Management & AKKR / ACG Fees` / `Severance` / `Transaction Costs` / `Transition & Integration Costs` / `Other Items`; D&A, interest and taxes repeat L4 at L5 and L6. **L6 = L5 means no further split**: never show it as an extra step or a duplicate row. Members with no activity in a window are left out, never zero-filled. The dashboard carries the levels under each driver (L4 › L5 › L6 › account) and shows revenue by product line.

**Negative keys: roll-ups and real rows** (`CHART_OF_ACCOUNT_KEY`, stored as text)

Two kinds of rows sit on negative keys. The **summary roll-ups** below are subtotals; the list is in `config/scope.json` (`rollup_keys`). Which keys carry rows depends on the mart (PROD, probed 17-Nov-2026):

| Mart | Roll-up keys present | Real rows on negative keys (keep them) |
|---|---|---|
| `INCOME_STATEMENT` | `-8` revenue, `-9` Adjusted EBITDA, `-19` PF Adjusted EBITDA, `-3` net income, `-6` gross profit, `-1` / `-100` recurring / non-recurring gross profit | `-8001` Capitalised Software, `-8002` Capitalised Commissions, `-8003` Reversal of Capitalised Portions (`config/scope.json` `capitalisation_keys`; §3a) |
| `BALANCE_SHEET` | `-1000` total debt | `-20001` Retained Earnings, `-20002` Cumulative Translation Adjustment, `-20003` Net Income (all L2 `Equity`) |
| `CASH_FLOW` | `-10` beginning cash, `-11` ending cash, `-12` net cash flow, `-27` cash before financing | `-3` **Net Income** (the `Cash from Operations` › `Income from Operations` › `Net Income` line), `-20002` FX (`Effect of Exchange Rate on Cash`) |

**Not in any mart:** `-4`, `-5` and `-15` have no rows (and no `ACCOUNT` row), so `TOTAL_EQUITY_MTD`, `TOTAL_LIABILITIES_AND_EQUITY_MTD` and their converted twins **return 0**. `ACCOUNT` also holds `-2`, `-13`, `-14` (gross profit %, EBITDA %, net income % placeholders) and `-26001` Subordinate Debt with no mart rows.

To rank or sum accounts on the **income statement or balance sheet**, exclude **the roll-up keys only**: `ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-6','-8','-9','-10','-11','-12','-15','-19','-100','-1000')`. Never `NOT LIKE '-%'`: on the balance sheet it drops retained earnings and the other equity rows. On the **cash-flow mart** that list is wrong: `-3` is the Net Income line of operating cash flow there, and `-27` is a roll-up it misses. Use `NOT IN ('-10','-11','-12','-27')` instead, or group by `CASH_FLOW_L1` and drop the label sections (`Beginning Cash`, `Ending Cash`, `Net Cash Flow`, `Cash before Financing`). A negative key that is in none of these lists is unknown: probe it before using the data. To read a headline roll-up, use the dedicated metric (`REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`), not a manual filter.

## 3a. Manual adjustments (`INCOME_STATEMENT.ADJUSTMENT_TYPE`)

Probed live 23-Nov-2026. Each adjustment type is its own row in `INCOME_STATEMENT`, so `TOTAL_MTD` and every headline metric include them. The view's instruction is **never exclude them; state which are included and their impact**.

- **Manual adjustments are part of the governed figures; never exclude them, always name them.** `INCOME_STATEMENT.ADJUSTMENT_TYPE` is NULL on ordinary actuals and budget and carries three adjustment types:
  - **i. Pro forma**: `Pro Forma Actuals` (actuals of acquired businesses before they joined the ledger, on ordinary accounts with a subsidiary: revenue, COGS, opex and below EBITDA) and `Pro Forma Adjustments` (pro forma reclasses between cost lines, close to nil in total).
  - **ii. Capitalised expenses and their reversal** (`Adjustment for Capitalized expenses`, no subsidiary): `-8001` **Capitalised Software** (in Fully loaded R&D) and `-8002` **Capitalised Commissions** (in Fully loaded S&M) charge the capitalised cost inside Adjusted EBITDA; `-8003` **Reversal of Capitalised Portions** (L4 `Reversal of Capitalized Portions`, below EBITDA) reverses it. The pair moves Adjusted EBITDA (lower) and nets to zero at net income. The 2026 budget carries the capitalisation on the same keys with no adjustment type.
  - Say which adjustments are in the window and their effect on revenue, Adjusted EBITDA and net income (`GROUP BY INCOME_STATEMENT.ADJUSTMENT_TYPE`). A movement on `-8001` / `-8002` / `-8003` is an accounting treatment, never a cost saving, overspend or operating improvement. PF Adjusted EBITDA (`PF_ADJUSTED_EBITDA_MTD`, key `-19`) equals Adjusted EBITDA in PROD today; quote it only when asked.
  - The balance-sheet and cash-flow marts already exclude all three adjustment types.

Live sizes (consolidated, actuals): Dec-2025 Adjusted EBITDA $1.78mn ordinary + $0.62mn pro forma actuals − $2.29mn capitalisation = $0.10mn; net income moves only by the pro forma actuals ($0.44mn), because the capitalisation nets to zero. FY2025: capitalisation −$3.16mn on Adjusted EBITDA (Software −$1.17mn in Dec-2025; Commissions −$1.99mn across the year).

```sql
-- Which adjustments are in a window, and their effect (sum the months; never the _YTD columns)
SELECT ADJUSTMENT_TYPE, SUM(REVENUE_MTD) AS revenue, SUM(ADJUSTED_EBITDA_MTD) AS adjusted_ebitda, SUM(NET_INCOME_MTD) AS net_income
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS INCOME_STATEMENT.ADJUSTMENT_TYPE, PERIOD.PERIOD_START_DATE
  METRICS    INCOME_STATEMENT.REVENUE_MTD, INCOME_STATEMENT.ADJUSTED_EBITDA_MTD, INCOME_STATEMENT.NET_INCOME_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '<first month>' AND '<as-of month>'
)
GROUP BY ADJUSTMENT_TYPE ORDER BY ADJUSTMENT_TYPE NULLS FIRST;
```

On the GL layer the same rows are `TRANSACTIONS_AND_ADJUSTMENTS.SOURCE_TYPE = 'ADJUSTMENT'` (always USD, no accounting book). Their `MEMO` is NULL, so they are explained by type and account, never by memo. The related ordinary GL entry often carries the memo: for example the asset-side "Establish Capitalized Software Development" entries on account 14700 and its contra 70830.

## 4. Metrics and derived KPIs

**Income statement mart (33 metrics)**

| Family | Metrics | Notes |
|---|---|---|
| Revenue | `REVENUE_MTD` (also `_QTD`, `_YTD`, `_LTM`, `REVENUE_PY_YTD`, `REVENUE_BUDGET_YTD`: not used, §1) | Only `_MTD` is used. Any window = `REVENUE_MTD` summed over its months; prior year and budget = `TOTAL_PY_MTD` / `TOTAL_BUDGET_MTD` on the revenue lines summed over the same months |
| Adjusted EBITDA | `ADJUSTED_EBITDA_MTD` (also `_QTD`, `_YTD`, `_LTM`, `ADJUSTED_EBITDA_BUDGET_YTD`: not used, §1) | Only `_MTD` is used, summed over the window's months |
| Net income | `NET_INCOME_MTD` (also `_YTD`, `_LTM`: not used, §1) | Only `_MTD` is used, summed over the window's months |
| Margins (MTD only) | `GROSS_MARGIN_MTD`, `EBITDA_MARGIN_MTD`, `NET_INCOME_MARGIN_MTD` | Ratios to revenue. Other windows: divide matching `TOTAL_*` figures. |
| Recurring split | `RECURRING_GROSS_PROFIT_MTD`, `NON_RECURRING_GROSS_PROFIT_MTD` | via `COA_MAPPING_L4` |
| Generic totals | `TOTAL_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD` (the `_QTD` / `_YTD` / `_LTM` twins exist but are not used, §1) | Sum of all rows in scope: **always slice by the account hierarchy** (L2, L3, L4, account); windows are these summed over the window's months |

**Balance sheet mart (11):** `ENDING_BALANCE`, `_BUDGET`, `_PY`, `_CONVERTED`, `_PY_CONVERTED`; `TOTAL_DEBT_MTD`, `TOTAL_EQUITY_MTD`, `TOTAL_LIABILITIES_AND_EQUITY_MTD` and their `_CONVERTED_MTD` twins. Filter to an account, GAAP mapping or type, or it double-counts. **`TOTAL_EQUITY_*` and `TOTAL_LIABILITIES_AND_EQUITY_*` return 0 in PROD** (their keys `-5` / `-4` have no rows). Derive them instead: equity = `ENDING_BALANCE_CONVERTED` with `COA_MAPPING_L2 = 'Equity'`; liabilities + equity = the same with `COA_MAPPING_L1 = 'Total Liabilities & Share Holder Equity'`. For Oct-26 that is $126.5mn and $289.5mn, which ties to total assets ($289.5mn). `TOTAL_DEBT_MTD` works but reads the unconverted `MTD` column and is stored negative (($92.4mn) Oct-26).

**Cash flow mart (6):** `BEGINNING_CASH_MTD`, `ENDING_CASH_MTD`, `NET_CASH_FLOW_MTD`, `TOTAL_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD`. Monthly only. Ending cash = beginning cash + net cash flow + FX (`-20002`): FX is outside `NET_CASH_FLOW_MTD` (Oct-26: $21.13mn + ($3.58mn) + ($0.59mn) = $16.96mn). The cash-flow bridge lives on this mart via `ACCOUNT.CASH_FLOW_L1..L3`; there are no `TRANSACTIONS.CASH_FLOW_*` metrics, whatever the table comment says.

**Live GL (`TRANSACTIONS`, six metrics in the export)**

| Metric | Use for |
|---|---|
| `TOTAL_DEBT` | Total debt, cumulative; raw transaction-currency amount, deliberately not filtered by posting flag or status |
| `TOTAL_OPEN_AMOUNT` | AR / AP ageing and unpaid balances |
| `TOTAL_TRANSACTION_CURRENCY_AMOUNT` | Line-level amounts; **valid only when filtered to a single currency** |
| `TRANSACTION_COUNT`, `TRANSACTION_LINE_COUNT` | How many documents / GL lines |
| `TOTAL_QUANTITY` | Units on GL lines |

The view description, the table comments and the `PERIOD_START_DATE` comment also name `REVENUE`, `GROSS_PROFIT`, `ADJUSTED_EBITDA`, `NET_INCOME`, `TOTAL_ASSETS`, `AR`, `AP`, `CASH_BALANCE`, `WORKING_CAPITAL`, `CURRENT_RATIO`, `NET_DEBT` and the `CASH_FLOW_*` bridge on `TRANSACTIONS`. **They are not defined in the PROD view** (DDL checked 17-Nov-2026: these six are the only `TRANSACTIONS` metrics). Don't query them; build the figure from the marts or from `TOTAL_TRANSACTION_CURRENCY_AMOUNT` on a single currency.

**Derived KPIs**

| KPI | How | Basis |
|---|---|---|
| Variance vs budget | `TOTAL_MTD` − `TOTAL_BUDGET_MTD` on the same slice, each summed over the window's months | mart, derived |
| Variance % and favourable / adverse | Variance ÷ budget. **Confirm the stored sign on an expense row** before labelling (open item 9). | derived |
| YoY growth | window ÷ `TOTAL_PY_MTD` summed over the same months − 1 | derived |
| Gross, EBITDA, net margin | MTD metrics; other windows ratio of `TOTAL_*` on matching slices | mart / derived |
| Working capital | `ENDING_BALANCE_CONVERTED`, `COA_MAPPING_L2` = Current Assets − `COA_MAPPING_L3` = Current Liabilities (liabilities are stored positive) | derived |
| Current ratio | Current Assets (L2) ÷ Current Liabilities (L3) | derived |
| Net debt | Debt (`ACCOUNT.DEBT_MAPPING = 1`: L4 `Short Term Debt`, `Senior Debt`, `Subordinate Debt`) − cash (`COA_MAPPING_L3` = `Cash & Equivalents`), both from `ENDING_BALANCE_CONVERTED`; `TOTAL_DEBT_MTD` is unconverted and negative | derived |
| Total equity, liabilities + equity | `ENDING_BALANCE_CONVERTED` by `COA_MAPPING_L2` = Equity / `COA_MAPPING_L1` = Total Liabilities & Share Holder Equity (the stored metrics return 0) | derived |
| FCF, cash conversion | Cash from Operations − CapEx (`CASH_FLOW_L2`) ÷ Adjusted EBITDA; two queries, two marts, summed over the same months | derived |
| Cash volatility | monthly Cash from Operations over ≥12 (prefer 24) periods: mean, std dev, CV, min, max | derived (see playbook §5) |
| AR / AP ageing | `TOTAL_OPEN_AMOUNT` by `DUE_DATE`, `CUSTOMER_NAME` | GL |

## 5. Query templates

Qualifiers are the logical-table names. Quoted literals are **examples**: probe the real member values first (`semantic-views.md` §9).

```sql
-- P&L: actual vs budget vs prior year for one month, by account category (real accounts only)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3
  METRICS    INCOME_STATEMENT.TOTAL_MTD, INCOME_STATEMENT.TOTAL_BUDGET_MTD, INCOME_STATEMENT.TOTAL_PY_MTD
  WHERE      PERIOD.PERIOD = '<period as stored>'
         AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-8','-9','-10','-11','-12','-15','-19','-100','-1000')   -- roll-ups only
) ORDER BY COA_MAPPING_L2, COA_MAPPING_L3;
```

```sql
-- Revenue by product line by month (L6; L5 named because a product can sit under more than one L5); roll-ups out
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD_START_DATE, ACCOUNT.COA_MAPPING_L4, ACCOUNT.COA_MAPPING_L5, ACCOUNT.COA_MAPPING_L6
  METRICS    INCOME_STATEMENT.TOTAL_MTD, INCOME_STATEMENT.TOTAL_PY_MTD, INCOME_STATEMENT.TOTAL_BUDGET_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '<first month>' AND '<as-of month>'
         AND ACCOUNT.COA_MAPPING_L3 = 'Revenue'
         AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-8','-9','-10','-11','-12','-15','-19','-100','-1000')
      -- AND SUBSIDIARY.SUBSIDIARY_NAME NOT IN ('<excluded>')   only when config/scope.json lists exclusions
) ORDER BY 1, 2, 3, 4;
-- Tie-out: the L6 rows summed by month equal REVENUE_MTD within $1 (checked Jan–Oct 2026, 16-Nov-2026); by subsidiary too.
```

```sql
-- Headline P&L cards for the latest closed period, fiscal year to date (1 January to the as-of month):
-- the months of the as-of PERIOD.YEAR summed from _MTD; the marts' own _QTD / _YTD / _LTM columns are never used (§1)
SELECT SUM(REVENUE_MTD) AS REVENUE_FYTD, SUM(ADJUSTED_EBITDA_MTD) AS ADJUSTED_EBITDA_FYTD, SUM(NET_INCOME_MTD) AS NET_INCOME_FYTD
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD_START_DATE
  METRICS INCOME_STATEMENT.REVENUE_MTD, INCOME_STATEMENT.ADJUSTED_EBITDA_MTD, INCOME_STATEMENT.NET_INCOME_MTD
  WHERE   PERIOD.YEAR = <fiscal year of the as-of month> AND PERIOD.PERIOD_START_DATE <= '<as-of month start>'
);
-- budget and prior year the same way, from TOTAL_BUDGET_MTD / TOTAL_PY_MTD sliced to the revenue, EBITDA or net-income lines
```

```sql
-- Balance sheet at a month-end by L2 › L3 › L4 line (current liabilities are L3; AP, deferred revenue, debt are L4)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS ACCOUNT.COA_MAPPING_L1, ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3, ACCOUNT.COA_MAPPING_L4
  METRICS    BALANCE_SHEET.ENDING_BALANCE_CONVERTED, BALANCE_SHEET.ENDING_BALANCE_PY_CONVERTED
  WHERE      PERIOD.PERIOD = '<period as stored>'
         AND ACCOUNT.FINANCIAL_STATEMENT = 'BS'
         AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-8','-9','-10','-11','-12','-15','-19','-100','-1000')   -- roll-ups only; equity rows -20001..-20003 kept
);
```

```sql
-- Cash flow by statement section (no key filter: -3 Net Income and -20002 FX are real lines here;
-- drop the label sections Beginning Cash / Ending Cash / Net Cash Flow / Cash before Financing before summing) across 24 months (sum months for a quarter or YTD)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD, PERIOD.PERIOD_END_DATE, ACCOUNT.CASH_FLOW_L1
  METRICS    CASH_FLOW.TOTAL_MTD, CASH_FLOW.TOTAL_BUDGET_MTD
  WHERE      PERIOD.PERIOD_END_DATE BETWEEN '<start>' AND '<end>'
) ORDER BY PERIOD_END_DATE;
```

```sql
-- GL drill: the lines behind one account for a period RANGE (flow), largest first
-- Amount is transaction currency: filter to one currency, and expect the converted mart to differ by FX
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS TRANSACTIONS.TRANSACTION_ID, TRANSACTIONS.TRANSACTION_LINE_ID, TRANSACTIONS.TRANSACTION_DATE,
             TRANSACTIONS.TRANSACTION_TYPE, ACCOUNT.ACCOUNT_NAME, CUSTOMER.CUSTOMER_NAME, CURRENCY.CURRENCY_CODE
  METRICS    TRANSACTIONS.TOTAL_TRANSACTION_CURRENCY_AMOUNT
  WHERE      ACCOUNT.ACCOUNT_NAME = '<account>'
         AND PERIOD.PERIOD_START_DATE >= '<range start>' AND PERIOD.PERIOD_END_DATE <= '<range end>'
         AND CURRENCY.CURRENCY_CODE = '<single currency>'
) ORDER BY ABS(TOTAL_TRANSACTION_CURRENCY_AMOUNT) DESC LIMIT 100;
```

```sql
-- AP / AR open items by counterparty and due date
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS CUSTOMER.CUSTOMER_NAME, TRANSACTIONS.DUE_DATE, ACCOUNT.COA_MAPPING_L4
  METRICS    TRANSACTIONS.TOTAL_OPEN_AMOUNT
  WHERE      ACCOUNT.COA_MAPPING_L4 = 'Accounts Payable'   -- AP is L4 (under L3 Current Liabilities); AR is L3 'Accounts Receivable'
) ORDER BY TOTAL_OPEN_AMOUNT DESC LIMIT 100;
```

## 6. Answer ladders

Each ladder starts at the headline and descends one level at a time. Stop where the user stops asking; offer the next rung in one line.

| Question | Ladder (top to bottom) | Layer |
|---|---|---|
| Why is EBITDA below budget YTD? | 1. Adjusted EBITDA actual vs budget. 2. Revenue, Cost of Sales, OpEx contribution (`L3`). 3. Recurring vs non-recurring (`L4`). 4. Sub-groups (`L5`: SaaS / one-time / licences, royalties / hosting / operational services, sales / marketing, engineering / product, finance / HR / IT) and product lines (`L6`). 5. By subsidiary. 6. Largest accounts. 7. GL lines | mart, then GL |
| How is revenue trending and what drives growth? | 1. Revenue by month with YoY. 2. Recurring vs non-recurring (`L4`). 3. Product line (`L5` › `L6`: which products carry the growth). 4. By subsidiary. 5. By class or department. 6. By customer (GL only) | mart, then GL |
| Gross margin: level and movement? | 1. Gross margin % by month. 2. Recurring vs non-recurring gross profit. 3. Cost of sales by `L4`, then `L5` (Operational Services, Royalties, Web Hosting). 4. By subsidiary | mart |
| Standout variances, with the transactions behind the top 5? | 1. Rank P&L accounts (number + name within subsidiary, classes summed; roll-up keys and subtotals such as EBITDA excluded) by absolute movement, counting accounts active in only one period. 2. Group by `L3` for the story. 3. For each top account the largest GL lines. 4. Tie lines back to the mart variance | mart, then GL |
| Liquidity position? | 1. Cash, working capital, current ratio, net debt. 2. Current assets (`L2`) and current liabilities (`L3`). 3. Cash and AR (`L3`), AP and deferred revenue (`L4`). 4. By subsidiary. 5. AR and AP open items by counterparty | mart, then GL |
| Debt and net debt? | 1. Total debt and cash. 2. Short-term vs long-term (`L3` Current vs Long-Term Liabilities; `L4` Short Term / Senior / Subordinate Debt). 3. Debt accounts (`DEBT_MAPPING = 1`). 4. Change in Debt in cash flow | mart, then GL |
| Where did cash go this quarter? | 1. Beginning to ending cash. 2. Operations, Investing, Financing (`CASH_FLOW_L1`). 3. Working capital, CapEx, debt (`L2`). 4. Net income vs non-cash items (`L3`). 5. By subsidiary | mart, sum months |
| How volatile is operating cash flow? | 1. Monthly Cash from Operations, 24 months: mean, std dev, CV, worst and best month. 2. Compare with revenue volatility. 3. Drivers by `L2` (working capital, net income, non-cash). 4. Worst month's lines | mart, then GL (partial) |
| What was in accrued expenses at 30 June? | 1. Balance by account. 2. By subsidiary. 3. GL lines cumulative to the date | GL (cumulative) |
| Largest AP open items? | 1. Total open. 2. By counterparty. 3. By due-date bucket. 4. Documents | GL |

## 7. Dashboard coverage

The Finance diagnostic dashboard (`dashboards.md`) reads what pages 1 and 2 show (monthly P&L, actual vs budget and prior year) and adds the diagnosis layer: drivers, structural evidence, persistence and proposed decisions. It does not reproduce the Power BI visuals. How the seven Finance Power BI pages map. **Yes** = metric exists; **Derived** = computed from view metrics; **Not available** = say so.

| Page | Visual | Status |
|---|---|---|
| 1. Income Statement Trend | Monthly P&L, LTM/MTD/QTD/YTD, revenue and EBITDA trend, KPI cards with prior year | Yes (revenue, recurring/non-recurring, cost of sales, gross profit, OpEx, Adjusted EBITDA, net income, margins) |
| | Fully loaded S&M, R&D, G&A, hosting and cloud cost | Yes: `COA_MAPPING_L4` `Fully loaded S&M Expense`, `Fully loaded R&D`, `Total G&A`; hosting is L5 `Web Hosting` under `Recurring COGs` |
| 2. Income Statement Variance | Actual vs budget, variance, variance %, EBITDA bridge | Yes for MTD, QTD, YTD, LTM; bridge is derived; arbitrary ranges can't be budgeted |
| 3. Balance Sheet Trend | Cash, AR, AP, working capital, current ratio, net debt, lines, cumulative cash PY vs CY | Yes for balances and debt; working capital, current ratio, net debt, total equity and liabilities + equity derived (the stored equity metrics return 0) |
| 4. Balance Sheet Variance | Actual vs budget, NWC bridge, top movers | Yes; movers by `ACCOUNT_NAME` |
| 5. Cash Flow Trend | Statement, CapEx, net cash flow, change in NWC, FCF/EBITDA | Yes monthly; QTD/YTD/LTM by summing months; FCF/EBITDA derived |
| | Revolver size, drawn, unused, principal payments | **Not available** |
| 6. Cash Flow Variance | Actual vs budget, top 10 movers, cash bridge | Yes by summing months |
| 7. Transaction Details | Transaction table with statement, account, date, period, GL amount, levels 1 to 4 | Partial: raw `AMOUNT` is exposed, not `CONVERTED_AMOUNT` (open item 1) |

## 8. Cautions

- **Sum `_MTD` over the window's months; never use the `_QTD` / `_YTD` / `_LTM` columns.** They are tagged to the keys present in one month and come out incomplete (§1). Balances are read at one date, never summed across months.
- **Roll-up rows are in the marts.** Filter to a mapping or account before summing; `ENDING_BALANCE` is unsafe unfiltered. Rank real accounts only. The roll-up list differs on the cash-flow mart (`-3` is a real line there, `-27` is a roll-up; §3).
- **Two balance-sheet metrics are empty.** `TOTAL_EQUITY_MTD`, `TOTAL_LIABILITIES_AND_EQUITY_MTD` and their converted twins return 0 in PROD. Derive them from `ENDING_BALANCE_CONVERTED` by mapping (§4); never report a zero equity.
- **Use the stored member names.** `Cash & Equivalents` (not "Cash & Cash Equivalents"), `Recurring COGs`, `Operating Expenses`; current and long-term liabilities are L3, AP and deferred revenue L4. The view's column comments give older labels: probe members before filtering.
- **Sign conventions differ by metric.** COGS and OpEx use raw `CONVERTED_AMOUNT`; most balance-sheet figures use GL amount (`CONVERTED_AMOUNT × P_AND_L_MULTIPLIER`).
- **Budget exists only on the marts.** No budget for custom ranges or on the GL.
- **Cash-flow mart is monthly.** Quarter, YTD, LTM are sums of months.
- **`TOTAL_TRANSACTION_CURRENCY_AMOUNT` is single-currency only.** A mixed-currency sum is meaningless; filter `CURRENCY_CODE` and say the drill is in transaction currency.
- **Drill tie-out.** GL lines are raw transaction currency; the mart is converted. A gap between them is expected for non-reporting-currency lines: say so and size it.
- **Display-sort columns are not filters.**
- **Subsidiary exclusions** live in `config/scope.json` (`exclude_subsidiaries`, none today). Add one only when a subsidiary's governed roll-ups do not equal the sum of its accounts, record the reason in `exclude_subsidiaries_reason`, and state the exclusion wherever scope is stated.
- **Reconcile to the governed roll-ups.** Any account-level extract should tie to `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD` and `NET_INCOME_MTD` by month and subsidiary within $1; a gap means a dropped key, a missing chunk or a scope problem.
- **Key ≠ account.** `CHART_OF_ACCOUNT_KEY` is account x class; budgets are often held on one class or one entity while actuals post across several. Compare at the budget's grain (see §3).
- **L6 = L5 is not a level.** Where `COA_MAPPING_L6` repeats `L5` (royalties, every G&A department, every non-operating line, every balance-sheet line) there is no finer split: skip the level, never show a duplicate row or an extra hop. A member with no activity in the window is left out, never zero-filled.
- **The governed tie-out still applies below L4.** Summing `L6` under `L3` Revenue must equal `REVENUE_MTD` within $1 by month and by subsidiary (it does, Jan–Oct 2026); the dashboard refuses a payload where an L5 / L6 subtotal does not foot to its L4 (invariant I13).
- **Subtotals are not drivers.** EBITDA, gross profit and net income are roll-ups of other lines; never present them as an independent line with its own transactions.

## GL line memo (`TRANSACTIONS_AND_ADJUSTMENTS.MEMO`)

Live in PROD and DEV (20-Nov-2026): the free-text NetSuite memo of each GL line; on adjustment rows (`SOURCE_TYPE = ADJUSTMENT`) the adjustment reason. Populated on almost every line (72,588 of 72,589 distinct actual memo groups). `TOTAL_IS_CONVERTED_AMT` by memo sums to the mart's `TOTAL_MTD` x `P_AND_L_MULTIPLIER` per subsidiary and account key to the cent. Manual adjustment rows (`SOURCE_TYPE = ADJUSTMENT`: pro forma and capitalisation) carry **no memo**: describe them by `ADJUSTMENT_TYPE` and account. **Memos are the first evidence for every "why"**: the chat why block, the executive summary, the "What this means" notes, findings and account readings. Use it for drill-through ("what were these postings") and as review evidence in the dashboard (`dashboards.md` §2a). Memos carry vendor, customer and people names and document numbers: paraphrase them in accounting words; never put a name or a document number in an answer or a shared file.
