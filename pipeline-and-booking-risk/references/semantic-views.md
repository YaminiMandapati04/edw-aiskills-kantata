# Semantic view registry (GTM)

**Status: filled from the live definition of Yes Energy's `GTM_ANALYTICS` in `PROD_DB.SEMANTIC_VIEWS` (exported to `assets/semantic_view.yml`, 2026-11-23) and checked against live data the same day. The weighted open pipeline from `OPPORTUNITIES` (`WEIGHTED_OPEN_PIPELINE_ACV`, `NOT IS_CLOSED`) ties to the `PIPELINE_OVERVIEW` card ($14.26mn, 1,599 deals). `BOOKINGS_OVERVIEW` Total = Recurring + Non-Recurring, and Recurring = ARR (New) + ARR (Upsell).** Live `DESCRIBE SEMANTIC VIEW` still wins if it disagrees.

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
| Role / user | `ROLE`, `USER` | read-only connector role; never switch (the view's owner role, `TRANSFORMER_PROD`, is not the role you query as) |
| MCP endpoint and OAuth | `SERVER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_CLIENT_SECRET_2` | **secrets: never read aloud, print, log, or write into SQL, a bundle, a file or an answer.** Don't open `.env`; if a connection fails, say so and point the user to the connector settings. |
| Row cap for row-level output | n/a | 100 |
| Statement timeout | n/a | not set; on a timeout narrow the window or grain |

Always fully qualify: `<DATABASE>.<DB_SCHEMA>.GTM_ANALYTICS`, for example `PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS`.

## 2. Conventions

| Convention | Value |
|---|---|
| Reporting currency | USD (`*_USD`). Booking and opportunity ACV is the year-1 product change to ARR of each Salesforce opportunity line, in USD at the Salesforce dated rate on the close date. Non-recurring bookings are the GL one-time services amount in USD. There is no constant-currency twin. **State the basis in every answer.** |
| Display scale | $ millions (`mn`) with one decimal for headline figures of $1mn or more, $ thousands (`k`) below that. Negatives in brackets. |
| Fiscal year | **The calendar year, 1 January to 31 December, named by that year** (January to December 2026 = FY2026). Fiscal quarters: Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec; labels look like `FY2026-Q3`. Every quarter and year to date in an answer is built by summing the months' `TOTAL_BOOKINGS_MTD` (or the booking lines). Never use the marts' `_QTD` / `_YTD` / `_LTM` (§5). `DIM_DATE` `QUARTER` / `YEAR` match the fiscal calendar because the fiscal year is the calendar year. |
| Latest period | Bookings: the latest month-end that **NetSuite has closed**. `BOOKINGS_OVERVIEW.IS_LATEST` can be a month whose non-recurring revenue is not closed yet: check `NON_RECURRING_BOOKINGS_MTD` before calling a month complete (31 Oct 2026 showed $208k, against $265k to $749k a month June to September). Pipeline: the "today" row (`IS_LATEST = TRUE`). |
| Data freshness | Compare the latest as-at date in the data with today's date and **say so when they differ**. Never judge staleness against the clock when the data itself lags (see `question-patterns.md` §2b). `OPPORTUNITIES.DATA_REFRESHED_AT` gives the load time for opportunities. |
| Entity handling | Only non-recurring (NetSuite) bookings carry `SUBSIDIARY_NAME` (Power Settlements, ENELYTIX). Recurring (Salesforce) bookings and pipeline have no subsidiary. `REGION` is a placeholder and is always blank. |
| Products | `PRODUCT` is the Salesforce Product2 name (for example PowerSignals:User License, DataSignals Cloud, QuickSignals:User License, EnCompass:Zonal Client/Server). Non-recurring rows carry the synthetic product **One Time Services**. `DIM_PRODUCT` adds `PRODUCT_FAMILY` (for example EnCompass LT:OnPrem, SettleCore, DataSignals Cloud), `PRODUCT_LINE_TYPE` (Modeling, Bid-to-Bill, Data Delivery, Visual Analytics, Primary Content, Long Term Physical) and `PRODUCT_CODE`. It is related to every fact table. |
| Plan | **No bookings plan, budget or pipeline target.** Bookings and pipeline compare to prior period or prior year only; there is no coverage ratio. |
| Pipeline values | **Weighted pipeline is the headline:** open line ACV × Salesforce `PROBABILITY` ÷ 100 (`OPPORTUNITIES.WEIGHTED_OPEN_PIPELINE_ACV`, `PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_*` / `WEIGHTED_PIPELINE_ACV_ASAT`). Quote unweighted open pipeline (`OPEN_PIPELINE_*`) only as labelled context. Pipeline created, won ACV, lost ACV and win rate have no weighted twin and stay unweighted. |

## 3. Routing: which table answers what

| The user asks about | Table | Detail |
|---|---|---|
| Bookings: total, recurring (ARR (New), ARR (Upsell)), non-recurring by month, product, subsidiary (monthly MTD; fiscal QTD / YTD built from months) | `BOOKINGS_OVERVIEW` | `view-gtm.md` |
| New ARR vs upsell ARR, opportunity type, customers and deals behind bookings; average deal value | `BOOKING_LINES` (`BOOKING_METRIC`, `OPPORTUNITY_TYPE`, `DIM_ACCOUNT`, `DIM_PRODUCT`) | `view-gtm.md` |
| Weighted pipeline, open opportunities, opportunities created, pipeline created (cards and trends) | `PIPELINE_OVERVIEW` | `view-gtm.md` |
| Opportunity list, stage, owner, source, type, product, probability, win rate, won and lost ACV | `OPPORTUNITIES` | `view-gtm.md` |
| Stage movement, days in stage, how one deal progressed | `OPPORTUNITY_STAGE_HISTORY` | `view-gtm.md` |
| Product family or product line type cuts | `DIM_PRODUCT` (joins to all five fact tables) | `view-gtm.md` |
| Revenue, margins, EBITDA, cash, budget variance | **not this skill**: finance skill | |
| ARR, retention, churn, logo counts | **not this skill**: ARR skill | |

## 4. Words users say, and what they mean

Ambiguous words are the biggest source of wrong answers. Resolve them here; ask only if the table leaves two live readings.

| User says | Means | Not |
|---|---|---|
| bookings, new business | `BOOKINGS_OVERVIEW` / `BOOKING_LINES`: recurring (Salesforce closed-won opportunity lines on the close date, `BOOKING_METRIC` ARR (New) or ARR (Upsell)) plus non-recurring (NetSuite one-time services revenue from the GL, on the period end date) | ARR bridge movements (ARR skill) |
| closed won | recurring bookings (`RECURRING_BOOKINGS_*`, or `BOOKING_LINES` with `BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)')`). `OPPORTUNITIES.WON_ACV_USD` covers the same deals in the pipeline scope, as a labelled reconciliation | non-recurring revenue |
| new, new logo, new customer | **ARR (New)**: `BOOKING_METRIC = 'ARR (New)'` (opportunity type New Customer); KPI `ARR_NEW_*` | ARR bridge movements (ARR skill) |
| upsell, expansion, upgrade, renewal uplift | **ARR (Upsell)**: `BOOKING_METRIC = 'ARR (Upsell)'` (opportunity types Upgrade, Renewal and Downgrade, signed); KPI `ARR_UPSELL_*` | |
| recurring bookings | `RECURRING_BOOKINGS_*` = `ARR_NEW_*` + `ARR_UPSELL_*` (never add the parts to the total) | recurring revenue (finance) |
| non-recurring bookings, services | `NON_RECURRING_BOOKINGS_*`: NetSuite one-time services revenue by subsidiary (product One Time Services) | services pipeline |
| pipeline | **Weighted pipeline** (`WEIGHTED_PIPELINE_VALUE_*`, `WEIGHTED_OPEN_PIPELINE_ACV`): open opportunity line ACV × probability ÷ 100, over every open stage (`NOT IS_CLOSED`). Say "weighted". Give unweighted open pipeline (`OPEN_PIPELINE_*`) only when asked, or as labelled context | closed-won |
| unweighted, gross, total open pipeline | `OPEN_PIPELINE_VALUE_*` / `OPEN_PIPELINE_ACV`, labelled unweighted | |
| probability | `OPPORTUNITIES.PROBABILITY` (0–100, as stored in Salesforce; non-additive) | a stage-mapping probability (none in the view) |
| coverage, target, quota, plan | **None in the view.** Say so and offer weighted pipeline by fiscal close quarter against the same quarter last year | a ratio built on an invented target |
| open deal | `NOT IS_CLOSED` (`STATUS = 'Open'`). **Closed Lost is not open** | |
| source | `OPPORTUNITY_SOURCE`. Live values (checked 2026-11-23): Renewal Outreach, Client Reached Out, Sales_Outreach, Sales Outreach, Website - Demo Request, User Churn, BDR Outbound, Conference, In-person Event, Referral and others, plus Unknown. "Sales_Outreach" and "Sales Outreach" are separate values: probe before filtering | |
| type | `OPPORTUNITY_TYPE`. On bookings: New Customer, Upgrade, Renewal, Downgrade. On opportunities there are more (Auto-generated Renewal, Ad-hoc Sale, M&A Add, Non-standard subscription change, Loaner …) | |
| win rate | `WIN_RATE` = Closed Won ÷ (Closed Won + Closed Lost) opportunities for a `CLOSE_DATE` period (44.5% over Nov 2025 – Oct 2026) | won ÷ created |
| customer | Recurring bookings and pipeline: the Salesforce account (`DIM_ACCOUNT.ACCOUNT_NAME`). Non-recurring bookings have no account (only a subsidiary). | |
| variance | actual minus prior year (or prior period); state which and the sign | a target variance (no target exists) |
| rep, seller | `OWNER_NAME`, sliced on `USER_KEY` (names aren't unique) | |
| revenue, ARR, churn, retention | not in this view: finance or ARR skill | |

## 5. Rules that always hold

| Rule | What goes wrong if ignored |
|---|---|
| Never add across `METRIC_NAME` unless a metric does it for you | Bookings and pipeline marts store several measures as rows. Total Bookings = Recurring + Non-Recurring, and Recurring = ARR (New) + ARR (Upsell). Summing rows double-counts; so does adding Open Pipeline Value to Weighted Pipeline Value. |
| Calculate from `_MTD` only: a quarter, year to date or LTM is the sum of its months' `TOTAL_BOOKINGS_MTD` (or of the booking lines); pipeline is `_MTD` / `_PYMTD` at one as-at date | The marts' `_QTD` / `_YTD` / `_LTM` columns and their PY twins are computed for one month's keys. Rolled up, keys from earlier months drop out and the window is incomplete. Never use or roll them up. |
| Point-in-time vs flow | Weighted and open pipeline take **one** as-at date. Bookings, created pipeline, won and lost take a **range**. Wrong shape, wrong number. |
| `IS_LATEST` | KPI cards read the latest as-at date only. Without `IS_LATEST = TRUE`, a card query returns one value per month-end. |
| Non-additive ratios | Win rate, probability, average opportunity value, average deal value and recurring share are computed after aggregation. Never sum or average them across rows. |
| Distinct counts | `OPPORTUNITIES` is at **line-item** grain (one row per opportunity × product line). Opportunity counts are distinct IDs; ACV is additive across lines. |
| Bookings and pipeline are different worlds | Pipeline, won and lost ACV (opportunities) are never added to bookings. Non-recurring revenue joins recurring bookings only in the governed Total Bookings. |
| Weighted is the pipeline default | A pipeline figure without a label is weighted. Never mix weighted pipeline with unweighted created, won or lost ACV in one ratio without saying so. |

## 6. The view at a glance

| | `GTM_ANALYTICS` |
|---|---|
| Business area | Bookings, pipeline overview, opportunity detail, stage history (no targets) |
| Source systems | Salesforce (ARR bookings and opportunities); NetSuite GL (non-recurring one-time services) |
| Logical tables | 11 (`BOOKINGS_OVERVIEW`, `BOOKING_LINES`, `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY`, `PIPELINE_OVERVIEW`, `DIM_ACCOUNT`, `DIM_DATE`, `DIM_PRODUCT`, `DIM_STAGE_MAPPING`, `DIM_SUBSIDIARY`, `DIM_USER`) |
| Metrics | 122 (mostly window twins of the same KPIs); 10 verified queries |
| Time basis | Month-end as-at dates plus "today"; fiscal year = calendar year |
| Power BI counterpart | GTM Analytics: Bookings, Pipeline Overview, Opportunities Details |
| Detail file | `view-gtm.md` |

## 7. Drill-through paths

Approved source is **the view only**. No raw tables. One hop at a time; carry the filters forward.

| Domain | Hop | From | To | Table | Filter carried |
|---|---|---|---|---|---|
| Bookings | 1 | total | recurring / non-recurring | `BOOKINGS_OVERVIEW` | `IS_LATEST` or `AS_OF_DATE` |
| Bookings | 2 | recurring | ARR (New) / ARR (Upsell); opportunity type; product, product family | `BOOKING_LINES` (+ `DIM_PRODUCT`) | `BOOKING_DATE` range, `BOOKING_METRIC`, `OPPORTUNITY_TYPE`, `PRODUCT` |
| Bookings | 2 | non-recurring | subsidiary | `BOOKINGS_OVERVIEW` / `BOOKING_LINES` | `SUBSIDIARY_NAME` |
| Bookings | 3 | recurring cut | customer (account) → opportunity → line item | `BOOKING_LINES` | `DIM_ACCOUNT.ACCOUNT_NAME`, `OPPORTUNITY_ID` |
| Pipeline | 1 | total (weighted) | stage, close quarter, product, product family, source, owner | `PIPELINE_OVERVIEW` | `IS_LATEST` |
| Pipeline | 2 | cut | opportunity list (with probability) | `OPPORTUNITIES` | stage, owner, `NOT IS_CLOSED` |
| Pipeline | 3 | opportunity | stage runs (by product) | `OPPORTUNITY_STAGE_HISTORY` | `OPPORTUNITY_ID` |

**Where drill stops.** Recurring bookings stop at the opportunity line item. Non-recurring bookings stop at the month and subsidiary (no account or order). **No invoice or sales-order grain exists in the view.** Pipeline stops at the opportunity line. Say where the data stops rather than inventing the next hop.

## 8. Across views, and what cannot be answered

Within the view, one labelled reconciliation is allowed:

| Question | Approach | Watch for |
|---|---|---|
| Is won pipeline showing up as bookings? | `OPPORTUNITIES.WON_ACV_USD` vs recurring `BOOKING_ACV_USD` (`BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)')`) by close month, each its own statement, labelled *derived* | Opportunities include types that book no ARR (Ad-hoc Sale, Loaner, M&A Add …), so expect a scope gap, not just timing |

Questions that need another view (bookings vs ARR, revenue vs bookings) are answered by the ARR or finance skill. Don't query those views from here.

**Cannot be answered from this view.** Reply with the gap and the nearest honest alternative; never improvise.

| Ask | Why not | Offer instead |
|---|---|---|
| Invoice-level or invoice-line detail behind bookings; booking → sales order → invoice leakage | No sales-order or invoice facts | Recurring bookings to the opportunity line; won vs booked reconciliation; ask the data team for a reconciled view |
| Renewals coming due, renewal rate | Renewal opportunities are in the view (type Renewal, stage Proposed Renewal), but no subscription end date is held | Renewal opportunities open, won and lost by close month; ARR skill for churn |
| Bookings plan, budget, pipeline target or coverage | No such data | Prior period or prior year; weighted pipeline by fiscal close quarter |
| Loss reasons | No loss reason in the view | Lost ACV by stage lost at, product, source and owner |
| LTV, CAC, payback, magic number | Needs S&M cost and renewal data | Bookings, ARR (New) bookings, pipeline created as inputs |
| Next step, last activity, call or email activity on opportunities | Not fields in the view | Stage age and past-due close date as a labelled proxy |
| Lead-level or funnel-before-opportunity questions | "Deals only: leads are not in any table" | Opportunity creation onwards |
| Bookings or pipeline by region | `REGION` is a placeholder, always blank | Subsidiary (non-recurring), product or product line type (recurring and pipeline) |

## 9. First-run probes and open items

Run these once per session as needed, to turn "verify" into fact. Each is a read-only `SELECT` on the view; run it through `sql_guard.py` first.

```sql
-- METRIC_NAME members and the latest as-at date
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE, BOOKINGS_OVERVIEW.METRIC_NAME, BOOKINGS_OVERVIEW.IS_LATEST
  METRICS    BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD
) ORDER BY AS_OF_DATE DESC LIMIT 30;

-- Stage members, order and status
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS OPPORTUNITIES.STATUS, OPPORTUNITIES.STAGE_NAME, OPPORTUNITIES.STAGE_ORDER
  METRICS    OPPORTUNITIES.TOTAL_OPPORTUNITIES, OPPORTUNITIES.WEIGHTED_OPEN_PIPELINE_ACV
) ORDER BY STAGE_ORDER;

-- Is the latest month closed in NetSuite?
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD
) ORDER BY AS_OF_DATE DESC LIMIT 6;

-- Weighted pipeline tie-out: lines vs card (should match)
SELECT * FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS
  METRICS PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.OPEN_OPPORTUNITIES_MTD
  WHERE   PIPELINE_OVERVIEW.IS_LATEST = TRUE
);
```

Open items carried from the definition review, and how the skill behaves until each is resolved:

| # | Item | Until resolved |
|---|---|---|
| 1 | `BOOKINGS_OVERVIEW` `METRIC_NAME`: Total Bookings, Recurring Bookings, Non-Recurring Bookings, ARR (New), ARR (Upsell) (checked 2026-11-23). There is no "Recurring Services" row | Recurring = ARR (New) + ARR (Upsell); split from `BOOKING_METRIC` on lines |
| 2 | Member values (checked 2026-11-23): stages Stage 0 (1), Proposed Renewal (2), Qualify (3), Discover (4), Align (5), Validate (6), Invest (7), Closed Lost (8), Closed Won (9); `STATUS` Open / Closed Won / Closed Lost; Stage 0 is not a pipeline stage and carries 0 ACV | Probe again before writing a filter if a literal looks different |
| 3 | `IS_LATEST` month not closed in NetSuite (non-recurring near 0) | Use the month before as the latest complete month and say so |
| 4 | Database | Confirmed: the view is in `PROD_DB.SEMANTIC_VIEWS` (checked 2026-11-23) |
| 5 | `OPPORTUNITIES.IS_ACTIVE_PIPELINE` (pipeline stage and ACV > 0) gives a different open set (357 deals, $14.97mn weighted) from the governed open metrics (`NOT IS_CLOSED`, 1,599 deals, $14.26mn) | Use the governed metrics' filter (`NOT IS_CLOSED`), which ties to the card |

## 10. Approved example questions

Use these in catalogue answers ("what can I ask?"). Each is answerable from the view as it stands. Fuller ladders are in `view-gtm.md` §6; demo-style prompts and their feasibility are in `question-patterns.md`.

- How are bookings tracking vs last year (fiscal year to date), and is growth coming from new ARR or upsell ARR?
- Which products and customers drove this fiscal quarter's recurring bookings?
- How large is the weighted pipeline, and how much is dated to close next quarter?
- How much pipeline did we create this quarter vs last year?
- What is our win rate, and at which stage do we lose deals?
- Which open deals have sat in their current stage the longest?
- Is won pipeline showing up as bookings?
- Build the GTM dashboard for October.
