"""Outcome-level patterns, ranked insights, the executive readout and KPI
diagnoses for one lens. Nothing here computes a new ledger figure: every
number placed in prose is a payload field, registered with its path."""
import math

from .common import Register, is_num, r2, r4, safe_div, lower_words
from .signals import PERSISTENCE_LABEL

DOMINANT = 0.6
CONCENTRATION = 0.5
MARGIN_DIVERGENCE = 0.0025   # 25 bps as a fraction
MAX_INFERENCES = 4

PERSIST_W = {"recurring_level_change": 1.0, "persistent": 0.9, "coverage": 0.9, "seasonal": 0.7, "timing_reversal": 0.6,
             "one_off_candidate": 0.8, "undetermined": 0.7}
OUTCOME_W = {"i:ebitda": 0.4, "i:ebitda_masking": 0.9, "i:margin": 0.4, "i:concentration": 0.35, "i:below_line": 0.6, "i:full_year": 0.9}
CONF_W = {"high": 1.0, "medium": 0.75, "low": 0.5}
OWNER_BY_SECTION = {"rev": "Revenue / FP&A lead", "cos": "Operations finance lead", "opex": "Function head with FP&A",
                    "syn": "Integration / PMO lead", "nonop": "Controller / Treasury"}
WHAT_BY_SECTION = {"rev": "volume, price or mix", "cos": "volume, unit cost or a one-off charge", "opex": "headcount, rate or a one-off item",
                   "syn": "a planned investment or a timing effect", "nonop": "a financing, tax or non-cash item"}
EN_DASH = "–"


def _line(L, lid):
    return next(x for x in L["lines"] if x["id"] == lid)


def _kpi(L, kid):
    return next(x for x in L["kpis"] if x["id"] == kid)


def _test(sg, tid):
    return next((t for t in sg["tests"] if t["id"] == tid), None)


def fav_word(v):
    return "favourable" if v >= 0 else "adverse"


BASIS_WORDS = {"no_comparator": "new this period (no {adj} activity)", "no_activity": "not this period ({basis} only)"}


def basis_words(b, basis):
    """'new this period (no prior-year activity)' / 'not this period (prior year only)' for a one-sided basis, else None."""
    w = BASIS_WORDS.get(b)
    return w.format(basis=basis, adj="prior-year" if basis == "prior year" else basis) if w else None


def basis_note(a, basis):
    w = basis_words(a.get("movement_basis"), basis)
    return f" ({w})" if w else ""


def spans_departments(dep):
    """True when the driver's movement sits in at least two named departments, each carrying at least 5% of the gross
    movement across departments (a department that moved by cents does not make a split); a single department is not news."""
    if not dep:
        return False
    k = "movement" if dep.get("comparable", True) else "actual"
    members = [r for r in dep["rows"] + list((dep.get("other") or {}).get("items") or []) if is_num(r.get(k))]
    gross = sum(abs(r[k]) for r in members)
    named = [r for r in members if r["name"] != "No department" and gross and abs(r[k]) >= 0.05 * gross]
    return len(named) >= 2


def account_label(model, aid):
    """Account name with its subsidiary, so duplicates such as several 'Unrealized Gain/Loss' rows stay distinguishable."""
    a = model.f.accounts[model.aidx[aid]]
    if not a.get("subsidiary") or len(model.f.subs) < 2:
        return a["name"]
    return f"{a['name']} ({a['subsidiary']})"


def _mark_scale(reg, source, scale):
    """Register entries whose display is the payload value times the display sign carry the scale for the validator."""
    if scale == 1.0:
        return
    for n in reg.numbers:
        if n["source"] == source and n.get("scale") is None:
            n["scale"] = scale


def _mark_abs(reg, source):
    for n in reg.numbers:
        if n["source"] == source and n.get("transform") is None:
            n["transform"] = "abs"


def rng_text(reg, lo_po, hi_po, ds, src_lo, src_hi):
    """Display a profit-oriented range low-to-high on the display basis (costs positive), each bound registered against its own source."""
    pairs = sorted([(lo_po * ds, src_lo), (hi_po * ds, src_hi)], key=lambda x: x[0])
    out = []
    for disp, src in pairs:
        out.append(reg.m(disp, src))
        _mark_scale(reg, src, ds)
    return out[0] + EN_DASH + out[1]


# ------------------------------------------------------------------- patterns

def patterns(model, L, signals):
    out = []
    LP = f"lenses[{L['id']}]"
    mon, mgmt = L["materiality"]["monitoring_abs"], L["materiality"]["management_abs"]
    rev, cos, opex, eb, ni = (_line(L, k) for k in ("rev", "cos", "opex", "ebitda", "ni"))
    gpm, ebm = _line(L, "gpm"), _line(L, "ebm")
    basis = L["basis_label"]

    def P(id_, fired, label, reading, evidence):
        out.append({"id": id_, "fired": bool(fired), "label": label, "reading": reading if fired else None,
                    "evidence": {k: (r4(v) if isinstance(v, float) else v) for k, v in evidence.items()}})

    ev = eb["variance"]
    P("in_line", is_num(ev) and abs(ev) < mon, "Result within the monitoring threshold",
      f"Adjusted EBITDA is within the monitoring threshold of {basis}; the discussion is about composition, not the total.", {"ebitda_variance": ev, "monitoring_abs": mon})
    parts = {k: abs(x["variance"] or 0) for k, x in (("rev", rev), ("cos", cos), ("opex", opex))}
    gross = sum(parts.values())
    rev_share = safe_div(parts["rev"], gross) if gross else None
    cost_share = safe_div(parts["cos"] + parts["opex"], gross) if gross else None
    P("revenue_led", rev_share is not None and rev_share >= DOMINANT, "Revenue carries most of the movement",
      f"Revenue carries most of the gross movement against {basis}; cost lines are secondary.", {"revenue_share_of_gross_steps": rev_share})
    P("cost_led", cost_share is not None and cost_share >= DOMINANT, "Cost lines carry most of the movement",
      f"Cost of sales and operating expenses carry most of the gross movement against {basis}; revenue is secondary.", {"cost_share_of_gross_steps": cost_share})
    c = L["concentration"]
    P("concentrated_variance", c["top3_share"] is not None and c["top3_share"] >= CONCENTRATION and c["accounts_with_variance"] >= 4,
      "Variance concentrated in three accounts", "Three accounts carry at least half of the gross account movement: the result is about a few decisions, not a systemic assumption.",
      {"top3_share": c["top3_share"], "top3_accounts": c["top3_accounts"]})
    P("broad_based_variance", c["top3_share"] is not None and c["top3_share"] < 0.35 and c["material_accounts"] >= 4,
      "Variance spread across many accounts", "No three accounts explain the movement: the driver is broad (volume, seasonality, pricing or a plan-wide assumption) rather than specific.",
      {"top3_share": c["top3_share"], "material_accounts": c["material_accounts"]})
    div = is_num(gpm["variance"]) and is_num(ebm["variance"]) and (gpm["variance"] > 0) != (ebm["variance"] > 0) and abs(gpm["variance"]) >= MARGIN_DIVERGENCE and abs(ebm["variance"]) >= MARGIN_DIVERGENCE
    P("margin_earnings_divergence", div, "Gross margin and EBITDA margin move in opposite directions",
      "Gross margin and EBITDA margin moved in opposite directions: the delivery margin and the operating cost base tell different stories.",
      {"gross_margin_bps": gpm["variance"], "ebitda_margin_bps": ebm["variance"]})
    rg = safe_div(rev["actual"] - rev["comparator"], abs(rev["comparator"])) if is_num(rev["actual"]) and is_num(rev["comparator"]) and rev["comparator"] else None
    cost_a = (cos["actual"] or 0) + (opex["actual"] or 0)
    cost_c = (cos["comparator"] or 0) + (opex["comparator"] or 0)
    cg = safe_div(cost_a - cost_c, abs(cost_c)) if cost_c else None
    P("cost_growth_outpacing_revenue", rg is not None and cg is not None and cg > rg + 0.02, "Costs moved faster than revenue",
      f"Operating costs grew faster than revenue against {basis}, so margin compressed even where revenue held.", {"revenue_change_pct": rg, "cost_change_pct": cg})
    P("operating_leverage", rg is not None and cg is not None and rg > cg + 0.02 and rg > 0, "Revenue moved faster than costs",
      f"Revenue grew faster than operating costs against {basis}: operating leverage is working in the period.", {"revenue_change_pct": rg, "cost_change_pct": cg})
    rec = [d for d in L["drivers"] if d["section"] == "rev" and d["label"].lower().startswith("recurring")]
    if rec and is_num(rev["actual_po"]) and rev["actual_po"] and is_num(rev["comparator_po"]) and rev["comparator_po"]:
        sh_a = safe_div(rec[0]["actual_po"], rev["actual_po"]); sh_c = safe_div(rec[0]["comparator_po"], rev["comparator_po"])
        shift = is_num(sh_a) and is_num(sh_c) and abs(sh_a - sh_c) >= 0.01
        P("mix_shift", shift, "Recurring share of revenue moved", "The recurring share of revenue moved by at least a point: part of the revenue story is mix, not level.",
          {"recurring_share_actual": sh_a, "recurring_share_comparator": sh_c, "driver": rec[0]["id"]})
    else:
        P("mix_shift", False, "Recurring share of revenue moved", None, {"reason": "no recurring revenue driver or no revenue"})
    bl = (ni["variance"] - ev) if is_num(ni["variance"]) and is_num(ev) else None
    P("below_the_line_swing", bl is not None and abs(bl) >= mgmt, "Net income moved differently from EBITDA",
      "Synergies, strategic investments or non-operating items moved net income materially away from the EBITDA story.", {"net_income_minus_ebitda_variance": bl})
    lay = L.get("layers") or {}
    if lay.get("state") == "calculated":
        t = lay["totals"]
        P("headline_masks_deterioration", t["reported"] > 0 and t["operational"] < 0 and abs(t["operational"]) >= mon,
          "Favourable headline, adverse operational move", "The headline is favourable only because the budget sat away from recent activity; against its own run-rate the month moved adversely.",
          {"reported": t["reported"], "operational": t["operational"]})
        P("headline_understates_performance", t["reported"] < 0 and t["operational"] > 0 and abs(t["operational"]) >= mon,
          "Adverse headline, favourable operational move", "The headline is adverse although the month improved on its own run-rate: the gap is the plan's level, not this month's execution.",
          {"reported": t["reported"], "operational": t["operational"]})
        P("budget_baseline_dominant", lay["primary_layer"] == "planning", "Budget-baseline dominant",
          "Most of the gap is the budget's distance from recent activity (planning), not the month's own move.", {"planning_share": lay["shares_of_gross"]["planning"]})
        P("execution_dominant", lay["primary_layer"] == "operational", "Execution dominant",
          "Most of the gap is the month's own move against its trailing run-rate (operational), not the plan level.", {"operational_share": lay["shares_of_gross"]["operational"]})
        P("unbudgeted_activity_material", abs(t["coverage"]) >= mon, "Material activity with no budget line",
          "Accounts with no budget line carry material activity: a coverage gap in the plan, reported beside the variance, never netted into it.", {"coverage": t["coverage"]})
    tot_abs = c["abs_variance_total"] or 0
    P("offsetting_variances", is_num(ev) and tot_abs >= 2 * abs(ev) and c["adverse_accounts"] >= 2 and c["favourable_accounts"] >= 2 and tot_abs >= mgmt,
      "Net result hides offsetting account moves", "Favourable and adverse account moves offset: the net figure understates how much changed underneath.",
      {"gross_account_variance": tot_abs, "net_ebitda_variance": ev})
    return out


# -------------------------------------------------------------------- insights

def driver_statements(model, L, d, signals, reg, LP):
    """Observed facts, inferences and the open question for one driver (an L4 group or a single account)."""
    basis = L["basis_label"]
    DP = f"{LP}.drivers[{d['id']}]"
    v = d["variance"]
    st = []
    scope_txt = "the Adjusted EBITDA movement" if d.get("share_scope", "ebitda") == "ebitda" else "the movement from Adjusted EBITDA to net income"
    share = f", {reg.p(d['share_of_abs_variance'], DP + '.share_of_abs_variance')} of {scope_txt}" if is_num(d.get("share_of_abs_variance")) else ""
    if is_num(v):
        st.append({"state": "observed_fact", "evidence_refs": [DP + ".variance"],
                   "text": (f"{d['label']} is {reg.m(d['actual'], DP + '.actual')} against {basis} {reg.m(d['comparator'], DP + '.comparator')}: "
                            f"{reg.m(v, DP + '.variance', sign=True)} ({reg.p(d['variance_pct'], DP + '.variance_pct', sign=True)}), {fav_word(v)} to profit{share}.")})
    else:                                   # active in only one of the two periods
        mv = d["movement"]
        side = f"{reg.m(d['actual'], DP + '.actual')} with no {basis} line" if d["movement_basis"] == "no_comparator" else f"nothing this period against {basis} {reg.m(d['comparator'], DP + '.comparator')}"
        st.append({"state": "observed_fact", "evidence_refs": [DP + ".movement"],
                   "text": f"{d['label']} is {side}: a movement of {reg.m(mv, DP + '.movement', sign=True)}, {fav_word(mv)} to profit{share}."})
    # every ranking uses movement: a one-sided account (new, or stopped) moves the step as much as a two-sided one
    accts = sorted([a for a in L["accounts"] if a["driver_ref"] == d["id"] and is_num(a["movement"]) and a["movement"] != 0],
                   key=lambda a: (-abs(a["movement"]), a["id"]))
    lead = accts[0] if accts else None
    if lead and len(accts) > 1:
        AP = f"{LP}.accounts[{lead['id']}]"
        st.append({"state": "observed_fact", "evidence_refs": [AP + ".movement"],
                   "text": f"{reg.lit(account_label(model, lead['id']))} carries {reg.m(lead['movement'], AP + '.movement', sign=True)} of the step{basis_note(lead, basis)}; "
                           f"the other {len(accts) - 1} account(s) carry the rest."})
        one = [a for a in accts if a["movement_basis"] != "both"]
        if one and abs(sum(a["movement"] for a in one)) >= L["materiality"]["monitoring_abs"]:
            CP = f"{LP}.drivers[{d['id']}]"
            st.append({"state": "observed_fact", "evidence_refs": [CP + ".one_sided_movement"],
                       "text": f"Accounts active in only one of the two periods carry {reg.m(d['one_sided_movement'], CP + '.one_sided_movement', sign=True)}; "
                               f"accounts in both carry {reg.m(d['two_sided_movement'], CP + '.two_sided_movement', sign=True)}."})
    dep = ((L.get("reconciliation") or {}).get(d["id"]) or {}).get("by_department")
    if dep and dep["comparable"] and spans_departments(dep) and is_num(dep["rows"][0]["movement"]) and dep["rows"][0]["name"] != "No department":
        DP2 = f"{LP}.reconciliation[{d['id']}].by_department.rows[0]"
        st.append({"state": "observed_fact", "evidence_refs": [DP2 + ".movement"],
                   "text": f"By department, {reg.lit(dep['rows'][0]['name'])} carries {reg.m(dep['rows'][0]['movement'], DP2 + '.movement', sign=True)} of it."})
    known, ruled_out, suggested = [], [], []
    persistence = "undetermined"
    conf = "low"
    per_acct_cap = {}
    for rank_a, a in enumerate(accts[:2]):
        per_acct_cap[a["id"]] = 3 if rank_a == 0 else 1
        sg = signals[a["id"]]
        name = model.f.accounts[model.aidx[a["id"]]]["name"]
        ds = a["display_sign"]
        SP = f"signals[{a['id']}]"
        fired = set(sg["fired"])
        if L["window"] == "MTD":
            t = _test(sg, "step_change")
            if t and t["state"] == "fired":
                e = t["evidence"]
                up_disp = (e["direction"] == "up") == (ds > 0)
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[step_change]"],
                           "text": (f"{reg.lit(name)}: a step {'up' if up_disp else 'down'} entered in {reg.lit(e['entered_at'])} and held this month, taking the level to "
                                    f"{reg.m(e['new_level'] * ds, SP + '.tests[step_change].evidence.new_level')} a month against an earlier range of "
                                    f"{rng_text(reg, e['earlier_min'], e['earlier_max'], ds, SP + '.tests[step_change].evidence.earlier_min', SP + '.tests[step_change].evidence.earlier_max')}; "
                                    f"this reads as a new level rather than a single-month event.")})
                _mark_scale(reg, SP + ".tests[step_change].evidence.new_level", ds)
                known.append("a new level held for two months"); persistence = "recurring_level_change"
            t = _test(sg, "outlier_month")
            if t and t["state"] == "fired" and "step_change" not in fired and "persistent_gap" not in fired:
                e = t["evidence"]
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[outlier_month]"],
                           "text": (f"{reg.lit(name)}: the month sits {'above' if (e['direction'] == 'above_reference') == (ds > 0) else 'below'} its trailing range "
                                    f"({rng_text(reg, e['trailing_min'], e['trailing_max'], ds, SP + '.tests[outlier_month].evidence.trailing_min', SP + '.tests[outlier_month].evidence.trailing_max')}; "
                                    f"run-rate reference {reg.m(e['reference'] * ds, SP + '.tests[outlier_month].evidence.reference')}): a single-month excursion until a second month confirms it.")})
                _mark_scale(reg, SP + ".tests[outlier_month].evidence.reference", ds)
                known.append("a single-month excursion from the trailing range")
                if persistence == "undetermined":
                    persistence = "one_off_candidate"
            t = _test(sg, "budget_outside_run_rate")
            if t and t["state"] == "fired" and L["basis"] == "budget":
                e = t["evidence"]
                b_disp, r_disp = e["budget"] * ds, e["reference"] * ds
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[budget_outside_run_rate]"],
                           "text": (f"{reg.lit(name)}: the budget ({reg.m(b_disp, SP + '.tests[budget_outside_run_rate].evidence.budget')}) sits {'above' if b_disp > r_disp else 'below'} the run-rate reference of "
                                    f"{reg.m(r_disp, SP + '.tests[budget_outside_run_rate].evidence.reference')} (trailing range "
                                    f"{rng_text(reg, e['trailing_min'], e['trailing_max'], ds, SP + '.tests[budget_outside_run_rate].evidence.trailing_min', SP + '.tests[budget_outside_run_rate].evidence.trailing_max')}); "
                                    f"part of the variance is the plan's distance from recent activity, not this month's execution.")})
                for k in ("budget", "reference"):
                    _mark_scale(reg, SP + f".tests[budget_outside_run_rate].evidence.{k}", ds)
                known.append("a budget set away from the recent run-rate")
            t = _test(sg, "reversal_signal")
            if t and t["state"] == "fired":
                e = t["evidence"]
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[reversal_signal]"],
                           "text": (f"{reg.lit(name)}: last month's variance ({reg.m(e['variance_prior_month'], SP + '.tests[reversal_signal].evidence.variance_prior_month', sign=True)}) reverses this month "
                                    f"({reg.m(e['variance_now'], SP + '.tests[reversal_signal].evidence.variance_now', sign=True)}), which fits a cut-off or accrual pattern rather than a change in activity.")})
                known.append("a reversal of last month's variance")
                if persistence == "undetermined":
                    persistence = "timing_reversal"
            t = _test(sg, "persistent_gap")
            if t and t["state"] == "fired":
                e = t["evidence"]
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[persistent_gap]"],
                           "text": (f"{reg.lit(name)}: the variance has sat on the same side of budget in {e['months_same_side']} of the last {e['months_compared']} months "
                                    f"(cumulative {reg.m(e['cumulative_variance'], SP + '.tests[persistent_gap].evidence.cumulative_variance', sign=True)}); it is not noise.")})
                known.append("a gap that has persisted for most recent months"); ruled_out.append("a single-month excursion")
                if persistence in ("undetermined", "one_off_candidate"):
                    persistence = "persistent"
            t = _test(sg, "seasonal_echo")
            if t and t["state"] == "fired":
                e = t["evidence"]
                st.append({"state": "analytical_inference", "evidence_refs": [SP + ".tests[seasonal_echo]"],
                           "text": (f"{reg.lit(name)}: the same month last year ({reg.lit(e['last_year_month'])}) moved the same way against its own run-rate "
                                    f"({reg.m(e['move_last_year_vs_its_reference'], SP + '.tests[seasonal_echo].evidence.move_last_year_vs_its_reference', sign=True)} to profit), so seasonality is a candidate explanation.")})
                known.append("the same seasonal move last year")
                if persistence in ("undetermined", "one_off_candidate"):
                    persistence = "seasonal"
            if "budget_outside_run_rate" not in fired and "budget_near_run_rate_edge" not in fired and sg["runrate"]["eligible"] and L["basis"] == "budget" and a["budget_status"] == "comparable":
                ruled_out.append("a budget set away from the recent run-rate")
        if a["budget_status"] == "no_comparator":
            st.append({"state": "observed_fact", "evidence_refs": [f"{LP}.accounts[{a['id']}].budget_status"],
                       "text": f"{reg.lit(name)} has no {basis} line: its activity is coverage, not comparable performance."})
            persistence = "coverage"
        if sg["confidence"] in ("high", "medium") and conf == "low":
            conf = sg["confidence"]
    if L["window"] != "MTD":
        st.append({"state": "analytical_inference", "evidence_refs": [],
                   "text": f"Structural signals are tested on the as-of month; the {L['window_label']} variance aggregates several months, so read the month signals on the account drawer before attributing the whole window."})
    facts = [s for s in st if s["state"] == "observed_fact"]
    infs, used_by = [], {}
    for s in st:
        if s["state"] != "analytical_inference":
            continue
        owner_acct = next((aid for aid in per_acct_cap if any(r.startswith(f"signals[{aid}]") for r in s.get("evidence_refs", []))), None)
        if owner_acct is not None:
            used_by[owner_acct] = used_by.get(owner_acct, 0) + 1
            if used_by[owner_acct] > per_acct_cap[owner_acct]:
                continue
        infs.append(s)
    infs = infs[:MAX_INFERENCES]
    st = facts + infs
    known = list(dict.fromkeys(known))
    ruled_out = [x for x in dict.fromkeys(ruled_out) if x not in known]
    owner = OWNER_BY_SECTION[d["section"]]
    what = WHAT_BY_SECTION[d["section"]]
    question = f"Which of {what} moved {lower_words(d['label']) if d['level'] == 'L4' else d['label']} in {L['range']['label']}, and does it continue?"
    st.append({"state": "management_input_required", "evidence_refs": [],
               "text": f"The ledger shows the amount and its history; it does not show whether this is {what}. Confirm with the {owner}."})
    suggested.append(f"ask the {owner} which of {what} moved the line")
    return st, {"known": known, "suggested": suggested, "ruled_out": ruled_out, "question": question}, persistence, conf


def _outcome(reg, id_, label, subject, tier, amount, st, question, persistence, relevance, conf, mgmt, persist_w=0.6):
    score = math.log(1 + abs(amount or 0) / mgmt) * persist_w * relevance * CONF_W[conf]
    return {"id": id_, "kind": "outcome", "subject_ref": subject, "label": label, "section": None, "tier": tier, "amount": r2(amount),
            "executive_conclusion": st[-1]["text"] if st[-1]["state"] == "analytical_inference" else st[0]["text"], "statements": st,
            "causal_gap": {"known": [], "suggested": [], "ruled_out": [], "question": question},
            "persistence": persistence, "persistence_label": PERSISTENCE_LABEL[persistence], "decision_relevance": "high" if relevance >= 0.9 else "medium",
            "confidence": conf, "score": r2(score), "numbers": reg.numbers,
            "score_components": {"magnitude": r2(abs(amount or 0)), "persistence_w": persist_w, "relevance_w": relevance, "confidence_w": CONF_W[conf]}}


def insights(model, L, signals, outlook):
    LP = f"lenses[{L['id']}]"
    mgmt = L["materiality"]["management_abs"]
    out = []
    pats = {p["id"]: p for p in L["patterns"]}
    fired = lambda pid: bool(pats.get(pid, {}).get("fired"))
    masking = fired("headline_masks_deterioration") or fired("headline_understates_performance")
    basis = L["basis_label"]
    # driver insights
    for d in L["drivers"]:
        one_sided = not is_num(d["variance"]) and d.get("movement_tier") in ("executive", "management")
        if not one_sided and (d["tier"] not in ("executive", "management") or not is_num(d["variance"])):
            continue
        reg = Register()
        st, gap, pers, conf = driver_statements(model, L, d, signals, reg, LP)
        relevance = 1.0 if (d["tier"] == "executive" or d.get("rank") == 1) else 0.8
        if pers in ("persistent", "recurring_level_change"):
            relevance = min(1.0, relevance + 0.1)
        score = math.log(1 + abs(d["movement"]) / mgmt) * PERSIST_W[pers] * relevance * CONF_W[conf]
        out.append({"id": f"i:{d['id']}", "kind": "driver", "subject_ref": d["id"], "label": d["label"], "section": d["section"], "tier": d["tier"] if not one_sided else d["movement_tier"],
                    "amount": d["movement"], "executive_conclusion": st[0]["text"], "statements": st, "causal_gap": gap,
                    "persistence": pers, "persistence_label": PERSISTENCE_LABEL[pers], "decision_relevance": "high" if relevance >= 1.0 else "medium",
                    "confidence": conf, "score": r2(score), "numbers": reg.numbers,
                    "score_components": {"magnitude": r2(abs(d["movement"])), "persistence_w": PERSIST_W[pers], "relevance_w": relevance, "confidence_w": CONF_W[conf]}})
    # outcome: EBITDA
    eb, rev, cos, opex = (_line(L, k) for k in ("ebitda", "rev", "cos", "opex"))
    ev = eb["variance"]
    if is_num(ev):
        reg = Register()
        st = [{"state": "observed_fact", "evidence_refs": [LP + ".bridge"],
               "text": (f"Adjusted EBITDA is {reg.m(eb['actual'], LP + '.lines[ebitda].actual')} against {basis} {reg.m(eb['comparator'], LP + '.lines[ebitda].comparator')}: "
                        f"{reg.m(ev, LP + '.lines[ebitda].variance', sign=True)} ({reg.p(eb['variance_pct'], LP + '.lines[ebitda].variance_pct', sign=True)}). Revenue contributes "
                        f"{reg.m(rev['variance'], LP + '.lines[rev].variance', sign=True)}, cost of sales {reg.m(cos['variance'], LP + '.lines[cos].variance', sign=True)} and operating expenses "
                        f"{reg.m(opex['variance'], LP + '.lines[opex].variance', sign=True)}.")}]
        lay = L.get("layers") or {}
        if lay.get("state") == "calculated":
            t = lay["totals"]
            st.append({"state": "analytical_inference", "evidence_refs": [LP + ".layers"],
                       "text": (f"Of the budgeted-account variance, {reg.m(t['planning'], LP + '.layers.totals.planning', sign=True)} is the budget's distance from the run-rate reference (planning) and "
                                f"{reg.m(t['operational'], LP + '.layers.totals.operational', sign=True)} is the month's own move against that reference (operational); activity with no budget line is "
                                f"{reg.m(t['coverage'], LP + '.layers.totals.coverage', sign=True)}.")})
        for pid in ("revenue_led", "cost_led", "offsetting_variances", "in_line", "headline_masks_deterioration", "headline_understates_performance"):
            if fired(pid):
                st.append({"state": "analytical_inference", "text": pats[pid]["reading"], "evidence_refs": [f"{LP}.patterns[{pid}]"]})
        relevance = 1.0 if (masking or fired("budget_baseline_dominant")) else 0.6
        ins = _outcome(reg, "i:ebitda", "Adjusted EBITDA", "ebitda", model.tier(ev, eb["variance_pct"]), ev, st,
                       "Which of the driver questions below does management answer first?", "undetermined", relevance, "high", mgmt,
                       persist_w=OUTCOME_W["i:ebitda_masking"] if (masking or fired("budget_baseline_dominant")) else OUTCOME_W["i:ebitda"])
        ins["executive_conclusion"] = st[0]["text"]
        ins["causal_gap"]["known"] = [p["label"] for p in L["patterns"] if p["fired"]]
        out.append(ins)
    # outcome: margin
    gpm, ebm = _line(L, "gpm"), _line(L, "ebm")
    if is_num(gpm["variance"]) and is_num(ebm["variance"]):
        reg = Register()
        st = [{"state": "observed_fact", "evidence_refs": [LP + ".lines[gpm]", LP + ".lines[ebm]"],
               "text": (f"Gross margin is {reg.p(gpm['actual'], LP + '.lines[gpm].actual')} ({reg.b(gpm['variance'], LP + '.lines[gpm].variance')} against {basis}) and Adjusted EBITDA margin "
                        f"{reg.p(ebm['actual'], LP + '.lines[ebm].actual')} ({reg.b(ebm['variance'], LP + '.lines[ebm].variance')}).")}]
        for pid in ("margin_earnings_divergence", "cost_growth_outpacing_revenue", "operating_leverage", "mix_shift"):
            if fired(pid):
                st.append({"state": "analytical_inference", "text": pats[pid]["reading"], "evidence_refs": [f"{LP}.patterns[{pid}]"]})
        mag = max(abs(gpm["variance"]), abs(ebm["variance"])) * abs(rev["actual"] or 0)
        relevance = 0.9 if any(fired(p) for p in ("margin_earnings_divergence", "cost_growth_outpacing_revenue", "mix_shift")) else 0.5
        out.append(_outcome(reg, "i:margin", "Margin quality", "ebm", None, mag, st,
                            "Is the margin move price, mix or cost intensity? The statement marts carry none of those directly.", "undetermined", relevance, "medium", mgmt, persist_w=OUTCOME_W["i:margin"]))
    # outcome: concentration
    c = L["concentration"]
    if c["top3_share"] is not None:
        reg = Register()
        names = [account_label(model, i) for i in c["top3_accounts"]]
        st = [{"state": "observed_fact", "evidence_refs": [LP + ".concentration"],
               "text": (f"Three accounts ({', '.join(reg.lit(n) for n in names)}) carry {reg.p(c['top3_share'], LP + '.concentration.top3_share')} of the gross account movement; "
                        f"{c['adverse_accounts']} accounts are adverse and {c['favourable_accounts']} favourable.")}]
        for pid in ("concentrated_variance", "broad_based_variance"):
            if fired(pid):
                st.append({"state": "analytical_inference", "text": pats[pid]["reading"], "evidence_refs": [f"{LP}.patterns[{pid}]"]})
        relevance = 0.7 if (fired("concentrated_variance") or fired("broad_based_variance")) else 0.4
        out.append(_outcome(reg, "i:concentration", "Where the movement sits", "concentration", None, c["abs_variance_total"], st,
                            "Do the three largest accounts share one cause, or three?", "undetermined", relevance, "high", mgmt, persist_w=OUTCOME_W["i:concentration"]))
    # outcome: below the line
    if fired("below_the_line_swing"):
        reg = Register()
        ni = _line(L, "ni")
        bl = ni["variance"] - ev
        st = [{"state": "observed_fact", "evidence_refs": [LP + ".bridge.to_net_income"],
               "text": (f"Net income is {reg.m(ni['actual'], LP + '.lines[ni].actual')} against {basis} {reg.m(ni['comparator'], LP + '.lines[ni].comparator')} "
                        f"({reg.m(ni['variance'], LP + '.lines[ni].variance', sign=True)}), while Adjusted EBITDA moved {reg.m(ev, LP + '.lines[ebitda].variance', sign=True)}: the difference sits below the line.")},
              {"state": "analytical_inference", "text": pats["below_the_line_swing"]["reading"], "evidence_refs": [f"{LP}.patterns[below_the_line_swing]"]}]
        out.append(_outcome(reg, "i:below_line", "Below the line", "ni", model.tier(bl, None), bl, st,
                            "Which synergy, investment or non-operating item moved, and is it in the forecast?", "undetermined", 0.8, "high", mgmt, persist_w=OUTCOME_W["i:below_line"]))
    # outcome: full year (budget basis, outlook with a full-year budget)
    if L["basis"] == "budget" and outlook.get("state") == "calculated" and outlook["lines"]["ebitda"].get("gap_vs_budget") is not None:
        reg = Register()
        o = outlook["lines"]["ebitda"]
        OP = "outlook.lines.ebitda"
        st = [{"state": "observed_fact", "evidence_refs": [OP + ".ytd"],
               "text": (f"Year to date Adjusted EBITDA is {reg.m(o['ytd']['actual'], OP + '.ytd.actual')} against budget {reg.m(o['ytd']['budget'], OP + '.ytd.budget')} "
                        f"({reg.m(o['ytd']['variance'], OP + '.ytd.variance', sign=True)}) after {o['periods_realized']} of {o['periods_total']} periods.")},
              {"state": "analytical_inference", "evidence_refs": [OP + ".mechanical"],
               "text": (f"Carrying the trailing three-month run-rate for the remaining {o['remaining_months']} months gives a mechanical full-year outlook of "
                        f"{reg.m(o['mechanical']['value'], OP + '.mechanical.value')} against the full-year budget of {reg.m(o['fy_budget'], OP + '.fy_budget')}: "
                        f"{reg.m(o['gap_vs_budget'], OP + '.gap_vs_budget', sign=True)}. This is a projection rule, not a forecast; nothing declared by management is included.")}]
        out.append(_outcome(reg, "i:full_year", "Full-year implication", "outlook", model.tier(o["gap_vs_budget"], None), o["gap_vs_budget"], st,
                            "Which of the period variances persist for the rest of the year, and which reverse?", "undetermined", 0.8, "medium", mgmt, persist_w=0.9))
    out.sort(key=lambda i: (-(i["score"] or 0), -abs(i["amount"] or 0), i["id"]))
    for r, i in enumerate(out, start=1):
        i["rank"] = r
    return out


# --------------------------------------------------------------------- readout

def readout(model, L, outlook):
    ins = L["insights"]
    LP = f"lenses[{L['id']}]"
    reg = Register()
    eb = _line(L, "ebitda")
    basis = L["basis_label"]
    v = eb["variance"]
    mon = L["materiality"]["monitoring_abs"]
    if not is_num(v):
        ahead = f"Adjusted EBITDA has no {basis} comparison for {L['range']['label']}."
    elif abs(v) < mon:
        ahead = f"Adjusted EBITDA is in line with {basis} for {L['range']['label']} ({reg.m(v, LP + '.lines[ebitda].variance', sign=True)})."
    else:
        ahead = (f"Adjusted EBITDA is {'ahead of' if v > 0 else 'behind'} {basis} by {reg.m(abs(v), LP + '.lines[ebitda].variance')} "
                 f"({reg.p(abs(eb['variance_pct']) if is_num(eb['variance_pct']) else None, LP + '.lines[ebitda].variance_pct')}) for {L['range']['label']}.")
        _mark_abs(reg, LP + ".lines[ebitda].variance"); _mark_abs(reg, LP + ".lines[ebitda].variance_pct")
    drv = [i for i in ins if i["kind"] == "driver"]
    top = sorted(drv, key=lambda i: -abs(i["amount"]))[:3]
    what = ("The largest driver movements are " + "; ".join(f"{i['label']} {reg.m(i['amount'], LP + '.drivers[' + i['subject_ref'] + '].movement', sign=True)}" for i in top) + "."
            if top else "No driver reaches the management materiality threshold.")
    quality = next((i["executive_conclusion"] for i in ins if i["id"] == "i:margin"), "Margins are not comparable in this lens.")
    temp = [f"{i['label']}: {i['persistence_label']}" for i in top]
    fy = next((i["executive_conclusion"] for i in ins if i["id"] == "i:full_year"), None)
    if fy is None and L["basis"] != "budget":
        fy = "The full-year outlook applies to the budget comparison; switch the comparator to budget."
    elif fy is None and outlook.get("state") == "calculated":
        o = outlook["lines"]["ebitda"]
        fy = (f"Carrying the trailing three-month run-rate for the remaining {o['remaining_months']} month(s) gives a mechanical full-year Adjusted EBITDA of "
              f"{reg.m(o['mechanical']['value'], 'outlook.lines.ebitda.mechanical.value')} (year to date {reg.m(o['ytd']['actual'], 'outlook.lines.ebitda.ytd.actual')}); "
              f"the full-year budget is not in the extract, so no gap is stated. A projection rule, not a forecast.")
    elif fy is None:
        fy = outlook.get("reason") or "Full-year outlook not calculated."
    roles, used = [], set()
    cand_driver = next((i for i in ins if i["kind"] == "driver"), None)
    if cand_driver:
        roles.append({"role": "current_period_driver", "insight_ref": cand_driver["id"]}); used.add(cand_driver["id"])
    cand_quality = next((i for pref in ("i:margin", "i:below_line", "i:concentration", "i:ebitda") for i in ins if i["id"] == pref and i["id"] not in used), None)
    if cand_quality:
        roles.append({"role": "performance_quality", "insight_ref": cand_quality["id"]}); used.add(cand_quality["id"])
    cand_fwd = next((i for i in ins if i["id"] == "i:full_year" and i["id"] not in used), None) or \
        next((i for i in ins if i["kind"] == "driver" and i["persistence"] in ("persistent", "recurring_level_change") and i["id"] not in used), None) or \
        next((i for i in ins if i["id"] not in used), None)
    if cand_fwd:
        roles.append({"role": "forward_looking", "insight_ref": cand_fwd["id"]}); used.add(cand_fwd["id"])
    return {"answers": {"ahead_or_behind": ahead, "what_drove": what, "quality_of_result": quality, "temporary_or_structural": temp, "full_year_implication": fy},
            "top_three": roles, "numbers": reg.numbers,
            "ranking": {"method": "score = ln(1 + magnitude / management_abs) x persistence weight x decision relevance x confidence; ties by |amount| then id",
                        "candidates": [{"id": i["id"], "score": i["score"], **i["score_components"]} for i in ins]}}


# ----------------------------------------------------------------------- story

STORY_LINES = (("rev", "Revenue", False), ("cos", "Cost of sales", True), ("opex", "Operating expenses", True),
               ("ebitda", "Adjusted EBITDA", None), ("syn", "Synergies and strategic investments", True), ("nonop", "Non-operating income (expense)", False))
GROWTH_PATTERNS = ("operating_leverage", "cost_growth_outpacing_revenue")


def _vs(reg, line, src, basis, cost, mon):
    """'$76k (47.8%) below budget' / '$27k (5.1%) over budget' / 'in line with budget'. Absolute displays carry transform=abs."""
    v, vp = line.get("variance"), line.get("variance_pct")
    if not is_num(v):
        return f"no {basis} comparison"
    if abs(v) < mon:
        return f"in line with {basis}"
    amt = reg.m(abs(v), src + ".variance"); _mark_abs(reg, src + ".variance")
    if is_num(vp):
        amt += f" ({reg.p(abs(vp), src + '.variance_pct')})"; _mark_abs(reg, src + ".variance_pct")
    word = ("over" if v < 0 else "under") if cost else ("above" if v > 0 else "below")
    return f"{amt} {word} {basis}"


def _growth(reg, vp, src, cost):
    """Growth on prior year from a profit-oriented variance_pct; costs are sign-flipped to read as cost growth (scale -1)."""
    if not is_num(vp):
        return "is not comparable"
    g = -vp if cost else vp
    if g >= 0:
        d = reg.p(g, src)
        if cost:
            _mark_scale(reg, src, -1.0)
        return f"grew {d}"
    d = reg.p(abs(g), src); _mark_abs(reg, src)
    return f"fell {d}"


def story(model, L, lenses):
    """Net-income-first narrative for the executive summary: the bottom line, one sentence per P&L line from
    revenue down to non-operating, growth against cost on prior year, and how the movement spreads across
    accounts. Wording is picked from signs only; each piece carries its own register of payload paths."""
    LP = f"lenses[{L['id']}]"
    basis = L["basis_label"]
    mon = L["materiality"]["monitoring_abs"]
    lines = {x["id"]: x for x in L["lines"]}
    pieces = {}

    # the bottom line
    reg = Register()
    ni, eb, nonop, syn = lines["ni"], lines["ebitda"], lines["nonop"], lines["syn"]
    has_syn = is_num(syn.get("variance")) and abs(syn["variance"]) >= mon
    if is_num(ni.get("actual")):
        text = f"Net income was {reg.m(ni['actual'], LP + '.lines[ni].actual')} for {L['range']['label']}, {_vs(reg, ni, LP + '.lines[ni]', basis, False, mon)}"
        twin_id = f"{L['window']}_{'py' if L['basis'] == 'budget' else 'budget'}"
        T = lenses.get(twin_id)
        if T and T.get("available"):
            tni = next(x for x in T["lines"] if x["id"] == "ni")
            tv, tvp, TS = tni.get("variance"), tni.get("variance_pct"), f"lenses[{twin_id}].lines[ni]"
            if is_num(tv) and abs(tv) < mon:
                text += f", in line with {T['basis_label']}"
            elif is_num(tv):
                amt = reg.m(abs(tv), TS + ".variance"); _mark_abs(reg, TS + ".variance")
                if is_num(tvp):
                    amt += f" ({reg.p(abs(tvp), TS + '.variance_pct')})"; _mark_abs(reg, TS + ".variance_pct")
                text += f"; against {T['basis_label']} it is {'up' if tv > 0 else 'down'} {amt}"
        text += "."
        if is_num(eb.get("variance")) and is_num(nonop.get("variance")) and is_num(ni.get("variance")):
            text += (f" Adjusted EBITDA accounts for {reg.m(eb['variance'], LP + '.lines[ebitda].variance', sign=True)} of the movement"
                     + (f", synergies and strategic investments {reg.m(syn['variance'], LP + '.lines[syn].variance', sign=True)}" if has_syn else "")
                     + f" and non-operating items {reg.m(nonop['variance'], LP + '.lines[nonop].variance', sign=True)}.")
    else:
        text = f"Net income is not available for {L['range']['label']}."
    pieces["lead"] = {"text": text, "numbers": reg.numbers}

    # one sentence per line, revenue down to non-operating
    out_lines = []
    for lid, label, cost in STORY_LINES:
        if lid == "syn" and not has_syn:
            continue
        ln, reg, src = lines[lid], Register(), f"{LP}.lines[{lid}]"
        if not is_num(ln.get("actual")):
            continue
        text = f"{reg.m(ln['actual'], src + '.actual')}, {_vs(reg, ln, src, basis, bool(cost), mon)}"
        top = None
        if lid == "ebitda":
            for rid, rlab in (("ebm", "EBITDA margin"), ("gpm", "gross margin")):
                r = lines.get(rid) or {}
                if is_num(r.get("actual")):
                    text += f"; {rlab} {reg.p(r['actual'], f'{LP}.lines[{rid}].actual')}" + (f" ({reg.b(r['variance'], f'{LP}.lines[{rid}].variance')})" if is_num(r.get("variance")) else "")
        else:
            cands = [d for d in L["drivers"] if d["section"] == lid and is_num(d["variance"]) and abs(d["variance"]) >= 0.5]
            top = max(cands, key=lambda d: (abs(d["variance"]), d["id"]), default=None)
            if top:
                dsrc = f"{LP}.drivers[{top['id']}].variance"
                text += f"; largest mover {reg.lit(top['label'])} {reg.m(top['variance'], dsrc, sign=True)}"
        out_lines.append({"id": lid, "label": label, "is_cost": bool(cost), "subtotal": cost is None, "text": text + ".",
                          "top_driver": top["id"] if top else None, "numbers": reg.numbers})
    pieces["lines"] = out_lines

    # growth against cost, on prior year, from the longest available prior-year window
    reg = Register()
    Lg = next((lenses[f"{w}_py"] for w in ("LTM", "YTD", "QTD", "MTD") if lenses.get(f"{w}_py", {}).get("available")), None)
    if Lg:
        GP = f"lenses[{Lg['id']}].lines"
        gl = {x["id"]: x for x in Lg["lines"]}
        text = (f"Over the {Lg['window_label']} revenue {_growth(reg, gl['rev'].get('variance_pct'), GP + '[rev].variance_pct', False)} on prior year, "
                f"while cost of sales {_growth(reg, gl['cos'].get('variance_pct'), GP + '[cos].variance_pct', True)} and operating expenses "
                f"{_growth(reg, gl['opex'].get('variance_pct'), GP + '[opex].variance_pct', True)}.")
        pat = next((p for p in Lg.get("patterns", []) if p["id"] in GROWTH_PATTERNS and p["fired"]), None)
        pieces["growth"] = {"lens": Lg["id"], "window": Lg["window"], "text": text, "numbers": reg.numbers,
                            "pattern": {"id": pat["id"], "reading": pat["reading"], "source": f"lenses[{Lg['id']}].patterns[{pat['id']}]"} if pat else None}
    else:
        pieces["growth"] = {"lens": None, "window": None, "text": "No prior-year comparison is available.", "numbers": [], "pattern": None}

    # how the movement spreads across accounts
    reg = Register()
    c, CP = L["concentration"], f"{LP}.concentration"
    text = (f"{reg.c(c['accounts_with_variance'], CP + '.accounts_with_variance')} of {reg.c(c['accounts_total'], CP + '.accounts_total')} accounts moved "
            f"({reg.c(c['adverse_accounts'], CP + '.adverse_accounts')} adverse, {reg.c(c['favourable_accounts'], CP + '.favourable_accounts')} favourable).")
    acc_by = {a["id"]: a for a in L["accounts"]}
    top3 = [acc_by[i] for i in c.get("top3_accounts") or [] if i in acc_by and is_num(acc_by[i]["movement"])]
    if top3 and is_num(c.get("top3_share")):
        movers = []
        for a in top3:
            asrc = f"{LP}.accounts[{a['id']}].movement"
            movers.append(f"{reg.lit(account_label(model, a['id']))} {reg.m(a['movement'], asrc, sign=True)}{basis_note(a, basis)}")
        text += f" {', '.join(movers)} lead; together they carry {reg.p(c['top3_share'], CP + '.top3_share')} of the gross movement."
    pieces["accounts"] = {"text": text, "numbers": reg.numbers}
    return pieces


# --------------------------------------------------------------- KPI diagnoses

def kpi_diagnoses(model, L, outlook):
    LP = f"lenses[{L['id']}]"
    basis = L["basis_label"]
    mon = L["materiality"]["monitoring_abs"]
    out = []
    secs = {"revenue": ("rev",), "gross_profit": ("rev", "cos"), "ebitda": ("rev", "cos", "opex"), "opex": ("opex",), "net_income": ("rev", "cos", "opex", "syn", "nonop"),
            "cogs": ("cos",), "nonop": ("nonop",)}
    comp = {"gross_profit": ("rev", "cos"), "ebitda": ("rev", "cos", "opex"), "net_income": ("ebitda", "syn", "nonop"), "revenue": (), "opex": (), "cogs": (), "nonop": ()}
    labels = {"rev": "Revenue", "cos": "Cost of sales", "opex": "Operating expenses", "ebitda": "Adjusted EBITDA", "syn": "Synergies and strategic investments", "nonop": "Non-operating"}
    for k in L["kpis"]:
        reg = Register()
        KP = f"{LP}.kpis[{k['id']}]"
        v = k["variance"]
        if not is_num(v):
            answer = f"{k['label']} has no {basis} comparison in this window."
        elif abs(v) < mon:
            answer = f"{k['label']} is in line with {basis}: {reg.m(k['actual'], KP + '.actual')} against {reg.m(k['comparator'], KP + '.comparator')}."
        else:
            answer = (f"{k['label']} is {reg.m(k['actual'], KP + '.actual')} against {basis} {reg.m(k['comparator'], KP + '.comparator')}: "
                      f"{reg.m(v, KP + '.variance', sign=True)} ({reg.p(k['variance_pct'], KP + '.variance_pct', sign=True)}), {fav_word(v)} to profit.")
        if is_num(k.get("margin_bps")):
            answer += f" Margin {reg.p(k['margin_actual'], KP + '.margin_actual')}, {reg.b(k['margin_bps'], KP + '.margin_bps')} against {basis}."
        decomposition = [{"line": lid, "label": labels[lid], "variance": _line(L, lid)["variance"], "source": f"{LP}.lines[{lid}].variance"}
                         for lid in comp[k["id"]] if is_num(_line(L, lid)["variance"])]
        drivers = sorted([d for d in L["drivers"] if d["section"] in secs[k["id"]] and is_num(d["variance"])], key=lambda d: -abs(d["variance"]))[:4]
        drv = [{"driver": d["id"], "label": d["label"], "variance": d["variance"], "tier": d["tier"], "source": f"{LP}.drivers[{d['id']}].variance"} for d in drivers]
        questions = [i["causal_gap"]["question"] for i in L["insights"] if i["kind"] == "driver" and i["section"] in secs[k["id"]]][:3]
        ol = None
        if L["basis"] == "budget" and outlook.get("state") == "calculated":
            key = {"revenue": "rev", "ebitda": "ebitda", "net_income": "ni"}.get(k["id"])
            if key and outlook["lines"][key].get("gap_vs_budget") is not None:
                o = outlook["lines"][key]
                ol = (f"Mechanical full-year outlook {reg.m(o['mechanical']['value'], f'outlook.lines.{key}.mechanical.value')} against full-year budget "
                      f"{reg.m(o['fy_budget'], f'outlook.lines.{key}.fy_budget')} ({reg.m(o['gap_vs_budget'], f'outlook.lines.{key}.gap_vs_budget', sign=True)}); a projection rule, not a forecast.")
            elif key:
                o = outlook["lines"][key]
                ol = f"Mechanical full-year outlook {reg.m(o['mechanical']['value'], f'outlook.lines.{key}.mechanical.value')} on the trailing three-month run-rate; the full-year budget is not in the extract."
        out.append({"kpi": k["id"], "label": k["label"], "answer": answer, "decomposition": decomposition, "drivers": drv, "outlook": ol,
                    "questions": questions, "evidence_refs": [KP], "numbers": reg.numbers})
    return out
