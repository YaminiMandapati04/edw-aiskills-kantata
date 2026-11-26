# Dashboard contract: the GTM diagnostic renderer

> **Status: live, with the AI review.** Renderer **1.11.0** (`artifacts/gtm_analytics/gtm_analytics.js`, assembled by `scripts/gtm/render.py` from governed extracts via `build_gtm_dashboard.py` or a local workbook via `build_sample_dashboard.py`; 1.9.0 is the Yes Energy build: no targets, coverage or weighted pipeline, fiscal quarters) reads payload contract **sda.gtm-analysis/2.0.0** and, when present, an admitted diagnosis of contract **sda.gtm-diagnosis/1.0.0**. It refuses anything else. The whole payload is embedded in the HTML as the audit record; what is on screen is what is in the payload. Field names below are the target shape; the build may refine them and must update this file when it does.

## Contents
1. Assets
2. The separation of powers
3. Payload structure
4. Tabs, regions and what each reads
5. Interaction rules and must-nots
6. Badges
7. Changing the renderer

---

## 1. Assets

| Asset | Role |
|---|---|
| `artifacts/gtm_analytics/template.html` | Shell, shared with the finance dashboard: dark header (scope chips, Window and Compare toggles), banner slot, numbered tabs with the tab question and the data badge, three views, glossary, one drawer, tooltip, footer; five pinned markers (`SDA:TITLE`, `SDA:CSS`, `SDA:BANNER`, `SDA:PAYLOAD`, `SDA:JS`) |
| `artifacts/gtm_analytics/gtm_analytics.css` | The reference report design system, as in finance renderer 1.4.0: dark-grey banner `#1F242F` with a 3px lime `#EEFB87` rule; Messina Sans (fallback Calibri, Carlito, Arial) with mono uppercase labels; surfaces `#F2F4F9` / `#DEE2E9`, hairlines `#C2C7CF` at 0.75px; dark table headers with banded rows; square corners; higher `#3BA184`, lower fills `#BF9856` with negative figures in `#B23A3A`; one fixed light theme (the page reads the same whatever the browser's colour scheme); no webfont fetch. The glossary is tab-aware ("This tab" / "All labels") |
| `artifacts/gtm_analytics/gtm_analytics.js` (to build) | Formats and arranges the payload; three render functions, the glossary, one drawer, string-built SVG and CSS charts. Chart primitives (waterfall, line, diverging bars, magnitude bars, range bars, gauges) are ported from the finance renderer |
| `artifacts/gtm_analytics/VERSION` | Renderer and contract pins |
| `scripts/render_gtm_dashboard.py` | Renders a saved payload with the admitted reviews: runs the diagnosis gate (`scripts/gtm/diagnosis.py`) on each `--diagnosis` file, attaches them as `diagnoses`, assembles the page with `scripts/gtm/render.py`; no HTML on refusal, or when the opening view has no review (unless `--allow-missing-review`) |

The assets are never edited for one engagement. Everything variable travels in the payload.

## 2. The separation of powers

The renderer performs **no analytical computation**. It never derives a variance, a share or a win rate, never infers a classification, never fills a blank, never calls a model. The complete list of arithmetic it may do:

| # | Where | Permitted | Why it is presentational |
|---|---|---|---|
| 1 | every chart | geometry of bars, lines and labels | scaling, not economics |
| 2 | driver trend | sum of engine-emitted monthly series over a driver's members | aggregation of emitted values |
| 3 | stage × quarter grid | placing engine-emitted cells | layout |

Unavailable is never zero: `null` renders `—`, `no prior quarter`, `no prior year`, `not calculated`, `withheld`, `not proposed`. Every proposal carries its state ("proposed · awaiting disposition", "scenario: proposal only, credit 0"); nothing reads as assigned, approved or verified.

## 3. Payload structure

```
contract_version          "sda.gtm-analysis/2.0.0"
meta                      title, view, data_mode, currency, as_of{label, month_end, quarter, fiscal_year}, primary_lens,
                          fiscal{start_month: 2, year, year_start, quarter, rule}, scope{products, subsidiaries, filtered_to, note},
                          months_of_history, generated_at, materiality, sources, renderer_version, window_labels, basis_labels,
                          data_refreshed_at. Quarters are fiscal (1 January to 31 December; labels FY2026-Q3).
series                    monthly bookings (actual, py) by measure, product and subsidiary; monthly pipeline created (actual, py)
drivers[]                 id (m:arr_new "New ARR" | m:arr_upsell "Upsell ARR" | m:non_recurring "Non-recurring" | p:<slug> | s:<slug>),
                          label, dimension (measure | product | subsidiary)
signals{<driver id>}      runrate{months, mean, min, max, stdev, reference, eligible, reason}, tests[]{id, label, state, evidence, note},
                          fired[], persistence_hint, confidence
lenses{<WINDOW>_<basis>}  WINDOW in MTD, QTD, YTD, LTM; basis pq: bookings against the same months one quarter earlier
                          (Oct 2026 vs Jul 2026; LTM Nov 25–Oct 26 vs Aug 25–Jul 26). QTD is the fiscal quarter to date (Aug–Oct for
                          October). YTD_pq is always available: false with a reason (a fiscal year to date shifted back a quarter is not a
                          fiscal period). Every comparison figure inside a lens is the
                          prior quarter's and is named cmp: range{label, cmp_label}, cmp_short ("last quarter"), conversion_cmp,
                          conv_size_cmp, velocity.cmp, lost.cmp, kpis[aov].orders_cmp, kpis[pipeline_created].count_cmp,
                          kpis[win_rate].closed_cmp, concentration.top_customers[].cmp. Outside the lenses, py keeps meaning a real
                          prior year (series, pipeline.py, created_trend, velocity_trend, rest_of_year).
                          available, range, kpis[], drivers{measure[], product[], subsidiary[]} each {id, actual, comparator, variance, variance_pct,
                          share_of_abs_variance, tier}, bridge{by_measure, by_product, by_subsidiary: {start, end, steps[], control}},
                          concentration{top_customers[], top_orders[], top5_share, largest_order_share}, insights[], actions[],
                          story{lead, lines[]}, headline{text, slots}
conversion                for each window: win_rate, (prior quarter in lenses[].conversion_cmp), won{acv, count}, lost{acv, count}, by_product[], by_source[],
                          loss_reasons[] (empty: the view has no loss reason)
pipeline                  point in time at the analysis date, weighted (ACV × probability): open, open_count, avg_value (each with py);
                          by_close_quarter[]{id, quarter, open, count, late_stage} (fiscal close quarters, current and next three);
                          in_quarter{quarter, open, count} (the next quarter when the analysis month is a quarter end); earlier_quarters_open;
                          by_stage_quarter[]; stage_days[]; risk{past_due{value, count, share}, aged{value, count, share}, deals[]};
                          won_vs_booked[] (won opportunity ACV vs recurring bookings by fiscal quarter). No target, coverage or weighted field.
rest_of_year              fiscal_year, months (to January), py_full, py_rest, ytd, to_match_py, to_hold_growth, growth, credit: 0
outlook                   scenario[]{quarter, open, win_rate_applied, at_win_rate, low, high, py_quarter, py_won}, rule, credit: 0, note
qc                        status, checks[], caveats[]
capabilities              invoices, renewals, discounts, activity, plan (targets and coverage), loss_reasons: state and reason ("not in the view")
analysis_hash             SHA-256 of everything above; the diagnosis binds to it
diagnoses (render only)   the admitted reviews keyed by view id, each with admitted_at and warnings; review {required, admitted, missing}
```

Identities the engine enforces and the validator re-checks: Total = Recurring + Non-recurring and Recurring = New ARR + Upsell ARR for actual and comparator in every lens; every bridge reconciles (start + Σ steps = end, to the cent); drivers in one dimension sum to the total; booking lines tie to `BOOKINGS_OVERVIEW` `TOTAL_BOOKINGS_MTD` for every month (QC `mart_tie_out`). QC `as_of_complete` (INFO) records a step back from a month NetSuite has not closed.

Paths follow `lenses[QTD_pq].drivers.measure[m:arr_new].variance`: `[x]` selects a dict key or the list element whose `id` is `x`.

## 4. Tabs, regions and what each reads

| Tab | Question in the tab bar | Regions (`id`) | Reads |
|---|---|---|---|
| Pipeline (first; the page opens on it) | Will the pipeline turn into bookings, and what needs a decision? | `pipe-exec`, `kpis-pipe`, `pipe-risk`, `pipe-asks` | Executive summary: 3 to 5 bullets from `lenses[].pipeline_insights` (velocity lead, then high-value exposure, not closing, stuck, conversion). Side cards: days to win (`lenses[].velocity`), high-value deals at risk as a share of weighted pipeline (`risk.high_value.flagged`), not closing (`risk.not_closing`), stuck (`risk.stuck`). Pipeline at a glance: open, closing this quarter (`pipeline.in_quarter`), pipeline created, win rate, lost. Chart: where the pipeline is at risk by stage (`risk.at_risk.by_stage`). Decisions: `lenses[].pipeline_actions` (high value at risk, not closing, stuck only). Deal lists only in drawers |
| Bookings | Where do bookings stand, why, and what needs a decision? | `book-exec`, `kpis`, `book-movers`, `book-asks` | Executive summary from `lenses[].insights` (lead, persistence, concentration, products, quality, size). Side cards: recurring share, average deal value, top two and top five customers (shares of recurring bookings), largest deal. Bookings at a glance in order of build-up. Chart: what moved bookings by measure / product / subsidiary (drivers). Decisions: `lenses[].actions` (concentration, product decline, recurring-share drop). The bridge opens from the Total bookings drawer |
| Outlook | What could the pipeline deliver in the quarters ahead? | `out-tiles`, `out-close`, `out-scenario`, `out-wvb`, `out-gaps` | Tiles: closing this quarter, scenario range, pipeline created. Weighted pipeline by fiscal close quarter (`pipeline.by_close_quarter`, no ratio), won vs recurring bookings, the scenario range, pipeline created by month, and what the data cannot answer yet (`capabilities.renewals`, `discounts`, `retention`). No tables |
| Glossary | | `glossary` | collapsible, tab-aware table: Direction, Figures, Where the numbers come from, one group per tab, Detail panels, Publication state |
| Drawer | | `dh`, `dbody` | kpi, driver (and bridge step), customer and deal list, quarter, stage, risk tier, action, finding, qc; charts first, text last |

## 5. Interaction rules and must-nots

- Window (Month, Quarter to date, Year to date, Last twelve months) switches between the precomputed `<WINDOW>_pq` lenses; nothing is recomputed. Year to date is shown disabled, with the lens's `reason` as its tooltip. The page opens on Quarter to date (fiscal). Compare shows "vs Prior quarter" only: the view has no plan or target. A chip in the header shows the fiscal year and quarter.
- An admitted review applies to its view: the executive summaries, decisions and Bookings "What this means" change with the window and fall back to the engine reading where the view has no review; the Pipeline and Outlook readings (snapshot and projection) show on every view. The data badge and footer say "AI reviewed" or "This view not AI reviewed" (`references/diagnosis.md` §7).
- Summary has only small charts (the diverging movers bars, the side-card gauges). The bookings bridge opens from the Total bookings drawer; weighted pipeline by close quarter only on Outlook.
- No fourth tab. A data-quality problem surfaces through the existing components: the QC badge and drawer, caveats beside the numbers they qualify.
- Progressive disclosure: executive summary → KPI strip → movers and decisions → drawer. A reader never needs a drawer to learn the direction of bookings, the three largest drivers or what is dated to close next quarter.
- Customer names appear in the summary only where an insight names the customers behind a movement, and in Drivers panels and drawers, capped at the top ten.
- Wording: negatives print in brackets `(45)`, never with a minus; `favourable` / `unfavourable` / `in line`, never "adverse"; `mn` not `mm`. Engine prose passes through `clean()` for the same rules.
- Offline single-file HTML: zero external requests, no CDN, no webfont fetch. The test asserts no `src="http` / `href="http`.
- Must-nots the test asserts: no `undefined`, `NaN`, `[object Object]` or "adverse" in the DOM; at least one waterfall; every region populated; no target, coverage, floor or weighted figure anywhere.

## 6. Badges

There is **no status banner** under the header: it was removed from every dashboard. The publication state lives in the data badge and the tags. The data badge in the tab bar repeats the QC status and opens the QC drawer.

Tags carry state, never inference: direction (`favourable`, `unfavourable`, `in line`; `ahead` / `behind` on KPIs), persistence (`One-off?`, `Recurring`, `New level`, `Seasonal`), method (`proxy` on stage-age risk, `scenario` on the outlook), publication state (`engine baseline` amber, `admitted diagnosis` green). Decisions always read "proposed, not approved".

## 7. Changing the renderer

1. Edit the asset in `artifacts/gtm_analytics/` for everyone, never for one request.
2. If the payload shape changed, bump `CONTRACT_VERSION` in `scripts/gtm/__init__.py` and the check in the JS; if only presentation changed, bump `RENDERER_VERSION`. Update `VERSION` and this file.
3. Run `python scripts/test_gtm_pipeline.py --keep --out work/test` and open the rendered files; the headless DOM check must pass.
4. Keep the allowlist in §2 true. When the payload gains content, the question is which existing component expresses it, not which panel to add.

**1.9.0** (Yes Energy) removes `pipeline.coverage`, `pipeline.weighted`, `pipeline.created_vs_target`, `pipeline.view_coverage_ratio`, `meta.coverage_floor` and `meta.view_schema`; adds `pipeline.by_close_quarter`, `pipeline.in_quarter`, `pipeline.earlier_quarters_open`, `meta.fiscal`, `meta.as_of.fiscal_year` and `rest_of_year.fiscal_year`. QC drops `forward_targets` and `coverage_window` and adds `as_of_complete`. Measures read New ARR, Upsell ARR and Non-recurring; orders read as deals. The contract id is unchanged.

**1.5.0** adds `short` to every insight (the one line on the page, at most 15 words, no figures) and to every action (the first question clause, at most 12 words); the page shows the short line and opens the full `text` / `question` above the drill-down when the bullet or decision is clicked. Payload additions only; contract unchanged.
