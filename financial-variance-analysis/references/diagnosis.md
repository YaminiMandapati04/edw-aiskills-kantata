# Diagnosis contract and admission gate

The deterministic engine decides what is true about the numbers (`finance_payload.json`). The model decides what those truths mean, in `diagnosis.json`. The gate (`scripts/validate_finance_diagnosis.py`, `scripts/finance/diagnosis.py`) admits only what the payload supports, and the renderer shows an admitted diagnosis beside the engine baseline, never in place of the numbers.

## Contents
1. Where it sits
2. The two roles
3. The contract (`sda.finance-diagnosis/1.0.0`)
4. Statement states and claim rules
5. Number provenance
6. What the gate refuses
7. Render-stage fallback
8. Worked example

---

## 1. Where it sits

```
extract → analyze (payload) → validate → [driver review → readout → gate] → render
```

The bracketed part is optional. A dashboard rendered without a diagnosis is complete and honest: every region carries the engine baseline with an "engine baseline" badge. A diagnosis adds judgement, never new figures.

## 2. The two roles

| Role file | Writes | Reads through |
|---|---|---|
| `specialists/driver-review.md` | `findings[]`, `unresolved[]` | `finance_brief.py brief / driver / account / resolve` |
| `specialists/readout.md` | `readout{}` (conclusions, decision asks, stories, structural conclusions, forecast assumptions, lead actions, account interpretations, headline, qc) | the findings plus `finance_brief.py brief / headline / outlook / kpis / resolve` |

Perform the roles yourself, one after the other, for one lens (normally the primary lens, Month vs Prior year). The other seven lenses keep the engine baseline; say so when handing the page over.

## 3. The contract

```json
{
  "contract": "sda.finance-diagnosis/1.0.0",
  "payload_hash": "<payload.analysis_hash>",
  "lens": {"window": "MTD", "basis": "budget"},
  "written_by": "driver review + readout (model)",
  "findings": [{
    "id": "f1", "title": "Marketing Programs ran $38k over budget in a single month",
    "scope": {"drivers": ["d:opex:acct-6300"], "accounts": ["6300"]},
    "decision_relevance": "high", "confidence": "medium", "controllability": "controllable", "persistence": "one_off",
    "statements": [
      {"state": "observed_fact", "text": "Marketing Programs is $143k against budget $105k: −$38k (−36.0%), adverse to profit.",
       "numbers": [{"display": "$143k", "value": 143045.62, "kind": "money", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].actual"},
                   {"display": "$105k", "value": 105215.41, "kind": "money", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].comparator"},
                   {"display": "−$38k", "value": -37830.21, "kind": "money", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].variance"},
                   {"display": "−36.0%", "value": -0.3595, "kind": "pct", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].variance_pct"}],
       "evidence_refs": ["lenses[MTD_budget].drivers[d:opex:acct-6300]"]},
      {"state": "analytical_inference", "text": "The month sits above its trailing six-month range while the budget sits on the run-rate reference, so the gap is the month's own move, not the plan level.",
       "numbers": [], "evidence_refs": ["signals[6300].tests[outlier_month]", "lenses[MTD_budget].layers.drivers[d:opex:acct-6300]"]},
      {"state": "hypothesis", "text": "A campaign or agency invoice landed in the month; if so it does not repeat, and the run-rate returns to the trailing level.",
       "numbers": [], "evidence_refs": ["signals[6300].tests[outlier_month]"], "claim_types": ["persistence"],
       "hypothesis": {"evidence_for": ["single-month excursion with no step held"], "missing_evidence": ["the largest postings in the month (GL drill)", "campaign approvals"], "closes_with": "the Function head confirms the item and whether it recurs"}},
      {"state": "management_input_required", "text": "The ledger does not show whether this is headcount, rate or a one-off item; the Function head with FP&A must say which.", "numbers": [], "evidence_refs": []}],
    "missing_evidence": ["the largest postings in the month", "campaign approvals or contracts"],
    "management_questions": ["Which item drove the October overspend, and does it recur in November?"],
    "addresses_tests": ["outlier_month", "yoy_break"]
  }],
  "unresolved": [],
  "readout": {
    "headline": null,
    "conclusions": [
      {"role": "current_period_driver", "finding_ref": "f1", "insight": "Likely a one-off, not a new level", "status": "unfavorable", "state": "analytical_inference", "persistence": "one_off",
       "text": "The month is behind budget mainly on one line: Marketing Programs, −$38k, an excursion from its own run-rate rather than a plan problem.",
       "numbers": [{"display": "−$38k", "value": -37830.21, "kind": "money", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].variance"}],
       "evidence_refs": ["lenses[MTD_budget].drivers[d:opex:acct-6300]"],
       "response": "Identify the postings and confirm whether the item recurs; suggested owner the Function head with FP&A."},
      {"role": "performance_quality", "finding_ref": "f2", "...": "..."},
      {"role": "forward_looking", "finding_ref": "f3", "...": "..."}],
    "decision_asks": [{"text": "Does the October marketing item recur, and if so at what monthly level?", "finding_ref": "f1", "owner": "Function head with FP&A", "action_refs": ["a:d:opex:acct-6300"], "numbers": []}],
    "driver_stories": [], "structural_conclusions": [], "forecast_assumptions": [], "lead_actions": [],
    "account_interpretations": [{"account": "6300", "state": "analytical_inference", "text": "A single-month excursion above the run-rate; one-off until November shows otherwise. Next: identify the postings.", "numbers": []}],
    "qc": {"business_cause": "No cause is attested; every reading is a hypothesis awaiting the owner's confirmation.", "open_gaps": ["no transaction detail in the payload", "no headcount, rate or volume data in the statement marts"]}
  }
}
```

Counts: findings ≥ 1; exactly three conclusions with distinct roles; decision asks ≤ 3; driver stories ≤ 3; structural conclusions ≤ 3; forecast assumptions ≤ 5; lead actions ≤ 3; account interpretations ≤ 10. Every executive-tier driver of the lens has a finding naming it in `scope.drivers` or an entry in `unresolved[]`. Driver stories and account interpretations are drill-through narratives of at most 75 words.

`readout.summary` (the written executive summary; full rules in `specialists/readout.md`): exactly 4 `bullets`, each with a `role` in the order `headline` → `why` → `trend` → `attention` (what it means is written inside them), the page lines (heads + texts) at most 220 words; a bullet naming a business-context driver the data model does not carry lists it in `unverified[]`, and the attention bullet's `data_needed[]` names the data that would confirm it. Plus 2 or 3 `decisions` (questions).

### Manual adjustments

Each lens carries `adjustments` (`types[]` with `actual.rev` / `actual.ebitda` / `actual.ni` and components, `total_ebitda_impact`, `ebitda_excluding_adjustments`). When an adjustment type moves the headline or a driver materially, the executive summary or the finding names it, with figures registered from those paths. Capitalisation (`Adjustment for Capitalized expenses`: Capitalised Software, Capitalised Commissions, Reversal of Capitalised Portions) is an `observed_fact` about accounting treatment. It is never the basis of a performance inference. Pro forma (`Pro Forma Actuals`, `Pro Forma Adjustments`) is named as pro forma, never as organic movement.

### GL memo evidence

When the payload carries memos (`payload.memos.available`), every lens has `memo_evidence`: for net income, each driver and each material account, the memo **themes** (a memo with month names, dates and document numbers removed, so "Sep26 Vendor Accruals" and "Aug26 Vendor Accruals" are one theme) and the additive memo **categories** (accruals and reversals for an earlier month, payroll, bonus, accruals for the period, interest, reclassifications, ... , no memo), each with actual, comparator and variance in the lens's convention, adding up to the driver or account. `payload.memos.run_rate` holds the same for the three months the outlook's run-rate averages, and `payload.memos.one_offs` the memos behind each one-off in the register. Read them with `finance_brief.py ... memos [--id]`; `driver`, `account` and `summary_pack` carry them too.

Use them wherever they apply, because they are the human-written description of the postings:
- a finding gets an `observed_fact` that says what the postings were called, in accounting words, with the figures registered from `memo_evidence` paths and the theme or category as its `evidence_ref`, and an `analytical_inference` that says what that means for the driver (one-off against monthly, a comparison effect, accrual movements flattering or inflating the month);
- the summary bullets (`why`, `attention` above all), the decisions, the structural conclusions (Drivers tab "What this means"), the forecast assumptions (Outlook tab "What this means") and the account interpretations use the same evidence;
- a category compares across years even where the memo wording changed; prefer it over a theme when the labels differ between the years;
- a blank memo is evidence too: say how much of a movement carries no description (`blank_memo_share`) rather than reading into it.

A memo is what the poster wrote, not a disposition: it narrows the hypotheses, it does not verify a cause. **Never quote a memo, a vendor, customer, person or system name, or a document number**: the gate refuses any word in `payload.memos.restricted_terms` (capitalised names found in the memos, matched as written) and any `#<digit>` or 7+ digit reference anywhere in the diagnosis. A common word on that list is refused only when capitalised; rephrase or lower-case it.

## 4. Statement states and claim rules

| State | Means | Must carry | May not |
|---|---|---|---|
| `observed_fact` | a payload figure restated | a registered number or an `evidence_ref` | causal wording; "timing" without a reversal signal |
| `analytical_inference` | a conclusion from two or more references | `evidence_refs` (two or more) | causal wording; a forecast; an assignment |
| `hypothesis` | a plausible reading the data cannot prove | the `hypothesis` block: `evidence_for`, `missing_evidence`, `closes_with` | be presented as a fact anywhere else |
| `management_input_required` | the data cannot separate the plausible causes | the specific input needed | a guess at the answer |

Persistence vocabulary: `one_off`, `recurring`, `seasonal`, `timing`, `persistent`, `coverage`, `undetermined`. `timing` is admitted only on an account where `reversal_signal` fired, or where a statement of the finding cites (in `evidence_refs`) a memo theme tagged `accrual_reversal` (an accrual or reversal that names an earlier month); `recurring` and `persistent` need an inference or hypothesis statement that says why.

Forbidden anywhere: "higher than expected", "lower than expected", "business needs", "root cause" as a claim, "confirmed cause", "verified cause", "will recover / reverse / persist", "assigned to", "owned by". Owners are suggested functions; dates are rule-generated targets; forecast credit is 0; nothing is approved.

## 5. Number provenance

Every `$`, `%` and `bps` token in any text is registered in that statement's `numbers[]` as `{display, value, kind, source}`:

- `display` is the exact string in the text, in the payload convention: `$38k`, `$1.57mm`, `−$76k` (U+2212), `+$4.6k`, `−36.0%`, `+123 bps`.
- `value` is the payload value; the gate resolves `source` and compares (±0.5 for money, ±0.06 points for percent). Optional `scale` (a display-sign flip, e.g. −1 for an expense range) and `transform: "abs"` are honoured.
- `source` is a payload path: `lenses[MTD_budget].drivers[d:cos:recurring-cogs].variance`, `lenses[MTD_budget].accounts[a1b2c3d4e5f6].actual`, `lenses[MTD_budget].hierarchy[d:rev:recurring-revenue].nodes[d:rev:recurring-revenue/saas-subscription].movement` (an L5 sub-group), `lenses[MTD_budget].hierarchy[d:rev:recurring-revenue].nodes[d:rev:recurring-revenue/saas-subscription].children[d:rev:recurring-revenue/saas-subscription/platform-recurring].movement` (an L6 product line; `finance_brief.py ... driver --id <driver>` lists the ids under `hierarchy`), `signals[a1b2c3d4e5f6].tests[persistent_gap].evidence.cumulative_variance` (account ids are engine ids since payload 1.2.0, not chart-of-account keys: read them from the brief), `lenses[MTD_py].reconciliation[d:rev:recurring-revenue].items[0].movement`, `lenses[MTD_py].accounts[<id>].movement` (use `movement` for an account active in only one period: its `variance` is null), `lenses[MTD_budget].layers.totals.operational`, `outlook.lines.ebitda.mechanical.value`. Read the exact value with `finance_brief.py ... resolve --path`.
- Period labels (`2026-10`), years, small counts ("4 of 6 months") and account names are exempt.

## 6. What the gate refuses

| Code area | Refusal |
|---|---|
| contract / staleness | wrong contract; `payload_hash` not equal to the payload's `analysis_hash` (the payload changed: rewrite the diagnosis) |
| lens | a lens that is not in the payload or not available |
| scope | an unknown driver or account id |
| numbers | an unregistered `$`/`%`/`bps` token; a registered display whose source does not resolve or whose value differs |
| states | an unknown state; a fact with no number or evidence ref; a hypothesis without its block; causal wording in a fact or inference; "timing" without a reversal signal |
| phrases | any forbidden phrase |
| memo names | a word from `memos.restricted_terms` (as written) or a document number (`#<digit>`, 7+ digits) in any text of the diagnosis |
| conclusion `insight` | longer than eight words, carries a figure, or uses causal or forbidden wording |
| counts and roles | not exactly three conclusions with distinct roles; a `finding_ref` that names no finding; more decision asks, stories, assumptions, actions or interpretations than allowed |
| coverage | an executive-tier driver with neither a finding nor an `unresolved` entry |
| headline | a rephrased headline that drops or re-rounds a pinned slot |
| summary narrative | not exactly 4 bullets; a bullet without a role; roles out of order or missing headline, why, trend or attention; page lines over 220 words; a page line over 48 words or with an unregistered figure; a detail over 130 words or five sentences, or a figure alone; a drill that does not exist |
| summary wording | a causal phrase other than "driven by" / "led by" without a hedge in the same sentence; a business-context driver (hiring, headcount, pricing, demand, churn, customers, adoption, acquisition, integration, reorganisation, inflation, volume) without a hedge, or without `unverified[]`; unverified drivers the attention bullet's `data_needed[]` does not name |
| drill narratives | a driver story or account interpretation over 75 words |

Warnings (admitted, listed in the render result): a finding with no management question; `qc` fields missing.

## 7. Render-stage fallback

Without an admitted diagnosis, or on any lens other than the diagnosed one, the narrative reads the engine's own fields and the executive summary carries the "engine baseline" tag (renderer 1.2.0):

| Diagnosis field | Where it shows when admitted | Engine fallback |
|---|---|---|
| `readout.headline` | "Reviewed reading" in the net income detail panel | none |
| `readout.conclusions[]` | executive-summary bullets right after the net-income lead, tagged "reviewed": bold `insight` (or a heading read from `persistence` / `status`), then `text`, then `response`; deduplicated; the summary stays at 3 to 5 bullets, so they replace engine insights rather than add to them | engine insights (concentration, trend, persistence, margin, mix, budget bias) |
| `readout.decision_asks[]` | "Decisions for management" (`sum-asks`) | the three highest-ranked follow-up items, phrased from their rule |
| `readout.structural_conclusions[]` | "Reviewed structural reading" on Drivers (`drv-reading`) | section not shown; the range bars and drawer patterns carry the signals |
| `readout.forecast_assumptions[]` | "Reviewed forecast assumptions" on Outlook (`out-reading`) | section not shown |
| `findings[]` | finding drawer; listed first under "What it means" in the driver drawer | the driver's engine reasoning |
| `readout.account_interpretations[]` | first point under "What it means" in the account drawer | the account's engine reasoning |

Nothing is derived in the browser; the renderer never calls a model.

## 8. Worked example

`scripts/test_finance_pipeline.py` builds a minimal admitted diagnosis from the sample payload programmatically and renders with and without it; read its `example_diagnosis()` for a complete, gate-passing shape.
