# Semantic view registry (GTM)

**Status: filled from the live definition of Kantata's `GTM_ANALYTICS` in `PROD_DB.SEMANTIC_VIEWS` (exported to `assets/semantic_view.yml`, 2026-11-18) and checked against live data the same day: booking lines tie to `BOOKINGS_OVERVIEW` `TOTAL_BOOKINGS_MTD` for 24 months to the cent, and open opportunities tie to the `PIPELINE_OVERVIEW` card.** Live `DESCRIBE SEMANTIC VIEW` still wins if it disagrees.

This skill queries **one view**, `GTM_ANALYTICS`. Finance (P&L, balance sheet, cash flow, budget) and ARR (ARR bridge, retention, logos) have their own skills. Per-view detail lives in `view-gtm.md`. Worked question patterns are in `question-patterns.md`.

## Contents
1. Connection defaults
2. Conventions
3. Routing: which table answers what
4. Words users say, and what they mean
5. Rules that always hold
6. The view at a glance
7. Drill-through paths
8. Across views, and what cannot be answered
9. First-run probes and open items
10. Approved example questions

---

## 1. Connection defaults

The connector itself (MCP server, OAuth) is configured outside this skill. Names below are the environment variables the owner uses; read the non-secret ones if the environment exposes them, otherwise use the stated default.

| Setting | Env var | Default |
|---|---|---|
| Database | `DATABASE` | `PROD_DB` (production; the default for every query and dashboard. `DEV_DB` holds the development copy: use it only when the user asks) |
| Schema holding the views | `DB_SCHEMA` | `SEMANTIC_VIEWS` |
| GTM view | `GTM_VIEW` | `GTM_ANALYTICS` |
| Warehouse | `WAREHOUSE` | `MCP_WH`. **Pass it in the `warehouse` field of every `sql-exec` call.** The connector rejects calls with no warehouse ("You must specify the warehouse to use"). |
| Role / user | `ROLE`, `USER` | read-only connector role; never switch (the view's owner role is not the role you query as) |
| MCP endpoint and OAuth | `SERVER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_CLIENT_SECRET_2` | **secrets: never read aloud, print, log, or write into SQL, a bundle, a file or an answer.** Don't open `.env`; if a connection fails, say so and point the user to the connector settings. |
| Row cap for row-level output | n/a | 100 |
| Statement timeout | n/a | not set; on a timeout narrow the window or grain |

Always fully qualify: `<DATABASE>.<DB_SCHEMA>.GTM_ANALYTICS`, for example `PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS`.

## 2. Conventions

| Convention | Value |
|---|---|
| Reporting currency | USD (`*_USD`); booking and opportunity ACV is Salesforce blended ARR in USD, non-recurring bookings are the income statement amount in USD. There is no constant-currency twin. **State the basis in every answer.** |
| Display scale | $ millions (`mn`) with one decimal for headline figures of $1mn or more, $ thousands (`k`) below that. Negatives in brackets. |
| Fiscal year | **1 February to 31 January, named by the year it ends** (February 2026 to January 2027 = FY2027). Fiscal quarters: Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan; labels look like `FY2027-Q3`. Every quarter and year to date in an answer is fiscal: sum the fiscal months of `TOTAL_BOOKINGS_MTD` (or the booking lines), and say "fiscal" when it matters. Never use the marts' `_QTD` / `_YTD` / `_LTM` (§5); **`BOOKINGS_OVERVIEW` QTD / YTD and `DIM_DATE` `QUARTER` / `YEAR` are also calendar**. |
| Latest period | Bookings: the latest month-end that **NetSuite has closed**. `BOOKINGS_OVERVIEW.IS_LATEST` can be a month whose non-recurring revenue is not closed yet (October 2026 showed $417 of non-recurring while Finance had closed September): check `NON_RECURRING_BOOKINGS_MTD` before calling a month complete. Pipeline: the "today" row (`IS_LATEST = TRUE`). |
| Data freshness | Compare the latest as-at date in the data with today's date and **say so when they differ**. Never judge staleness against the clock when the data itself lags (see `question-patterns.md` §2b). `OPPORTUNITIES.DATA_REFRESHED_AT` gives the load time for opportunities. |
| Entity handling | Only non-recurring (NetSuite) bookings carry `SUBSIDIARY_NAME`; recurring (Salesforce) bookings and pipeline have no subsidiary. Pipeline carries `REGION` (owner region, NorAm or EMEA). |
| Plan | **No bookings plan, budget or pipeline target.** Bookings and pipeline compare to prior period or prior year only; there is no coverage ratio. |
| Pipeline values | **Unweighted ACV only.** Never use `WEIGHTED_PIPELINE_VALUE_*` or stage probability (blank until the stage seed is maintained). |

## 3. Routing: which table answers what

| The user asks about | Table | Detail |
|---|---|---|
| Bookings: total, recurring, non-recurring by window, product, subsidiary (monthly MTD; fiscal QTD / YTD built from months) | `BOOKINGS_OVERVIEW` | `view-gtm.md` |
| New sales vs seat expansion, customers and deals behind bookings; average deal value | `BOOKING_LINES` (`OPPORTUNITY_TYPE`, `DIM_ACCOUNT`) | `view-gtm.md` |
| Open pipeline, opportunities created, pipeline created, average value (cards and trends) | `PIPELINE_OVERVIEW` | `view-gtm.md` |
| Opportunity list, stage, owner, source, region, win rate, won and lost ACV | `OPPORTUNITIES` | `view-gtm.md` |
| Stage movement, days in stage, how one deal progressed | `OPPORTUNITY_STAGE_HISTORY` | `view-gtm.md` |
| Revenue, margins, EBITDA, cash, budget variance | **not this skill**: finance skill | |
| ARR, retention, churn, logo counts | **not this skill**: ARR skill | |

## 4. Words users say, and what they mean

Ambiguous words are the biggest source of wrong answers. Resolve them here; ask only if the table leaves two live readings.

| User says | Means | Not |
|---|---|---|
| bookings, new business | `BOOKINGS_OVERVIEW` / `BOOKING_LINES`: recurring (Salesforce won New Sales and Seat Expansion opportunities, blended ARR, on the close date) plus non-recurring (NetSuite non-recurring revenue from the income statement, on the period end date) | ARR bridge movements (ARR skill) |
| closed won | recurring bookings (`RECURRING_BOOKINGS_*`, or `BOOKING_LINES` with `BOOKING_METRIC = 'Recurring Services'`); `OPPORTUNITIES.WON_ACV_USD` is the same deals in the pipeline scope (owner segments), a labelled reconciliation | non-recurring revenue |
| new / upsell, expansion | `BOOKING_LINES.OPPORTUNITY_TYPE`: New Sales = *new sales*, Seat Expansion = *seat expansion*. The view's `ARR_NEW_*` / `ARR_UPSELL_*` metrics are always 0: never use them | ARR bridge movements (ARR skill) |
| recurring bookings | `RECURRING_BOOKINGS_*` (`RECURRING_SERVICES_*` is the same figure: never add the two) | recurring revenue (finance) |
| non-recurring bookings | `NON_RECURRING_BOOKINGS_*`: NetSuite non-recurring revenue by subsidiary (the income statement's non-recurring revenue) | services pipeline |
| pipeline | Open pipeline ACV (`OPEN_PIPELINE_*`), unweighted: opportunities in a pipeline stage (01 - ENGAGE to 06 - NEGOTIATE) with ACV above 0 | closed-won; weighted pipeline (not used) |
| coverage, target, quota, plan | **None in the view.** Say so and offer open pipeline by fiscal close quarter against the same quarter last year | a ratio built on an invented target |
| open deal | `STATUS = 'Open'` / `OPPORTUNITIES.IS_ACTIVE_PIPELINE` for pipeline. **Closed Lost is not open** | |
| source | `OPPORTUNITY_SOURCE`. Live values (checked 2026-11-18): Marketing, Sales, Expansion/Renewal, Operations, Televerde (one deal) and blank. The view's description mentions Inbound / Outbound / SelfGen / Partners, but those values are not in the data: probe before filtering. | |
| win rate | `WIN_RATE` = won ÷ (won + lost) opportunities for a `CLOSE_DATE` period | won ÷ created |
| customer | Recurring bookings and pipeline: the Salesforce account (`DIM_ACCOUNT.ACCOUNT_NAME`). Non-recurring bookings have no account (only a subsidiary). | |
| variance | actual minus prior year (or prior period); state which and the sign | a target variance (no target exists) |
| rep, seller | `OWNER_NAME`, sliced on `USER_KEY` (names aren't unique) | |
| revenue, ARR, churn, retention | not in this view: finance or ARR skill | |

## 5. Rules that always hold

| Rule | What goes wrong if ignored |
|---|---|
| Never add across `METRIC_NAME` unless a metric does it for you | Bookings and pipeline marts store several measures as rows. Total Bookings = Recurring + Non-Recurring, and Recurring Services repeats Recurring Bookings, so summing rows double-counts. |
| Calculate from `_MTD` only: a quarter, year to date or LTM is the sum of its fiscal months' `TOTAL_BOOKINGS_MTD` (or of the booking lines); open pipeline is `_MTD` / `_PYMTD` at one as-at date | The marts' `_QTD` / `_YTD` / `_LTM` columns and their PY twins are computed for one month's keys; rolled up, keys from earlier months drop out and the window is incomplete (the bookings ones are also calendar). Never use or roll them up. |
| Point-in-time vs flow | Open pipeline takes **one** as-at date. Bookings, created pipeline, won and lost take a **range**. Wrong shape, wrong number. |
| `IS_LATEST` | KPI cards read the latest as-at date only. Without `IS_LATEST = TRUE`, a card query returns one value per month-end. |
| Non-additive ratios | Win rate, average opportunity value, average deal value and recurring share are computed after aggregation. Never sum or average them across rows. |
| Distinct counts | Opportunity counts are distinct IDs. Booked-opportunity counts are non-additive across groups. |
| Bookings and pipeline are different worlds | Pipeline, won and lost ACV (opportunities) are never added to bookings; non-recurring revenue joins recurring bookings only in the governed Total Bookings. |

## 6. The view at a glance

| | `GTM_ANALYTICS` |
|---|---|
| Business area | Bookings, pipeline, opportunity detail, stage history (no targets) |
| Source systems | Salesforce (recurring bookings and opportunities); NetSuite (non-recurring revenue) |
| Logical tables | 10 (`BOOKINGS_OVERVIEW`, `BOOKING_LINES`, `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY`, `PIPELINE_OVERVIEW`, `DIM_ACCOUNT`, `DIM_DATE`, `DIM_STAGE_MAPPING`, `DIM_SUBSIDIARY`, `DIM_USER`) |
| Metrics | 118 (mostly window twins of the same KPIs) |
| Time basis | Month-end as-at dates plus "today"; pipeline windows fiscal (from 1 February), bookings mart windows calendar |
| Power BI counterpart | GTM Analytics, 3 pages |
| Detail file | `view-gtm.md` |

## 7. Drill-through paths

Approved source is **the view only**. No raw tables. One hop at a time; carry the filters forward.

| Domain | Hop | From | To | Table | Filter carried |
|---|---|---|---|---|---|
| Bookings | 1 | total | recurring / non-recurring | `BOOKINGS_OVERVIEW` | `IS_LATEST` or `AS_OF_DATE` |
| Bookings | 2 | recurring | new sales / seat expansion, product (SX, OX) | `BOOKING_LINES` | `BOOKING_DATE` range, `OPPORTUNITY_TYPE`, `PRODUCT` |
| Bookings | 2 | non-recurring | subsidiary | `BOOKINGS_OVERVIEW` / `BOOKING_LINES` | `SUBSIDIARY_NAME` |
| Bookings | 3 | recurring cut | customer (account) → opportunity | `BOOKING_LINES` | `DIM_ACCOUNT.ACCOUNT_NAME`, `OPPORTUNITY_ID` |
| Pipeline | 1 | total | stage, close quarter, product, source, region, owner | `PIPELINE_OVERVIEW` | `IS_LATEST` |
| Pipeline | 2 | cut | opportunity list | `OPPORTUNITIES` | stage, owner |
| Pipeline | 3 | opportunity | stage runs | `OPPORTUNITY_STAGE_HISTORY` | `OPPORTUNITY_ID` |

**Where drill stops.** Recurring bookings stop at the won opportunity; non-recurring bookings stop at the month and subsidiary (no account, product or order). **No invoice or sales-order grain exists in the view.** Pipeline stops at the opportunity. Say where the data stops rather than inventing the next hop.

## 8. Across views, and what cannot be answered

Within the view, one labelled reconciliation is allowed:

| Question | Approach | Watch for |
|---|---|---|
| Is won pipeline showing up as bookings? | `OPPORTUNITIES.WON_ACV_USD` vs recurring `BOOKING_ACV_USD` (`BOOKING_METRIC = 'Recurring Services'`) by close month, each its own statement, labelled *derived* | Both are Salesforce won New Sales and Seat Expansion deals, but the pipeline scope is the Corporate, Enterprise and Large Enterprise owner segments while bookings are the bookings teams; expect a scope gap, not timing |

Questions that need another view (bookings vs ARR, revenue vs bookings) are answered by the ARR or finance skill. Don't query those views from here.

**Cannot be answered from this view.** Reply with the gap and the nearest honest alternative; never improvise.

| Ask | Why not | Offer instead |
|---|---|---|
| Invoice-level or invoice-line detail behind bookings; booking → sales order → invoice leakage | No sales-order or invoice facts | Recurring bookings to the opportunity; won vs booked reconciliation; ask the data team for a reconciled view |
| Renewal rate, renewal win/loss | Only New Sales and Seat Expansion opportunities are in the view | ARR skill for churn and downsell |
| Bookings plan, budget, pipeline target or coverage | No such data | Prior period or prior year; open pipeline by fiscal close quarter |
| Weighted pipeline | Stage probabilities are not maintained; the skill uses unweighted values only | Open pipeline by stage, late stage (04 - PROPOSE onwards) |
| Loss reasons | No loss reason in the view | Lost ACV by stage lost at, product, source and owner |
| LTV, CAC, payback, magic number | Needs S&M cost and renewal data | Bookings, new ARR bookings, pipeline created as inputs |
| Next step, last activity, call or email activity on opportunities | Not fields in the view | Stage age and past-due close date as a labelled proxy |
| Lead-level or funnel-before-opportunity questions | "Deals only: leads are not in any table" | Opportunity creation onwards |
| Bookings by region | Recurring bookings carry no region (pipeline has `REGION`) | Subsidiary (non-recurring), product (recurring) |

## 9. First-run probes and open items

Run these once per session as needed, to turn "verify" into fact. Each is a read-only `SELECT` on the view; run it through `sql_guard.py` first.

```sql
-- METRIC_NAME members (open item 1) and the latest as-at date
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE, BOOKINGS_OVERVIEW.METRIC_NAME, BOOKINGS_OVERVIEW.IS_LATEST
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD
) ORDER BY AS_OF_DATE DESC LIMIT 30;

-- Stage members, order and status (open item 2)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS OPPORTUNITIES.STATUS, OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.STAGE_ORDER
  METRICS    OPPORTUNITIES.TOTAL_OPPORTUNITIES
) ORDER BY STAGE_ORDER;

-- Is the latest month closed in NetSuite? (open item 3)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD
) ORDER BY AS_OF_DATE DESC LIMIT 6;
```

Open items carried from the definition review, and how the skill behaves until each is resolved:

| # | Item | Until resolved |
|---|---|---|
| 1 | `RECURRING_SERVICES_*` repeats `RECURRING_BOOKINGS_*`; `ARR_NEW_*` / `ARR_UPSELL_*` are always 0 | Use Recurring Bookings; split new sales / seat expansion from `BOOKING_LINES.OPPORTUNITY_TYPE` |
| 2 | Member values (checked 2026-11-18): stages `00 - PROSPECT` to `06 - NEGOTIATE`, `07 - CLOSE (WON)`, `07 - CLOSE (LOST)` (`STAGE_ORDER` 1 to 9); `STATUS` Open / Closed Won / Closed Lost; products SX, OX (opportunities also Undecided, Unassigned) | Probe again before writing a filter if a literal looks different |
| 3 | `IS_LATEST` month not closed in NetSuite (non-recurring near 0) | Use the month before as the latest complete month and say so |
| 4 | Database | Confirmed: the view is in `PROD_DB.SEMANTIC_VIEWS` (checked 2026-11-18) |

## 10. Approved example questions

Use these in catalogue answers ("what can I ask?"). Each is answerable from the view as it stands. Fuller ladders are in `view-gtm.md` §6; demo-style prompts and their feasibility are in `question-patterns.md`.

- How are bookings tracking vs last year (fiscal year to date), and is growth coming from new sales or seat expansion?
- Which products and customers drove this fiscal quarter's recurring bookings?
- How healthy is the open pipeline, and how much is dated to close next fiscal quarter?
- How much pipeline did we create this fiscal quarter vs last year?
- What is our win rate, and at which stage do we lose deals?
- Which open deals have sat in their current stage the longest?
- Is won pipeline showing up as bookings?
- Build the GTM dashboard for October.
