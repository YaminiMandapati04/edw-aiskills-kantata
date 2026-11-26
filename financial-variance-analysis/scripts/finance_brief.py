#!/usr/bin/env python3
"""Read-only query interface over a finance payload for the diagnosis roles. Every figure comes back
with the payload path to cite as its `source`; the roles never compute, round or combine numbers.

Usage:
  python finance_brief.py PAYLOAD brief                [--lens MTD_budget]   # the evidence brief: what to investigate, ranked
  python finance_brief.py PAYLOAD overview             [--lens ...]          # headline, KPIs, lines, patterns, layers, concentration
  python finance_brief.py PAYLOAD drivers              [--lens ...]          # every driver with values, tier, rank
  python finance_brief.py PAYLOAD driver --id d:...    [--lens ...]          # one driver: values, accounts, insight, explanation, action, bridge step
  python finance_brief.py PAYLOAD account --id 6300    [--lens ...]          # one account: values, signals, run-rate, explanation, series
  python finance_brief.py PAYLOAD accounts             [--lens ...] [--tier management]   # account table
  python finance_brief.py PAYLOAD insights | actions | patterns | kpis | readout | story | headline | layers | bridge | outlook | qc | explanation --id ...
  python finance_brief.py PAYLOAD resolve --path "lenses[MTD_budget].drivers[d:cos:recurring-cogs].variance"
  python finance_brief.py PAYLOAD memos               [--lens ...] [--id d:...|<account id>]   # GL memo themes: what the postings were called, with sources
  python finance_brief.py PAYLOAD summary_pack        [--lens ...]          # every figure the written executive summary may use, with sources, and the writing rules
  python finance_brief.py PAYLOAD contract             # the diagnosis.json shape and rules, in brief
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance import DIAGNOSIS_CONTRACT                   # noqa: E402
from finance.common import resolve_path, money, pct, is_num      # noqa: E402

CONTRACT_BRIEF = {
    "contract": DIAGNOSIS_CONTRACT,
    "shape": {"contract": DIAGNOSIS_CONTRACT, "payload_hash": "<payload.analysis_hash>", "lens": {"window": "MTD", "basis": "budget"}, "written_by": "<role / model name, never a person's approval>",
              "findings": [{"id": "f1", "title": "...", "scope": {"drivers": ["d:..."], "accounts": ["..."]}, "decision_relevance": "high|medium|low", "confidence": "high|medium|low",
                            "controllability": "controllable|partially_controllable|external|not_assessed", "persistence": "one_off|recurring|seasonal|timing|persistent|coverage|undetermined",
                            "statements": [{"state": "observed_fact|analytical_inference|hypothesis|management_input_required", "text": "...",
                                            "numbers": [{"display": "$38k", "value": -37830.21, "kind": "money", "source": "lenses[MTD_budget].drivers[d:opex:acct-6300].variance"}],
                                            "evidence_refs": ["signals[6300].tests[outlier_month]"], "claim_types": ["persistence"],
                                            "hypothesis": {"evidence_for": ["..."], "missing_evidence": ["..."], "closes_with": "..."}}],
                            "missing_evidence": ["..."], "management_questions": ["..."], "addresses_tests": ["outlier_month"]}],
              "unresolved": ["d:... with the reason"],
              "readout": {"headline": "optional rephrase that keeps every pinned slot display verbatim",
                      "conclusions": [{"role": "current_period_driver|performance_quality|forward_looking", "finding_ref": "f1", "status": "favorable|unfavorable|mixed", "state": "analytical_inference",
                                       "text": "...", "numbers": [], "evidence_refs": [], "persistence": "...", "response": "what management should do or decide"}],
                      "decision_asks": [{"text": "...", "finding_ref": "f1", "owner": "suggested role", "action_refs": ["a:d:..."], "numbers": []}],
                      "driver_stories": [{"finding_ref": "f1", "state": "...", "text": "...", "numbers": []}], "structural_conclusions": [], "forecast_assumptions": [], "lead_actions": [],
                      "account_interpretations": [{"account": "6300", "state": "analytical_inference", "text": "...", "numbers": [], "hypothesis": None}],
                      "qc": {"business_cause": "one sentence on how much is attested vs open", "open_gaps": ["..."]}}},
    "rules": ["every $ / % / bps figure in any text is registered in that statement's numbers[] with display, value and a resolving source path; the display must appear verbatim in the text",
              "money displays use the payload convention ($38k, $1.57mm, U+2212 for minus, + for signed); use `resolve` to read the exact value",
              "observed_fact restates a payload field (carries a number or evidence_ref); analytical_inference rests on at least two references; hypothesis carries the hypothesis block; management_input_required names the input",
              "no causal wording (because, due to, driven by, caused by) in a fact or inference; 'timing' only where reversal_signal fired, else as a hypothesis",
              "forbidden: higher/lower than expected, business needs, root cause (as a claim), confirmed/verified cause, will recover/reverse/persist, assigned to / owned by",
              "three conclusions, one per role; at most three decision asks; every executive-tier driver has a finding or is listed in unresolved[]",
              "payload_hash must equal payload.analysis_hash; a changed payload needs a rewritten diagnosis"]}


MEMO_RULES = ["GL memos are what the person who posted the lines wrote: evidence for a reading (an accrual, a reversal, a payroll run, an "
              "adjustment), never a verified cause; cite a theme with its evidence_ref and its figures with their sources",
              "describe a theme in accounting words ('vendor accruals for the prior month reversed', 'semi-monthly payroll runs'); never quote a memo, "
              "a vendor, customer, person or system name, or a document number: the gate refuses memos.restricted_terms anywhere in the review",
              "a theme tagged accrual_reversal (an accrual or reversal naming an earlier month) may support 'timing' when cited in evidence_refs",
              "'(no memo)' is a theme too: say how much of a movement carries no description (blank_memo_share) rather than reading it",
              "on a budget view the budget has no memos: themes show what posted in the window, not what moved against plan"]


def memo_table(t, path, top=None):
    """A memo table with every figure citable."""
    if not t:
        return None
    out = {"source": path, "theme_count": t["theme_count"], "blank_memo_share": t.get("blank_memo_share"), "comparator_tie": t.get("comparator_tie"),
           "actual_total": t["actual_total"], "comparator_total": t.get("comparator_total"), "themes": []}
    for x in t["themes"][:top] if top else t["themes"]:
        tp = f"{path}.themes[{x['id']}]"
        rec = {"id": x["id"], "evidence_ref": tp, "label": x["label"], "tags": x.get("tags", []), "lines": x.get("lines"), "refers_to": x.get("refers_to"),
               "actual": cite(f"{tp}.actual", x["actual"]), "comparator": cite(f"{tp}.comparator", x.get("comparator")) if x.get("comparator") is not None else None,
               "variance": cite(f"{tp}.variance", x.get("variance")) if x.get("variance") is not None else None,
               "share_of_abs_movement": cite(f"{tp}.share_of_abs_movement", x.get("share_of_abs_movement"), "pct") if x.get("share_of_abs_movement") is not None else None}
        for k in ("accounts", "drivers", "source_type"):
            if x.get(k):
                rec[k] = x[k]
        out["themes"].append(rec)
    out["categories"] = [{"id": c["id"], "label": c["label"], "themes": c["themes"], "evidence_ref": f"{path}.categories[{c['id']}]",
                          "actual": cite(f"{path}.categories[{c['id']}].actual", c["actual"]),
                          "comparator": cite(f"{path}.categories[{c['id']}].comparator", c["comparator"]) if c.get("comparator") is not None else None,
                          "variance": cite(f"{path}.categories[{c['id']}].variance", c["variance"]) if c.get("variance") is not None else None}
                         for c in t.get("categories", [])]
    return out


def memo_for(p, L, LP, kind, id_, top=None):
    me = L.get("memo_evidence") or {}
    if not me.get("available"):
        return {"available": False, "reason": me.get("reason") or (p.get("memos") or {}).get("reason") or "no memo evidence"}
    if kind == "net_income":
        return memo_table(me["net_income"], f"{LP}.memo_evidence.net_income", top)
    t = me[kind].get(id_)
    return memo_table(t, f"{LP}.memo_evidence.{kind}[{id_}]", top) if t else {"available": False, "reason": f"no memo table for this {kind[:-1]} (immaterial in this view)"}


def lens_of(p, key):
    key = key or p["meta"]["primary_lens"]["id"]
    L = p["lenses"].get(key)
    if not L or not L.get("available"):
        raise SystemExit(json.dumps({"status": "REFUSED", "reason": f"lens {key} unavailable"}))
    return key, L


def cite(path, value, kind="money"):
    """A figure with its source, as the diagnosis registers it: display, value, kind, source (points carry transform abs)."""
    if kind == "pts":
        return {"display": f"{round(abs(value) * 10000):,} bps" if isinstance(value, (int, float)) else "n/a", "value": abs(value) if isinstance(value, (int, float)) else value, "kind": "pts", "transform": "abs", "source": path}
    return {"display": money(value) if kind == "money" else pct(value) if kind == "pct" else value, "value": value, "kind": kind, "source": path}


# drivers the Finance view does not carry: name them when a movement may reflect them, never quantify them, and ask for the data
MISSING_DRIVERS = {
    "rev": [{"driver": "customer count (new, churned)", "confirm_with": "Revenue Operations / CRM"}, {"driver": "customer concentration", "confirm_with": "Revenue Operations / CRM"},
            {"driver": "price and volume", "confirm_with": "Revenue Accounting"}, {"driver": "product adoption", "confirm_with": "Product / Customer Success"}],
    "cos": [{"driver": "delivery headcount", "confirm_with": "HR / Payroll"}, {"driver": "hosting and usage volumes", "confirm_with": "Operations / Engineering"},
            {"driver": "vendor rates and contracts", "confirm_with": "Procurement"}],
    "opex": [{"driver": "headcount and hiring", "confirm_with": "HR / Payroll"}, {"driver": "compensation rates", "confirm_with": "HR / Payroll"},
             {"driver": "vendor and programme contracts", "confirm_with": "Procurement / function head"}, {"driver": "organisational changes", "confirm_with": "Function head"}],
    "syn": [{"driver": "acquisition and integration plans", "confirm_with": "Corporate Development"}],
    "nonop": [{"driver": "tax provision workpapers", "confirm_with": "Tax"}, {"driver": "debt schedule and interest rates", "confirm_with": "Treasury"}, {"driver": "FX rates", "confirm_with": "Treasury"}],
}

SUMMARY_RULES = [
    "the narrative: exactly 4 bullets, each with a role, in this order: headline (outcome, primary driver, implication: '[outcome], driven by [driver], [what it means]'; about net income) -> why (the causal chain: net income -> EBITDA -> revenue / cost of sales / opex -> department or product line -> sub-group -> account; each step explains the one above, use hierarchy[]) -> trend (the month against the quarter and year to date: continuing, reversal, new or easing; use trend{}) -> attention (the most important risk, validation or action, with any data needed). What it means (margin, growth, efficiency, recurring vs one-off, operating vs non-operating, broad vs concentrated, sustainability) is written inside the headline, why and trend bullets, not as a fifth bullet",
    "the page lines (heads + texts of all bullets) total at most 220 words (about 60 per bullet): fewer, deeper points rather than many short ones",
    "business context the data model does not carry (customers, headcount, pricing, acquisitions, integration, inflation): only as a hedged possibility ('appears', 'suggests', 'potentially', 'may indicate', 'to be confirmed'), never quantified, never read as unchanged because the data is absent; list it in the bullet's unverified[] and put the data that would confirm it in the attention bullet's data_needed[] (missing_drivers{} names it and who holds it)",
    "each bullet: head (bold lead, at most 10 words, no figures) + text (the insight shown on the page: 2 to 3 sentences, at most 48 words, the key figures allowed if registered in numbers[], each sentence explaining the previous one) + detail (the fuller reading shown when the bullet is opened, above its evidence: at most 130 words, at most five sentences, with the figures, the drivers down the hierarchy, history and what it implies)",
    "observation, then meaning: a figure alone is refused; the text says what it means (concentration, trend, structural vs one-off, margin, forecast quality, mix, actionability) and the detail carries the evidence",
    "every figure in detail is in numbers[] with its source path from this pack; nothing is computed, rounded or combined by the writer",
    "drill: {level, ids} opens on what the bullet says (driver, account, line, section, outlook, action); the reader must land on the evidence for that bullet",
    "tone: favourable | unfavourable | neutral | outlook; claim (optional, lead only): revenue_led | cost_led | growth_outpacing_cost | below_line_led | margin_up | margin_down | broad | growth_absorbed | on_plan, re-checked against the numbers",
    "attribution down the hierarchy may say 'driven by' or 'led by' (the drill proves it); any other causal phrase (because, due to, caused by, as a result of, owing to, thanks to, explained by) only hedged in the same sentence ('may be due to'); none of the forbidden phrases; no business explanation the data does not support, no assumed management intent",
    "decisions: 2 or 3 questions for management; text is the question on the page (at most 12 words, ends with ?, no figures), detail the full question (at most 40 words, with registered figures, ends with ?); a suggested owner, a drill on what the question is about, an optional registered amount at stake",
]


def _trend_pack(p, L, drivers):
    """The month against the quarter and year to date on this basis, for net income, EBITDA, revenue, opex and the top
    drivers, each figure with its source, and the engine's reading (continuing, reversal, new, easing)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from finance.summary import trend_reading, trend_windows
    ws = trend_windows(p["lenses"], L["basis"])
    if not ws:
        return None
    mon = L["materiality"]["monitoring_abs"]
    def row(find):
        vals = {w: find(p["lenses"][f"{w}_{L['basis']}"]) for w in ws}
        if not all(v is not None for v, _ in vals.values()):
            return None
        return {"windows": {w: cite(src, v) for w, (v, src) in vals.items()}, "reading": trend_reading(vals["MTD"][0], [vals[w][0] for w in ws[1:]], mon)}
    line = lambda lid: lambda X: next(((x["variance"], f"lenses[{X['id']}].lines[{lid}].variance") for x in X["lines"] if x["id"] == lid), (None, None))
    drv = lambda did: lambda X: next(((x["variance"], f"lenses[{X['id']}].drivers[{did}].variance") for x in X["drivers"] if x["id"] == did), (None, None))
    return {"windows": ws, "readings": "continuing (the month repeats the longer pattern) | reversal (the month points the other way) | new (not in the longer windows yet) | easing (the month is close to the comparison)",
            "lines": {lid: row(line(lid)) for lid in ("ni", "ebitda", "rev", "opex")},
            "drivers": {d["id"]: row(drv(d["id"])) for d in drivers}}


def adj_pack(L, LP, cite):
    """The manual adjustments in the lens window (pro forma; capitalised software and commissions with their reversal),
    each impact cited, so the summary and readout can say which adjustments are included and what they did."""
    A = L.get("adjustments") or {}
    if not A.get("available"):
        return {"available": False, "reason": A.get("reason")}
    out = []
    for x in A["types"]:
        tp = f"{LP}.adjustments.types[{x['id']}]"
        a, c = x["actual"] or {}, x["comparator"] or {}
        out.append({"id": x["id"], "label": x["label"], "class": x["class"], "class_label": x["class_label"],
                    "revenue": cite(f"{tp}.actual.rev", a.get("rev")) if a else None,
                    "ebitda": cite(f"{tp}.actual.ebitda", a.get("ebitda")) if a else None,
                    "net_income": cite(f"{tp}.actual.ni", a.get("ni")) if a else None,
                    "components": [{"label": k["label"], "amount": cite(f"{tp}.actual.components[{k['id']}].amount", k["amount"])} for k in a.get("components", [])],
                    "comparator_ebitda": cite(f"{tp}.comparator.ebitda", c.get("ebitda")) if c else None,
                    "ebitda_variance": cite(f"{tp}.ebitda_variance", x.get("ebitda_variance")) if x.get("ebitda_variance") is not None else None})
    return {"available": True, "types": out, "total_ebitda_impact": cite(f"{LP}.adjustments.total_ebitda_impact", A["total_ebitda_impact"]),
            "ebitda_excluding_adjustments": cite(f"{LP}.adjustments.ebitda_excluding_adjustments", A.get("ebitda_excluding_adjustments")),
            "basis_note": A.get("basis_note"), "rule": A.get("rule")}


def summary_pack(p, L, LP, cite):
    """The figures a writer may use in the executive summary, each with its source path, plus the rules the gate applies."""
    ln = {x["id"]: x for x in L["lines"]}
    def line(lid):
        x = ln[lid]
        d = {"actual": cite(f"{LP}.lines[{lid}].actual", x.get("actual")), "comparator": cite(f"{LP}.lines[{lid}].comparator", x.get("comparator")),
             "variance": cite(f"{LP}.lines[{lid}].variance", x.get("variance")), "variance_pct": cite(f"{LP}.lines[{lid}].variance_pct", x.get("variance_pct"), "pct")}
        if x.get("kind") == "ratio":
            d = {"actual": cite(f"{LP}.lines[{lid}].actual", x.get("actual"), "pct"), "comparator": cite(f"{LP}.lines[{lid}].comparator", x.get("comparator"), "pct"),
                 "variance_pts": cite(f"{LP}.lines[{lid}].variance", x.get("variance"), "pts")}
        return d
    sig = p["signals"]
    drv = sorted([d for d in L["drivers"] if d["tier"] in ("executive", "management")], key=lambda d: -abs(d["variance"] or 0))
    def lead_acct(d):
        xs = [a for a in L["accounts"] if a["driver_ref"] == d["id"] and a["variance"] is not None]
        return max(xs, key=lambda a: abs(a["variance"]), default=None)
    def persist(aid):
        t = next((t for t in sig[aid]["tests"] if t["id"] == "persistent_gap"), None)
        return {"months_same_side": (t.get("evidence") or {}).get("months_same_side"), "of": (t.get("evidence") or {}).get("months_compared"), "source": f"signals[{aid}].tests[persistent_gap].evidence.months_same_side"} if t and t["state"] == "fired" else None
    twin_key = f"{L['window']}_{'py' if L['basis'] == 'budget' else 'budget'}"
    T = p["lenses"].get(twin_key) or {}
    oo = L.get("one_offs") or {}
    O = p.get("outlook") or {}
    hs = (L.get("headline") or {}).get("slots") or {}
    out = {
        "window": L["window_label"], "basis": L["basis_label"], "range": L["range"]["label"],
        "lines": {k: line(k) for k in ("rev", "cos", "gp", "opex", "ebitda", "syn", "nonop", "ni", "ebm", "gpm")},
        "totals": {"cost_variance": cite(f"{LP}.totals.cost_variance", L["totals"]["cost_variance"]), "below_line_variance": cite(f"{LP}.totals.below_line_variance", L["totals"]["below_line_variance"])},
        "same_window_other_basis": {"basis": T.get("basis_label"), "ni_variance": cite(f"lenses[{twin_key}].lines[ni].variance", next((x["variance"] for x in T.get("lines", []) if x["id"] == "ni"), None))} if T.get("available") else None,
        "concentration": {k: {"display": v["display"], "value": v["value"], "source": v["source"]} for k, v in hs.items() if k in ("material_accounts", "top3_share")},
        "drivers": [{"id": d["id"], "label": d["label"], "section": d["section"], "tier": d["tier"], "share_of_movement": cite(f"{LP}.drivers[{d['id']}].share_of_abs_variance", d.get("share_of_abs_variance"), "pct"),
                     "variance": cite(f"{LP}.drivers[{d['id']}].variance", d["variance"]), "variance_pct": cite(f"{LP}.drivers[{d['id']}].variance_pct", d["variance_pct"], "pct"),
                     "actual": cite(f"{LP}.drivers[{d['id']}].actual", d["actual"]), "comparator": cite(f"{LP}.drivers[{d['id']}].comparator", d["comparator"]),
                     "lead_account": (lambda a: {"id": a["id"], "variance": cite(f"{LP}.accounts[{a['id']}].variance", a["variance"]), "persistence_hint": sig[a["id"]]["persistence_hint"], "fired": sig[a["id"]]["fired"], "persistent_gap": persist(a["id"])} if a else None)(lead_acct(d)),
                     "top_department": (lambda dep: {"name": dep["rows"][0]["name"], "movement": cite(f"{LP}.reconciliation[{d['id']}].by_department.rows[0].movement", dep["rows"][0]["movement"])} if dep and dep.get("comparable") and dep.get("rows") else None)(((L.get("reconciliation") or {}).get(d["id"]) or {}).get("by_department"))}
                    for d in drv[:8]],
        "one_offs": {"named": [{"account": x["account"], "name": x["name"], "month": x["month"], "driver": x["driver"], "amount": cite(f"{LP}.one_offs.named[{i}].amount", x["amount"])} for i, x in enumerate(oo.get("named") or [])],
                     "underlying_ni_variance": cite(f"{LP}.one_offs.underlying_variance", oo.get("underlying_variance")), "count": oo.get("count")},
        "patterns_fired": [{"id": x["id"], "reading": x["reading"]} for x in L["patterns"] if x["fired"]],
        "engine_insights": [{"id": i["id"], "label": i["label"], "persistence": i["persistence"], "statements": [s["text"] for s in i["statements"] if s["state"] != "management_input_required"]} for i in L["insights"][:8]],
        "outlook": {lid: {"full_year": cite(f"outlook.lines.{lid}.mechanical.value", O["lines"][lid]["mechanical"]["value"]), "gap_vs_budget": cite(f"outlook.lines.{lid}.gap_vs_budget", O["lines"][lid].get("gap_vs_budget")),
                          "gap_vs_prior_year": cite(f"outlook.lines.{lid}.gap_vs_prior_year", O["lines"][lid].get("gap_vs_prior_year")), "rule": O["lines"][lid]["mechanical"]["rule"],
                          "spread_pct": cite(f"outlook.lines.{lid}.mechanical.sensitivity_spread_pct", O["lines"][lid]["mechanical"].get("sensitivity_spread_pct"), "pct")} for lid in ("ebitda", "ni")} if O.get("state") == "calculated" else None,
        "actions": [{"id": x["id"], "subject_ref": x["subject_ref"], "question": x["question"], "owner": x["owner"]["role"], "date": x["date"]["target"], "at_stake": cite(x["exposure"]["source"], x["exposure"]["amount"])} for x in L["actions"][:6]],
        "drill_levels": {"section": ["rev", "cos", "opex", "syn", "nonop", "ebitda"], "line": sorted(ln), "driver": [d["id"] for d in L["drivers"]], "outlook": ["mechanical", "ytd"], "action": [x["id"] for x in L["actions"]], "account": "any account id in this view"},
        "hierarchy": [{"driver": d["id"], "label": d["label"], "parent_line": d["section"], "parent_variance": cite(f"{LP}.lines[{d['section']}].variance", ln[d["section"]]["variance"]) if d["section"] in ln else None,
                       "driver_variance": cite(f"{LP}.drivers[{d['id']}].variance", d["variance"]),
                       "position": ("offsets the parent" if is_num(d["variance"]) and is_num((ln.get(d["section"]) or {}).get("variance")) and (d["variance"] > 0) != (ln[d["section"]]["variance"] > 0)
                                    else "most of the parent" if is_num(d["variance"]) and is_num((ln.get(d["section"]) or {}).get("variance")) and abs(d["variance"]) >= 0.5 * abs(ln[d["section"]]["variance"])
                                    else "part of the parent")}
                      for d in drv[:5]],
        "trend": _trend_pack(p, L, drv[:5]),
        "missing_drivers": {sec: MISSING_DRIVERS[sec] for sec in sorted({d["section"] for d in drv[:5]}) if sec in MISSING_DRIVERS},
        "memo_evidence": ({"net_income": memo_for(p, L, LP, "net_income", None, 8),
                           "drivers": {d["id"]: memo_for(p, L, LP, "drivers", d["id"], 4) for d in drv[:5]},
                           "restricted_terms": (p.get("memos") or {}).get("restricted_terms"), "rules": MEMO_RULES}
                          if (L.get("memo_evidence") or {}).get("available") else {"available": False, "reason": (L.get("memo_evidence") or p.get("memos") or {}).get("reason")}),
        "adjustments": adj_pack(L, LP, cite),
        "rules": SUMMARY_RULES,
        "shape": {"bullets": [{"id": "lead", "role": "headline", "tone": "favourable|unfavourable|neutral|outlook", "head": "Bold lead, no figures.", "text": "One line, no figures: where net income stands, what drives it, what it means.", "detail": "The full sentence with registered figures, then what it means.",
                               "numbers": [{"display": "$275k", "value": 274616.72, "kind": "money", "source": f"{LP}.lines[ni].variance"}], "drill": {"level": "line", "ids": ["ni"]}, "claim": "below_line_led"},
                              {"id": "why", "role": "why", "head": "...", "text": "...", "detail": "... may reflect hiring, which the data model does not carry ...", "unverified": ["headcount"], "numbers": [], "drill": {"level": "driver", "ids": ["d:..."]}},
                              {"id": "trend", "role": "trend", "head": "...", "text": "...", "detail": "...", "numbers": [], "drill": {"level": "line", "ids": ["ni"]}},
                              {"id": "attention", "role": "attention", "head": "...", "text": "...", "detail": "...", "data_needed": ["headcount by department (HR / Payroll)"], "numbers": [], "drill": {"level": "action", "ids": ["a:..."]}}],
                  "decisions": [{"text": "Short question on the page?", "detail": "The full question, with registered figures?", "owner": "Controller", "drill": {"level": "driver", "ids": ["d:..."]}, "amount": {"display": "$440k", "value": 440000, "kind": "money", "source": "..."}, "numbers": []}]},
    }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload")
    ap.add_argument("op")
    ap.add_argument("--lens")
    ap.add_argument("--id")
    ap.add_argument("--path")
    ap.add_argument("--tier")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    with open(a.payload, encoding="utf-8") as fh:
        p = json.load(fh)
    out = {"payload_hash": p["analysis_hash"], "as_of": p["meta"]["as_of_label"]}
    if a.op == "contract":
        out.update(CONTRACT_BRIEF)
    elif a.op == "resolve":
        out["path"] = a.path
        out["value"] = resolve_path(p, a.path)
    elif a.op == "qc":
        out["qc"] = p["qc"]; out["sign_convention"] = p["meta"]["sign_convention"]; out["materiality"] = p["meta"]["materiality"]; out["capabilities"] = p["capabilities"]
    elif a.op == "outlook":
        out["outlook"] = p["outlook"]
    elif a.op == "adjustments":
        key, L = lens_of(p, a.lens)
        out["lens"] = key
        out["adjustments"] = adj_pack(L, f"lenses[{key}]", cite)
    else:
        key, L = lens_of(p, a.lens)
        LP = f"lenses[{key}]"
        out["lens"] = key
        if a.op == "summary_pack":
            out.update(summary_pack(p, L, LP, cite))
        elif a.op == "brief":
            drv = sorted([d for d in L["drivers"] if d["tier"] in ("executive", "management", "monitoring")], key=lambda d: -abs(d["variance"] or 0))
            out.update({
                "headline": L["headline"]["text"], "headline_slots": {k: v["display"] for k, v in L["headline"]["slots"].items()},
                "readout": L["readout"]["answers"], "top_three": L["readout"]["top_three"],
                "story": {"lead": L["story"]["lead"]["text"], "lines": {x["id"]: x["text"] for x in L["story"]["lines"]}, "growth": L["story"]["growth"]["text"],
                          "growth_reading": (L["story"]["growth"]["pattern"] or {}).get("reading"), "accounts": L["story"]["accounts"]["text"]},
                "patterns_fired": [{"id": x["id"], "reading": x["reading"], "source": f"{LP}.patterns[{x['id']}]"} for x in L["patterns"] if x["fired"]],
                "layers": {k: v for k, v in (L.get("layers") or {}).items() if k in ("state", "totals", "shares_of_gross", "primary_layer", "reason")},
                "material_drivers": [{"id": d["id"], "label": d["label"], "section": d["section"], "tier": d["tier"], "rank": d.get("rank"),
                                      "variance": cite(f"{LP}.drivers[{d['id']}].variance", d["variance"]), "variance_pct": cite(f"{LP}.drivers[{d['id']}].variance_pct", d["variance_pct"], "pct"),
                                      "actual": cite(f"{LP}.drivers[{d['id']}].actual", d["actual"]), "comparator": cite(f"{LP}.drivers[{d['id']}].comparator", d["comparator"]),
                                      "accounts": [{"id": x, "fired": p["signals"][x]["fired"], "persistence_hint": p["signals"][x]["persistence_hint"],
                                                    "variance": cite(f"{LP}.accounts[{x}].variance", next(q["variance"] for q in L["accounts"] if q["id"] == x))} for x in d["accounts"]]}
                                     for d in drv],
                "insights": [{"id": i["id"], "rank": i["rank"], "label": i["label"], "persistence": i["persistence"], "confidence": i["confidence"],
                              "statements": [{"state": s["state"], "text": s["text"], "evidence_refs": s.get("evidence_refs", [])} for s in i["statements"]],
                              "causal_gap": i["causal_gap"], "numbers": i["numbers"]} for i in L["insights"][:a.top]],
                "actions": [{"id": x["id"], "rank": x["rank"], "subject_ref": x["subject_ref"], "category": x["category"], "rule": x["rule"], "short": x["short"], "question": x["question"],
                             "owner": x["owner"], "date": x["date"], "exposure": x["exposure"], "forecast": x["forecast"]} for x in L["actions"]],
                "adjustments": adj_pack(L, LP, cite),
                "executive_tier_drivers_needing_a_finding": [d["id"] for d in L["drivers"] if d["tier"] == "executive"],
                "gl_memos": {"available": bool((L.get("memo_evidence") or {}).get("available")), "basis": (L.get("memo_evidence") or {}).get("basis"),
                             "read_with": f"finance_brief.py PAYLOAD memos --lens {key} [--id <driver or account>]; `driver` and `account` carry them too",
                             "rules": MEMO_RULES} if (p.get("memos") or {}).get("available") else {"available": False, "reason": (p.get("memos") or {}).get("reason")},
                "how_to_cite": f"numbers[].source is a path such as {LP}.drivers[<driver id>].variance, {LP}.accounts[<account id>].actual, signals[<account id>].tests[<test id>].evidence.<key>, outlook.lines.ebitda.mechanical.value; use `resolve --path` to read the exact value"})
        elif a.op == "overview":
            out.update({"headline": L["headline"], "kpis": [{**k, "source": f"{LP}.kpis[{k['id']}]"} for k in L["kpis"]], "lines": [{**x, "source": f"{LP}.lines[{x['id']}]"} for x in L["lines"]],
                        "patterns": L["patterns"], "layers": L.get("layers"), "concentration": {**L["concentration"], "source": f"{LP}.concentration"}, "readout": L["readout"]})
        elif a.op == "drivers":
            out["drivers"] = [{**d, "source": f"{LP}.drivers[{d['id']}]"} for d in L["drivers"]]
        elif a.op == "driver":
            d = next((x for x in L["drivers"] if x["id"] == a.id), None) or sys.exit(json.dumps({"status": "REFUSED", "reason": f"unknown driver {a.id}"}))
            out.update({"driver": {**d, "source": f"{LP}.drivers[{d['id']}]"}, "accounts": [{**x, "source": f"{LP}.accounts[{x['id']}]"} for x in L["accounts"] if x["driver_ref"] == d["id"]],
                        "insight": next((i for i in L["insights"] if i["subject_ref"] == d["id"]), None), "explanation": next((x for x in L["explanations"]["drivers"] if x["id"] == d["id"]), None),
                        "action": next((x for x in L["actions"] if x["subject_ref"] == d["id"]), None), "bridge_step": next((s for s in L["bridge"]["steps"] + L["bridge"]["to_net_income"]["steps"] if s["id"] == d["id"]), None),
                        "layers": next((x for x in (L.get("layers") or {}).get("drivers", []) if x["id"] == d["id"]), None),
                        "hierarchy": ({**L["hierarchy"][d["id"]], "source": f"{LP}.hierarchy[{d['id']}]",
                                       "how_to_cite": f"a sub-group's figure: {LP}.hierarchy[{d['id']}].nodes[<node id>].movement (L5), {LP}.hierarchy[{d['id']}].nodes[<node id>].children[<node id>].movement (L6)"}
                                      if d["id"] in (L.get("hierarchy") or {}) else None),
                        "memos": memo_for(p, L, LP, "drivers", d["id"]),
                        "memos_run_rate": memo_table(((p.get("memos") or {}).get("run_rate") or {}).get("drivers", {}).get(d["id"]), f"memos.run_rate.drivers[{d['id']}]")})
        elif a.op == "account":
            x = next((q for q in L["accounts"] if q["id"] == a.id), None) or sys.exit(json.dumps({"status": "REFUSED", "reason": f"unknown account {a.id}"}))
            acc = next(q for q in p["accounts"] if q["id"] == a.id)
            out.update({"account": {**x, "name": acc["name"], "source": f"{LP}.accounts[{a.id}]"}, "signals": {**p["signals"][a.id], "source": f"signals[{a.id}]"},
                        "path": {"l3": acc.get("l3"), "l4": acc.get("l4"), "l5": acc.get("l5"), "l6": acc.get("l6"), "driver": x["driver_ref"], "nodes": acc.get("node_path") or [],
                                 "sources": [f"{LP}.hierarchy[{x['driver_ref']}].nodes[{nid}]" if i == 0 else f"{LP}.hierarchy[{x['driver_ref']}].nodes[{(acc.get('node_path') or [])[0]}].children[{nid}]" for i, nid in enumerate(acc.get("node_path") or [])]},
                        "explanation": next((e for e in L["explanations"]["accounts"] if e["id"] == a.id), None),
                        "series_last_13": {k: acc["series"][k][-13:] for k in ("actual", "py", "budget", "variance_vs_budget")}, "periods_last_13": [q["label"] for q in p["meta"]["periods"][-13:]],
                        "layers": next((q for q in (L.get("layers") or {}).get("accounts", []) if q["id"] == a.id), None),
                        "memos": memo_for(p, L, LP, "accounts", a.id),
                        "memos_one_offs": [{**x, "evidence_ref": f"memos.one_offs[{x['id']}]"} for x in (p.get("memos") or {}).get("one_offs", []) if x["account"] == a.id]})
        elif a.op == "memos":
            M = p.get("memos") or {}
            if not M.get("available"):
                out["memos"] = {"available": False, "reason": M.get("reason")}
            elif a.id:
                kind = "drivers" if a.id in {d["id"] for d in L["drivers"]} else "accounts"
                out["memos"] = memo_for(p, L, LP, kind, a.id)
            else:
                me = L.get("memo_evidence") or {}
                out["memos"] = {"available": me.get("available", False), "basis": me.get("basis"), "note": me.get("note"), "months": me.get("months"), "comparator_months": me.get("comparator_months"),
                                "net_income": memo_for(p, L, LP, "net_income", None),
                                "drivers": {d["id"]: memo_for(p, L, LP, "drivers", d["id"], 5) for d in sorted(L["drivers"], key=lambda d: -abs(d["variance"] or 0)) if d["tier"] in ("executive", "management")},
                                "run_rate_months": (M.get("run_rate") or {}).get("months"), "one_offs": [{**x, "evidence_ref": f"memos.one_offs[{x['id']}]"} for x in M.get("one_offs", [])[:15]],
                                "restricted_terms": M.get("restricted_terms"), "rules": MEMO_RULES}
        elif a.op == "accounts":
            rows = [x for x in L["accounts"] if not a.tier or x["tier"] == a.tier]
            out["accounts"] = [{"id": x["id"], "name": next(q["name"] for q in p["accounts"] if q["id"] == x["id"]), "section": x["section"], "driver_ref": x["driver_ref"], "tier": x["tier"], "rank": x.get("rank"),
                                "actual": x["actual"], "comparator": x["comparator"], "variance": x["variance"], "variance_pct": x["variance_pct"], "fired": p["signals"][x["id"]]["fired"], "source": f"{LP}.accounts[{x['id']}]"}
                               for x in sorted(rows, key=lambda q: -abs(q["variance"] or 0))]
        elif a.op == "insights":
            out["insights"] = L["insights"][:a.top]
        elif a.op == "actions":
            out["actions"] = L["actions"]
        elif a.op == "patterns":
            out["patterns"] = L["patterns"]
        elif a.op == "kpis":
            out["kpis"] = [{**k, "source": f"{LP}.kpis[{k['id']}]"} for k in L["kpis"]]; out["kpi_diagnoses"] = L["kpi_diagnoses"]
        elif a.op == "readout":
            out["readout"] = L["readout"]
        elif a.op == "story":
            out["story"] = L["story"]
        elif a.op == "headline":
            out["headline"] = L["headline"]
        elif a.op == "layers":
            out["layers"] = L.get("layers")
        elif a.op == "bridge":
            out["bridge"] = L["bridge"]
        elif a.op == "explanation":
            out["explanation"] = (next((e for e in L["explanations"]["accounts"] if e["id"] == a.id), None) or next((e for e in L["explanations"]["drivers"] if e["id"] == a.id), None)
                                  or next((e for e in L["explanations"]["lines"] if e["id"] == a.id), None) or (L["explanations"]["summary"] if a.id == "summary" else None))
        else:
            sys.exit(json.dumps({"status": "REFUSED", "reason": f"unknown op {a.op}"}))
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
