#!/usr/bin/env python3
"""Read-only query interface over a GTM payload for the diagnosis roles (references/diagnosis.md). Every figure comes
back with the payload path to cite as its `source` and the display to write in the text; the roles never compute,
round or combine numbers.

Usage:
  python gtm_brief.py PAYLOAD brief    [--lens QTD_pq]   # what the review must cover, every figure it may cite, the drill targets
  python gtm_brief.py PAYLOAD resolve --path "lenses[QTD_pq].kpis[total].variance"
  python gtm_brief.py PAYLOAD refs     [--lens QTD_pq]   # every detail the page can open (bullet and decision `ref`)
  python gtm_brief.py PAYLOAD contract                   # the diagnosis.json shape and rules, in brief
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from gtm import DIAGNOSIS_CONTRACT                                 # noqa: E402
from gtm.common import is_num, resolve_path                        # noqa: E402
from gtm.diagnosis import RISKS, _drivers, _risk_flagged, page_refs  # noqa: E402


def money(v, sign=False):
    """The page's money display: brackets for negatives, + when signed (as the renderer prints it)."""
    if not is_num(v):
        return "—"
    a = abs(v)
    s = (f"${a:,.0f}" if a < 1000 else f"${a / 1e3:.1f}k" if a < 1e4 else f"${a / 1e3:,.0f}k" if a < 1e6
         else f"${a / 1e6:.2f}mn" if a < 1e7 else f"${a / 1e6:.1f}mn" if a < 1e8 else f"${a / 1e6:,.0f}mn")
    return f"({s})" if v < 0 and a >= 0.5 else ("+" + s if sign and v >= 0.5 else s)


def pct(v, sign=False, dec=1):
    if not is_num(v):
        return "—"
    s = f"{abs(v) * 100:.{dec}f}%"
    return f"({s})" if v < 0 and abs(v) * 100 >= 0.05 else ("+" + s if sign and v > 0 else s)


def cite(path, value, kind="money", sign=False, dec=1):
    disp = money(value, sign) if kind == "money" else pct(value, sign, dec) if kind == "pct" else (f"{value:.0f} days" if kind == "days" and is_num(value) else value)
    return {"display": disp, "value": value, "kind": kind, "source": path}


CONTRACT_BRIEF = {
    "contract": DIAGNOSIS_CONTRACT,
    "shape": {"contract": DIAGNOSIS_CONTRACT, "payload_hash": "<payload.analysis_hash>", "lens": {"window": "QTD", "basis": "pq"}, "written_by": "driver review + readout (model)",
              "findings": [{"id": "f1", "title": "...", "scope": {"drivers": ["m:arr_new"], "risks": ["not_closing"]}, "decision_relevance": "high|medium|low", "confidence": "high|medium|low",
                            "persistence": "one_off|recurring|seasonal|timing|persistent|undetermined",
                            "statements": [{"state": "observed_fact|analytical_inference|hypothesis|management_input_required", "text": "...",
                                            "numbers": [{"display": "$2.92mn", "value": 2917000.0, "kind": "money", "source": "lenses[QTD_pq].kpis[total].actual"}],
                                            "evidence_refs": ["lenses[QTD_pq].kpis[total]"], "hypothesis": {"evidence_for": ["..."], "missing_evidence": ["..."], "closes_with": "..."}}],
                            "missing_evidence": ["..."], "management_questions": ["..."]}],
              "unresolved": [{"ref": "m:... or not_closing", "reason": "..."}],
              "readout": {"summary": {"pipeline": {"bullets": [{"head": "Bold lead, no figures.", "text": "the line on the page (<= 30 words)", "detail": "the full reading when opened",
                                                              "tone": "favourable|unfavourable|neutral|outlook", "ref": "rk:not_closing", "finding_ref": "f1", "numbers": [], "unverified": []}],
                                                 "decisions": [{"text": "Short question?", "detail": "Full question with figures?", "owner": "suggested function", "ref": "action:... or rk:...", "numbers": [], "amount": None}]},
                                      "bookings": {"bullets": [], "decisions": []}},
                          "bookings_meaning": [{"state": "analytical_inference", "text": "...", "numbers": [], "evidence_refs": ["..."]}],
                          "pipeline_meaning": [], "outlook_meaning": [],
                          "qc": {"business_cause": "how much is attested vs open", "open_gaps": ["..."]}}},
    "rules": ["every $ and % figure in any text is registered in numbers[] with display (verbatim in the text), value and a resolving source path; take both from `brief` or `resolve`",
              "negatives print in brackets: ($294k), (11.7%); signed positives carry +",
              "observed_fact restates a payload field; analytical_inference rests on two or more references; hypothesis carries its block; no causal wording in a fact or inference",
              "summary bullets: 3 to 5 per tab, head <= 10 words with no figures, text <= 30 words, detail <= 110 words that says what the figure means; the first Bookings bullet is about total bookings",
              "causes the view does not carry (pricing, competition, quota, churn, renewals, ...) only hedged ('may', 'to be confirmed') and listed in unverified[]",
              "decisions: 2 or 3 per tab, a question of <= 12 words with no figures; the full question with figures in detail; a suggested owner",
              "forbidden: higher/lower than expected, root cause (as a claim), confirmed/verified cause, will close/convert/recover/persist, assigned to / owned by, 'stalled' without 'proxy'",
              "every executive-tier driver and every flagged risk block (not_closing, stuck, high_value) has a finding or an unresolved entry",
              "each ref is a detail the page can open in this view (`refs`); payload_hash must equal payload.analysis_hash"]}


def lens_of(p, key):
    key = key or p["meta"]["primary_lens"]["id"]
    L = p["lenses"].get(key)
    if not L or not L.get("available"):
        raise SystemExit(json.dumps({"status": "REFUSED", "reason": f"lens {key} unavailable"}))
    return key, L


def brief(p, key, L):
    LP = f"lenses[{key}]"
    kp = []
    for k in L["kpis"]:
        ratio = k.get("kind") == "ratio"
        kk = "pct" if ratio else "money"
        row = {"id": k["id"], "label": k["label"], "status": k.get("status"),
               "actual": cite(f"{LP}.kpis[{k['id']}].actual", k.get("actual"), kk), "comparator": cite(f"{LP}.kpis[{k['id']}].comparator", k.get("comparator"), kk)}
        if ratio:
            row["variance"] = {"display": f"{'+' if (k.get('variance') or 0) > 0 else ''}{round((k.get('variance') or 0) * 10000):,} bps", "value": k.get("variance"), "kind": "pts", "source": f"{LP}.kpis[{k['id']}].variance",
                               "note": "points are not gated as $/%; write them as shown"}
        else:
            row["variance"] = cite(f"{LP}.kpis[{k['id']}].variance", k.get("variance"), "money", True)
            row["variance_pct"] = cite(f"{LP}.kpis[{k['id']}].variance_pct", k.get("variance_pct"), "pct", True)
        kp.append(row)
    drv = []
    for dim in ("measure", "product", "subsidiary"):
        for d in L["drivers"][dim]:
            drv.append({"id": d["id"], "dimension": dim, "label": d["label"], "tier": d.get("tier"),
                        "actual": cite(f"{LP}.drivers.{dim}[{d['id']}].actual", d.get("actual")), "comparator": cite(f"{LP}.drivers.{dim}[{d['id']}].comparator", d.get("comparator")),
                        "variance": cite(f"{LP}.drivers.{dim}[{d['id']}].variance", d.get("variance"), "money", True),
                        "variance_pct": cite(f"{LP}.drivers.{dim}[{d['id']}].variance_pct", d.get("variance_pct"), "pct", True),
                        "share_of_abs_variance": cite(f"{LP}.drivers.{dim}[{d['id']}].share_of_abs_variance", d.get("share_of_abs_variance"), "pct", dec=0),
                        "reading": d.get("reading"), "persistence_hint": (p["signals"].get(d["id"]) or {}).get("persistence_hint")})
    rk, risk = p.get("risk") or {}, {}
    for r in ("not_closing", "stuck", "at_risk"):
        x = rk.get(r) or {}
        if x:
            risk[r] = {"rule": x.get("rule"), "count": x.get("count"), "acv": cite(f"risk.{r}.acv", x.get("acv")), "recurring": cite(f"risk.{r}.recurring", x.get("recurring")),
                       "share_of_open": cite(f"risk.{r}.share", x.get("share"), "pct", dec=0) if is_num(x.get("share")) else None}
    hv = rk.get("high_value") or {}
    if hv:
        risk["high_value"] = {"cutoff": cite("risk.high_value.cutoff", hv.get("cutoff")), "count": hv.get("count"), "acv": cite("risk.high_value.acv", hv.get("acv")),
                              "flagged_count": (hv.get("flagged") or {}).get("count"), "flagged_acv": cite("risk.high_value.flagged.acv", (hv.get("flagged") or {}).get("acv")),
                              "flagged_share_of_hv": cite("risk.high_value.flagged.share_of_hv", (hv.get("flagged") or {}).get("share_of_hv"), "pct", dec=0)}
    lo = L.get("lost")
    if lo:
        risk["lost"] = {"count": lo.get("count"), "acv": cite(f"{LP}.lost.acv", lo.get("acv")), "variance": cite(f"{LP}.lost.variance", lo.get("variance"), "money", True),
                        "headline": lo.get("headline")}
    pipe = p["pipeline"]
    pip = {"as_of": pipe.get("as_of"), "open": cite("pipeline.open", pipe.get("open")), "open_count": pipe.get("open_count"),
           "in_quarter": {"quarter": (pipe.get("in_quarter") or {}).get("quarter"), "open": cite("pipeline.in_quarter.open", (pipe.get("in_quarter") or {}).get("open"))},
           "by_close_quarter": [{"quarter": r.get("quarter"), "open": cite(f"pipeline.by_close_quarter[{i}].open", r.get("open")), "count": r.get("count")} for i, r in enumerate(pipe.get("by_close_quarter") or [])]}
    cov = (pipe.get("coverage") or {}).get("by_quarter") or []      # a view with a pipeline target: coverage by quarter (multiples are written as shown, not gated)
    if cov:
        pip["coverage"] = {"floor": (pipe.get("coverage") or {}).get("floor"),
                           "by_quarter": [{"quarter": r.get("quarter"), "coverage": r.get("coverage"), "source": f"pipeline.coverage.by_quarter[{i}]",
                                           **{k: cite(f"pipeline.coverage.by_quarter[{i}].{k}", r[k]) for k in ("weighted", "open", "target") if is_num(r.get(k))}}
                                          for i, r in enumerate(cov)]}
    scen = [{"quarter": s["quarter"], "low": cite(f"outlook.scenario[{i}].low", s.get("low")), "high": cite(f"outlook.scenario[{i}].high", s.get("high")),
             "open": cite(f"outlook.scenario[{i}].open", s.get("open")), "py_won": cite(f"outlook.scenario[{i}].py_won", s.get("py_won")),
             "won_since": cite(f"outlook.scenario[{i}].won_since", s.get("won_since")) if is_num(s.get("won_since")) else None}
            for i, s in enumerate((p.get("outlook") or {}).get("scenario") or [])]
    roy = p.get("rest_of_year") or None
    royb = {k: cite(f"rest_of_year.{k}", roy[k]) for k in ("to_match_py", "to_hold_growth", "py_rest", "won_since", "still_to_match", "ytd") if roy and is_num(roy.get(k))} if roy else None
    drivers = _drivers(L)
    need = {"executive_drivers": [d for d, x in drivers.items() if x.get("tier") == "executive"], "flagged_risks": _risk_flagged(p, L)}
    return {"lens": key, "payload_hash": p["analysis_hash"], "range": L["range"], "headline": L["headline"]["text"],
            "must_cover": need, "risk_blocks": list(RISKS),
            "engine_pipeline_bullets": L.get("pipeline_insights") or rk.get("insights"), "engine_bookings_bullets": L.get("insights"),
            "engine_actions": [{"id": a["id"], "ref": "action:" + a["id"], "question": a.get("question"), "owner": a.get("owner"), "exposure": a.get("exposure")}
                               for a in (L.get("pipeline_actions") or []) + (L.get("actions") or []) + (rk.get("actions") or [])],
            "kpis": kp, "drivers": drv, "risk": risk, "pipeline": pip, "scenario": scen, "rest_of_year": royb,
            "concentration": {k: L["concentration"].get(k) for k in ("top2_share", "top5_share", "largest_order_share", "customers")},
            "velocity": {k: (L.get("velocity") or {}).get(k) for k in ("avg_days", "variance_days", "n")},
            "refs": sorted(page_refs(p, L))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload")
    ap.add_argument("cmd", choices=["brief", "resolve", "refs", "contract"])
    ap.add_argument("--lens")
    ap.add_argument("--path")
    a = ap.parse_args()
    with open(a.payload, encoding="utf-8") as fh:
        p = json.load(fh)
    if a.cmd == "contract":
        out = CONTRACT_BRIEF
    elif a.cmd == "resolve":
        try:
            v = resolve_path(p, a.path)
        except (KeyError, IndexError, TypeError):
            raise SystemExit(json.dumps({"status": "REFUSED", "reason": f"{a.path} does not resolve"}))
        out = {"path": a.path, "value": v, "money": money(v) if is_num(v) else None, "pct": pct(v) if is_num(v) else None}
    else:
        key, L = lens_of(p, a.lens)
        out = sorted(page_refs(p, L)) if a.cmd == "refs" else brief(p, key, L)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
