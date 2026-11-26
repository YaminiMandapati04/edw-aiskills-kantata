#!/usr/bin/env python3
"""Check a finance payload against its invariants (bridge reconciles, statement foots, tiers recomputed,
every figure in generated prose resolves to its path, hash matches).

Usage: python validate_finance_payload.py work/finance_payload.json
Exit 0 = OK, 1 = problems listed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance.validate import validate_payload   # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        payload = json.load(fh)
    errs = validate_payload(payload)
    if errs:
        print(json.dumps({"status": "FAILED", "problems": errs[:60], "count": len(errs)}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "OK", "contract": payload["contract_version"], "analysis_hash": payload["analysis_hash"], "lenses": sorted(payload["lenses"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
