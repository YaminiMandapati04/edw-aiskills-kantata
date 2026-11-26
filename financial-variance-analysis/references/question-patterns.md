# Question patterns

What the client will actually ask, whether the Finance view can answer it, and the shape of the answer. Built from the client demo deck (Conversational AI and Agentic AI sections), the Financial Review sample output and the view definition.

## Contents
1. How every answer is shaped
2. The deck's demo prompts: feasibility and recipe
3. Review packs (agentic recipes)
4. Style notes taken from the demo transcripts
5. Standard replies for gaps

---

## 1. How every answer is shaped

**How it is written is set by `chat-answers.md`**: what happened → drivers (ranked, with "Other") → why (only what the data shows) → business impact (with a bridge), shown as short paragraphs, with a heading only on business impact, with all four blocks by default, under 200 words. This section covers how to find what goes in it.

**Follow the hierarchy.** The view has a top-down path (`view-finance.md` §3 and §6). Choose the largest movements by descending **one level at a time**, stopping where the question stops. Never open at the bottom rung.

```
Level 1       the headline measure vs its comparison (period, budget, prior year)
Level 2       the first split down the view's own hierarchy (Revenue / Cost of Sales / OpEx / below EBITDA)
Level 3..n    one further split per rung (L4, L5, L6, account, subsidiary)
Bottom        the GL lines, only when asked                                             → drill-through table
```

Contributors plus "all other" must sum to the total. If they don't, there's a filter or grain bug: fix it before answering (`query-playbook.md` §8).

Label **Governed / Derived / Scenario** as `SKILL.md` Step 4 describes. A "why" claim the view can't show (a price change, a management decision) is never invented or hinted at: write "Reason not established in the data" and name who can confirm (`chat-answers.md`).

## 2. The deck's demo prompts: feasibility and recipe

Status key: **Full** = the view carries everything; **Partial** = answerable with a labelled proxy or a stop short of the demo's depth; **Gap** = needs data the view doesn't have (give the standard reply in §5).

### 2a. "Highlight any standout high variances, and drill down to transaction level to show the top 5." Full (to the GL line), with a currency caveat

| | |
|---|---|
| Views | Finance `INCOME_STATEMENT` then `TRANSACTIONS` |
| Recipe | Pull actual, budget, prior year by account (number + name within subsidiary, classes summed; roll-up keys excluded: `view-finance.md` §3) for the period; rank the movers at `L5` / `L6` first (sub-groups and product lines, named in the view's own words: "<product line> - recurring drove 40% of the increase", never by account number), then the accounts beneath the top sub-groups by absolute movement, including accounts active in only one period; keep the top 5. **Exclude subtotals** (EBITDA, EBIT, gross profit, net income): they are roll-ups of other lines and have no transactions of their own. Group the story by `COA_MAPPING_L3`. For each top account, pull the largest GL lines for the period **range** and tie them back to the mart variance. |
| Watch for | Sign on expense rows before calling a variance favourable or adverse (open item 9). GL amounts are raw transaction currency; mart amounts are converted: size any FX gap in the tie-out. If the ledger bottoms out at monthly journals with no customer or document detail, say so rather than implying more granularity (the demo did exactly this). |
| Output | Ranked table (rank, line, actual, budget, variance, %), then a top-5 postings table per line, then the tie-out sentence. |

### 2b. "How volatile is operating cash flow? Trace it to its drivers and down to individual transactions." Full to driver, Partial to transactions

| | |
|---|---|
| Views | Finance `CASH_FLOW` (monthly) then `TRANSACTIONS` |
| Recipe | Playbook §5. Monthly Cash from Operations (`CASH_FLOW_L1`) for 24 months (at least 12): mean, standard deviation, coefficient of variation, min, max, worst and best month, all *derived*. Benchmark against revenue volatility or seasonality. Decompose by `CASH_FLOW_L2` / `L3` (net income, non-cash items, working capital by line) and show which component's variance contributes most. |
| Stops at | The GL layer lacks a confirmed cash-flow bridge metric (open item 1). Drill the worst month's biggest drivers to GL lines through the account hierarchy (amount in transaction currency), or stop at the account level and say so. |
| Output | Volatility in words and numbers, trend chart with the worst month marked, driver table, then the biggest transactions if reachable. |

### 2c. "Run a liquidity stress test: does the cash trough stay above the undrawn revolver?" Partial (scenario)

| | |
|---|---|
| Views | Finance `CASH_FLOW` (`BEGINNING_CASH_MTD`, `ENDING_CASH_MTD`, `NET_CASH_FLOW_MTD`); `BALANCE_SHEET` for debt |
| Recipe | Playbook §6. Base = actual ending cash by month. Levers are assumptions: collections slowdown (delay N days or % of receipts), revenue −10 / −20 / −30%, a one-off outflow. Apply them period by period in a shown calculation. |
| **Gap** | Revolver size, drawn and unused are **not in the view**. Ask the user for the facility amount (and any minimum-cash covenant) before concluding anything. Without it, report the trough and headroom against zero or the stated minimum cash, and say the revolver comparison is pending. |
| Output | Lever → trough → headroom table, break-even shock, the trough month, and a bold "Scenario: illustrative assumptions" label on the answer, chart and export. |

### 2d. "Automated monthly variance analysis and narrative." Full

Playbook §7a. Layers: `INCOME_STATEMENT` for the movers (actual vs budget and vs prior year by L3, then L4, then account), `TRANSACTIONS` only to explain a one-off or timing item. Tag each mover `volume`, `price`, `mix`, `timing`, `one-off` or `unexplained`. The view carries no volume or price data for the P&L, so most tags will honestly be `unexplained`; `timing` needs a reversal in the data and `one-off` a single GL item. Fixed output shape in §3a below.

## 3. Review packs (agentic recipes)

One pack mirrors the Financial Review sample. It is a fixed shape over several queries; produce it as an HTML dashboard and Excel from one result bundle (`output-formats.md`), with the headline repeated in chat.

### 3a. Monthly finance review (variance narrative)

Mirrors the Financial Review's Overview tab.

| Section | Content | Source |
|---|---|---|
| Executive summary | Verdict (positive / mixed / warning / negative) and 3–4 sentences: result vs comparison, the two or three things that explain most of it | derived from below |
| Headline KPIs | Revenue, gross margin, Adjusted EBITDA and margin, net income, cash, working capital, net debt, each with value, period-on-period or year-on-year delta, and direction of travel (improving, stable, softening, deteriorating) | marts |
| Liquidity, leverage and working capital | Cash, current ratio, net debt, AR, AP | balance sheet mart |
| Actual vs budget vs prior year | P&L by L3 with variance $ and %, **EBITDA bridge**: budget EBITDA → revenue variance → cost-of-sales variance → OpEx variance → actual | income statement mart |
| Biggest movers | Favourable and adverse, ranked by absolute impact at `L5` / `L6` first (product lines, sub-groups) and then by account beneath them, described in L6 language rather than by account number, each with cause tag and "what that means" | mart, then GL |
| Recommendations | Specific, owned, tagged by urgency (now / this quarter / opportunity) | derived |
| Data caveats | Provisional periods, unmapped lines, currency basis, open items that apply | registry |

Unit drill-down (the sample's second tab) maps to **by subsidiary** (or department, class) using the same metrics: one panel per member with revenue share, margin, "what's going best / what's dragging" and a commentary row, as the view's dimension values allow.

## 4. Style notes taken from the demo transcripts

- Lead with what happened (the headline vs its comparator), then the ranked drivers (`chat-answers.md`). A table only when three or more items are compared.
- **Correct yourself in the open.** If a first query was wrong, say so in one line and re-run. Don't quietly swap the number.
- **Name the data limit honestly.** "All revenue posts as monthly journal entries, so there is no customer-level detail below this" is a good answer. A confident-sounding drill the data can't support is not.
- State the **FX basis** every time money crosses currencies. Here: marts are converted reporting currency, GL lines are raw transaction currency.
- No judgement words (strong, weak, healthy, concerning) and no labels the data doesn't show (FX, non-cash, demand, timing, pricing): `chat-answers.md`.
- Give the visual a job: ranked bars for "largest", a waterfall for any bridge, a line for trend and volatility, a ranked table for variances. Offer Excel or an HTML dashboard once, in one line, after multi-part analyses.
- Keep tool narration out of the answer ("I used the SQL Execution Tool"); show the SQL only when asked.

## 5. Standard replies for gaps

Use these only when the data cannot give an accurate answer. Lead with what the data does show, keep it to one or two sentences, write "Not available in the data" for the missing part, and name who can confirm.

| Ask | Reply |
|---|---|
| A cause the data can't show ("why did S&M go up?") | "S&M is up $X (Y%) vs <comparator>, almost all in <accounts and amounts>, <trend or offset>. <Functional lead> can speak to what is behind the increase." |
| A forecast ("where will EBITDA land?") | "A mechanical range only: $X to $Y, assuming <run-rate months, remaining budget phasing>. No single-point forecast." |
| Revolver headroom | "The facility isn't in the data. What is the revolver size (and any minimum-cash requirement)? Meanwhile, the cash trough is $X in <period>." |
| CAC, LTV, payback, magic number | "These need data the Finance view doesn't hold; the dashboard lists SaaS Metrics as future scope. I can show GL expense lines by department as inputs." |
