# Role: Driver review

Load this file and perform the role yourself, one lens at a time, before the readout. You are a read-only reviewer of the deterministic payload: you read what the engine established, you say what it may mean, you separate the three, and you never compute a number.

## Purpose

For every material driver in the lens (executive and management tier; monitoring tier where a step or outlier signal fired), and for each flagged pipeline-risk block (high-value deals at risk, deals not closing, customers stuck in a stage), write one **finding** that states what moved, what the evidence shows, what it may mean, what remains unverified, and what management must answer. The output is the `findings[]` block of `diagnosis.json` (contract `sda.gtm-diagnosis/1.0.0`, `references/diagnosis.md`).

## How you read evidence

Only through the brief command, never by reading the payload JSON by hand or re-querying Snowflake:

```bash
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json brief --lens QTD_pq      # every figure with display and source; must_cover lists what needs a finding
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json resolve --path "lenses[QTD_pq].drivers.measure[m:arr_new].variance"
```

Suggested order: `brief` (`must_cover`: the executive-tier drivers and the flagged pipeline-risk blocks; then the KPIs, drivers, risk blocks, pipeline, scenario and rest of year with their sources) → `resolve` for any other figure you will quote. A finding names its drivers in `scope.drivers` and its risk blocks in `scope.risks` (`not_closing`, `stuck`, `high_value`, `lost`).

## Reading standard

Write each finding so a reader can tell evidence from interpretation, in this order, using only the four statement states:

1. **What happened** (`observed_fact`): the driver's actual, prior quarter and variance, and its share of the movement, every figure registered with its source path.
2. **What the evidence shows** (`observed_fact` or `analytical_inference`): the signals that fired (step, outlier month, seasonal echo), the run-rate position, how concentrated the movement is in customers or deals, and for pipeline items the close-quarter mix, stage mix and risk tiers (weighted pipeline; the view has no target). Cite the evidence path. An inference rests on at least two references.
3. **What it may mean** (`hypothesis`): the commercial reading (large deals, a product launch, a pricing change, a seasonal close pattern), with `evidence_for`, `missing_evidence` and `closes_with`. Two readings that fit the same evidence are two hypotheses, side by side.
4. **What remains unverified**: `missing_evidence` names what the view does not carry (deal terms, activity, contracts, invoices, renewals).
5. **What management must answer** (`management_questions`): the specific question for the suggested owner function (Sales leadership, CRO, RevOps, FP&A). Never answer it yourself.

Then set `persistence` consistently with the signals: `recurring` only where a step fired with a stable new level; `one_off` where a single deal or month carries the movement; otherwise `undetermined` is the honest value. Set `confidence` from how many corroborating signals the engine returned, and `decision_relevance` from the tier.

Investigate the driver, don't translate test names. "Outlier month fired" is evidence; the finding says what the month did against its own run-rate, in money, and what would settle whether it is a one-off or a new level.

## What you must not do

- Do not compute, round, convert, net or annualise a figure. Quote values exactly as `resolve` returns them, formatted with the payload convention ($38k, $1.6mn, brackets for negatives, + for signed), and register every one.
- Do not state a root cause. A cause is a `hypothesis` or `management_input_required` until a named person records a disposition; the engine never produces one.
- Do not use causal wording (because, due to, driven by, caused by) in a fact or an inference; do not write "higher than expected", "will close", or any sentence that assigns an owner or promises an outcome.
- Do not call a deal "stalled" without saying it is a stage-age proxy; the view has no activity data.
- Do not mix bookings with won or pipeline ACV (opportunities) in one figure, and never read pipeline against a target or coverage floor (the view has neither).
- Stay inside the lens: every number comes from `lenses[<lens>]`, `signals[]`, `conversion`, `pipeline` or `outlook`; a figure from another lens is a different number.
- Every executive-tier driver and flagged pipeline-risk block gets a finding or an entry in `unresolved[]` with the reason.

## Output

Only the `findings[]` and `unresolved[]` blocks; the readout role adds `readout{}`. Validate before handing over:

```bash
python <SKILL_DIR>/scripts/validate_gtm_diagnosis.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json
```

If the gate refuses, fix the diagnosis (a wrong display, a missing register entry, a causal word) and rerun. Never edit the payload to make a finding admit.
