# Diagnosis contract and admission gate (the AI review)

> **Status: live.** The gate is `scripts/gtm/diagnosis.py` (CLI `scripts/validate_gtm_diagnosis.py`), the evidence brief is `scripts/gtm_brief.py`, and the page is rendered with the review by `scripts/render_gtm_dashboard.py` or `build_gtm_dashboard.py --diagnosis`. Ported from the finance skill's gate.

The deterministic engine decides what is true about the numbers (`gtm_payload.json`). Claude decides what those truths mean, in `diagnosis.json`. The gate admits only what the payload supports, and the page shows an admitted review beside the engine's figures, never in place of them. A page whose views carry an admitted review says **AI reviewed** in the data badge and the footer; any other view says **This view not AI reviewed** and shows the engine reading.

## Contents
1. Where it sits
2. The two roles
3. The contract (`sda.gtm-diagnosis/1.0.0`)
4. Statement states and wording rules
5. Number provenance
6. What the gate refuses
7. Where the review shows, and the fallback

---

## 1. Where it sits

```
extract → build (payload, --payload-out) → [driver review → readout → gate] → render
```

The opening view (the payload's primary lens, normally Quarter to date vs Prior quarter) needs an admitted review before the page is published: `build_gtm_dashboard.py` without `--diagnosis` writes the payload and no page. `--allow-missing-review` publishes the engine reading alone, with "This view not AI reviewed" on the page; say so when handing it over. Other views may carry their own review (one file per view, `--diagnosis a.json b.json`).

## 2. The two roles

| Role file | Writes | Reads through |
|---|---|---|
| `specialists/driver-review.md` | `findings[]`, `unresolved[]` | `gtm_brief.py brief / refs / resolve` |
| `specialists/readout.md` | `readout{}`: the written executive summary and decisions for the Pipeline and Bookings tabs, the "What this means" readings for Pipeline, Bookings and Outlook, `qc` | the findings plus `gtm_brief.py brief / refs / resolve` |

Perform the roles yourself, one after the other, for one view.

## 3. The contract

```json
{
  "contract": "sda.gtm-diagnosis/1.0.0",
  "payload_hash": "<payload.analysis_hash>",
  "lens": {"window": "QTD", "basis": "pq"},
  "written_by": "driver review + readout (Claude)",
  "findings": [{
    "id": "f1", "title": "New sales carry the quarter's decline",
    "scope": {"drivers": ["m:arr_new"], "risks": ["not_closing"]},
    "decision_relevance": "high", "confidence": "medium", "persistence": "undetermined",
    "statements": [
      {"state": "observed_fact", "text": "New-sales bookings are $878k against $1.26mn last quarter, a change of ($378k).",
       "numbers": [{"display": "$878k", "value": 877900.0, "kind": "money", "source": "lenses[QTD_pq].drivers.measure[m:arr_new].actual"}, "..."],
       "evidence_refs": ["lenses[QTD_pq].drivers.measure[m:arr_new]"]},
      {"state": "analytical_inference", "text": "Win rate fell while the average deal grew, so the decline sits in the number of deals won.", "numbers": [], "evidence_refs": ["lenses[QTD_pq].kpis[win_rate]", "lenses[QTD_pq].kpis[aov]"]},
      {"state": "hypothesis", "text": "...", "numbers": [], "evidence_refs": ["..."],
       "hypothesis": {"evidence_for": ["..."], "missing_evidence": ["..."], "closes_with": "the suggested owner confirms ..."}},
      {"state": "management_input_required", "text": "The view cannot show why; Sales leadership must say which.", "numbers": [], "evidence_refs": []}],
    "missing_evidence": ["..."], "management_questions": ["..."]
  }],
  "unresolved": [{"ref": "stuck", "reason": "..."}],
  "readout": {
    "summary": {
      "pipeline": {"bullets": [{"head": "Most of the pipeline is not closing.", "text": "the line on the page", "detail": "the full reading when the bullet is opened",
                                 "tone": "unfavourable", "ref": "rk:at_risk", "finding_ref": "f2", "numbers": [], "unverified": []}],
                    "decisions": [{"text": "Which high-value deals get an executive sponsor?", "detail": "the full question, with figures?", "owner": "Sales leadership",
                                   "ref": "action:a:high_value", "finding_ref": "f2", "numbers": [], "amount": {"display": "$23.6mn", "value": 23618246.4, "kind": "money", "source": "risk.high_value.flagged.acv"}}]},
      "bookings": {"bullets": [], "decisions": []}},
    "pipeline_meaning": [{"state": "analytical_inference", "text": "...", "numbers": [], "evidence_refs": ["..."]}],
    "bookings_meaning": [],
    "outlook_meaning": [],
    "qc": {"business_cause": "how much is attested vs open", "open_gaps": ["..."]}
  }
}
```

Counts: findings ≥ 1. Each tab's summary: 3 to 5 bullets (head ≤ 10 words, no figures; text ≤ 30 words; detail ≤ 110 words; at most 200 words of heads and texts per tab), the first Bookings bullet about total bookings; 2 or 3 decisions (a question of ≤ 12 words with no figures; the full question in `detail`; a suggested owner). `pipeline_meaning` ≤ 3, `bookings_meaning` ≤ 3, `outlook_meaning` ≤ 4, each ≤ 45 words. Tones: `favourable`, `unfavourable`, `neutral`, `outlook`. Coverage: every executive-tier driver of the view, and every flagged pipeline-risk block (`not_closing`, `stuck`, `high_value`), is in a finding's `scope` or in `unresolved[]`.

## 4. Statement states and wording rules

| State | Means | Must carry | May not |
|---|---|---|---|
| `observed_fact` | a payload figure restated | a registered number or an `evidence_ref` | causal wording |
| `analytical_inference` | a conclusion from two or more references | `evidence_refs` | causal wording; a forecast; an assignment |
| `hypothesis` | a plausible reading the data cannot prove | the `hypothesis` block: `evidence_for`, `missing_evidence`, `closes_with` | be presented as a fact anywhere else |
| `management_input_required` | the data cannot separate the plausible causes | the specific input needed | a guess at the answer |

Persistence: `one_off`, `recurring`, `seasonal`, `timing`, `persistent`, `undetermined`; `recurring`, `persistent` and `timing` need an inference or hypothesis statement.

In the summary bullets, attribution down the bookings hierarchy ("led by new sales", "driven by SX") is arithmetic the bridge proves and is allowed; any other causal phrase only hedged in the same sentence ("may", "to be confirmed"). A cause the view does not carry (pricing, discounts, competition, quota, territories, campaigns, churn, renewals, procurement...) is written only as a possibility and named in the bullet's `unverified[]`.

Forbidden anywhere: "higher than expected", "lower than expected", "root cause" as a claim, "confirmed cause", "verified cause", "will close / convert / recover / reverse / persist", "assigned to", "owned by", "stalled" without "proxy". Owners are suggested functions; dates are rule-generated targets; scenario credit is 0; nothing is approved.

## 5. Number provenance

Every `$` and `%` token in any text is registered in that item's `numbers[]` as `{display, value, kind, source}`:

- `display` is the exact string in the text, as the page prints it: `$38k`, `$1.26mn`, `($378k)`, `+$159k`, `(30.1%)`, `+36.1%`. `gtm_brief.py brief` gives every figure the review may use with its display and source.
- `value` is the payload value; the gate resolves `source` and compares (±0.5 for money, ±0.0006 for a fraction).
- `source` is a payload path: `lenses[QTD_pq].kpis[total].variance`, `lenses[QTD_pq].drivers.product[p:sx].variance`, `risk.not_closing.acv`, `outlook.scenario[0].low`, `rest_of_year.still_to_match`. Read an exact value with `gtm_brief.py PAYLOAD resolve --path ...`.
- Period labels (`2026-09`, `FY2027-Q3`), years, small counts and product names are exempt. Deal counts and points are not gated: copy them from the brief exactly.

## 6. What the gate refuses

| Area | Refusal |
|---|---|
| contract / staleness | wrong contract; `payload_hash` not equal to the payload's `analysis_hash` (the payload changed: rewrite the review) |
| lens | a view that is not in the payload or not available |
| scope | an unknown driver id or risk block |
| numbers | an unregistered `$`/`%` token; a registered display whose source does not resolve or whose value differs |
| states | an unknown state; a fact with no number or evidence ref; a hypothesis without its block; causal wording in a fact or inference |
| phrases | any forbidden phrase; an unhedged or unlisted cause the view does not carry |
| summary | bullet and decision counts and lengths; a head or question with figures; a decision that is not a question; no owner; a figure alone with no meaning; an unknown tone |
| drill | a `ref` the page cannot open in this view (`gtm_brief.py refs` lists them) |
| coverage | an executive-tier driver or a flagged pipeline-risk block with neither a finding nor an `unresolved` entry |

Warnings (admitted, listed in the render result): a finding with no management question; `qc` fields missing; no `outlook_meaning`.

## 7. Where the review shows, and the fallback

| Diagnosis field | Where it shows | Without a review for the view |
|---|---|---|
| `readout.summary.pipeline` | Pipeline tab: Executive summary bullets and Decisions for management | the engine's pipeline insights and follow-up items |
| `readout.summary.bookings` | Bookings tab: Executive summary bullets and Decisions for management | the engine's insights and follow-up items |
| `readout.pipeline_meaning` | "What this means" under Where the pipeline is at risk; the pipeline is a snapshot, so the opening view's reading shows on every view | not shown |
| `readout.bookings_meaning` | "What this means" under What moved bookings, for this view only | the engine's reading of the largest moves against their usual range |
| `readout.outlook_meaning` | "What this means" in the Outlook commentary panel, on every view (this view's review first, then the opening view's) | a note that the ranges are a straight-line scenario, not a forecast |
| `findings[]` | first under "What it means" in the driver drawer | the driver's engine reading |
| any admitted view | data badge and footer: "AI reviewed" | "This view not AI reviewed" |

Nothing is derived in the browser; the renderer never calls a model.
