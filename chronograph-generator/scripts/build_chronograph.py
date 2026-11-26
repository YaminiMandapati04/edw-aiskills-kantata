#!/usr/bin/env python3
"""Build the Accel-KKR CFO Chronograph workbook from the three governed semantic views.

    python build_chronograph.py [--work work/] [--out outputs/] [--excel auto|on|off]

Reads <work>/queries/manifest.json (written by chronograph_queries.py) and the ten saved sql-exec results in
<work>/raw/, fills the template's Actual sheet with one column per month of the window, and writes
<out>/yes_energy_chronograph_<YYYY-MM>.xlsx, named for the as-of month (yes_energy_chronograph_<YYYY-MM>_SYNTHETIC.xlsx
for test data; a rerun for the same month rewrites that file) plus <work>/chronograph_report.json.

Deterministic, and fail-closed:
- Every labelled template row must be in assets/chronograph_map.json and every map row in the template; the template
  must match the map's SHA-256. Every source must cover every month of the window.
- P&L (FINANCE_ANALYTICS): signed with the view's P_AND_L_MULTIPLIER (revenue positive, costs negative). A row reads
  the deepest COA level whose name matches (L6, L5, L4, L3, L2); a group's Other row is the line total less the rows
  named. Every view line with activity must land in a row. Balance sheet and cash flow read the view as stored. ARR
  and customer bridges (ARR_ANALYTICS) and bookings and pipeline (GTM_ANALYTICS) read the governed metrics. Rows no
  view carries (headcount, revolver, payments) are left blank, never 0.
- The template enters costs and outflows as positive amounts and subtracts them in its formulas. Rows marked
  'negate' in the map (P&L costs, working-capital change, investing outflows, churn, downsell, lost customers) are
  written with the view's sign reversed; every calculation and gate inside the build uses the view's own sign.
- Template formulas stay formulas, copied to every month; three template formula errors are corrected (map 'override').
- Gates (the sheet's own formulas are evaluated as Excel will): Total Revenue, Adjusted EBITDA and Net Income tie to the
  governed roll-ups; the balance sheet balances (A = L + E is 0); cash ties to the cash flow's ending cash; Net Cash Flow, Cash before
  Financing, Beginning and Ending Cash tie; the ARR bridge's GDR, NDR (+ FX) and Ending ARR tie to the view; Ending Customers
  ties; Recurring and Total Bookings tie. Tolerance $1 (0 for counts). Any failure refuses the file.
- The workbook is sanitised (no defined names, external links or stale views) and checked with check_workbook.py,
  including a hidden-Excel open test on Windows; a file Excel would repair is refused.
Exit codes: 0 written, 1 refused.
"""
import argparse
import calendar
import statistics
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import check_workbook                                   # noqa: E402
import fetch_template                                   # noqa: E402
from clean_template import sanitize, sha256             # noqa: E402

TEMPLATE = os.path.join(SKILL, "assets", "chronograph_template.xlsx")
MAP = os.path.join(SKILL, "assets", "chronograph_map.json")
BS_SECTIONS = ("assets", "total liabilities share holder equity")
CF_LABELS = ("beginning cash", "ending cash", "net cash flow", "cash before financing")
TEXT_SECTIONS = {"pl": "P&L", "bs": "balance sheet", "cf": "cash flow"}


class Refused(Exception):
    def __init__(self, msg, **extra):
        super().__init__(msg)
        self.extra = extra


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def num(v):
    if v is None or v == "":
        return None
    return float(v)


def r2(v):
    return None if v is None else round(v + 0.0, 2)


def col_letter(idx):
    from openpyxl.utils import get_column_letter
    return get_column_letter(idx)


def month_label(d):
    return str(d)[:7]


def is_month_end(d):
    s = str(d)[:10]
    y, m, day = int(s[:4]), int(s[5:7]), int(s[8:10])
    return day == calendar.monthrange(y, m)[1]


# ---------------------------------------------------------------- inputs

def load_result(path, expected):
    """A saved sql-exec result: refuses a missing file, a truncated result or unexpected columns."""
    if not os.path.exists(path):
        raise Refused(f"{path} is missing: run the matching query in work/queries and save its full result there")
    raw = open(path, encoding="utf-8").read()
    start = raw.find("{")
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        rs = obj["result_set"]
        meta = rs["resultSetMetaData"]
        data = rs["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused(f"{path} is not a saved sql-exec result ({exc})")
    cols = [c["name"] for c in meta["rowType"]]
    declared = meta.get("numRows")
    if declared is not None and declared != len(data):
        raise Refused(f"{path}: the result declares {declared} rows but holds {len(data)}: it was cut off; re-run and save the whole result")
    parts = meta.get("partitionInfo") or []
    if len(parts) > 1 and sum(p.get("rowCount", 0) for p in parts) != len(data):
        raise Refused(f"{path}: the result has {len(parts)} partitions and not all rows are present")
    if sorted(cols) != sorted(expected):
        raise Refused(f"{path}: columns {cols} do not match the query's {expected}; save the result of the query in work/queries unchanged")
    if any(len(r) != len(cols) for r in data):
        raise Refused(f"{path}: rows with the wrong field count")
    return [dict(zip(cols, r)) for r in data], obj.get("query_id")


class Lines:
    """Line-level monthly amounts with a name index per hierarchy level (deepest level wins on lookup)."""

    def __init__(self, kind, rows, level_cols, value_col, date_col, months, sign=None):
        """sign(row) -> multiplier applied to the row's value (the P&L's per-account P_AND_L_MULTIPLIER)."""
        self.kind, self.months = kind, months
        self.base = 2 if kind == "pl" else 1                  # the COA / cash-flow level number of the first level column
        self.items, idx, self.index = [], {}, {}
        for r in rows:
            m = month_label(r[date_col])
            if m not in months:
                continue
            levels = tuple((r[c] or "").strip() for c in level_cols)
            v = num(r[value_col])
            if v is not None and sign:
                v *= sign(r)
            k = idx.setdefault(levels, len(self.items))
            if k == len(self.items):
                self.items.append({"levels": levels, "values": {}})
            cur = self.items[k]["values"].get(m)
            self.items[k]["values"][m] = v if cur is None else (cur if v is None else cur + v)
        for i, it in enumerate(self.items):
            for depth, name in enumerate(it["levels"]):
                if name:
                    self.index.setdefault((depth, norm(name)), []).append(i)
        self.used = set()
        self.present = {m for it in self.items for m, v in it["values"].items()}

    def lookup(self, name, level=None):
        """(depth, item ids) for a line name: at the given level (L-number) or the deepest level it exists at.
        A list of names takes every line that matches any of them (all at one level)."""
        names = name if isinstance(name, (list, tuple)) else [name]
        depths = [level - self.base] if level else range(len(self.items[0]["levels"]) - 1 if self.items else -1, -1, -1)
        for depth in depths:
            ids = [i for n in names for i in self.index.get((depth, norm(n)), [])]
            if ids:
                return depth, ids
        return None

    def series(self, ids):
        out = {}
        for m in self.months:
            vals = [self.items[i]["values"].get(m) for i in ids]
            vals = [v for v in vals if v is not None]
            out[m] = sum(vals) if vals else None
        return out

    def take(self, name, level=None):
        hit = self.lookup(name, level)
        if not hit:
            return None, None
        depth, ids = hit
        self.used.update(ids)
        shown = " + ".join(sorted({self.items[i]['levels'][depth] for i in ids}))
        return self.series(ids), f"{shown} (L{depth + self.base}, {len(ids)} line(s))"

    def uncovered(self):
        out = set()
        for i, it in enumerate(self.items):
            if i in self.used:
                continue
            if any(v is not None and abs(v) >= 0.005 for v in it["values"].values()):
                out.add(" > ".join(x for x in it["levels"] if x))
        return sorted(out)


def keyed(rows, date_col, months, month_end_only=False, key_col=None, value_cols=None):
    """{month: {key or column: value}} from metric rows; refuses duplicate months."""
    out, seen = {}, set()
    for r in rows:
        if month_end_only and not is_month_end(r[date_col]):
            continue
        m = month_label(r[date_col])
        if m not in months:
            continue
        if key_col:
            k = (m, r[key_col])
            if k in seen:
                raise Refused(f"duplicate {key_col} {r[key_col]!r} for {m}")
            seen.add(k)
            out.setdefault(m, {})[r[key_col]] = {c: num(r[c]) for c in value_cols}
        else:
            if m in out:
                raise Refused(f"two rows for {m} in a monthly result")
            out[m] = {c: num(r[c]) for c in value_cols}
    return out


def require_months(name, have, months):
    missing = [m for m in months if m not in have]
    if missing:
        raise Refused(f"{name}: no data for {', '.join(missing[:6])}{' ...' if len(missing) > 6 else ''}; the window needs every month (choose a later --as-of or fewer --months, or check the view)")


def pl_sign(r):
    """The view stores P&L values unsigned; P_AND_L_MULTIPLIER (+1 revenue and income, -1 costs) gives each account its sign."""
    m = num(r.get("P_AND_L_MULTIPLIER"))
    if m is None:
        if num(r.get("TOTAL_MTD")) in (None, 0.0):
            return 1.0
        raise Refused(f"a P&L line has no P_AND_L_MULTIPLIER, so the sign of its values is unknown: "
                      f"{' > '.join(str(r.get(c) or '') for c in ('COA_MAPPING_L2', 'COA_MAPPING_L3', 'COA_MAPPING_L4', 'COA_MAPPING_L5', 'COA_MAPPING_L6'))}")
    return m


def relabel_cash_flow(rows, rules, months):
    """Give the cash-flow rows the view leaves without a cash-flow label the label the map's cf_unlabelled rules assign
    (matched on their COA levels). An unlabelled row with activity that no rule matches is refused: nothing is dropped."""
    out, unknown, used = [], set(), {}
    for r in rows:
        if norm(r.get("CASH_FLOW_L1")) or month_label(r["PERIOD_START_DATE"]) not in months:
            out.append(r)
            continue
        v = num(r.get("TOTAL_MTD"))
        rule = next((u for u in rules if all(norm(r.get(k)) == norm(w) for k, w in u["when"].items())), None)
        if rule is None:
            if v not in (None, 0.0):
                unknown.add(f"{r.get('COA_MAPPING_L1') or '(no COA L1)'} > {r.get('COA_MAPPING_L3') or '(no COA L3)'}")
            continue
        q = dict(r)
        q["CASH_FLOW_L1"], q["CASH_FLOW_L2"], q["CASH_FLOW_L3"] = rule["as"]
        out.append(q)
        if v not in (None, 0.0):
            u = used.setdefault(rule["as"][-1], {"placed_in": rule["as"][-1], "why": rule.get("why"), "months": {}})
            u["months"][month_label(r["PERIOD_START_DATE"])] = r2((u["months"].get(month_label(r["PERIOD_START_DATE"])) or 0.0) + v)
    if unknown:
        raise Refused("cash-flow rows without a cash-flow label carry activity and no cf_unlabelled rule in the map places them",
                      unlabelled=sorted(unknown))
    return out, list(used.values())


def closed_check(gov, pl, months):
    """Refuse an as-of month that has not closed: its governed revenue is under half the median of the three months
    before it, or under half as many P&L lines post as in the busiest earlier month of the window."""
    posted = {m: sum(1 for it in pl.items if abs(it["values"].get(m) or 0.0) >= 0.005) for m in months}

    def is_open(i):
        prior = [gov[m]["REVENUE_MTD"] for m in months[max(0, i - 3):i] if gov[m]["REVENUE_MTD"] not in (None, 0.0)]
        rev = gov[months[i]]["REVENUE_MTD"] or 0.0
        if prior and rev < 0.5 * statistics.median(prior):
            return True
        return i > 0 and posted[months[i]] < 0.5 * max(posted[m] for m in months[:i])
    if len(months) > 1 and is_open(len(months) - 1):
        closed = next((months[i] for i in range(len(months) - 2, -1, -1) if not is_open(i)), None)
        raise Refused(f"{months[-1]} has not closed in FINANCE_ANALYTICS (revenue {r2(gov[months[-1]]['REVENUE_MTD'])}, "
                      f"{posted[months[-1]]} P&L lines posted): build the last closed month instead",
                      use_as_of=closed)


# ---------------------------------------------------------------- formula evaluation (what Excel will display)

_REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")


class Evaluator:
    def __init__(self, ws):
        self.ws, self.cache = ws, {}

    def _cell(self, coord):
        if coord in self.cache:
            return self.cache[coord]
        self.cache[coord] = 0.0
        v = self.ws[coord].value
        if isinstance(v, str) and v.startswith("="):
            r = self.formula(v)
        elif isinstance(v, (dt.datetime, dt.date)):
            d = v.date() if isinstance(v, dt.datetime) else v
            r = float((d - dt.date(1899, 12, 30)).days)                 # Excel serial date (1900 system)
        elif isinstance(v, bool):
            r = float(v)
        elif isinstance(v, (int, float)):
            r = float(v)
        else:
            r = 0.0
        self.cache[coord] = r
        return r

    def _range(self, a, b):
        from openpyxl.utils.cell import range_boundaries
        c1, r1, c2, r2_ = range_boundaries(f"{a}:{b}")
        return [self._cell(f"{col_letter(c)}{r}") for r in range(r1, r2_ + 1) for c in range(c1, c2 + 1)]

    def formula(self, f):
        if re.search(r"[&^<>=\"!:'$]", _REF.sub("", f[1:])):          # only + - * / , SUM( IFERROR( and plain references
            raise Refused(f"the sheet holds a formula the check cannot evaluate: {f}")

        def ref(m):
            if m.group(3):
                return f'_r("{m.group(1)}{m.group(2)}","{m.group(3)}{m.group(4)}")'
            return f'_v("{m.group(1)}{m.group(2)}")'
        py = _REF.sub(ref, f[1:])
        py = re.sub(r"\bSUM\(", "_sum(", py)
        py = re.sub(r"\bIFERROR\(", "_iferror(lambda: ", py)
        py = re.sub(r"\bEOMONTH\(", "_eomonth(", py)
        if re.search(r"\b[A-Z][A-Z0-9.]*\(", py):
            raise Refused(f"the sheet holds a formula the check cannot evaluate: {f}")

        def _sum(*args):
            t = 0.0
            for a in args:
                t += sum(a) if isinstance(a, list) else a
            return t

        def _iferror(fn, alt):
            try:
                return fn()
            except ZeroDivisionError:
                return alt
        def _eomonth(serial, n):
            d = dt.date(1899, 12, 30) + dt.timedelta(days=int(serial))
            k = d.year * 12 + d.month - 1 + int(n)
            y, m = k // 12, k % 12 + 1
            return float((dt.date(y, m, calendar.monthrange(y, m)[1]) - dt.date(1899, 12, 30)).days)
        # names go in globals: the lambda IFERROR wraps its first argument in cannot see eval locals
        return float(eval(py, {"__builtins__": {}, "_v": self._cell, "_r": self._range, "_sum": _sum, "_iferror": _iferror, "_eomonth": _eomonth}))

    def value(self, coord):
        return self._cell(coord)


def store_results(path, sheet_name):
    """Write each formula's calculated result into the saved file (openpyxl saves formulas with an empty result, which
    Excel shows as blank or stale until it recalculates). The results come from the same evaluator as the gates; the
    Excel check then recalculates in Excel and refuses the file unless Excel gets the same numbers."""
    import zipfile
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ev = Evaluator(wb[sheet_name])
    values = {}
    for row in wb[sheet_name].iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                values[cell.coordinate] = ev.value(cell.coordinate)
    zin = zipfile.ZipFile(path)
    part = "xl/worksheets/sheet1.xml"
    xml = zin.read(part).decode("utf-8")
    done = set()

    def fill(m):
        coord = m.group(1)
        if coord not in values:
            return m.group(0)
        done.add(coord)
        attrs = re.sub(r'\s+t="[^"]*"', "", m.group(2))                # a numeric result: no type attribute
        return f'<c r="{coord}"{attrs}><f>{m.group(3)}</f><v>{repr(round(values[coord], 10))}</v></c>'
    xml = re.sub(r'<c r="([A-Z]+\d+)"([^>]*)><f>([^<]*)</f>(<v\s*/>|<v></v>)?</c>', fill, xml)
    missing = sorted(set(values) - done)
    if missing:
        raise Refused(f"could not store the calculated result of {len(missing)} formula cell(s), e.g. {missing[:5]}")
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, xml.encode("utf-8") if item.filename == part else zin.read(item.filename))
    zin.close()
    os.replace(tmp, path)
    return len(values)


AMOUNT_FORMAT = "#,##0;\\(#,##0\\);\\-"                       # the template's whole-unit amount format


def thousands_format(value):
    """Number format for an amount already held in thousands: one decimal, US grouping, negatives in brackets, zero as
    a dash. Excel takes digit grouping from the Windows locale (en-IN shows 2,88,095.6), which a format code cannot
    override, and the locale grouping only differs from US once the value reaches 100,000.0; from there the commas are
    written into the format."""
    shown = abs(value or 0.0)
    if shown < 99_999.95:
        return "#,##0.0;\\(#,##0.0\\);\\-"
    if shown < 999_999.95:
        return "#\\,##0.0;\\(#\\,##0.0\\);\\-"
    return "#\\,###\\,##0.0;\\(#\\,###\\,##0.0\\);\\-"


# ---------------------------------------------------------------- layout

def compact(ws, hdr, first_col):
    """The output layout (as before): title in B1, the "P&L Items" header on row 3 in column B, months from column C.
    The template's metric-type, period and criticality columns and the rows between title and header are removed;
    formulas, widths, heights and the freeze pane follow."""
    from copy import copy
    from openpyxl.formula.translate import Translator
    from openpyxl.utils import column_index_from_string
    from openpyxl.utils.cell import coordinate_from_string
    label_col = first_col - 1
    ncols = label_col - 2
    nrows = hdr - 3
    for rr in (1, 2):
        t = ws.cell(rr, 2)
        if t.value is not None and ncols > 0:
            d = ws.cell(rr, 2 + ncols)
            d.value, d.font, d.alignment = t.value, copy(t.font), copy(t.alignment)
            t.value = None
    widths = {column_index_from_string(k): (v.width, v.hidden) for k, v in ws.column_dimensions.items() if v.width}
    heights = {k: v.height for k, v in ws.row_dimensions.items() if v.height}
    freeze = ws.freeze_panes
    if nrows > 0:
        ws.delete_rows(3, nrows)
    if ncols > 0:
        ws.delete_cols(2, ncols)
    old_row = lambda r: r + (nrows if r >= 3 else 0)
    old_col = lambda c: c + (ncols if c >= 2 else 0)
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.value = Translator(cell.value, origin=f"{col_letter(old_col(cell.column))}{old_row(cell.row)}").translate_formula(cell.coordinate)
    for k in list(ws.column_dimensions.keys()):
        del ws.column_dimensions[k]
    for idx, (w, hidden) in widths.items():
        if idx == 1 or idx >= 2 + ncols:
            new = idx - (ncols if idx >= 2 + ncols else 0)
            ws.column_dimensions[col_letter(new)].width = w
            ws.column_dimensions[col_letter(new)].hidden = hidden
    for k in list(ws.row_dimensions.keys()):
        del ws.row_dimensions[k]
    for r, h in heights.items():
        if r < 3 or r >= 3 + nrows:
            ws.row_dimensions[r - (nrows if r >= 3 + nrows else 0)].height = h
    if freeze:
        fc, fr = coordinate_from_string(freeze)
        fci = column_index_from_string(fc)
        ws.freeze_panes = f"{col_letter(fci - (ncols if fci >= 2 + ncols else 0))}{fr - (nrows if fr >= 3 + nrows else 0)}"
    return {"columns_removed": ncols, "rows_removed": nrows, "label_column": "B", "first_month_column": "C", "header_row": 3}


# ---------------------------------------------------------------- build

def build(args):
    with open(os.path.join(args.work, "queries", "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    with open(args.map, encoding="utf-8") as fh:
        mp = json.load(fh)
    if args.template == TEMPLATE and not os.path.exists(TEMPLATE):
        try:
            fetch_template.fetch()
        except RuntimeError as exc:
            raise Refused(f"template is missing and could not be fetched from the stage: {exc}")
    if sha256(args.template) != mp["template_sha256"]:
        raise Refused(f"{os.path.basename(args.template)} does not match the map's template_sha256: a changed template needs clean_template.py and a map review")
    y, m = int(man["first_month"][:4]), int(man["first_month"][5:7])
    months = []
    for k in range(man["months"]):
        mm = (y * 12 + m - 1 + k)
        months.append(f"{mm // 12:04d}-{mm % 12 + 1:02d}")
    if months[-1] != man["as_of"]:
        raise Refused("the manifest's window does not end at its as-of month")
    q = man["queries"]
    res, qids = {}, {}
    for name in q:
        res[name], qids[name] = load_result(q[name]["raw"], q[name]["columns"])
    tol = mp.get("tolerance_default", 1.0)

    # -- sources
    pl = Lines("pl", res["pl"], ["COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "COA_MAPPING_L5", "COA_MAPPING_L6"], "TOTAL_MTD", "PERIOD_START_DATE", months,
               sign=pl_sign)
    bs_rows = [r for r in res["bs"] if norm(r["COA_MAPPING_L1"]) in BS_SECTIONS]
    stray = sorted({r["COA_MAPPING_L1"] for r in res["bs"] if norm(r["COA_MAPPING_L1"]) not in BS_SECTIONS
                    and month_label(r["PERIOD_START_DATE"]) in months and num(r["ENDING_BALANCE_CONVERTED"]) not in (None, 0.0)})
    if stray:
        raise Refused(f"balance sheet lines outside Assets and Liabilities & Equity carry balances: {', '.join(map(str, stray))}")
    bs = Lines("bs", bs_rows, ["COA_MAPPING_L1", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4"], "ENDING_BALANCE_CONVERTED", "PERIOD_START_DATE", months)
    cf_all, relabelled = relabel_cash_flow(res["cf"], mp.get("cf_unlabelled", []), months)
    cf = Lines("cf", [r for r in cf_all if norm(r["CASH_FLOW_L1"]) not in CF_LABELS], ["CASH_FLOW_L1", "CASH_FLOW_L2", "CASH_FLOW_L3"], "TOTAL_MTD", "PERIOD_START_DATE", months)
    cf_lab = Lines("cf_label", [r for r in cf_all if norm(r["CASH_FLOW_L1"]) in CF_LABELS], ["CASH_FLOW_L1", "CASH_FLOW_L2", "CASH_FLOW_L3"], "TOTAL_MTD", "PERIOD_START_DATE", months)
    for name, lines in (("pl", pl), ("bs", bs), ("cf", cf)):
        require_months(f"{name} ({TEXT_SECTIONS[name]})", lines.present, months)
    gov = keyed(res["pl_governed"], "PERIOD_START_DATE", months, value_cols=["REVENUE_MTD", "ADJUSTED_EBITDA_MTD", "NET_INCOME_MTD"])
    require_months("pl_governed", gov, months)
    closed_check(gov, pl, months)
    mtd_col, ltm_col = q["arr"]["columns"][2], q["arr"]["columns"][3]
    arr = keyed(res["arr"], "MONTH_END_DATE", months, key_col="CATEGORY", value_cols=[mtd_col, ltm_col])
    require_months("arr (ARR bridge)", arr, months)
    cust = keyed(res["customers"], "MONTH_END_DATE", months, key_col="CATEGORY", value_cols=["TOTAL_LTM"])
    require_months("customers (customer bridge)", cust, months)
    # revolver: Finance-maintained, one row per METRIC x month; METRICs are separate measures, never added together
    rev_metrics = mp.get("revolver_metrics", [])
    rev = {}
    for r in res["revolver"]:
        mo = month_label(r["MONTH_START_DATE"])
        if mo not in months:
            continue
        if r["METRIC"] not in rev_metrics:
            raise Refused(f"FINANCE_ANALYTICS REVOLVER carries METRIC {r['METRIC']!r}, which no row of the template holds")
        if (r["METRIC"], mo) in rev:
            raise Refused(f"duplicate REVOLVER METRIC {r['METRIC']!r} for {mo}")
        rev[(r["METRIC"], mo)] = num(r["AMOUNT"])
    for met in rev_metrics:
        require_months(f"revolver ({met})", {mo for (k, mo), v in rev.items() if k == met and v is not None}, months)
    bkg_cols = q["bookings"]["columns"][1:]
    bkg = keyed(res["bookings"], "AS_OF_DATE", months, month_end_only=True, value_cols=bkg_cols)
    require_months("bookings", bkg, months)
    ppl_cols = q["pipeline"]["columns"][1:]
    ppl = keyed(res["pipeline"], "AS_OF_DATE", months, month_end_only=True, value_cols=ppl_cols)
    # pipeline is a snapshot: months before the view's snapshot history cannot be rebuilt, so they stay blank (reported)
    ppl_missing = [m for m in months if m not in ppl]
    if len(ppl_missing) == len(months):
        require_months("pipeline", ppl, months)
    for m in ppl_missing:
        ppl[m] = {c: None for c in ppl_cols}
    # hosting: the hosting accounts (scope.json) split by COA L3, signed by P_AND_L_MULTIPLIER like the P&L. A month the
    # result carries has 0 for a bucket with no lines; a month it does not carry stays blank.
    hosting = {}
    host_months = {month_label(r["PERIOD_START_DATE"]) for r in res["hosting"]}
    for r in res["hosting"]:
        mo = month_label(r["PERIOD_START_DATE"])
        if mo in months:
            k = (str(r["BUCKET"]), mo)
            hosting[k] = hosting.get(k, 0.0) + (num(r["TOTAL_MTD"]) or 0.0) * pl_sign(r)
    known_arr = set(mp["arr_categories"])
    odd = sorted({c for mo in arr.values() for c, v in mo.items() if c not in known_arr and any(x not in (None, 0.0) for x in v.values())})
    if odd:
        raise Refused(f"ARR_ANALYTICS carries bridge categories the template has no row for: {', '.join(odd)}")

    def cat(src, name, col):
        return {mo: (src[mo].get(name) or {}).get(col) for mo in months}

    # -- template
    from openpyxl import load_workbook
    from openpyxl.comments import Comment
    from openpyxl.formatting.formatting import ConditionalFormattingList
    from openpyxl.formula.translate import Translator
    wb = load_workbook(args.template)
    sanitize(wb, keep_sheet=mp["sheet"])
    ws = wb[mp["sheet"]]
    lc, fc = mp["label_col"], mp["first_month_col"]
    hdr = next((r for r in range(1, 40) if norm(ws.cell(r, lc).value) == norm(mp["header_label"])), None)
    if not hdr:
        raise Refused(f"header row {mp['header_label']!r} not found in column {col_letter(lc)}")
    last_tpl = ws.max_column
    if last_tpl - fc + 1 < len(months):
        raise Refused(f"the template has {last_tpl - fc + 1} month columns; {len(months)} asked")
    cols = list(range(fc, fc + len(months)))
    first_end = dt.date(int(months[0][:4]), int(months[0][5:7]), calendar.monthrange(int(months[0][:4]), int(months[0][5:7]))[1])
    ws.cell(hdr, fc).value = dt.datetime(first_end.year, first_end.month, first_end.day)

    rows, unknown, section = {}, [], None
    sections = {norm(s): s for s in mp["sections"]}
    for r in range(hdr + 1, ws.max_row + 1):
        lab = ws.cell(r, lc).value
        if lab is None or str(lab).strip() == "":
            continue
        lab = str(lab).strip()
        if norm(lab) in sections:
            section = sections[norm(lab)]
            continue
        key = f"{section} | {lab}"
        if key not in mp["rows"]:
            unknown.append(f"row {r}: {key}")
            continue
        if key in rows:
            raise Refused(f"two template rows read {key!r}")
        rows[key] = r
    missing = [k for k in mp["rows"] if k not in rows]
    if unknown or missing:
        raise Refused("the template and the row map disagree", not_in_map=unknown[:20], not_in_template=missing[:20])

    report = {"filled": [], "blank": [], "derived": [], "formula_overrides": [], "template_values_replaced": [], "remainders": []}
    values = {}                                                     # key -> {month: value} for data rows, in the view's sign
    shown = {}                                                      # key -> {month: value} as written to the sheet
    notes_written = 0

    def as_shown(e, series):
        """The template enters costs and outflows positive: a 'negate' row is written with the view's sign reversed."""
        if not series or not e.get("negate"):
            return series
        return {mo: (None if v is None else (0.0 if v == 0 else -v)) for mo, v in series.items()}

    def put(r, series, kind="amt"):
        for j, c in enumerate(cols):
            v = series.get(months[j]) if series else None
            if v is not None:
                v = round(v, 6) if kind == "ratio" else (int(round(v)) if kind == "count" else r2(v))
            ws.cell(r, c).value = v

    def first_formula(r):
        g = ws.cell(r, fc).value
        return g if isinstance(g, str) and g.startswith("=") else None

    def chain_formula(r):
        h = ws.cell(r, fc + 1).value
        return h if isinstance(h, str) and h.startswith("=") else None

    def fill_formula(r, f, origin_col):
        for c in cols:
            ws.cell(r, c).value = Translator(f, origin=f"{col_letter(origin_col)}{r}").translate_formula(f"{col_letter(c)}{r}")

    remainders, confirm = [], []
    if ppl_missing:
        confirm.append({"item": "Pipeline", "detail": f"GTM_ANALYTICS has no pipeline snapshot for {ppl_missing[0]} to {ppl_missing[-1]} ({len(ppl_missing)} month(s)); those months are blank",
                        "months": len(ppl_missing)})
    for key, r in rows.items():
        e = mp["rows"][key]
        src = e.get("src")
        section = key.split(" | ")[0]
        hf = None
        if e.get("chain"):
            hf = chain_formula(r)                                    # read before any cell of the row is written
            if not hf:
                raise Refused(f"{key}: marked chain but the template's second month is not a formula")
        if src == "heading":
            put(r, None)
            continue
        if src == "formula":
            f = e.get("override") or first_formula(r)
            if not f:
                raise Refused(f"{key}: a formula row whose first month holds no formula")
            replaced = sum(1 for c in cols[1:] if not (isinstance(ws.cell(r, c).value, str) and str(ws.cell(r, c).value).startswith("=")) and ws.cell(r, c).value is not None)
            fill_formula(r, f, fc)
            if e.get("override"):
                report["formula_overrides"].append({"row": key, "formula": f, "why": e.get("why")})
            if replaced:
                report["template_values_replaced"].append({"row": key, "cells": replaced, "why": "the template carried typed numbers in some months of a formula row; the formula now runs in every month"})
            continue
        if src is None:
            put(r, None)
            if hf:
                fill_formula(r, hf, fc + 1)
                ws.cell(r, fc).value = None
            report["blank"].append({"row": key, "reason": e.get("reason")})
            continue
        if first_formula(r):
            report["template_values_replaced"].append({"row": key, "was": first_formula(r), "why": e.get("why") or "the view carries this row"})
        series, origin, kind = None, None, "amt"
        if src in ("pl", "bs", "cf") and "remainder_of" in e:
            remainders.append((key, r, e))
            continue
        if src in ("pl", "bs", "cf"):
            series, origin = {"pl": pl, "bs": bs, "cf": cf}[src].take(e["line"], e.get("level"))
        elif src == "cf_label":
            series, origin = cf_lab.take(e["line"])
        elif src == "arr":
            series, origin = cat(arr, e["category"], mtd_col), f"ARR_WATERFALL {e['category']} ({mtd_col})"
        elif src == "arr_rate":
            num_s = [cat(arr, n, ltm_col) for n in e["numerator"]]
            den = cat(arr, e["denominator"], ltm_col)
            series = {}
            for mo in months:
                parts = [s[mo] for s in num_s]
                series[mo] = None if (den[mo] in (None, 0.0) or any(p is None for p in parts)) else sum(parts) / den[mo]
            origin, kind = f"derived: ({' + '.join(e['numerator'])}) / {e['denominator']}, LTM ({ltm_col})", "ratio"
            report["derived"].append({"row": key, "formula": origin, "why": e.get("why")})
        elif src == "customers":
            series, origin, kind = cat(cust, e["category"], "TOTAL_LTM"), f"CUSTOMER_BRIDGE {e['category']} (LTM)", "count"
        elif src == "customer_rate":
            num_s = [cat(cust, n, "TOTAL_LTM") for n in e["numerator"]]
            den = cat(cust, e["denominator"], "TOTAL_LTM")
            series = {}
            for mo in months:
                parts = [s[mo] for s in num_s]
                series[mo] = None if (den[mo] in (None, 0.0) or any(p is None for p in parts)) else sum(parts) / den[mo]
            origin, kind = f"derived: ({' + '.join(e['numerator'])}) / {e['denominator']}, CUSTOMER_BRIDGE LTM", "ratio"
            report["derived"].append({"row": key, "formula": origin, "why": e.get("why")})
        elif src == "revolver":
            # a stored 0 is Finance's figure and is written; a missing month was refused above
            series, origin = {mo: rev[(e["metric"], mo)] for mo in months}, f"REVOLVER {e['metric']}"
        elif src == "bookings":
            series, origin = {mo: bkg[mo][e["metric"]] for mo in months}, f"BOOKINGS_OVERVIEW.{e['metric']}"
        elif src == "hosting":
            series = {mo: (hosting.get((e["bucket"], mo), 0.0) if mo in host_months else None) for mo in months}
            origin = f"hosting accounts {', '.join(e.get('accounts_label', []) or ['(scope.json)'])}, bucket {e['bucket']}"
        elif src == "pipeline":
            series, origin = {mo: ppl[mo][e["metric"]] for mo in months}, f"PIPELINE_OVERVIEW.{e['metric']}"
            kind = "ratio" if "RATIO" in e["metric"] else "amt"
        else:
            raise Refused(f"{key}: unknown source {src!r} in the map")
        if e.get("blank_if_all_zero") and series and all(v in (None, 0.0) for v in series.values()):
            confirm.append({"item": key, "detail": f"{origin} is 0 in every month of the window; the row is left blank. {e.get('zero_reason', '')}".strip()})
            series = None
        if e.get("negate") and src not in ("pl", "bs", "cf", "arr", "customers", "hosting"):
            raise Refused(f"{key}: 'negate' is only for amounts read from a view line or bridge category")
        out = as_shown(e, series)
        if hf:
            fill_formula(r, hf, fc + 1)
            ws.cell(r, fc).value = r2((out or {}).get(months[0]))
        else:
            put(r, out, kind)
        values[key] = series
        shown[key] = out
        if series is None or all(v is None for v in series.values()):
            report["blank"].append({"row": key, "reason": e.get("zero_reason") if e.get("blank_if_all_zero") else f"{e.get('line') or e.get('category') or e.get('metric')} is not in the view"})
        else:
            report["filled"].append({"row": key, "from": origin, "months_with_values": sum(1 for v in series.values() if v is not None)})

    for key, r, e in remainders:
        section = key.split(" | ")[0]
        src_lines = {"pl": pl, "bs": bs, "cf": cf}[e["src"]]
        bases = e["remainder_of"] if isinstance(e["remainder_of"], list) else [e["remainder_of"]]
        base, origin = None, None
        for b in bases:
            base, origin = src_lines.take(b, e.get("remainder_level"))
            if base is not None:
                break
        less = [values.get(f"{section} | {n}") or {} for n in e.get("less", [])]
        less += [src_lines.series(src_lines.lookup(n)[1]) if src_lines.lookup(n) else {} for n in e.get("less_lines", [])]
        series = None
        if base is not None:
            series = {}
            for mo in months:
                if base[mo] is None:
                    series[mo] = None
                    continue
                series[mo] = base[mo] - sum((s.get(mo) or 0.0) for s in less)
                if abs(series[mo]) < 0.005:
                    series[mo] = 0.0
        out = as_shown(e, series)
        put(r, out)
        values[key] = series
        shown[key] = out
        if series is None:
            report["blank"].append({"row": key, "reason": f"{' / '.join(bases)} is not in the view"})
        else:
            report["remainders"].append({"row": key, "from": f"{origin} less {', '.join(e.get('less', []) + e.get('less_lines', []))}"})
            report["filled"].append({"row": key, "from": f"{origin} (remainder)", "months_with_values": sum(1 for v in series.values() if v is not None)})

    # every line with activity lands in a row
    gaps = {k: v.uncovered() for k, v in (("pl", pl), ("bs", bs), ("cf", cf))}
    # the cash flow's Net Income is the P&L's (the CF row is a formula); it is checked below, so count it as covered
    gaps["cf"] = [g for g in gaps["cf"] if not g.endswith("> Net Income")]
    if any(gaps.values()):
        raise Refused("view lines with activity have no row in the template (add them to assets/chronograph_map.json)",
                      unmapped={TEXT_SECTIONS[k]: v for k, v in gaps.items() if v})

    # formats and notes
    for key, r in rows.items():
        e = mp["rows"][key]
        if e.get("format"):
            for c in cols:
                ws.cell(r, c).number_format = e["format"]
        note = e.get("note") or (f"Derived from ARR_ANALYTICS ({man['arr_basis']}), not a governed metric. {e.get('why', '')}" if e.get("src") == "arr_rate"
                                 else "Derived from ARR_ANALYTICS CUSTOMER_BRIDGE LTM counts, not a governed metric. (Beginning - Lost) / Beginning, LTM." if e.get("src") == "customer_rate" else None)
        if note:
            ws.cell(r, lc).comment = Comment(note, "CFO Chronograph refresh")
            notes_written += 1

    # months beyond the window, and stray constants in unlabelled rows
    for r in range(hdr + 1, ws.max_row + 1):
        if r in rows.values():
            continue
        for c in cols:
            v = ws.cell(r, c).value
            if v is not None and not (isinstance(v, str) and v.startswith("=")) and ws.cell(r, lc).value is None:
                ws.cell(r, c).value = None
    if last_tpl > cols[-1]:
        ws.delete_cols(cols[-1] + 1, last_tpl - cols[-1])

    # -- amounts in thousands: every amount the build wrote is divided by 1,000 (counts, percentages and ratios are not);
    # formula cells are left alone and calculate in thousands from their inputs. The gates below compare in dollars.
    disp = mp.get("display") or {}
    skip = set(disp.get("not_scaled_sections", []))
    scaled_rows, divided = set(), 0
    if disp.get("scale") == "thousands":
        for key, r in rows.items():
            if key.split(" | ")[0] in skip or ws.cell(r, cols[0]).number_format != AMOUNT_FORMAT:
                continue
            scaled_rows.add(r)
            for c in cols:
                cell = ws.cell(r, c)
                if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    cell.value = cell.value / 1000.0
                    divided += 1
    unit = lambda r: 1000.0 if r in scaled_rows else 1.0          # sheet value x unit = the view's dollars

    # -- gates: evaluate the sheet's formulas as Excel will
    ev = Evaluator(ws)
    refs = {
        "pl_governed": lambda col: {mo: gov[mo][col] for mo in months},
        "cf_label": lambda name: cf_lab.series(cf_lab.lookup(name)[1]) if cf_lab.lookup(name) else {mo: None for mo in months},
        "cf": lambda name: cf.series(cf.lookup(name)[1]) if cf.lookup(name) else {mo: None for mo in months},
        # a list of categories is summed: NDR is checked against Net Dollar Retention + FX, because the sheet carries
        # FX in the (Transactional) downsell row inside its NDR formula, while the view adds FX only after NDR
        "arr": lambda *names: {mo: (None if any(cat(arr, n, mtd_col)[mo] is None for n in names) else sum(cat(arr, n, mtd_col)[mo] for n in names)) for mo in months},
        "customers": lambda name: cat(cust, name, "TOTAL_LTM"),
        "bookings": lambda col: {mo: bkg[mo][col] for mo in months},
        "zero": lambda *_: {mo: 0.0 for mo in months},
    }
    checks, failed, info = [], [], []
    for chk in mp["checks"]:
        r = rows[chk["row"]]
        ref = refs[chk["against"][0]](*chk["against"][1:])
        blocking = chk.get("blocking", True)
        diffs = []
        for j, c in enumerate(cols):
            mine = ev.value(f"{col_letter(c)}{r}") * unit(r)
            theirs = ref[months[j]]
            if theirs is None:
                if blocking:
                    failed.append({"row": chk["row"], "month": months[j], "sheet": r2(mine), "view": None, "why": "the view has no value to check against"})
                continue
            d = mine - theirs
            rec = {"row": chk["row"], "month": months[j], "sheet": r2(mine), "view": r2(theirs), "difference": r2(d)}
            if not blocking:
                if abs(d) > chk.get("tolerance", tol) + 1e-9:
                    diffs.append(rec)
                continue
            checks.append(rec)
            if abs(d) > chk.get("tolerance", tol) + 1e-9:
                failed.append(rec)
        if not blocking:
            info.append({"row": chk["row"], "against": ".".join(chk["against"]), "explain": chk.get("explain"),
                         "months_different": len(diffs), "differences": [{k: d[k] for k in ("month", "sheet", "view", "difference")} for d in diffs]})
    for lim in mp.get("limit_checks", []):
        hi, lo = values.get(lim["not_above"]) or {}, values.get(lim["row"]) or {}
        over = [mo for mo in months if lo.get(mo) is not None and hi.get(mo) is not None and lo[mo] > hi[mo] + 1e-9]
        for mo in over:
            failed.append({"row": lim["row"], "month": mo, "sheet": r2(lo[mo]), "view": r2(hi[mo]), "why": lim.get("explain")})
        checks.extend({"row": lim["row"], "month": mo, "limit": lim["not_above"]} for mo in months if mo not in over)
    if failed:
        by_row = {}
        for f in failed:
            by_row.setdefault(f["row"], []).append(f["month"])
        raise Refused(f"{len(failed)} reconciliation check(s) failed: the workbook would not tie to the governed views",
                      failed_rows={k: f"{len(v)} month(s): {', '.join(v[:6])}{' ...' if len(v) > 6 else ''}" for k, v in by_row.items()},
                      first_failures=failed[:8])

    # -- items for the view owner: what the build placed or reported rather than took from a labelled, consistent line
    for u in relabelled:
        confirm.append({"item": f"Cash flow | {u['placed_in']}", "detail": f"rows the view leaves without a cash-flow label were placed here: {u.get('why') or ''}".strip(),
                        "last_month": u["months"].get(months[-1])})
    for it in info:
        if it["months_different"]:
            confirm.append({"item": it["row"], "detail": it.get("explain"), "months_different": it["months_different"],
                            "largest": max((d["difference"] for d in it["differences"]), key=abs)})
    for key, chk in (mp.get("sign_watch") or {}).items():
        ser = shown.get(key) or {}                                  # the sign as the template reads it
        odd = {mo: v for mo, v in ser.items() if v is not None and (v > 0.5 if chk["expect"] == "negative" else v < -0.5)}
        if odd:
            confirm.append({"item": key, "detail": chk["explain"], "months": len(odd), "largest": max(odd.values(), key=abs)})

    totals = {k: r2(ev.value(f"{col_letter(cols[-1])}{rows[k]}") * unit(rows[k])) for k in
              ("Profit & Loss | Total Revenue", "Profit & Loss | Adjusted EBITDA", "Profit & Loss | Net Income", "Balance Sheet | Total Assets",
               "Cash Flow Statement | Ending Cash", "ARR Bridge | Ending ARR", "Customer Bridge | Ending Customers", "Bookings | Total Bookings (ARR + SR)")}

    # -- display: the amounts (already in thousands) with one decimal and US grouping
    scaled_cells = 0
    for r in scaled_rows:
        for c in cols:
            cell = ws.cell(r, c)
            if cell.number_format == AMOUNT_FORMAT:                  # percentages, ratios and dates keep their formats
                cell.number_format = thousands_format(ev.value(cell.coordinate))
                scaled_cells += 1

    # -- provenance line, layout, sanitise, save, check
    synthetic = man.get("mode") == "synthetic"
    accounts = man["scope"].get("exclude_accounts") or []           # opt-in; older manifests carry none
    acct_note = (f" Excludes {len(accounts)} Salesforce account(s) from recurring bookings and pipeline (ARR, customers and the P&L still include them): {', '.join(accounts)};"
                 " the P&L, balance sheet, cash flow and non-recurring bookings still include them." if accounts else "")
    stamp = (f"{'SYNTHETIC TEST DATA - NOT REAL. ' if synthetic else ''}Actuals {months[0]} to {months[-1]} from PROD semantic views FINANCE_ANALYTICS, "
             f"GTM_ANALYTICS and ARR_ANALYTICS (ARR basis: {man['arr_basis']}); excludes {', '.join(man['scope']['exclude_subsidiaries']) or 'no subsidiary'}.{acct_note} "
             f"Amounts in USD thousands (customer and headcount counts, percentages and ratios unscaled). Blank = not carried by the views. Generated {dt.date.today().isoformat()}.")
    # provenance goes in the file's document properties (File > Info), not on the sheet; synthetic data stays labelled on the sheet
    wb.properties.description = stamp
    wb.properties.subject = f"CFO Chronograph actuals {months[0]} to {months[-1]}"
    if synthetic:
        ws.cell(2, 2).value = "SYNTHETIC TEST DATA - NOT REAL"
    for row in ws.iter_rows(min_col=1, max_col=1):                 # column A: the template's "Notes" header, not shown
        for cell in row:
            cell.value = None
    ws.conditional_formatting = ConditionalFormattingList()       # the criticality column the rules colour is removed below
    layout = compact(ws, hdr, fc)
    from openpyxl.worksheet.views import Selection
    ws.freeze_panes = None                                         # no frozen panes ...
    ws.sheet_view.pane = None
    ws.sheet_view.selection = [Selection(activeCell="B1", sqref="B1")]   # ... and no selections left on the removed panes
    sanitize(wb, keep_sheet=mp["sheet"])
    # the output is a report, not the template: sheet name and title without "Template" (the pinned template keeps its names)
    ws.title = mp.get("output_sheet", mp["sheet"])
    if mp.get("output_title"):
        ws["B1"].value = mp["output_title"]
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, f"yes_energy_chronograph_{man['as_of']}" + ("_SYNTHETIC" if synthetic else "") + ".xlsx")
    # the workbook is assembled and checked on local disk: a stage-backed folder (the Snowsight /workspace mount)
    # cannot rewrite a zip in place. Only the finished, checked file is copied to the output folder.
    fd, tmp = tempfile.mkstemp(prefix=".chrono-", suffix=".xlsx")
    os.close(fd)
    wb.save(tmp)
    try:
        stored = store_results(tmp, ws.title)
        finalized = check_workbook.excel_finalize(tmp) if args.excel != "off" and check_workbook.excel_available() else None
    except Refused:
        os.remove(tmp)
        raise
    if finalized is not None and not finalized.get("saved"):
        os.remove(tmp)
        raise Refused(f"Excel could not recalculate and save the workbook: {finalized.get('error')}")
    wbcheck = check_workbook.run(tmp, args.excel, require_results=True)
    if wbcheck["status"] != "CLEAN":
        os.remove(tmp)
        raise Refused("the workbook failed the open check (Excel would repair it, show stale values, or calculate different results)", workbook_check=wbcheck)
    try:
        shutil.copyfile(tmp, out)
    except PermissionError:
        raise Refused(f"{out} is open (probably in Excel) and cannot be replaced: close it and run the build again")
    finally:
        os.remove(tmp)
    wbcheck["file"] = out
    return {
        "status": "WRITTEN", "out": out, "as_of": man["as_of"], "window": [months[0], months[-1]], "months": len(months),
        "mode": man.get("mode", "governed"), "arr_basis": man["arr_basis"],
        "scope": {"excluded_subsidiaries": man["scope"]["exclude_subsidiaries"], "note": "ARR_ANALYTICS and GTM pipeline have no subsidiary dimension: all entities as stored",
                  "excluded_accounts": accounts,
                  "excluded_accounts_note": ("left out of recurring bookings and pipeline only: ARR_ANALYTICS keys customers by Yes Energy / RTO Insider ID and FINANCE_ANALYTICS has no Salesforce account, so ARR, customers, the P&L, "
                                             "balance sheet and cash flow (and NetSuite non-recurring bookings) still include them" if accounts else "none: every account included")},
        "sources": {n: {"rows": len(res[n]), "query_id": qids[n]} for n in res},
        "rows_filled": len(report["filled"]), "rows_blank": len(report["blank"]),
        "blank": report["blank"], "derived": report["derived"], "formula_overrides": report["formula_overrides"],
        "entered_positive": [k for k, e in mp["rows"].items() if e.get("negate") and shown.get(k)],
        "template_values_replaced": report["template_values_replaced"], "remainders": report["remainders"],
        "checks": {"run": len(checks), "failed": 0, "tolerance_usd": tol, "result": "PASS"},
        "reconciling_items": info,
        "confirm_at_source": confirm,
        "formula_rows_over_blank_inputs": [k for k, e in mp["rows"].items() if e.get("src") == "formula" and e.get("inputs_blank")],
        "last_month": totals, "layout": layout, "formula_results_stored": stored,
        "display": {"amounts": "USD thousands (cell values divided by 1,000), one decimal, US grouping", "rows_in_thousands": len(scaled_rows),
                    "values_divided": divided, "cells_formatted": scaled_cells, "last_month_totals": "USD (sheet x 1,000)",
                    "not_scaled": "Customer Bridge and Headcount (counts), percentages and the month headers"},
        "saved_by_excel": bool(finalized and finalized.get("saved")),
        "note": None if finalized else "Excel was not available to recalculate and save the file: results are stored, but in a manual-calculation Excel session the formulas may show as stale until F9",
        "workbook_check": {k: wbcheck[k] for k in ("structure", "excel", "status")} | ({"excel_recalc": wbcheck["excel_detail"].get("recalc")} if wbcheck.get("excel_detail") else {}),
        "filled": report["filled"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--map", default=MAP)
    ap.add_argument("--excel", choices=["auto", "on", "off"], default="auto", help="open-test the file in a hidden Excel (auto: when Excel is installed)")
    args = ap.parse_args()
    try:
        result = build(args)
    except Refused as exc:
        out = {"status": "REFUSED", "reason": str(exc), **exc.extra}
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        return 1
    with open(os.path.join(args.work, "chronograph_report.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False, default=str)
    brief = {k: v for k, v in result.items() if k != "filled"}
    print(json.dumps(brief, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
