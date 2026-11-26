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

| Section | Source | How a row is read |
|---|---|---|
A row's line name is looked up at the deepest level that has it, unless the map pins a `level` (an L-number). A list of names takes every matching line. Each group's Other row is the group total less the rows named (`remainder_of`, at `remainder_level`), so the group's SUM reproduces the view's total whatever the view adds.

| Section | Source | How a row is read |
|---|---|---|
| Profit & Loss | `pl` | Kantata's hierarchy: L4 Recurring / Non-Recurring Revenue, Recurring / Non-Recurring COGs, Fully Loaded S&M Expense, Fully Loaded R&D, G&A, and the non-operating L4s; L5 SaaS - Subscription, One-time Services, HR / IT / Finance / Legal Department, Severance, Other Items; L6 Sales / Marketing / Engineering / Product Expense. The `pl` query keeps L6 only under S&M Expense and R&D and sums the rest to L5 (`config/scope.json` `pl_l6_kept_under_l5`): Kantata's L6 is account-level detail, and the full grain (about 5,800 rows for 24 months) is cut off by the connector. Other S&M (Training), Other R&D and Other G&A Spend are remainders of their L4. Depreciation & Amortization = the D&A L4 plus the two goodwill amortisation L4s (Kimble, Mavenlink). The memo row Hosting/Cloud Costs (COGs) reads the Webhosting L5 lines under both COGS groups. |
| Balance Sheet | `bs` | L3 Cash & Cash Equivalents, Accounts Receivable, Other Current Assets, Goodwill & Intangibles; L4 Tangible fixed assets (Net Fixed Assets), Accounts Payable + "Acounts Payable" (the chart of accounts carries both spellings), Deferred Revenue, Senior Debt; L2 Equity (Total Equity, including the group-level keys -20001 / -20002 / -20003). Other Non-Current Assets, Other Current Liabilities and Other Long-Term Liabilities are remainders of their L3. |
| Cash Flow Statement | `cf`, `cf_label` | **Strictly by the view's cash-flow mapping**, consolidated over all subsidiaries: every row reads only rows the view labels (CASH_FLOW_L1..L3); nothing is assumed or placed by rule. Net Income = the L3 Net Income line; Total Non-Cash Items = L3 lines labelled Total Non-Cash Items (none today, so blank); Change in Working Capital, Capital Expenditures, Change in equity, Change in debt = their L2 lines; FX Change = the L1 FX Change label; Other cash from investing and the financing Other Items are the remainders of their L1 totals (0 today). Cash Before Financing, Net Cash Flow, Beginning Cash and Ending Cash read the view's own labels every month (no formulas, no link to the prior month). Rows the view carries **without a cash-flow label** (today the group-level Amortization adjustment, key -10000, (4.53)mn a month) are placed in no line and reported; the view's Net Cash Flow and Ending Cash include them. A dashboard filtered to one subsidiary (for example Mavenlink, Inc.) shows that subsidiary only and will not match. |
| ARR Bridge | `arr` | Kantata's categories: Beginning ARR, New, Churn, Upsell, Downsell, Ending ARR, Gross / Net Dollar Retention. Churn fills (-) Churn/Lost, Downsell fills (-) Downsell/Contraction (Subscription); both are negative in the view and entered positive in the sheet (§3). MTD values, USD as the view stores it (the view has no actual-rate or constant-currency variant). Beginning ARR: first month from the view, later months linked to the prior Ending ARR. Gross Dollar Retention (Beginning less churn and downsell), Net Dollar Retention and Ending ARR are the template's formulas and tie to the view. The retention % rows are derived (§4). |
| Customer Bridge | `customers` | Beginning, New and Lost Customers from the bridge as **LTM** counts (`CUSTOMER_BRIDGE.TOTAL_LTM`): each category is measured against the customer count 12 months back, so Beginning Customers is that count and does not equal the prior month's Ending (cell note on every row). Lost is entered positive (§3). Ending Customers is the template's formula (Beginning less Lost plus New); the LTM bridge foots and its Ending equals the month-end count. |
| Bookings | `bookings` | GTM does not split recurring bookings into New and Upsell (`ARR_NEW_MTD` / `ARR_UPSELL_MTD` are always 0), so all recurring bookings (`RECURRING_BOOKINGS_MTD`, won New Sales and Seat Expansion) sit in Bookings - Recurring Services, with a cell note. Non-Recurring from `NON_RECURRING_BOOKINGS_MTD`. Recurring and Total are the template's SUMs and tie to the view. |
| Pipeline | `pipeline` | Unweighted = `OPEN_PIPELINE_VALUE_MTD` (stages 01 - ENGAGE to 06 - NEGOTIATE, ACV > 0, as at each month-end; cell note). Weighted = `WEIGHTED_PIPELINE_VALUE_MTD`, left blank while the view returns 0 in every month (no stage probabilities yet). Months before the view's snapshot history (today it starts February 2025) are blank and reported. No coverage ratio: the view has no pipeline target. |
| Liquidity | `revolver`, `revolver_drawn`, `cf` | $ Revolver Size = `REVOLVER_AMOUNT` for METRIC Revolver Size from FINANCE_ANALYTICS REVOLVER (Finance's manual table `PROD_DB.MANUAL.REVOLVER`), every month written from the table (no link to the prior month). $ Drawn Revolver: Drawn Revolver is the balance sheet MTD value of account 280360 (`ENDING_BALANCE_CONVERTED`, query `revolver_drawn`; the account sits in Senior Debt). The other revolver accounts (280370, 280903) are 0 today and not included. A stored 0 is written as 0; a missing month is refused, never filled. $ Unused Revolver is the template's formula (Size less Drawn). Principal Payments = `REVOLVER_AMOUNT` for METRIC Principal Payments in the REVOLVER table: blank (reported) while the table has no such rows; once present, every month must be (a part-filled month set is refused). |
| Headcount, Payments Metrics | none | Blank (§4). The template's formulas in these sections stay. |

## 3. Sign conventions

The template (the corrected Accel-KKR template, sheet "2025 Template Corrected") enters **costs, outflows and reductions as positive amounts and subtracts them in its formulas**: Gross Profit = Revenue − Cost of Sales, Adjusted EBITDA = Gross Profit − Operating Expenses, Total Non-Operating = Interest Income − D&A − Interest Expense + Reversal of Capitalized Portions − Income Taxes − Other Non-Operating, Cash from Operations = Income from Operations − Change in Working Capital, Cash before Financing = Cash from Operations − Cash from Investing, GDR = Beginning ARR − Churn − Downsell, Ending Customers = Beginning − Lost + New. The build reads every view in its own sign and writes the rows marked `negate` in the map with the sign reversed; all its calculations (remainders, derived ratios) and gates use the view's sign, and the gates evaluate the template's formulas, so a wrong flip fails the P&L, cash, ARR or customer ties. The rows written positive are listed in the build output (`entered_positive`).

- **P&L**: the view stores values unsigned; each row is multiplied by its account's `P_AND_L_MULTIPLIER` (+1 revenue and income, -1 costs), and a line without one is refused. Revenue is written positive; cost of sales, every operating expense, D&A, Interest Expense, Income Taxes, Severance, Other Items and the Hosting memo row are written positive as costs (a credit shows negative). The governed tie-out of revenue, Adjusted EBITDA and net income proves the signs every month.
- **Watch: Depreciation & Amortization reads as income.** The group-level Amortization adjustment (key -10000) is income in the view (about 4.5mn a month), so D&A shows negative in the sheet and lifts Net Income above Adjusted EBITDA; the cash flow then adds it back again. Governed Net Income includes it, so the sheet ties, but the build lists it under `confirm_at_source` (map `sign_watch`: D&A is expected positive) for the view owner.
- **Balance sheet**: as stored. Assets, liabilities and equity are all positive, so `A = L + E` (Total Assets less Total L & S/H Equity) should be 0. Kantata's view does not balance (§5).
- **Cash flow**: the view's sign is positive for cash in. Net Income, Total Non-Cash Items, FX Change, the financing rows and the totals read from the view's labels are written as stored. Change in Working Capital, Capital Expenditures and Other cash from investing are written with the sign reversed (a use of cash positive), because the template subtracts them.
- **ARR and customers**: churn, downsell and lost customers are negative in the views and written positive.

## 4. Blanks, derived rows and template corrections

**Blank, never 0** (each listed in the build report with its reason):
- Headcount (all rows) and the Payments Metrics inputs. No view carries them.
- P&L, BS and CF lines Kantata's chart of accounts does not carry (`src: null`, reason "not in Kantata's chart of accounts"): Maintenance & Support, Recurring Transactional, Recurring Services, Perpetual License, Term License, Hardware, Capitalized commissions, Capitalized software, Rent/Lease Expense, the three synergy rows, Interest Income, Reversal of Capitalized Portions, Transition & Integration Costs, Transaction Costs, Management & AKKR / ACG Fees, Hosting/Cloud Costs (R&D); Net Capitalized Software, Accrued Expenses, Short Term Debt, Accrued Interest, Subordinate Debt; cash-flow Capitalized R&D and Revolver (the cash flow carries no revolver line; Liquidity holds size and drawn amount). If the view gains such a line, the coverage gate refuses until the owner maps it.
- ARR rows Kantata's bridge has no category for: Downsell/Contraction (Transactional), Cross-Sell, Price Increase (all downsell is in the Subscription row; cross-sell and price increases are in Upsell).
- Bookings - ARR (New) and ARR (Upsell): the view does not split recurring bookings.
- Quarterly Pipeline Coverage Ratio: GTM has no coverage metric. Weighted Pipeline while the view returns 0 in every month.
- Template formulas over blank inputs (Ending FTEs, Net Transactional Revenue, the take rates) keep their formulas so they work once the inputs are filled; until then they show a dash. They are listed at hand-over (`formula_rows_over_blank_inputs`).

**Derived (labelled with a cell note)**: three ratios of the ARR view's own LTM amounts, LTM basis, each divided by the opening ARR twelve months back:
- Churn Only Gross Retention % = (opening ARR less LTM churn) / opening ARR.
- Gross Retention % = LTM Gross Dollar Retention / opening ARR.
- Net Retention % = LTM Net Dollar Retention / opening ARR.

and one ratio of the ARR view's LTM customer counts (`src: customer_rate`):
- Renewal Rate % = (Beginning Customers LTM less Lost Customers LTM) / Beginning Customers LTM, with Lost as a positive count. In the view's sign (Lost negative) that is (Beginning + Lost) / Beginning. Formatted 0.0% and not divided by 1,000; blank, never 0, where Beginning is missing or 0.

**Template corrections** (reported on every build). The corrected template already fixed its sign formulas (Gross Profit, Adjusted EBITDA, Total Non-Operating, Cash from Operations, Cash before Financing, Net Cash Flow, GDR, NDR, the retention %, Ending Customers, Ending FTEs, Net Transactional Revenue) and made Recurring and Non-recurring Gross Profit formulas in every month. Two errors it still carries are corrected by the build:
- S&M Expense becomes `=SUM(Sales:Other S&M)` and R&D becomes `=SUM(Engineering:Other R&D)`. The template's SUMs stopped one row short of their own Other row.
- Rows that now read the views instead of the template's links or placeholders:
  - Bookings ARR (New) and ARR (Upsell) no longer link to the ARR bridge (which measures ARR going live, not signings); they are blank, and all recurring booking ACV from GTM sits in Bookings - Recurring Services.
  - Cash-flow Net Income now reads the cash-flow mart (§5).
  - Cash Before Financing, Net Cash Flow, Beginning Cash and Ending Cash read the view's own labels (strict mapping) instead of the template's formulas and prior-month link; the template's Ending Cash also left out its own FX row.
  - Hosting/Cloud Costs (COGs) now reads the Webhosting lines. The template's `=Recurring COGs × 0.9` was a placeholder.
- Cell notes state the source on the cash-flow Net Income, Net Cash Flow, Bookings - Recurring Services, Unweighted Pipeline, Accounts Payable, Total Equity, D&A, Downsell, retention %, Renewal Rate %, Customer Bridge (LTM) and revolver rows.

## 5. Gates

The build evaluates the sheet's own formulas as Excel will, and refuses unless every month ties. Money rows must tie within $1 and counts exactly.

| Row | Must equal |
|---|---|
| Total Revenue, Adjusted EBITDA, Net Income | `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD`, `NET_INCOME_MTD` |
| Cash & Equivalents | the cash flow's Ending Cash |
| Cash Before Financing (view label) | Cash from Operations less Cash from Investing, from the strictly mapped lines |
| Ending Cash (view label) | Beginning Cash + Net Cash Flow + FX Change |
| Beginning ARR, Gross Dollar Retention, Net Dollar Retention, Ending ARR | the ARR bridge's categories |
| Ending Customers | the customer bridge's Ending Customers (LTM; exact) |
| $ Drawn Revolver (balance sheet account 280360) | not above the REVOLVER table's Revolver Size, every month |
| Recurring Bookings (ARR), Total Bookings (ARR + SR) | `RECURRING_BOOKINGS_MTD`, `TOTAL_BOOKINGS_MTD` |

Coverage and input gates:
- Every P&L, balance sheet and labelled cash-flow line with activity must land in a row. Cash-flow rows without a label are reported, not placed (`cf_unlabelled` is empty).
- Every P&L line must carry `P_AND_L_MULTIPLIER`.
- Every source must cover every month of the window, except pipeline months before the view's snapshot history (blank and reported).
- The as-of month must have closed: its governed revenue at least half the median of the three months before it, and at least half as many P&L lines posting as in the busiest earlier month. Otherwise the build refuses and names the last closed month (`use_as_of`).
- No ARR category may carry values without a row to hold it (`arr_categories`).
- The revolver result must carry Revolver Size for every month of the window (a missing month or an empty amount is refused: "no data for …"), and no other METRIC: one with no row to hold it is refused, including a Drawn Revolver METRIC, because Drawn Revolver comes from the balance sheet. The `revolver_drawn` result must carry account 280360's balance for every month.
- No balance sheet line may sit outside Assets and Liabilities & Equity.

**Reconciling items (reported, not gates; each also lands in `confirm_at_source`)**:
- **A = L + E.** Kantata's balance sheet does not balance in FINANCE_ANALYTICS: 80k (Oct–Dec 2024), 785k (2025), (1.49mn) (2026), stepping each January (the view's governed L&E and Equity totals return 0). Quote the months and the gap; it is a view-owner item.
- **Net Cash Flow vs Cash Before Financing + Cash from Financing.** The view's Net Cash Flow includes the rows without a cash-flow label (today the group-level Amortization adjustment, key -10000, (4.53)mn a month); no cash-flow line holds them under strict mapping. The difference equals those rows.
- **Cash-flow Net Income vs P&L Net Income.** They should agree; the cash flow uses its own Net Income so that cash ties.

Ending Cash is the view's label and ties to Beginning Cash + Net Cash Flow + FX Change and to balance-sheet cash in every month.

**Confirm at source** (`confirm_at_source` in the build output): the reconciling items above, the cash-flow rows without a cash-flow label (placed in no line; months and last month's amount), D&A reading as income (`sign_watch`), weighted pipeline at 0, and pipeline months without a snapshot.

## 6. Refusals and what resolves them

| Refusal | Meaning | Resolution (never edit a result, the map or a tolerance) |
|---|---|---|
| `<file> is missing` / `columns … do not match` | A result was not saved, or was saved from another query | Run that `.sql` file verbatim and save it with `save_result.py` |
| `declares N rows but holds M` | The result was cut off | Re-run and save the whole result |
| `no data for <months>` | A view has not loaded those months | An earlier `--as-of`, or fewer `--months` |
| `<month> has not closed in FINANCE_ANALYTICS` | The as-of month carries only early accruals | Rebuild with `--as-of <use_as_of>` (the last closed month the refusal names) |
| `reconciliation check(s) failed` on Cash Before Financing | The strictly mapped operating and investing lines do not add up to the view's own Cash before Financing | A view-owner question (a labelled line the map does not read, or an inconsistent label); never place a row by assumption |
| `a P&L line has no P_AND_L_MULTIPLIER` | The sign of an account is unknown | A view-owner question; never guess the sign |
| `reconciliation check(s) failed` | The sheet would not tie to the views | Report the rows and months. If only P&L totals fail, the view's sign convention or roll-ups changed; if a cash or ARR chain fails from one month on, the view's opening balance moved. Either way it is a data or mapping question for the skill owner. |
| `view lines with activity have no row` | The chart of accounts has a new line | The skill owner adds it to the map (a line name, or a remainder), then re-runs the self-test |
| `the template and the row map disagree` / `template_sha256` | The template changed | §8 |
| `workbook failed the open check` | Excel would repair the file, a formula has no stored result, the file is in manual calculation, or Excel's recalculation differs from the stored results | Report it with the check output; the skill owner fixes the cause in `clean_template.py` / `sanitize()` |

## 7. Why Excel used to repair the file, and how it is prevented

The Accel-KKR template carried:
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
