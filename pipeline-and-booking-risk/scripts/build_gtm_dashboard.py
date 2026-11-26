#!/usr/bin/env python3
"""Build the pipeline risk readout from governed GTM_ANALYTICS extracts (the live path).

    python build_gtm_dashboard.py --extracts work/gtm-live [--out outputs/pipeline_risk_readout.html]
                                  [--as-of YYYY-MM] [--window MTD|QTD|YTD|LTM]
                                  [--scope-label "<product>"] [--source PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS]
                                  [--payload-out work/gtm_payload.json] [--expect-as-of YYYY-MM] [--previous auto|none|<page.html>]
                                  [--diagnosis work/diagnosis_qtd.json ...] [--allow-missing-review]

--extracts is the folder of saved SEMANTIC_VIEW results named as in references/dashboards.md §2
(sql-exec JSON or CSV). The loader (scripts/gtm/live.py) refuses capped, overlapping or gapped
extracts; the engine (scripts/gtm/engine.py) computes every figure and ties the lines to the
KPI marts; the renderer (artifacts/gtm_analytics/) displays the payload and computes nothing.
Prints one JSON line.

AI review (references/diagnosis.md): the opening view (normally Quarter to date vs Prior quarter) needs an admitted
diagnosis before the page is published. A first run without --diagnosis writes the payload (--payload-out) and no
page; write the diagnosis against that payload (gtm_brief.py, validate_gtm_diagnosis.py), then pass --diagnosis here
or render the saved payload with render_gtm_dashboard.py. --allow-missing-review publishes the engine reading alone,
and the page says "This view not AI reviewed".

Recurring run (references/dashboards.md §7): --expect-as-of refuses to build, and writes no file,
when the latest closed month in the extracts is not the month the run is for. --previous auto
(the default) compares with the previous month's page (scripts/gtm/compare.py: the page already at
--out when it is for an earlier month, else outputs/previous/pipeline_risk_readout.html) and adds
"since_last" to the JSON line; the page is unchanged. The file name never carries the month, so a
scheduled daily run always rewrites the same file.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gtm import compare, engine, live                   # noqa: E402
from gtm.common import BuildError                       # noqa: E402
from gtm.diagnosis import admit                         # noqa: E402
from gtm.render import render                           # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extracts", required=True, help="folder of governed extracts")
    ap.add_argument("--out", help="default outputs/pipeline_risk_readout.html under the skill folder")
    ap.add_argument("--as-of", help="analysis month YYYY-MM (default: the latest month in the booking lines that NetSuite has closed)")
    ap.add_argument("--window", choices=engine.WINDOWS)
    ap.add_argument("--scope-label", help="product the extracts were filtered to, for the page")
    ap.add_argument("--title", default="GTM review")
    ap.add_argument("--source", default="PROD_DB.SEMANTIC_VIEWS.GTM_ANALYTICS",
                    help="the view the extracts were run against (default PROD_DB); must match the statements")
    ap.add_argument("--payload-out")
    ap.add_argument("--expect-as-of", help="YYYY-MM the run is for; refuse when the extracts close on another month")
    ap.add_argument("--previous", default="auto", help="auto (the previous month's page, see compare.find_previous), none, or a page path")
    ap.add_argument("--diagnosis", nargs="*", default=[], help="diagnosis.json file(s), one per view, written against this payload")
    ap.add_argument("--allow-missing-review", action="store_true", help="publish without the opening view's AI review (a visible notice says so)")
    a = ap.parse_args()
    try:
        inputs, prov = live.load(a.extracts)
        p = engine.build(inputs, as_of=a.as_of, window=a.window, title=a.title,
                         source=a.source, data_mode="governed", provenance=prov)
        ym = p["meta"]["as_of"]["month_end"][:7]
        if a.expect_as_of and ym != a.expect_as_of:
            raise BuildError(f"the extracts close on {ym}, not {a.expect_as_of}: the month is not closed in the view yet "
                             "(or the extracts are stale), so no page was written")
        if a.scope_label:
            p["meta"]["scope"]["filtered_to"] = a.scope_label
        out = a.out or os.path.join(SKILL, "outputs", "pipeline_risk_readout.html")
        prev_file = (None if a.previous == "none" else
                     compare.find_previous(out, ym) if a.previous == "auto" else a.previous)
        since = ({"available": False, "reason": "comparison turned off (--previous none)", "previous": {"file": None, "as_of": None}}
                 if a.previous == "none" else compare.since_last(p, compare.read_page_payload(prev_file) if prev_file else None, prev_file))
        if a.payload_out:                               # saved before the review gate: the diagnosis is written against it
            json.dump(p, open(a.payload_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        review = admit(p, a.diagnosis, a.allow_missing_review)
        page_bytes = render(p, out)
    except BuildError as e:
        pp = locals().get("p") or {}
        print(json.dumps({"ok": False, "error": str(e), "payload_out": a.payload_out, "analysis_hash": pp.get("analysis_hash")}, ensure_ascii=False))
        return 1
    lid = p["meta"]["primary_lens"]["id"]
    print(json.dumps({"ok": True, "out": os.path.abspath(out), "bytes": page_bytes, "as_of": p["meta"]["as_of"]["label"], "pipeline_as_of": p["pipeline"]["as_of"],
                      "opens_on": lid, "qc": p["qc"]["status"], "checks": {c["id"]: c["result"] for c in p["qc"]["checks"]},
                      "headline": p["lenses"][lid]["headline"]["text"], "analysis_hash": p["analysis_hash"][:12],
                      "review": review, "since_last": since}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
