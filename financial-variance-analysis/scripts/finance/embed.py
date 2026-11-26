"""The read-view of a validated payload that the renderer embeds in the HTML.

An Artifact page is capped at 16 MB. The full payload carries prose, number registers, test evidence and scoring for
every account in all eight lenses, which the page never reads; at production scale (~1,700 accounts) it runs to tens
of MB. The full payload stays on disk for the brief, the diagnosis gate and audit. Only this view is embedded.

Stage A (lossless): drop fields the pinned page (artifacts/finance_analytics/finance_analytics.js) never reads, and
  reduce the blocks it reads only in part (explanations, run-rate, pattern tests) to the keys it reads.
  The lists below come from an audit of renderer 1.9.1. As a guard, a field in a *_DROP list is dropped only when its
  name appears nowhere in the pinned JS as a word: if a later JS reads it, it stays in the page (and `kept_by_guard`
  in the report names it so the list can be tidied).
Stage B (only when the page is still over the limit): for accounts immaterial in every available lens, drop the
  drill-down evidence table and the pattern / run-rate detail. Totals, tables, trends, splits and sub-groups stay whole.

If the JS starts reading a key inside a reduced block (the *_KEEP lists), add it there; test_finance_pipeline.py renders
the page from the view and from the full payload and compares the opening DOM and every drill-down in every lens.
"""
import copy
import json
import re

PAGE_LIMIT_BYTES = 16_000_000          # Artifact page cap is 16 MB; keep a margin under 16 MiB

# fields the page never reads (audited against finance_analytics.js, renderer 1.9.1); dropped only if the JS never names them
LENS_DROP = ("story", "readout", "layers", "insights", "one_offs")      # whole lens sections
LENS_ACCOUNT_DROP = ("actual_po", "comparator_po", "months_with_actual", "months_with_comparator", "pct_of_revenue",
                     "tier", "movement_tier", "rank", "budget_status", "sign_flip")
LENS_DRIVER_DROP = LENS_ACCOUNT_DROP + ("one_sided_movement", "two_sided_movement")
BRIDGE_STEP_DROP = ("tier", "contributions", "comparator_missing")    # the page draws steps from label / value / kind / id
ACTION_DROP = ("layers", "rule_label", "expected_output", "persistence_label", "secondary", "score", "score_components", "rank")
KPI_DIAG_DROP = ("decomposition", "evidence_refs")
HEADLINE_DROP = ("slots", "forbidden")
ACCOUNT_DROP = ("l2", "l3", "l4", "l5", "l6", "node_path")
SIGNAL_DROP = ("persistence_label", "confidence", "volatility")
SERIES_DROP = ("yoy_pct",)
# blocks the page reads only in part: keep these keys
RUNRATE_KEEP = ("eligible", "min", "max", "reference")
NUMBER_KEEP = ("display", "source", "kind")                       # evidence() shows display + source of non-literal figures
PERSISTENT_GAP_EVIDENCE = ("months_same_side", "months_compared")  # the only test evidence the page reads
# names the JS uses for another object, so the word guard cannot tell; the DOM comparison in the test covers them
GUARD_EXEMPT = {"insights", "readout"}
# GL memo text (and the names in it) is review evidence only: never embedded in the page, whatever the JS names
NEVER_EMBED_LENS, NEVER_EMBED_TOP = ("memo_evidence",), ("memos",)   # the page reads summary.insights and the diagnosis readout{}, never lens.insights or lens.readout


def size(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _dropper(js):
    """pop(obj, names): remove the names the JS never mentions; remember the ones it does."""
    named, kept = {}, set()

    def pop(obj, names):
        for k in names:
            if k not in obj:
                continue
            if k not in named:
                named[k] = js is not None and k not in GUARD_EXEMPT and re.search(r"\b%s\b" % re.escape(k), js) is not None
            if named[k]:
                kept.add(k)
            else:
                del obj[k]
    return pop, kept


def _never_embed(view):
    for k in NEVER_EMBED_TOP:
        view.pop(k, None)
    for L in view.get("lenses", {}).values():
        for k in NEVER_EMBED_LENS:
            L.pop(k, None)


def _stage_a(view, pop):
    for L in view["lenses"].values():
        if not L.get("available"):
            continue
        pop(L, LENS_DROP)
        for a in L.get("accounts", []):
            pop(a, LENS_ACCOUNT_DROP)
        for d in L.get("drivers", []):
            pop(d, LENS_DRIVER_DROP)
        b = L.get("bridge") or {}
        for s in (b.get("steps") or []) + ((b.get("to_net_income") or {}).get("steps") or []):
            pop(s, BRIDGE_STEP_DROP)
        for a in L.get("actions", []):
            pop(a, ACTION_DROP)
        for k in L.get("kpi_diagnoses", []):
            pop(k, KPI_DIAG_DROP)
        if isinstance(L.get("headline"), dict):
            pop(L["headline"], HEADLINE_DROP)
        X = L.get("explanations") or {}
        recs = []
        for x in X.get("accounts", []):       # the page reads explanations only as xacct(id).numbers
            nums = [{k: n[k] for k in NUMBER_KEEP if k in n} for n in x.get("numbers", []) if n.get("kind") != "literal"]
            if nums:                          # a record with no figures renders nothing; a missing one is handled
                recs.append({"id": x["id"], "numbers": nums})
        L["explanations"] = {"accounts": recs}
    for a in view.get("accounts", []):
        pop(a, ACCOUNT_DROP)
    for s in view.get("statement_series", []):
        pop(s, SERIES_DROP)
    for s in (view.get("signals") or {}).values():
        pop(s, SIGNAL_DROP)
        s["runrate"] = {k: s["runrate"].get(k) for k in RUNRATE_KEEP}
        tests = []
        for t in s.get("tests", []):
            q = {"id": t["id"], "label": t["label"], "state": t["state"]}
            if t["id"] == "persistent_gap" and t["state"] == "fired":
                q["evidence"] = {k: (t.get("evidence") or {}).get(k) for k in PERSISTENT_GAP_EVIDENCE}
            tests.append(q)
        s["tests"] = tests


def _immaterial_everywhere(payload):
    tiers = {}
    for L in payload["lenses"].values():
        if not L.get("available"):
            continue
        for a in L.get("accounts", []):
            tiers.setdefault(a["id"], set()).add(a.get("tier"))
    return {aid for aid, t in tiers.items() if t <= {"immaterial"}}


def _stage_b(view, minor):
    for L in view["lenses"].values():
        if L.get("available"):
            L["explanations"]["accounts"] = [x for x in L["explanations"]["accounts"] if x["id"] not in minor]
    for aid in minor:
        s = (view.get("signals") or {}).get(aid)
        if s is None:
            continue
        s["tests"] = [t for t in s["tests"] if t["state"] == "fired"]
        s["runrate"] = {"eligible": False, "min": None, "max": None, "reference": None}


def embed_view(payload, build_html, js=None, limit_bytes=PAGE_LIMIT_BYTES, trim=True):
    """Return (html, report). build_html(view) -> str makes the page; js is the pinned page script (the drop guard).
    Never mutates `payload`. report['over_limit'] is True when even stage B leaves the page above the limit (the
    caller refuses)."""
    full = size(payload)
    if not trim:
        view = copy.deepcopy(payload)
        _never_embed(view)
        html = build_html(view)
        n = len(html.encode("utf-8"))
        return html, {"stage": "none", "full_bytes": full, "embedded_bytes": full, "page_bytes": n,
                      "accounts_trimmed": 0, "limit_bytes": limit_bytes, "over_limit": n > limit_bytes}
    view = copy.deepcopy(payload)
    _never_embed(view)
    pop, kept = _dropper(js)
    _stage_a(view, pop)
    report = {"stage": "A", "full_bytes": full, "accounts_trimmed": 0, "limit_bytes": limit_bytes}
    html = build_html(view)
    if len(html.encode("utf-8")) > limit_bytes:
        minor = _immaterial_everywhere(payload)
        _stage_b(view, minor)
        report.update({"stage": "B", "accounts_trimmed": len(minor)})
        html = build_html(view)
    report["embedded_bytes"] = size(view)
    report["page_bytes"] = len(html.encode("utf-8"))
    report["over_limit"] = report["page_bytes"] > limit_bytes
    report["kept_by_guard"] = sorted(kept)
    return html, report
