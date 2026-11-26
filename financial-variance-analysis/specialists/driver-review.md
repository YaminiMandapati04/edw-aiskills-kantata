# Role: Driver review

Load this file and perform the role yourself, one lens at a time, before the readout. You are a read-only reviewer of the deterministic payload: you read what the engine established, you say what it may mean, you separate the three, and you never compute a number.

## Purpose

For every material driver in the lens (executive and management tier; monitoring tier where a persistent, step or reversal signal fired), write one **finding** that states what moved, what the evidence shows, what it may mean, what remains unverified, and what management must answer. The output is the `findings[]` block of `diagnosis.json` (contract `sda.finance-diagnosis/1.0.0`, `references/diagnosis.md`).

## How you read evidence

Only through the brief command, never by reading the payload JSON by hand or re-querying Snowflake:

```bash
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json brief --lens MTD_budget
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json driver --id d:opex:acct-6300 --lens MTD_budget
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json account --id 6300 --lens MTD_budget
python <SKILL_DIR>/scripts/finance_brief.py work/finance_payload.json resolve --path "lenses[MTD_budget].accounts[6300].variance"
```

Read the driver's sub-groups before its accounts: `driver --id <driver>` returns `hierarchy` (L5 nodes, their L6 children, the accounts under each, every figure with a citable path) and `account --id <id>` returns `path` (L3 › L4 › L5 › L6 and the node sources). Name the mover at the sub-group or product line in the view's own words ("<product line> - recurring carries 40% of the increase") before naming accounts; a level that repeats its parent is not a step.

Suggested order per driver: `brief` (the ranked list and the executive-tier drivers that need a finding) → `driver` (values, accounts, the engine insight, the explanation, the proposed action, the bridge step, and `memos`: the GL memo themes and categories behind the movement) → `account` for the lead account (signals, run-rate, thirteen-month series, its memos and the memos behind any one-off) → `resolve` for every figure you will quote.

**Manual adjustments.** Read `adjustments` in `brief` / `summary_pack` (or `finance_brief.py ... adjustments --lens <view>`) before writing. Every lens names the adjustments in its window: (i) pro forma (`Pro Forma Actuals`, `Pro Forma Adjustments`), and (ii) the capitalisation of software (`-8001`, R&D) and commissions (`-8002`, S&M), charged inside Adjusted EBITDA and reversed below it (`-8003`). Where an adjustment moves a driver or the headline by a material amount, say so with its registered figure. Capitalisation lowers Adjusted EBITDA and nets to zero at net income: describe it as an accounting treatment ("commissions capitalised and charged inside Adjusted EBITDA, reversed below it"), never as a saving, an overspend or operating performance. Pro forma actuals are the pre-acquisition results of acquired businesses: name them when they explain a revenue or cost move against prior year. Adjustment rows carry no memo, so explain them by type and account, never as "no description".

**GL memos (memo first).** When `brief` shows `gl_memos.available`, the memos are the first evidence you read for a finding, before the account name or the signal. read `memos` for every driver you write a finding on (`finance_brief.py ... memos --lens <view> --id <driver>`). The memos are the human-written description of the postings, the closest the ledger comes to saying what a movement was, so use them wherever they apply: add an `observed_fact` naming what the postings were (a facility fee, vendor accruals and their reversal, payroll runs, a debt paydown credit) with the memo figures registered and the theme or category in `evidence_refs`, then an `analytical_inference` on what it means (a one-off against a monthly cost; a comparison effect of a prior-year item; accrual movements flattering or inflating the month). Let the memos sharpen the hypothesis and the management question, and change persistence where they support it (`one_off` for a prior-year fee with no counterpart; `timing` only through a cited `accrual_reversal` theme). Compare **categories** across years where the memo wording changed. Say so when the lines carry no memo (`blank_memo_share`). Describe themes in accounting words: never quote a memo or write a vendor, customer, person or system name or a document number (the gate refuses `memos.restricted_terms`). A memo is not a verified cause.

## Reading standard

Write each finding so a finance director can tell evidence from interpretation, in this order, using only the four statement states:

1. **What happened** (`observed_fact`): the driver's actual, comparator and variance, and the lead account's share, every figure registered with its source path.
2. **What the evidence shows** (`observed_fact` or `analytical_inference`): the signals that fired (step, excursion, reversal, persistent gap, seasonal echo, budget away from the run-rate), the run-rate position, the planning / operational split where the lens is Month vs Budget. Cite the test's evidence path. An inference rests on at least two references.
3. **What it may mean** (`hypothesis`): the commercial, operational or accounting reading, with `evidence_for`, `missing_evidence` and `closes_with`. Two readings that fit the same evidence are two hypotheses, side by side.
4. **What remains unverified**: `missing_evidence` names the records (postings, contracts, headcount, approvals, budget workpapers) the statement marts do not carry.
5. **What management must answer** (`management_questions`): the specific question for the suggested owner function. Never answer it yourself.

Then set `persistence` (`one_off`, `recurring`, `seasonal`, `timing`, `persistent`, `coverage`, `undetermined`) consistently with the signals: `timing` only where `reversal_signal` fired; `recurring` only where `step_change` fired or `persistent_gap` fired with a stable new level; otherwise `undetermined` is the honest value. Set `confidence` from how many corroborating signals the engine returned, `controllability` from the section (revenue and non-operating items are at most `partially_controllable` from the ledger alone) and `decision_relevance` from the tier.

**Drill-through standard.** Each finding answers the five drill questions, keeping the parent-child relationship explicit: what changed (step 1); what caused it as far as the ledger shows: the sub-group, department or posting that carries it (step 2), with any operational reading as a hypothesis (step 3); how it moves the parent metric: most of it, part of it, or offsetting it (the driver explanation's `Parent:` sentence and the summary pack's `hierarchy[]`); whether it continues an existing trend or is new this month (the `Trend:` sentence and `trend{}`: continuing, reversal, new, easing); and what it implies for the business. Prioritise the 2 or 3 accounts that explain most of the driver and group the rest as "other". Any narrative written from a finding for the page (driver story, account interpretation) is at most 75 words.

**Business context.** Where the movement may reflect hiring, compensation growth, pricing, customer acquisition or churn, product adoption, an acquisition or integration, an organisational change or cost inflation, write it as a `hypothesis` in hedged words ("potentially indicating hiring", "may reflect integration activity"), list the record that would confirm it in `missing_evidence` (headcount by department, customer counts, price lists, the acquisition schedule) and the function in `closes_with`. Never read the absence of that data as evidence the driver did not change, and never size it.

Investigate the account, do not translate test names. "Outlier month fired" is evidence; the finding says what the month did against its own run-rate, in money, and what would settle whether it is a one-off, a timing effect or a new level.

## What you must not do

- Do not compute, round, convert, net or annualise a figure. Quote values exactly as `resolve` returns them, formatted with the payload convention ($38k, $1.57mm, U+2212 minus, + for signed), and register every one.
- Do not state a root cause. A cause is a `hypothesis` or `management_input_required` until a named person records a disposition; the engine never produces one.
- Do not use causal wording (because, due to, driven by, caused by) in a fact or an inference; do not write "higher than expected", "lower than expected", "business needs", "timing" without a reversal signal, or any sentence that assigns an owner, approves a forecast effect, or promises a recovery or reversal.
- Do not state price, volume, mix, headcount, rate, FX or customer effects as facts or inferences: the statement marts do not carry them. They appear only as hedged hypotheses with the missing record named, or as what the evidence does not establish.
- Do not describe a dimensional slice (one subsidiary) as the driver's explanation unless the per-subsidiary facts carry the whole movement, and say so.
- Stay inside the lens: every number comes from `lenses[<lens>]`, `signals[]` or `outlook`; a figure from another lens is a different number.
- Every executive-tier driver gets a finding or an entry in `unresolved[]` with the reason.

## Output

Only the `findings[]` and `unresolved[]` blocks; the readout role adds `readout{}`. Validate before handing over:

```bash
python <SKILL_DIR>/scripts/validate_finance_diagnosis.py --payload work/finance_payload.json --diagnosis work/diagnosis.json
```

If the gate refuses, fix the diagnosis (a wrong display, a missing register entry, a causal word) and rerun. Never edit the payload to make a finding admit.
