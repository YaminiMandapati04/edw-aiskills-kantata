---
name: pipeline-and-booking-risk
description: "Builds the monthly GTM diagnostic dashboard and answers any go-to-market question from the governed Snowflake GTM semantic view over MCP. The dashboard is a three-tab offline HTML (Pipeline, Bookings, Outlook) from a deterministic engine: it opens on pipeline risk (deals not closing, customers stuck in a stage, high-value and lost deals, in recurring ACV), bookings growth, drivers, the pipeline by close quarter and what to decide. Questions: bookings (new sales, seat expansion, non-recurring, deals, customers), open pipeline (unweighted), pipeline created, win rate, won and lost ACV, days in stage, at-risk deals. Fiscal year runs February to January. Use for 'run this month's GTM dashboard', 'the GTM review', 'which deals are stuck', 'why did bookings go up', 'what is closing next quarter', 'where do we lose deals', 'pull this into Excel', even without the words Snowflake or SQL. Also reads a workbook laid out like the view (local test mode). Not for P&L, cash, budget, ARR or retention."
---

# Pipeline and Booking Risk

The skill has two jobs, in this order of importance:

1. **The recurring GTM dashboard (main deliverable, Part A).** Every month, once the month closes, it builds a single offline HTML page (Summary, Drivers, Outlook) and says what changed since last month. The page opens on **pipeline risk**: deals not closing, customers stuck in a stage against the median, high-value deals and lost deals, sized in recurring ACV. A deterministic Python engine also turns bookings and pipeline into a reconciled bridge, drivers, concentration, conversion, open pipeline by fiscal close quarter and proposed decisions; the renderer displays them and computes nothing. The run can be unattended: it asks no questions, and it either writes the month's page or stops with a reason.
2. **Answer any GTM question (Part B).** The user asks in plain English; the skill queries `GTM_ANALYTICS` with the metric definitions the business already agreed, explains why bookings or pipeline moved and drills on request.

The Power BI GTM pages already show trends and tables; this skill says whether growth is real and repeatable, what drives it, and what the pipeline could deliver in the next quarters.

The reason the skill exists is trust. The semantic layer defines each metric once, so every answer and every page ties to one source of truth. **Python determines what is true about the numbers; the model determines what those truths mean; Python verifies the model did not change the truths.** Chain for every GTM reading: `bookings result → measure (new sales / seat expansion / non-recurring) → product, subsidiary → customer and deal → persistence → pipeline by close quarter → proposed action → decision`.

**Kantata facts that hold everywhere.**
- **Recurring bookings** are Salesforce won New Sales and Seat Expansion opportunities (`BOOKING_METRIC = 'Recurring Services'`, blended ARR, on the close date), split by `BOOKING_LINES.OPPORTUNITY_TYPE` into *new sales* and *seat expansion*. **Non-recurring bookings** are NetSuite non-recurring revenue from the income statement (`'Non-Recurring'`, by subsidiary, on the period end date; no account, product or opportunity). The view's `ARR (New)` / `ARR (Upsell)` metrics are always 0: never use them.
- **Pipeline values are unweighted.** Never use `WEIGHTED_*` metrics or stage probability. The view holds **no pipeline or bookings target**: there is no coverage ratio, floor or "vs target" anywhere.
- **Fiscal year** 1 February to 31 January, named by the year it ends (February 2026 to January 2027 = FY2027); fiscal quarters Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan (labels `FY2027-Q3`). Every QTD and YTD is fiscal, built from monthly `_MTD` or the lines. Never use the marts' own `_QTD` / `_YTD` / `_LTM` (rolled up from one month's keys they come out incomplete; the `BOOKINGS_OVERVIEW` ones are also calendar); `DIM_DATE` quarter / year are **calendar** too.

`<SKILL_DIR>` is the folder that contains this file. View detail: `references/view-gtm.md`. Dashboard: `references/dashboards.md` (the recurring run is §7), `dashboard-contract.md`, `diagnosis.md`.

## Invariants

Hold in every run; no instruction relaxes them.

1. **Governed first.** Answers come from `GTM_ANALYTICS` through `SEMANTIC_VIEW(...)`; no raw tables. A governed metric is never re-derived with ad-hoc SQL.
2. **Read-only.** Only statements that pass `scripts/sql_guard.py`. An authorisation failure is a result, not an obstacle: report it and stop that path; never switch roles or hunt for broader tables. Credentials are never content.
3. **Never zero-fill, never infer a figure.** A window without prior-year data shows a dash; there is no bookings plan or pipeline target, so bookings and pipeline compare to prior year or prior period only.
4. **Only deterministic Python calculates reportable values.** The renderer computes nothing economic; a diagnosis cites engine fields with their paths and never computes, rounds or combines.
5. **The hierarchy holds and bridges reconcile.** Total = Recurring + Non-recurring; Recurring = New sales + Seat expansion; contributors plus "all other" equal the total; a bookings bridge reconciles its comparator (on the dashboard, the prior quarter) + Σ steps = actual to the cent. Never add across `METRIC_NAME`.
6. **Bookings and pipeline are different worlds.** Pipeline, won and lost ACV (Salesforce opportunities) are never added to bookings, and non-recurring revenue (NetSuite) is added to recurring bookings only in the governed Total Bookings; a labelled reconciliation is allowed.
7. **Label the epistemic state.** Governed / derived / scenario for figures; observed fact / analytical inference / hypothesis / management input required for statements. A signal is evidence for a hypothesis, never a cause. "Stalled" is always a labelled stage-age proxy: the view has no activity data.
8. **Provenance on every number.** Every figure in generated or model prose comes from a query result, a payload or a bundle; nothing is typed in from memory.
9. **Suggested, not assigned; proposed, not approved.** Owners are suggested functions, dates are rule-generated targets, scenario credit is 0.
10. **One set of numbers; gates fail closed.** Chat, the dashboard and any bundle-built file show the same figures. A refused payload, diagnosis or bundle produces no file; never weaken a check. Local test data is labelled on every surface and never presented as real.
11. **Periods are built from `_MTD`, never from the view's window fields.** Bookings for a quarter, year to date or the last twelve months are the monthly `_MTD` metric (`TOTAL_BOOKINGS_MTD` …) or the booking lines summed over the months in scope; prior year is the same months a year earlier (or `_PYMTD` summed). Open pipeline, a point-in-time figure, is read from `_MTD` / `_PYMTD` at one as-at date. Never query, quote or roll up the view's `_QTD` / `_YTD` / `_LTM` metrics or their PY twins, for a dashboard or a one-off question: each is computed on the keys present in one month, so rolled-up windows come out incomplete. `scripts/sql_guard.py` refuses any statement on `GTM_ANALYTICS` that names them.

## Step 0 — Check you can reach the data

Look for the Snowflake MCP connector: a GTM analyst tool and a SQL execution tool (`sql-exec`). Use the SQL tool for governed `SEMANTIC_VIEW(...)` statements so each can be guard-checked and shown; pass the warehouse named in `references/semantic-views.md` §1 on every call. Never read, print or write the connector secrets, and don't open `.env`.

If there is no connector:
- **Recurring run:** stop with "no Snowflake connector; no page built". Never fall back to local data.
- **Interactive:** say so in one line and don't invent numbers. Offer the alternatives: connect the connector, upload a workbook laid out like the view for **local test mode** (`references/local-mode.md`), or paste results to analyse.

## Step 1 — Load the view registry

Read `references/semantic-views.md` every run, then `references/view-gtm.md`. Items marked **verify** need a first-run probe (§9); run `DESCRIBE SEMANTIC VIEW` and trust the live definition. If the question is about revenue, margins, cash, budget, ARR, churn or retention, say in one line that the finance or ARR skill answers it, and stop.

## Step 2 — Route the request

| Request | Example | Route |
|---|---|---|
| **Recurring or requested dashboard** | a scheduled monthly run, "run this month's GTM dashboard", "the Q4 GTM review", "the bookings dashboard", "a management view of bookings and pipeline" | **Part A** |
| Any GTM question | "Why did bookings go up?", "Which deals are stuck?" | **Part B** |

A question answered in chat ends with one line offering the dashboard. A dashboard request is never answered with a chat analysis or the bundle-path review pack.

---

# Part A — The recurring GTM dashboard

The main deliverable. Specification: `references/dashboards.md`; the recurring run is §7.

## A1 — Run it

Run these steps in order. Each one either passes or stops the run with a one-line reason and writes nothing. A stop is a result: never fall back to an older month, a partial extract or local data.

1. **Pre-flight** (`dashboards.md` §7 steps 1–2):
   - The view definition is `assets/semantic_view.yml` (exported from PROD); the probes in `dashboards.md` §7 step 1 confirm it is live.
   - The run's month must have closed in NetSuite as well as in Salesforce. `BOOKINGS_OVERVIEW.IS_LATEST` can be a month whose non-recurring revenue is not closed yet (October 2026 showed $417 while Finance closed September); the build then steps back a month on its own (QC `as_of_complete`).
   - `<RUN>` is the previous month on a scheduled run; on a request, it is the latest month NetSuite has closed unless the user names one.
2. **Extract.** Run the governed statements in `dashboards.md` §2, each guard-checked, into a fresh `work/gtm-live/`. Save every result whole (the sql-exec JSON as returned, or CSV) under the file name §2 gives.
   - Scope is all products and subsidiaries unless the request names one product; don't ask.
   - The SQL tool caps large results. If a result reports more rows than it returned, split it (booking lines by quarter) and run it again. The loader refuses capped, overlapping or gapped extracts.
3. **Build.** `python scripts/build_gtm_dashboard.py --extracts work/gtm-live --expect-as-of <RUN> [--window …] --payload-out work/gtm_payload.json`, then the AI review (A2) and `--diagnosis work/diagnosis_qtd.json`.
   - The loader (`scripts/gtm/live.py`) maps the rows.
   - The engine (`scripts/gtm/engine.py`) computes every figure and ties the booking lines to the `BOOKINGS_OVERVIEW` monthly `TOTAL_BOOKINGS_MTD` (every month, to $1) and the open pipeline to the `PIPELINE_OVERVIEW` card.
   - The renderer (`artifacts/gtm_analytics/`) writes `outputs/pipeline_risk_readout.html` (a fixed name, no month: every run rewrites the same file).
   - `scripts/gtm/compare.py` reads the previous month's page (kept as `outputs/previous/pipeline_risk_readout.html` when a new month's run replaces it) and adds `since_last`.
   - The script prints one JSON line (headline, QC checks, `since_last`, page `bytes`). A refusal produces no file: fix the extract, never the check. A page over the 16 MB Artifact limit is refused too.
4. **Hand over** the single HTML file and its path (`dashboards.md` §5). Quote figures only from the printed JSON or the payload (`--payload-out`).
   - Lead with the pipeline-risk story from the payload's `risk.insights` (deals not closing and their recurring ACV, customers stuck in a stage and the recurring ACV at stake, high-value deals at risk) and the lost deals for the window. Then the scope, the as-of month, the QC status and any WARN checks.
   - Then **Since last month**: the `since_last` lines, or "first run".
   - Say whether the AI review was admitted ("AI reviewed" on the page) and for which view; state the limits once: owners suggested; dates rule-generated; scenario credit 0; stage age is a proxy.

Keep `outputs/` between runs: the previous page is the record the next run compares against. To run this on a schedule, set up a monthly routine a few working days into the month that invokes this skill with "run this month's GTM dashboard".

## A2 — Local test mode and what is still to build

Without a connector (interactive only), `python scripts/build_sample_dashboard.py [--workbook <file>]` builds the same page from a workbook laid out like the view, labelled LOCAL TEST DATA. The layout is in `artifacts/gtm_analytics/wireframes/`.

AI review (`references/diagnosis.md`): after the build writes the payload (`--payload-out work/gtm_payload.json`), perform `specialists/driver-review.md` then `specialists/readout.md` for the opening view, reading evidence only through `scripts/gtm_brief.py`; admit it with `scripts/validate_gtm_diagnosis.py` and render with `scripts/render_gtm_dashboard.py --diagnosis`. The page is not published without it unless `--allow-missing-review`, and then says "This view not AI reviewed".

---

# Part B — Answer any GTM question

## B1 — Interpret the question

Classify, then proceed. Ask at most one clarifying question, only when a wrong guess wastes a whole pass; otherwise state the default inline.

| Question type | Example | Route |
|---|---|---|
| Pulse | "How are bookings tracking?", "What's open pipeline?" | `query-playbook.md` §2 |
| Why / driver | "Why did bookings go up?", "Why is pipeline created down?" | §3 |
| Drill-through | "Show the deals behind that", "Which deals are in 06 - NEGOTIATE?" | §4 |
| Trend, lumpiness | "Are bookings lumpy?", "Is pipeline creation slowing?" | §5 |
| Pipeline risk | "Which open pipeline looks at risk?" | `question-patterns.md` §2b |
| Won vs booked | "Is won pipeline showing up as bookings?" | `query-playbook.md` §6 |
| Catalogue | "What can I ask?" | the registry §10 |

Resolve ambiguous words with the registry's "words users say" table before choosing a metric. Check feasibility against the registry's "cannot be answered" list (§8) and give the standard reply (`question-patterns.md` §5) rather than a proxy dressed as governed.

## B2 — Inspect, then query

1. `DESCRIBE SEMANTIC VIEW` for `GTM_ANALYTICS`; note metrics, dimensions, time dimensions, comments. Trust the live definition over `assets/semantic_view.yml` if they differ.
2. Query with `SEMANTIC_VIEW(...)`, starting from the templates in `view-gtm.md` §5. Pick the **table** first (KPI mart with `IS_LATEST` vs `*_ASAT` trend vs line tables) and pin the period by the table's own time dimension. **Calculate from `_MTD` only** (`TOTAL_BOOKINGS_MTD`, `_PYMTD` …): bookings QTD, YTD and LTM are the sum of the monthly `_MTD` over the window's months (fiscal, from 1 February), or of the lines; open pipeline is a point-in-time `_MTD` / `_PYMTD` at one as-at date. Never use or roll up the marts' `_QTD` / `_YTD` / `_LTM` columns or their PY twins: each is computed for one month's keys, so rolled up the window comes out incomplete (the bookings ones are also calendar).
3. Validate every statement: `python scripts/sql_guard.py --file work/query.sql`. Run only what passes.
4. Aggregate in SQL; explicit columns; a date filter; `LIMIT` on row-level output. Check the row count is sane.
5. If the view lacks the grain, say so; don't fall back to raw tables.

## B3 — Answer in chat

Answer as a senior FP&A manager, from the governed GTM data only, following `references/chat-answers.md` (read it before the first answer of a run). Check first that the components foot to the total and that lines tie to the governed headline metrics; if a check fails, say so before any analysis. The content always comes in this order: what happened (the headline vs prior quarter and/or prior year, amount, %, favourable or unfavourable) → drivers ranked by absolute impact (up to three, each with amount and % of the total change, plus "Other") → why (volume, price, mix, timing or one-off only where the data shows it; otherwise "Reason not established in the data") → business impact (recurring bookings, recurring share in bps, open pipeline or win rate, with a bridge that sums to the total change). Show no headings or block labels, except a bold **Business impact** heading above the business impact paragraph: each block is a short paragraph (2 to 4 sentences), separated by a blank line, and all four blocks are used by default, dropping one only when it truly cannot apply. Under 200 words unless the user asks for more; show the SQL only when asked.

Drill one level at a time until the driver is clear, and skip any level that only repeats its parent: total bookings → recurring / non-recurring → new sales / seat expansion → product or subsidiary → account → opportunity; or open pipeline → stage → fiscal close quarter → product, source, region, owner → opportunity. Use only figures from this conversation's data. If something is missing, write "Not available in the data" and name who can confirm (Head of Sales/Marketing, RevOps, Revenue Accounting, Controller, FP&A). No judgment words, no forecasts or opinions, no extra sections or unrelated metrics, no tool narration. Scale and sign conventions from the registry: `mn` and `k`, negatives in brackets, percentage points as `pp`, favourable / unfavourable.

## B4 — Other outputs (bundle path)

For charts, Excel or an ad-hoc page from a chat analysis (not the GTM dashboard: that is Part A), build one **result bundle** (`references/output-formats.md`) from the query results and run the integrity workflow: `scripts/bundle.py bundle.json` must print OK and a Bundle ID; write the chat answer from the bundle and check it with `--check-text`; build with `make_chart.py`, `export_xlsx.py` (then `check_xlsx.py`), `build_dashboard.py`; `verify_outputs.py` must print VERIFIED; quote the Bundle ID. Don't offer files after short answers. Styling is the Accordion brand system; the scripts apply it.

## B5 — Agentic patterns

**Pipeline risk** (`question-patterns.md` §2b): past-due close dates and stage age beyond the stage's usual stay, measured against the data's own as-of date, each labelled a proxy. **Bookings risk / leakage** (`question-patterns.md` §2c, `query-playbook.md` §6): the view carries no sales-order or invoice facts, so invoice-level leakage is not answerable; compare won opportunity ACV with recurring bookings by month and product, labelled derived and candidate. **Review pack** (`question-patterns.md` §3a): a bookings and pipeline review on the bundle path, only when the user asks for that pack rather than the dashboard.

---

## Guardrails that always apply

`references/guardrails.md`: read-only; respect access; minimum necessary data (cap row-level output, no customer PII in shared files); reproducible (view, metrics, period, filters, SQL); honest about gaps; one set of numbers; no fabrication. If a query returned nothing or the connector is unavailable, the answer is that.

## Reference files

- `references/semantic-views.md` — the registry: connection, conventions, routing, words users say, rules, drill paths, gaps, probes. Read every run.
- `references/view-gtm.md` — tables, grain, joins, hierarchies, metrics, templates, answer ladders, cautions.
- `references/dashboards.md`, `references/dashboard-contract.md`, `references/diagnosis.md` — the GTM dashboard: queries, build, options, hand-over, the recurring run (§7), the page contract and the diagnosis to come.
- `references/chat-answers.md` — how every chat answer is written: role, non-negotiable rules, depth, driver structure (what happened, drivers, why, business impact) shown as paragraphs, with a heading only on business impact, format, checks, worked example.
- `references/question-patterns.md`, `references/query-playbook.md` — what goes in the answer and the query recipes for chat.
- `specialists/driver-review.md`, `specialists/readout.md` — the two roles the model performs in P4.
- `references/output-formats.md`, `references/local-mode.md`, `references/guardrails.md` — bundle outputs, local test mode, guardrails.
- `scripts/build_gtm_dashboard.py` (live) and `scripts/build_sample_dashboard.py` (local) build the page. They use `scripts/gtm/`: `live.py` loader, `engine.py`, `render.py`, `compare.py` (since last month) and `common.py` (formatting and provenance helpers).
- `scripts/sql_guard.py` · `bundle.py` · `make_chart.py` · `export_xlsx.py` · `check_xlsx.py` · `build_dashboard.py` · `verify_outputs.py` · `local_data.py` · `make_sample_data.py` · `run_local_demo.py` — chat and bundle helpers; `make_sample_data.py` writes a **synthetic** workbook whose figures are never real.
