#!/usr/bin/env python3
"""Export a result bundle to a branded Excel workbook.

Usage:  python export_xlsx.py bundle.json out.xlsx

Sheets: Summary, one sheet per table (with native charts), Definitions,
"SQL & lineage". Total rows are SUM formulas; waterfall charts are driven by
a formula-based helper block so they stay live. After building, run
check_xlsx.py and confirm zero errors.

Brand: Accordion (Gray 7 headers, Gray 1/white banding, Gray 2 totals, Citron
accent, alert red for negatives). Font: Calibri (documented brand fallback —
Messina Sans cannot be embedded in .xlsx).
"""
import datetime as dt
import re
import sys

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

import bundle as B

FONT = "Calibri"
MONO = "Courier New"


def fill(hex_):
    return PatternFill("solid", start_color=hex_, end_color=hex_)


F_BODY = Font(name=FONT, size=10, color=B.GRAY5)
F_BOLD = Font(name=FONT, size=10, bold=True, color=B.NAVY)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=16, bold=True, color=B.NAVY)
F_SUB = Font(name=FONT, size=11, bold=True, color=B.NAVY)
F_SMALL = Font(name=FONT, size=9, color=B.GRAY4)
F_MONO = Font(name=MONO, size=9, color=B.NAVY)
THIN = Side(style="thin", color=B.GRAY3)
HAIR = Border(bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
RED_RULE = lambda: CellIsRule(operator="lessThan", formula=["0"], font=Font(name=FONT, color=B.ALERT))


def safe_sheet_name(title, used):
    name = re.sub(r"[\[\]\*\?/\\:]", "-", title).strip() or "Table"
    name = name[:31]
    base, i = name, 2
    while name.lower() in used:
        suffix = f" ({i})"
        name = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


def to_cell(value, ctype):
    if value is None:
        return None
    if ctype == "date" and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value


def write_summary(ws, b):
    meta = b.get("meta", {})
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 70

    r = 1
    ws.cell(r, 1, meta.get("title", "Analysis")).font = F_TITLE
    r += 1
    if meta.get("question"):
        ws.cell(r, 1, f"Question: {meta['question']}").font = F_BODY
        r += 1
    line = " · ".join(x for x in [meta.get("period"), meta.get("currency"), meta.get("scale"),
                                  f"As of {meta['as_of']}" if meta.get("as_of") else None] if x)
    if line:
        ws.cell(r, 1, line).font = F_SMALL
        r += 1
    ws.cell(r, 1, f"Bundle ID: {B.fingerprint(b)}").font = F_SMALL
    r += 1
    if meta.get("data_mode") == "local":
        c = ws.cell(r, 1, B.LOCAL_BANNER)
        c.font = Font(name=FONT, size=10, bold=True, color=B.ALMOND)
        r += 1
    r += 1

    if b.get("headline"):
        ws.cell(r, 1, "Headline").font = F_SUB
        r += 1
        c = ws.cell(r, 1, b["headline"])
        c.font = F_BODY
        c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        ws.row_dimensions[r].height = max(30, 15 * (len(b["headline"]) // 110 + 1))
        r += 2

    kpis = b.get("kpis") or []
    if kpis:
        ws.cell(r, 1, "Key figures").font = F_SUB
        r += 1
        for ci, h in enumerate(["Measure", "Value", "Change", "Note"], start=1):
            c = ws.cell(r, ci, h)
            c.font, c.fill = F_HEAD, fill(B.NAVY)
        r += 1
        for i, k in enumerate(kpis):
            ws.cell(r, 1, k["label"]).font = F_BOLD
            v = ws.cell(r, 2, k["value"])
            v.number_format = B.excel_numfmt(k.get("format", "number"))
            v.font = F_BODY
            if k.get("delta") is not None:
                d = ws.cell(r, 3, k["delta"])
                d.number_format = B.excel_numfmt(k.get("delta_format", k.get("format", "number")))
                d.font = F_BODY
            ws.cell(r, 4, k.get("note", "")).font = F_BODY
            for ci in range(1, 5):
                ws.cell(r, ci).fill = fill(B.GRAY1 if i % 2 == 0 else "FFFFFF")
                ws.cell(r, ci).alignment = Alignment(horizontal="left")
            r += 1
        ws.conditional_formatting.add(f"B{r - len(kpis)}:C{r - 1}", RED_RULE())
        r += 1

    findings = b.get("findings") or []
    if findings:
        ws.cell(r, 1, "Findings").font = F_SUB
        r += 1
        for ci, h in enumerate(["Evidence", "Cause tag", "", "Finding"], start=1):
            c = ws.cell(r, ci, h)
            c.font, c.fill = F_HEAD, fill(B.NAVY)
        r += 1
        for i, f in enumerate(findings):
            ev = f.get("evidence", "established")
            c = ws.cell(r, 1, ev.capitalize())
            c.font = Font(name=FONT, size=10, bold=True, color=B.NAVY if ev == "established" else B.ALMOND)
            c.alignment = WRAP
            tg = ws.cell(r, 2, f.get("tag", ""))
            tg.font, tg.alignment = F_BODY, WRAP
            t = ws.cell(r, 4, f["text"])
            t.font, t.alignment = F_BODY, WRAP
            ws.row_dimensions[r].height = max(15, 15 * (len(f["text"]) // 75 + 1))
            for ci in range(1, 5):
                ws.cell(r, ci).fill = fill(B.GRAY1 if i % 2 == 0 else "FFFFFF")
            r += 1
        r += 1

    for title, items in (("Caveats", b.get("caveats")), ("Sources", meta.get("sources"))):
        if items:
            ws.cell(r, 1, title).font = F_SUB
            r += 1
            for it in items:
                c = ws.cell(r, 1, f"• {it}")
                c.font, c.alignment = F_BODY, WRAP
                ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
                ws.row_dimensions[r].height = max(15, 15 * (len(it) // 120 + 1))
                r += 1
            r += 1

    foot = ("Built from an uploaded local workbook for testing; not governed semantic-view results. "
            if meta.get("data_mode") == "local" else "Built from governed semantic-view results. ")
    ws.cell(r, 1, foot + "Tables are labelled Governed, Derived or Scenario; scenario figures depend on "
                         "stated assumptions and are not actuals.").font = F_SMALL
    ws.sheet_properties.tabColor = B.CITRON


def write_table_sheet(wb, b, t, name):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    cols = t["columns"]
    n = len(cols)

    ws.cell(1, 1, t["title"]).font = F_TITLE
    prov = t.get("provenance", "governed")
    c = ws.cell(2, 1, f"{B.provenance_label(prov)} · {b.get('meta', {}).get('scale', '')}".strip(" ·"))
    c.font = Font(name=FONT, size=9, bold=True, color=B.ALMOND if prov == "scenario" else B.GRAY4)

    hdr = 4
    for ci, col in enumerate(cols, start=1):
        h = ws.cell(hdr, ci, col["name"])
        h.font, h.fill = F_HEAD, fill(B.NAVY)
        numeric = col.get("type", "text") in B.NUMERIC_TYPES
        h.alignment = Alignment(horizontal="right" if numeric else "left", vertical="center", wrap_text=True)
    ws.row_dimensions[hdr].height = 30

    first = hdr + 1
    for ri, row in enumerate(t["rows"]):
        r = first + ri
        for ci, (col, v) in enumerate(zip(cols, row), start=1):
            ctype = col.get("type", "text")
            cell = ws.cell(r, ci, to_cell(v, ctype))
            cell.font = F_BODY
            cell.number_format = B.excel_numfmt(ctype)
            cell.fill = fill(B.GRAY1 if ri % 2 == 0 else "FFFFFF")
            cell.alignment = Alignment(horizontal="left" if ctype in ("text", "date") else "right")
    last = first + len(t["rows"]) - 1 if t["rows"] else first

    # total row — SUM formulas on additive columns flagged total: "sum"
    end = last
    if any(c.get("total") for c in cols) and t["rows"]:
        tr = last + 1
        ws.cell(tr, 1, "Total").font = F_BOLD
        for ci, col in enumerate(cols, start=1):
            cell = ws.cell(tr, ci)
            cell.fill = fill(B.GRAY2)
            if col.get("total") == "sum" and ci > 1:
                cell.value = f"=SUM({L(ci)}{first}:{L(ci)}{last})"
                cell.number_format = B.excel_numfmt(col.get("type", "number"))
                cell.font = F_BOLD
                cell.alignment = Alignment(horizontal="right")
            elif ci == 1:
                cell.font = F_BOLD
        end = tr

    # negatives in alert red
    for ci, col in enumerate(cols, start=1):
        if col.get("type") in B.NUMERIC_TYPES and t["rows"]:
            ws.conditional_formatting.add(f"{L(ci)}{first}:{L(ci)}{end}", RED_RULE())

    ws.freeze_panes = ws.cell(first, 1)
    if t["rows"]:
        ws.auto_filter.ref = f"A{hdr}:{L(n)}{last}"

    for ci, col in enumerate(cols, start=1):
        longest = max([len(str(col["name"]))] +
                      [len(B.fmt(r[ci - 1], col.get("type", "text"))) for r in t["rows"]] or [10])
        ws.column_dimensions[L(ci)].width = min(48, max(13, longest + 3))

    notes_row = end + 2
    if t.get("capped"):
        ws.cell(notes_row, 1, f"Showing {len(t['rows'])} of {t.get('row_count_total', '?')} rows (capped).").font = F_SMALL
        notes_row += 1

    ws.sheet_properties.tabColor = B.ALMOND if prov == "scenario" else B.GRAY4
    return ws, hdr, first, last, notes_row + 1


def style_series(s, color, kind):
    if kind == "line":
        s.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.width = 22000
        s.smooth = False
        s.marker.symbol = "circle"
        s.marker.size = 5
        s.marker.graphicalProperties.solidFill = color
        s.marker.graphicalProperties.line.solidFill = color
    else:
        s.graphicalProperties.solidFill = color
        s.graphicalProperties.line.noFill = True


def add_chart(ws, b, t, ch, hdr, first, last, anchor_col, anchor_row, helper_row):
    cols = [c["name"] for c in t["columns"]]
    xi = cols.index(ch["x"]) + 1
    kind = ch["type"]
    title = ch["title"]
    prov = ch.get("provenance", "governed")
    if prov != "governed":
        title += f" ({B.provenance_label(prov).split(' –')[0].lower()})"

    cats = Reference(ws, min_col=xi, min_row=first, max_row=last)

    if kind == "waterfall":
        # formula-driven helper block under the table; stacked columns with an invisible base
        yi = cols.index(ch["y"][0]) + 1
        totals = set(ch.get("totals") or [])
        # The stacked-column technique cannot draw below zero. If the running total ever goes
        # negative, skip the native chart (the HTML dashboard and PNG draw it correctly) and say so.
        run, negative = 0.0, False
        for k, row in enumerate(t["rows"]):
            v = row[yi - 1] or 0
            run = v if (str(row[xi - 1]) in totals or k == 0) else run + v
            negative = negative or run < -1e-9
        if negative:
            note = ws.cell(anchor_row, anchor_col, "Waterfall chart not drawn in Excel: the running total goes "
                                                   "below zero. See the HTML dashboard or PNG chart.")
            note.font = F_SMALL
            return helper_row
        h0 = helper_row
        ws.cell(h0, 1, "Waterfall chart helper (formulas)").font = F_SMALL
        heads = ["Step", "Running end", "Base", "Total", "Increase", "Decrease"]
        for i, h in enumerate(heads, start=1):
            c = ws.cell(h0 + 1, i, h)
            c.font, c.fill = F_HEAD, fill(B.GRAY6)
        n = last - first + 1
        for k in range(n):
            r = h0 + 2 + k
            src = first + k
            val = f"{L(yi)}{src}"
            is_total = str(ws.cell(src, xi).value) in totals
            ws.cell(r, 1, f"={L(xi)}{src}")
            if is_total or k == 0:
                ws.cell(r, 2, f"={val}")
                ws.cell(r, 3, 0)
                ws.cell(r, 4, f"={val}")
                ws.cell(r, 5, 0)
                ws.cell(r, 6, 0)
            else:
                ws.cell(r, 2, f"=B{r - 1}+{val}")
                ws.cell(r, 3, f"=MIN(B{r - 1},B{r})")
                ws.cell(r, 4, 0)
                ws.cell(r, 5, f"=MAX({val},0)")
                ws.cell(r, 6, f"=MAX(-{val},0)")
            for ci in range(1, 7):
                ws.cell(r, ci).font = F_SMALL
                if ci > 1:
                    ws.cell(r, ci).number_format = B.excel_numfmt("number")
        chart = BarChart()
        chart.type = "col"
        chart.grouping = "stacked"
        chart.overlap = 100
        data = Reference(ws, min_col=3, max_col=6, min_row=h0 + 1, max_row=h0 + 1 + n)
        wcats = Reference(ws, min_col=1, min_row=h0 + 2, max_row=h0 + 1 + n)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(wcats)
        base, tot, inc, dec = chart.series
        base.graphicalProperties.noFill = True
        base.graphicalProperties.line.noFill = True
        for s, col in ((tot, B.NAVY), (inc, B.MINT), (dec, B.ALMOND)):
            style_series(s, col, "bar")
        chart.legend = None
        chart.gapWidth = 60
    else:
        if kind == "line":
            chart = LineChart()
            palette = B.LINE_PALETTE
        else:
            chart = BarChart()
            chart.type = "bar" if kind == "bar" else "col"
            chart.grouping = "clustered"
            chart.gapWidth = 80
            palette = B.BAR_PALETTE
        for i, yname in enumerate(ch["y"]):
            yi = cols.index(yname) + 1
            ref = Reference(ws, min_col=yi, min_row=hdr, max_row=last)
            chart.add_data(ref, titles_from_data=True)
        chart.set_categories(cats)
        for i, s in enumerate(chart.series):
            style_series(s, palette[i % len(palette)], "line" if kind == "line" else "bar")
        if len(ch["y"]) == 1:
            chart.legend = None
        else:
            chart.legend.position = "b"
        if kind == "bar":
            chart.y_axis.scaling.orientation = "minMax"
            chart.x_axis.scaling.orientation = "maxMin"   # first row on top
            chart.y_axis.crosses = "max"                  # keep value axis at the bottom after the flip

    chart.title = title
    chart.height, chart.width = 8.5, 17
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.x_axis.tickLblPos = "low"          # keep category labels at the bottom when values go negative
    chart.y_axis.majorGridlines.spPr = None
    ws.add_chart(chart, f"{L(anchor_col)}{anchor_row}")
    return (helper_row + 2 + (last - first + 1) + 1) if kind == "waterfall" else helper_row


def write_definitions(wb, b):
    defs = b.get("definitions") or []
    if not defs:
        return
    ws = wb.create_sheet("Definitions")
    ws.sheet_view.showGridLines = False
    ws.cell(1, 1, "Metric definitions").font = F_TITLE
    ws.cell(2, 1, "As stated by the semantic view. Governed metrics are not re-derived.").font = F_SMALL
    for ci, h in enumerate(["Metric", "View", "Definition"], start=1):
        c = ws.cell(4, ci, h)
        c.font, c.fill = F_HEAD, fill(B.NAVY)
    for i, d in enumerate(defs):
        r = 5 + i
        ws.cell(r, 1, d.get("metric", "")).font = F_BOLD
        ws.cell(r, 2, d.get("view", "")).font = F_BODY
        c = ws.cell(r, 3, d.get("definition", ""))
        c.font, c.alignment = F_BODY, WRAP
        ws.row_dimensions[r].height = max(15, 15 * (len(d.get("definition", "")) // 80 + 1))
        for ci in range(1, 4):
            ws.cell(r, ci).fill = fill(B.GRAY1 if i % 2 == 0 else "FFFFFF")
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 90
    ws.sheet_properties.tabColor = B.GRAY3


def write_lineage(wb, b, sheet_names):
    ws = wb.create_sheet("SQL & lineage")
    ws.sheet_view.showGridLines = False
    ws.cell(1, 1, "SQL and lineage").font = F_TITLE
    ws.cell(2, 1, "The statement behind each table, so any number can be reproduced.").font = F_SMALL
    heads = ["Table", "Sheet", "Provenance", "Rows shown", "Rows total", "Capped", "SQL / derivation"]
    for ci, h in enumerate(heads, start=1):
        c = ws.cell(4, ci, h)
        c.font, c.fill = F_HEAD, fill(B.NAVY)
    for i, t in enumerate(b.get("tables", [])):
        r = 5 + i
        vals = [t["title"], sheet_names.get(t["id"], ""), B.provenance_label(t.get("provenance", "governed")),
                len(t.get("rows", [])), t.get("row_count_total", len(t.get("rows", []))),
                "Yes" if t.get("capped") else "No", t.get("sql", "")]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(r, ci, v)
            c.font = F_MONO if ci == 7 else F_BODY
            c.alignment = WRAP
            c.fill = fill(B.GRAY1 if i % 2 == 0 else "FFFFFF")
        ws.row_dimensions[r].height = max(30, 13 * (len(t.get("sql", "")) // 85 + 1))
    for col, w in zip("ABCDEFG", (34, 22, 26, 12, 12, 9, 95)):
        ws.column_dimensions[col].width = w
    ws.sheet_properties.tabColor = B.GRAY3


def main():
    if len(sys.argv) != 3:
        print("usage: export_xlsx.py bundle.json out.xlsx", file=sys.stderr)
        return 2
    b = B.load(sys.argv[1])
    errs = B.validate(b)
    if errs:
        print("Bundle problems — fix before exporting:")
        for e in errs:
            print(" -", e)
        return 1

    wb = Workbook()
    wb.remove(wb.active)
    summary = wb.create_sheet("Summary")
    write_summary(summary, b)

    used = {"summary", "definitions", "sql & lineage"}
    names = {}
    for t in b.get("tables", []):
        name = safe_sheet_name(t["title"], used)
        names[t["id"]] = name
        ws, hdr, first, last, free_row = write_table_sheet(wb, b, t, name)
        ncols = len(t["columns"])
        if any(c["type"] == "waterfall" and c["table"] == t["id"] for c in b.get("charts", [])):
            ncols = max(ncols, 6)             # keep charts clear of the helper block
        # charts that reference this table: stack them to the right of the table
        anchor_row = hdr
        helper_row = free_row
        for ch in b.get("charts", []):
            if ch["table"] != t["id"] or not t["rows"]:
                continue
            helper_row = add_chart(ws, b, t, ch, hdr, first, last, ncols + 2, anchor_row, helper_row)
            anchor_row += 19

    write_definitions(wb, b)
    write_lineage(wb, b, names)

    from openpyxl.worksheet.properties import PageSetupProperties
    for ws in wb.worksheets:                      # print-friendly: landscape, fit to one page wide
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

    wb.properties.title = b["meta"]["title"]
    wb.properties.subject = f"Bundle ID: {B.fingerprint(b)}"
    wb.properties.creator = "Semantic data analyst"
    wb.save(sys.argv[2])
    print(f"Wrote {sys.argv[2]}  ({len(wb.sheetnames)} sheets: {', '.join(wb.sheetnames)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
