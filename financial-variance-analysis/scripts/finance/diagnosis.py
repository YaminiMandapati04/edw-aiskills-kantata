"""The diagnosis admission gate. The model writes diagnosis.json (contract
sda.finance-diagnosis/1.0.0, see references/diagnosis.md); this module admits
only statements the payload supports: every figure registered and resolving,
no causal wording in a fact, no forbidden phrase, no stale reference, roles
and counts as contracted. Fix the diagnosis, never the payload."""
import re

from . import DIAGNOSIS_CONTRACT
from .common import is_num, resolve_path, unregistered_tokens

STATES = {"observed_fact", "analytical_inference", "hypothesis", "management_input_required"}
ROLES = {"current_period_driver", "performance_quality", "forward_looking"}
PERSISTENCE = {"one_off", "recurring", "seasonal", "timing", "persistent", "coverage", "undetermined"}
CAUSAL = re.compile(r"\b(because|due to|driven by|caused by|as a result of|owing to|thanks to|explained by)\b", re.I)
FORBIDDEN = [(re.compile(r"\bhigher than expected\b", re.I), "higher than expected"), (re.compile(r"\blower than expected\b", re.I), "lower than expected"),
             (re.compile(r"\bbusiness needs\b", re.I), "business needs"), (re.compile(r"\broot cause\b(?! (is|remains|stays) (open|unknown|not))", re.I), "root cause (as a claim)"),
             (re.compile(r"\b(confirmed|verified) (cause|root cause)\b", re.I), "confirmed / verified cause"),
             (re.compile(r"\bwill (recover|reverse|persist)\b", re.I), "a forecast asserted as fact"),
             (re.compile(r"\b(assigned to|owned by)\b", re.I), "an assignment (owners are suggested only)")]
TIMING = re.compile(r"\btiming\b", re.I)
# GL memos are evidence, not page text: no name from a memo (vendor, customer, person, system) and no document number
DOCREF = re.compile(r"#\s*\d|\b\d{7,}\b")           # account numbers are six digits; document numbers run longer
NO_TEXT_KEYS = {"source", "evidence_refs", "id", "finding_ref", "ids", "support", "drill", "action_refs", "account", "scope", "contract", "payload_hash",
                "lens", "written_by", "claim", "tone", "role", "state", "status", "persistence", "kind", "transform", "addresses_tests", "claim_types",
                "decision_relevance", "confidence", "controllability", "level", "ref"}


def _texts(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in NO_TEXT_KEYS:
                yield from _texts(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _texts(v, f"{path}[{i}]")


def _memo_names_ok(payload, diag, errs):
    """Refuse a name taken from a GL memo, or a document number, anywhere in the review: memos inform it, they are not quoted."""
    terms = (payload.get("memos") or {}).get("restricted_terms") or []
    # matched as written (capitalised, or an acronym): a name keeps its capital; a common word in prose does not
    rx = [(t, re.compile(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])")) for t in terms]
    hits = {}
    for where, text in _texts({k: v for k, v in diag.items() if k in ("findings", "unresolved", "readout")}):
        for t, r in rx:
            if r.search(text):
                hits.setdefault(t, where)
        if DOCREF.search(text):
            hits.setdefault("a document number", where)
    for t, where in list(hits.items())[:12]:
        errs.append(f"{where}: '{t}' comes from a GL memo (a vendor, customer, person or system name, or a document number); describe the posting in accounting words instead")


def _memo_timing(payload, refs):
    """A cited memo theme that is an accrual or a reversal naming an earlier month supports a timing reading."""
    for ref in refs or []:
        if "memo_evidence" not in ref and not ref.startswith("memos."):
            continue
        try:
            t = resolve_path(payload, ref)
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(t, dict) and "accrual_reversal" in (t.get("tags") or []):
            return True
    return False


def _nums_ok(payload, numbers, where, errs):
    for n in numbers:
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
        tol = 0.0006 if n.get("kind") == "pct" else 0.5
        if abs(vv - n["value"]) > tol:
            errs.append(f"{where}: {n.get('display')} ({n['value']}) differs from {src} ({v})")


def _statement_ok(payload, st, where, errs, allow_timing=False):
    if st.get("state") not in STATES:
        errs.append(f"{where}: state must be one of {sorted(STATES)}"); return
    text = st.get("text") or ""
    nums = st.get("numbers") or []
    bad = unregistered_tokens(text, nums)
    if bad:
        errs.append(f"{where}: unregistered figure(s): {', '.join(bad)}")
    _nums_ok(payload, nums, where, errs)
    for rx, label in FORBIDDEN:
        if rx.search(text):
            errs.append(f"{where}: forbidden phrase: {label}")
    if st["state"] in ("observed_fact", "analytical_inference"):
        if CAUSAL.search(text):
            errs.append(f"{where}: causal wording in a {st['state']} (state it as a hypothesis)")
        if TIMING.search(text) and not allow_timing:
            errs.append(f"{where}: 'timing' in a {st['state']} needs a reversal signal on the account; otherwise state it as a hypothesis")
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
        errs.append(f"lens {key} is not in the payload"); return errs, warns
    drivers = {d["id"] for d in L["drivers"]}
    accounts = {a["id"] for a in L["accounts"]}
    signals = payload.get("signals") or {}
    findings = diag.get("findings") or []
    if not findings:
        errs.append("findings[] is empty")
    ids = set()
    scoped_drivers = set()
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
        for a in sc.get("accounts") or []:
            if a not in accounts:
                errs.append(f"{where}: unknown account {a}")
        allow_timing = any(t["id"] == "reversal_signal" and t["state"] == "fired" for a in (sc.get("accounts") or []) for t in signals.get(a, {}).get("tests", []))             or _memo_timing(payload, [r for st in (f.get("statements") or []) for r in (st.get("evidence_refs") or [])])
        if f.get("persistence") not in PERSISTENCE:
            errs.append(f"{where}: persistence must be one of {sorted(PERSISTENCE)}")
        if f.get("confidence") not in ("high", "medium", "low"):
            errs.append(f"{where}: confidence must be high, medium or low")
        if f.get("decision_relevance") not in ("high", "medium", "low"):
            errs.append(f"{where}: decision_relevance must be high, medium or low")
        sts = f.get("statements") or []
        if not sts:
            errs.append(f"{where}: statements[] is empty")
        for i, st in enumerate(sts):
            _statement_ok(payload, st, f"{where}.statements[{i}]", errs, allow_timing)
        if not any(st.get("state") == "observed_fact" for st in sts):
            errs.append(f"{where}: at least one observed_fact statement is required")
        if f.get("persistence") in ("recurring", "persistent", "timing") and not any(st.get("state") in ("analytical_inference", "hypothesis") for st in sts):
            errs.append(f"{where}: a persistence claim needs an inference or hypothesis statement")
        if not f.get("management_questions"):
            warns.append(f"{where}: no management question; every finding that is not a verified cause should carry one")
    # every executive-tier driver has a finding or is listed as unresolved
    unresolved = set(x.get("ref") if isinstance(x, dict) else str(x) for x in (diag.get("unresolved") or []))
    for d in L["drivers"]:
        if d["tier"] == "executive" and d["id"] not in scoped_drivers and d["id"] not in unresolved:
            errs.append(f"executive-tier driver {d['id']} has no finding and is not listed in unresolved[]")
    ro = diag.get("readout") or {}
    concl = ro.get("conclusions") or []
    if len(concl) != 3:
        errs.append("readout.conclusions must hold exactly three conclusions (one per role)")
    roles = [c.get("role") for c in concl]
    if set(roles) != ROLES and len(concl) == 3:
        errs.append(f"readout.conclusions roles must be exactly {sorted(ROLES)}")
    for i, c in enumerate(concl):
        where = f"readout.conclusions[{i}]"
        if c.get("finding_ref") not in ids:
            errs.append(f"{where}: finding_ref does not name a finding")
        if c.get("status") not in ("favorable", "unfavorable", "mixed"):
            errs.append(f"{where}: status must be favorable, unfavorable or mixed")
        _statement_ok(payload, {"state": c.get("state", "analytical_inference"), "text": c.get("text", ""), "numbers": c.get("numbers", []), "evidence_refs": c.get("evidence_refs", ["lenses"]), "hypothesis": c.get("hypothesis")}, where, errs, True)
        if not c.get("response"):
            errs.append(f"{where}: response (what management should do or decide) missing")
        ins = c.get("insight")                       # optional bold lead of the executive-summary bullet
        if ins is not None:
            if not isinstance(ins, str) or not ins.strip() or len(ins.split()) > 8:
                errs.append(f"{where}: insight must be a short heading of at most eight words")
            elif re.search(r"\d", ins):
                errs.append(f"{where}: insight carries no figures; the numbers belong in text")
            elif CAUSAL.search(ins) or any(rx.search(ins) for rx, _ in FORBIDDEN):
                errs.append(f"{where}: insight uses causal or forbidden wording")
    asks = ro.get("decision_asks") or []
    if len(asks) > 3:
        errs.append("readout.decision_asks holds at most three")
    for i, q in enumerate(asks):
        if q.get("finding_ref") not in ids:
            errs.append(f"readout.decision_asks[{i}]: finding_ref does not name a finding")
        if not q.get("text") or not q.get("owner"):
            errs.append(f"readout.decision_asks[{i}]: text and suggested owner are required")
        bad = unregistered_tokens(q.get("text", ""), q.get("numbers", []))
        if bad:
            errs.append(f"readout.decision_asks[{i}]: unregistered figure(s): {', '.join(bad)}")
        _nums_ok(payload, q.get("numbers", []), f"readout.decision_asks[{i}]", errs)
    for name, mx in (("driver_stories", 3), ("structural_conclusions", 3), ("forecast_assumptions", 5), ("lead_actions", 3)):
        arr = ro.get(name) or []
        if len(arr) > mx:
            errs.append(f"readout.{name} holds at most {mx}")
        for i, st in enumerate(arr):
            _statement_ok(payload, {"state": st.get("state", "analytical_inference"), "text": st.get("text", ""), "numbers": st.get("numbers", []), "evidence_refs": st.get("evidence_refs", ["lenses"]), "hypothesis": st.get("hypothesis")}, f"readout.{name}[{i}]", errs, True)
            if st.get("finding_ref") and st["finding_ref"] not in ids:
                errs.append(f"readout.{name}[{i}]: finding_ref does not name a finding")
    for name in ("driver_stories", "account_interpretations"):
        for i, st in enumerate(ro.get(name) or []):
            n = len((st.get("text") or "").split())
            if n > MAX_DRILL_WORDS:
                errs.append(f"readout.{name}[{i}]: a drill-through narrative is at most {MAX_DRILL_WORDS} words ({n} given)")
    ai = ro.get("account_interpretations") or []
    if len(ai) > 10:
        errs.append("readout.account_interpretations holds at most ten")
    for i, x in enumerate(ai):
        where = f"readout.account_interpretations[{i}]"
        if x.get("account") not in accounts:
            errs.append(f"{where}: unknown account {x.get('account')}")
        _statement_ok(payload, {"state": x.get("state", "analytical_inference"), "text": x.get("text", ""), "numbers": x.get("numbers", []), "evidence_refs": x.get("evidence_refs", [f"lenses[{key}].accounts[{x.get('account')}]"]), "hypothesis": x.get("hypothesis")}, where, errs,
                      any(t["id"] == "reversal_signal" and t["state"] == "fired" for t in signals.get(x.get("account"), {}).get("tests", [])) or _memo_timing(payload, x.get("evidence_refs")))
    hl = ro.get("headline")
    if hl:
        for name, sl in (L.get("headline", {}).get("slots") or {}).items():
            if sl["display"] not in hl:
                errs.append(f"readout.headline: pinned slot {name} ({sl['display']}) is missing from the rephrased headline")
        for rx, label in FORBIDDEN:
            if rx.search(hl):
                errs.append(f"readout.headline: forbidden phrase: {label}")
    qc = ro.get("qc") or {}
    for k in ("business_cause", "open_gaps"):
        if k not in qc:
            warns.append(f"readout.qc.{k} missing")
    _memo_names_ok(payload, diag, errs)
    sm = ro.get("summary")
    if not sm:
        errs.append("readout.summary is required: the written executive summary (bullets[] of 4, decisions[] of 2 to 3) for this view")
    else:
        _summary_ok(payload, L, key, sm, ids, errs, warns)
    return errs, warns


SUMMARY_TONES = {"favourable": "fav", "unfavourable": "unf", "neutral": "neu", "outlook": "ink"}
# the executive narrative, in this order: headline (outcome, primary driver, implication), why (the causal chain down the
# hierarchy), trend (month against quarter and year to date), meaning (optional: margin, growth, sustainability), attention
SUMMARY_ROLES = ["headline", "why", "trend", "meaning", "attention"]
REQUIRED_ROLES = {"headline", "why", "trend", "attention"}
MAX_PAGE_WORDS, MAX_DRILL_WORDS = 220, 75
# attribution down the financial hierarchy is arithmetic the drill proves, so it may be written as such
ATTRIBUTION = re.compile(r"\b(driven by|led by)\b", re.I)
HEDGE = re.compile(r"\b(appears?|suggests?|potentially|potential|may|might|could|possibly|to be confirmed|unconfirmed|not (yet )?confirmed)\b", re.I)
# business-context drivers the finance marts do not carry: written only as a hedged possibility, with the missing data named
OPERATIONAL = re.compile(r"\b(hiring|hires?|headcount|head count|attrition|layoffs?|salary (increases?|growth)|pay rises?|merit increases?|pric(e|ing) (changes?|increases?|cuts?|rises?)|pricing|"
                         r"demand|churn(ed)?|new customers?|customer (acquisition|growth|losses|loss|wins?|count|concentration|base)|product adoption|adoption|"
                         r"acquisitions?|acquired|integration|reorgani[sz]ation|restructuring|inflation|volumes?)\b", re.I)


def _sentences(text):
    return [x for x in re.split(r"(?<=[.!?;:])\s+", text or "") if x.strip()]


def _cause_ok(text, where, errs, unverified):
    """Causal wording: attribution down the hierarchy ("driven by", "led by") is allowed; any other causal phrase only
    hedged in the same sentence ("may be due to"). A business-context driver the data model does not carry (hiring,
    pricing, churn, acquisitions...) is written only as a hedged possibility, and the bullet names it in unverified[]."""
    for sent in _sentences(text):
        for m in CAUSAL.finditer(sent):
            if not ATTRIBUTION.fullmatch(m.group(0)) and not HEDGE.search(sent):
                errs.append(f"{where}: causal wording ('{m.group(0)}') without evidence; attribute down the hierarchy ('driven by <driver>') or hedge it ('may be due to', 'to be confirmed')")
        op = OPERATIONAL.search(sent)
        if op:
            if not HEDGE.search(sent):
                errs.append(f"{where}: '{op.group(0)}' is not in the data model; write it as a possibility ('appears', 'suggests', 'potentially', 'may indicate', 'to be confirmed')")
            if not unverified:
                errs.append(f"{where}: names a driver the data model does not carry ('{op.group(0)}'); list it in unverified[] so the reader knows it is not confirmed")
SUMMARY_CLAIMS = {"revenue_led", "cost_led", "growth_outpacing_cost", "below_line_led", "margin_up", "margin_down", "margin_mixed", "broad", "growth_absorbed", "on_plan", "outlook", None}
MAX_BULLET_WORDS, MAX_DETAIL_WORDS, MAX_HEAD_WORDS, MAX_ASK_WORDS, MAX_ASK_DETAIL_WORDS, MIN_MEANING_WORDS = 48, 130, 10, 12, 40, 8
MIN_BULLETS, MAX_BULLETS, MAX_DETAIL_SENTENCES = 4, 4, 5


def _drill_ok(payload, L, key, dr):
    """A drill target the page can open: the level and every id exist in this lens."""
    lines = {x["id"] for x in L["lines"]}
    ok = {"section": {"rev", "cos", "opex", "syn", "nonop", "ebitda"}, "line": lines, "driver": {d["id"] for d in L["drivers"]},
          "account": {a["id"] for a in L["accounts"]}, "outlook": {"mechanical", "ytd"}, "action": {a["id"] for a in L.get("actions", [])}}
    if not isinstance(dr, dict) or dr.get("level") not in ok or not dr.get("ids"):
        return False
    return all(i in ok[dr["level"]] for i in list(dr["ids"]) + list(dr.get("support") or []))


def _summary_ok(payload, L, key, sm, ids, errs, warns):
    """The written summary: 3-5 short bullets, net income first, every figure registered, a drill that opens on what the
    bullet says, observation plus meaning (never a figure alone), the gate's wording rules; 2-3 decisions as questions."""
    from .validate import _claim_contradiction
    bullets = sm.get("bullets") or []
    if not MIN_BULLETS <= len(bullets) <= MAX_BULLETS:
        errs.append(f"readout.summary.bullets must hold {MAX_BULLETS} bullets (headline, why, trend, attention; what it means is folded into them), not {len(bullets)}")
    roles = [b.get("role") for b in bullets]
    if any(r not in SUMMARY_ROLES for r in roles):
        errs.append(f"readout.summary.bullets: every bullet carries a role, one of {SUMMARY_ROLES}")
    else:
        if roles and roles[0] != "headline":
            errs.append("readout.summary.bullets: the first bullet is the headline (outcome, primary driver, implication)")
        if roles != sorted(roles, key=SUMMARY_ROLES.index):
            errs.append(f"readout.summary.bullets: roles run in the narrative order {SUMMARY_ROLES}")
        if roles.count("headline") > 1:
            errs.append("readout.summary.bullets: one headline only")
        miss = REQUIRED_ROLES - set(roles)
        if miss:
            errs.append(f"readout.summary.bullets: missing {sorted(miss)}; the summary answers what happened, why, against the trend, and what needs attention")
    page = sum(len((b.get("head") or "").split()) + len((b.get("text") or "").split()) for b in bullets)
    if page > MAX_PAGE_WORDS:
        errs.append(f"readout.summary: the page lines (heads and texts) run {page} words; the executive summary is at most {MAX_PAGE_WORDS}")
    unver = [str(u).strip().lower() for b in bullets for u in (b.get("unverified") or [])]
    att = next((b for b in bullets if b.get("role") == "attention"), None)
    if unver and att is not None:
        need = " ".join(str(x).lower() for x in (att.get("data_needed") or []))
        gap = [u for u in unver if u not in need]
        if gap:
            errs.append(f"readout.summary: the attention bullet's data_needed[] names the data that would confirm {gap}")
    lines = {x["id"]: x for x in L["lines"]}
    for i, b in enumerate(bullets):
        where = f"readout.summary.bullets[{i}]"
        head, text = (b.get("head") or "").strip(), (b.get("text") or "").strip()
        if not head or len(head.split()) > MAX_HEAD_WORDS or re.search(r"\d", head):
            errs.append(f"{where}: head is a bold lead of at most {MAX_HEAD_WORDS} words with no figures")
        words = text.split()
        if not words or len(words) > MAX_BULLET_WORDS:
            errs.append(f"{where}: text is the insight shown on the page, at most {MAX_BULLET_WORDS} words ({len(words)} given)")
        badt = unregistered_tokens(text, b.get("numbers") or [])
        if badt:
            errs.append(f"{where}: unregistered figure(s) in text: {', '.join(badt)}")
        detail = (b.get("detail") or "").strip()
        dw = detail.split()
        if not dw or len(dw) > MAX_DETAIL_WORDS:
            errs.append(f"{where}: detail (the full sentence shown when the bullet is opened) is required, at most {MAX_DETAIL_WORDS} words ({len(dw)} given)")
        if len(re.findall(r"[.!?](\s|$)", detail)) > MAX_DETAIL_SENTENCES:
            errs.append(f"{where}: detail is at most {MAX_DETAIL_SENTENCES} sentences")
        nums = b.get("numbers") or []
        bad = unregistered_tokens(detail, nums)
        if bad:
            errs.append(f"{where}: unregistered figure(s) in detail: {', '.join(bad)}")
        _nums_ok(payload, nums, where, errs)
        bare = detail
        for n in nums:
            bare = bare.replace(str(n.get("display", "")), " ")
        if len(re.findall(r"[A-Za-z][A-Za-z'-]+", bare)) < MIN_MEANING_WORDS:
            errs.append(f"{where}: a figure alone is not an insight; say what it means (observation, then meaning)")
        for rx, label in FORBIDDEN:
            if rx.search(head + " " + text + " " + detail):
                errs.append(f"{where}: forbidden phrase: {label}")
        _cause_ok(head + ". " + text + " " + detail, where, errs, b.get("unverified"))
        if b.get("tone") not in SUMMARY_TONES:
            errs.append(f"{where}: tone must be one of {sorted(SUMMARY_TONES)}")
        if not _drill_ok(payload, L, key, b.get("drill")):
            errs.append(f"{where}: drill must name a level (section, line, driver, account, outlook, action) and ids that exist in this view")
        if b.get("claim") not in SUMMARY_CLAIMS:
            errs.append(f"{where}: unknown claim {b.get('claim')}")
        elif b.get("claim"):
            why = _claim_contradiction(b["claim"], L, lines, payload)
            if why:
                errs.append(f"{where}: claim '{b['claim']}' contradicts the numbers ({why})")
        if i == 0 and "net income" not in (head + " " + text + " " + detail).lower():
            errs.append(f"{where}: the first bullet is about net income")
        if i == 0 and not (b.get("drill") or {}).get("ids") and not b.get("claim"):
            errs.append(f"{where}: the lead carries a claim or a drill")
    decs = sm.get("decisions") or []
    if not 2 <= len(decs) <= 3:
        errs.append(f"readout.summary.decisions must hold 2 or 3 questions, not {len(decs)}")
    for i, d in enumerate(decs):
        where = f"readout.summary.decisions[{i}]"
        text = (d.get("text") or "").strip()
        if not text.endswith("?"):
            errs.append(f"{where}: a decision is a question (ends with ?)")
        if len(text.split()) > MAX_ASK_WORDS:
            errs.append(f"{where}: the question on the page is at most {MAX_ASK_WORDS} words; the full question goes in detail")
        if re.search(r"\d", text):
            errs.append(f"{where}: the question on the page carries no figures; they belong in detail")
        detail = (d.get("detail") or "").strip()
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
        for rx, label in FORBIDDEN:
            if rx.search(text + " " + detail):
                errs.append(f"{where}: forbidden phrase: {label}")
        if not _drill_ok(payload, L, key, d.get("drill")):
            errs.append(f"{where}: drill must open on what the question is about (a driver, account, line, section, action or outlook that exists)")
        if d.get("finding_ref") and d["finding_ref"] not in ids:
            errs.append(f"{where}: finding_ref does not name a finding")
