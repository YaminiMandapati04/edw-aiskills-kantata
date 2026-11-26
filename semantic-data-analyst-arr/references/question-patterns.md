# Question patterns (ARR)

This file covers what Yes Energy users ask about ARR, whether `ARR_ANALYTICS` can answer it, and the shape of the answer. Finance and GTM questions belong to the finance and GTM skills.

## 1. How every answer is shaped

Answers follow the hierarchy in `view-arr.md` §6 and descend one level at a time:

```
Level 1   headline (Ending ARR / movement / NDR %) vs prior month and prior year
Level 2   bridge category: New, Upsell, Downsell (Operational), Downsell (Translational), Churn
Level 3   customer attribute: segment, source system, industry, customer type
Bottom    customer list (≤100 rows, "All other" for the rest)
```

Contributors plus "All other" sum to the total. The writing itself follows `chat-answers.md`.

## 2. Common question types

Status: **Full** means the view carries everything. **Partial** means the answer uses a labelled derived figure. **Gap** means the data is not in the view.

| # | Question | Status | Tables / template | Watch for |
|---|---|---|---|---|
| 2a | "What is our ARR and how fast is it growing?" | Full | ARR_WATERFALL 5a | Ending ARR is a balance. YoY % is derived. |
| 2b | "Walk me through the Q3 ARR bridge." | Full | 5b (TOTAL_QTD) | Show Downsell (Operational) and (Translational). The bridge must tie. |
| 2c | "What is NDR / GDR, and why did it move?" | Full ($) / derived (%) | 5c, 5b | Both exclude New and Translational. % = ÷ Beginning ARR of the same window. |
| 2d | "Which customers churned / downsold / upsold?" | Full | 5d | Customer names only in chat. The list sums to the category. |
| 2e | "What was the FX impact on ARR?" | Full | 5e, 5d with 'FX' | Report it as Downsell (Translational), by source system. An FX gain is a favourable offset. |
| 2f | "How many customers did we add and lose?" | Full | CUSTOMER_BRIDGE 5f | Windows are independent; never add months. |
| 2g | "What is our logo churn rate?" | Derived | 5f | −Lost ÷ Beginning for the same window. |
| 2h | "ARR by product family / which products grew?" | Full (balance) / derived (change) | ARR_BY_PRODUCT 5g | No New/Upsell split by product. Keep Unmapped. |
| 2i | "ARR by segment / industry / system" | Full | 5h | NULL segment = "Not set" (RTO-only). |
| 2j | "Churn or upsell by product" | Gap | — | The buckets are decided at customer level; offer the 2h balance change. |
| 2k | "Cohort retention curve" | Partial | ARR_BY_PRODUCT by customer and month | Build it from customer balances (first month with ARR > $10). Label it derived. |
| 2l | "Is booked ACV showing up in ARR?" | Partial | New ARR here, plus the GTM skill | Different keys and timing. Treat it as a derived comparison only. |

## 3. Style notes

- Key number first, then the "so what". Use a table only for three or more items.
- USD at the monthly average rate, every time.
- Give each visual a job:
  - waterfall for the bridge (steps: Beginning, New, Upsell, Downsell (Operational), Downsell (Translational), Churn, Ending)
  - line for Ending ARR or NDR %
  - ranked bars for the largest movers
  - stacked bars for product or segment
- Negatives in brackets, `pp` for rate changes, `mn` / `k`, favourable / unfavourable.

## 4. Standard replies for gaps

| Ask | Reply |
|---|---|
| Churn / upsell / downsell by product | "The bridge assigns movements on each customer's total ARR, so it has no product split. Here is ARR by product family at both dates; the change is a balance difference, not a bridge." |
| Subscription, invoice or contract detail | "The view goes to customer level. Here is the customer list; Revenue Accounting can take it to contract level." |
| ARR by region | "There is no region dimension. The Maxio system (Yes Energy, RTO, APAC, EMEA, Multiple) is the closest cut, shown here." |
| FX at constant currency | "The view holds the FX movement each month, reported as Downsell (Translational). Here it is by month and system; constant-currency ARR needs Revenue Accounting." |
| Renewal win / loss, bookings, pipeline | "Those come from Salesforce in the GTM skill. Here are ARR churn and the lost-customer count." |
| CAC, LTV, payback | "These need cost data from the finance skill. Here are the ARR inputs: new ARR, NDR and churn." |
| ARR plan / target | "The view has no ARR plan. Here it is against the prior month and prior year." |
| Revenue, EBITDA, cash, budget | "Those are in the finance skill." |
