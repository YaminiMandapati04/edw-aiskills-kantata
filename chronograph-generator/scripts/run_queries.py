#!/usr/bin/env python3
"""Run the nine written Chronograph queries verbatim and save each full result to work/raw/<name>.json.

    python run_queries.py [--work work] [--connection default] [--warehouse <WH>]

For Cortex Code in Snowsight (and any environment with a Snowflake connection in ~/.snowflake/connections.toml).
It reads work/queries/manifest.json, refuses any .sql file whose text no longer matches the SHA-256 the manifest
recorded (the file must be run exactly as chronograph_queries.py wrote it), runs it on the connection as configured,
and writes the complete result in the sql-exec shape the build reads ({"query_id", "result_set": {"resultSetMetaData",
"data"}}), with the real Snowflake query id. Values are written as the connector returns them (numbers as exact
decimal strings, dates as ISO dates); nothing is rounded, filtered or re-keyed.

It never changes role or database. --warehouse is only for a warehouse the user named; without it the connection's
default warehouse is used. If no usable warehouse is active, it stops and lists the warehouses the role can see.
Exit codes: 0 all saved, 1 refused.
"""
import argparse
import datetime as dt
import decimal
import hashlib
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def refuse(msg, **extra):
    print(json.dumps({"status": "REFUSED", "reason": msg, **extra}, indent=2, ensure_ascii=False, default=str))
    sys.exit(1)


def cell(v):
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, decimal.Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="work")
    ap.add_argument("--connection", default="default", help="connection name in ~/.snowflake/connections.toml")
    ap.add_argument("--warehouse", help="only a warehouse the user named; default: the connection's own")
    a = ap.parse_args()
    man_path = os.path.join(a.work, "queries", "manifest.json")
    if not os.path.exists(man_path):
        refuse(f"{man_path} is missing: run chronograph_queries.py first")
    man = json.load(open(man_path, encoding="utf-8"))
    import snowflake.connector
    try:
        con = snowflake.connector.connect(connection_name=a.connection)
    except Exception as exc:                                    # an auth or connection failure stops the run
        refuse(f"cannot connect with connection {a.connection!r}: {exc}")
    cur = con.cursor()
    try:
        if a.warehouse:
            cur.execute(f'USE WAREHOUSE "{a.warehouse.replace(chr(34), "")}"')
        wh = cur.execute("SELECT CURRENT_WAREHOUSE()").fetchone()[0]
        role = cur.execute("SELECT CURRENT_ROLE()").fetchone()[0]
        if not wh:
            usable = [r[0] for r in cur.execute("SHOW WAREHOUSES").fetchall()]
            refuse("no warehouse is active for this connection; ask the user which warehouse to use and rerun with --warehouse",
                   warehouses_visible=usable)
        saved = {}
        for name, q in man["queries"].items():
            sql = open(q["sql"], encoding="utf-8").read().rstrip("\n")
            if hashlib.sha256(sql.encode("utf-8")).hexdigest() != q["sha256"]:
                refuse(f"{q['sql']} differs from the query chronograph_queries.py wrote; rerun chronograph_queries.py, never edit a query")
            try:
                cur.execute(sql)
            except Exception as exc:
                refuse(f"query {name} failed: {exc}", warehouse=wh, role=role)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if not rows:
                refuse(f"query {name} returned no rows", query_id=cur.sfqid)
            obj = {"query_id": cur.sfqid,
                   "result_set": {"resultSetMetaData": {"numRows": len(rows), "rowType": [{"name": c} for c in cols]},
                                  "data": [[cell(v) for v in r] for r in rows]}}
            with open(q["raw"], "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False)
            saved[name] = {"rows": len(rows), "query_id": cur.sfqid}
    finally:
        con.close()
    print(json.dumps({"status": "SAVED", "warehouse": wh, "role": role, "results": saved,
                      "next": "python build_chronograph.py --work " + a.work + " --out outputs"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
