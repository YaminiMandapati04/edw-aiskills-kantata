#!/usr/bin/env python3
"""The standing account exclusion for ARR_ANALYTICS: Kantata's internal test accounts (config/excluded_accounts.json).

    python account_scope.py clause                 # print the WHERE fragment to add to every ARR_ANALYTICS query
    python account_scope.py check --file q.sql     # exit 0 only if the query carries the exclusion (run after sql_guard.py)
    python account_scope.py check "SELECT ..."

Every SEMANTIC_VIEW(... ARR_ANALYTICS ...) query must carry, inside its WHERE:

    AND (CUSTOMER.ACCOUNT_ID IS NULL OR CUSTOMER.ACCOUNT_ID NOT IN ('<id>', ...))

with every listed ID (null-safe: a bare NOT IN would also drop rows with no account). The check refuses a query that
leaves an ID out, and a query that excludes accounts by name (NOT LIKE / NOT ILIKE / NOT IN on ACCOUNT_NAME): the
exclusion is by ID only, so real customers whose names contain 'test' stay in. Looking a customer up by name is fine. DESCRIBE / SHOW statements and queries that do not read
ARR_ANALYTICS pass unchanged.
Prints one JSON object: {"ok": bool, "reason": str}. Exit codes: 0 ok, 1 refused, 2 usage error.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "config", "excluded_accounts.json")
SF_ID = re.compile(r"^[A-Za-z0-9]{18}$")


def load(path=CONFIG):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    ids = cfg["account_ids"]
    bad = [i for i in ids if not SF_ID.match(str(i))]
    if bad:
        raise ValueError(f"{path}: not 18-character Salesforce account IDs: {', '.join(map(str, bad))}")
    return cfg["column"], ids


def clause(path=CONFIG):
    col, ids = load(path)
    return f"AND ({col} IS NULL OR {col} NOT IN (" + ", ".join(f"'{i}'" for i in ids) + "))"


def check(sql, path=CONFIG):
    col, ids = load(path)
    flat = re.sub(r"\s+", " ", sql).strip()
    up = flat.upper()
    if re.match(r"^(DESCRIBE|DESC|SHOW)\b", up) or "ARR_ANALYTICS" not in up:
        return {"ok": True, "reason": "no ARR_ANALYTICS data read; exclusion not needed"}
    if re.search(r"ACCOUNT_NAME\s+NOT\s+(I?LIKE|IN)\b", up) or re.search(r"NOT\s*\(?\s*[\w.]*ACCOUNT_NAME\s+I?LIKE", up):
        return {"ok": False, "reason": "accounts are excluded by ID only (config/excluded_accounts.json), never by name: remove the NOT LIKE / NOT ILIKE / NOT IN on ACCOUNT_NAME (real customers whose names contain 'test' stay in)"}
    m = re.search(re.escape(col.upper()) + r"\s+IS\s+NULL\s+OR\s+" + re.escape(col.upper()) + r"\s+NOT\s+IN\s*\(([^)]*)\)", up)
    if not m:
        return {"ok": False, "reason": f"the query reads ARR_ANALYTICS without the standing test-account exclusion; add inside SEMANTIC_VIEW's WHERE: {clause(path)}"}
    listed = {v.strip().strip("'\"").upper() for v in m.group(1).split(",")}
    missing = [i for i in ids if i.upper() not in listed]
    if missing:
        return {"ok": False, "reason": f"the exclusion leaves out {len(missing)} listed account(s); use the full clause: {clause(path)}"}
    return {"ok": True, "reason": f"excludes the {len(ids)} internal test accounts"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clause")
    c = sub.add_parser("check")
    c.add_argument("sql", nargs="?")
    c.add_argument("--file")
    a = ap.parse_args()
    if a.cmd == "clause":
        print(clause())
        return 0
    if a.file:
        sql = open(a.file, encoding="utf-8").read()
    elif a.sql:
        sql = sys.stdin.read() if a.sql == "-" else a.sql
    else:
        print(json.dumps({"ok": False, "reason": "give the SQL or --file"}))
        return 2
    res = check(sql)
    print(json.dumps(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
