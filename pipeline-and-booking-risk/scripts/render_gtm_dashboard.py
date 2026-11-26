#!/usr/bin/env python3
"""Render the GTM page from a saved payload plus the admitted AI reviews (the second half of the run, after the
diagnosis is written against the payload that build_gtm_dashboard.py --payload-out saved).

Usage:
  python render_gtm_dashboard.py --payload work/gtm_payload.json --diagnosis work/diagnosis_qtd.json [--out outputs/yes_energy_pipeline_risk_readout.html]
                                 [--allow-missing-review]

Each diagnosis passes the admission gate (scripts/gtm/diagnosis.py) or nothing is written. The opening view (the
payload's primary lens, normally Quarter to date vs Prior quarter) needs an admitted review unless
--allow-missing-review; views without one show the engine reading and say "This view not AI reviewed".
Prints one JSON line. Exit 0 rendered, 1 refused.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from gtm import RENDERER_VERSION                        # noqa: E402
from gtm.common import BuildError                       # noqa: E402
from gtm.diagnosis import admit                         # noqa: E402
from gtm.render import render                           # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--diagnosis", nargs="*", default=[], help="diagnosis.json file(s), one per view, written against this payload")
    ap.add_argument("--allow-missing-review", action="store_true", help="publish without the opening view's review (the page says which views are not AI reviewed)")
    ap.add_argument("--out", default=os.path.join(SKILL, "outputs", "yes_energy_pipeline_risk_readout.html"))
    a = ap.parse_args()
    try:
        with open(a.payload, encoding="utf-8") as fh:
            p = json.load(fh)
        review = admit(p, a.diagnosis, a.allow_missing_review)
        n = render(p, a.out)
    except BuildError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "bytes": n, "renderer": RENDERER_VERSION, "as_of": p["meta"]["as_of"]["label"],
                      "opens_on": p["meta"]["primary_lens"]["id"], "review": review}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
