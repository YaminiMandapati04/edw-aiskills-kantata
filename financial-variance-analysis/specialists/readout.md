# Role: Readout

Load this file and perform the role yourself after the driver review, for the same lens. You turn the admitted-ready findings into the reading shown first: three complementary conclusions, the decision asks, the driver stories, the structural conclusions, the forecast assumptions, the lead actions and the per-account interpretations shown on the Statement tab. You create ordering, roles and wording **only from the findings and the payload**; you cannot add a finding, change what a finding claims, or upgrade a hypothesis.

## How you read evidence

```bash
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json brief --lens MTD_budget      # readout, top_three, actions
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json headline --lens MTD_budget   # the pinned slots
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json outlook
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json kpis --lens MTD_budget
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json resolve --path "..."
```

Plus the `findings[]` you already wrote. When the payload carries GL memos, `summary_pack` has `memo_evidence` (the net-income themes and the lead drivers' themes and categories, every figure with its source) and `finance_brief.py ... memos` the full set, including the run-rate months (`memos.run_rate`) the Outlook rests on.

## Narrative standard

The three conclusions are **complementary**, one per role, never three phrasings of one point:

| Role | Covers | Typical lead |
|---|---|---|
| `current_period_driver` | what drove the period: the largest driver finding, in money, with the planning / operational reading where available | the top-ranked driver finding |
| `performance_quality` | the quality of the result: margin, mix, concentration, cost growth versus revenue, offsetting moves, a headline that masks or understates | the margin or concentration pattern, or a second driver |
| `forward_looking` | what it means for the rest of the year: persistence, the mechanical outlook, what must be confirmed before any forecast moves | the persistent or step-change finding, or the full-year insight |

Each conclusion carries: a business headline (`text`, with every figure registered), the `status` (favorable / unfavorable / mixed), `persistence`, the `response` (what management should do or decide, with the suggested owner function), and the `finding_ref` it rests on. State plainly which parts are observed, which are interpretation and which are unverified, using only the states the finding already carries.

**Write each conclusion as an insight, not a data line.** The conclusions become bullets in the dashboard's executive summary (renderer 1.3.0), beside the engine's own insights, inside a hard limit of five bullets. So:
- `insight` (optional but recommended): the bold lead of the bullet, at most eight words, no figures, no causal wording. It states the conclusion: "A recurring gap, not noise", "Revenue quality is improving", "October is overstated".
- `text`: observation, then what it means. The amounts are evidence, never the point. Not "Marketing Programs is $143k against budget $105k: ($38k)", but "Marketing Programs ran $38k over budget in a single month outside its usual range, so it reads as a one-off rather than a new spending level." One or two sentences.
- `response`: the action in a short clause, starting lower-case after the dashboard's colon ("confirm the October royalty accrual before reporting the month; suggested owner Controller").
- Never repeat what the engine summary already says (the net-income lead, the full-year run-rate); add what only review can: the item behind a movement, what to exclude from the run-rate, what to confirm first.
- `readout.headline` no longer takes a summary bullet; it shows in the net income detail panel.

**Decision asks** (at most three): one question each, for a suggested owner function, bound to a finding and, where one exists, to the engine's follow-up item (`action_refs`). A decision ask is a question management answers, not an instruction the dashboard issues.

**Driver stories** (at most three), **structural conclusions** (at most three), **forecast assumptions** (at most five) and **lead actions** (at most three) are statements with registered numbers. A forecast assumption names the mechanical outlook figure it rests on and says that nothing declared by management is included and that forecast credit is 0.

**Account interpretations** (at most ten) and **driver stories** are the drill-through narratives: at most 75 words each (the gate refuses longer). Keyed by account id, an interpretation replaces the engine baseline in the account detail drawer. Each answers, in order: what changed (amount against the comparator); what caused it, as far as the data shows (the sub-group, department or posting; an operational cause only as a hedged possibility, as above); how it moves the parent metric (most of it, part of it, or offsetting it: `hierarchy[]` and the driver's `Parent:` sentence); whether it continues an existing trend or is new (`trend{}` and the driver's `Trend:` sentence); and what it implies for the business. Keep the parent-child relationship explicit at every level. Keep the baseline's scope (account-wide, this lens) and add only what the findings support.

**Headline**: optional. You may rephrase the engine headline, but every pinned slot display must survive verbatim (`headline` op lists them); the gate refuses a dropped or re-rounded slot.

**QC**: `qc.business_cause` says in one sentence how much of the material movement rests on an attested cause (none, unless a named disposition exists) versus open hypotheses; `qc.open_gaps` lists what the data could not establish.

## What you must not do

- Never change what a finding claims, merge competing hypotheses into one story, or drop a finding; present competing explanations side by side and name what would decide between them.
- Do not compute or restate a number that is not a payload field; every figure in your prose is registered `{display, value, kind, source}` with a path that resolves to that exact value.
- Do not name an approver, owner or decision-maker you were not given; owners are suggested functions, dates are rule-generated targets, nothing is approved, assigned or verified.
- Do not use field labels as prose ("Cause:", "Evidence:") or test identifiers above the fold.
- Do not describe an analyst confirmation as verification (none exists in this pipeline) and do not narrate a rejected reading as live.

## Writing the executive summary and the decisions (`readout.summary`)

The page shows what you write here, not a template. Read `python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json summary_pack --lens <view>` first: it holds every figure you may use, each with its `source`, and the rules the gate applies.

You write as an FP&A analyst for CFOs: explain the performance, not the data. Lead with the conclusion, focus on drivers rather than observations, trace cause and effect through the financial hierarchy, quantify, and end on what management must decide or confirm.

**Bullets (exactly 4), one narrative: fewer points, each one developed.** Each bullet carries a `role`, in this order (the gate refuses another order):

| Role | Answers | Write |
|---|---|---|
| `headline` (required, first) | What happened, and what does it mean? | `[Outcome], driven by [primary driver], [business implication]`: net income against the comparator, the driver that carries it, and what it means for profitability, margin or sustainability (recurring against one-off, operating against non-operating). |
| `why` (required) | Why did it happen? | The causal chain down the hierarchy: net income → EBITDA → revenue / cost of sales / opex → department or product line → sub-group → account. Each step explains the one above it ("S&M ran $440k over budget; Marketing Programs carries most of it, in one account"). Use `hierarchy[]` for the parent and the driver's position (most of the parent, part of it, offsets it). Top 2 to 3 drivers; the rest is "other". |
| `trend` (required) | What has changed against history? | The month against the quarter and year to date from `trend{}`: continuing (a trend, not a single month), reversal (a change of direction), new, or easing. Say whether the lead driver accelerates, reverses or holds, and whether the pattern is broad-based or concentrated. |
| `attention` (required, last) | What requires attention? | The most important risk, opportunity, validation or action, with the data needed to confirm any unverified driver (`data_needed[]`). |

Each bullet has three parts: `head`, a bold lead of at most ten words with no figures; `text`, the developed insight shown on the page: two to three sentences, at most 48 words, the key figures allowed when registered in `numbers[]`, each sentence explaining the one before (observation, driver, consequence); and `detail`, the fuller reading shown when the bullet is opened, above its evidence: at most 130 words and five sentences, with the figures, the drivers down the hierarchy (top two or three, the rest as "other"), the comparison with the quarter, year to date and prior year where the payload has it, and the business implication. **The page lines (all heads and texts) total at most 220 words.** Write each bullet as a short paragraph of reasoning, not a label. Never a figure alone: "Contractor expense exceeded budget by $800k" is evidence; "Contractor expense exceeded budget by $800k, with spending growing faster than revenue and compressing margin" is an insight.

Patterns worth looking for, in this order of usefulness:

1. Concentration: a few drivers carry most of the movement (targeted) or none do (broad-based).
2. Trend: the month continuing the quarter and year to date, a reversal, or a new driver; a driver that is accelerating or changing direction.
3. Structural vs one-off: recurring lines versus a single posting; name the one-off and give net income without it. Timing only with a reversal signal.
4. Operating vs non-operating: how much of net income sits below Adjusted EBITDA.
5. Margin: costs growing faster than revenue, or operating leverage working.
6. Forecast quality: lines that have missed budget for months (a plan problem) versus a new miss.
7. Mix: recurring against non-recurring.
8. Actionability: concentrated in one unit or a few categories, so the fix is targeted.

**Manual adjustments.** Read `adjustments` in `brief` / `summary_pack` (or `finance_brief.py ... adjustments --lens <view>`) before writing. Every lens names the adjustments in its window: (i) pro forma (`Pro Forma Actuals`, `Pro Forma Adjustments`), and (ii) the capitalisation of software (`-8001`, R&D) and commissions (`-8002`, S&M), charged inside Adjusted EBITDA and reversed below it (`-8003`). Where an adjustment moves a driver or the headline by a material amount, say so with its registered figure. Capitalisation lowers Adjusted EBITDA and nets to zero at net income: describe it as an accounting treatment ("commissions capitalised and charged inside Adjusted EBITDA, reversed below it"), never as a saving, an overspend or operating performance. Pro forma actuals are the pre-acquisition results of acquired businesses: name them when they explain a revenue or cost move against prior year. Adjustment rows carry no memo, so explain them by type and account, never as "no description".

**GL memos in the readout: memo first.** Before writing the executive summary, the Drivers and Outlook "What this means" notes or a decision, read `summary_pack.memo_evidence` and the lead drivers' `memos`. Every `why` statement should rest on what the postings were where a memo exists, not on the account name alone. Use what the memos show wherever it applies: in the `why` bullet (what the lead driver's postings were: payroll, accruals, fees), the `attention` bullet (a prior-year one-off, a missing credit, an accrual reversal that flatters the month, lines with no memo), the decisions (ask the question the memo leaves open), the structural conclusions shown as **What this means on the Drivers tab** (accrual movements across the cost lines, a one-off behind a non-operating move, a cost base growing in payroll) and the forecast assumptions shown as **What this means on the Outlook tab** (whether accruals, reversals or one-off credits inside the run-rate months inflate or deflate the trailing average; what the run-rate is made of). Paraphrase in accounting words with registered figures; never a memo, a name or a document number. A memo narrows the reading; it is not a disposition, so a cause stays hedged.

**Business context and missing driver data.** Name a business signal only when the data supports it, and then as a possibility: "Salary expense rose $300k, potentially indicating hiring; headcount is not in the data model, to be confirmed." The Finance view carries no customer counts, customer concentration, headcount, prices, volumes or acquisition plans (`missing_drivers{}` lists them by section, with who holds them). So:
- a movement that may reflect one of them says so, names the missing driver, and is hedged in the same sentence ("appears", "suggests", "potentially", "may indicate", "might be due to", "to be confirmed");
- never treat the absence of that data as evidence that the driver did not change, and never quantify or size it;
- list the missing drivers in the bullet's `unverified[]`, and put the data that would confirm them in the attention bullet's `data_needed[]` ("headcount by department (HR / Payroll)").

The gate refuses an unhedged hiring, pricing, churn, customer, acquisition, integration, inflation or volume reading, one without `unverified[]`, and an attention bullet that does not ask for the data.

Every figure comes from the pack with its `source`; you never compute, round or combine. Each bullet carries a `drill` (`level` + `ids`) that opens on the evidence for that bullet, and a `tone`. The lead may carry a `claim`, which the gate re-checks against the numbers. Attribution down the hierarchy may say "driven by" or "led by" (the drill proves it); any other causal phrase ("because", "due to", "caused by") only hedged in the same sentence ("may be due to"). Never invent a business explanation, assume management intent, or claim a cause the data does not show. None of the forbidden phrases, no "n.m." style shorthand.

**Decisions (2 or 3).** Questions for management, to the point. `text` is the question on the page: at most 12 words, ending with `?`, no figures. `detail` is the full question shown when it is opened: at most 40 words, with the registered figures, ending with `?`. Each has a suggested owner, a `drill` on what the question is about (usually the driver or the action) and, where the pack gives one, the registered `amount` at stake. Ask the question the number cannot answer: which of volume, price or mix; a single receivable or a rate change; closed event or recurring.

Shape (the pack prints it under `shape`):

```json
"summary": {
  "bullets": [{"id": "lead", "role": "headline", "tone": "favourable", "head": "Ahead, carried below the line.", "text": "Net income is ahead of prior year, driven by taxes, not operations.", "detail": "Net income is $275k ahead of prior year, driven by +$248k from income taxes against +$108k from Adjusted EBITDA: the operating gain is modest and most of the improvement is not operating.",
               "numbers": [{"display": "$275k", "value": 274616.72, "kind": "money", "source": "lenses[MTD_py].lines[ni].variance"}, ...], "drill": {"level": "line", "ids": ["ni"]}, "claim": "below_line_led"},
              {"id": "why", "role": "why", "tone": "unfavourable", "head": "Selling cost absorbs the revenue gain.", "text": "S&M growth offsets most of the recurring revenue gain.", "detail": "Recurring Revenue added +$781k, but S&M rose $440k, most of it in Salaries, potentially indicating hiring; headcount is not in the data model, to be confirmed.",
               "unverified": ["headcount"], "numbers": [...], "drill": {"level": "driver", "ids": ["d:opex:fully-loaded-s-m-expense"]}},
              {"id": "trend", "role": "trend", ...},
              {"id": "attention", "role": "attention", ..., "data_needed": ["headcount by department (HR / Payroll)"]}],
  "decisions": [{"text": "Is the bad debt charge a single receivable or a new rate?", "detail": "Is the $292k bad debt charge a single receivable or a change in the provisioning rate, and does the selling cost base stay at this level?", "owner": "Function head with FP&A", "drill": {"level": "driver", "ids": ["d:opex:fully-loaded-s-m-expense"]},
                 "amount": {"display": "$440k", "value": 440000.0, "kind": "money", "source": "lenses[MTD_py].drivers[d:opex:fully-loaded-s-m-expense].movement"}, "numbers": []}]
}
```

## Output

Add the `readout{}` block to `diagnosis.json`, set `payload_hash` to the payload's `analysis_hash`, `lens` to the lens you read, `written_by` to the role name (never a person's approval), then run the gate and render:

```bash
python <SKILL_DIR>/scripts/validate_finance_diagnosis.py --payload work/finance_payload.json --diagnosis work/diagnosis.json
python <SKILL_DIR>/scripts/render_finance_dashboard.py --payload work/finance_payload.json --diagnosis work/diagnosis_mtd.json work/diagnosis_ytd.json --out outputs/
```

A refused diagnosis is fixed in the diagnosis. If it cannot be fixed in the time available, render with `--allow-missing-review`: the build output names the views without a review, those views carry the data only, and you say so when handing it over.
