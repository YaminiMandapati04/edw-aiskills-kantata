"""The diagnosis admission gate (contract sda.gtm-diagnosis/1.0.0, references/diagnosis.md), ported from the finance
skill's gate. The model writes diagnosis.json for one view (lens) of the payload; this module admits only what the payload
supports: every figure registered and resolving to the payload value, no causal wording in a fact, no forbidden phrase,
no stale payload, every drill target one the page can open, roles and counts as contracted. Fix the diagnosis, never the
payload. `admit()` attaches the admitted diagnoses to the payload for the renderer; nothing is derived in the browser."""
import datetime as dt
import json
import re

from . import DIAGNOSIS_CONTRACT
from .common import BuildError, is_num, resolve_path, unregistered_tokens

STATES = {"observed_fact", "analytical_inference", "hypothesis", "management_input_required"}
PERSISTENCE = {"one_off", "recurring", "seasonal", "timing", "persistent", "undetermined"}
RISKS = ("not_closing", "stuck", "high_value", "lost")
CAUSAL = re.compile(r"\b(because|due to|driven by|caused by|as a result of|owing to|thanks to|explained by)\b", re.I)
FORBIDDEN = [(re.compile(r"\bhigher than expected\b", re.I), "higher than expected"), (re.compile(r"\blower than expected\b", re.I), "lower than expected"),
             (re.compile(r"\broot cause\b(?! (is|remains|stays) (open|unknown|not))", re.I), "root cause (as a claim)"),
             (re.compile(r"\b(confirmed|verified) (cause|root cause)\b", re.I), "confirmed / verified cause"),
             (re.compile(r"\bwill (close|recover|reverse|persist|convert)\b", re.I), "a forecast asserted as fact"),
             (re.compile(r"\b(assigned to|owned by)\b", re.I), "an assignment (owners are suggested only)"),
             (re.compile(r"\bstalled\b(?![^.]*\bproxy\b)", re.I), "'stalled' without saying stage age is a proxy")]
# attribution down the bookings hierarchy (measure, product, subsidiary) is arithmetic the bridge proves
ATTRIBUTION = re.compile(r"\b(driven by|led by)\b", re.I)
HEDGE = re.compile(r"\b(appears?|suggests?|potentially|potential|may|might|could|possibly|to be confirmed|unconfirmed|not (yet )?confirmed)\b", re.I)
# business context the GTM view does not carry: written only as a hedged possibility, named in unverified[]
OPERATIONAL = re.compile(r"\b(pricing|price (changes?|increases?|cuts?)|discount(s|ing)?|competitors?|competition|budget freezes?|macro|economy|"
                         r"hiring|headcount|quota|territor(y|ies)|rep (turnover|attrition)|marketing spend|campaigns?|product launch(es)?|"
                         r"churn(ed)?|renewals?|procurement|legal review)\b", re.I)
SUMMARY_TONES = {"favourable": "fav", "unfavourable": "unf", "neutral": "neu", "outlook": "ink"}
TABS = ("pipeline", "bookings")
MIN_BULLETS, MAX_BULLETS = 3, 5
MAX_BULLET_WORDS, MAX_DETAIL_WORDS, MAX_HEAD_WORDS, MAX_ASK_WORDS, MAX_ASK_DETAIL_WORDS, MIN_MEANING_WORDS = 30, 110, 10, 12, 45, 8
MAX_PAGE_WORDS, MAX_MEANING = 200, {"bookings_meaning": 3, "pipeline_meaning": 3, "outlook_meaning": 4}
MAX_MEANING_WORDS = 45


# ------------------------------------------------------------------ numbers and statements

def _nums_ok(payload, numbers, where, errs):
    for n in numbers or []:
        if n.get("kind") == "literal":
            continue
        src = n.get("source")
        if not src:
            errs.append(f"{where}: number {n.get('display')} has no source"); continue
        try:
            v = resolve_path(payload, src)
        except (KeyError, IndexError, TypeError):
            errs.append(f"{where}: source {src} does not resolve"); continue
        if isinstance(v, list):
            v = len(v)
        if not is_num(v) or not is_num(n.get("value")):
            errs.append(f"{where}: {src} is not a number"); continue
        vv = v * n["scale"] if n.get("scale") is not None else v
        if n.get("transform") == "abs":
            vv = abs(vv)
        tol = 0.0006 if n.get("kind") == "pct" else 0.05 if n.get("kind") in ("mult", "days") else 0.5
        if abs(vv - n["value"]) > tol:
            errs.append(f"{where}: {n.get('display')} ({n['value']}) differs from {src} ({v})")


def _wording_ok(text, where, errs, unverified=None, strict_cause=False):
    for rx, label in FORBIDDEN:
        if rx.search(text):
            errs.append(f"{where}: forbidden phrase: {label}")
    for sent in [x for x in re.split(r"(?<=[.!?;:])\s+", text or "") if x.strip()]:
        for m in CAUSAL.finditer(sent):
            if strict_cause or (not ATTRIBUTION.fullmatch(m.group(0)) and not HEDGE.search(sent)):
                errs.append(f"{where}: causal wording ('{m.group(0)}') without evidence; attribute down the bookings hierarchy "
                            "('driven by <measure or product>') or hedge it ('may be due to', 'to be confirmed')")
        op = OPERATIONAL.search(sent)
        if op and unverified is not None:
            if not HEDGE.search(sent):
                errs.append(f"{where}: '{op.group(0)}' is not in the GTM view; write it as a possibility ('appears', 'may', 'to be confirmed')")
            if not unverified:
                errs.append(f"{where}: names a cause the view does not carry ('{op.group(0)}'); list it in unverified[]")


def _statement_ok(payload, st, where, errs):
    if st.get("state") not in STATES:
        errs.append(f"{where}: state must be one of {sorted(STATES)}"); return
    text, nums = st.get("text") or "", st.get("numbers") or []
    bad = unregistered_tokens(text, nums)
    if bad:
        errs.append(f"{where}: unregistered figure(s): {', '.join(bad)}")
    _nums_ok(payload, nums, where, errs)
    _wording_ok(text, where, errs, strict_cause=st["state"] in ("observed_fact", "analytical_inference"))
    if st["state"] == "observed_fact" and not nums and not st.get("evidence_refs"):
        errs.append(f"{where}: an observed fact carries a number or an evidence reference")
    if st["state"] == "hypothesis":
        h = st.get("hypothesis") or {}
        if not h.get("missing_evidence") or not h.get("closes_with"):
            errs.append(f"{where}: a hypothesis carries missing_evidence[] and closes_with")
    for ref in st.get("evidence_refs") or []:
        try:
            resolve_path(payload, ref)
        except (KeyError, IndexError, TypeError):
            errs.append(f"{where}: evidence_ref {ref} does not resolve")


# ------------------------------------------------------------------ drill targets the page can open

def _drivers(L):
    return {d["id"]: d for k in ("measure", "product", "subsidiary") for d in (L.get("drivers") or {}).get(k, [])}


def page_refs(payload, L):
    """Every data-ref the page can open for this lens (the renderer's openDrawer kinds)."""
    rk, pipe, out = payload.get("risk") or {}, payload.get("pipeline") or {}, payload.get("outlook") or {}
    refs = {"velocity", "pipe:open", "conc:customers", "conv:win", "conv:loss"}
    refs |= {"kpi:" + k["id"] for k in L.get("kpis", [])}
    refs |= {"driver:" + d for d in _drivers(L)}
    refs |= {"quarter:" + str(r.get("quarter")) for r in pipe.get("by_close_quarter") or [] if r.get("quarter")}
    refs |= {"quarter:" + str(r.get("quarter")) for r in (pipe.get("coverage") or {}).get("by_quarter") or [] if r.get("quarter")}   # views with a pipeline target
    refs |= {"scenario:" + str(s.get("quarter")) for s in out.get("scenario") or [] if s.get("quarter")}
    acts = list(L.get("pipeline_actions") or []) + list(L.get("actions") or []) + list(rk.get("actions") or [])
    refs |= {"action:" + a["id"] for a in acts if a.get("id")}
    if rk:
        refs |= {"rk:not_closing", "rk:stuck", "rk:high_value"}
        if rk.get("at_risk"):
            refs.add("rk:at_risk")
        hv = rk.get("high_value") or {}
        if hv.get("not_closing"):
            refs.add("rk:hv_not_closing")
        if hv.get("stuck"):
            refs.add("rk:hv_stuck")
        refs |= {"rk:cust:" + c["id"] for c in (rk.get("stuck") or {}).get("customers", []) if c.get("id")}
    if L.get("lost"):
        refs.add("rk:lost")
    refs |= {"risk:" + r[3:] for r in refs if r.startswith("rk:")}      # the page opens risk:<id> the same as rk:<id>
    return refs


def _risk_flagged(payload, L):
    """The pipeline-risk blocks the page flags: each needs a finding or an unresolved entry."""
    rk, out = payload.get("risk") or {}, []
    if (rk.get("not_closing") or {}).get("count"):
        out.append("not_closing")
    if (rk.get("stuck") or {}).get("available", True) and (rk.get("stuck") or {}).get("count"):
        out.append("stuck")
    if ((rk.get("high_value") or {}).get("flagged") or {}).get("count"):
        out.append("high_value")
    return out


# ------------------------------------------------------------------ the gate

def validate_diagnosis(payload, diag):
    errs, warns = [], []
    if diag.get("contract") != DIAGNOSIS_CONTRACT:
        errs.append(f"contract must be {DIAGNOSIS_CONTRACT}"); return errs, warns
    if diag.get("payload_hash") != payload.get("analysis_hash"):
        errs.append("payload_hash does not match the payload's analysis_hash: the diagnosis is stale; rewrite it against the current payload")
    lens = diag.get("lens") or {}
    key = f"{lens.get('window')}_{lens.get('basis')}"
    L = (payload.get("lenses") or {}).get(key)
    if not L or not L.get("available"):
        errs.append(f"lens {key} is not in the payload or not available"); return errs, warns
    drivers, refs = _drivers(L), page_refs(payload, L)
    findings = diag.get("findings") or []
    if not findings:
        errs.append("findings[] is empty")
    ids, scoped_drivers, scoped_risks = set(), set(), set()
    for f in findings:
        fid = f.get("id") or "?"
        where = f"findings[{fid}]"
        if fid in ids:
            errs.append(f"{where}: duplicate id")
        ids.add(fid)
        if not f.get("title"):
            errs.append(f"{where}: title missing")
        sc = f.get("scope") or {}
        for d in sc.get("drivers") or []:
            if d not in drivers:
                errs.append(f"{where}: unknown driver {d}")
            scoped_drivers.add(d)
        for r in sc.get("risks") or []:
            if r not in RISKS:
                errs.append(f"{where}: unknown risk block {r} (one of {list(RISKS)})")
            scoped_risks.add(r)
        if f.get("persistence") not in PERSISTENCE:
            errs.append(f"{where}: persistence must be one of {sorted(PERSISTENCE)}")
        for k in ("confidence", "decision_relevance"):
            if f.get(k) not in ("high", "medium", "low"):
                errs.append(f"{where}: {k} must be high, medium or low")
        sts = f.get("statements") or []
        if not sts:
            errs.append(f"{where}: statements[] is empty")
        for i, st in enumerate(sts):
            _statement_ok(payload, st, f"{where}.statements[{i}]", errs)
        if not any(st.get("state") == "observed_fact" for st in sts):
            errs.append(f"{where}: at least one observed_fact statement is required")
        if f.get("persistence") in ("recurring", "persistent", "timing") and not any(st.get("state") in ("analytical_inference", "hypothesis") for st in sts):
            errs.append(f"{where}: a persistence claim needs an inference or hypothesis statement")
        if not f.get("management_questions"):
            warns.append(f"{where}: no management question; every finding that is not a verified cause should carry one")
    # coverage: every executive-tier driver and every flagged pipeline-risk block has a finding or an unresolved entry
    unresolved = {x.get("ref") if isinstance(x, dict) else str(x) for x in (diag.get("unresolved") or [])}
    for did, d in drivers.items():
        if d.get("tier") == "executive" and did not in scoped_drivers and did not in unresolved:
            errs.append(f"executive-tier driver {did} has no finding and is not listed in unresolved[]")
    for r in _risk_flagged(payload, L):
        if r not in scoped_risks and r not in unresolved and "rk:" + r not in unresolved:
            errs.append(f"flagged pipeline-risk block {r} has no finding and is not listed in unresolved[]")
    ro = diag.get("readout") or {}
    sm = ro.get("summary") or {}
    for tab in TABS:
        if not sm.get(tab):
            errs.append(f"readout.summary.{tab} is required: the written executive summary (bullets[] of {MIN_BULLETS} to {MAX_BULLETS}, decisions[] of 2 to 3) for the {tab.title()} tab")
        else:
            _summary_ok(payload, refs, sm[tab], ids, f"readout.summary.{tab}", errs, tab)
    for name, mx in MAX_MEANING.items():
        arr = ro.get(name) or []
        if len(arr) > mx:
            errs.append(f"readout.{name} holds at most {mx}")
        for i, st in enumerate(arr):
            where = f"readout.{name}[{i}]"
            _statement_ok(payload, {"state": st.get("state", "analytical_inference"), "text": st.get("text", ""), "numbers": st.get("numbers", []),
                                    "evidence_refs": st.get("evidence_refs", ["lenses"]), "hypothesis": st.get("hypothesis")}, where, errs)
            if len((st.get("text") or "").split()) > MAX_MEANING_WORDS:
                errs.append(f"{where}: at most {MAX_MEANING_WORDS} words")
            if st.get("finding_ref") and st["finding_ref"] not in ids:
                errs.append(f"{where}: finding_ref does not name a finding")
    if not ro.get("outlook_meaning"):
        warns.append("readout.outlook_meaning is empty: the Outlook tab keeps the engine's note under What this means")
    qc = ro.get("qc") or {}
    for k in ("business_cause", "open_gaps"):
        if k not in qc:
            warns.append(f"readout.qc.{k} missing")
    return errs, warns


def _summary_ok(payload, refs, sm, ids, at, errs, tab):
    bullets = sm.get("bullets") or []
    if not MIN_BULLETS <= len(bullets) <= MAX_BULLETS:
        errs.append(f"{at}.bullets must hold {MIN_BULLETS} to {MAX_BULLETS} bullets, not {len(bullets)}")
    page = sum(len((b.get("head") or "").split()) + len((b.get("text") or "").split()) for b in bullets)
    if page > MAX_PAGE_WORDS:
        errs.append(f"{at}: the page lines (heads and texts) run {page} words; the executive summary is at most {MAX_PAGE_WORDS}")
    for i, b in enumerate(bullets):
        where = f"{at}.bullets[{i}]"
        head, text, detail = (b.get("head") or "").strip(), (b.get("text") or "").strip(), (b.get("detail") or "").strip()
        if not head or len(head.split()) > MAX_HEAD_WORDS or re.search(r"\d", head):
            errs.append(f"{where}: head is a bold lead of at most {MAX_HEAD_WORDS} words with no figures")
        if not text or len(text.split()) > MAX_BULLET_WORDS:
            errs.append(f"{where}: text is the line shown on the page, at most {MAX_BULLET_WORDS} words ({len(text.split())} given)")
        if not detail or len(detail.split()) > MAX_DETAIL_WORDS:
            errs.append(f"{where}: detail (the full reading shown when the bullet is opened) is required, at most {MAX_DETAIL_WORDS} words")
        nums = b.get("numbers") or []
        for part, s in (("text", text), ("detail", detail)):
            bad = unregistered_tokens(s, nums)
            if bad:
                errs.append(f"{where}: unregistered figure(s) in {part}: {', '.join(bad)}")
        _nums_ok(payload, nums, where, errs)
        bare = detail
        for n in nums:
            bare = bare.replace(str(n.get("display", "")), " ")
        if len(re.findall(r"[A-Za-z][A-Za-z'-]+", bare)) < MIN_MEANING_WORDS:
            errs.append(f"{where}: a figure alone is not an insight; say what it means (observation, then meaning)")
        _wording_ok(head + ". " + text + " " + detail, where, errs, unverified=b.get("unverified") or [])
        if b.get("tone") not in SUMMARY_TONES:
            errs.append(f"{where}: tone must be one of {sorted(SUMMARY_TONES)}")
        if b.get("ref") not in refs:
            errs.append(f"{where}: ref {b.get('ref')!r} is not a detail the page can open in this view")
        if b.get("finding_ref") and b["finding_ref"] not in ids:
            errs.append(f"{where}: finding_ref does not name a finding")
    if bullets and tab == "bookings" and "bookings" not in " ".join(str(bullets[0].get(k) or "") for k in ("head", "text", "detail")).lower():
        errs.append(f"{at}.bullets[0]: the first Bookings bullet is about total bookings")
    decs = sm.get("decisions") or []
    if not 2 <= len(decs) <= 3:
        errs.append(f"{at}.decisions must hold 2 or 3 questions, not {len(decs)}")
    for i, d in enumerate(decs):
        where = f"{at}.decisions[{i}]"
        text, detail = (d.get("text") or "").strip(), (d.get("detail") or "").strip()
        if not text.endswith("?"):
            errs.append(f"{where}: a decision is a question (ends with ?)")
        if len(text.split()) > MAX_ASK_WORDS:
            errs.append(f"{where}: the question on the page is at most {MAX_ASK_WORDS} words; the full question goes in detail")
        if re.search(r"\d", text):
            errs.append(f"{where}: the question on the page carries no figures; they belong in detail")
        if detail and (len(detail.split()) > MAX_ASK_DETAIL_WORDS or not detail.endswith("?")):
            errs.append(f"{where}: detail is the full question, at most {MAX_ASK_DETAIL_WORDS} words, ending with ?")
        if not d.get("owner"):
            errs.append(f"{where}: suggested owner missing")
        nums = d.get("numbers") or []
        bad = unregistered_tokens(detail, nums)
        if bad:
            errs.append(f"{where}: unregistered figure(s) in detail: {', '.join(bad)}")
        _nums_ok(payload, nums, where, errs)
        if d.get("amount") is not None:
            _nums_ok(payload, [d["amount"]], where + ".amount", errs)
        _wording_ok(text + " " + detail, where, errs)
        if d.get("ref") not in refs:
            errs.append(f"{where}: ref {d.get('ref')!r} is not a detail the page can open in this view")
        if d.get("finding_ref") and d["finding_ref"] not in ids:
            errs.append(f"{where}: finding_ref does not name a finding")


# ------------------------------------------------------------------ admission for the renderer

def admit(payload, paths, allow_missing=False):
    """Validate each diagnosis file against the payload and attach the admitted ones (payload["diagnoses"], keyed by
    lens id, and payload["review"]). The primary view needs an admitted review unless allow_missing. Raises BuildError
    with the gate's reasons; no page is written then."""
    diags = {}
    for path in paths or []:
        try:
            with open(path, encoding="utf-8") as fh:
                diag = json.load(fh)
        except Exception as exc:
            raise BuildError(f"diagnosis {path} is not readable JSON: {exc}")
        errs, warns = validate_diagnosis(payload, diag)
        if errs:
            raise BuildError(f"diagnosis {path} refused by the admission gate (fix the diagnosis, never the payload): " + " | ".join(errs[:30]))
        key = f"{diag['lens']['window']}_{diag['lens']['basis']}"
        if key in diags:
            raise BuildError(f"two diagnoses for the {key} view; keep one")
        diag = dict(diag, admitted_at=dt.datetime.now().isoformat(timespec="seconds"), warnings=warns)
        diags[key] = diag
    primary = payload["meta"]["primary_lens"]["id"]
    required = [primary] if (payload["lenses"].get(primary) or {}).get("available") else []
    missing = [k for k in required if k not in diags]
    if missing and not allow_missing:
        raise BuildError(f"the opening view ({primary}) needs an admitted AI review before the page is published; no page written "
                         "(write it with gtm_brief.py and pass --diagnosis, or pass --allow-missing-review to publish with a visible notice)")
    payload["diagnoses"] = diags
    payload["review"] = {"required": required, "admitted": sorted(diags), "missing": missing}
    return {"admitted": sorted(diags), "missing": missing, "warnings": {k: d["warnings"] for k, d in diags.items()}}
