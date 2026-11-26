#!/usr/bin/env python3
"""Save a sql-exec result to work/raw/<name>.json without retyping it.

    python save_result.py <name> --file <tool-results file>     # the tool saved a large result to a file
    python save_result.py <name> --query-id <query_id>          # the result came back inline (Claude Code)

--file copies the saved result. --query-id finds the result in the Claude Code session transcripts
(~/.claude/projects/**/*.jsonl, newest first) by its query_id and writes it byte for byte. Either way the result is
parsed, and refused when it is not a sql-exec result or its row count does not match what it declares.
If neither works (no transcript in this environment), write the inline result verbatim with the file tool; never edit,
reformat or retype a number. The build's reconciliation gates refuse a result that was altered.
Exit codes: 0 saved, 1 refused.
"""
import argparse
import glob
import json
import os
import shutil
import sys

NAMES = ("pl", "pl_governed", "bs", "cf", "arr", "customers", "bookings", "pipeline", "hosting", "revolver")


def refuse(msg):
    print(json.dumps({"status": "REFUSED", "reason": msg}))
    sys.exit(1)


def parse(text):
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    rs = obj["result_set"]
    n = rs["resultSetMetaData"].get("numRows")
    if n is not None and n != len(rs["data"]):
        raise ValueError(f"declares {n} rows but holds {len(rs['data'])}")
    return obj


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def from_transcripts(query_id):
    needle = f'"query_id":"{query_id}"'
    roots = [os.path.join(os.path.expanduser("~"), ".claude", "projects")]
    files = sorted({f for r in roots for f in glob.glob(os.path.join(r, "**", "*.jsonl"), recursive=True)}, key=os.path.getmtime, reverse=True)
    for f in files[:50]:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if query_id not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                for s in strings(rec):
                    i = s.find("{" + needle)
                    if i >= 0:
                        return s[i:]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", choices=NAMES)
    ap.add_argument("--file")
    ap.add_argument("--query-id")
    ap.add_argument("--work", default="work")
    a = ap.parse_args()
    out = os.path.join(a.work, "raw", f"{a.name}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if a.file:
        text = open(a.file, encoding="utf-8").read()
    elif a.query_id:
        text = from_transcripts(a.query_id)
        if text is None:
            refuse(f"query_id {a.query_id} not found in the session transcripts: write the inline result verbatim to {out}")
    else:
        refuse("give --file or --query-id")
    try:
        obj = parse(text)
    except (ValueError, KeyError, TypeError) as exc:
        refuse(f"not a complete sql-exec result: {exc}")
    if a.query_id and obj.get("query_id") != a.query_id:
        refuse("the result found carries a different query_id")
    if a.file:
        shutil.copyfile(a.file, out)
    else:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
    meta = obj["result_set"]["resultSetMetaData"]
    print(json.dumps({"status": "SAVED", "out": out, "query_id": obj.get("query_id"), "rows": len(obj["result_set"]["data"]),
                      "columns": [c["name"] for c in meta["rowType"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
