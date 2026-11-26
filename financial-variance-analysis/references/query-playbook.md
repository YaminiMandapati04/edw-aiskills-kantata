# Query playbook

Recipes for each question type. The goal in every one is the same: answer from governed metrics, decompose until the mechanism is visible, and keep fact, derived and scenario separate.

> **Syntax caveat.** The Snowflake statements below reflect the documented semantic-view syntax and the exported definition of the Finance view, but were written without access to a live account. Ready-to-adapt templates with the real metric and dimension names are in `view-finance.md` §5. The first time you use each form in a session, if it errors, read the error, adjust (qualifier names, clause order), and carry on — don't abandon the governed route for raw tables on the first syntax failure.

## Contents
1. Discovery and the base query form
2. Pulse questions
3. Why / driver questions
4. Drill-through
5. Volatility and trend
6. Scenario and stress tests
7. Agentic recipes — variance narrative
8. Sanity checks before you answer
9. When the view can't answer it

---

## 1. Discovery and the base query form

**Discovery** (use when the registry names a view the account doesn't have, when the user asks what's available, or to confirm a "verify" item). Defaults: `<db>` = `DATABASE` (`PROD_DB`), `<schema>` = `DB_SCHEMA` (`SEMANTIC_VIEWS`):

```sql
SHOW SEMANTIC VIEWS IN SCHEMA <db>.<schema>;        -- or IN DATABASE <db>
DESCRIBE SEMANTIC VIEW <db>.<schema>.<view>;         -- tables, dimensions, facts, metrics, comments
SHOW SEMANTIC DIMENSIONS IN <db>.<schema>.<view>;
SHOW SEMANTIC METRICS    IN <db>.<schema>.<view>;
SHOW SEMANTIC FACTS      IN <db>.<schema>.<view>;
```

`SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` is blocked by `sql_guard.py`; use `DESCRIBE` instead.

Choosing the layer: match on the domain words in the question, then on metric names and synonyms in `DESCRIBE`, then on grain (a question about transactions needs the GL, not a mart). Report your choice in one line.

**Base query form** — dimensions and metrics are referenced through the view's logical tables:

```sql
SELECT <dimension_a>, <dimension_b>, <metric_x>, <metric_y>   -- explicit columns, never *
FROM SEMANTIC_VIEW(
    <db>.<schema>.<view>
    DIMENSIONS <logical_table>.<dimension_a>, <logical_table>.<dimension_b>
    METRICS    <logical_table>.<metric_x>, <logical_table>.<metric_y>
    WHERE      <logical_table>.<dimension_a> BETWEEN '2026-01-01' AND '2026-06-30'
)
ORDER BY <metric_x> DESC
LIMIT 50;
```

Notes:
- Metrics aggregate to the grain of the dimensions you list — that's how the platform applies the governed definition. Add or remove dimensions to change the grain; never re-aggregate a ratio metric (margin %, current ratio) by summing or averaging it in Python.
- Ratio metrics: if you need them at a coarser grain than you queried, re-query at that grain.
- Always pin the time window explicitly, through the view's own time dimension (`PERIOD`, or `TRANSACTION_DATE` on the GL). State the window in the answer.
- A dimension-only probe still needs one metric from a related table. Metrics from tables that don't share a dimension can't be combined in one statement (for example mart metrics with `TRANSACTIONS` metrics): run separate statements and combine in the analysis.
- Filter literals (period labels, `COA_MAPPING_*` values) must be real members; probe them (`semantic-views.md` §9) rather than guessing.
- Put filters in the `WHERE` inside `SEMANTIC_VIEW(...)` where possible so they apply before aggregation.
- Run every statement through `python scripts/sql_guard.py` first.

## 2. Pulse questions

"What's revenue by subsidiary this quarter?" "How did we do last month?"

1. Resolve the period (latest closed period unless stated) and the comparison (prior period by default; say so).
2. Query the metric(s) at the requested grain **and** the comparison period in one statement where the view supports it, so the delta uses a consistent definition.
3. Answer: the number, the change in $ and %, and one sentence on what's notable. If the change is large, proactively run the §3 decomposition rather than asking — a bare number with an unexplained jump is a weak answer.

## 3. Why / driver questions

"Why did EBITDA miss budget?" "What drove the revenue variance?"

This is the signature use case: governed answer, then the explanation.

1. **Confirm the move.** Current vs comparison, in $ and %. If the move is trivial or inside normal fluctuation (see §5), say so before explaining anything.
2. **Decompose by each available dimension**, one query per dimension: the account hierarchy down to `L5` / `L6` (rank the sub-groups and product lines before the accounts, and describe the driver in L6 language: "<product line> - recurring drove 40% of the increase", not "<account number> <account name>"; skip a level that repeats its parent), subsidiary, department, class, customer (GL only). For each, compute each member's contribution to the total change and its share of it. Keep the top 5–8 contributors and an "all other" row so the parts sum to the total — if they don't sum, you have a filter or grain bug.
3. **Find the concentration.** Which dimension explains the most change with the fewest members? "Two subsidiaries and four accounts make up 80% of the increase" is a finding. A flat spread across everything is also a finding — it says the driver is broad (volume, seasonality or pricing) rather than specific.
4. **Separate price, volume and mix where the view supports it** (e.g. units × rate). Report only what the metrics allow.
5. **Drill the top contributors to entities** (accounts, customers), then to transactions on request (§4).
6. **State the mechanism and its evidence level.**
   - *Established*: the decomposition shows it. "Recurring revenue in the UK subsidiary rose $4.2mm (+38%), 71% of the total increase, led by three customers."
   - *Not in the data*: never invent or hint at a reason. End at the deepest level the data supports and name who can take it further.
7. **Write it** as `chat-answers.md` describes: what happened, the ranked drivers, why (only what the data shows), the business impact with a bridge; a heading only on business impact, all four blocks by default.

Cause-type tags for ranked movers (use in variance work): `volume`, `price`, `mix`, `timing`, `one-off`, `unexplained`. Tag only from evidence; `unexplained` is a legitimate answer and better than a guess.

## 4. Drill-through

"Show me the GL lines behind that." "Which journal entries make up that account?"

1. Look up the path in `semantic-views.md` §7 (drill-through paths). Move one hop at a time; carry forward the exact filters (period, entity, account, customer) so the detail ties to the number you just quoted.
2. Query the row-level source with explicit columns, the carried filters, `ORDER BY` impact descending, and `LIMIT 100` (or the registry's row cap). Prefer a semantic view that reaches the grain; use an approved raw table only if it's listed.
3. **Tie-out check:** sum the amount column over the *full* filtered set (a separate aggregate query, not just the limited rows) and confirm it equals the number you drilled from. State it: "These 14 GL lines total $4.2mm, matching the account figure." If it doesn't tie, say by how much and why you think so (timing, currency, a filter difference; GL lines are raw transaction currency while the marts are converted, and balance drills need the cumulative filter while flow drills need the exact range) — never paper over it.
4. If rows were capped, say "showing top 100 of 412 by amount".
5. Keep row-level output minimal: only the columns needed to understand the answer. Avoid contact details and other personal data unless the user specifically needs them and has the access.

## 5. Volatility and trend

"How volatile is operating cash flow?" "Is margin trending down?"

1. Pull the metric at a consistent periodic grain (monthly is typical) over a window long enough to be meaningful — at least 12 periods; prefer 24+. State the window.
2. Derive and label as *derived*: mean, standard deviation, coefficient of variation (std ÷ |mean|), min, max, and the periods of the worst and best values. For trend, a simple start-vs-end change and, if useful, a trailing 3- or 12-period average. Don't over-fit — no regressions unless asked.
3. Interpret volatility against something: compared with revenue volatility, with a prior window, or with seasonality (same month prior year). A standalone "CV is 0.42" means nothing to a reader.
4. **Trace to drivers.** Decompose the metric into its components using the view (for OCF: operating income, working-capital movements — receivables, payables, inventory, deferred revenue — and other). Show which component's variance contributes most to the swings. Then drill the biggest swing period to transactions (§4).
5. Answer with: how volatile (in plain words and numbers), what drives it, when it was worst and why.

## 6. Scenario and stress tests

"Does the cash trough stay above the undrawn revolver under a collections slowdown?"

Everything here is **scenario**, built on an actual base. The base is governed; the shocks are assumptions.

1. **Base case.** Pull actual (and budget/forecast if the view has it) cash balance or net cash flow by period over the test horizon.
2. **Levers.** Use the user's levers if given. If not, run a small, explicit default set and say they are illustrative — e.g. collections delayed by N days, revenue −10% / −20% / −30%, a one-off outflow. Never silently choose a single shock and present it as "the" stress.
3. **Compute in a transparent way.** Apply each lever to the base period by period, in SQL or a short, shown calculation. Keep the arithmetic simple enough that the user can check it.
4. **Compare the trough to the facility.** Trough = minimum projected liquidity over the horizon. The facility headroom (undrawn revolver) is **not in the view** (`semantic-views.md` §2); ask the user for it — it's the one input you can't infer. Report the *headroom* (trough minus any minimum-cash threshold, plus undrawn revolver where relevant) and the period of the trough.
5. **Label clearly.** "Scenario — illustrative assumptions" in the answer, the chart title and the export's Summary sheet. Show a table of lever → trough → headroom.
6. Say what would have to be true for the facility to be at risk (break-even shock), which is usually the most useful single number.

## 7. Agentic recipes

### 7a. Automated variance narrative

Inputs: P&L metrics for the current period and the comparison (prior month, budget, or prior year — default prior month and budget if available; state it).

1. Query metrics by P&L account (or account category) for both periods; compute variance $ and %.
2. Rank by absolute $ impact. Keep the top 8–10 movers plus a reconciling "all other".
3. For each mover, take it one level down (by subsidiary, department or account) just far enough to name the concentration. Tag only from evidence the data shows (`volume`, `price`, `mix`, `timing` with a reversal, `one-off` with a single GL item); otherwise `unexplained`. Never name customers or vendors.
4. Write it as `chat-answers.md` describes: what happened, the top three movers with amount and % of the variance (Other so it foots), why (only what the data shows), and the business impact on EBITDA or margin with a bridge. Under 200 words unless the user asked for the full narrative; then add the remaining ranked movers as a table.
5. Name the function that can confirm, not an assigned action ("the Controller can confirm the accrual"), rather than a generic "monitor".

## 8. Sanity checks before you answer

- Parts sum to the total (contributors + "all other" = total change).
- Period and filters in the answer are the ones in the query.
- Units and scale match the registry (not $ vs $mm confusion), and the **currency basis** is named (marts converted, GL lines transaction currency).
- The right **layer** was used (mart vs GL; one date for balances, a range for flows), and every window was **summed from `_MTD` over its months**, never the marts' `_QTD` / `_YTD` / `_LTM` columns (tagged to one month's account keys, so incomplete). Quarter and year to date are **fiscal** (year from 1 February, FY named by its end): summed by `PERIOD.YEAR` / `QUARTER`.
- Roll-up and subtotal rows (negative keys, EBITDA, gross profit, net income) are not ranked as drivers or double-counted.
- Sign convention applied consistently (expenses, cash outflows).
- Ratio metrics weren't summed or averaged across groups.
- Row-level drills tie to the summary number they came from.
- Partial or open periods flagged — don't compare a half-closed month with a full one without saying so.
- Empty or tiny result sets are reported as such, not interpreted.

## 9. When the view can't answer it

Say what's missing and offer the closest honest alternative:
- **Dimension not in the view** (e.g. "by sales rep" when rep isn't modelled): say so; offer the nearest available cut.
- **Grain too coarse** for the drill: say where the data stops; point to the registry's approved drill source if one exists, otherwise note it as a gap for the data owner.
- **Metric not defined**: don't improvise a definition for a governed term (EBITDA, gross margin). Offer a clearly-labelled *derived* proxy only if it's useful, and say it isn't the governed metric.
- **No data for the period**: report that, with the data's actual date range.
- **On the registry's "cannot be answered" list** (`semantic-views.md` §8): give the standard reply (`question-patterns.md` §5) and the nearest governed alternative. Label any proxy *derived*, never governed.
