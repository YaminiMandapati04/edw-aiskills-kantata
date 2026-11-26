# Semantic view registry

**Status: filled from the exported definition of the Finance view (created 2026-11-02, owner role `TRANSFORMER_DEV`).** Nothing here was run against live data, so items marked **verify** are read from the definitions and still need a first-run check (§9). Names are trusted; live `DESCRIBE SEMANTIC VIEW` still wins if it disagrees.

View detail lives in `view-finance.md`. Read this file every run, then `view-finance.md` for the layer the question routes to. Worked question patterns are in `question-patterns.md`.

## Contents
1. Connection defaults
2. Conventions
3. Routing: which layer answers what
4. Words users say, and what they mean
5. Rules that always hold
6. The Finance view at a glance
7. Drill-through paths
8. Out of scope, and what cannot be answered
9. First-run probes and open items
10. Approved example questions

---

## 1. Connection defaults

The connector itself (MCP server, OAuth) is configured outside this skill. Names below are the environment variables the owner uses; read the non-secret ones if the environment exposes them, otherwise use the stated default.

| Setting | Env var | Default |
|---|---|---|
| Database | `DATABASE` | `PROD_DB` (production; the default for every query and dashboard. `DEV_DB` holds the development copy: use it only when the user asks) |
| Schema holding the views | `DB_SCHEMA` | `SEMANTIC_VIEWS` |
| Finance view | `FINANCE_VIEW` | `FINANCE_ANALYTICS` |
| Warehouse | `WAREHOUSE` | `MCP_WH`. **Pass it in the `warehouse` field of every `sql-exec` call.** The connector rejects calls with no warehouse ("You must specify the warehouse to use"). |
| Role / user | `ROLE`, `USER` | read-only connector role; never switch (the views are *owned* by `TRANSFORMER_DEV`, which is not the role you query as) |
| MCP endpoint and OAuth | `SERVER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_CLIENT_SECRET_2` | **secrets: never read aloud, print, log, or write into SQL, a bundle, a file or an answer.** Don't open `.env`; if a connection fails, say so and point the user to the connector settings. |
| Row cap for row-level output | n/a | 100 |
| Statement timeout | n/a | not set; on a timeout narrow the window or grain |

Always fully qualify: `<DATABASE>.<DB_SCHEMA>.<view>`, for example `PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS`.

## 2. Conventions

| Convention | Value |
|---|---|
| Reporting currency | Use the `CONVERTED_*` mart columns (reporting currency; the currency code is not in the export, **verify**). **State the basis in every answer.** |
| Display scale | $ millions with one decimal for headline figures of $1m or more, $ thousands below that. Negatives in parentheses. |
| Fiscal calendar | NetSuite fiscal `PERIOD`: Kantata's fiscal year runs **1 February to 31 January**, named by the year it ends in (Feb 2026 to Jan 2027 = FY2027; Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan). `PERIOD.YEAR` / `QUARTER` carry it (Feb 2026 = YEAR 2027, QUARTER 1); `config/scope.json` `fiscal_year_start_month` is 2. |
| Period label | Quote `PERIOD.PERIOD` exactly as stored. Don't invent "FY26 P10" labels. |
| Latest closed period | Latest `PERIOD` that actually returns a non-null metric (probe, §9). |
| Data freshness | Compare the latest period in the data with today's date and **say so when they differ**. Never judge staleness against the clock when the data itself lags. |
| Sign convention | Finance marts store GL amount = `CONVERTED_AMOUNT × P_AND_L_MULTIPLIER`. COGS and OpEx metrics use the raw `CONVERTED_AMOUNT`, so their sign can differ from revenue. Check one known account before labelling a variance favourable or adverse (open item 9). |
| Entity handling | No filter means all subsidiaries in scope. Eliminations and intercompany treatment are not documented (**verify**); say "all subsidiaries as stored" when unfiltered. |
| Undrawn revolver | **Not in the view.** Revolver size, drawn and unused are not modelled. Ask the user for the figure; it is the one input you cannot infer. |
| Budget | Exists only on the marts (`BUDGET_*`). `TRANSACTIONS` has no budget. |

## 3. Routing: which layer answers what

If a question spans two rows, run each layer separately and compare in the analysis.

| The user asks about | View | Layer or table | Detail |
|---|---|---|---|
| Revenue, gross profit, EBITDA, net income, margins by month, quarter, year, LTM; budget and prior-year variance | Finance | `INCOME_STATEMENT` mart | `view-finance.md` |
| Cash, AR, AP, debt, equity, working capital at a month-end | Finance | `BALANCE_SHEET` mart | `view-finance.md` |
| Cash flow bridge, beginning and ending cash | Finance | `CASH_FLOW` mart (monthly only) | `view-finance.md` |
| "What transactions made up X", AR/AP open items, custom date ranges, by customer or location | Finance | `TRANSACTIONS` (live GL) | `view-finance.md` |
| Bookings, pipeline, ARR | out of scope | none | §8: use the `semantic-data-analyst-gtm` skill for bookings and pipeline; ARR is not covered |

## 4. Words users say, and what they mean

Ambiguous words are the biggest source of wrong answers. Resolve them here; ask only if the table leaves two live readings.

| User says | Means | Not |
|---|---|---|
| revenue, sales, top line | GL revenue (`REVENUE_*`, placeholder key `-8`) | |
| recurring revenue | Revenue where `COA_MAPPING_L4` is Recurring Revenue | |
| product line, product | `COA_MAPPING_L6` under `L3` Revenue: `<product> - recurring` (L5 `SaaS - Subscription`), `<product>` (L5 `One-time Services`) or `<product> - Licenses` (L5 `Perpetual License`); the same product can sit under more than one L5, so name the L5 too | a class or a subsidiary |
| SaaS revenue, subscription revenue | `COA_MAPPING_L5` = `SaaS - Subscription` (all of Recurring Revenue today) | |
| one-time services, services revenue | `COA_MAPPING_L5` = `One-time Services` (under Non-Recurring Revenue) | Operational Services (a cost line) |
| license revenue, perpetual licenses | `COA_MAPPING_L5` = `Perpetual License` (L6 `<product> - Licenses`, `License Revenue`) | |
| royalties, royalty cost | `COA_MAPPING_L5` = `Royalties` under `L4` Recurring COGs | |
| hosting cost, cloud cost, web hosting | `COA_MAPPING_L5` = `Web Hosting` under `L4` Recurring COGs | |
| operational services cost, delivery cost | `COA_MAPPING_L5` = `Operational Services` under `L4` Recurring COGs | |
| engineering vs product spend | `COA_MAPPING_L6` = `Engineering Expense` / `Product Expense` / `Other R&D Expense` under L5 `R&D`, L4 Fully loaded R&D | |
| sales vs marketing spend | `COA_MAPPING_L6` = `Sales Expense` / `Marketing Expense` / `Other S&M Expense` under L5 `S&M Expense`, L4 Fully loaded S&M Expense | the Sales or Marketing department |
| finance, HR, IT cost (G&A) | `COA_MAPPING_L5` = `Finance Department` / `HR Department` / `IT Department` / `Other G&A Spend` under L4 Total G&A | the `DEPARTMENT` dimension (which splits every line) |
| management fees, AKKR fees | `COA_MAPPING_L5` = `Management & AKKR / ACG Fees` under L4 Other Non-Operating Income & Expense | |
| severance | `COA_MAPPING_L5` = `Severance` under L4 Other Non-Operating Income & Expense | |
| transaction costs, deal costs | `COA_MAPPING_L5` = `Transaction Costs`; integration costs are `Transition & Integration Costs`; the rest is `Other Items` | |
| customer | GL `CUSTOMER` entity (customer, vendor, counterparty); GL only, not on the marts | |
| budget, plan | Mart `BUDGET_*` columns | |
| variance | actual minus budget (or prior year); state which and the sign | |
| working capital | Current assets minus current liabilities (derived, `COA_MAPPING_L2`) | |
| net debt | Total debt (`-1000` / `DEBT_MAPPING = 1`) minus cash (derived) | |
| segment | Ambiguous: `CLASSIFICATION.CLASS_NAME`; customer segment is not modelled | |
| class | `CLASSIFICATION.CLASS_NAME`: a split **beneath** an account; the key `CHART_OF_ACCOUNT_KEY` is account x class | an account on its own |
| department, team, function (Sales, Marketing, Customer Success) | `DEPARTMENT.DEPARTMENT_NAME` (`DEPARTMENT_FULL_NAME` carries the parent, e.g. `Sales & Marketing : 200 - Sales`); splits actual, budget and prior year | fully loaded S&M / R&D / G&A (an L4, not a department) |
| account | Account number + name within a subsidiary, classes summed | a single `CHART_OF_ACCOUNT_KEY` |
| all subsidiaries, consolidated | Every subsidiary except any `config/scope.json` exclusions (none today); say "All subsidiaries (N)", adding "excluding …" when any are excluded | |
| business unit | `SUBSIDIARY` (confirm), else department or class | |

## 5. Rules that always hold

| Rule | What goes wrong if ignored |
|---|---|
| Calculate from `_MTD` only: QTD, YTD, LTM (and their prior-year and budget) are the sum of `TOTAL_MTD` / `TOTAL_PY_MTD` / `TOTAL_BUDGET_MTD` (or `REVENUE_MTD` …) over the window's months | The view's `_QTD` / `_YTD` / `_LTM` columns and their PY / budget twins are tagged to the account keys present in one month; keys that posted earlier but not that month drop out, so the window is incomplete (Oct-2026 consolidated: `ADJUSTED_EBITDA_YTD` 10.45mn vs 7.72mn from the calendar Jan–Oct months; `NET_INCOME_LTM` 66.36mn vs 17.08mn). Never use or roll them up. |
| Point-in-time vs flow | Balances (cash, AR, AP, debt) take **one** date. Flows (revenue, expenses, cash flow) take a **range**. Wrong shape, wrong number. |
| Fiscal vs calendar | Marts are keyed by fiscal `PERIOD` (the marts' own `*_QTD` / `*_YTD` are also calendar, checked live 2026-11-18, another reason they are not used). Build fiscal QTD and YTD as the sum of `*_MTD` over the months of the same `PERIOD.YEAR` (and `QUARTER`). `CALENDAR` (`DIM_DATE`, GL only) is calendar years. |
| "NOT drillable" metrics | Mart metrics cannot be traced to journal lines. When the user wants transactions, switch to `TRANSACTIONS`. |
| Non-additive ratios | Margins, current ratio and other ratios are computed after aggregation. Never sum or average them across rows. |
| Negative keys | Finance marts hold negative-key roll-up rows (`-8` revenue, `-9` Adjusted EBITDA …) beside real accounts, **and** real rows on other negative keys (balance-sheet equity, cash-flow net income). Exclude the roll-up list only (`view-finance.md` §3; never `NOT LIKE '-%'`, which drops those real rows). Summing a mart with no account filter adds roll-ups on top of detail. |
| Governed tie-out | An account-level extract must tie to `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD` by month and subsidiary within $1. A gap is a dropped key, a cut-off result or a scope problem. |

## 6. The Finance view at a glance

| | `FINANCE_ANALYTICS` |
|---|---|
| Business area | P&L, balance sheet, cash flow, budget variance, GL drill-down |
| Source systems | NetSuite GL |
| Logical tables | 13 |
| Metrics | 56 (6 on live GL, 50 on marts) |
| Time basis | Fiscal `PERIOD` (marts); calendar date too on GL lines |
| Power BI counterpart | Finance Analytics, 7 pages |
| Detail file | `view-finance.md` |

## 7. Drill-through paths

Approved source is **`FINANCE_ANALYTICS` only**. No raw tables. One hop at a time; carry the filters forward.

| Domain | Hop | From | To | Source | Filter carried |
|---|---|---|---|---|---|
| P&L | 1 | total | `COA_MAPPING_L1` → `L2` → `L3` → `L4` → `L5` → `L6` (skip a level when it repeats its parent) | Finance `INCOME_STATEMENT` | `PERIOD`, `SUBSIDIARY` |
| P&L | 2 | L4 / L5 / L6 | `ACCOUNT_NAME` | Finance `INCOME_STATEMENT` | account mapping level |
| P&L | 3 | account | GL line (`TRANSACTION_ID`, `TRANSACTION_LINE_ID`) | Finance `TRANSACTIONS` | account, period start and end dates as a **range**, subsidiary |
| Balance sheet | 1 | total | `COA_MAPPING_L2` → `L3` → `L4` → `L5` (L6 repeats L5 on every balance-sheet line) → account | Finance `BALANCE_SHEET` | `PERIOD` |
| Balance sheet | 2 | account | contributing GL lines | Finance `TRANSACTIONS` | `PERIOD_START_DATE <=` date (**cumulative**) |
| Cash flow | 1 | total | `CASH_FLOW_L1` → `L2` → `L3` | Finance `CASH_FLOW` | `PERIOD` (monthly; sum months) |
| Cash flow | 2 | driver | GL lines | Finance `TRANSACTIONS` | partial: see `view-finance.md` |

**Levels 5 and 6** sit on the `ACCOUNT` dimension, so they work on every mart and on `TRANSACTIONS`. L6 repeats L5 where there is no finer split (Royalties › Royalties, Finance Department › Finance Department, every Non-Operating line, every balance-sheet and cash-flow line): treat L6 = L5 as "no further split", never an extra hop or a duplicate row. Members confirmed 16-Nov-2026 (§9 probe): P&L L5 / L6 as listed in §4; balance sheet L5 e.g. Other Current Assets › `Prepaid expenses and other current assets` / `Prepaid royalties`, Accrued Expenses › `Accrued Bonus` / `Accrued Commissions` / `Accrued Rent` / `Accrued expenses` / `Intercompany`, Other Current Liabilities › `Accrued royalties` / `Equipment notes payable`, Other Long-Term Liabilities › `Deferred income tax liabilities` / `Deferred revenue, net of current portion` / `Operating lease liabilities, net of current` / `Other long term liabilities`, Goodwill & Intangibles › `Goodwill, net` / `Intangible assets, net`; the cash-flow mart carries the same account members. Some members carry no activity in a window (e.g. `GSE` one-time services, `License Revenue`, `Other R&D Expense`): leave them out, never zero-fill.

**Where drill stops.** The GL line: **no invoice or sales-order grain exists in the view.** Say where the data stops rather than inventing the next hop.

## 8. Out of scope, and what cannot be answered

**Out of scope.** Questions that need bookings, pipeline or ARR data are not covered by this skill: say so in one line, point the user to the `semantic-data-analyst-gtm` skill for bookings and pipeline, and say ARR questions are not covered. Never join `FINANCE_ANALYTICS` to another view.

**Answerable since 16-Nov-2026 through `COA_MAPPING_L5` / `L6`** (was "cannot be answered"): fully loaded S&M, R&D and G&A split into sales / marketing / other S&M, engineering / product / other R&D, finance / HR / IT / other G&A; hosting, royalties and operational-services cost of sales; revenue by product line; management fees, severance, transaction and integration costs. Route: `L3` → `L4` → `L5` → `L6` on `INCOME_STATEMENT`, roll-up keys excluded.

**Cannot be answered from the view.** Reply with the gap and the nearest honest alternative; never improvise.

| Ask | Why not | Offer instead |
|---|---|---|
| LTV, CAC, payback, magic number, Rule of X, burn productivity | Wireframe marks SaaS Metrics "Future Scope"; needs data outside this view | GL expense lines by department |
| Revolver size, drawn, unused, principal payments | Not modelled | Cash trough and net debt from the view; ask the user for the facility size |
| Budget for an arbitrary date range | Budget is only on the monthly marts | Nearest whole-month range: `TOTAL_BUDGET_MTD` summed over its months |

## 9. First-run probes and open items

Run these once per session as needed, to turn "verify" into fact. Each is a read-only `SELECT` on a view; run it through `sql_guard.py` first. Replace the view path with your connection defaults.

```sql
-- Finance: which fiscal periods have P&L data, newest first (gives latest closed period and fiscal-year structure)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS PERIOD.PERIOD, PERIOD.PERIOD_END_DATE, PERIOD.YEAR, PERIOD.QUARTER
  METRICS    INCOME_STATEMENT.REVENUE_MTD
) ORDER BY PERIOD_END_DATE DESC LIMIT 24;

-- Finance: live metric list on the GL (open item 1)
SHOW SEMANTIC METRICS IN PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS;

-- Finance: member values for the dimensions you will filter on
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS ACCOUNT.FINANCIAL_STATEMENT, ACCOUNT.COA_MAPPING_L1, ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3
  METRICS    INCOME_STATEMENT.TOTAL_MTD
) LIMIT 200;

-- Finance: L5 / L6 members under each L3 / L4 for the year to date (P&L; swap the mart and metric for BS or CF members)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.FINANCE_ANALYTICS
  DIMENSIONS ACCOUNT.COA_MAPPING_L3, ACCOUNT.COA_MAPPING_L4, ACCOUNT.COA_MAPPING_L5, ACCOUNT.COA_MAPPING_L6
  METRICS    INCOME_STATEMENT.TOTAL_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '<fiscal year start>' AND '<as-of month>'
         AND ACCOUNT.FINANCIAL_STATEMENT = 'P&L'
         AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ('-1','-3','-4','-5','-8','-9','-10','-11','-12','-15','-19','-100','-1000')
) ORDER BY 1, 2, 3, 4;
```

Open items carried from the definitions review, and how the skill behaves until each is resolved (numbers kept as originally issued, so 4 and 5 are absent):

| # | Item | Until resolved |
|---|---|---|
| 1 | Finance description lists live-GL metrics (`REVENUE`, `GROSS_PROFIT`, `NET_INCOME`, balance-sheet and `CASH_FLOW_*` metrics) and a `CONVERTED_AMOUNT` fact that the metric export does not show (only 6 metrics on `TRANSACTIONS`) | Run `SHOW SEMANTIC METRICS` first. If absent, GL drill returns raw transaction-currency amounts only; say the tie-out to the converted mart may differ by FX. |
| 2 | `ACCOUNTING_BOOK_KEY` is in the mart keys but no accounting-book dimension exists | Cannot filter or label by book; note it if totals look doubled |
| 3 | ~~Fully loaded S&M, R&D, G&A, hosting cost lines have no visible dimension~~ Closed 16-Nov-2026: they are `COA_MAPPING_L5` / `L6` members (§4) | Answer from L5 / L6 |
| 6 | Finance `CASH_FLOW` mart has no QTD/YTD/LTM columns | Sum months (flows are additive) and say so |
| 7 | Dimension member values not exported | Probe members before writing filters; never guess a literal such as `'P&L'` or a `COA_MAPPING_L3` value |
| 8 | Database | Confirmed: the views are in `PROD_DB.SEMANTIC_VIEWS` (checked 2026-11-12) |
| 10 | ~~`COA_MAPPING_L5` / `L6` not in the view~~ Closed 16-Nov-2026: `ACCOUNT.COA_MAPPING_L5` and `L6` are live on every mart and on `TRANSACTIONS`; members probed and listed in §4 and §7 | Drill L4 › L5 › L6 › account; the dashboard carries them (renderer 1.9.0, contract 1.5.0) |
| 9 | Sign convention for expense and budget rows undocumented. Observed 2026-11-10 on `FINANCE_ANALYTICS` (Jul–Oct 2026): actuals and prior year store expenses **positive**, the budget stores them **negative**; revenue positive in all three | The engine detects each measure's sign on its own and reports a mismatch in QC; still confirm on one known account before stating favourable / unfavourable |

## 10. Approved example questions

Use these in catalogue answers ("what can I ask?"). Each is answerable from the view as it stands. Fuller ladders are in `view-finance.md`; demo-style prompts and their feasibility are in `question-patterns.md`.

- What were revenue and Adjusted EBITDA last closed month vs budget and prior year, and what drove the gap?
- Which P&L lines have the biggest variances this month, and what are the largest transactions behind them?
- What is our liquidity position: cash, working capital, current ratio, net debt?
- Where did cash go this quarter, and how volatile is operating cash flow over the last 24 months?
- Show the largest open AP items by vendor and due date.
- Which product lines drove recurring revenue growth this year (L6 under SaaS - Subscription)?
- How has Royalties vs Web Hosting cost of sales trended over the last twelve months?
- Engineering vs Product R&D spend YTD vs budget, and sales vs marketing spend?
- What sits in Other Non-Operating this month: management fees, severance, transaction costs or other items?
