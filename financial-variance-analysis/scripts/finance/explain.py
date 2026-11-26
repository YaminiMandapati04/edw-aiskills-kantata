"""Deterministic baseline explanations (account, driver, statement line,
summary), the proposed actions with suggested owners and rule-generated
target dates, and the pinned headline. Every figure in prose is registered."""
import datetime as dt

from .common import Register, is_num, r2, money, pct, lower_words
from .signals import TEST_LABEL, PERSISTENCE_LABEL
from .synthesis import OWNER_BY_SECTION, WHAT_BY_SECTION, fav_word, _line, _test, EN_DASH

# rule table: test id -> (category, owner role or None for the section default, relevance weight, action template)
RULES = {
    "budget_outside_run_rate": ("forecast_assumption", "FP&A", 1.0, "Confirm whether the budget level for {label} is a deliberate plan or a carried-forward level; document the assumption or propose a documented forecast review. The budget of record stays the accountability baseline until a named person changes it."),
    "step_change": ("forecast_assumption", None, 0.9, "Confirm what changed in {label} from {since}: name the new monthly level and its cause, and carry it for the remaining months only once confirmed."),
    "persistent_gap": ("management_decision", None, 0.9, "Decide whether the persistent gap in {label} is structural (re-plan it) or an execution issue (corrective action with an owner). It has held for most recent months, so it is not noise."),
    "reversal_signal": ("investigation", "Controller", 0.7, "Check cut-off and accruals for {label} across {prior} and {period}: confirm the net position of the two months and whether anything remains to reverse."),
    "outlier_month": ("investigation", None, 0.8, "Identify the postings behind the {period} excursion in {label}; establish whether it is a one-off, a timing effect or a new level, and document the recurring monthly amount for forecast review."),
    "seasonal_echo": ("forecast_assumption", "FP&A", 0.5, "Confirm the seasonal pattern in {label} and whether the budget phasing reflects it; if it does not, propose a documented re-phasing rather than a level change."),
    "unbudgeted_activity": ("accountability", "FP&A", 0.8, "Confirm whether {label} belongs in the plan: add a budget line or correct the mapping, and state the recurring monthly amount for the forecast."),
    "budgeted_no_activity": ("investigation", None, 0.7, "Confirm whether the budgeted spend in {label} is delayed, cancelled or coded elsewhere; a delay needs the expected month, a cancellation needs the full-year release."),
    "yoy_break": ("investigation", None, 0.6, "Explain the break in the year-on-year pace of {label} in {period} against its trailing pace."),
    "budget_near_run_rate_edge": ("forecast_assumption", "FP&A", 0.5, "The budget for {label} sits at the edge of the trailing run-rate range: confirm the plan assumption or propose a documented review."),
    "escalator": ("accountability", "Controller", 0.4, "Confirm the source of the constant monthly escalation in {label} (contract step, allocation rule or posting formula) and carry it into the outlook."),
    "dormant_account": ("accountability", "Controller", 0.4, "{label} stopped posting: confirm whether the activity moved to another account or ceased, and release or re-map the remaining budget."),
}
PRIORITY_PLANNING = ["budget_outside_run_rate", "unbudgeted_activity", "budgeted_no_activity", "step_change", "persistent_gap", "reversal_signal", "outlier_month",
                     "seasonal_echo", "yoy_break", "budget_near_run_rate_edge", "escalator", "dormant_account"]
PRIORITY_OPERATIONAL = ["unbudgeted_activity", "budgeted_no_activity", "step_change", "reversal_signal", "persistent_gap", "outlier_month", "seasonal_echo", "yoy_break",
                        "budget_outside_run_rate", "budget_near_run_rate_edge", "escalator", "dormant_account"]
BUDGET_ONLY = {"budget_outside_run_rate", "budget_near_run_rate_edge", "unbudgeted_activity", "budgeted_no_activity", "persistent_gap", "reversal_signal"}
CATEGORY_WORDS = {"investigation": "investigation", "management_decision": "management decision", "forecast_assumption": "forecast assumption", "accountability": "accountability"}
QUESTION_BY_RULE = {"budget_outside_run_rate": "Is the budget level a deliberate plan or the carried-forward level of a past month?",
                    "step_change": "What changed, and is the new level permanent?",
                    "persistent_gap": "Is the gap structural or an execution issue, and who owns the response?",
                    "reversal_signal": "What is the net position across the two months once cut-off is corrected?",
                    "outlier_month": "Is the excursion a one-off, a timing effect or a new level?",
                    "seasonal_echo": "Does the budget phasing reflect the seasonal pattern?",
                    "unbudgeted_activity": "Does the account belong in the plan, and at what recurring amount?",
                    "budgeted_no_activity": "Is the budgeted spend delayed, cancelled or coded elsewhere?",
                    "yoy_break": "What broke the year-on-year pace?",
                    "budget_near_run_rate_edge": "Is the plan assumption still valid?",
                    "escalator": "What drives the constant monthly step?",
                    "dormant_account": "Did the activity move or cease?"}
EVIDENCE_BY_RULE = {
    "budget_outside_run_rate": ["budget workpapers for the line", "the trailing months' postings", "the plan owner's stated assumption"],
    "step_change": ["postings for the last two months", "contracts, headcount or rate changes effective in the period", "the owner's confirmation of the new level"],
    "persistent_gap": ["monthly variance history for the line", "the original plan assumption", "the owner's view on structural versus execution"],
    "reversal_signal": ["accrual and cut-off journals for both months", "invoices dated around the month end"],
    "outlier_month": ["the largest postings in the month (GL drill through the TRANSACTIONS table)", "approvals or contracts behind them"],
    "seasonal_echo": ["prior-year monthly phasing", "the budget phasing for the line"],
    "unbudgeted_activity": ["the chart-of-accounts mapping for the account", "the budget file"],
    "budgeted_no_activity": ["purchase orders or commitments for the budgeted spend", "the owner's expected timing"],
    "yoy_break": ["prior-year postings for the month", "known changes in scope or pricing"],
    "budget_near_run_rate_edge": ["budget workpapers for the line"],
    "escalator": ["the contract or allocation rule driving the step"],
    "dormant_account": ["the account mapping", "the replacement account if any"],
}


def owner_for(rule, section):
    o = RULES[rule][1] if rule in RULES else None
    return o or OWNER_BY_SECTION[section]


def _scale(reg, source, ds):
    if ds == 1.0:
        return
    for n in reg.numbers:
        if n["source"] == source and n.get("scale") is None:
            n["scale"] = ds


# ------------------------------------------------------------ decision asks

DECIDE_BY_SECTION = {"rev": "a timing issue in billing, a change in customers or pricing, or a budget that needs re-basing",
                     "cos": "a volume effect, a unit-cost change or a one-off charge",
                     "opex": "a headcount or rate change, a timing effect, or a one-off item",
                     "syn": "a planned investment or a timing effect",
                     "nonop": "a financing, tax or non-cash item"}


def _months_active(model, aid, rng):
    s = model.series[model.aidx[aid]]["actual"]
    return [model.f.periods[k]["label"] for k in range(rng[0], rng[1] + 1) if is_num(s[k]) and s[k] != 0]


def decision_ask(model, L, d, signals, owner):
    """One question per driver, built from facts: the driver's movement, where it sits (department, then the lead account
    with its subsidiary), whether that is new or stopped (one-sided), recurring (persistence signal) or a one-off
    (a single month in the window), and the decision to make. Every figure is registered; the owner is suggested."""
    from .synthesis import account_label, basis_words, spans_departments
    LP = f"lenses[{L['id']}]"
    DP = f"{LP}.drivers[{d['id']}]"
    reg = Register()
    mv = d["movement"]
    if not is_num(mv):
        return None
    basis, cost = L["basis_label"], d["section"] in ("cos", "opex")
    amt = reg.m(abs(mv), DP + ".movement")
    for n in reg.numbers:
        if n["source"] == DP + ".movement":
            n["transform"] = "abs"
    side = ("below" if mv < 0 else "above") if not cost else ("over" if mv < 0 else "under")
    label = d["label"] if d["level"] == "L4" else account_label(model, d["accounts"][0]) if len(d["accounts"]) == 1 else d["label"]
    parts = [f"{label} is {amt} {side} {basis} for {L['range']['label']}."]
    rc = (L.get("reconciliation") or {}).get(d["id"]) or {}
    dep = rc.get("by_department")
    where = []
    same = lambda v: is_num(v) and v != 0 and (v > 0) == (mv > 0)       # "most of it sits in" names a contributor moving the driver's way
    di = next((i for i, r in enumerate((dep or {}).get("rows") or []) if same(r["movement"])), None)
    if dep and dep["comparable"] and di is not None and dep["rows"][di]["name"] != "No department" and spans_departments(dep):
        r0 = dep["rows"][di]
        where.append(f"in {reg.lit(r0['name'])} ({reg.m(r0['movement'], DP.replace('.drivers[', '.reconciliation[') + f'.by_department.rows[{di}].movement', sign=True)})")
    items = [i for i in (rc.get("items") or []) if same(i["movement"])]
    lead = next((a for a in L["accounts"] if items and a["id"] == items[0]["account"]), None)
    one_off = None
    if lead:
        AP = f"{LP}.accounts[{lead['id']}]"
        acc = model.f.accounts[model.aidx[lead["id"]]]
        name = f"at {acc['subsidiary']}" if d["level"] == "account" and acc.get("subsidiary") and len(d["accounts"]) > 1 else account_label(model, lead["id"])
        txt = f"{reg.lit(name)} {reg.m(lead['movement'], AP + '.movement', sign=True)}"
        w = basis_words(lead["movement_basis"], basis)
        if w:
            txt += f", {w}"
        sg = signals.get(lead["id"]) or {}
        pg = next((t for t in sg.get("tests", []) if t["id"] == "persistent_gap" and t["state"] == "fired"), None)
        if pg and L["basis"] == "budget":
            unf = (pg["evidence"].get("cumulative_variance") or 0) < 0           # profit-oriented: negative is unfavourable
            word = ("over" if cost else "below") if unf else ("under" if cost else "above")
            txt += f", {word} budget in {pg['evidence']['months_same_side']} of the last {pg['evidence']['months_compared']} months"
        rng = (L["range"]["start_idx"], L["range"]["end_idx"])
        act = _months_active(model, lead["id"], rng)
        if lead["movement_basis"] == "no_comparator" and len(act) == 1 and rng[1] > rng[0]:
            one_off = act[0]
            txt += f", booked in {act[0]} only"
        where.append(txt)
    if lead and len(d["accounts"]) == 1 and where:      # a single-account driver: say how it moved, not where
        tail = where[-1].split(", ", 1)[1] if ", " in where[-1] else ""
        where = where[:-1]
        if tail:
            parts[0] = parts[0][:-1] + f": {tail}."
    if len(where) == 2:
        parts.append(f"Most of it sits {where[0]}; the largest account is {where[1]}.")
    elif where:
        parts.append(f"Most of it sits {where[0] if where[0].startswith(('in ', 'at ')) else 'in ' + where[0]}.")
    if one_off and lead:
        decide = (f"Confirm it is a one-off{' and non-cash' if d['section'] == 'nonop' else ''}, and exclude it from the run-rate"
                  + (", or say what makes it recur." if d["section"] != "nonop" else "."))
    elif d["section"] == "rev" and L["basis"] == "budget":
        decide = f"Is this {DECIDE_BY_SECTION['rev']}?"
    else:
        decide = f"Is this {DECIDE_BY_SECTION[d['section']]}, and does it continue?"
    parts.append(decide)
    parts.append(f"Suggested owner: {owner}.")
    return {"text": " ".join(parts), "numbers": reg.numbers, "one_off_month": one_off}


# ---------------------------------------------------------------------- actions

def business_days_after(d, n):
    """n weekdays after d (weekends skipped; public holidays are not known here)."""
    while n > 0:
        d = d + dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def actions(model, L, signals, as_of_period):
    """One consolidated, ranked item per driver that is material, carries a material coverage exception, or is tracked for a persistent / step / reversal signal."""
    LP = f"lenses[{L['id']}]"
    target = business_days_after(getattr(model, "build_date", None) or dt.date.today(), 10).isoformat()
    lay = L.get("layers") or {}
    lay_by_driver = {d["id"]: d for d in lay.get("drivers", [])} if lay.get("state") == "calculated" else {}
    mon = L["materiality"]["monitoring_abs"]
    remaining = L.get("_remaining_months")
    items = []
    for d in L["drivers"]:
        accts = [a for a in L["accounts"] if a["driver_ref"] == d["id"]]
        fired = {}
        for a in accts:
            for t in signals[a["id"]]["tests"]:
                if t["state"] == "fired" and t["id"] in RULES:
                    fired.setdefault(t["id"], []).append((a, t))
        material = d["tier"] in ("executive", "management") or (not is_num(d["variance"]) and model.tier(d["movement"], None) in ("executive", "management"))
        coverage = "unbudgeted_activity" in fired and L["basis"] == "budget" and any(abs(a["actual_po"] or 0) >= mon for a, _ in fired["unbudgeted_activity"])
        tracked = d["tier"] == "monitoring" and any(k in fired for k in ("persistent_gap", "step_change", "reversal_signal"))
        if not material and not coverage and not tracked:
            continue
        lead = max(accts, key=lambda a: (abs(a["movement"] or 0), a["id"])) if accts else None
        lead_name = model.f.accounts[model.aidx[lead["id"]]]["name"] if lead else d["label"]
        label = d["label"] if d["level"] == "L4" else lead_name
        ld = lay_by_driver.get(d["id"])
        planning_led = bool(ld) and is_num(ld.get("planning")) and is_num(ld.get("operational")) and abs(ld["planning"]) > abs(ld["operational"])
        primary = None
        for rule in (PRIORITY_PLANNING if planning_led else PRIORITY_OPERATIONAL):
            if rule in fired and (L["basis"] == "budget" or rule not in BUDGET_ONLY):
                primary = rule
                break
        exposure_amt, exposure_basis = abs(d["movement"] or 0), "driver movement"
        if primary:
            cat, _, weight, tmpl = RULES[primary]
            a, t = fired[primary][0]
            e = t.get("evidence", {})
            since = e.get("entered_at") or (model.f.periods[model.as_of - 1]["label"] if model.as_of else "")
            title = tmpl.format(label=label, period=as_of_period["label"], prior=e.get("prior_month", ""), since=since)
            question, required = QUESTION_BY_RULE[primary], EVIDENCE_BY_RULE[primary]
            confidence, owner = signals[a["id"]]["confidence"], owner_for(primary, d["section"])
        else:
            cat, weight = "investigation", 0.6
            title = f"No structural signal fired on {label}; the variance needs a named cause from the owner: review the postings for {label} in {L['range']['label']} and document what moved."
            question = "What moved the line, and does it continue?"
            required = ["the largest postings in the window (GL drill through the TRANSACTIONS table)", "the owner's explanation"]
            confidence, owner = "low", OWNER_BY_SECTION[d["section"]]
        pers = signals[lead["id"]]["persistence_hint"] if lead else "undetermined"
        conf_w = {"high": 1.0, "medium": 0.75, "low": 0.5}[confidence]
        score = exposure_amt * weight * 1.0 * conf_w
        monthly = d["variance"] if L["window"] == "MTD" else None
        carry = pers in ("recurring_level_change", "persistent")
        forecast = {"state": "proposed" if (carry or pers == "coverage") else "undetermined", "credit": 0,
                    "proposed_monthly_effect": r2(monthly) if carry else None, "remaining_months": remaining,
                    "remaining_months_effect": r2(monthly * remaining) if (carry and is_num(monthly) and remaining) else None,
                    "note": ("Forecast credit is 0 until a named person accepts the treatment; a planning-gap item restates a gap the mechanical outlook already carries and is not additive to it."
                             if primary in ("budget_outside_run_rate", "budget_near_run_rate_edge") else "Forecast credit is 0 until a named person accepts the treatment.")}
        secondary = []
        for rule, hits in fired.items():
            if rule == primary:
                continue
            for a, t in hits:
                nm = model.f.accounts[model.aidx[a["id"]]]["name"]
                e = t.get("evidence", {})
                secondary.append({"rule": rule, "label": TEST_LABEL[rule], "account": a["id"],
                                  "text": RULES[rule][3].format(label=nm, period=as_of_period["label"], prior=e.get("prior_month", ""), since=e.get("entered_at", ""))})
        items.append({"id": f"a:{d['id']}", "subject_ref": d["id"], "label": d["label"], "section": d["section"], "category": cat, "category_label": CATEGORY_WORDS[cat],
                      "layers": {"planning": ld.get("planning") if ld else None, "operational": ld.get("operational") if ld else None, "led_by": "planning" if planning_led else ("operational" if ld else None)},
                      "state": "active", "rule": primary, "rule_label": TEST_LABEL[primary] if primary else "No structural signal; cause pending management input",
                      "short": (title.split(". ")[0].split(";")[0].split(":")[0]).rstrip(".") + ".", "title": title, "question": question, "required_evidence": required,
                      "expected_output": "A recorded decision (keep, re-phase or re-plan) and, where the line continues, a recurring monthly amount for forecast review.",
                      "exposure": {"amount": r2(exposure_amt), "basis": exposure_basis, "source": f"{LP}.drivers[{d['id']}].movement"},
                      "owner": {"role": owner, "status": "suggested"}, "date": {"target": target, "status": "rule_generated_target", "note": "build date + 10 business days; not an assigned commitment"},
                      "persistence": pers, "persistence_label": PERSISTENCE_LABEL[pers], "confidence": confidence, "forecast": forecast,
                      "secondary": secondary, "accounts": [a["id"] for a in accts], "score": r2(score),
                      "score_components": {"exposure": r2(exposure_amt), "decision_relevance": weight, "unresolved_risk": 1.0, "evidence_strength": conf_w}})
    items.sort(key=lambda i: (-(i["score"] or 0), i["id"]))
    drv_by = {d["id"]: d for d in L["drivers"]}
    for r, i in enumerate(items, start=1):
        i["rank"] = r
        i["ask"] = decision_ask(model, L, drv_by[i["subject_ref"]], signals, i["owner"]["role"])
    return items


# ----------------------------------------------------------------- explanations

def account_explanation(model, L, a, sg, action_by_driver, as_of_period):
    LP = f"lenses[{L['id']}]"
    AP = f"{LP}.accounts[{a['id']}]"
    SP = f"signals[{a['id']}]"
    reg = Register()
    acct = model.f.accounts[model.aidx[a["id"]]]
    name = reg.lit(acct["name"])
    basis = L["basis_label"]
    ds = a["display_sign"]
    win = L["range"]["label"]
    sentences, limits, hyps = [], [], []
    status = {"evidence": "observed", "hypothesis": "none", "disposition": "none_recorded", "cause_verification": "not_verified",
              "management_decision": "none_recorded", "action_assignment": "suggested", "forecast_approval": "not_approved"}
    v = a["variance"]
    if a["budget_status"] == "no_comparator" or not is_num(v):
        if is_num(a["actual"]) and a["actual"] != 0:
            sentences.append(f"{name} posted {reg.m(a['actual'], AP + '.actual')} in {win} with no {basis} line, so no variance is reported: this is coverage (comparability), not performance.")
            status["hypothesis"] = "coverage"
        else:
            sentences.append(f"{name} has no activity in {win} and no {basis} line.")
        limits.append(f"No {basis} exists for this account; an omitted comparator is never read as a zero budget, unauthorised spending or favourable performance.")
    else:
        sentences.append(f"{name} is {reg.m(a['actual'], AP + '.actual')} against {basis} {reg.m(a['comparator'], AP + '.comparator')}: "
                         f"{reg.m(v, AP + '.variance', sign=True)} ({reg.p(a['variance_pct'], AP + '.variance_pct', sign=True)}), {fav_word(v)} to profit; {a['tier']} tier.")
        rr = sg["runrate"]
        if rr["eligible"]:
            lo, hi, ref = rr["min"], rr["max"], rr["reference"]
            cur = model.series[model.aidx[a["id"]]]["actual"][model.as_of]
            pos = "inside" if is_num(cur) and lo <= cur <= hi else ("above" if is_num(cur) and ((cur > hi) == (ds > 0)) else "below")
            pairs = sorted([(lo * ds, SP + ".runrate.min"), (hi * ds, SP + ".runrate.max")], key=lambda x: x[0])
            sentences.append(f"The {reg.lit(as_of_period['label'])} figure sits {pos} its trailing {rr['months']}-month range "
                             f"({reg.m(pairs[0][0], pairs[0][1])}{EN_DASH}{reg.m(pairs[1][0], pairs[1][1])}; run-rate reference {reg.m(ref * ds, SP + '.runrate.reference')}).")
            for k in ("min", "max", "reference"):
                _scale(reg, SP + f".runrate.{k}", ds)
            if L["basis"] == "budget":
                t = _test(sg, "budget_outside_run_rate")
                if t and t["state"] == "fired":
                    e = t["evidence"]
                    sentences.append(f"The budget ({reg.m(e['budget'] * ds, SP + '.tests[budget_outside_run_rate].evidence.budget')}) sits "
                                     f"{'above' if (e['budget'] * ds) > (ref * ds) else 'below'} that reference: part of the variance is the plan's distance from recent activity rather than this month's execution.")
                    _scale(reg, SP + ".tests[budget_outside_run_rate].evidence.budget", ds)
                    hyps.append({"id": "budget_outside_run_rate", "label": TEST_LABEL["budget_outside_run_rate"], "state": "proposed", "evidence_needed": EVIDENCE_BY_RULE["budget_outside_run_rate"]})
        else:
            limits.append(f"Run-rate comparison not eligible: {rr['reason']}.")
        step_fired = (_test(sg, "step_change") or {}).get("state") == "fired"
        persist_fired = (_test(sg, "persistent_gap") or {}).get("state") == "fired"
        for tid in ("step_change", "outlier_month", "reversal_signal", "persistent_gap", "seasonal_echo", "yoy_break"):
            t = _test(sg, tid)
            if not t or t["state"] != "fired":
                continue
            e = t.get("evidence", {})
            if tid == "step_change":
                sentences.append(f"A step entered in {reg.lit(e['entered_at'])} and held this month, which reads as a new level ({reg.m(e['new_level'] * ds, SP + '.tests[step_change].evidence.new_level')} a month) rather than a single event.")
                _scale(reg, SP + ".tests[step_change].evidence.new_level", ds)
            elif tid == "outlier_month":
                if not step_fired and not persist_fired:
                    sentences.append("The month is a single-month excursion from its range until a second month confirms it.")
            elif tid == "reversal_signal":
                sentences.append(f"It reverses last month's variance of {reg.m(e['variance_prior_month'], SP + '.tests[reversal_signal].evidence.variance_prior_month', sign=True)}, which fits a cut-off or accrual pattern.")
            elif tid == "persistent_gap":
                sentences.append(f"The variance has been on the same side of budget in {e['months_same_side']} of the last {e['months_compared']} months (cumulative {reg.m(e['cumulative_variance'], SP + '.tests[persistent_gap].evidence.cumulative_variance', sign=True)}).")
            elif tid == "seasonal_echo":
                sentences.append("The same month last year moved the same way against its own run-rate, so seasonality is a candidate.")
            elif tid == "yoy_break":
                word = "Revenue" if ds > 0 else "Cost"
                sentences.append(f"{word} is {reg.p(e['yoy_now'] * ds, SP + '.tests[yoy_break].evidence.yoy_now', sign=True)} on the same month last year, against a trailing pace of "
                                 f"{reg.p(e['trailing_yoy_mean'] * ds, SP + '.tests[yoy_break].evidence.trailing_yoy_mean', sign=True)}.")
                _scale(reg, SP + ".tests[yoy_break].evidence.yoy_now", ds); _scale(reg, SP + ".tests[yoy_break].evidence.trailing_yoy_mean", ds)
            hyps.append({"id": tid, "label": TEST_LABEL[tid], "state": "proposed", "evidence_needed": EVIDENCE_BY_RULE.get(tid, [])})
        if sg["persistence_hint"] != "undetermined":
            status["hypothesis"] = sg["persistence_hint"]
        if L["window"] != "MTD":
            limits.append(f"Structural signals are tested on {as_of_period['label']} only; the {L['window_label']} variance aggregates {L['months']} months.")
        limits.append("The statement mart shows amounts, not volume, price, headcount or rate; none of those effects is established here. Transaction-level detail needs the TRANSACTIONS table (raw transaction currency).")
    what = WHAT_BY_SECTION[a["section"]]
    item = action_by_driver.get(a["driver_ref"])
    if item:
        ns = {"state": "action" if item["accounts"] == [a["id"]] or a["tier"] in ("executive", "management", "monitoring") else "shared_action",
              "action_ref": item["id"], "text": item["short"], "question": item["question"], "required_evidence": item["required_evidence"],
              "expected_output": item["expected_output"], "owner": item["owner"], "date": item["date"]}
    else:
        ns = {"state": "no_action_required", "action_ref": None, "text": None,
              "reason_no_action": "Below the monitoring threshold with no structural signal; tracked without commentary.", "owner": None, "date": None}
    concise = " ".join(sentences[:3])
    if item:
        concise_next = f" Next: {item['short']}"
        if len(concise) + len(concise_next) <= 520:
            concise += concise_next
    expanded = " ".join(sentences + ([f"What it does not establish: {what}; {limits[-1]}"] if limits else [])
                        + ([f"Next: {item['title']} (suggested owner {item['owner']['role']}; rule-generated target {item['date']['target']}, not assigned.)"] if item else []))
    return {"id": a["id"], "name": acct["name"], "text": {"concise": concise, "expanded": expanded, "summary": sentences[0]},
            "status": status, "hypotheses": hyps, "limitations": limits, "next_step": ns, "numbers": reg.numbers,
            "sources": [AP, SP], "review": {"state": "engine_baseline", "label": "deterministic evidence baseline; the diagnosis may refine it"}}


DRILL_MAX_WORDS = 75
SECTION_NAMES = {"rev": "revenue", "cos": "cost of sales", "opex": "operating expenses", "syn": "synergies and strategic investments", "nonop": "non-operating items"}
WINDOW_WORDS = {"MTD": "the month", "QTD": "quarter to date", "YTD": "year to date", "LTM": "the last twelve months"}


def _trend_clause(reg, L, lenses, find):
    """Whether the latest month continues the quarter and year to date for this item on this basis: a continuing pattern,
    a change of direction, new this month or easing. find(lens) returns (variance, source path) or (None, None)."""
    if not lenses:
        return ""
    from .summary import trend_reading, trend_windows
    ws = trend_windows(lenses, L["basis"])
    if not ws:
        return ""
    got = [(w,) + find(lenses[f"{w}_{L['basis']}"]) for w in ws]
    if not is_num(got[0][1]):
        return ""
    reading = trend_reading(got[0][1], [g[1] for g in got[1:]], L["materiality"]["monitoring_abs"])
    if not reading:
        return ""
    vals = ", ".join(f"{WINDOW_WORDS[w]} {reg.m(v, src, sign=True)}" for w, v, src in got if is_num(v))
    mean = {"continuing": "the month continues the longer pattern",
            "reversal": "the month points the other way from the longer windows, a change of direction",
            "new": "not visible in the longer windows, so new this month",
            "easing": "the month is close to the comparison, so the variance did not build further"}[reading]
    return f" Trend: {vals}; {mean}."


def _parent_clause(reg, L, d, LP):
    """How the driver moves its parent line: most of it, part of it, or against it."""
    sec = d["section"]
    ln = next((x for x in L["lines"] if x["id"] == sec), None)
    v, pv = d["variance"], (ln or {}).get("variance")
    if not (is_num(v) and is_num(pv)) or pv == 0 or v == 0:
        return ""
    name = SECTION_NAMES.get(sec, sec)
    if (v > 0) != (pv > 0):
        how = f"it offsets part of the {name} movement of {reg.m(pv, f'{LP}.lines[{sec}].variance', sign=True)}"
    elif abs(v) >= 0.5 * abs(pv):
        how = f"it carries most of the {name} movement of {reg.m(pv, f'{LP}.lines[{sec}].variance', sign=True)}"
    else:
        how = f"it is one part of the {name} movement of {reg.m(pv, f'{LP}.lines[{sec}].variance', sign=True)}"
    return f" Parent: {how}."


def _fit(parts, limit=DRILL_MAX_WORDS):
    """Join (priority, text) parts in order, dropping the lowest-priority parts until the narrative fits the word limit."""
    keep = list(parts)
    while len(" ".join(t for _, t in keep).split()) > limit and len(keep) > 1:
        drop = max(range(len(keep)), key=lambda i: (keep[i][0], i))
        if keep[drop][0] == 0:
            break
        keep.pop(drop)
    return " ".join(t.strip() for _, t in keep if t.strip())


def driver_explanation(model, L, d, insight, action, lenses=None):
    """The drill-through narrative for one driver, at most 75 words: what changed, how it moves its parent line, whether
    it continues across the windows, what the evidence implies, and the next step."""
    LP = f"lenses[{L['id']}]"
    DP = f"{LP}.drivers[{d['id']}]"
    reg = Register()
    basis = L["basis_label"]
    v = d["variance"]
    parts = []
    if not is_num(v):
        parts.append((0, f"{d['label']} has no {basis} comparison in {L['range']['label']}."))
    else:
        parts.append((0, f"{d['label']} is {reg.m(d['actual'], DP + '.actual')} against {basis} {reg.m(d['comparator'], DP + '.comparator')}: "
                         f"{reg.m(v, DP + '.variance', sign=True)} ({reg.p(d['variance_pct'], DP + '.variance_pct', sign=True)}), {fav_word(v)} to profit."))
        parts.append((1, _parent_clause(reg, L, d, LP)))
        parts.append((2, _trend_clause(reg, L, lenses, lambda X: next(((x["variance"], f"lenses[{X['id']}].drivers[{d['id']}].variance") for x in X["drivers"] if x["id"] == d["id"]), (None, None)))))
    if insight:
        inf = [s["text"] for s in insight["statements"] if s["state"] == "analytical_inference"]
        if inf:
            parts.append((4, inf[0]))
            for n in insight["numbers"]:
                if n not in reg.numbers:
                    reg.numbers.append(n)
    if action:
        parts.append((3, f"Next: {action['short']}"))
    text = _fit(parts)
    return {"id": d["id"], "label": d["label"], "text": {"concise": text}, "numbers": reg.numbers, "action_ref": action["id"] if action else None,
            "insight_ref": insight["id"] if insight else None, "review": {"state": "engine_baseline", "label": "deterministic evidence baseline"}}


def line_explanations(model, L, lenses=None):
    LP = f"lenses[{L['id']}]"
    basis = L["basis_label"]
    out = []
    names = {"rev": "Revenue", "cos": "Cost of sales", "gp": "Gross profit", "opex": "Operating expenses", "ebitda": "Adjusted EBITDA", "syn": "Synergies and strategic investments",
             "nonop": "Non-operating income (expense)", "ni": "Net income"}
    comps = {"gp": ("rev", "cos"), "ebitda": ("gp", "opex"), "ni": ("ebitda", "syn", "nonop")}
    for lid, label in names.items():
        ln = _line(L, lid)
        reg = Register()
        if not is_num(ln["variance"]):
            text = f"{label} has no {basis} comparison in this window."
        else:
            text = (f"{label} is {reg.m(ln['actual'], f'{LP}.lines[{lid}].actual')} against {basis} {reg.m(ln['comparator'], f'{LP}.lines[{lid}].comparator')}: "
                    f"{reg.m(ln['variance'], f'{LP}.lines[{lid}].variance', sign=True)} ({reg.p(ln['variance_pct'], f'{LP}.lines[{lid}].variance_pct', sign=True)}).")
            if lid in comps:
                parts = [f"{lower_words(names[c])} {reg.m(_line(L, c)['variance'], f'{LP}.lines[{c}].variance', sign=True)}" for c in comps[lid] if is_num(_line(L, c)["variance"])]
                text += " Built from " + ", ".join(parts) + "; the components add to the subtotal exactly."
            else:
                drv = sorted([d for d in L["drivers"] if d["section"] == lid and is_num(d["variance"])], key=lambda d: -abs(d["variance"]))[:3]
                if drv:
                    text += " Largest drivers: " + "; ".join(f"{d['label']} {reg.m(d['variance'], f'{LP}.drivers[{d['id']}].variance', sign=True)}" for d in drv) + "."
            if lid in ("gp", "ebitda", "ni"):
                mid = {"gp": "gpm", "ebitda": "ebm", "ni": "nim"}[lid]
                m = _line(L, mid)
                if is_num(m["variance"]):
                    text += f" Margin {reg.p(m['actual'], f'{LP}.lines[{mid}].actual')}, {reg.b(m['variance'], f'{LP}.lines[{mid}].variance')} against {basis}."
            text += _trend_clause(reg, L, lenses, lambda X: next(((x["variance"], f"lenses[{X['id']}].lines[{lid}].variance") for x in X["lines"] if x["id"] == lid), (None, None)))
        out.append({"id": lid, "label": label, "text": {"concise": text}, "numbers": reg.numbers})
    return out


def summary(model, L, actions_, as_of_period):
    LP = f"lenses[{L['id']}]"
    reg = Register()
    eb = _line(L, "ebitda")
    basis = L["basis_label"]
    v = eb["variance"]
    c = L["concentration"]
    lay = L.get("layers") or {}
    if is_num(v):
        outcome = (f"Adjusted EBITDA for {L['range']['label']} is {reg.m(eb['actual'], LP + '.lines[ebitda].actual')} against {basis} {reg.m(eb['comparator'], LP + '.lines[ebitda].comparator')}, "
                   f"{reg.m(v, LP + '.lines[ebitda].variance', sign=True)} ({reg.p(eb['variance_pct'], LP + '.lines[ebitda].variance_pct', sign=True)}).")
    else:
        outcome = f"Adjusted EBITDA has no {basis} comparison for {L['range']['label']}."
    if lay.get("state") == "calculated":
        t = lay["totals"]
        layer_q = (f"Planning ({reg.m(t['planning'], LP + '.layers.totals.planning', sign=True)}) is the budget's distance from the run-rate reference and operational "
                   f"({reg.m(t['operational'], LP + '.layers.totals.operational', sign=True)}) is the month's move against that reference; neither proves controllable execution, and the two may offset. "
                   f"Activity with no budget line ({reg.m(t['coverage'], LP + '.layers.totals.coverage', sign=True)}) is comparability, not performance.")
    else:
        layer_q = lay.get("reason", "")
    activity = (f"{c['material_accounts']} of {c['accounts_total']} accounts are material; three accounts carry {reg.p(c['top3_share'], LP + '.concentration.top3_share')} of the gross movement; "
                f"{c['adverse_accounts']} accounts are adverse and {c['favourable_accounts']} favourable." if c["top3_share"] is not None else "No account carries a comparable variance.")
    limits = ["Every explanation is the engine's deterministic baseline unless a diagnosis badge says otherwise; no business cause is verified by the ledger alone.",
              "Owners are suggested roles and dates are rule-generated targets; nothing here assigns, approves or changes the budget of record.",
              f"Sign convention: expenses {model.sign['expenses_stored']} as stored ({model.sign['source']})."]
    return {"outcome": outcome, "layer_qualification": layer_q, "activity": activity, "decision_refs": [a["id"] for a in actions_[:3]],
            "limitations": limits, "numbers": reg.numbers}


# -------------------------------------------------------------------- headline

def headline(model, L, outlook):
    """Pinned-slot headline. The diagnosis may rephrase the prose but every slot display must survive verbatim."""
    LP = f"lenses[{L['id']}]"
    eb, rev, cos, opex = (_line(L, k) for k in ("ebitda", "rev", "cos", "opex"))
    basis = L["basis_label"]
    slots = {}

    def slot(name, display, source, value):
        slots[name] = {"display": display, "source": source, "value": r2(value) if is_num(value) else value}
        return display
    if not is_num(eb["variance"]):
        text = f"Adjusted EBITDA for {L['range']['label']} has no {basis} comparison."
        return {"text": text, "slots": slots}
    ebitda_actual = slot("ebitda_actual", money(eb["actual"]), LP + ".lines[ebitda].actual", eb["actual"])
    ebitda_comp = slot("ebitda_comparator", money(eb["comparator"]), LP + ".lines[ebitda].comparator", eb["comparator"])
    ebitda_var = slot("ebitda_variance", money(eb["variance"], sign=True), LP + ".lines[ebitda].variance", eb["variance"])
    ebitda_pct = slot("ebitda_variance_pct", pct(eb["variance_pct"], sign=True), LP + ".lines[ebitda].variance_pct", eb["variance_pct"])
    rv = slot("revenue_variance", money(rev["variance"], sign=True), LP + ".lines[rev].variance", rev["variance"])
    cv = slot("cos_variance", money(cos["variance"], sign=True), LP + ".lines[cos].variance", cos["variance"])
    ov = slot("opex_variance", money(opex["variance"], sign=True), LP + ".lines[opex].variance", opex["variance"])
    c = L["concentration"]
    n_mat = slot("material_accounts", str(c["material_accounts"]), LP + ".concentration.material_accounts", c["material_accounts"])
    top3 = slot("top3_share", pct(c["top3_share"]) if c["top3_share"] is not None else "n/a", LP + ".concentration.top3_share", c["top3_share"])
    n_act = slot("follow_up_items", str(len(L["actions"])), LP + ".actions", len(L["actions"]))
    fy = ""
    if L["basis"] == "budget" and outlook.get("state") == "calculated" and outlook["lines"]["ebitda"].get("gap_vs_budget") is not None:
        o = outlook["lines"]["ebitda"]
        mech = slot("fy_mechanical", money(o["mechanical"]["value"]), "outlook.lines.ebitda.mechanical.value", o["mechanical"]["value"])
        gap = slot("fy_gap", money(o["gap_vs_budget"], sign=True), "outlook.lines.ebitda.gap_vs_budget", o["gap_vs_budget"])
        fy = f" On the trailing three-month run-rate the full year lands at {mech}, {gap} against the full-year budget (a projection rule, not a forecast)."
    text = (f"Adjusted EBITDA is {ebitda_actual} versus {basis} of {ebitda_comp}, a {ebitda_var} ({ebitda_pct}) variance for {L['range']['label']}. "
            f"Revenue contributes {rv}, cost of sales {cv} and operating expenses {ov}. "
            f"{n_mat} account(s) are material and the top three carry {top3} of the gross movement.{fy} {n_act} follow-up item(s) are proposed.")
    return {"text": text, "slots": slots, "forbidden": ["higher than expected", "lower than expected", "business needs", "root cause confirmed"]}
