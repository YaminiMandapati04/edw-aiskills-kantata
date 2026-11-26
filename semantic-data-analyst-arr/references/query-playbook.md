# Query playbook (ARR)

Recipes for each ARR question type. The goal in every one is the same: answer from governed metrics, decompose until the mechanism is visible, and keep fact, derived and scenario separate.

> **Syntax caveat.** The statements below reflect documented Snowflake semantic-view syntax and known ARR domain conventions, but were written without access to a live account. Ready-to-adapt templates with real metric and dimension names are in `view-arr.md` §5. The first time you use each form in a session, if it errors, read the error, adjust, and carry on — don't abandon the governed route for raw tables on the first syntax failure.

## Contents
1. Discovery and the base query form
2. Pulse questions
3. Why / driver questions
4. Bridge (waterfall)
5. Trend and seasonality
6. Cohort retention
7. Sanity checks before you answer
8. When the view can't answer it

---

## 1. Discovery and the base query form

**Discovery** (use when confirming "verify" items, when the user asks what's available, or on a first-run check):

```sql
SHOW SEMANTIC VIEWS IN SCHEMA PROD_DB.SEMANTIC_VIEWS;
DESCRIBE SEMANTIC VIEW PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;
SHOW SEMANTIC DIMENSIONS IN PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;
SHOW SEMANTIC METRICS    IN PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS;
```

`SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` is blocked by `sql_guard.py`; use `DESCRIBE` instead.

**Base query form:**

```sql
SELECT <dimension_a>, <dimension_b>, <metric_x>
FROM SEMANTIC_VIEW(
    PROD_DB.SEMANTIC_VIEWS.ARR_ANALYTICS
    DIMENSIONS <logical_table>.<dimension_a>, <logical_table>.<dimension_b>
    METRICS    <logical_table>.<metric_x>
    WHERE      <logical_table>.<dimension_a> BETWEEN '2026-01-31' AND '2026-09-30'
)
ORDER BY <metric_x> DESC
LIMIT 50;
```

Notes:
- Metrics aggregate to the grain of the dimensions you list. Add or remove dimensions to change the grain.
- NRR and GRR are non-additive rates; if you need them at a coarser grain, re-query at that grain — never average them from finer results.
- Always pin the time window explicitly through `AS_OF_DATE`. State the window in the answer.
- Filter literal values (segment names, movement type strings) must be real members; probe them (`semantic-views.md` §9) rather than guessing.
- Run every statement through `python scripts/sql_guard.py` first.

---

## 2. Pulse questions

"What is our current ARR?" "What is NRR this quarter?"

1. Resolve the period (latest closed month-end unless stated) and the comparison (prior-year same month by default; say so).
2. Query the KPI mart with `IS_LATEST = TRUE` for the card; for a comparison, also query the prior-year equivalent.
3. Answer: the number, the change in $ and %, and one sentence on what's notable. If the change is large or in the wrong direction, proactively run the §3 decomposition rather than asking.

---

## 3. Why / driver questions

"Why did ARR growth slow?" "What drove the NRR drop?"

1. **Confirm the move.** Current ending ARR vs prior period (or prior year), in $ and %. If the move is small relative to normal fluctuation, say so before explaining.
2. **Decompose by movement type.** From `ARR_WATERFALL`: how much of the change came from each of New / Expansion / Contraction / Churn? Each movement's contribution and its share of total net new ARR.
3. **Decompose by segment and product.** Which segments or products drove each movement type? Rank by absolute dollar impact. Keep the top 5–8 and an "all other" row so the parts sum to the total.
4. **Identify the concentration.** "Three customers account for 68% of the churn" is a finding. A flat spread is also a finding.
5. **Drill to customers** for the dominant movement. Name the top churned or expanded customers (capped at 100 rows).
6. **State the mechanism and its evidence level.**
   - *Established*: "Churn increased by $1.2mn, 80% of which came from two Enterprise customers in the Professional Services product."
   - *Not in the data*: never invent or hint at a reason. End at the deepest level the data supports and name who can take it further.
7. **Write it** as `chat-answers.md` describes: the key number first, then the insight, in the shape the question needs.

Cause-type tags for ranked movers: `new logo growth`, `expansion`, `contraction`, `logo churn`, `mix shift`, `one-off`, `unexplained`. Tag only from evidence; `unexplained` is a legitimate answer.

---

## 4. Bridge (waterfall)

"Show me the ARR bridge for Q3." "Walk me through how ARR moved last month."

1. Query `ARR_WATERFALL` for each movement type summed over the period. Also query `ARR_OVERVIEW` for the starting and ending balances.
2. Lay out the bridge:
   - Starting ARR (from `ARR_OVERVIEW`)
   - + New ARR
   - + Expansion ARR
   - − Contraction ARR (in brackets)
   - − Churned ARR (in brackets)
   - = Ending ARR
3. **Foot-check (mandatory):** Starting + New + Expansion − Contraction − Churn must equal Ending ARR to the cent. If it does not, say the gap and the likely cause (rounding, partial month, unclassified movements) before presenting the bridge.
4. Drill a step by product or customer only when the question asks for it or the driver needs it.

For quarterly bridges, sum monthly movements rather than re-querying at a quarterly grain if the view does not expose quarter-level aggregation — but state which approach you used. Quarters are **fiscal** (the year starts 1 February: Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan, FY named by its end); the view's `TOTAL_QTD` / `TOTAL_YTD` already follow it, so monthly sums must use the same months.

---

## 5. Trend and seasonality

"How has NRR trended over the last 12 months?" "Is ARR growth accelerating?"

1. Pull the metric monthly over at least 12 months (24+ for seasonality); prefer a full year of comparisons.
2. Derive and label as *derived*: mean, standard deviation, the best and worst months, and the year-over-year change at each point.
3. Interpret against something: prior-year window, the trailing 12-month level, or a target rate. A standalone "NRR is 108%" means nothing to a reader without context.
4. Trace swings to drivers: a single large customer churning inflates the churn rate in one month — it is an event, not a trend.
5. For NRR / GRR trends, label the window definition (trailing 12M) in every data point; a one-month "NRR" is a different calculation from the standard trailing-12M rate.

---

## 6. Cohort retention

"Show me the ARR retention curve for customers acquired in 2024."

1. Filter `CUSTOMER_ARR` or `ARR_WATERFALL` to customers first appearing (New ARR movement) in the cohort period.
2. For each subsequent month, compute: Retained ARR ÷ Cohort's initial ARR. Present as a percentage series from Month 0 (100%) through the latest closed month.
3. Label as *derived* (the view may not expose a pre-built cohort metric; you are constructing it from row-level data). State whether the view exposes this directly or whether you are building it from the customer table.
4. Cap the customer list at 100 when showing the underlying data.
5. Offer to compare cohorts (2023 vs 2024 vs 2025) if data is available.

---

## 7. Sanity checks before you answer

- Starting ARR + Net New ARR = Ending ARR (or Starting + New + Expansion − Contraction − Churn = Ending ARR if showing all components).
- Period and filters in the answer match those in the query.
- Units and scale match the registry (`mn` for $1mn+, `k` below that; not $ vs $mn confusion). Currency basis named (USD).
- NRR and GRR are rates, not sums; the window definition is stated.
- Logo counts: new logos and churned logos tie to the net logo add figure.
- Movement signs are correct: Contraction and Churn reduce ending ARR; shown in brackets in the bridge.
- Row-level drills tie to the summary number they came from (run the aggregate query to confirm before showing rows).
- Partial months flagged; never compare an open month with a closed one without saying so.
- Empty results reported as such, not interpreted as zero.

---

## 8. When the view can't answer it

Say what's missing and offer the closest honest alternative:

- **Dimension not in the view** (e.g. "by region"): say so; offer the nearest available cut (segment or product).
- **Grain too coarse** (e.g. "subscription-line ARR"): say where the data stops (customer is the finest grain).
- **Metric not defined**: don't improvise a definition for a governed term. Offer a clearly-labelled *derived* proxy only if it is useful, and say it isn't the governed metric.
- **No data for the period**: report that, with the data's actual date range.
- **On the registry's "cannot be answered" list**: give the standard reply (`question-patterns.md` §5) and the nearest governed alternative. Label any proxy *derived*, never governed.
