# Question patterns

What the client will actually ask about bookings and pipeline, whether `GTM_ANALYTICS` can answer it, and the shape of the answer. Built from the client demo deck (Conversational AI and Agentic AI sections), the sample outputs (leakage workbook, Bookings Risk Review) and the view definition. Finance and ARR questions belong to the finance and ARR skills.

## Contents
1. How every answer is shaped
2. The deck's demo prompts: feasibility and recipe
3. Review pack (agentic recipe)
4. Style notes taken from the demo transcripts
5. Standard replies for gaps

---

## 1. How every answer is shaped

**Follow the hierarchy.** The view has top-down paths (`view-gtm.md` §3 and §6). The answer starts at the headline and descends **one level at a time**, stopping where the question stops. Never open at the bottom rung.

```
Level 1       the headline measure vs its comparison (prior period or prior year; there is no target)
Level 2       the first split down the view's own hierarchy (e.g. new ARR / upsell ARR / non-recurring, or stage)
Level 3..n    one further split per rung (product, subsidiary, opportunity source, region, owner, account)
Bottom        the booked or open opportunities, when asked or when the answer needs them
```

Contributors plus "all other" must sum to the total. If they don't, there's a filter or grain bug: fix it before answering (`query-playbook.md` §7).

**How it is written is set by `chat-answers.md`**: what happened → drivers (ranked, with "Other") → why (only what the data shows) → business impact (with a bridge), shown as short paragraphs, with a heading only on business impact, with all four blocks by default, under 200 words. A "why" claim the view can't show (a price change, a sales-ops decision) is never invented or hinted at: write "Reason not established in the data" and name who can confirm.

## 2. The deck's demo prompts: feasibility and recipe

Status key: **Full** = the view carries everything; **Partial** = answerable with a labelled proxy or a stop short of the demo's depth; **Gap** = needs data the view doesn't have (give the standard reply in §5).

### 2a. "Why did bookings go up? Then drill into the specific invoices behind the answer." Partial

| | |
|---|---|
| Tables | `BOOKINGS_OVERVIEW`, `BOOKING_LINES` |
| Recipe | Playbook §3. Window vs prior-year or prior-period twin (fiscal quarter or year to date built from months); split new ARR / upsell ARR / non-recurring; then product (recurring) and subsidiary (non-recurring); then top customers and booked opportunities from `BOOKING_LINES`. |
| Stops at | The won opportunity (recurring) or the month and subsidiary (non-recurring). **There is no invoice or sales-order fact in the view.** Say it: "I can take recurring bookings to the won opportunity; invoices aren't in the view." Don't present opportunities as invoices. |
| Watch for | Recurring bookings = Salesforce won ARR (New) and ARR (Upsell) ACV  on the close date; non-recurring = NetSuite non-recurring revenue on the period end date. Only completed month-ends appear, and the latest may not be closed in NetSuite yet. |

### 2b. "Which weighted pipeline shows limited activity and what risk does it pose to the overall pipeline?" Partial

| | |
|---|---|
| Tables | `OPPORTUNITIES`, `OPPORTUNITY_STAGE_HISTORY`, `PIPELINE_OVERVIEW` |
| What is missing | No next-step, last-activity or activity-count fields. The demo flagged deals with "no logged next step or no activity date": that exact lens is **not available** here. |
| Proxy to offer, labelled *derived* | (1) open deals whose expected close date has already passed; (2) open deals that have sat in their current stage longer than the usual completed stay in that stage (median or 90th percentile of `STAGE_END_DATE` − `STAGE_START_DATE` over completed stage runs), age = data as-of date − `STAGE_START_DATE` of the current run (`IS_CURRENT_STAGE`); (3) deals whose close date moved out between stage runs (`CLOSE_DATE` at the end of each run); (4) deals with one stage run only since creation. Size each tier in ACV and count and as a share of total weighted pipeline. |
| Traps from the demo | **Pipeline means open (`NOT IS_CLOSED`) and weighted (ACV × probability), not "not won"** (counting Closed Lost inflates the number). **Don't use today's clock against lagging data**: the demo's data sat months behind "now", so a 30-day staleness test flagged every deal. Measure age against the data's own as-of date (`DATA_REFRESHED_AT` or the latest `AS_OF_DATE`) and state both dates. |
| Output | Headline (flagged value, share of weighted pipeline, deal count), tier table, largest flagged deals as a bar chart, one-line methodology note naming the proxy. |

### 2c. "Bookings risk / revenue leakage across NetSuite and Salesforce." Partial: this is the biggest gap against the deck

The deck shows one reconciled view over Salesforce and NetSuite on a common Customer/Account ID, and the leakage workbook follows booking → sales order → invoice ("never converted", "under-invoiced", "CRM/ERP mismatch"). **That workbook was built on `EDW_ACCORDION.GOLD` fact tables (opportunity, sales order, invoice), not on the semantic views.** `GTM_ANALYTICS` carries no sales-order or invoice facts.

What the view *can* support, labelled *derived* and *candidate* (never "confirmed leakage"):

| Check | Compare | Level | Reading |
|---|---|---|---|
| Won not booked | `OPPORTUNITIES.WON_ACV_USD` (by `CLOSE_DATE` month) vs recurring `BOOKING_ACV_USD` (`BOOKING_METRIC IN ('ARR (New)', 'ARR (Upsell)')`, by `BOOKING_DATE` month) | total, product | Both sides are Salesforce won ARR (New) and ARR (Upsell) deals; a persistent gap is a scope difference (pipeline owner segments vs bookings teams) or a deal missing from one side. Non-recurring revenue has no opportunity and stays out. |

Bookings vs ARR (booked not in ARR, ARR with no booking) needs the ARR view: point the user to the ARR skill and compare at product × month level there. Size each bucket in $ and count, rank the top products and months, leave anything unattributable in an **"unmatched — needs data-owner review"** bucket. **Say plainly that invoice-level leakage needs sales-order and invoice data in a governed view**, and recommend the data team adds a reconciled booking-to-cash view. Don't recreate the leakage workbook from raw tables.

## 3. Review pack (agentic recipe)

### 3a. Bookings and pipeline review

Mirrors the bookings and pipeline half of the Bookings Risk Review. Quarterly series, latest four fiscal quarters (Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec). A request for the GTM review or the GTM dashboard always gets the three-tab GTM dashboard (`SKILL.md` Part A), never this pack. Build this pack only when the user asks for a quarterly bookings-and-pipeline pack, charts or Excel. It goes through the bundle path (`output-formats.md`), with the headline repeated in chat.

| Section | Content | Source |
|---|---|---|
| Executive summary | Short bullets: verdict, then the two or three things that explain it | derived |
| Headline KPIs (quarterly series, delta, direction) | Total bookings, recurring share, new ARR, upsell ARR, weighted pipeline, pipeline created, win rate | `BOOKINGS_OVERVIEW` (monthly `*_MTD` summed into fiscal quarters), `BOOKING_LINES` (`OPPORTUNITY_TYPE`), `PIPELINE_OVERVIEW` (`*_ASAT`, `IS_LATEST`), `OPPORTUNITIES` |
| Pipeline tiles | Weighted pipeline dated to close in the next fiscal quarter, average deal size, late stage (Align onwards) | derived |
| Bookings and pipeline table | Actual vs prior period vs prior year: new ARR, upsell ARR, recurring, non-recurring, total; weighted pipeline | `BOOKINGS_OVERVIEW`, `BOOKING_LINES`, `PIPELINE_OVERVIEW` |
| Biggest movers | Favourable / unfavourable, ranked by product and subsidiary | `BOOKINGS_OVERVIEW` |
| Recommendations | Data-backed, tagged by urgency | derived |

**Omit the sample's renewal-rate and coverage tiles.** The view holds no renewal opportunities and no pipeline target, so show "not available" instead of a proxy.

## 4. Style notes taken from the demo transcripts

- Lead with what happened (the headline vs its comparator), then the ranked drivers (`chat-answers.md`). A table only when three or more items are compared.
- **Correct yourself in the open.** If a first query was wrong (e.g. counted Closed Lost as open), say so in one line and re-run. Don't quietly swap the number.
- **Name the data limit honestly.** "Recurring bookings stop at the won opportunity; there are no invoices below this" is a good answer. A confident-sounding drill the data can't support is not.
- State the **currency basis** every time: GTM metrics are USD (`*_USD`); there is no constant-currency twin.
- Say **fiscal** with any quarter or year to date (the fiscal year is the calendar year: FY2026 = January to December 2026).
- Give the visual a job: ranked bars for "largest", a waterfall for any bridge, a line for trend, a ranked table for movers. Offer Excel or an HTML dashboard once, in one line, after multi-part analyses.
- Keep tool narration out of the answer ("I used the SQL Execution Tool"); show the SQL only when asked.

## 5. Standard replies for gaps

Use these only when the data cannot give an accurate answer. Lead with what the data does show, keep it to one or two sentences, write "Not available in the data" for the missing part, and name who can confirm.

| Ask | Reply |
|---|---|
| Invoices behind bookings | "The view takes recurring bookings down to the won opportunity, but it doesn't include sales orders or invoices. Here are the opportunities; invoice detail would need an invoice fact added to the model." |
| Renewal rate | "Renewal opportunities aren't in the view (only ARR (New) and ARR (Upsell)), so I can't give a renewal rate here. Churn and downsell dollars from the ARR skill are the nearest measure." |
| CAC, LTV, payback, magic number | "These need sales and marketing cost and renewal data that the GTM view doesn't hold. I can show bookings, new-sales bookings and pipeline created as the inputs." |
| Activity or next-step on deals | "The view doesn't hold activity or next-step data. As a proxy, here are open deals that have sat in their stage longer than usual or are past their expected close date." |
| Bookings plan, budget, pipeline target or coverage | "There is no bookings plan, budget or pipeline target in the data, so there is no coverage ratio. I've compared with the prior period and prior year instead, and shown weighted pipeline by fiscal close quarter." |
| Unweighted pipeline | "Pipeline here is weighted by the Salesforce probability. The unweighted open ACV is $X (labelled context); here it is by stage, with the late-stage share (Align onwards)." |
| Loss reasons | "The view has no loss reason. Here is lost ACV by the stage it was lost at, product, source and owner." |
| Leads, funnel before opportunity | "Leads aren't in the view; it starts at opportunity creation. Here is the funnel from creation onwards." |
| Revenue, EBITDA, cash, ARR, retention | "That comes from the finance or ARR view, which this GTM skill doesn't query. Use the finance or ARR skill for it." |
