#!/usr/bin/env python3
"""The diagnosis admission gate: refuse any statement the payload does not support.

Usage: python validate_finance_diagnosis.py --payload work/finance_payload.json --diagnosis work/diagnosis.json
Exit 0 = admitted (warnings may be listed), 1 = refused with the reasons. Fix the diagnosis, never the payload.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance.diagnosis import validate_diagnosis   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--diagnosis", required=True)
    a = ap.parse_args()
    with open(a.payload, encoding="utf-8") as fh:
        payload = json.load(fh)
    with open(a.diagnosis, encoding="utf-8") as fh:
        diag = json.load(fh)
    errs, warns = validate_diagnosis(payload, diag)
    if errs:
        print(json.dumps({"status": "REFUSED", "reasons": errs[:60], "warnings": warns[:20], "count": len(errs)}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ADMITTED", "findings": len(diag.get("findings") or []), "conclusions": len((diag.get("readout") or {}).get("conclusions") or []),
                      "warnings": warns}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
