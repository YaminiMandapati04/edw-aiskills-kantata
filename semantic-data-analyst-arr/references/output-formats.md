# Output formats and the result bundle

Every file output (charts, Excel, HTML dashboard) is built from one JSON **result bundle**. Build it once from the query results, validate it, and feed it to the scripts. That keeps the chat answer, the workbook and the dashboard consistent — they can't drift because they share one source.

## Contents
1. Choosing outputs
2. The result bundle contract
3. Column types and formatting
4. Chart types
5. What each export contains
6. Build commands and checks
7. Brand and fonts
8. Reference outputs and how the scripts compare
9. Integrity checks: one set of numbers

---

## 1. Choosing outputs

| The user says… | Produce |
|---|---|
| A question, nothing about files | Chat answer only. Offer a file in one line if the analysis is multi-part. |
| "chart", "graph", "visualise" | Chat answer + PNG chart(s) via `make_chart.py` |
| "Excel", "spreadsheet", "export", "download the data" | `.xlsx` via `export_xlsx.py` |
| "dashboard", "HTML", "something I can share/open" | `.html` via `build_dashboard.py` |
| "give me everything" | all three, same bundle |

Do not create a file when a short chat answer fully serves the question.

## 2. The result bundle contract

Save as `bundle.json` in a scratch folder (e.g. `work/` under the project; not committed). Required keys are marked; everything else is optional and omitted sections simply don't render.

```json
{
  "meta": {
    "title": "Bookings increase — Q3 FY26",            // required
    "question": "Why did bookings go up?",
    "period": "FY26 Q3 vs Q2",
    "as_of": "2026-10-27",
    "currency": "USD",
    "scale": "$ millions",
    "sources": ["DB.SCHEMA.GTM_ANALYTICS"],
    "data_mode": "governed"                              // "governed" (default) or "local" (uploaded workbook)
  },
  "headline": "Bookings rose $4.2mn (+18%) ...",         // 1–3 sentences, same as the chat headline
  "kpis": [
    {"label": "Bookings", "value": 27.6, "format": "currency_mm",
     "delta": 0.18, "delta_format": "percent", "note": "vs Q2",
     "source": {"table": "by_segment", "column": "Q3 bookings ($mn)", "row": "total"}}
  ],
  "tables": [
    {
      "id": "by_segment",                                // required, unique, [a-z0-9_]
      "title": "Bookings by segment",                    // required
      "provenance": "governed",                          // governed | derived | scenario
      "columns": [
        {"name": "Segment", "type": "text"},
        {"name": "Q3 bookings ($mn)", "type": "currency_mm", "total": "sum"},
        {"name": "Change vs Q2", "type": "percent"}
      ],
      "rows": [["Enterprise", 14.2, 0.38], ["Mid-market", 9.1, 0.04]],
      "sql": "SELECT ...",                               // the statement that produced it
      "row_count_total": 2,                              // if rows were capped, the true count
      "capped": false
    }
  ],
  "charts": [
    {"id": "seg_chart", "title": "Bookings by segment", "type": "column",
     "table": "by_segment", "x": "Segment", "y": ["Q3 bookings ($mn)"],
     "provenance": "governed"}
  ],
  "findings": [
    {"text": "Two segments explain 71% of the increase.", "evidence": "established", "tag": "volume"},
    {"text": "Timing coincides with the Q3 price change — not in the views; confirm with Sales Ops.",
     "evidence": "hypothesis"}
  ],
  "definitions": [
    {"metric": "Bookings", "view": "GTM_BOOKINGS_VIEW", "definition": "Closed-won amount, as defined in the view."}
  ],
  "caveats": ["Q3 is provisional until close; 3 opportunities pending approval."]
}
```

Rules:
- Every row has exactly one value per column, in column order. `null` is allowed for missing values.
- Percentages are **fractions** (`0.18` = 18%). Currency amounts are already in the scale named by `meta.scale` for `currency_mm`.
- `charts[].table` must match a table `id`; `x` and every `y` must match column names in it.
- Put the exact SQL in each table's `sql`. The Excel "SQL & lineage" sheet and the dashboard's collapsible SQL read it.
- `provenance` is how the scripts badge each table and chart: **governed** (straight from a semantic view), **derived** (computed from governed outputs), **scenario** (assumption-driven). A scenario table must also list its assumptions as a table or in `caveats`.
- `kpis[].good` (optional, `"up"` default or `"down"`) says which direction of `delta` is favourable; use `"down"` for costs, churn, DSO. It sets the delta colour in the dashboard.
- `kpis[].source` (recommended, checked when present) names the table cell the KPI came from: `{"table": id, "column": name, "row": <index> | {"column": name, "equals": value} | "total"}`. `bundle.py` fails if the KPI value differs from that cell.
- `meta.data_mode: "local"` marks results from an uploaded workbook. It adds a "LOCAL TEST DATA" banner to every output and forbids `provenance: governed` on any table or chart.
- `findings[].evidence` is `established` or `hypothesis`; `tag` (optional) is one of `volume`, `price`, `mix`, `timing`, `one-off`, `unexplained`.

Validate before any export:

```bash
python scripts/bundle.py bundle.json          # prints OK or a list of problems; exit 1 on problems
```

## 3. Column types and formatting

| `type` | Stored as | Displays as |
|---|---|---|
| `text` | string | as is |
| `date` | `YYYY-MM-DD` string | date |
| `integer` | number | `1,234` |
| `number` | number | `1,234.5` |
| `currency` | number (whole currency units) | `$1,234` |
| `currency_mm` | number (millions) | `$12.3` (header should carry the unit, e.g. "($mn)") |
| `percent` | fraction | `18.0%` |
| `multiple` | number | `1.4x` |

Negatives show in parentheses and in alert red (`#B23A3A`) in Excel and the dashboard. Zero shows as a dash. `total: "sum"` adds a SUM formula row in Excel (only on additive columns — never on percent or multiple).

## 4. Chart types

| `type` | Use for | Spec notes |
|---|---|---|
| `line` | trend over time | `x` = period column, `y` = one or more series |
| `column` | comparison across categories / periods | `y` may have 2–4 series (clustered) |
| `bar` | ranked lists (top customers, accounts) | horizontal; sort the table descending first |
| `waterfall` | bridges: variance walks, bookings bridge | one `y`; give `"totals": ["Start", "End"]` — labels in `x` that are full bars from zero; others float as deltas |

In Excel the waterfall is built from a formula-driven helper block and cannot draw below zero; if the running total goes negative, the workbook shows a note instead and the HTML dashboard and PNG draw it correctly. Lines break at missing values rather than bridging the gap.

Keep to 1–4 series. A chart earns its place when it shows something the table doesn't (a trend, a ranking, a bridge).

## 5. What each export contains

**Excel (`export_xlsx.py`)**
- `Summary` — title, question, period, headline, KPIs, findings (tagged established / hypothesis), caveats, sources, as-of.
- One sheet per table — branded header, banded rows, native number formats, frozen header, filters, SUM total rows (formulas) where requested, a provenance label, and any native charts that reference that table.
- `Definitions` — metric definitions as the semantic view states them.
- `SQL & lineage` — each table's SQL, view, row counts and cap flags.

**HTML dashboard (`build_dashboard.py`)** — a single self-contained file: header banner (title, period, source, currency/scale, as-of), KPI tiles, findings, charts with a hover tooltip on every data point, drill tables, definitions, caveats, and collapsible SQL. No external scripts or fonts; works offline.

**Charts (`make_chart.py`)** — one PNG per chart, brand-coloured, titled with its provenance label when it isn't governed.

## 6. Build commands and checks

```bash
python scripts/bundle.py bundle.json
python scripts/make_chart.py bundle.json --outdir outputs/
python scripts/export_xlsx.py bundle.json outputs/<name>.xlsx
python scripts/check_xlsx.py outputs/<name>.xlsx   # must report 0 errors (needs LibreOffice; exit 2 = unchecked)
python scripts/build_dashboard.py bundle.json outputs/<name>.html [--fonts-dir fonts/Managed]
```

Run these with the virtual environment built from `requirements.txt` (kept outside OneDrive, e.g. `C:\Users\<you>\venvs\semantic-data-analyst`). Name files descriptively (`bookings-drivers-fy26-q3.xlsx`), not `output.xlsx`. Tell the user the file paths; workbook first, then dashboard, then charts.

Spot-check after building: a total in the file equals the number in the chat answer; the chart's top bar matches the table's top row; no `None`, `nan` or `#` errors visible.

## 7. Brand and fonts

Accordion brand: Gray 7 `#1F242F` structure and headers, Citron `#EEFB87` as accent fill only (never text on white), Gray 5 body, Gray 1/2 bands, Mint `#3BA184` positive, Almond `#BF9856` caution, alert red `#B23A3A` for negatives only. No gradients, shadows or rounded containers. Messina Sans is the brand font; the scripts fall back to Calibri / Courier New when it isn't embedded (the documented brand fallback). To embed it in the HTML dashboard, unzip the uploaded `Fonts.zip` and pass `--fonts-dir`; Excel can't embed fonts, so the workbook uses the fallback.

## 8. Reference outputs and how the scripts compare

The client's sample outputs (`Sample Outputs/`) set the target look and content. Map them onto the bundle like this:

| Sample element | In the bundle | Status |
|---|---|---|
| Bookings Risk Review / CFO Financial Review HTML: headline verdict, executive summary, KPI cards with sparkline, delta and direction of travel (improving / stable / softening / deteriorating) | `headline`, `kpis` (`good`, `delta`) | Supported; direction colour comes from `delta` and `good`. No separate verdict class or sparkline series. |
| Bookings bridge (waterfall) | `charts` with `type: waterfall` and `totals` | Supported. Prior-year vs prior-period toggles: build two charts. |
| "What's working / needs attention", biggest movers (favourable / unfavourable), "what that means" | `findings` (`evidence`, `tag`) and a movers `table` | Supported as findings and tables; no separate favourable / unfavourable panels. |
| Recommendations tagged by urgency (now / this quarter / opportunity), data caveats, dataset lineage | `findings`, `caveats`, `definitions`, per-table `sql` | Urgency tags are not a field: put them in the finding text. |
| Leakage workbook: Glossary, Executive Summary, Calculations, raw line-item tabs, section divider tabs, Version Control | `Summary`, one sheet per table, `Definitions`, `SQL & lineage` | Different tab set. Equivalent content except dividers and the version-control tab. |
| Unit drill-down tab (per business unit) | one table and chart per member | Build per member; no dataset switch. |

**Not in the scripts today:** a verdict class, sparkline series, urgency-tagged recommendation blocks, a dataset switch, divider and version-control sheets. If the client wants pixel-parity with the sample HTML and workbook, extend `build_dashboard.py` and `export_xlsx.py` and `bundle.py` together; don't hand-edit outputs.

Rules the samples follow and these outputs should keep: state the currency basis and FX rate on the summary (the leakage workbook says "All amounts in GBP; USD at 1.35"), keep headline figures consistent between chat and file, put methodology caveats beside the numbers they qualify, list data gaps rather than hiding them, and keep subtotal and double-count exclusions explicit (the leakage workbook excludes the CRM/ERP mismatch category from its totals and says so).

## 9. Integrity checks: one set of numbers

Every figure a reader sees (chat, workbook, dashboard, PNG) must be the same figure. The bundle is the single source; these checks stop the copies drifting.

| Check | Command | Catches |
|---|---|---|
| Bundle validation | `python scripts/bundle.py bundle.json` | Unbacked figures in the headline or findings (a `$`, `%`, `x`, `pp`, `k`, `mn`/`mm` or `bn` number with no matching table cell or KPI, within rounding); KPI not equal to its `source` cell; bridges (waterfall charts) that don't add up; percent columns holding whole numbers; capped tables without the true count; local data labelled governed. Prints the **Bundle ID**. |
| Chat answer check | `python scripts/bundle.py bundle.json --check-text work/answer.md` | The answer must contain the bundle headline verbatim, and every `$`, `%`, `x`, `pp` figure in its prose (SQL blocks ignored) must be in the bundle. Plain counts and decimals without a unit are reported as warnings. |
| Output verification | `python scripts/verify_outputs.py bundle.json --xlsx f.xlsx --html f.html --charts dir` | Reads the finished files back: Bundle ID present in each; headline, findings and caveats unchanged; every KPI value and change; every table header, cell and row count; `SUM` total formulas; every HTML table cell exactly as displayed; a chart tooltip for every plotted point; one PNG per chart carrying the Bundle ID. Fails on a stale file, a hand edit or an exporter bug. |
| Workbook recalculation | `python scripts/check_xlsx.py f.xlsx` | Formula errors after recalculation (needs LibreOffice). |

The **Bundle ID** is a hash of the visible content (headline, KPIs, findings, tables, charts, period, currency, scale, mode). It appears on the workbook's Summary sheet and in its file properties, in the HTML footer and `<meta name="bundle-id">`, and in each PNG's metadata. Quote it when handing over the files. If two files show different IDs, they were not built from the same results.

What the checks cannot do: they don't test that the SQL is right, that a figure means what the text says, or that a number sits next to the right label. A figure that exists in the bundle but is attached to the wrong name passes (a local demo once reported two measures swapped, because rows were taken by position; both numbers were in the table). Build rows by looking values up by name, never by position, and read the headline against the table before sending. They guarantee the same numbers in every place, that text figures come from the data, and that bridges and KPIs are internally consistent. Native Excel charts and PNG pixels are not read back (they draw from the table ranges and values the other checks cover).

Phrase derived figures so they can be matched: put "$0.4mn unfavourable" in the headline only if a table or KPI holds 0.4 (or 400,000, or 0.0004bn). A number computed in your head and typed into the prose is exactly what the check rejects.

