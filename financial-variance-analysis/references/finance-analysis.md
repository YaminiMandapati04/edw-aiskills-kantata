# Finance analysis methodology

Reference for `scripts/analyze_finance.py` and the `scripts/finance/` package. The analytical object is not a variance table. It is a reconciled bridge from the comparator's Adjusted EBITDA to the actual, with every step a driver, every material driver decomposed into what the plan assumed and what the month did, every account carrying the structural evidence for a hypothesis, and every material item ending in a proposed decision. The chain is

```
financial result → statement line → driver → structural evidence → persistence hint → proposed action → decision
```

never `account → variance → explanation`. Python establishes the figures; the model (`references/diagnosis.md`) interprets them; nothing in the renderer computes.

## Contents
1. Inputs and scope
2. Sign convention and the statement model
3. Drivers
4. Lenses: windows and comparators
5. Materiality
6. The bridge
7. Analytical layers: planning, operational, coverage
8. Structural signals
9. Persistence hints
10. Patterns
11. Insights and ranking
12. Readout, KPI diagnoses, headline
13. Explanations
14. Actions
15. Outlook
16. Quality checks and what the engine does not do
17. The five-second test

---

## 1. Inputs and scope

One query result (`references/dashboards.md`): one row per fiscal month × subsidiary × account key × class × department, with `TOTAL_MTD`, `TOTAL_PY_MTD`, `TOTAL_BUDGET_MTD` and the L2 to L6 mapping, 24 or more months ending at the as-of month, extended through the fiscal year end for the budget, plus the governed roll-ups by month × subsidiary. The summary roll-up keys in `config/scope.json` are dropped (every subtotal is rebuilt from the accounts so it adds up); any other negative key refuses the build. Scope is every subsidiary except the `config/scope.json` exclusions (none by default; `--exclude-subsidiary`, `--no-default-exclusions`), or one subsidiary with `--subsidiary`; `meta.scope.label` states it ("All subsidiaries (N)", with "excluding …" when any are excluded) and it never changes inside the dashboard.

**Governed reconciliation.** For every month up to the as-of month and every subsidiary in scope, the extract's revenue, Adjusted EBITDA and net income must equal the view's `REVENUE_MTD`, `ADJUSTED_EBITDA_MTD` and `NET_INCOME_MTD` within $1; otherwise the build refuses and names the subsidiary, month and metric (QC `governed_reconciliation`). This catches a dropped key, a cut-off chunk and a roll-up that does not equal its accounts.

**Account grain.** `CHART_OF_ACCOUNT_KEY` is account × class. The engine's account is the account number and name within a subsidiary, with class and department beneath it as drill cells. Where an account's budget is held on some subsidiaries while actuals post on others, the account is compared across subsidiaries (`budget_grain: account`, `budget_held_at`), so the class or entity split of actuals can no longer manufacture variances; signals, run-rates and the planning / operational layers run at that same grain. The as-of month is the latest month with actuals unless `--as-of` says otherwise; later months are budget only.

## 2. Sign convention and the statement model

Every internal figure is **profit-oriented**: positive adds to profit. Revenue po = stored revenue; expense po = minus the cost. The engine detects how expenses and revenue are stored **separately for actuals, prior year and budget** (from the sum of the cost and revenue accounts in each measure) and normalises each measure on its own sign, so a budget load stored with the opposite sign to actuals still compares like with like. It discloses the result (`meta.sign_convention.by_measure`, `qc.sign_convention`, and `qc.sign_mismatch` when the measures differ; open item 9 in the registry). `--expense-sign` declares the actuals and prior-year sign, `--budget-sign` the budget's.

**Budget reliability.** `meta.budget_check` compares the budget with actuals per section (revenue, cost of sales, opex) over the last six closed months. A budget outside 0.5x–2x of actuals, or of the opposite sign after normalisation, is not meaningful for variance work (an incomplete load, a missing account family, a broken sign): QC warns (`budget_reliability`), the page opens on prior year unless `--basis` was given, and every budget view carries a "Budget not meaningful" note naming the failed lines. Variance = actual po − comparator po, so a positive variance is favourable on every line, revenue or cost, and the reader never reverses signs. Display values show costs positive (`display_sign = −1` on cost sections).

Sections come from the mapping: `COA_MAPPING_L3` Revenue → `rev`; Cost of Sales / COGS → `cos`; OpEx → `opex`; `COA_MAPPING_L2` Synergies and Strategic Investments → `syn`; Total Non-Operating (or L3 depreciation, amortization, interest, taxes) → `nonop`. Anything else is **unmapped**: left out of every total and listed in QC, never guessed. Lines: Revenue, Cost of sales, Gross profit, Gross margin %, Operating expenses, Adjusted EBITDA and its margin, Synergies, Non-operating, Net income and its margin. Subtotals foot exactly (validator I1).

## 3. Drivers

A driver is the unit of explanation: an `L4` group inside a section (Recurring Revenue, Non-Recurring COGS …) or, where L4 is empty, the account (number and name, across subsidiaries). Beneath each driver the engine carries the view's `L5` and `L6` levels as sub-groups (`lenses[*].hierarchy[<driver>]`: L5 nodes with their L6 children and accounts), each valued like a driver over the window and footing to its parent to the cent (invariant I13); a level that repeats its parent is collapsed and a member with no activity in the window is left out. The deepest revenue sub-groups are the product lines (`lenses[*].product_lines`, footing to revenue; monthly series in `product_lines` at the top level). Bridge steps, insights, actions and the Statement's expandable rows are drivers; accounts sit beneath them. Ids: `d:<section>:<slug>` or `d:<section>:acct-<number>`.

**Movement.** Every account and driver carries `movement = actual po − comparator po`, with a missing side counted as absent for that period, and `movement_basis`: `both`, `no_comparator` (new this period: activity with no comparator) or `no_activity` (not this period: a comparator with no activity). `variance` stays null when a side is missing (never zero-filled); the driver's variance is the sum of its accounts' movements, so every ranking, share of movement, concentration statistic, "mostly …" sentence, top-N and bridge contribution uses `movement`. Drivers also carry `one_sided_movement` and `two_sided_movement`.

**Drill tables.** `lenses[*].reconciliation[<driver>]`: the accounts by |movement| (top eight, the remainder as one row, the total = the driver's movement, plus the driver's comparator and actual for the mini waterfall) and `by_department`, the same total split top-down into departments, each with its top three accounts. `lenses[*].splits[<account>]`: the account's subsidiary, class and department splits. A split is `comparable` only when every member with activity also carries a comparator; otherwise it shows actuals with `no_comparator_at_level` and foots on the actual, never inventing member variances. The validator foots every table to the cent (I10).

## 4. Lenses

Eight lenses are precomputed at the as-of period: window ∈ {MTD, QTD, YTD, LTM} × comparator ∈ {budget, prior year}. A window is the sum of its months (QTD and YTD follow the fiscal `YEAR` / `QUARTER` columns: Yes Energy's fiscal year is the calendar year, so year to date at September is January to September and the outlook runs to 31 December; without those columns `fiscal_year_start_month` in `config/scope.json` sets them, and QC `fiscal_calendar` states the basis; LTM needs twelve months). Each lens carries its own lines, KPIs, accounts, drivers, per-subsidiary facts, bridge, concentration, patterns, insights, actions, explanations, readout, KPI diagnoses and headline. The primary lens (default MTD vs budget) is the one the dashboard opens on and the diagnosis is written for.

## 5. Materiality

Dollar thresholds disclosed on the page, defaulting to shares of LTM revenue (executive 0.5 %, management 0.1 % and 5 % of the comparator, monitoring 0.03 %), overridable with `--materiality`. Tiers apply to accounts and drivers per lens:

| Tier | Rule | Treatment |
|---|---|---|
| executive | |variance| ≥ executive | leads the conclusions; a diagnosis must name it or list it as unresolved |
| management | ≥ management and ≥ management % (the % test is waived when the comparator is zero or absent) | insight, action, material table |
| monitoring | ≥ monitoring | tracked; an action only when a persistent, step or reversal signal fires |
| immaterial | below | explained in one sentence, no action |

## 6. The bridge

`comparator Adjusted EBITDA → one step per driver (revenue, cost of sales, operating expenses) → actual Adjusted EBITDA`, each step being the driver's movement and carrying its accounts' movements as contributions (with their basis). Control: start + Σ steps = end to the cent, per lens; the validator refuses otherwise. `to_net_income` extends it through synergies and non-operating drivers to the net income variance. Steps are drivers, not accounts; an immaterial driver still appears so the bridge is complete.

## 7. Analytical layers (Month vs Budget only)

For each budgeted account with an eligible run-rate reference:

```
planning     = reference − budget      (how far the plan sits from recent activity: budget realism, not execution)
operational  = actual − reference      (how far the month moved from its own recent level: not proven controllable)
coverage     = actual of an account with no budget line (comparability, never netted into the variance)
unsplit      = variance of a budgeted account with fewer than three trailing months
```

`planning + operational + unsplit = reported variance` on budgeted accounts (validator I5). The **reference** is the trailing six-month trend extended one month (ordinary least squares), falling back to the mean below four months; a growing line therefore does not read as a permanent "operational" surprise. `primary_layer` is the layer with ≥ 60 % of the gross split and the same sign as the reported variance, else mixed. The layers are a diagnostic, never a verified cause, and the dashboard says so wherever they appear. Other windows and the prior-year comparator report `not_calculated` with the reason.

## 8. Structural signals

Tested per account at the as-of month on the profit-oriented series. Each is `fired`, `not_fired` or `not_tested` with a reason; a fired test is evidence for a hypothesis, never a cause. Floors: the larger of the monitoring threshold, twice the trailing residual spread and 3 % of the reference level.

| Signal | Fires when |
|---|---|
| `budget_outside_run_rate` | the budget sits further than the floor from the reference |
| `budget_near_run_rate_edge` | outside the raw trailing range but within the floor of the reference (the weaker signal) |
| `outlier_month` | the month is outside the trailing range and further than the floor from the reference |
| `step_change` | a step entered last month and held this month: the new two-month level differs from the old trend carried forward by more than max(monitoring, 2 σ, 5 %), the entry jump is at least half the step and the second month holds within half of it |
| `reversal_signal` | this month's variance to budget has the opposite sign to last month's and each is at least half the other |
| `persistent_gap` | ≥ 4 of the last 6 monthly variances to budget on the same side, cumulative ≥ max(monitoring, 1.5 % of the six months' budget) |
| `seasonal_echo` | the same month last year moved the same way against its own reference by at least half as much |
| `unbudgeted_activity` / `budgeted_no_activity` | activity with no budget line / budget with no activity |
| `escalator` | six months growing by a constant factor (formula-posted) |
| `fixed_level` / `volatile_series` | trailing coefficient of variation < 3 % / > 30 % |
| `yoy_break` | the month's year-on-year change is 15 points away from its trailing pace and the amount exceeds monitoring |
| `new_account` / `dormant_account` | started posting within three months / stopped posting |

## 9. Persistence hints

A rule output per account, in priority: `coverage` (no budget line) → `recurring_level_change` (step held) → `timing_reversal` (reversal) → `persistent` (persistent gap) → `seasonal` → `one_off_candidate` (excursion) → `undetermined`. Confidence counts corroborating signals (three or more high, two medium, else low). The hint feeds the driver insight, the action's forecast state and the Outlook persistence view; it is a proposal with forecast credit 0.

## 10. Patterns

Outcome-level readings per lens, each with the evidence it used: `in_line`, `revenue_led` / `cost_led` (≥ 60 % of the gross step mass), `concentrated_variance` (top three accounts ≥ 50 %) / `broad_based_variance`, `margin_earnings_divergence` (gross and EBITDA margin opposite by ≥ 25 bps), `cost_growth_outpacing_revenue` / `operating_leverage`, `mix_shift` (recurring share moved ≥ 1 point), `below_the_line_swing`, `headline_masks_deterioration` / `headline_understates_performance` (reported and operational signs disagree), `budget_baseline_dominant` / `execution_dominant`, `unbudgeted_activity_material`, `offsetting_variances`. A pattern's reading is always an inference.

## 11. Insights and ranking

One insight per material driver (observed facts, at most four inferences from the lead accounts' signals, then the management input the ledger cannot supply, plus a causal gap: known, ruled out, question) and outcome insights for EBITDA, margin quality, concentration, below the line and the full year. Ranking is auditable in `readout.ranking`:

```
score = ln(1 + magnitude / management_abs) × persistence weight × decision relevance × confidence
```

Driver persistence weights: recurring 1.0 · persistent 0.9 · coverage 0.9 · one-off candidate 0.8 · seasonal 0.7 · undetermined 0.7 · timing 0.6. Outcome insights carry lower weights (EBITDA 0.4, or 0.9 when the headline masks or the plan baseline dominates; margin 0.4; concentration 0.35; below the line 0.6; full year 0.9) so a driver leads unless the headline misleads. Ties: |amount|, then id.

## 12. Readout, KPI diagnoses, headline

**Executive summary** (`lenses[*].summary`): the lead (net income, the primary driver it is led by, and what it means), up to six insights in narrative order (concentration as the why, trend, persistence, margin, mix, budget bias) and the full-year bullet, each with `head`, `text`, its own `numbers[]`, a `claim` and a `drill {level, ids, support}` (section › L4 drivers › accounts; driver; line; outlook). The lead is chosen from the numbers: below-the-line when the non-operating move exceeds the EBITDA move in the direction of net income; revenue-led only when revenue is the largest contributor; "growth outpacing cost" only when Adjusted EBITDA and its margin both rose, otherwise "growth, partly absorbed by cost". The margin bullet names its window and, when the latest month moved the other way, reads "margin mixed". The trend bullet reads net income in the month against the quarter to date (once the quarter holds more than one month) and the year to date on the same basis: `trend_continuing` (same side, all material), `trend_reversal` (a material month against a longer window on the other side), `trend_new` (the longer windows not material) or `trend_easing` (the month not material while a longer window is); it says whether the month's largest driver sits on the same side. The engine never names a business cause the ledger cannot show: where the top line moved it says the data model does not carry customer, volume or price data. **Drill-through narratives** (`explanations.drivers[]`, at most 75 words): what changed; `Parent:` how the driver moves its section line (most of it, part of it, offsetting it); `Trend:` the same driver in the month, quarter and year to date with the same reading; the engine inference; `Next:`. Lower-priority parts drop first to keep the limit. Line explanations add the same `Trend:` sentence. The validator re-checks every claim against the lens figures (I11).

The readout answers five questions (ahead or behind, what drove, quality, temporary or structural, full-year implication) and assigns the three roles the Summary shows: `current_period_driver` (the top driver), `performance_quality` (margin, below the line, concentration or EBITDA, in that preference), `forward_looking` (the full-year insight, else a persistent or step driver). Each KPI carries a diagnosis: answer → decomposition → largest drivers → outlook → questions. The headline is a template with pinned slots (EBITDA actual, comparator, variance and %, the three section variances, material count, top-three share, follow-up count, and the mechanical full-year figures when the budget allows); the diagnosis may rephrase it but every slot display must survive verbatim.

## 13. Explanations

A deterministic baseline text for every account (`concise` for tables, `expanded` for the drawer, `summary` for lists), every driver, every statement line and the lens as a whole. The reasoning sequence: result and comparator → run-rate position → fired signals → what the evidence does not establish (volume, price, headcount, rate; transaction detail needs the GL) → the next step with its suggested owner and rule-generated date. Status is seven states, never one Boolean: evidence observed · hypothesis (the persistence hint) · disposition none recorded · cause not verified · management decision none recorded · action suggested · forecast not approved. Every figure in every text is registered with its path (`numbers[]`) and the validator strips the registered displays and refuses any money, percent or bps token that remains.

## 14. Actions

One consolidated, ranked item per driver that is material, carries material unbudgeted activity, or is monitored with a persistent / step / reversal signal. The primary rule is chosen in planning-first order when the driver's planning layer exceeds its operational layer, else operational-first:

| Rule | Category | Default owner | Weight | Action |
|---|---|---|---|---|
| budget_outside_run_rate | forecast assumption | FP&A | 1.0 | confirm whether the budget level is a deliberate plan or a carried-forward level; propose a documented review (the budget of record stays the baseline) |
| step_change | forecast assumption | section owner | 0.9 | confirm what changed and the new monthly level; carry it only once confirmed |
| persistent_gap | management decision | section owner | 0.9 | decide structural (re-plan) or execution (corrective action with an owner) |
| outlier_month | investigation | section owner | 0.8 | identify the postings; one-off, timing or new level |
| unbudgeted_activity | accountability | FP&A | 0.8 | add a budget line or correct the mapping |
| reversal_signal | investigation | Controller | 0.7 | check cut-off and accruals across the two months |
| budgeted_no_activity | investigation | section owner | 0.7 | delayed, cancelled or coded elsewhere |
| yoy_break | investigation | section owner | 0.6 | explain the break in pace |
| seasonal_echo / budget_near_run_rate_edge | forecast assumption | FP&A | 0.5 | confirm phasing / the plan assumption |
| escalator / dormant_account | accountability | Controller | 0.4 | confirm the mechanism / the mapping |
| none fired | investigation | section owner | 0.6 | the variance needs a named cause from the owner |

Section owners are suggested functions: Revenue / FP&A lead; Operations finance lead; Function head with FP&A; Integration / PMO lead; Controller / Treasury. Dates are the period end plus 30 days, labelled rule-generated. Ranking: exposure (|reported variance|) × decision relevance (the rule weight) × unresolved risk (1.0, no dispositions exist) × evidence strength (confidence). Each item also carries `ask`: one question built from facts for the driver: its movement and comparator, where it sits (the leading department, then the lead account with its subsidiary), whether that is new or stopped (one-sided), recurring (persistent gap, with the months) or a one-off (a one-sided account booked in a single month of the window: "confirm it is a one-off (and non-cash below EBITDA) and exclude it from the run-rate"), the decision to make and the suggested owner, every figure registered. Exposure is the driver's |movement|. Each item carries the question to resolve, the required evidence, the expected output and a forecast block with credit 0: a proposed monthly effect and remaining-months effect only for recurring or persistent hints, and a note that a planning-gap item restates a gap the mechanical outlook already carries.

## 15. Outlook

For revenue, Adjusted EBITDA and net income: year to date actual and budget; the full-year budget when the extract carries every period of the fiscal year (else the note says to extend the query); the mechanical outlook = year to date + remaining months × the trailing three-month average, with the sensitivity to three other rules (trailing six, latest month flat, twelve-month trend) and the spread between them; the gap to the full-year budget and to the prior full year. Identity: FY budget + YTD variance + remaining effect = mechanical (validator I8). The persistence view lists the material drivers of Month vs Budget with their hint, the proposed treatment (carry, reverses, none) and the remaining-months effect if the hint holds, all with forecast credit 0. Nothing declared by management is included because nothing is supplied.

## 16. Quality checks and what the engine does not do

`qc.checks`: governed reconciliation, scope exclusions, open months skipped, sign convention (detected or declared), unmapped accounts, months of history, prior-year coverage, budget coverage, fiscal-year budget presence, data freshness, completeness (`--expect-accounts`), data mode, scope. Any warning makes the run `QUALIFIED`; the banner and the QC drawer carry the caveats.

Disabled capabilities, shown as such rather than as empty charts: price / volume / mix (no quantity grain in the marts), FX (converted amounts only), location (subsidiary, class and department are carried), L5 / L6 (not in the view), transactions (drill through the TRANSACTIONS table in chat and tie back to the mart figure).

## 17. The five-second test

From the Summary alone a reader can state: whether Adjusted EBITDA is ahead or behind and by how much; the three largest drivers; whether each is a one-off, persistent or a new level; what the mechanical full year looks like; and what management is being asked to decide. If any of the five needs a drawer, the Summary is wrong, not the reader.

## Manual adjustments

The extract carries `INCOME_STATEMENT.ADJUSTMENT_TYPE`. Adjustment rows stay inside the account totals (the governed tie-out needs them). `frame.adjustments` also records, per type and month, the actual impact on revenue, Adjusted EBITDA and net income, with components (the capitalisation keys by name, pro forma by L4). Every lens has `adjustments` with these fields:
- `types[]`: id, label, class `pro_forma` | `capitalisation`, `actual` {rev, ebitda, ni, months, components[]}, the prior-year `comparator` and `ebitda_variance` on the prior-year basis.
- `total_ebitda_impact` and `ebitda_excluding_adjustments`.
- `basis_note` and `rule`.

QC `adjustments_included` names each type and its months. It warns when capitalisation and its reversal do not net to zero at net income within $1 in a month. `finance_brief.py PAYLOAD adjustments --lens <id>` and the `adjustments` block of `brief` / `summary_pack` give the figures with their source paths. Capitalisation is a treatment, not performance: a driver moved by `-8001` / `-8002` is read as "capitalisation charged inside Adjusted EBITDA, reversed below it", never as a saving or overspend.

