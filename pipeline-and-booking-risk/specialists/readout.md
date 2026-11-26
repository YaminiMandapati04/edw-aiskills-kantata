# Role: Readout

Load this file and perform the role yourself after the driver review, for the same view. You turn the findings into what the reader sees first: the executive summary and the decisions for management on the Pipeline and Bookings tabs, and the "What this means" readings on Pipeline, Bookings and Outlook. You create ordering and wording **only from the findings and the payload**; you cannot add a finding, change what a finding claims, or upgrade a hypothesis. The shape is in `references/diagnosis.md` §3.

## How you read evidence

```bash
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json brief --lens QTD_pq    # every figure with its display and source, what must be covered
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json refs --lens QTD_pq     # every detail a bullet or decision may open
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json resolve --path "..."
python <SKILL_DIR>/scripts/gtm_brief.py work/gtm_payload.json contract
```

Plus the `findings[]` you already wrote.

## Narrative standard

**Executive summary, per tab** (`readout.summary.pipeline`, `readout.summary.bookings`): 3 to 5 short bullets, top-down.
- Pipeline: what is at risk in the weighted pipeline (not closing, stuck, high-value deals), then conversion and creation (weighted pipeline dated to close in the next fiscal quarter, pipeline creation, at-risk pipeline, the straight-line scenario (weighted pipeline; there is no target or coverage)).
- Bookings: total bookings first (the outcome, what led it, what it means), then the quality of the growth (new ARR against upsell ARR, deal size, dependence on a few customers or deals, win rate), then what to watch.
- `head`: the bold conclusion, at most ten words, no figures ("Most of the pipeline is not closing.").
- `text`: the line on the page, at most 30 words: observation, then what it means. The amounts are evidence, never the point.
- `detail`: the full reading shown when the bullet is opened, at most 110 words.
- `tone`: `favourable`, `unfavourable`, `neutral` or `outlook`; `ref`: the detail the bullet opens (`refs`); `finding_ref` where it rests on a finding.
- Never repeat the engine's sentence; add what only review can: what to discount, what to confirm first, what it means for the year.

**Decisions** (2 or 3 per tab): one question each for a suggested owner function, at most twelve words with no figures; the full question with its figures in `detail`; `ref` to the engine's follow-up item (`action:<id>`) or the evidence; `amount` (a registered figure) for what is at stake.

**What this means** (`pipeline_meaning`, `bookings_meaning` ≤ 3 each, `outlook_meaning` ≤ 4; each ≤ 45 words): the structural reading a manager takes away. Outlook readings say what the straight-line ranges assume (scenario credit 0, no management view) and what the rest of the year needs.

**QC**: `qc.business_cause` says in one sentence how much rests on an attested cause (none, unless a named disposition exists); `qc.open_gaps` lists what the data could not establish.

## What you must not do

- Never change what a finding claims, merge competing hypotheses into one story, or drop a finding.
- Do not compute or restate a number that is not a payload field; every `$` and `%` figure is registered `{display, value, kind, source}`. Copy deal counts exactly from the brief.
- Do not name an approver, owner or decision-maker you were not given; owners are suggested functions, nothing is approved, assigned or verified.
- Negatives in brackets, "mn" not "mm", favourable / unfavourable, never "adverse".
- Do not present the straight-line scenario as a forecast or a commitment.

## Output

Add the `readout{}` block to the diagnosis, set `payload_hash` to the payload's `analysis_hash`, `lens` to the view you read, `written_by` to the role name (never a person's approval), then run the gate and render:

```bash
python <SKILL_DIR>/scripts/validate_gtm_diagnosis.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json
python <SKILL_DIR>/scripts/render_gtm_dashboard.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json --out outputs/yes_energy_pipeline_risk_readout.html
```

A refused review is fixed in the diagnosis, never the payload. If it cannot be fixed in the time available, render with `--allow-missing-review`: the page then shows the engine reading and says "This view not AI reviewed", and you say so when handing it over.
