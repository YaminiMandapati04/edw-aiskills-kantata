# Mapping: what fills each row, the gates, and the Excel fix

`assets/chronograph_map.json` is the source of truth. It lists every labelled row of the template as `<Section> | <Label>`. This file explains it.

## Contents
1. Layout of the output
2. Row sources by section
3. Sign conventions
4. Blanks, derived rows and template corrections
5. Gates
6. Refusals and what resolves them
7. Why Excel used to repair the file, and how it is prevented
8. Changing the template or the map

---

## 1. Layout of the output

- One sheet, `Accel-KKR Chronograph`, titled "Accel-KKR Portfolio Company Monthly Reporting" in B1. The template's own sheet name and title contain "Template"; the output names come from `output_sheet` / `output_title` in the map, and the pinned template is not changed. Nothing else is above the header and nothing is in column A (the template's "Notes" label is removed). The provenance (window, views, ARR basis, exclusions, "Blank = not carried by the views", build date) is in the file's document properties (File › Info › Comments), not on the sheet. A synthetic test file says SYNTHETIC TEST DATA in B2.
- No panes are frozen.
- **Amounts are in USD thousands with one decimal**: the cells hold the values divided by 1,000 (1,000,678 is stored as 1,000.678 and shows as 1,000.7; negatives in brackets; zero as a dash). The build divides every amount it writes; the template's formulas then calculate in thousands. The gates multiply the sheet back by 1,000 and compare with the views in dollars (tolerance $1), and the build report's headline totals are in USD. Not divided: the Customer Bridge and Headcount (counts), the percentage rows, the pipeline coverage ratio and the month headers.
- **US digit grouping.** Excel takes grouping from the Windows locale, and a format code cannot override it: en-IN shows 2,88,095.6. The two only differ once the shown value reaches 100,000.0, so from there each cell's format writes the commas in itself. The build picks the format per cell from the value it shows.
- Header "P&L Items" on row 3 in column B; months from column C, oldest first. The first month is a month-end date; the rest are the template's `=EOMONTH(prev,1)` chain.
- The template's metric-type, period and criticality columns, and the rows between the title and the header, are removed (the same compact layout as before). Formats, widths, the freeze pane and the template's number formats are kept; the conditional formats that coloured the removed criticality column are dropped.
- The workbook is in automatic calculation, and every formula is saved with its calculated result (the same evaluator as the gates). The file therefore shows every month header and total correctly before Excel recalculates: in manual mode, in Protected View, in previews. The template had been saved in manual calculation with empty results, which showed blank month headers after the first month and "Stale Value" flags. A file written by another program is still treated by Excel as needing recalculation, so in a manual-calculation session (another manual workbook opened first) every formula shows struck through as a stale value. On Windows the build therefore has Excel recalculate the file and save it itself. It then reopens the file in a manual-calculation session and refuses it if any cell loads stale, or if Excel's result differs from the stored one in any formula cell. Without Excel the results are still stored, and the build output carries a note.
- Totals stay as the template's formulas, copied to every month. Where the template carried typed numbers in later months of a formula row (Recurring and Non-recurring Gross Profit), the formula now runs in every month.

## 2. Row sources by section

A row's line name is looked up (case- and punctuation-insensitive) at the deepest level that has it, unless the map pins a `level` (an L-number). A list of names takes every matching line. Each group's Other row is the group total less the rows named (`remainder_of`, at `remainder_level`), so the group's SUM reproduces the view's total whatever the view adds.

| Section | Source | How a row is read |
|---|---|---|
| Profit & Loss | `pl` | Yes Energy's NetSuite hierarchy. L4: Recurring / Non-Recurring Revenue, Recurring / Non-Recurring COGs, Fully loaded S&M Expense, Fully loaded R&D, Total G&A, Depreciation & Amortization, Interest Income, Interest Expense, Reversal of Capitalized Portions, Income Taxes, Other Non-Operating Income & Expense. L5: SaaS - Subscription, Perpetual License, One-time Services (Other Non Recurring Revenue falls in Other non-recurring); Capitalized Commissions, Capitalized Software; HR / IT / Finance / Legal Department, Rent/Lease Expense (Other G&A Spend is the remainder of Total G&A); Transition & Integration Costs, Transaction Costs, Management & AKKR / ACG Fees (Other Items is the remainder). L6: Sales / Marketing / Engineering / Product Expense. The `pl` query keeps L6 only under S&M Expense and R&D and sums the rest to L5 (`config/scope.json` `pl_l6_kept_under_l5`). The COGS L5s (SysOps, Core Operational/Analytics, Customer Support, Data Ops, Live Power Operations, Professional Services) sum into Recurring / Non-Recurring COGs. The memo rows Hosting/Cloud Costs (COGs) and (R&D) read the `hosting` query: the accounts in `scope.json` `hosting_accounts`, split on COA L3 = Cost of Sales (COGs) or not (R&D, including the 61200 Transition & Integration row under Non-Operating), written positive as costs. |
| Balance Sheet | `bs` | L3: Cash & Equivalents (the individual bank accounts summed), Accounts Receivable, Other Current Assets, Net Fixed Assets, Goodwill & Intangibles. L4: Accounts Payable, Accrued Expenses, Deferred Revenue, Senior Debt. Other Non-Current Assets at L3 includes Capitalized Software Development: the COA mapping has no separate capitalised-software line, so Net Capitalized Software is blank. L2: Equity (Total Equity: shareholder's equity, retained earnings, cumulative translation adjustment and current-year net income, keys -20001 / -20002 / -20003). Other Current Liabilities and Other Long-Term Liabilities (Non-Current Liabilities less Senior Debt) are remainders of their L3. |
| Cash Flow Statement | `cf` | Every row carries a cash-flow label. Net Income = Cash from Operations > Income from Operations > Net Income. Total Non-Cash Items = Income from Operations less Net Income. Change in Working Capital, Capital Expenditures, Change in Equity and Change in Debt = their L2 lines. FX Change = Effect of Exchange Rate on Cash. Other cash from investing (Contingent Purchase Consideration, Other Asset) and the financing Other Items (Other Long Term Liabilities) are remainders. Beginning Cash: the first month from the view, later months the template's link to the prior month's Ending Cash. `cf_unlabelled` is empty: an unlabelled row with activity is refused until the owner maps it. |
| ARR Bridge | `arr` | ARR_WATERFALL categories: Beginning ARR, New, Churn, Upsell, Downsell, **FX**, Ending ARR, Gross / Net Dollar Retention. Churn fills (-) Churn/Lost, Downsell fills (-) Downsell/Contraction (Subscription), and **FX fills (-) Downsell/Contraction (Transactional) as -1 × FX**. The template has no FX row; it subtracts the Transactional row inside Net Dollar Retention, so the bridge foots to the view's Ending ARR. MTD values, USD as the view stores it. Beginning ARR: first month from the view, later months linked to the prior Ending ARR. GDR, NDR and Ending ARR are the template's formulas and tie to the view (NDR to the view's NDR + FX, §5). The retention % rows are derived (§4). |
| Customer Bridge | `customers` | Beginning, New and Lost Customers from the bridge, month-to-date; Lost is entered positive (§3). Ending Customers is the template's formula (Beginning less Lost plus New). |
| Bookings | `bookings` | Bookings - ARR (New) = `ARR_NEW_MTD`, Bookings - ARR (Upsell) = `ARR_UPSELL_MTD` (together they are `RECURRING_BOOKINGS_MTD`). Bookings - Recurring Services is blank: the view has no separate recurring-services booking. Non-Recurring from `NON_RECURRING_BOOKINGS_MTD`. Recurring and Total are the template's SUMs and tie to the view. |
| Pipeline | `pipeline` | Unweighted = `OPEN_PIPELINE_VALUE_MTD`, Weighted = `WEIGHTED_PIPELINE_VALUE_MTD`, as at each month-end (Weighted is left blank only if the view returns 0 in every month). Snapshot history starts January 2024. No coverage ratio: the view has no pipeline target. |
| Headcount, Liquidity, Payments Metrics | none | Blank (§4). The template's formulas in these sections stay. |

## 3. Sign conventions

The template (the corrected Accel-KKR template, sheet "2025 Template Corrected") enters **costs, outflows and reductions as positive amounts and subtracts them in its formulas**: Gross Profit = Revenue − Cost of Sales, Adjusted EBITDA = Gross Profit − Operating Expenses, Total Non-Operating = Interest Income − D&A − Interest Expense + Reversal of Capitalized Portions − Income Taxes − Other Non-Operating, Cash from Operations = Income from Operations − Change in Working Capital, Cash before Financing = Cash from Operations − Cash from Investing, GDR = Beginning ARR − Churn − Downsell (Subscription), NDR = GDR + Upsell − Downsell (Transactional) + Cross-Sell + Price Increase, Ending Customers = Beginning − Lost + New. The build reads every view in its own sign and writes the rows marked `negate` in the map with the sign reversed. All its calculations and gates use the view's sign, and the gates evaluate the template's formulas, so a wrong flip fails a tie.

- **P&L**: the view stores values unsigned; each row is multiplied by its account's `P_AND_L_MULTIPLIER` (+1 revenue, -1 costs and the non-operating lines), and a line without one is refused. Revenue is written positive. Cost of sales, every operating expense (including Capitalized Commissions / Software), D&A, Interest Expense, Income Taxes, Transition & Integration, Transaction Costs, Management Fees and Other Items are written positive as costs (a credit shows negative). Interest Income and Reversal of Capitalized Portions are written as signed (income positive), because the template adds them. The governed tie-out of revenue, Adjusted EBITDA and net income proves the signs every month.
- **Capitalised portions**: Capitalized Commissions / Software (keys -8002 / -8001) sit in Fully loaded opex, and their Reversal (key -8003) adds them back below Adjusted EBITDA. They move Adjusted EBITDA and net to zero in Net Income.
- **Balance sheet**: as stored. Assets, liabilities and equity are all positive, so `A = L + E` should be 0. In Yes Energy's view it is, so the check is a blocking gate.
- **Cash flow**: positive for cash in. Net Income, Total Non-Cash Items, FX Change and the financing rows are written as stored. Change in Working Capital, Capital Expenditures and Other cash from investing are written with the sign reversed (a use of cash positive).
- **ARR and customers**: churn, downsell and lost customers are negative in the views and written positive. FX is written as -1 × FX in the Transactional row: a favourable FX movement shows negative there and adds to NDR.

## 4. Blanks, derived rows and template corrections

**Blank, never 0** (each listed in the build report with its reason):
- Headcount (all rows), $ Revolver Size and $ Drawn Revolver, Principal Payments, the Payments Metrics inputs, and Renewal Rate %. No view carries them.
- P&L and BS lines Yes Energy's chart of accounts does not carry (`src: null`): Maintenance & Support, Recurring Transactional, Recurring Services, Term License, Hardware, the three synergy rows, Severance; Net Capitalized Software, Short Term Debt, Accrued Interest, Subordinate Debt; cash-flow Capitalized R&D and Revolver. If the view gains such a line, the coverage gate refuses until the owner maps it. Rows are mapped only from COA mapping levels or owner-set account lists, never by a similar name.
- ARR (+) Cross-Sell and (+) Price Increase: the bridge has no such category (they are in Upsell).
- Bookings - Recurring Services: all recurring bookings are split into ARR New / ARR Upsell.
- Quarterly Pipeline Coverage Ratio: GTM has no coverage metric.
- Template formulas over blank inputs (Ending FTEs, $ Unused Revolver, Net Transactional Revenue, the take rates) keep their formulas; until the inputs are filled they show a dash. They are listed at hand-over (`formula_rows_over_blank_inputs`).

**Derived (labelled with a cell note)**: three ratios of the ARR view's own LTM amounts, each divided by the opening ARR twelve months back:
- Churn Only Gross Retention % = (opening ARR less LTM churn) / opening ARR.
- Gross Retention % = LTM Gross Dollar Retention / opening ARR.
- Net Retention % = LTM Net Dollar Retention / opening ARR (the view's NDR, before FX).

**Template corrections** (reported on every build):
- S&M Expense becomes `=SUM(Sales:Other S&M)` and R&D becomes `=SUM(Engineering:Other R&D)`. The template's SUMs stopped one row short of their own Other row.
- Ending Cash becomes `=Net Cash Flow + FX Change + Beginning Cash`. The template left out its own FX row.
- Rows that now read the views instead of the template's links: Bookings ARR (New) and ARR (Upsell) read GTM bookings (the template linked them to the ARR bridge, which measures ARR going live, not signings); cash-flow Net Income reads the cash-flow mart.
- The ARR Transactional downsell row carries FX, with a cell note.

## 5. Gates

The build evaluates the sheet's own formulas as Excel will, and refuses unless every month ties. Money rows must tie within $1 and counts exactly.

| Row | Must equal |
|---|---|
| Total Revenue, Adjusted EBITDA, Net Income | `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD` |
| A = L + E | 0 |
| Cash & Equivalents | the cash flow's Ending Cash |
| Cash Before Financing | the cash flow's Cash before Financing |
| Beginning Cash, Ending Cash | the cash flow's Beginning / Ending Cash |
| Beginning ARR, Gross Dollar Retention, Ending ARR | the ARR bridge's categories |
| Net Dollar Retention | the bridge's Net Dollar Retention + FX (the sheet carries FX inside NDR) |
| Ending Customers | the customer bridge's Ending Customers |
| Recurring Bookings (ARR), Total Bookings (ARR + SR) | `RECURRING_BOOKINGS_MTD`, `TOTAL_BOOKINGS_MTD` |

Coverage and input gates:
- Every P&L, balance sheet and cash-flow line with activity must land in a row. Every unlabelled cash-flow row with activity must match a `cf_unlabelled` rule (none today).
- Every P&L line must carry `P_AND_L_MULTIPLIER`.
- Every source must cover every month of the window, except pipeline months before the view's snapshot history (blank and reported).
- The as-of month must have closed: its governed revenue at least half the median of the three months before it, and at least half as many P&L lines posting as in the busiest earlier month. Otherwise the build refuses and names the last closed month (`use_as_of`).
- No ARR category may carry values without a row to hold it (`arr_categories`).
- No balance sheet line may sit outside Assets and Total Liabilities & Share Holder Equity.

**Reconciling item (reported, not a gate; it also lands in `confirm_at_source`)**:
- **Cash-flow Net Income vs P&L Net Income.** They differ in most months of the Yes Energy view (Nov 2024 to Oct 2026: 17 of 24 months, by up to about 0.9mn). The cash flow uses its own Net Income so that cash ties. Quote the months and sizes for the view owner.

**Net Cash Flow is not gated**; the sheet's Ending Cash ties to the view in every month.

**Confirm at source** (`confirm_at_source`): the reconciling item above, D&A if it ever reads as income (`sign_watch`), weighted pipeline if it is 0 in every month, and pipeline months without a snapshot.

## 6. Refusals and what resolves them

| Refusal | Meaning | Resolution (never edit a result, the map or a tolerance) |
|---|---|---|
| `<file> is missing` / `columns … do not match` | A result was not saved, or was saved from another query | Run that `.sql` file verbatim and save it with `save_result.py` |
| `declares N rows but holds M` | The result was cut off | Re-run and save the whole result |
| `no data for <months>` | A view has not loaded those months | An earlier `--as-of`, or fewer `--months` |
| `<month> has not closed in FINANCE_ANALYTICS` | The as-of month carries only early accruals | Rebuild with `--as-of <use_as_of>` (the last closed month the refusal names) |
| `cash-flow rows without a cash-flow label … no cf_unlabelled rule` | The view added a cash-flow row without a label (the Yes Energy view has none today) | The skill owner adds a `cf_unlabelled` rule (by COA level) and re-runs the self-test |
| `a P&L line has no P_AND_L_MULTIPLIER` | The sign of an account is unknown | A view-owner question; never guess the sign |
| `reconciliation check(s) failed` | The sheet would not tie to the views | Report the rows and months. If only P&L totals fail, the view's sign convention or roll-ups changed (a new roll-up key belongs in `rollup_keys`); if A = L + E fails, the balance sheet stopped balancing; if a cash or ARR chain fails from one month on, the view's opening balance moved. Either way it is a data or mapping question for the skill owner. |
| `view lines with activity have no row` | The chart of accounts has a new line | The skill owner adds it to the map (a line name, or a remainder), then re-runs the self-test |
| `the template and the row map disagree` / `template_sha256` | The template changed | §8 |
| `workbook failed the open check` | Excel would repair the file, a formula has no stored result, the file is in manual calculation, or Excel's recalculation differs from the stored results | Report it with the check output; the skill owner fixes the cause in `clean_template.py` / `sanitize()` |

## 7. Why Excel used to repair the file, and how it is prevented

The Accel-KKR template as originally received carried:
- about 55,000 leftover range names, 17,000 of them `#REF!`, some pointing at workbooks `[3]` and `[4]` that are not linked;
- a link to a SharePoint task-tracker workbook;
- a workbook view whose `firstSheet` pointed at a second sheet that no longer existed.

Excel reports any of these as "We found a problem with some content". Declining the repair leaves the file unopened. Removing any one fault alone was not enough; removing all three opens the file cleanly. Every workbook the old finance-skill refresh wrote inherited the faults.

The fix has three layers:
- `clean_template.py` removed the faults once, giving the pinned 56 KB `assets/chronograph_template.xlsx` (the original was 828 KB).
- The build runs `sanitize()` again before saving: no defined names, no external links, a reset workbook view.
- `check_workbook.py` lints the saved package and, on Windows with Excel, opens it in a hidden Excel instance and refuses the file if Excel writes a repair log or cannot open it.

To repair a workbook made by the old refresh, rebuild it with this skill. A file someone has already edited can be cleaned in place of a rebuild with `python scripts/clean_template.py --src <file> --out <new file> --no-pin`: it keeps every sheet and value, removes the three faults and runs the check. The original is kept.

## 8. Changing the template or the map

This is skill-owner work, not part of a run:
1. `python scripts/clean_template.py --src <new template.xlsx>` writes `assets/chronograph_template.xlsx` and updates `template_sha256` in the map.
2. Make every labelled row of the new template a map entry: a `src`, `formula`, `heading` or `null` with a reason. The build lists any row not in the map, and any map row not in the template.
3. `python scripts/test_chronograph.py --excel` must pass, and then a governed build must pass every gate.
