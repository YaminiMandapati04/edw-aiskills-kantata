#!/usr/bin/env python3
"""Result-bundle loading, validation and number formatting shared by the
exporters (make_chart.py, export_xlsx.py, build_dashboard.py).

CLI:  python bundle.py bundle.json     -> prints OK or a list of problems (exit 1)

Contract: see references/output-formats.md.
"""
import json
import re
import sys

COLUMN_TYPES = {"text", "date", "integer", "number", "currency", "currency_mm", "percent", "multiple"}
CHART_TYPES = {"line", "column", "bar", "waterfall"}
PROVENANCE = {"governed", "derived", "scenario"}
EVIDENCE = {"established", "hypothesis"}
TAGS = {"volume", "price", "mix", "timing", "one-off", "unexplained"}
NUMERIC_TYPES = {"integer", "number", "currency", "currency_mm", "percent", "multiple"}
ADDITIVE_TYPES = {"integer", "number", "currency", "currency_mm"}

# Accordion brand
NAVY = "1F242F"      # Gray 7
GRAY6 = "393F4A"
GRAY5 = "525965"
GRAY4 = "818995"
GRAY3 = "C2C7CF"
GRAY2 = "DEE2E9"
GRAY1 = "F2F4F9"
CITRON = "EEFB87"
MINT = "3BA184"
ALMOND = "BF9856"
SKY = "91C1F2"
LAVENDER = "EADCF5"
ALERT = "B23A3A"     # functional red, negatives only

BAR_PALETTE = [NAVY, CITRON, GRAY4, MINT, ALMOND, SKY]
LINE_PALETTE = [NAVY, MINT, ALMOND, GRAY4, SKY]


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(b):
    """Return a list of problem strings (empty list = valid)."""
    errs = []
    if not isinstance(b, dict):
        return ["Bundle must be a JSON object."]
    meta = b.get("meta") or {}
    if not meta.get("title"):
        errs.append("meta.title is required.")

    tables = b.get("tables") or []
    ids = set()
    tmap = {}
    for ti, t in enumerate(tables):
        tid = t.get("id")
        where = f"tables[{ti}]"
        if not tid or not re.fullmatch(r"[a-z0-9_]+", tid):
            errs.append(f"{where}: id is required and must match [a-z0-9_]+.")
            continue
        if tid in ids:
            errs.append(f"{where}: duplicate id '{tid}'.")
        ids.add(tid)
        where = f"table '{tid}'"
        if not t.get("title"):
            errs.append(f"{where}: title is required.")
        cols = t.get("columns") or []
        if not cols:
            errs.append(f"{where}: columns is empty.")
        names = [c.get("name") for c in cols]
        if len(set(names)) != len(names):
            errs.append(f"{where}: duplicate column names.")
        for c in cols:
            if c.get("type", "text") not in COLUMN_TYPES:
                errs.append(f"{where}: column '{c.get('name')}' has unknown type '{c.get('type')}'.")
            if c.get("total") and c.get("type") not in ADDITIVE_TYPES:
                errs.append(f"{where}: column '{c.get('name')}' has total but type "
                            f"'{c.get('type')}' is not additive (percent/multiple can't be summed).")
        for ri, r in enumerate(t.get("rows") or []):
            if len(r) != len(cols):
                errs.append(f"{where}: row {ri} has {len(r)} values for {len(cols)} columns.")
                continue
            for ci, v in enumerate(r):
                ctype = cols[ci].get("type", "text")
                if v is not None and ctype in NUMERIC_TYPES and (isinstance(v, bool) or not isinstance(v, (int, float))):
                    errs.append(f"{where}: row {ri}, column '{cols[ci].get('name')}' expects a number, got {v!r}.")
        if t.get("provenance", "governed") not in PROVENANCE:
            errs.append(f"{where}: provenance must be one of {sorted(PROVENANCE)}.")
        tmap[tid] = t

    for ci, ch in enumerate(b.get("charts") or []):
        where = f"charts[{ci}]"
        if ch.get("type") not in CHART_TYPES:
            errs.append(f"{where}: type must be one of {sorted(CHART_TYPES)}.")
        t = tmap.get(ch.get("table"))
        if t is None:
            errs.append(f"{where}: table '{ch.get('table')}' not found.")
            continue
        if not t.get("rows"):
            errs.append(f"{where}: table '{ch.get('table')}' has no rows; remove the chart.")
            continue
        names = [c["name"] for c in t.get("columns", [])]
        if ch.get("x") not in names:
            errs.append(f"{where}: x column '{ch.get('x')}' not in table '{ch.get('table')}'.")
        ys = ch.get("y") or []
        if not ys:
            errs.append(f"{where}: y must list at least one column.")
        for y in ys:
            if y not in names:
                errs.append(f"{where}: y column '{y}' not in table '{ch.get('table')}'.")
            else:
                ctype = next(c.get("type", "text") for c in t["columns"] if c["name"] == y)
                if ctype not in NUMERIC_TYPES:
                    errs.append(f"{where}: y column '{y}' is not numeric.")
        if ch.get("type") == "waterfall" and len(ys) != 1:
            errs.append(f"{where}: waterfall takes exactly one y column.")
        if len(ys) > 4:
            errs.append(f"{where}: more than 4 series — split the chart.")
        if ch.get("provenance", "governed") not in PROVENANCE:
            errs.append(f"{where}: provenance must be one of {sorted(PROVENANCE)}.")

    for fi, f in enumerate(b.get("findings") or []):
        if not f.get("text"):
            errs.append(f"findings[{fi}]: text is required.")
        if f.get("evidence", "established") not in EVIDENCE:
            errs.append(f"findings[{fi}]: evidence must be one of {sorted(EVIDENCE)}.")
        if f.get("tag") and f["tag"] not in TAGS:
            errs.append(f"findings[{fi}]: tag must be one of {sorted(TAGS)}.")

    for ki, k in enumerate(b.get("kpis") or []):
        if "label" not in k or "value" not in k:
            errs.append(f"kpis[{ki}]: label and value are required.")
        elif k.get("source"):
            errs.extend(_kpi_source_problems(ki, k, tmap))

    if meta.get("data_mode", "governed") not in DATA_MODES:
        errs.append(f"meta.data_mode must be one of {sorted(DATA_MODES)}.")
    for t in tables:
        if t.get("capped") and not (isinstance(t.get("row_count_total"), int) and t["row_count_total"] > len(t.get("rows") or [])):
            errs.append(f"table '{t.get('id')}': capped is true but row_count_total is missing or not larger than the rows shown.")
    if meta.get("data_mode") == "local":
        for t in tables:
            if t.get("provenance", "governed") == "governed":
                errs.append(f"table '{t.get('id')}': local test data cannot be labelled governed; set provenance to derived (or scenario).")
        for ci, ch in enumerate(b.get("charts") or []):
            if ch.get("provenance", "governed") == "governed":
                errs.append(f"charts[{ci}]: local test data cannot be labelled governed; set provenance to derived (or scenario).")
    errs.extend(waterfall_problems(b, tmap))
    errs.extend(m for sev, m in claim_problems(b) if sev == "error")
    return errs


# ------------------------------------------------------------------- integrity
# These checks exist so that every figure a reader sees (chat, workbook, dashboard,
# chart) is the same figure: text may only cite numbers that are in a bundle table
# or KPI, KPIs can be tied to the table cell they came from, bridges must add up,
# and every output carries a fingerprint of the content it was built from.

DATA_MODES = {"governed", "local"}
LOCAL_BANNER = "LOCAL TEST DATA: from an uploaded workbook, not a governed semantic view"


def _same(a, b_, rel=1e-9):
    return abs(a - b_) <= rel * max(1.0, abs(a), abs(b_))


def _kpi_source_problems(ki, k, tmap):
    src = k["source"]
    where = f"kpis[{ki}] ('{k.get('label')}')"
    t = tmap.get(src.get("table"))
    if t is None:
        return [f"{where}: source table '{src.get('table')}' not found."]
    names = [c["name"] for c in t["columns"]]
    if src.get("column") not in names:
        return [f"{where}: source column '{src.get('column')}' not in table '{src['table']}'."]
    ci = names.index(src["column"])
    row = src.get("row")
    if isinstance(row, dict):
        if row.get("column") not in names:
            return [f"{where}: source row column '{row.get('column')}' not in table '{src['table']}'."]
        ri = names.index(row["column"])
        hits = [r for r in t["rows"] if r[ri] == row.get("equals")]
        if len(hits) != 1:
            return [f"{where}: source row match {row} found {len(hits)} rows, need exactly 1."]
        cell = hits[0][ci]
    elif isinstance(row, int) and 0 <= row < len(t["rows"]):
        cell = t["rows"][row][ci]
    elif row == "total" and any(c.get("total") == "sum" for c in t["columns"] if c["name"] == src["column"]):
        cell = sum(r[ci] for r in t["rows"] if isinstance(r[ci], (int, float)))
    else:
        return [f"{where}: source row must be an index, {{column, equals}} or 'total'."]
    v = k["value"]
    if not (isinstance(cell, (int, float)) and isinstance(v, (int, float)) and _same(cell, v)):
        return [f"{where}: value {v!r} does not equal source cell {cell!r} ({src['table']}.{src['column']})."]
    return []


def waterfall_problems(b, tmap=None):
    """A bridge must add up: each subtotal or end bar equals the running sum before it."""
    tmap = tmap or {t.get("id"): t for t in b.get("tables") or []}
    out = []
    for ch in b.get("charts") or []:
        t = tmap.get(ch.get("table"))
        if ch.get("type") != "waterfall" or t is None or not t.get("rows") or len(ch.get("y") or []) != 1:
            continue
        names = [c["name"] for c in t["columns"]]
        if ch.get("x") not in names or ch["y"][0] not in names:
            continue
        xs = [r[names.index(ch["x"])] for r in t["rows"]]
        vs = [r[names.index(ch["y"][0])] or 0 for r in t["rows"]]
        totals = set(ch.get("totals") or [])
        run = 0.0
        for i, (lab, v) in enumerate(zip(xs, vs)):
            if i == 0 or lab in totals:
                if i > 0 and abs(v - run) > 1e-6 * max(1.0, abs(run)) + 0.005:
                    out.append(f"chart '{ch.get('id')}': bridge does not add up at '{lab}': bar is {v:,.4g}, "
                               f"the steps before it sum to {run:,.4g}.")
                run = v
            else:
                run += v
    return out


def fingerprint(b):
    """Short content hash of everything a reader could see. Stamped into every output."""
    import hashlib
    meta = b.get("meta") or {}
    core = {
        "meta": {k: meta.get(k) for k in ("title", "period", "currency", "scale", "as_of", "data_mode")},
        "headline": b.get("headline"),
        "kpis": b.get("kpis"),
        "findings": b.get("findings"),
        "tables": [{"id": t.get("id"), "columns": t.get("columns"), "rows": t.get("rows")} for t in b.get("tables") or []],
        "charts": b.get("charts"),
    }
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


_STRIP = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{4}-Q\d\b|\b(?:19|20)\d{2}\b")
_NUM = re.compile(r"(?<![\w.])(\$?)\s?(\d[\d,]*(?:\.\d+)?)\s?(%|pp\b|mm\b|mn\b|bn\b|x\b|m\b|k\b)?", re.I)
_SCALES = {"%": (1, 100), "pp": (1, 100), "x": (1,)}
_MONEY_SCALES = (1, 1e-3, 1e-6, 1e-9, 1e3, 1e6)


def _pool(b):
    """Every number a sentence is allowed to cite: KPI values and deltas, table cells, column totals, row counts."""
    vals = []

    def add(x):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            vals.append(abs(float(x)))
    for k in b.get("kpis") or []:
        add(k.get("value"))
        add(k.get("delta"))
    for t in b.get("tables") or []:
        cols, rows = t.get("columns") or [], t.get("rows") or []
        add(len(rows))
        add(t.get("row_count_total"))
        for r in rows:
            for v in r:
                add(v)
        for i, c in enumerate(cols):
            if c.get("total") == "sum":
                add(sum(r[i] for r in rows if isinstance(r[i], (int, float))))
    return vals


def number_claims(text):
    """(token, value, decimals, unit, hard) for each number in prose. 'hard' = carries $, %, x, pp, k, mn, mm or bn."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = _STRIP.sub(" ", text)
    out = []
    for m in _NUM.finditer(text):
        dollar, num, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        digits = num.replace(",", "")
        dec = len(digits.split(".")[1]) if "." in digits else 0
        val = float(digits)
        hard = bool(dollar or unit)
        if not hard and dec == 0 and val < 10:
            continue                                  # "two segments", "3 accounts"
        out.append((m.group(0).strip(), val, dec, unit, hard))
    return out


def claim_problems(b, text=None):
    """Numbers in prose that no bundle table or KPI backs. Returns [(severity, message)].
    With text=None the bundle's own headline and findings are checked."""
    texts = [("answer", text)] if text is not None else (
        [("headline", b.get("headline") or "")] + [(f"findings[{i}]", f.get("text", "")) for i, f in enumerate(b.get("findings") or [])])
    pool = _pool(b)
    problems = []
    for where, s in texts:
        for token, val, dec, unit, hard in number_claims(s):
            scales = _SCALES.get(unit, _MONEY_SCALES)
            tol = 0.5 * 10 ** -dec + 1e-9
            if any(abs(x * sc - val) <= tol for x in pool for sc in scales):
                continue
            problems.append(("error" if hard else "warning",
                             f"{where}: '{token}' is not backed by any bundle table cell or KPI. Put the figure in a "
                             f"table or KPI (derived figures go in a derived table) or remove it from the text."))
    return problems


def answer_problems(b, text):
    """Check a chat answer against the bundle it accompanies: it must open with the bundle headline
    and every figure it cites must be in the bundle."""
    probs = []
    norm = lambda s: " ".join((s or "").split()).lower()
    if b.get("headline") and norm(b["headline"]) not in norm(text):
        probs.append(("error", "answer does not contain the bundle headline verbatim; copy it from the bundle."))
    probs.extend(claim_problems(b, text))
    return probs


def warnings(b):
    w = []
    meta = b.get("meta") or {}
    for key in ("as_of", "currency", "period"):
        if not meta.get(key):
            w.append(f"meta.{key} is empty; every answer should state it.")
    if not meta.get("sources"):
        w.append("meta.sources is empty.")
    if not b.get("headline"):
        w.append("no headline.")
    for t in b.get("tables") or []:
        for i, c in enumerate(t.get("columns") or []):
            if c.get("type") == "percent":
                vals = [abs(r[i]) for r in t.get("rows") or [] if isinstance(r[i], (int, float))]
                if vals and sum(v > 1.5 for v in vals) > len(vals) / 2:
                    w.append(f"table '{t['id']}', column '{c['name']}': percent values look like whole numbers; percent columns hold fractions (0.18 = 18%).")
    for ki, k in enumerate(b.get("kpis") or []):
        if not k.get("source"):
            w.append(f"kpis[{ki}] ('{k.get('label')}') has no source; add source {{table, column, row}} so it is tied to a table cell.")
    w.extend(m for sev, m in claim_problems(b) if sev == "warning")
    return w


# ---------------------------------------------------------------- formatting

def fmt(value, ctype="number", scale_note=None):
    """Format a value for display. Negatives in parentheses; zero as a dash."""
    if value is None or value == "":
        return "–"
    if ctype in ("text", "date"):
        return str(value)
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if x == 0:
        return "–"
    neg = x < 0
    a = abs(x)
    if ctype == "integer":
        s = f"{a:,.0f}"
    elif ctype == "number":
        s = f"{a:,.1f}"
    elif ctype == "currency":
        s = f"${a:,.0f}"
    elif ctype == "currency_mm":
        s = f"${a:,.1f}"
    elif ctype == "percent":
        s = f"{a * 100:,.1f}%"
    elif ctype == "multiple":
        s = f"{a:,.1f}x"
    else:
        s = f"{a:,.1f}"
    return f"({s})" if neg else s


def excel_numfmt(ctype):
    return {
        "integer": '#,##0;(#,##0);"–"',
        "number": '#,##0.0;(#,##0.0);"–"',
        "currency": '$#,##0;($#,##0);"–"',
        "currency_mm": '$#,##0.0;($#,##0.0);"–"',
        "percent": '0.0%;(0.0%);"–"',
        "multiple": '0.0"x";(0.0"x");"–"',
        "date": "yyyy-mm-dd",
    }.get(ctype, "General")


def col_type(table, name):
    for c in table["columns"]:
        if c["name"] == name:
            return c.get("type", "text")
    return "text"


def table_by_id(b, tid):
    for t in b.get("tables", []):
        if t["id"] == tid:
            return t
    return None


def col_values(table, name):
    idx = [c["name"] for c in table["columns"]].index(name)
    return [r[idx] for r in table["rows"]]


def provenance_label(p):
    return {"governed": "Governed", "derived": "Derived", "scenario": "Scenario – illustrative assumptions"}.get(p, "")


def main():
    args = sys.argv[1:]
    text_file = None
    if "--check-text" in args:
        i = args.index("--check-text")
        text_file = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    if len(args) != 1 or (("--check-text" in sys.argv) and not text_file):
        print("usage: bundle.py bundle.json [--check-text answer.md]", file=sys.stderr)
        return 2
    b = load(args[0])
    errs = validate(b)
    answer = None
    if text_file:
        raw = open(text_file, "rb").read()
        try:
            answer = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            answer = raw.decode("cp1252", errors="replace")      # Windows editors
        errs += [m for sev, m in answer_problems(b, answer) if sev == "error"]
    if errs:
        print("PROBLEMS:")
        for e in errs:
            print(" -", e)
        return 1
    print("OK")
    print(f"Bundle ID: {fingerprint(b)}")
    for w in warnings(b):
        print(" warning:", w)
    if text_file:
        for sev, m in answer_problems(b, answer):
            if sev == "warning":
                print(" warning:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
