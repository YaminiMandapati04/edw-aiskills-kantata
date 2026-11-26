#!/usr/bin/env python3
"""Independent check that the finished files show exactly what the bundle says.

The exporters write from the bundle; this script reads the *files* back and
compares them with the bundle, so a bug in an exporter, a hand edit, or a stale
file from an earlier run is caught before anyone sees it.

Usage:
    python verify_outputs.py bundle.json [--xlsx out.xlsx] [--html out.html] [--charts outdir]

Checks
  Excel  Bundle ID on Summary and in file properties; headline; every KPI value and
         delta; every table's header, every cell, row count, SUM formulas on total rows.
  HTML   Bundle ID (meta tag and footer); headline; KPI tiles; findings; caveats;
         every table cell exactly as displayed; chart tooltips for every plotted point.
  PNG    One file per chart carrying the Bundle ID in its metadata.

Exit 0 = every check passed, 1 = at least one mismatch, 2 = usage error.
Native Excel charts and the pixels of PNGs are not read back; they are drawn from
the table ranges / table values the checks above cover.
"""
import argparse
import datetime as dt
import os
import sys
from collections import Counter
from html.parser import HTMLParser

import bundle as B

TOL = 1e-9


def same_num(a, b):
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


def norm(s):
    return " ".join(str(s).split())


class Report:
    def __init__(self):
        self.fails, self.checked = [], 0

    def check(self, ok, msg):
        self.checked += 1
        if not ok:
            self.fails.append(msg)


# ------------------------------------------------------------------------ xlsx

def verify_xlsx(b, path, rep):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter as L
    fp = B.fingerprint(b)
    wb = load_workbook(path)
    try:
        cached = load_workbook(path, data_only=True)
    except Exception:
        cached = None

    rep.check(f"Bundle ID: {fp}" in (wb.properties.subject or ""), f"xlsx: file properties do not carry Bundle ID {fp}.")
    if "Summary" not in wb.sheetnames:
        rep.check(False, "xlsx: no Summary sheet.")
        return
    ws = wb["Summary"]
    texts = [norm(c.value) for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    rep.check(f"Bundle ID: {fp}" in texts, f"xlsx: Summary does not show Bundle ID {fp} (stale or edited file?).")
    if b.get("headline"):
        rep.check(norm(b["headline"]) in texts, "xlsx: Summary headline differs from the bundle headline.")
    if (b.get("meta") or {}).get("data_mode") == "local":
        rep.check(B.LOCAL_BANNER in texts, "xlsx: local-data banner missing from Summary.")
    for f in b.get("findings") or []:
        rep.check(norm(f["text"]) in texts, f"xlsx: finding missing or altered: {f['text'][:60]!r}")

    rows = {norm(r[0].value): r for r in ws.iter_rows() if r and isinstance(r[0].value, str)}
    for k in b.get("kpis") or []:
        r = rows.get(norm(k["label"]))
        if r is None:
            rep.check(False, f"xlsx: KPI '{k['label']}' not on Summary.")
            continue
        v = r[1].value
        rep.check(isinstance(v, (int, float)) and same_num(v, k["value"]),
                  f"xlsx: KPI '{k['label']}' shows {v!r}, bundle says {k['value']!r}.")
        if k.get("delta") is not None:
            d = r[2].value
            rep.check(isinstance(d, (int, float)) and same_num(d, k["delta"]),
                      f"xlsx: KPI '{k['label']}' change shows {d!r}, bundle says {k['delta']!r}.")

    by_title = {}
    for s in wb.worksheets:
        a1 = s.cell(1, 1).value
        if isinstance(a1, str):
            by_title.setdefault(a1, s)
    for t in b.get("tables") or []:
        s = by_title.get(t["title"])
        if s is None:
            rep.check(False, f"xlsx: no sheet for table '{t['title']}'.")
            continue
        cols = t["columns"]
        for ci, c in enumerate(cols, start=1):
            rep.check(s.cell(4, ci).value == c["name"], f"xlsx[{t['id']}]: header {ci} is {s.cell(4, ci).value!r}, expected {c['name']!r}.")
        first = 5
        for ri, row in enumerate(t["rows"]):
            for ci, (c, v) in enumerate(zip(cols, row), start=1):
                got = s.cell(first + ri, ci).value
                ctype = c.get("type", "text")
                if v is None:
                    ok = got is None
                elif ctype in B.NUMERIC_TYPES:
                    ok = isinstance(got, (int, float)) and same_num(got, v)
                elif ctype == "date":
                    gd = got.date() if isinstance(got, dt.datetime) else got
                    ok = (gd.isoformat() if isinstance(gd, dt.date) else str(gd)) == str(v)[:10]
                else:
                    ok = got == v
                rep.check(ok, f"xlsx[{t['id']}] row {ri + 1}, '{c['name']}': file has {got!r}, bundle has {v!r}.")
        after = s.cell(first + len(t["rows"]), 1).value
        rep.check(after in (None, "Total"), f"xlsx[{t['id']}]: more rows in the sheet than in the bundle ({len(t['rows'])}).")
        if any(c.get("total") for c in cols) and t["rows"]:
            tr = first + len(t["rows"])
            for ci, c in enumerate(cols, start=1):
                if c.get("total") == "sum" and ci > 1:
                    want = f"=SUM({L(ci)}{first}:{L(ci)}{tr - 1})"
                    rep.check(s.cell(tr, ci).value == want, f"xlsx[{t['id']}]: total for '{c['name']}' is {s.cell(tr, ci).value!r}, expected {want}.")
                    if cached is not None:
                        cv = cached[s.title].cell(tr, ci).value
                        if isinstance(cv, (int, float)):
                            exp = sum(r[ci - 1] for r in t["rows"] if isinstance(r[ci - 1], (int, float)))
                            rep.check(same_num(cv, exp), f"xlsx[{t['id']}]: cached total for '{c['name']}' is {cv}, expected {exp}.")


# ------------------------------------------------------------------------ html

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.text, self.tables, self.titles = {}, [], [], []
        self._row = self._cell = None
        self._skip = 0
        self._svg = 0
        self._title = None
        self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content")
        elif tag == "svg":
            self._svg += 1
        elif tag == "title" and self._svg:
            self._title = []
        elif tag == "table":
            self._cur = []
            self.tables.append(self._cur)
        elif tag == "tr" and self._cur is not None:
            self._row = []
            self._cur.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip -= 1
        elif tag == "svg":
            self._svg -= 1
        elif tag == "title" and self._title is not None:
            self.titles.append(norm("".join(self._title)))
            self._title = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(norm("".join(self._cell)))
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._cur = None

    def handle_data(self, d):
        if self._skip:
            return
        if self._title is not None:
            self._title.append(d)
        if self._cell is not None:
            self._cell.append(d)
        self.text.append(d)


def verify_html(b, path, rep):
    fp = B.fingerprint(b)
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    p = Page()
    p.feed(raw)
    full = norm(" ".join(p.text))
    rep.check(p.meta.get("bundle-id") == fp, f"html: bundle-id meta is {p.meta.get('bundle-id')!r}, expected {fp} (stale or edited file?).")
    rep.check(f"Bundle ID: {fp}" in full, f"html: footer does not show Bundle ID {fp}.")
    if b.get("headline"):
        rep.check(norm(b["headline"]) in full, "html: headline differs from the bundle headline.")
    if (b.get("meta") or {}).get("data_mode") == "local":
        rep.check(B.LOCAL_BANNER in full, "html: local-data banner missing.")
    for f in b.get("findings") or []:
        rep.check(norm(f["text"]) in full, f"html: finding missing or altered: {f['text'][:60]!r}")
    for c in b.get("caveats") or []:
        rep.check(norm(c) in full, f"html: caveat missing or altered: {c[:60]!r}")
    for k in b.get("kpis") or []:
        fmtk = k.get("format", "number")
        rep.check(norm(B.fmt(k["value"], fmtk)) in full and norm(k["label"]) in full,
                  f"html: KPI '{k['label']}' not shown as {B.fmt(k['value'], fmtk)}.")
        if k.get("delta") is not None:
            d = k["delta"]
            txt = f"{'+' if d > 0 else ''}{B.fmt(d, k.get('delta_format', fmtk))}"
            rep.check(norm(txt) in full, f"html: KPI '{k['label']}' change not shown as {txt}.")

    # tables: displayed text must equal the formatted bundle value, cell for cell
    shown = [t for t in p.tables if t]
    rep.check(len(shown) == len(b.get("tables") or []), f"html: {len(shown)} tables on the page, bundle has {len(b.get('tables') or [])}.")
    for t, ht in zip(b.get("tables") or [], shown):
        cols = t["columns"]
        rep.check(ht[0] == [c["name"] for c in cols], f"html[{t['id']}]: header row differs from the bundle.")
        body = [r for r in ht[1:] if not (r and r[0] == "Total" and any(c.get("total") for c in cols))]
        n_rows = len(t["rows"])
        rep.check(len(body) == n_rows, f"html[{t['id']}]: {len(body)} rows shown, bundle has {n_rows}.")
        for ri, (row, hrow) in enumerate(zip(t["rows"], body)):
            for ci, (c, v) in enumerate(zip(cols, row)):
                want = norm(B.fmt(v, c.get("type", "text")))
                got = hrow[ci] if ci < len(hrow) else None
                rep.check(got == want, f"html[{t['id']}] row {ri + 1}, '{c['name']}': page shows {got!r}, bundle gives {want!r}.")

    # chart tooltips: one per plotted point
    seen = Counter(p.titles)
    want = Counter()
    for ch in b.get("charts") or []:
        t = B.table_by_id(b, ch["table"])
        xs = [str(v) for v in B.col_values(t, ch["x"])]
        ys = ch["y"]
        ctype = B.col_type(t, ys[0])
        for y in ys:
            for x, v in zip(xs, B.col_values(t, y)):
                if v is None:
                    continue
                tip = f"{x}: {B.fmt(v, ctype)}"
                want[norm(f"{tip} ({y})" if len(ys) > 1 and ch["type"] != "waterfall" else tip)] += 1
    for tip, n in want.items():
        rep.check(seen[tip] >= n, f"html: chart tooltip missing: {tip!r}.")


# ------------------------------------------------------------------------- png

def verify_charts(b, outdir, rep):
    fp = B.fingerprint(b)
    for ch in b.get("charts") or []:
        path = os.path.join(outdir, f"{ch['id']}.png")
        if not os.path.exists(path):
            rep.check(False, f"charts: {path} not found.")
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        rep.check(f"Bundle ID: {fp}".encode() in data, f"charts: {ch['id']}.png does not carry Bundle ID {fp} (stale file?).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle")
    ap.add_argument("--xlsx")
    ap.add_argument("--html")
    ap.add_argument("--charts")
    a = ap.parse_args()
    if not (a.xlsx or a.html or a.charts):
        ap.error("give at least one of --xlsx, --html, --charts")
    b = B.load(a.bundle)
    errs = B.validate(b)
    if errs:
        print("Bundle problems:")
        for e in errs:
            print(" -", e)
        return 1
    rep = Report()
    if a.xlsx:
        verify_xlsx(b, a.xlsx, rep)
    if a.html:
        verify_html(b, a.html, rep)
    if a.charts:
        verify_charts(b, a.charts, rep)
    if rep.fails:
        print(f"MISMATCH: {len(rep.fails)} of {rep.checked} checks failed (Bundle ID {B.fingerprint(b)})")
        for f in rep.fails[:40]:
            print(" -", f)
        if len(rep.fails) > 40:
            print(f" ... and {len(rep.fails) - 40} more")
        return 1
    print(f"VERIFIED: {rep.checked} checks passed. Files match bundle {B.fingerprint(b)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
