#!/usr/bin/env python3
"""Local test mode: analyse an uploaded Excel workbook when no warehouse connection exists.

Each sheet is loaded as a table named after the sheet (the view's logical-table
names: BOOKING_LINES, OPPORTUNITY_LINE_ITEM, PIPELINE_TARGET, ...) into a
local SQLite database, and queried with ordinary read-only SQL. SQLite has no
SEMANTIC_VIEW(), so the metric definitions are applied by hand; the formulas are
in references/local-mode.md. Results are NOT governed: label them local test data.

Usage:
    python local_data.py check  book.xlsx [book2.xlsx ...]      # structure vs the GTM view
    python local_data.py load   book.xlsx [...] --db local.db   # build the database
    python local_data.py schema --db local.db                   # tables, columns, row counts
    python local_data.py query  --db local.db --file q.sql      # or: ... query --db local.db "SELECT ..."
                                [--limit 100] [--json]

Rules: row 1 of every sheet is the header; sheets whose name starts with README or
"_" are ignored; dates are stored as ISO text (YYYY-MM-DD); TRUE/FALSE become 1/0.
Queries go through sql_guard.py and run on a read-only connection.
"""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys

import sql_guard

# Required sheets and columns per view (minimum for the standard questions).
# Extra sheets and columns are fine; missing optional ones only limit what can be asked.
SPEC = {
    "GTM_ANALYTICS": {
        "required": {
            "BOOKING_LINES": ["BOOKINGS_DATE", "BOOKING_METRIC", "PRODUCT", "SUBSCRIPTION_TYPE", "SOURCE_ORDER",
                              "COMPANY_NAME", "SUBSIDIARY_NAME", "BOOKING_ACV_USD"],
            "OPPORTUNITY_LINE_ITEM": ["OPPORTUNITY_ID", "OPPORTUNITY_NAME", "OWNER_NAME", "PRODUCT", "DEAL_SOURCE",
                                      "STATUS", "STAGE_NAME", "STAGE_ORDER", "CLOSE_DATE", "EXPECTED_CLOSE_QUARTER",
                                      "ACV_USD", "TCV_USD", "PROBABILITY"],
        },
        "optional": {
            "OPPORTUNITY_STAGE_HISTORY": ["OPPORTUNITY_ID", "STAGE_NAME", "STAGE_CHANGE_NO", "STAGE_START_DATE",
                                          "IS_CURRENT_STAGE", "IS_OPEN", "OWNER_NAME", "DAYS_IN_STAGE"],
            "PIPELINE_TARGET": ["TARGET_QUARTER", "PRODUCT", "DEAL_SOURCE", "PIPELINE_TARGET_USD"],
        },
    },
}


def clean_name(s):
    s = re.sub(r"[^0-9A-Za-z_]+", "_", str(s).strip()).strip("_").upper()
    return s or "COL"


def sheet_tables(path):
    """Yield (table_name, header, rows) for each usable sheet of a workbook."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        if ws.title.upper().startswith("README") or ws.title.startswith("_"):
            continue
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            continue
        keep = [i for i, h in enumerate(header) if h not in (None, "")]
        names, seen = [], {}
        for i in keep:
            n = clean_name(header[i])
            seen[n] = seen.get(n, 0) + 1
            names.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
        rows = []
        for r in it:
            if r is None or all(c is None for c in r):
                continue
            rows.append(tuple(_cell(r[i]) if i < len(r) else None for i in keep))
        yield clean_name(ws.title), names, rows
    wb.close()


def _cell(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ") if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def cmd_check(a):
    found = {}
    for path in a.workbooks:
        for table, names, rows in sheet_tables(path):
            found[table] = (names, len(rows), os.path.basename(path))
    print(f"Sheets found: {', '.join(sorted(found)) or 'none'}")
    ok_any = False
    for view, spec in SPEC.items():
        missing_req, notes = [], []
        for table, cols in spec["required"].items():
            if table not in found:
                missing_req.append(f"sheet {table}")
            else:
                miss = [c for c in cols if c not in found[table][0]]
                if miss:
                    missing_req.append(f"{table}: {', '.join(miss)}")
        for table, cols in spec["optional"].items():
            if table not in found:
                notes.append(f"optional sheet {table} absent")
            else:
                miss = [c for c in cols if c not in found[table][0]]
                if miss:
                    notes.append(f"{table}: missing {', '.join(miss)}")
        relevant = any(t in found for t in list(spec["required"]) + list(spec["optional"]))
        if not relevant:
            continue
        ok = not missing_req
        ok_any = ok_any or ok
        print(f"\n{view}: {'READY' if ok else 'INCOMPLETE'}")
        for m in missing_req:
            print(f"  missing required: {m}")
        for n in notes:
            print(f"  note: {n}")
    if not ok_any:
        print("\nNo view's required sheets are all present. See references/local-mode.md for the layout, "
              "or run make_sample_data.py to generate example workbooks.")
        return 1
    return 0


def cmd_load(a):
    if os.path.exists(a.db):
        os.remove(a.db)
    con = sqlite3.connect(a.db)
    seen = {}
    for path in a.workbooks:
        for table, names, rows in sheet_tables(path):
            if table in seen:
                print(f"skipping duplicate sheet {table} in {os.path.basename(path)} (already loaded from {seen[table]})")
                continue
            seen[table] = os.path.basename(path)
            con.execute(f'CREATE TABLE "{table}" (' + ", ".join(f'"{n}"' for n in names) + ")")
            con.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" * len(names))})', rows)
            print(f"loaded {table:<26} {len(rows):>7} rows  {len(names):>2} columns  ({os.path.basename(path)})")
    con.commit()
    con.close()
    print(f"\nWrote {a.db}. Local test data: results are not governed semantic-view output.")
    return 0


def _ro(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def cmd_schema(a):
    con = _ro(a.db)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
        print(f"{t} ({n} rows): {', '.join(cols)}")
    return 0


def cmd_query(a):
    if a.file:
        sql = open(a.file, "r", encoding="utf-8").read()
    elif a.sql == "-":
        sql = sys.stdin.read()
    elif a.sql:
        sql = a.sql
    else:
        print("give SQL, '-' or --file", file=sys.stderr)
        return 2
    g = sql_guard.check(sql)
    if not g["ok"]:
        print("REJECTED by sql_guard:", g["reason"])
        return 1
    for w in g["warnings"]:
        print("warning:", w, file=sys.stderr)
    if re.search(r"\bSEMANTIC_VIEW\b", sql, flags=re.I):
        print("SEMANTIC_VIEW() does not exist locally. Use plain SQL over the loaded tables "
              "(formulas in references/local-mode.md).")
        return 1
    con = _ro(a.db)
    try:
        cur = con.execute(sql)
    except sqlite3.Error as e:
        print("SQL error:", e)
        return 1
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(a.limit + 1)
    capped = len(rows) > a.limit
    rows = rows[:a.limit]
    if a.json:
        print(json.dumps({"columns": cols, "rows": rows, "row_count": len(rows), "capped": capped}, default=str))
    else:
        print(" | ".join(cols))
        for r in rows:
            print(" | ".join("" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in r))
        print(f"({len(rows)} rows{', capped at ' + str(a.limit) if capped else ''})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("workbooks", nargs="+")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("load")
    p.add_argument("workbooks", nargs="+")
    p.add_argument("--db", required=True)
    p.set_defaults(fn=cmd_load)
    p = sub.add_parser("schema")
    p.add_argument("--db", required=True)
    p.set_defaults(fn=cmd_schema)
    p = sub.add_parser("query")
    p.add_argument("sql", nargs="?")
    p.add_argument("--db", required=True)
    p.add_argument("--file")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_query)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
