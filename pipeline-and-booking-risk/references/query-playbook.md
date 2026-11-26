# Query playbook

Recipes for each question type. The goal in every one is the same: answer from governed metrics, decompose until the mechanism is visible, and keep fact, derived and scenario separate.

> **Syntax caveat.** The Snowflake statements below reflect the documented semantic-view syntax and the live definition of `GTM_ANALYTICS`. Ready-to-adapt templates with the real metric and dimension names are in `view-gtm.md` §5. The first time you use each form in a session, if it errors, read the error, adjust (qualifier names, clause order), and carry on — don't abandon the governed route for raw tables on the first syntax failure.

## Contents
1. Discovery and the base query form
2. Pulse questions
3. Why / driver questions
4. Drill-through
5. Trend and lumpiness
6. Agentic recipe — bookings risk
7. Sanity checks before you answer
8. When the view can't answer it

---

## 1. Discovery and the base query form

**Discovery** (use when the registry names a view the account doesn't have, when the user asks what's available, or to confirm a "verify" item). Defaults: `<db>` = `DATABASE` (`PROD_DB`), `<schema>` = `DB_SCHEMA` (`SEMANTIC_VIEWS`):

```sql
SHOW SEMANTIC VIEWS IN SCHEMA <db>.<schema>;        -- or IN DATABASE <db>
DESCRIBE SEMANTIC VIEW <db>.<schema>.GTM_ANALYTICS;  -- tables, dimensions, facts, metrics, comments
SHOW SEMANTIC DIMENSIONS IN <db>.<schema>.GTM_ANALYTICS;
SHOW SEMANTIC METRICS    IN <db>.<schema>.GTM_ANALYTICS;
SHOW SEMANTIC FACTS      IN <db>.<schema>.GTM_ANALYTICS;
```

`SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` is blocked by `sql_guard.py`; use `DESCRIBE` instead.

Choosing between tables: match on the domain words in the question (bookings vs pipeline vs stage history), then on metric names and synonyms in `DESCRIBE`, then on grain (a question about deals, customers or new sales vs seat expansion needs `BOOKING_LINES`, not the KPI mart). Report your choice in one line.

**Base query form** — dimensions and metrics are referenced through the view's logical tables:

```sql
SELECT <dimension_a>, <dimension_b>, <metric_x>, <metric_y>   -- explicit columns, never *
FROM SEMANTIC_VIEW(
    <db>.<schema>.GTM_ANALYTICS
    DIMENSIONS <logical_table>.<dimension_a>, <logical_table>.<dimension_b>
    METRICS    <logical_table>.<metric_x>, <logical_table>.<metric_y>
    WHERE      <logical_table>.<dimension_a> BETWEEN '2026-02-01' AND '2026-07-31'
)
ORDER BY <metric_x> DESC
LIMIT 50;
```

Notes:
- Metrics aggregate to the grain of the dimensions you list — that's how the platform applies the governed definition. Add or remove dimensions to change the grain; never re-aggregate a ratio metric (win rate, average opportunity value) by summing or averaging it in Python.
- Ratio metrics: if you need them at a coarser grain than you queried, re-query at that grain.
- Always pin the time window explicitly, through the table's own time dimension (`AS_OF_DATE`, `BOOKING_DATE`, `CLOSE_DATE`, `PIPELINE_CREATION_DATE`). State the window in the answer.
- **Quarters and years are fiscal** (1 February to 31 January; Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan). Build every window from `_MTD`: for bookings, filter a fiscal date range on the lines or sum the fiscal months of `TOTAL_BOOKINGS_MTD`; open pipeline is read at one as-at date from `_MTD` / `_PYMTD`; created pipeline is summed by month from the lines. Never use or roll up the marts' `*_QTD` / `*_YTD` / `*_LTM` columns (computed for one month's keys, so incomplete; the bookings ones and `DIM_DATE` quarter / year are also calendar).
- A dimension-only probe still needs one metric from a related table. Metrics from tables that don't share a dimension can't be combined in one statement (for example `BOOKING_LINES` with `OPPORTUNITIES`): run separate statements and combine in the analysis.
- Filter literals (`STATUS`, `STAGE_NAME`, `METRIC_NAME`, `OPPORTUNITY_SOURCE`, `OPPORTUNITY_TYPE`) must be real members; probe them (`semantic-views.md` §9) rather than guessing.
- Put filters in the `WHERE` inside `SEMANTIC_VIEW(...)` where possible so they apply before aggregation.
- Run every statement through `python scripts/sql_guard.py` first.

## 2. Pulse questions

"How are bookings tracking?" "What's open pipeline by stage?"

1. Resolve the period (the latest month-end NetSuite has closed for bookings, the "today" row for pipeline, unless stated) and the comparison (prior-year twin by default; say so). "Year to date" means fiscal year to date, from 1 February.
2. Query the metric(s) at the requested grain **and** the comparison window in one statement where the view supports it (open pipeline: `*_MTD` with `*_PYMTD` at one as-at date; bookings: monthly `*_MTD` with `*_PYMTD` over the fiscal months, summed), so the delta uses a consistent definition.
3. Answer: the number, the change in $ and %, and one sentence on what's notable. If the change is large, proactively run the §3 decomposition rather than asking — a bare number with an unexplained jump is a weak answer.

## 3. Why / driver questions

"Why did bookings go up?" "Why is pipeline created down?"

This is the signature use case: governed answer, then the explanation.

1. **Confirm the move.** Current vs comparison, in $ and %. If the move is trivial or inside normal fluctuation (see §5), say so before explaining anything.
2. **Decompose by each available dimension**, one query per dimension: measure (new sales / seat expansion / non-recurring), product and customer for recurring bookings, subsidiary for non-recurring; stage, fiscal close quarter, product, opportunity source, region, owner for pipeline. For each, compute each member's contribution to the total change and its share of it. Keep the top 5–8 contributors and an "all other" row so the parts sum to the total — if they don't sum, you have a filter or grain bug.
3. **Find the concentration.** Which dimension explains the most change with the fewest members? "Two products and four customers account for 80% of the increase" is a finding. A flat spread across everything is also a finding — it says the driver is broad rather than specific.
4. **Separate count and size where the view supports it**: booked-opportunity count × average deal value (`BOOKING_LINES`, recurring), opportunity count × average opportunity value (pipeline). Report only what the metrics allow.
5. **Drill the top contributors to entities** (customers, opportunities), then to lines on request (§4).
6. **State the mechanism and its evidence level.**
   - *Established*: the decomposition shows it. "New-sales bookings in OX rose $4.2mn (+38%), 71% of the total increase, led by three customers."
   - *Not in the data*: never invent or hint at a reason. End at the deepest level the data supports and name who can take it further.
7. **Write it** as `chat-answers.md` describes: what happened, the ranked drivers, why (only what the data shows), the business impact with a bridge; a heading only on business impact, all four blocks by default.

Cause-type tags for ranked movers: `volume`, `size`, `mix`, `timing`, `one-off`, `unexplained`. Tag only from evidence; `unexplained` is a legitimate answer and better than a guess.

## 4. Drill-through

"Show me the deals behind that." "Which deals make up that stage?"

1. Look up the path in `semantic-views.md` §7 (drill-through paths). Move one hop at a time; carry forward the exact filters (window, product, subsidiary, stage, owner) so the detail ties to the number you just quoted.
2. Query the row-level table with explicit columns, the carried filters, `ORDER BY` impact descending, and `LIMIT 100` (the registry's row cap).
3. **Tie-out check:** sum the amount column over the *full* filtered set (a separate aggregate query, not just the limited rows) and confirm it equals the number you drilled from. State it: "These 14 deals total $4.2mn, matching the bookings figure." If it doesn't tie, say by how much and why you think so (the mart is at completed month-ends while booking lines run to today; credits net off on lines; a filter difference) — never paper over it.
4. If rows were capped, say "showing top 100 of 412 by amount".
5. Keep row-level output minimal: only the columns needed to understand the answer. Avoid contact details and other personal data unless the user specifically needs them and has the access.

## 5. Trend and lumpiness

"Are bookings lumpy?" "Is pipeline creation slowing?"

1. Pull the metric at a monthly grain (`*_MTD` by `AS_OF_DATE`, or `*_ASAT` for pipeline) over at least 12 months; prefer 24+. State the window.
2. Derive and label as *derived*: mean, standard deviation, coefficient of variation (std ÷ |mean|), min, max, and the months of the worst and best values; the same month prior year for seasonality. Don't over-fit — no regressions unless asked.
3. Interpret against something: the prior-year window, the trailing twelve-month level, or the quarter-end pattern. A standalone "CV is 0.42" means nothing to a reader.
4. **Trace to drivers.** Split the swings by measure, product and the largest deals: a single large deal in one month is lumpiness, not a trend. Expect a fiscal quarter-end pattern (January, April, July, October).

## 6. Agentic recipe — bookings risk

Read `question-patterns.md` §2c first: the view carries **no sales-order or invoice facts**, so the deck's booking → order → invoice leakage cannot be produced. The supportable check is **won not booked**: `OPPORTUNITIES.WON_ACV_USD` by `CLOSE_DATE` month vs recurring `BOOKING_ACV_USD` (`BOOKING_METRIC = 'Recurring Services'`) by `BOOKING_DATE` month, total and by product, each as its own statement, labelled *derived*. Non-recurring revenue has no opportunity and stays out of it.

Classify each product-month into one bucket and size it in $ (and count of product-months):

| Bucket | Meaning |
|---|---|
| **Matched** | The two sides agree within the tolerance you state (there is no registry tolerance: propose one and say it). |
| **Won, not booked** | Won ACV with no corresponding booking: a candidate for a missing or late booking. |
| **Booked, not won** | Booking with no matching won ACV: a deal outside the pipeline scope (owner segments) or a timing difference. |
| **Amount mismatch** | Both exist, amounts differ beyond tolerance: timing across months, scope. |
| **Unmatched — needs data-owner review** | Anything that can't be attributed. Don't force it into a story. |

Report: $ per bucket, the top products and months in each non-matched bucket, the largest single driver. Say these are **candidates** until a data owner confirms, that differences in scope are expected (the pipeline covers the Corporate, Enterprise and Large Enterprise owner segments; bookings cover the bookings teams), and that invoice-level leakage needs an invoice and sales-order fact added to a governed view.

## 7. Sanity checks before you answer

- Parts sum to the total (contributors + "all other" = total change).
- Period and filters in the answer are the ones in the query.
- Units and scale match the registry (not $ vs $mn confusion), and the **currency basis** (USD) is named.
- The right **table** was used (KPI mart vs lines; `IS_LATEST` on cards; one date for open pipeline, a range for bookings and created), every window was **summed from `_MTD` over its months** (never a mart's `_QTD` / `_YTD` / `_LTM`), and any quarter or year to date is **fiscal**.
- Pipeline values are unweighted; nothing is read against a target (the view has none).
- Never summed across `METRIC_NAME` (Total = Recurring + Non-recurring already; Recurring Services repeats Recurring Bookings).
- Ratio metrics weren't summed or averaged across groups; distinct counts weren't summed.
- Open pipeline means `IS_ACTIVE_PIPELINE` (a pipeline stage, ACV above 0), not "not won".
- Row-level drills tie to the summary number they came from.
- Partial or open periods flagged — don't compare a half-closed month with a full one without saying so (the latest bookings month may not be closed in NetSuite yet).
- Empty or tiny result sets are reported as such, not interpreted.

## 8. When the view can't answer it

Say what's missing and offer the closest honest alternative:
- **Dimension not in the view** (e.g. "bookings by region"): say so; offer the nearest available cut (product for recurring bookings, subsidiary for non-recurring; region, product or opportunity source for pipeline).
- **Grain too coarse** for the drill: say where the data stops (the won opportunity; the month and subsidiary for non-recurring).
- **Metric not defined**: don't improvise a definition for a governed term. Offer a clearly-labelled *derived* proxy only if it's useful, and say it isn't the governed metric.
- **No data for the period**: report that, with the data's actual date range.
- **On the registry's "cannot be answered" list** (`semantic-views.md` §8): give the standard reply (`question-patterns.md` §5) and the nearest governed alternative. Label any proxy *derived*, never governed.
