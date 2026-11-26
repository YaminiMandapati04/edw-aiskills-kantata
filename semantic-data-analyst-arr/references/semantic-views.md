# Semantic view registry (ARR)

**Status: populated from the `ARR_ANALYTICS` MCP tool description and known domain conventions. Items marked **verify** need a first-run check (§9). Names are taken from the tool description; live `DESCRIBE SEMANTIC VIEW` wins if it disagrees.**

This skill queries **one view**, `ARR_ANALYTICS`. Bookings and pipeline have their own GTM skill; P&L, balance sheet, cash flow and budget have their own Finance skill. Per-view detail lives in `view-arr.md`. Worked question patterns are in `question-patterns.md`.

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
| Database | `DATABASE` | `PROD_DB` (production; the default for every query. `DEV_DB` holds the development copy: use it only when the user asks) |
| Schema holding the views | `DB_SCHEMA` | `SEMANTIC_VIEWS` |
| ARR view | `ARR_VIEW` | `ARR_ANALYTICS` |
| Warehouse | `WAREHOUSE` | `MCP_WH`. **Pass it in the `warehouse` field of every `sql-exec` call.** The connector rejects calls with no warehouse. |
| Role / user | `ROLE`, `USER` | read-only connector role; never switch |
| MCP endpoint and OAuth | `SERVER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_CLIENT_SECRET_2` | **secrets: never read aloud, print, log, or write into SQL, a bundle, a file or an answer.** Don't open `.env`; if a connection fails, say so and point the user to the connector settings. |
| Row cap for row-level output | n/a | 100 |
| Statement timeout | n/a | not set; on a timeout narrow the window or grain |

Always fully qualify: `<DATABASE>.<DB_SCHEMA>.ARR_ANALYTICS`, for example `PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS`.

## 2. Conventions

| Convention | Value |
|---|---|
| Reporting currency | USD. **State the basis in every answer.** |
| Display scale | $ millions (`mn`) with one decimal for headline figures of $1mn or more, $ thousands (`k`) below that. Negatives in brackets. |
| Calendar | **Fiscal**: Kantata's year runs 1 February to 31 January, named by the year it ends in (Feb 2026 to Jan 2027 = FY2027; Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan). `PERIOD.FY_YEAR` / `QUARTER` carry it, and the view's `TOTAL_QTD` / `TOTAL_YTD` are already fiscal (checked live 2026-11-18: YTD and QTD restart in February, QTD again in May). Say "fiscal" with every QTD / YTD figure. |
| Latest period | Latest closed month-end unless the user names a period. The current open month may appear in the view; label it "partial month — not yet closed" and exclude it from bridge calculations unless the user asks. |
| Data freshness | Compare the latest as-at date in the data with today's date and **say so when they differ**. Never judge staleness against the clock when the data itself lags. |
| Movement signs | New ARR and Expansion ARR are positive and add to ending ARR. Contraction ARR and Churned ARR are shown as positive amounts (the magnitude of the reduction) but their effect on ending ARR is negative; display them in brackets when showing net impact. |
| NRR / GRR | Rates expressed as a percentage; one decimal place. Never sum or average across groups — requery at the coarser grain. |

## 3. Routing: which table answers what

**verify** — confirm table names on first run with `DESCRIBE SEMANTIC VIEW`.

| The user asks about | Expected table | Detail |
|---|---|---|
| Current ARR balance, ending ARR by period, ARR growth rate | `ARR_OVERVIEW` or equivalent KPI mart | `view-arr.md` |
| ARR movements: new, expansion, contraction, churn | `ARR_WATERFALL` or movement table | `view-arr.md` |
| NRR, GRR, net dollar retention | `RETENTION_METRICS` or KPI mart | `view-arr.md` |
| Logo counts: total, new, churned, net adds | `LOGO_METRICS` or movement table | `view-arr.md` |
| Customer-level ARR detail, which customers expanded or churned | Row-level customer table | `view-arr.md` |
| Bookings, pipeline, win rate | **not this skill**: GTM skill | |
| Revenue, EBITDA, cash, budget | **not this skill**: Finance skill | |

## 4. Words users say, and what they mean

| User says | Means | Not |
|---|---|---|
| ARR, annual recurring revenue | Ending ARR for the period | Bookings ACV (GTM skill) |
| new ARR, new logo ARR | ARR from customers new in the period (first subscription) | New bookings (GTM) |
| expansion, upsell ARR | ARR added by existing customers (upsell, cross-sell, seat expansion) | Upsell bookings (GTM) |
| contraction, downsell | ARR lost from existing customers who reduced but did not fully cancel | Churn |
| churn, lost ARR | ARR from customers who fully cancelled; Churned ARR is the magnitude | A negative figure in the bridge; displayed in brackets |
| net new ARR | New + Expansion − Contraction − Churn; the net movement for the period | Bookings (different measure and source) |
| NRR, net dollar retention, net revenue retention | (Starting ARR + Expansion − Contraction − Churn) ÷ Starting ARR, over a trailing 12-month window | GRR, which excludes expansion |
| GRR, gross revenue retention, gross dollar retention | (Starting ARR − Contraction − Churn) ÷ Starting ARR | NRR |
| logo retention, customer retention | (Starting logos − Churned logos) ÷ Starting logos | Dollar retention (NRR/GRR) |
| logo churn, customer churn | Churned logos ÷ Starting logos | ARR churn rate |
| ARR churn rate | Churned ARR ÷ Starting ARR | Logo churn rate |
| cohort | Customers first acquired in a given period; retention curve shows how their ARR evolves | Rolling retention (not cohort-based) |
| segment | Customer segment dimension (e.g. Enterprise, Mid-Market, SMB) — **verify** members on first run | |
| coverage | Pipeline ACV ÷ ARR target — this is a GTM metric, not an ARR metric | ARR |

## 5. Rules that always hold

| Rule | What goes wrong if ignored |
|---|---|
| The bridge must foot | Starting ARR + New + Expansion − Contraction − Churn = Ending ARR. Presenting a bridge that does not foot implies a fabricated or missing movement. |
| NRR and GRR are non-additive rates | Averaging NRR across segments or summing it across months gives nonsense. Requery at the target grain. |
| One period anchor per question | "Current" means the latest closed month. "Q3" means the quarter-end. Never mix period anchors in one bridge. |
| Internal test accounts are excluded from every query | Add `AND (CUSTOMER.ACCOUNT_ID IS NULL OR CUSTOMER.ACCOUNT_ID NOT IN (...))` with the five IDs in `config/excluded_accounts.json` (`scripts/account_scope.py clause`) inside the WHERE of every `ARR_ANALYTICS` query; `account_scope.py check` refuses a query without it. Both ARR_BRIDGE and CUSTOMER_BRIDGE join to CUSTOMER, so the one filter covers every metric. Without it, ARR includes a test account worth 0.5mn at Sep-26. Exclude by ID only, never by name: real customers whose names contain "test" stay in. |
| `IS_LATEST` or the right as-at date on KPI cards | Without it, a card query returns one value per month-end, inflating aggregates. |
| New vs expansion are distinct movements | A customer renewing with the same ARR generates no movement. A customer who is new in one month cannot also expand that month (they had no prior ARR). Never mix the two. |
| Contraction and churn are different | Contraction: customer still active, lower ARR. Churn: customer fully cancelled. Presenting churn as contraction understates the severity of a loss. |
| Logo and dollar retention answer different questions | A high-ARR customer churning has a large dollar impact but counts as one logo. Report both when the question is about retention health. |

## 6. The view at a glance

| | `ARR_ANALYTICS` |
|---|---|
| Business area | ARR bridge, retention, logo counts |
| Source systems | Billing / subscription system (ERP or billing platform; **verify**) |
| Metrics | Starting ARR, Ending ARR, New ARR, Expansion ARR, Contraction ARR, Churned ARR, Net New ARR, NRR, GRR, Logo counts (total, new, churned), ARR growth rate |
| Key dimensions | Customer, segment, product, month / quarter |
| Time basis | Month-end as-at dates; trailing-12-month windows for NRR/GRR |
| Detail file | `view-arr.md` |

## 7. Drill-through paths

Approved source is **the view only**. No raw tables. One hop at a time; carry the filters forward.

| Domain | Hop | From | To | Filter carried |
|---|---|---|---|---|
| ARR bridge | 1 | total | movement type (New / Expansion / Contraction / Churn) | period |
| ARR bridge | 2 | movement type | product, segment | period, movement type |
| ARR bridge | 3 | segment / product | customer list | period, movement type |
| Retention | 1 | NRR / GRR rate | segment, product | trailing-12M window |
| Retention | 2 | segment | customer-level expansion / contraction / churn | segment, period |
| Logo | 1 | net logo adds | new logos, churned logos | period |
| Logo | 2 | churned logos | customer list | period |

**Where drill stops.** Customer is the finest grain in the view; there is no subscription-line or invoice grain. Say where the data stops rather than inventing the next hop.

## 8. Across views, and what cannot be answered

Questions that need another view:

| Question | Route |
|---|---|
| Bookings, closed-won ACV, pipeline | GTM skill |
| Revenue on the income statement, EBITDA, cash, budget variance | Finance skill |
| ARR vs bookings reconciliation (booked not yet in ARR, ARR with no booking) | Governed by joining ARR and GTM views; note the two views have different customer keys — a data-team reconciliation view is the right long-term answer; offer to compare at product × month level as a *derived candidate* |

**Cannot be answered from this view.** Reply with the gap and the nearest honest alternative; never improvise.

| Ask | Why not | Offer instead |
|---|---|---|
| Invoice-level or billing-event detail | No invoice grain in the view | Customer-level ARR movements; ask the data team for a billing-event view |
| Renewal win / loss rate | Renewals that cancel become churn; renewals that renew generate no movement (net-zero) | Logo and dollar churn rate; GRR as the renewal-health proxy |
| CAC, LTV, payback | Needs S&M cost from the finance view | ARR growth, NRR and churn rate as inputs |
| Seat-level or usage-level breakdown | Not in the view | ARR by product and segment |
| ARR by region | No region dimension — **verify** | Segment or product |
| Bookings plan vs ARR target variance | Needs a bookings plan (GTM view has none) and an ARR target | NRR trend, net new ARR vs prior period / prior year |

## 9. First-run probes and open items

Run these once per session as needed, to turn "verify" into fact. Each is a read-only statement; run it through `sql_guard.py` first.

```sql
-- Confirm the view exists and list its tables
DESCRIBE SEMANTIC VIEW PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;

-- Latest available month-end
SELECT MAX(AS_OF_DATE) AS LATEST_DATE
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_OVERVIEW.AS_OF_DATE
  METRICS    ARR_OVERVIEW.ENDING_ARR_USD
);

-- Segment members (verify dimension name)
SELECT DISTINCT SEGMENT
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_OVERVIEW.SEGMENT
  METRICS    ARR_OVERVIEW.ENDING_ARR_USD
)
ORDER BY SEGMENT;

-- Movement type members (verify dimension name)
SELECT DISTINCT MOVEMENT_TYPE
FROM SEMANTIC_VIEW(
  PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
  DIMENSIONS ARR_WATERFALL.MOVEMENT_TYPE
  METRICS    ARR_WATERFALL.MOVEMENT_ARR_USD
)
ORDER BY MOVEMENT_TYPE;
```

Open items:

| # | Item | Until resolved |
|---|---|---|
| 1 | Exact table names inside `ARR_ANALYTICS` unknown until `DESCRIBE` runs | Use templates in `view-arr.md`; adjust on the first error |
| 2 | Dimension member values (segment names, movement type strings) not yet verified | Probe members before writing filters; never guess a literal |
| 3 | Fiscal year starts in February | QTD / YTD and quarter labels are fiscal (FY2027 Q3 = Aug–Oct 2026); a calendar quarter or year must be summed from `TOTAL_MTD` and labelled calendar |
| 4 | NRR / GRR window definition (trailing 12M vs rolling cohort) not confirmed | Use `DESCRIBE` and the view's metric comment; state the definition used |

## 10. Approved example questions

- What is our current ARR, and how fast is it growing?
- Walk me through the ARR bridge for Q3 — where did we gain and lose?
- What is our NRR this year, and how has it trended over the last 12 months?
- Which customers churned last quarter, and how much ARR did we lose?
- Which existing customers expanded the most, and in which products?
- What is our logo retention rate, and how does it compare to the prior year?
- Break down ARR by segment and show me the net new ARR for each.
- Which segment has the highest churn rate?
- Show me the ARR cohort curve for customers acquired in 2024.
