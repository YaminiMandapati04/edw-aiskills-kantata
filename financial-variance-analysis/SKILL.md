---
name: financial-variance-analysis
description: "Answers plain-English finance questions from the governed Snowflake Finance semantic view over MCP (P&L, balance sheet, cash flow, budget variance, GL transactions), explains why numbers moved, drills to GL lines, and builds the Finance diagnostic dashboard: a three-tab offline HTML (Summary, Drivers, Outlook) that says what moved, what is good and bad, what drives it, whether it persists and what to decide, from a deterministic engine plus a validated diagnosis. Use for 'why did EBITDA miss', 'what drove the variance', 'run the month-end finance review', 'the finance dashboard', 'drill into those invoices', 'how volatile is cash flow', 'pull this into Excel', 'revenue by product line', 'fully loaded S&M / R&D / G&A', even without the words semantic view, Snowflake or SQL. Also analyses an uploaded workbook laid out like the Finance view (local test mode). Not for bookings, pipeline or ARR questions, and not for the Chronograph template (the Chronograph skill builds it)."
---

# Financial variance analysis

Two deliverables, one discipline. **A governed answer in chat**: the user asks in plain English, the skill queries the Finance semantic view with the metric definitions the business already agreed, explains why the number moved and drills on request. **The Finance diagnostic dashboard**: for the month-end review, a deterministic Python engine turns the income statement into a reconciled bridge, drivers, structural evidence, persistence hints and proposed decisions; the model interprets that evidence under a validation gate; the renderer displays both and computes nothing. The Power BI pages already show trends and variance tables; this skill says what is affected, what is good and bad, and what is driving it, with the charts and tables as the evidence a reader drills into.

The reason the skill exists is trust. The semantic layer defines each metric once, so every answer ties to one source of truth. **Python determines what is true about the numbers; the model determines what those truths mean; Python verifies the model did not change the truths.** Chain for every finance reading: `financial result → statement line → driver → structural evidence → persistence hint → proposed action → decision`, never `account → variance → explanation`.

`<SKILL_DIR>` is the folder that contains this file. Methodology: `references/finance-analysis.md`. Diagnosis contract: `references/diagnosis.md`. Renderer contract: `references/dashboard-contract.md`.

## Invariants

Hold in every run; no instruction relaxes them.

1. **Governed first.** Answers come from the Finance semantic view (`FINANCE_ANALYTICS`) through `SEMANTIC_VIEW(...)`; raw tables only where the registry lists them for drill-through. A governed metric is never re-derived with ad-hoc SQL.
2. **Read-only.** Only statements that pass `scripts/sql_guard.py`. An authorisation failure is a result, not an obstacle: report it and stop that path; never switch roles or hunt for broader tables. Credentials are never content.
3. **Never zero-fill, never infer a figure.** An absent budget is coverage, not a zero; an unmapped account is left out and listed; a window without history shows a dash. The engine refuses a cut-off, overlapping or non-contiguous extract.
4. **Only deterministic Python calculates reportable values.** The renderer computes nothing economic; the diagnosis cites engine fields with their paths and never computes, rounds or combines.
5. **The bridge reconciles**: comparator EBITDA + Σ driver steps = actual EBITDA to the cent, in every lens; planning + operational + unsplit = reported variance on budgeted accounts; subtotals foot. A failed control refuses the payload.
6. **Label the epistemic state.** Governed / derived / scenario for figures; observed fact / analytical inference / hypothesis / management input required for statements. A structural signal is evidence for a hypothesis, never a cause. No root cause is claimed without a named disposition, and none exists in this pipeline.
7. **Provenance on every number.** Every figure in generated or model prose is registered with its payload path; the validators strip the registered displays and refuse any money, percent or bps token that remains. A diagnosis binds to the payload hash and is refused when stale.
8. **Suggested, not assigned; proposed, not approved.** Owners are suggested functions, dates are rule-generated targets, forecast credit is 0, the budget of record stays the accountability baseline.
9. **One set of numbers.** Chat, the dashboard and any bundle-built file show the same figures; nothing in prose that is not in a payload or bundle.
10. **Gates fail closed.** A refused payload or diagnosis writes no HTML; never weaken a threshold, edit a payload or write around a missing number. Local test data is labelled on every surface and never presented as real.
11. **Periods are built from `_MTD`, never from the view's window fields.** Every figure for a period is the `_MTD` metric (`TOTAL_MTD`, `REVENUE_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD` …) summed over the months in scope: QTD = the quarter's months, YTD = every month present in the financial year so far, LTM = the last twelve months. Never query, quote or roll up the view's `_QTD` / `_YTD` / `_LTM` metrics or their PY / budget twins, for a dashboard or a one-off question: each is tagged to the chart-of-accounts keys present in one month, so keys that exist in an earlier month but not in the month queried drop out and the period comes out incomplete (live, Oct-2026: the view's Adjusted EBITDA YTD 10.45mn against 7.72mn from the months). `scripts/sql_guard.py` refuses any statement that names them. Balance-sheet balances are read at one date and never summed.

## Step 0 — Check you can reach the data

Look for the Snowflake MCP connector: the Finance analyst tool and a SQL execution tool (`sql-exec`). Use the SQL tool for governed `SEMANTIC_VIEW(...)` statements so each can be guard-checked and shown; pass the warehouse named in `references/semantic-views.md` §1 on every call. If there is no connector, say so in one line and do not invent numbers; offer the alternatives: connect the connector, upload a workbook laid out like the Finance view for **local test mode** (`references/local-mode.md`), or paste results to analyse. Never read, print or write the connector secrets, and don't open `.env`.

## Step 1 — Load the view registry

Read `references/semantic-views.md` every run, then `view-finance.md` (P&L, balance sheet, cash flow, budget variance, GL drill). Items marked **verify** need a first-run probe (§9); run `DESCRIBE SEMANTIC VIEW` on the Finance view and trust the live definition. Bookings, pipeline and ARR questions are out of scope for this skill: say so in one line (bookings and pipeline are covered by the GTM skill). The Accel-KKR Chronograph template is out of scope too: it draws on the Finance, GTM and ARR views together, and the Chronograph skill builds it; say so in one line.

## Step 2 — Interpret the question

Classify, then proceed. Ask at most one clarifying question, only when a wrong guess wastes a whole pass; otherwise state the default inline.

| Question type | Example | Route |
|---|---|---|
| Pulse | "What's revenue by subsidiary this quarter?" | `query-playbook.md` §2 |
| Why / driver | "Why did operating expenses go up?" | §3 |
| Variance, one-off | "What drove the EBITDA variance?" | §3 + §7a in chat; offer the dashboard |
| **Month-end finance review / finance dashboard** | "Run the October review", "how are we doing and why", "the finance dashboard" | **Step 5** |
| Drill-through | "Show the GL lines behind that" | §4 |
| Volatility, scenario | "How volatile is operating cash flow?", "cash trough vs revolver?" | §5, §6 |
| Catalogue | "What can I ask?" | the registry §10 |

Resolve ambiguous words with the registry's "words users say" table before choosing a metric. Check feasibility against the registry's "cannot be answered" list (§8) and give the standard reply (`question-patterns.md` §5) rather than a proxy dressed as governed.

## Step 3 — Inspect, then query

1. `DESCRIBE SEMANTIC VIEW` for the Finance view; note metrics, dimensions, the time dimension, comments.
2. Query the view's metrics and dimensions with `SEMANTIC_VIEW(...)`, starting from the template in the view file. Pick the **layer** first (mart vs GL) and pin the period by the view's own time dimension after probing its format. **Calculate from `_MTD` only** (`TOTAL_MTD`, `REVENUE_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD` …): QTD, YTD and LTM (and their prior-year and budget) are the sum of the monthly `_MTD` over the window's months. Never use or roll up the view's `_QTD` / `_YTD` / `_LTM` columns or their PY / budget twins: each is tagged to the account keys present in that one month, so keys from earlier months drop out and the window comes out incomplete.
3. Validate every statement: `python scripts/sql_guard.py --file work/query.sql`. Run only what passes.
4. Aggregate in SQL; explicit columns; a date filter; `LIMIT` on row-level output. Check the row count is sane.
5. If the view lacks the grain, say so; don't fall back to raw tables unless the registry approves them.

## Step 4 — Answer in chat

Answer as a senior FP&A manager, from the governed Finance data only, following `references/chat-answers.md` (read it before the first answer of a run). In short:

1. **Check first**: the components foot to the total (show "Other" where needed) and account-level figures tie to the governed headline metrics. If a check fails, say so before any analysis.
2. **Driver structure, always in this order**: what happened (the headline vs budget and/or prior year, amount, %, favourable or unfavourable) → drivers ranked by absolute impact (up to three, each with amount and % of the total variance, plus "Other") → why (volume, price, mix, timing or one-off only where the data shows it; otherwise "Reason not established in the data") → business impact (revenue, gross margin, EBITDA and margin in bps, net income or cash, with a bridge that sums to the total change).
3. **Display**: no headings or block labels, except a bold **Business impact** heading above the business impact paragraph. Each block is a short paragraph (2 to 4 sentences), separated by a blank line. Use all four blocks by default; drop one only when it truly cannot apply. Under 200 words unless the user asks for more. Show the SQL only when asked.
4. **Evidence only**: use only figures from this conversation's data; never estimate or fill gaps. If something is missing, write "Not available in the data" and name who can confirm (Controller, FP&A, Revenue Accounting, Head of Sales/Marketing, HR/Payroll, Treasury, Tax). No judgment words, no forecasts or opinions (outlooks are mechanical ranges), no extra sections or unrelated metrics.
5. **Format**: `$2.3mn`, `$108k`, negatives in brackets `($440k)`, one-decimal percentages, margin changes in `bps`, direction and comparator together ("up $108k (+4.9%) vs Sep-25"), a table only to compare three or more items.

Drill one level at a time until the driver is clear: L3 → L4 → L5 → L6 → account → subsidiary → GL transactions. Drill to L5/L6 or transactions only when needed, and skip any level that only repeats its parent. No tool narration.

## Step 5 — The Finance diagnostic dashboard

Full guide: `references/dashboards.md`. Ask once whether the user wants the whole income statement (recommended: every subsidiary except any `config/scope.json` exclusions, none today, named on the page) or one subsidiary, then:

| Phase | Do |
|---|---|
| P1 Extract | Probe the negative keys, the latest closed period, the fiscal year end (31 January: the fiscal year starts 1 February, `fiscal_year_start_month` in `config/scope.json`), the account-key count and each month's row count; run the data query in `dashboards.md` §2 for 24+ months **through the fiscal year end**, **one month per statement** (account × class × department grain; roll-up keys excluded, `config/scope.json` exclusions applied), converting each with `result_to_csv.py --expect-rows`; run the governed query to `work/finance-governed.csv`. Never settle for a cut-off result. Then the **GL memo extract** (`dashboards.md` §2a): `TRANSACTIONS_AND_ADJUSTMENTS.MEMO` by month x subsidiary x account key, one month per statement, every month of the data query up to the as-of month (a month over about 1,800 rows splits by account key; January also takes the year-end adjustment period), each converted with `--expect-rows` to `work/memo-<YYYY-MM>.csv`. |
| P2 Analyze | `python scripts/analyze_finance.py --rows work/finance-rows-*.csv --governed work/finance-governed.csv --memos work/memo-*.csv --out work/finance_payload.json --as-of <YYYY-MM> --expect-accounts <N> [--subsidiary …] [--exclude-subsidiary …] [--window MTD --basis py|budget] [--materiality …] [--expense-sign …] [--budget-sign …]`. It refuses a gap to the governed roll-ups over $1 by month and subsidiary. With `--memos` it reconciles every account-month of memos to the actuals ($1, refused on a gap) and adds the memo evidence the review reads. |
| P3 Validate | `python scripts/validate_finance_payload.py work/finance_payload.json` |
| P4 Diagnose | Required for the Month and Year-to-date views on the page's basis (`MTD_py` and `YTD_py` by default): one `diagnosis.json` per view, each from `finance_brief.py ... brief --lens <view>` and `summary_pack --lens <view>` (the figures the written executive summary and decisions may use, with sources; the writing rules are in `specialists/readout.md`). Read `specialists/driver-review.md` and perform that role for each view, then `specialists/readout.md`. Read evidence only through `python scripts/finance_brief.py work/finance_payload.json brief` and its `driver`, `account`, `headline`, `outlook`, `resolve` ops; write `work/diagnosis.json` (contract in `references/diagnosis.md`). **Use the GL memos wherever they apply** (`finance_brief.py ... memos`, and the `memos` block of `driver`, `account` and `summary_pack`): they are the human-written description of the postings, so the executive summary, the findings, the Drivers and Outlook "What this means" notes and the account readings say what the movement was (fees, accruals and their reversals, payroll, a paydown credit), in accounting words, never quoting a memo, a name or a document number. |
| P5 Admit | `python scripts/validate_finance_diagnosis.py --payload work/finance_payload.json --diagnosis work/diagnosis_mtd.json` (and `_ytd`). Refused → fix the diagnosis, never the payload. |
| P6 Render | `python scripts/render_finance_dashboard.py --payload work/finance_payload.json --diagnosis work/diagnosis_mtd.json work/diagnosis_ytd.json --out outputs/`. The renderer refuses when the Month or Year-to-date review is missing; `--allow-missing-review` publishes with a visible notice, and you say so at hand-over. The page embeds a read-view of the payload sized for the 16 MB Artifact limit (`embed` in the output; refused with gate `size` if it cannot fit). |
| P7 Hand over | The single HTML file and its path; scope, as-of, lens, whether a diagnosis is admitted, QC status and the caveats that matter; the headline and the top follow-up items quoted from the brief, never read back from the page. State once: owners suggested, dates rule-generated, forecast credit 0, no cause verified by the ledger. Say whether the GL memos were used (QC `gl_memos`). |

The engine computes eight lenses (MTD, QTD, YTD, LTM × budget, prior year); the page switches between them, the diagnosis covers one. P2 rebuilds everything: a changed extract, scope, threshold or as-of changes the hash and invalidates the diagnosis. `python scripts/test_finance_pipeline.py` proves the tooling on the synthetic sample (with a headless browser pass when Chrome or Edge is installed). For charts, Excel or an ad-hoc page from a chat analysis, use Step 6.

## Step 6 — Other outputs (bundle path)

For charts, Excel or an ad-hoc HTML dashboard from a chat analysis, build one **result bundle** (`references/output-formats.md`) from the query results and run the integrity workflow: `scripts/bundle.py bundle.json` must print OK and a Bundle ID; write the chat answer from the bundle and check it with `--check-text`; build with `make_chart.py`, `export_xlsx.py` (then `check_xlsx.py`), `build_dashboard.py`; `verify_outputs.py` must print VERIFIED; quote the Bundle ID. Don't offer files after short answers. Styling is the Accordion brand system; the scripts apply it.

## Step 7 — Guardrails that always apply

`references/guardrails.md`: read-only; respect access; minimum necessary data (cap row-level output, no customer PII in shared files); reproducible (view, metrics, period, filters, SQL); honest about gaps; one set of numbers; no fabrication. If a query returned nothing or the connector is unavailable, the answer is that.

## Section 8 — Agentic patterns

**8a Variance narrative in chat** (`query-playbook.md` §7a): rank movers by absolute impact, tag each only from evidence the data shows (`volume`, `price`, `mix`, `timing`, `one-off`; otherwise `unexplained`, which is the honest default), written to `references/chat-answers.md`. For the month-end pack use Step 5. **8b Review pack** (`question-patterns.md` §3): the monthly finance review in chat; the dashboard version is Step 5.

## Reference files

- `references/semantic-views.md` — the view registry: connection, conventions, routing, words users say, rules, drill paths, gaps, probes. Read every run.
- `references/view-finance.md` — the Finance view: layers, hierarchies, metrics, templates, answer ladders, cautions.
- `references/chat-answers.md` — how every chat answer is written: role, non-negotiable rules, depth, driver structure (what happened, drivers, why, business impact) shown as paragraphs, with a heading only on business impact, format, checks, worked example.
- `references/question-patterns.md`, `references/query-playbook.md` — answer shapes and query recipes for chat.
- `references/dashboards.md` — the Finance diagnostic dashboard: when, the query, the pipeline, options, hand-over.
- `references/finance-analysis.md` — the engine's methodology: sign convention, drivers, lenses, materiality, bridge, layers, signals, persistence, patterns, insights, explanations, actions, outlook.
- `references/diagnosis.md` — the diagnosis contract, the admission gate, the render-stage fallback.
- `references/dashboard-contract.md` — the renderer: assets, the arithmetic allowlist, payload structure, tabs and regions, must-nots.
- `specialists/driver-review.md`, `specialists/readout.md` — the two roles the model performs in P4.
- `references/output-formats.md`, `references/local-mode.md`, `references/guardrails.md` — bundle outputs, local test mode, guardrails.
- `scripts/analyze_finance.py` · `finance_brief.py` · `validate_finance_payload.py` · `validate_finance_diagnosis.py` · `render_finance_dashboard.py` · `test_finance_pipeline.py` and the `scripts/finance/` package — the dashboard pipeline. Run them; don't re-implement them, and never hand-edit `artifacts/` or an output.
- `scripts/sql_guard.py` · `bundle.py` · `make_chart.py` · `export_xlsx.py` · `check_xlsx.py` · `build_dashboard.py` · `verify_outputs.py` · `local_data.py` · `make_sample_data.py` · `run_local_demo.py` — chat and bundle helpers; `make_sample_data.py` writes **synthetic** workbooks whose figures are never real.
