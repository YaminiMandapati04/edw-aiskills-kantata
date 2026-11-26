---
name: semantic-data-analyst-arr
description: "Answers plain-English ARR and retention questions from the governed Snowflake ARR semantic view over MCP (ARR bridge, new/expansion/contraction/churn ARR, net and gross revenue retention, logo counts, by customer, segment, product and month). Explains why ARR moved, drills to customer-level detail, and answers trend and cohort questions. Use for 'what is our ARR?', 'why did NRR drop?', 'how much ARR did we churn?', 'show the ARR waterfall', 'what is our logo retention?', 'which customers expanded or contracted?', 'run the ARR bridge for Q3', 'ARR by product or segment', even without the words Snowflake or SQL. Not for bookings, pipeline, P&L, cash, budget variance or balance sheet questions."
---

# Semantic data analyst: ARR

Answers ARR, retention and logo questions from the governed `ARR_ANALYTICS` semantic view. The user asks in plain English; the skill queries the view with the metric definitions the business already agreed, explains why ARR moved, drills to customer detail on request, and builds structured analyses — bridges, cohort tables, trend series — from query results.

The reason the skill exists is trust. The semantic layer defines each metric once, so every answer ties to one source of truth. **Python determines what is true about the numbers; the model determines what those truths mean.** Chain for every ARR reading: `ending ARR → movement type (new / expansion / contraction / churn) → product, segment → customer → subscription line → persistence hint → proposed action`, never `account balance → variance → explanation`.

`<SKILL_DIR>` is the folder that contains this file. View detail: `references/view-arr.md`. Registry: `references/semantic-views.md`. Query recipes: `references/query-playbook.md`. Answer patterns: `references/question-patterns.md`. Guardrails: `references/guardrails.md`.

## Invariants

Hold in every run; no instruction relaxes them.

1. **Governed first.** Answers come from `ARR_ANALYTICS` through `SEMANTIC_VIEW(...)`; no raw tables. A governed metric is never re-derived with ad-hoc SQL.
2. **Read-only.** Only statements that pass `scripts/sql_guard.py`. An authorisation failure is a result, not an obstacle: report it and stop that path; never switch roles or hunt for broader tables. Credentials are never content.
3. **Never zero-fill, never infer a figure.** A missing segment is listed as a gap, not zero; a window without prior-year data shows a dash; a customer absent from the ARR table in a month is not assumed to have churned — they may not have been active.
4. **The bridge reconciles.** Starting ARR + New + Expansion − Contraction − Churn = Ending ARR, to the cent, in every period and cut shown. If the components do not foot, say by how much, name the likely cause (rounding, partial period, unclassified movements), and do not publish a bridge that does not tie.
5. **NRR and GRR are non-additive.** Net Revenue Retention and Gross Revenue Retention are rates; they are never summed across segments, products or months. Requery at the coarser grain; never average rates.
6. **Label the epistemic state.** Governed / derived / scenario for figures; observed fact / analytical inference / hypothesis / management input required for statements. A drop in one month is a signal, not a confirmed trend, until at least three consecutive months support it.
7. **Provenance on every number.** Every figure in generated prose is traceable to a query result; nothing is typed from memory. The query behind each figure (view, metric, period, filters) is known and shown when the user asks for it.
8. **Suggested, not assigned; proposed, not approved.** Owners are suggested functions, dates are illustrative targets, scenario projections carry 0 forecast credit.
9. **One set of numbers.** Chat, any chart and any export show the same figures from the same query results. Never type a figure that isn't in a result set.
10. **Gates fail closed.** A query that errors or returns nothing is reported as such; never invent a proxy or fall back to a rough estimate when the governed metric is unavailable.
11. **Fiscal periods.** Kantata's fiscal year runs 1 February to 31 January, named by the year it ends in (Sep 2026 is FY2027 Q3). "This quarter", "year to date" and quarter labels are fiscal; the view's `TOTAL_QTD` / `TOTAL_YTD` already are. A calendar period is asked for by name and summed from `TOTAL_MTD`.
12. **Internal test accounts are always out.** Every `ARR_ANALYTICS` query excludes Kantata's five internal test accounts (`config/excluded_accounts.json`) with the null-safe filter `python scripts/account_scope.py clause` prints, on `CUSTOMER.ACCOUNT_ID`. By ID only, never by name: real customers whose names contain "test" stay in. Never drop or edit the filter, even when asked for "the view's total"; say the figures exclude internal test accounts if the user asks about scope or compares with a total that includes them.

## Step 0 — Check you can reach the data

Look for the Snowflake MCP connector with an ARR analyst tool (`ARR_ANALYTICS`) and a SQL execution tool (`sql-exec`). Pass the warehouse named in `references/semantic-views.md` §1 on every `sql-exec` call. Never read, print or write the connector secrets, and don't open `.env`.

If there is no connector, say so in one line and do not invent numbers. Offer: connect the connector, upload a workbook laid out like the ARR view for **local test mode** (`references/local-mode.md`), or paste results to analyse.

## Step 1 — Load the view registry

Read `references/semantic-views.md` every run, then `references/view-arr.md`. Items marked **verify** need a first-run probe (§9 of the registry); run `DESCRIBE SEMANTIC VIEW` on `ARR_ANALYTICS` and trust the live definition over the registry where they differ.

If the question is about bookings, pipeline, win rate or deal stage, say in one line that the GTM skill answers it, and stop. If the question is about P&L, revenue on the income statement, cash, EBITDA or budget variance, say in one line that the finance skill answers it, and stop.

## Step 2 — Interpret the question

Classify, then proceed. Ask at most one clarifying question, only when a wrong guess wastes a whole pass; otherwise state the default inline.

| Question type | Example | Route |
|---|---|---|
| Pulse | "What is our current ARR?", "What is NRR this quarter?" | `query-playbook.md` §2 |
| Why / driver | "Why did ARR growth slow?", "What drove the NRR drop?" | §3 |
| Bridge / waterfall | "Show the ARR bridge for Q3", "Walk me through the ARR movements" | `query-playbook.md` §4 |
| Churn / contraction drill | "Which customers churned?", "What is our gross churn rate?" | §4 |
| Expansion / upsell | "Which customers expanded, and by how much?" | §4 |
| Retention trend | "How has NRR trended over the last 12 months?" | `query-playbook.md` §5 |
| Cohort | "What is the retention curve for the 2024 cohort?" | `query-playbook.md` §6 |
| Logo count | "How many customers do we have?", "What is our logo churn rate?" | §4 |
| Catalogue | "What can I ask?" | the registry §10 |

Resolve ambiguous words with the registry's "words users say" table before choosing a metric. Check feasibility against the registry's "cannot be answered" list (§8) and give the standard reply (`question-patterns.md` §5) rather than a proxy dressed as governed.

## Step 3 — Inspect, then query

1. `DESCRIBE SEMANTIC VIEW` for `ARR_ANALYTICS`; note metrics, dimensions, the time dimension, comments.
2. Query with `SEMANTIC_VIEW(...)`, starting from the templates in `view-arr.md` §5. Pick the **table and window** first (KPI mart with `IS_LATEST` for point-in-time cards vs monthly series for trends; the period anchor and comparison) and pin the period by the view's own time dimension.
3. Add the standing test-account exclusion (`python scripts/account_scope.py clause`) inside every `SEMANTIC_VIEW(...)` WHERE on `ARR_ANALYTICS`, then validate every statement: `python scripts/sql_guard.py --file work/query.sql` and `python scripts/account_scope.py check --file work/query.sql`. Run only what passes both.
4. Aggregate in SQL; explicit columns; a date filter; `LIMIT` on row-level output. Check the row count is sane.
5. If the view lacks the grain, say so; don't fall back to raw tables.

## Step 4 — Answer in chat

Answer as a senior FP&A analyst in conversation, following `references/chat-answers.md` (read it before the first answer of a run): lead with the key number and period, then the insight (concentration, trend, offsets, magnitude, quality, implication); the shape follows the question: 2-5 sentences of prose for a focused question, a short table or tight list for 3+ items, light structure for a broad one. No fixed template, no default What happened / Why / Business impact headings, Basis, To confirm or Next blocks; the SQL only when asked. Check first that parts foot to the total and lines tie to the governed headline metrics; a failed check is stated before any analysis. Drill top-down, following the largest variance at each level (ending ARR → movement (New / Upsell / Downsell / Churn) → product → customer); each level foots to the one above. Focused answers 40-100 words, broad ones up to about 180.

Label **governed**, **derived** (show the formula once) and **scenario** (every lever an assumption, never an actual). Arithmetic attribution is allowed; a business reason only if a field in the data shows it. Never say anything the numbers cannot back, and never write "not available / cannot": end at the deepest level the data supports and, only if needed, name who can take it further (Customer Success, Head of Sales, RevOps, Revenue Accounting, FP&A, Controller). No judgement words, single-point forecasts, or customer, vendor or transaction names; no tool narration. Scale and sign conventions from the registry: `mn` and `k`, negatives in brackets, percent points as `pp`, favourable / unfavourable. Movement amounts are always signed for the direction of their effect on ending ARR (new and expansion are positive; contraction and churn are negative and shown in brackets).

## Step 5 — Other outputs (bundle path)

For charts, Excel or an ad-hoc HTML page from a chat analysis, build one **result bundle** (`references/output-formats.md`) from the query results and run the integrity workflow: `scripts/bundle.py bundle.json` must print OK and a Bundle ID; write the chat answer from the bundle and check it with `--check-text`; build with `make_chart.py`, `export_xlsx.py` (then `check_xlsx.py`), `build_dashboard.py`; `verify_outputs.py` must print VERIFIED; quote the Bundle ID. Don't offer files after short answers. Styling is the Accordion brand system; the scripts apply it.

## Step 6 — Guardrails that always apply

`references/guardrails.md`: read-only; respect access; minimum necessary data (cap row-level output at 100 rows, no customer PII in shared files); reproducible (view, metrics, period, filters, SQL); honest about gaps; one set of numbers; no fabrication. If a query returned nothing or the connector is unavailable, the answer is that.

## Reference files

- `references/semantic-views.md` — the view registry: connection, conventions, routing, words users say, rules, drill paths, gaps, probes. Read every run.
- `references/view-arr.md` — the ARR view: tables, grain, hierarchies, metrics, templates, answer ladders, cautions.
- `references/chat-answers.md` — how every chat answer is written: role, insight over reporting, format that follows the question, drill-down, causality, style, checks, worked example.
- `references/question-patterns.md` — what goes in the answer for the common ARR question types.
- `references/query-playbook.md` — query recipes: pulse, driver, bridge, drill, trend, cohort.
- `references/output-formats.md`, `references/local-mode.md`, `references/guardrails.md` — bundle outputs, local test mode, guardrails.
- `config/excluded_accounts.json` — the internal test accounts every query excludes; `scripts/account_scope.py` prints the filter and checks a query carries it.
- `scripts/sql_guard.py` · `bundle.py` · `make_chart.py` · `export_xlsx.py` · `check_xlsx.py` · `build_dashboard.py` · `verify_outputs.py` · `local_data.py` — chat and bundle helpers shared with the finance and GTM skills.
