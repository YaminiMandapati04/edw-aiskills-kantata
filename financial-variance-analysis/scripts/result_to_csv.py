#!/usr/bin/env python3
"""Turn a saved Snowflake MCP sql-exec result into a CSV chunk for analyze_finance.py, refusing any cut-off result.

    python result_to_csv.py table  <result.json|txt> <out.csv> --expect-rows N
    python result_to_csv.py blob   <result.json|txt> <out.csv> --cols C1,C2,... --expect-rows N
    python result_to_csv.py slices <out.csv> --cols C1,C2,... --expect-rows N <slice1> <slice2> ...

table   a plain result set (rows x columns).
blob    one row, one value: rows packed with LISTAGG (fields TAB-separated, rows NEWLINE-separated).
slices  base64 of zlib-compressed packed rows, returned in order as several one-value results.

Large statement extracts are why the earlier runs narrowed the query to a few accounts or collapsed it to
statement lines. Never do that: run the full account-grain query in period chunks, and for each chunk pass
the row count the probe returned (SELECT COUNT(*) over the same query) as --expect-rows. Any mismatch
(a truncated multi-partition result, a dropped slice) is refused and no CSV is written.
Exit codes: 0 written, 1 refused.
"""
import argparse
import base64
import csv
import json
import sys
import zlib


def refuse(msg):
    print(json.dumps({"status": "REFUSED", "reason": msg}))
    sys.exit(1)


def load(path):
    raw = open(path, encoding="utf-8").read()
    try:
        return json.loads(raw[raw.find("{"):])["result_set"]
    except (ValueError, KeyError) as exc:
        refuse(f"{path}: not a sql-exec result ({exc})")


def single_value(rs, path):
    data = rs["data"]
    if len(data) != 1 or len(data[0]) != 1 or data[0][0] is None:
        refuse(f"{path}: expected one row with one value, got {len(data)} row(s)")
    return data[0][0]


def write(out, cols, rows, expect):
    bad = [i for i, r in enumerate(rows) if len(r) != len(cols)]
    if bad:
        refuse(f"{len(bad)} row(s) with the wrong field count (first at {bad[0]})")
    if len(rows) != expect:
        refuse(f"{len(rows)} row(s) but the probe counted {expect}: truncated result; halve the period chunk and re-run")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows([[None if v == "" else v for v in r] for r in rows])
    print(json.dumps({"status": "OK", "out": out, "rows": len(rows), "cols": cols}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["table", "blob", "slices"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--cols", help="column names for blob / slices, in packed order")
    ap.add_argument("--expect-rows", type=int, required=True, help="row count from the COUNT(*) probe of the same chunk")
    a = ap.parse_args()
    if a.mode == "table":
        if len(a.paths) != 2:
            refuse("table mode takes <result> <out.csv>")
        rs = load(a.paths[0])
        meta = rs["resultSetMetaData"]
        declared, parts = meta.get("numRows"), meta.get("partitionInfo") or []
        if declared is not None and len(rs["data"]) != declared:
            refuse(f"data has {len(rs['data'])} rows but the result declares {declared}: truncated")
        if len(parts) > 1 and sum(p.get("rowCount", 0) for p in parts) != len(rs["data"]):
            refuse("partition row counts do not match the returned rows: truncated")
        write(a.paths[1], [c["name"] for c in meta["rowType"]], [[("" if v is None else v) for v in r] for r in rs["data"]], a.expect_rows)
        return 0
    if not a.cols:
        refuse("--cols is required for blob and slices")
    cols = a.cols.split(",")
    if a.mode == "blob":
        if len(a.paths) != 2:
            refuse("blob mode takes <result> <out.csv>")
        text = single_value(load(a.paths[0]), a.paths[0])
        out = a.paths[1]
    else:
        out, slices = a.paths[0], a.paths[1:]
        if not slices:
            refuse("slices mode needs at least one slice file")
        try:
            text = zlib.decompress(base64.b64decode("".join(single_value(load(p), p) for p in slices))).decode("utf-8")
        except (ValueError, zlib.error) as exc:
            refuse(f"slices do not decode ({exc}): a slice is missing or out of order")
    write(out, cols, [line.split("\t") for line in text.split("\n") if line != ""], a.expect_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
