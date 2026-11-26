# Question patterns (ARR)

What the client will actually ask about ARR and retention, whether `ARR_ANALYTICS` can answer it, and the shape of the answer. Finance and GTM questions belong to the finance and GTM skills.

## Contents
1. How every answer is shaped
2. Common ARR question types: feasibility and recipe
3. Style notes
4. Standard replies for gaps

---

## 1. How every answer is shaped

**Follow the hierarchy.** The view has top-down paths (`view-arr.md` §6). The answer starts at the headline and descends **one level at a time**, stopping where the question stops. Never open at the bottom rung.

```
Level 1       the headline metric vs its comparison (prior period, prior year)
Level 2       the first split (movement for ARR, product for retention)
Level 3..n    one further split per rung (product, customer)
Bottom        customer list when asked or when the answer needs them (capped at 100 rows)
```

Contributors plus "all other" must sum to the total. If they don't, there's a filter or grain bug: fix it before answering (`query-playbook.md` §7).

**How it is written is set by `chat-answers.md`**: the key number first, then the insight, in the shape the question needs (no fixed template). A "why" claim the view can't show (a price change, a contract decision) is never invented or hinted at: end at the deepest level the data supports and name who can take it further.

---

## 2. Common ARR question types: feasibility and recipe

Status key: **Full** = the view carries everything; **Partial** = answerable with a labelled proxy or stop short of full depth; **Gap** = needs data the view doesn't have.

### 2a. "What is our ARR, and how fast is it growing?" Full

| | |
|---|---|
| Tables | `ARR_OVERVIEW` |
| Recipe | `query-playbook.md` §2. Latest month-end card; prior-year same month for growth rate. Break out by segment and product if asked. |
| Watch for | Current open month may appear — label it partial. |

### 2b. "Walk me through the ARR bridge for Q3." Full

| | |
|---|---|
| Tables | `ARR_WATERFALL`, `ARR_OVERVIEW` |
| Recipe | `query-playbook.md` §4. Starting ARR + movements = Ending ARR; foot-check is mandatory. |
| Watch for | Contraction sign — probe whether the view stores it as positive or negative before showing the bridge. |

### 2c. "What is our NRR, and why did it drop?" Full (rate; non-additive)

| | |
|---|---|
| Tables | `ARR_OVERVIEW` (NRR rate), `ARR_WATERFALL` (movements) |
| Recipe | NRR card for the current and prior period; then decompose the change via expansion and churn movements by segment and customer. |
| Watch for | NRR is a trailing-12M rate — a single month's change in NRR reflects 12 months of movement, not just the latest month. Say so. Never sum NRR across segments. |

### 2d. "Which customers churned last quarter?" Full

| | |
|---|---|
| Tables | `CUSTOMER_ARR` or `ARR_WATERFALL` with `MOVEMENT_TYPE = 'Churn'` |
| Recipe | `query-playbook.md` §4 drill. Filter movement type and period; order by churned ARR descending; cap at 100 rows. Tie the total back to the bridge figure. |
| Watch for | Partial-month churn at the boundary of the period; state that the period is quarter-end closed months only. |

### 2e. "Which customers expanded the most?" Full

| | |
|---|---|
| Tables | `ARR_WATERFALL` with `MOVEMENT_TYPE = 'Expansion'` |
| Recipe | Filter, rank by expansion ARR descending, cap at 100. Tie to total expansion in the bridge. |

### 2f. "How has NRR trended over the last 12 months?" Full

| | |
|---|---|
| Tables | `ARR_OVERVIEW` |
| Recipe | `query-playbook.md` §5. Monthly NRR for the past 24 months (to show 12 months of trailing-12M rates). State the window definition. |
| Watch for | The trailing-12M NRR for month M uses data from M−11 through M, so the first 11 months of data produce partial trailing windows; flag if the series starts before 12 months of data exist. |

### 2g. "What is our logo retention rate?" Partial

| | |
|---|---|
| Tables | `LOGO_METRICS` |
| Recipe | Logo retention = (Starting Logos − Churned Logos) ÷ Starting Logos for the period. Label as *derived* if not a direct view metric. |
| Watch for | Logo retention answers a different question from NRR; a high-ARR customer churning barely moves logo retention but dominates dollar retention. Report both when health is the subject. |

### 2h. "Show me the ARR cohort curve for 2024 customers." Partial

| | |
|---|---|
| Tables | `CUSTOMER_ARR` or `ARR_WATERFALL` |
| Recipe | `query-playbook.md` §6. Filter to customers first appearing in 2024; compute retention ratio by month. Label as *derived*. |
| Watch for | The view may not expose a pre-built cohort metric. If you are constructing it from customer-level data, say so explicitly. |

### 2i. "Compare ARR with bookings — is booked ACV showing up in ARR?" Partial

| | |
|---|---|
| Tables | `ARR_WATERFALL` (New ARR), plus GTM skill for bookings |
| Limitation | The ARR and GTM views use different customer keys and different period anchors (ARR go-live date vs booking date). A formal reconciliation requires a data-team–managed mapping. |
| Offer | Compare New ARR (this skill) with New Bookings ACV (GTM skill) at product × month level as a *derived candidate*. Label every figure by its source and the expected timing difference. Say that confirmed leakage needs a reconciled billing view. |

---

## 3. Style notes

- Lead with the key number and the "so what", then the supporting numbers (`chat-answers.md`). A table only when three or more items are compared.
- **Correct yourself in the open.** If a first query was wrong, say so in one line and re-run.
- **Name the data limit honestly.** "The view goes to customer; there is no subscription-line or invoice grain" is a good answer.
- State the **currency basis** every time: USD.
- Give the visual a job: a waterfall for the ARR bridge, a line for NRR trend, ranked bars for "largest churned customers", a stacked bar for ARR by segment over time. Offer Excel or an HTML chart once, after multi-part analyses.
- Keep tool narration out of the answer; show the SQL only when asked.
- Negatives in brackets, percent points as `pp`, scale in `mn` / `k`, favourable / unfavourable. Movement amounts are signed for their effect on ending ARR (New and Expansion positive; Contraction and Churn in brackets when showing net impact).

---

## 4. Standard replies for gaps

Use these only when the data cannot give an accurate answer. Lead with what the data does show, keep it to one or two sentences, and name who can take it further; never use "not available / cannot" wording where the data supports an answer.

| Ask | Reply |
|---|---|
| Subscription-line or invoice detail behind ARR | "The view goes to customer-level ARR movements; it doesn't hold subscription lines or invoices. Here is the customer list; finer grain would need a billing-event view." |
| Renewal win / loss rate | "Renewals that cancel are captured as churn, and renewals at the same value generate no movement. I can show logo and dollar churn rates; GRR is the closest proxy for renewal health." |
| CAC, LTV, payback period | "These need sales and marketing cost from the finance view. I can show NRR, ARR growth and new-logo ARR as the ARR inputs." |
| ARR by region | "There is no region dimension in the view (**verify**). I can break it down by segment or product." |
| Bookings, pipeline, win rate | "Those come from the GTM view, which this ARR skill doesn't query. Use the GTM skill for bookings and pipeline." |
| Revenue on the income statement, EBITDA, cash, budget | "Those come from the finance view. Use the finance skill for P&L and budget questions." |
| ARR plan or ARR target | "There is no ARR budget in the view (**verify**). I've compared with prior period and prior year instead." |
