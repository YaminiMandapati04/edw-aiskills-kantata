#!/usr/bin/env python3
"""Read-only SQL guard.

Accepts a SQL string and exits 0 only if it is a single read-only statement
(SELECT / WITH ... SELECT / SHOW / DESCRIBE / DESC / EXPLAIN) containing no
write, DDL, privilege, or session-changing keywords outside string literals
and comments.

Usage:
    python sql_guard.py "SELECT 1"
    python sql_guard.py --file query.sql
    echo "SELECT 1" | python sql_guard.py -

Prints one JSON object: {"ok": bool, "reason": str, "warnings": [str, ...]}
Exit code 0 = ok, 1 = rejected, 2 = usage error.

This is a safety net, not a substitute for a read-only database role. It is
deliberately conservative: when in doubt it rejects.
"""
import argparse
import json
import re
import sys

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}

# Hard-write keywords are rejected anywhere in the statement. Words that are also
# legitimate function/column names (REPLACE, GET, COMMENT, SET, LIST ...) are NOT
# listed: they cannot start an allowed statement, and multi-statement input is
# already rejected, so they are blocked by the first-keyword check instead.
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE", "ALTER",
    "GRANT", "REVOKE", "COPY", "PUT", "CALL", "EXECUTE", "USE", "UNDROP",
    "BEGIN", "COMMIT", "ROLLBACK",
}


# A table-qualified metric whose name ends in a window other than MTD: REVENUE_YTD, TOTAL_PY_LTM, TOTAL_BUDGET_QTD,
# TOTAL_BOOKINGS_PYYTD, WEIGHTED_PIPELINE_VALUE_QTD ... (an alias such as REVENUE_FYTD is not table-qualified and passes).
WINDOW_METRIC = re.compile(r"\.\s*([A-Za-z_][A-Za-z0-9_]*?_(?:PY_|BUDGET_|PY)?(?:QTD|YTD|LTM))\b", re.IGNORECASE)

def strip_literals_and_comments(sql: str) -> str:
    """Blank out comments, single-quoted strings, double-quoted identifiers and
    $$ blocks so keyword scanning only sees real SQL tokens."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if c == "-" and nxt == "-":                    # line comment
            while i < n and sql[i] != "\n":
                i += 1
            out.append(" ")
        elif c == "/" and nxt == "/":                  # Snowflake // comment
            while i < n and sql[i] != "\n":
                i += 1
            out.append(" ")
        elif c == "/" and nxt == "*":                  # block comment
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif c == "$" and nxt == "$":                  # $$ ... $$ block
            end = sql.find("$$", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ' ' ")
        elif c in ("'", '"'):                          # quoted string / identifier
            q = c
            i += 1
            while i < n:
                if sql[i] == q:
                    if i + 1 < n and sql[i + 1] == q:  # doubled quote escape
                        i += 2
                        continue
                    break
                if sql[i] == "\\" and q == "'":
                    i += 1
                i += 1
            i += 1
            out.append(" ' ' " if q == "'" else " _ID_ ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check(sql: str) -> dict:
    warnings = []
    if not sql or not sql.strip():
        return {"ok": False, "reason": "Empty statement.", "warnings": warnings}

    clean = strip_literals_and_comments(sql)

    # Single statement: allow one optional trailing semicolon only.
    body = clean.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        return {"ok": False, "reason": "Multiple statements detected; run one statement per call.",
                "warnings": warnings}
    if not body:
        return {"ok": False, "reason": "Statement is empty after removing comments.", "warnings": warnings}

    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", body)
    first = tokens[0].upper() if tokens else ""
    if first not in ALLOWED_FIRST:
        return {"ok": False,
                "reason": f"Statement starts with '{first or body[:20]}'; only "
                          f"{', '.join(sorted(ALLOWED_FIRST))} are allowed.",
                "warnings": warnings}

    upper_tokens = [t.upper() for t in tokens]
    for t in upper_tokens:
        if t.startswith("SYSTEM$"):
            return {"ok": False, "reason": f"System function '{t}' is not allowed.", "warnings": warnings}
        if t in FORBIDDEN:
            return {"ok": False, "reason": f"Forbidden keyword '{t}' found; this skill is read-only.",
                    "warnings": warnings}

    # Calculation rule (FINANCE_ANALYTICS, GTM_ANALYTICS): period values are built by summing the _MTD metric over the
    # months in scope. The views' own _QTD / _YTD / _LTM metrics (and their PY / BUDGET twins) are never queried: each is
    # tagged to the chart-of-accounts keys present in one month, so keys that exist in an earlier month but not in the
    # month queried drop out and the window comes out incomplete; rolling them up is just as wrong.
    if {"FINANCE_ANALYTICS", "GTM_ANALYTICS"} & set(upper_tokens):
        bad = sorted({m.group(1).upper() for m in WINDOW_METRIC.finditer(body)})
        if bad:
            return {"ok": False,
                    "reason": f"Window metric(s) {', '.join(bad)} are not allowed: query the _MTD metric and sum it over the "
                              "months in scope (QTD = the quarter's months, YTD = every month of the financial year so far, "
                              "LTM = the last twelve months). The view's own QTD / YTD / LTM fields are incomplete when "
                              "aggregated.",
                    "warnings": warnings}

    # Non-blocking hygiene warnings
    if first in ("SELECT", "WITH"):
        has_limit = "LIMIT" in upper_tokens or "TOP" in upper_tokens or "FETCH" in upper_tokens
        has_agg = any(t in upper_tokens for t in
                      ("SUM", "COUNT", "AVG", "MIN", "MAX", "SEMANTIC_VIEW", "GROUP", "MEDIAN", "STDDEV"))
        if re.search(r"SELECT\s+\*", body, flags=re.IGNORECASE) and not has_limit:
            warnings.append("SELECT * without LIMIT: list explicit columns and add a LIMIT.")
        if not has_limit and not has_agg:
            warnings.append("No LIMIT and no aggregation: this could return a very large result.")
        if "WHERE" not in upper_tokens and "SEMANTIC_VIEW" not in upper_tokens and not has_limit:
            warnings.append("No WHERE filter or LIMIT: consider pinning a date window.")
    return {"ok": True, "reason": "Single read-only statement.", "warnings": warnings}


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only SQL guard")
    ap.add_argument("sql", nargs="?", help="SQL text, or '-' to read stdin")
    ap.add_argument("--file", help="Read SQL from a file")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            sql = fh.read()
    elif args.sql == "-":
        sql = sys.stdin.read()
    elif args.sql is not None:
        sql = args.sql
    else:
        ap.print_usage(sys.stderr)
        return 2

    result = check(sql)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
