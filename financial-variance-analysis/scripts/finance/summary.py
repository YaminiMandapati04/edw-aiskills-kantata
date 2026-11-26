"""The executive summary bullets for one lens.

Built here, from engine fields, so every figure is registered with its payload path, every bullet carries the drill
target its claim rests on ({level, ids, support}), and every lead states a claim that validate.py re-checks against
the numbers: "revenue-led" only when revenue is the largest contributor in the direction of the result, "growth
outpacing cost" only when Adjusted EBITDA and its margin both rose, "margin expanding" only when the margin rose,
and a window whose latest month moved the other way reads "margin mixed". The renderer only displays them."""
from .common import Register, is_num, r4
from .synthesis import _growth, _mark_abs, _test, account_label


def join_and(xs):
    xs = list(xs)
    return xs[0] if len(xs) < 2 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _tone(v, mon=0.0):
    return "neu" if not is_num(v) or abs(v) < mon else ("fav" if v > 0 else "unf")


def _bullet(id_, tone, head, text, drill, reg, claim=None, evidence=None, short=None):
    """head: the bold lead; short: the one line shown on the page (at most 15 words, no figures); text: the full sentence
    with its registered figures, shown when the bullet is opened, above the evidence it drills to."""
    return {"id": id_, "tone": tone, "head": head, "short": short or _shorten(text), "text": text, "drill": drill, "claim": claim,
            "evidence": evidence or {}, "numbers": reg.numbers}


def _shorten(text):
    """Fallback only: the first clause, cut at fifteen words."""
    first = text.split(":")[0].split(";")[0]
    w = first.split()
    return (" ".join(w[:15]).rstrip(",") + ("…" if len(w) > 15 else "")).rstrip(".") + "."


def _lead_short(claim, head, nv, basis, item, oo):
    """One line, no figures, for the lead: where net income stands and what carries it."""
    ahead = is_num(nv) and nv > 0
    uv = (oo or {}).get("underlying_variance")
    if claim == "below_line_led":
        if is_num(uv) and (uv > 0) != ahead:
            return f"Net income is {'ahead of' if ahead else 'behind'} {basis} only on a one-off item outside operations."
        line = f"Net income is {'ahead of' if ahead else 'behind'} {basis}, mostly on {item}, not operations."
        return line if len(line.split()) <= 15 else f"Net income is {'ahead of' if ahead else 'behind'} {basis}, mostly below the line, not operations."
    if claim == "on_plan":
        return f"Net income is in line with {basis}; nothing needs intervention this period."
    if claim == "revenue_led":
        return f"Net income is {'ahead of' if ahead else 'behind'} {basis} on revenue, with costs held."
    if claim == "cost_led":
        return (f"Net income is ahead of {basis} on lower spending, which may be timing." if ahead
                else f"Net income is behind {basis} on costs, with revenue held.")
    if claim == "growth_outpacing_cost":
        return "Revenue grew faster than cost, so more of it reaches net income."
    if claim == "growth_absorbed":
        return (f"Revenue grew, but cost absorbed part of it; net income is still ahead of {basis}." if ahead
                else f"Revenue grew, but cost grew more, so net income is behind {basis}.")
    if head.startswith("Savings"):
        return f"Lower costs only partly offset the revenue gap against {basis}."
    return (f"Net income beats {basis} on revenue and cost together; no single line carries it." if ahead
            else f"Revenue and costs both moved against {basis}; net income is behind on both.")



def _amt(reg, v, src):
    d = reg.m(abs(v), src)
    _mark_abs(reg, src)
    return d


def _rev_move(reg, v, src, bud):
    a = _amt(reg, v, src)
    if bud:
        return f"fell {a} short of budget" if v < 0 else f"beat budget by {a}"
    return f"fell {a} on prior year" if v < 0 else f"grew {a} on prior year"


def _cost_move(reg, v, src, bud):
    """v is profit-oriented: negative means costs went up."""
    a = _amt(reg, v, src)
    if bud:
        return f"ran {a} over budget" if v < 0 else f"came in {a} under budget"
    return f"rose {a} on prior year" if v < 0 else f"fell {a} on prior year"


def _line(L, lid):
    return next(x for x in L["lines"] if x["id"] == lid)


def lead(model, L, lenses, mon):
    LP = f"lenses[{L['id']}]"
    reg = Register()
    ni, eb, rev, ebm = (_line(L, k) for k in ("ni", "ebitda", "rev", "ebm"))
    bud, basis = L["basis"] == "budget", L["basis_label"]
    nv, rv, ev = ni["variance"], rev["variance"], eb["variance"]
    cv, below = L["totals"]["cost_variance"], L["totals"]["below_line_variance"]
    if not is_num(nv):
        return _bullet("lead", "neu", "Not comparable.", f"Net income has no {basis} comparison for {L['range']['label']}.",
                       {"level": "line", "ids": ["ni"]}, reg, claim="not_comparable", short=f"Net income cannot be compared with {basis} for this window.")
    if abs(nv) < mon:
        where = f"in line with {basis}"
    else:
        where = _amt(reg, nv, LP + ".lines[ni].variance")
        if is_num(ni["variance_pct"]) and abs(ni["variance_pct"]) < 0.1:
            where += f" ({reg.p(abs(ni['variance_pct']), LP + '.lines[ni].variance_pct')})"
            _mark_abs(reg, LP + ".lines[ni].variance_pct")
        where += f" {'ahead of' if nv > 0 else 'behind'} {basis}"
    twin_id = f"{L['window']}_{'py' if bud else 'budget'}"
    T, twin = lenses.get(twin_id), ""
    if T and T.get("available"):
        tv = _line(T, "ni")["variance"]
        if is_num(tv) and abs(tv) >= mon:
            twin = f" and {'up' if tv > 0 else 'down'} {_amt(reg, tv, f'lenses[{twin_id}].lines[ni].variance')} on {T['basis_label']}"
    head_ni = f"Net income {reg.m(ni['actual'], LP + '.lines[ni].actual')} is {where}{twin}"
    R, C, ALL = ["rev"], ["cos", "opex"], ["rev", "cos", "opex"]
    rM, cM = is_num(rv) and abs(rv) >= mon, is_num(cv) and abs(cv) >= mon
    rev_largest = is_num(rv) and is_num(cv) and abs(rv) >= abs(cv)
    rsrc, csrc = LP + ".lines[rev].variance", LP + ".totals.cost_variance"
    if abs(nv) < mon:
        head, mean, claim, drill = "On plan.", "no P&L line moved enough to change the picture, so the month needs monitoring, not intervention", "on_plan", {"level": "line", "ids": ["ni"]}
    elif is_num(below) and is_num(ev) and abs(below) > abs(ev) and (below > 0) == (nv > 0):
        # name the below-the-line item that carries it, and say what operations did: same way, the other way, or flat
        bl = [d for d in L["drivers"] if d["section"] in ("nonop", "syn") and is_num(d["movement"]) and d["movement"] != 0 and (d["movement"] > 0) == (below > 0)]
        top = max(bl, key=lambda d: (abs(d["movement"]), d["id"]), default=None)
        ahead, basis_w = nv > 0, basis
        led = (f", led by {reg.lit(top['label'])} ({reg.m(top['movement'], LP + '.drivers[' + top['id'] + '].movement', sign=True)})" if top else "")
        moved = (f"non-operating items moved {reg.m(below, LP + '.totals.below_line_variance', sign=True)}{led}, against "
                 f"{reg.m(ev, LP + '.lines[ebitda].variance', sign=True)} from Adjusted EBITDA")
        item = top["label"] if top else "below-the-line items"
        if abs(ev) < mon:
            head = f"{'Ahead' if ahead else 'Behind'}, all below the line."
            mean = f"{moved}, so operations are in line and the whole result sits below the line"
        elif (ev > 0) == ahead:
            head = f"{'Ahead' if ahead else 'Behind'}, mostly on {item}."
            mean = (f"{moved}; operations moved the same way, but most of the {'gain' if ahead else 'gap'} sits outside day-to-day operations"
                    + (f", so confirm {item} repeats before relying on it" if ahead else ", so the operating result is better than net income suggests"))
        else:
            head = f"{item} {'covers an operating shortfall' if ahead else 'outweighs an operating gain'}."
            head = head[0].upper() + head[1:]
            mean = f"{moved}, so operations are {'behind' if ahead else 'ahead of'} {basis_w} even though net income is {'ahead' if ahead else 'behind'}"
        claim, drill = "below_line_led", {"level": "section", "ids": ["nonop", "syn"], "support": ["ebitda"]}
    elif nv > 0:
        if rM and rv > 0 and rev_largest and not (cM and cv < 0):
            if cM:
                head, claim, drill = "A broad beat.", "broad", {"level": "section", "ids": ALL}
                mean = f"revenue {_rev_move(reg, rv, rsrc, bud)} and costs {_cost_move(reg, cv, csrc, bud)}"
            else:
                head, claim, drill = "Revenue-led.", "revenue_led", {"level": "section", "ids": R, "support": C}
                mean = f"revenue {_rev_move(reg, rv, rsrc, bud)} with costs held, so the beat sits in the top line rather than in lower spending"
        elif rM and rv > 0 and cM and cv < 0:
            ebv = ebm["variance"]
            drill = {"level": "section", "ids": ALL}
            if is_num(ev) and ev > 0 and is_num(ebv) and ebv >= 0:
                head, claim = "Growth outpacing cost.", "growth_outpacing_cost"
                mean = (f"revenue {_rev_move(reg, rv, rsrc, bud)} while costs {_cost_move(reg, cv, csrc, bud)}, and EBITDA margin rose "
                        f"{reg.pt(ebv, LP + '.lines[ebm].variance')}, so growth is reaching profit")
            else:
                head, claim = "Growth, partly absorbed by cost.", "growth_absorbed"
                mean = (f"revenue {_rev_move(reg, rv, rsrc, bud)} but costs {_cost_move(reg, cv, csrc, bud)}"
                        + (f"; EBITDA margin fell {reg.pt(ebv, LP + '.lines[ebm].variance')}" if is_num(ebv) and ebv < 0 else "")
                        + ", so less of each dollar of revenue reaches profit")
        elif cM and cv > 0 and not rev_largest:
            head, claim, drill = "Cost-led.", "cost_led", {"level": "section", "ids": C, "support": R}
            mean = f"costs {_cost_move(reg, cv, csrc, bud)} while revenue held, so the beat depends on spending staying at this level; whether it is timing is to be confirmed"
        else:
            head, mean, claim, drill = "A broad beat.", "no single P&L line carries the result", "broad", {"level": "section", "ids": ALL}
    else:
        if cM and cv < 0 and not rev_largest and not (rM and rv < 0):
            head, claim, drill = "A cost gap, with revenue held.", "cost_led", {"level": "section", "ids": C, "support": R}
            mean = f"costs {_cost_move(reg, cv, csrc, bud)} while revenue held, so the gap sits in costs rather than in the top line"
        elif rM and rv < 0 and rev_largest and not (cM and cv < 0):
            head, claim, drill = "A top-line shortfall.", "revenue_led", {"level": "section", "ids": R, "support": C}
            mean = (f"revenue {_rev_move(reg, rv, rsrc, bud)} while costs held, so the gap sits in the top line; it may reflect customer, volume or price movement, "
                    "which the data model does not carry, so it is to be confirmed")
        elif rM and cM and rv > 0:
            head, claim, drill = "Growth absorbed by cost.", "growth_absorbed", {"level": "section", "ids": ALL}
            mean = f"revenue {_rev_move(reg, rv, rsrc, bud)}, but costs {_cost_move(reg, cv, csrc, bud)}, so growth is not reaching the bottom line"
        elif rM and cM and cv > 0:
            head, claim, drill = "Savings could not cover the revenue gap.", "broad", {"level": "section", "ids": ALL}
            mean = f"revenue {_rev_move(reg, rv, rsrc, bud)} and lower costs ({_amt(reg, cv, csrc)}) only partly offset it"
        else:
            head, claim, drill = "A broad miss.", "broad", {"level": "section", "ids": ALL}
            mean = "revenue and costs both moved against the result, so closing the gap needs action on both lines" if rM and cM else "no single P&L line carries the result"
    if claim != "below_line_led" and abs(nv) >= mon:
        pd = next((d for d in _mat_drivers(L, mon) if (d["movement"] > 0) == (nv > 0)), None)
        if pd:
            head_ni += f", led by {reg.lit(pd['label'])} ({reg.m(pd['movement'], LP + '.drivers[' + pd['id'] + '].movement', sign=True)})"
    tail = _lead_tail(L, reg, LP, basis, mon)
    item = locals().get("item", "below-the-line items")
    return _bullet("lead", _tone(nv, mon), head, f"{head_ni}: {mean}.{tail}", drill, reg, claim=claim,
                   short=_lead_short(claim, head, nv, basis, item, L.get("one_offs")))


def _lead_tail(L, reg, LP, basis, mon):
    """Net income without the named one-off item(s), when that applies."""
    tail = ""
    oo = L.get("one_offs") or {}
    uv = oo.get("underlying_variance")
    if oo.get("named") and is_num(uv):
        top = oo["named"][0]
        if oo["named_count"] == 1:
            what = f"the {reg.lit(top['name'])} item in {top['month']} ({reg.m(top['amount'], LP + '.one_offs.named[0].amount', sign=True)})"
        else:
            what = f"{reg.c(oo['named_count'], LP + '.one_offs.named_count')} one-off items ({reg.m(oo['named_total'], LP + '.one_offs.named_total', sign=True)})"
        rest = f"in line with {basis}" if abs(uv) < mon else f"{_amt(reg, uv, LP + '.one_offs.underlying_variance')} {'ahead of' if uv > 0 else 'behind'} {basis}"
        tail += f" Excluding {what}, net income is {rest}."
    return tail


def _mat_drivers(L, mon):
    return sorted([d for d in L["drivers"] if is_num(d["movement"]) and abs(d["movement"]) >= mon and d["section"] != "nonop"],
                  key=lambda d: (-abs(d["movement"]), d["id"]))


def _lead_account(L, d):
    accts = [a for a in L["accounts"] if a["driver_ref"] == d["id"] and is_num(a["movement"])]
    return max(accts, key=lambda a: (abs(a["movement"]), a["id"]), default=None)


def persistence(model, L, signals, mon, SP):
    if L["window"] != "MTD" or L["basis"] != "budget":
        return None
    cls = []
    for d in _mat_drivers(L, mon):
        la = _lead_account(L, d)
        cls.append((d, la, signals[la["id"]]["persistence_hint"] if la else None))
    stru = [x for x in cls if x[2] in ("persistent", "recurring_level_change")]
    one = [x for x in cls if x[2] == "one_off_candidate"]
    sea = [x for x in cls if x[2] in ("seasonal", "timing_reversal")]
    if not (stru or one or sea):
        return None
    reg, LP = Register(), f"lenses[{L['id']}]"
    gross = sum(abs(x[0]["movement"]) for x in cls) or 1.0
    share = r4(sum(abs(x[0]["movement"]) for x in stru) / gross)
    acts = {a["subject_ref"]: a for a in L.get("actions", [])}
    parts = []
    for d, la, _ in stru:
        t = _test(signals[la["id"]], "persistent_gap")
        s = f"{reg.lit(d['label'])} is recurring"
        if t and t["state"] == "fired":
            s += f" ({reg.lit(account_label(model, la['id']))} off budget in {t['evidence']['months_same_side']} of the last {t['evidence']['months_compared']} months)"
        a = acts.get(d["id"])
        fx = a["forecast"]["remaining_months_effect"] if a else None
        if is_num(fx) and fx < 0:
            src = LP + ".actions[" + a["id"] + "].forecast.remaining_months_effect"
            s += f" and would cost another {_amt(reg, fx, src)} by year end"
        parts.append(s)
    if one:
        parts.append(f"{join_and(reg.lit(x[0]['label']) for x in one)} {'look' if len(one) > 1 else 'looks'} one-off, outside {'their' if len(one) > 1 else 'its'} usual range for the first time")
    if sea:
        parts.append(f"{join_and(reg.lit(x[0]['label']) for x in sea)} {'follow' if len(sea) > 1 else 'follows'} last year's seasonal pattern")
    head = "Mostly temporary." if not stru else ("Mostly structural." if share >= 0.5 else "Partly structural.")
    mean = ("little of this month's movement should carry into the rest of the year" if not stru else
            f"about {reg.p(share, SP + '.evidence.structural_share', dec=0)} of the driver movement will repeat unless someone acts on it")
    text = "; ".join(parts)
    short = ("The movement looks temporary; little of it carries into the year." if not stru else
             "Most of the movement is structural and repeats unless someone acts." if share >= 0.5 else
             "Part of the movement is structural and repeats; the rest looks temporary.")
    return _bullet("persistence", "unf" if stru else "neu", head, text[0].upper() + text[1:] + f": {mean}.",
                   {"level": "driver", "ids": [x[0]["id"] for x in stru + one + sea]}, reg,
                   claim="structural" if stru else "temporary", evidence={"structural_share": share}, short=short)


def concentration(model, L, mon, SP):
    md = [d for d in _mat_drivers(L, mon) if d.get("share_scope", "ebitda") == "ebitda"]   # shares are of the Adjusted EBITDA bridge
    if not md:
        return None
    reg = Register()
    top = md[:3]
    sh = r4(sum(d["share_of_abs_variance"] or 0 for d in top))
    nv = _line(L, "ni")["variance"]
    drill = {"level": "driver", "ids": [d["id"] for d in top]}
    if sh < 0.5:
        return _bullet("concentration", "neu", "Broad-based.",
                       f"No small group of drivers explains the result (the top three carry {reg.p(sh, SP + '.evidence.top_share', dec=0)}): the Adjusted EBITDA movement is spread across the operating lines, "
                       "so a shared assumption, such as the budget itself, may sit behind it; to be confirmed with FP&A.", drill, reg, claim="broad_based", evidence={"top_share": sh},
                       short="No small group of drivers explains the result; the movement is broad-based.")
    who = "One owner" if len(top) == 1 else ("Two owners" if len(top) == 2 else "Three owners")
    neg = is_num(nv) and nv < 0
    return _bullet("concentration", "ink", "Concentrated, so fixable." if neg else "Gains come from a few lines.",
                   f"{join_and(reg.lit(d['label']) for d in top)} carry {reg.p(sh, SP + '.evidence.top_share', dec=0)} of the Adjusted EBITDA movement: "
                   + (f"{who.lower()} can close most of the gap, without a broad cost programme." if neg else f"{who.lower()} explain most of the beat, so confirm it repeats before relying on it."),
                   drill, reg, claim="concentrated", evidence={"top_share": sh},
                   short="A few drivers carry the gap, so the fix is targeted." if neg else "A few drivers carry the beat; confirm they repeat before relying on it.")


def margin(model, L, lenses):
    LP = f"lenses[{L['id']}]"
    ebm = _line(L, "ebm")
    v = ebm["variance"]
    if not is_num(v) or abs(v) < 0.005:
        return None
    reg = Register()
    M = lenses.get(f"MTD_{L['basis']}")
    mv = _line(M, "ebm")["variance"] if L["window"] != "MTD" and M and M.get("available") else None
    trend, lev = "", None
    lp = lenses.get("LTM_py")
    if L["id"] != "LTM_py" and lp and lp.get("available"):
        g = {x["id"]: x.get("variance_pct") for x in lp["lines"]}
        if all(is_num(g[k]) for k in ("rev", "cos", "opex")):
            lev = g["rev"] > max(-g["cos"], -g["opex"])
            gw = lambda k, cost: _growth(reg, g[k], f"lenses[LTM_py].lines[{k}].variance_pct", cost)
            trend = f"; over twelve months revenue {gw('rev', False)}, cost of sales {gw('cos', True)} and operating expenses {gw('opex', True)}"
    pats = {p["id"] for p in L.get("patterns", []) if p["fired"]}
    why = " as costs outran revenue" if "cost_growth_outpacing_revenue" in pats else " as revenue outgrew costs" if "operating_leverage" in pats else ""
    wl = L["window_label"]
    obs = (f"{wl[0].upper() + wl[1:]} EBITDA margin {'fell' if v < 0 else 'rose'} {reg.pt(v, LP + '.lines[ebm].variance')} to "
           f"{reg.p(ebm['actual'], LP + '.lines[ebm].actual')} against {L['basis_label']}{why}")
    if is_num(mv) and abs(mv) >= 0.005 and (mv > 0) != (v > 0):
        obs += f", but {M['range']['label']} alone {'fell' if mv < 0 else 'rose'} {reg.pt(mv, 'lenses[' + M['id'] + '].lines[ebm].variance')}"
        return _bullet("margin", "neu", "Margin mixed.", obs + trend + ": the window and the latest month point different ways, so read the month before calling a trend.",
                       {"level": "line", "ids": ["ebm"]}, reg, claim="margin_mixed", short="The window and the latest month point different ways on margin.")
    if v < 0:
        if lev and L["basis"] == "budget" and L["window"] != "MTD":
            head, mean = "Margin below plan, trend intact.", "the business is growing into its costs, but more slowly than the budget assumed, so the gap is in the plan level rather than a deterioration"
            short = "Margin is below plan, but the year's trend is intact."
        else:
            head = "A margin dip, not a trend." if lev else ("Margin under sustained pressure." if lev is False else "Margin compressed.")
            mean = ("operating leverage is intact over the year, so the month reads as a dip rather than a trend" if lev else
                    "costs are growing faster than revenue over the year, so the squeeze appears structural rather than a single month" if lev is False else "watch whether it repeats next month")
            short = ("Margin dipped this period; the year's operating leverage is intact." if lev else
                     "Margin is under sustained pressure as costs outgrow revenue." if lev is False else "Margin compressed this period; watch whether it repeats.")
        claim = "margin_down"
    else:
        head = "Margin up, against the trend." if lev is False else "Margin expanding."
        mean = "costs still grow faster than revenue over the year, so this gain may not hold" if lev is False else "growth is converting into profit"
        short = "Margin rose this period, against a year of costs outgrowing revenue." if lev is False else "Margin is expanding: growth is converting into profit."
        claim = "margin_up"
    return _bullet("margin", _tone(v), head, obs + trend + f": {mean}.", {"level": "line", "ids": ["ebm"]}, reg, claim=claim, short=short)


def mix(model, L, mon):
    LP = f"lenses[{L['id']}]"
    r = next((d for d in L["drivers"] if d["section"] == "rev" and d["label"].lower().startswith("recurring")), None)
    n = next((d for d in L["drivers"] if d["section"] == "rev" and d["label"].lower().startswith("non")), None)
    if not (r and n and is_num(r["movement"]) and is_num(n["movement"]) and abs(r["movement"]) >= mon and abs(n["movement"]) >= mon
            and (r["movement"] > 0) != (n["movement"] > 0)):
        return None
    reg = Register()
    rs, ns = f"{LP}.drivers[{r['id']}].movement", f"{LP}.drivers[{n['id']}].movement"
    drill = {"level": "driver", "ids": [r["id"], n["id"]]}
    if r["movement"] < 0:
        return _bullet("mix", "unf", "Lower-quality revenue.", f"{reg.lit(n['label'])} ({reg.m(n['movement'], ns, sign=True)}) offset {reg.lit(r['label'])} "
                       f"({reg.m(r['movement'], rs, sign=True)}): the top line holds, but less of it repeats next year.", drill, reg, claim="mix_down",
                       short="Non-recurring revenue offset recurring, so less of the top line repeats.")
    return _bullet("mix", "fav", "Better-quality revenue.", f"{reg.lit(r['label'])} grew ({reg.m(r['movement'], rs, sign=True)}) while {reg.lit(n['label'])} fell "
                   f"({reg.m(n['movement'], ns, sign=True)}): more of the revenue base now repeats.", drill, reg, claim="mix_up",
                   short="Recurring revenue grew while non-recurring fell: better-quality revenue.")


def budget_bias(model, L, signals, mon):
    if L["basis"] != "budget" or L["window"] != "MTD":
        return None
    hits = []
    for d in _mat_drivers(L, mon):
        la = _lead_account(L, d)
        if la and any(f in ("budget_outside_run_rate", "persistent_gap") for f in signals[la["id"]]["fired"]):
            hits.append(d)
    if not hits:
        return None
    reg = Register()
    return _bullet("budget_bias", "neu", "Part of the gap is the plan.",
                   f"The budget for {join_and(reg.lit(d['label']) for d in hits)} sits away from recent run-rate or has been missed on the same side for months: "
                   "re-basing the forecast matters as much as cost action.", {"level": "driver", "ids": [d["id"] for d in hits]}, reg, claim="budget_bias",
                   short="Part of the gap is the plan: the budget sits away from run-rate.")


def year(L, outlook, mon):
    if not outlook or outlook.get("state") != "calculated":
        return None
    fy, reg, O = outlook["lines"]["ebitda"], Register(), "outlook.lines.ebitda"
    text = f"Full-year EBITDA tracks about {reg.m(fy['mechanical']['value'], O + '.mechanical.value')} on run-rate"
    if L["basis"] == "budget" and is_num(fy.get("gap_vs_budget")):
        text += f", {_amt(reg, fy['gap_vs_budget'], O + '.gap_vs_budget')} {'short of' if fy['gap_vs_budget'] < 0 else 'above'} budget"
    elif is_num(fy.get("gap_vs_prior_year")):
        text += f", {_amt(reg, fy['gap_vs_prior_year'], O + '.gap_vs_prior_year')} {'above' if fy['gap_vs_prior_year'] > 0 else 'below'} last year"
        if fy["gap_vs_prior_year"] > 0:
            text += ", so the year is still one of growth"
    text += "."
    carry = (outlook.get("persistence_totals") or {}).get("proposed_carry")
    if L["basis"] == "budget" and is_num(carry) and abs(carry) >= mon:
        text += f" Correcting the recurring gaps protects about {_amt(reg, carry, 'outlook.persistence_totals.proposed_carry')} of that."
    gap = fy.get("gap_vs_budget") if L["basis"] == "budget" else fy.get("gap_vs_prior_year")
    against = "budget" if L["basis"] == "budget" else "last year"
    short = (f"Full-year EBITDA on run-rate lands {'ahead of' if gap > 0 else 'short of'} {against}." if is_num(gap) else "Full-year EBITDA on run-rate: a projection rule, not a forecast.")
    return _bullet("year", "ink", "What it means for the year.", text, {"level": "outlook", "ids": ["mechanical"]}, reg, claim="outlook", short=short)


WINDOW_WORDS = {"MTD": "the month", "QTD": "the quarter to date", "YTD": "the year to date", "LTM": "the last twelve months"}


def trend_windows(lenses, basis):
    """The windows a trend reads across, latest month first: the month, the quarter to date (only once the quarter holds
    more than one month, otherwise it repeats the month) and the year to date, on one basis."""
    out = []
    for w in ("MTD", "QTD", "YTD"):
        X = lenses.get(f"{w}_{basis}") or {}
        if X.get("available") and not (w == "QTD" and X.get("months") == 1):
            out.append(w)
    return out if "MTD" in out and len(out) > 1 else []


def trend_reading(month, longer, mon):
    """Whether the latest month continues the longer windows: continuing (same side, all material), reversal (the month
    is material and a longer window sits on the other side), new (the month is material, the longer windows are not),
    easing (the month is not material while a longer window is); None when nothing is material."""
    longer = [v for v in longer if is_num(v)]
    if not is_num(month) or not longer:
        return None
    if abs(month) < mon:
        return "easing" if any(abs(v) >= mon for v in longer) else None
    if any(abs(v) >= mon and (v > 0) != (month > 0) for v in longer):
        return "reversal"
    if all(abs(v) >= mon and (v > 0) == (month > 0) for v in longer):
        return "continuing"
    return "new"


TREND_TEXT = {
    "continuing": ("A continuing pattern.", "the month repeats the longer pattern, so it is a trend rather than a single month",
                   "The month continues the quarter and year-to-date pattern."),
    "reversal": ("A change of direction.", "the latest month points the other way from the longer windows, so confirm it holds before the outlook moves",
                 "The latest month points the other way from the year to date."),
    "new": ("A new development.", "the longer windows do not show it yet, so it is new this month and worth watching",
            "The longer windows do not show it yet; it is new this month."),
    "easing": ("Easing this month.", "the month is close to the comparison while the longer windows are not, so the variance did not build further this month",
               "The month is close to the comparison; the variance did not build further."),
}


def trend(model, L, lenses, mon):
    """Net income in the month against the quarter and year to date on the same basis, and whether the largest driver
    sits on the same side in every window: a continuing pattern, a change of direction, a new development or easing."""
    ws = trend_windows(lenses, L["basis"])
    if not ws:
        return None
    reg, basis = Register(), L["basis_label"]
    lid = lambda w: f"{w}_{L['basis']}"
    v = {w: _line(lenses[lid(w)], "ni")["variance"] for w in ws}
    reading = trend_reading(v["MTD"], [v[w] for w in ws[1:]], mon)
    if not reading:
        return None
    parts = []
    for w in ws:
        if is_num(v[w]):
            parts.append(f"{WINDOW_WORDS[w]} {_amt(reg, v[w], 'lenses[' + lid(w) + '].lines[ni].variance')} {'ahead' if v[w] > 0 else 'behind'}")
    obs = f"Net income against {basis}: " + join_and(parts)
    md = _mat_drivers(lenses[lid("MTD")], mon)
    d0 = md[0] if md else None
    dtxt = ""
    if d0 and reading != "easing":
        dv = [next((x["movement"] for x in lenses[lid(w)]["drivers"] if x["id"] == d0["id"]), None) for w in ws[1:]]
        same = all(is_num(x) and (x > 0) == (d0["movement"] > 0) for x in dv)
        dtxt = f"; {reg.lit(d0['label'])}, the month's largest driver, is on the {'same' if same else 'other'} side in the longer {'windows' if len(dv) > 1 else 'window'}"
    head, mean, short = TREND_TEXT[reading]
    return _bullet("trend", "neu", head, f"{obs}{dtxt}: {mean}.", {"level": "line", "ids": ["ni"]}, reg, claim=f"trend_{reading}", evidence={"reading": reading}, short=short)


def summary(model, L, lenses, outlook, signals):
    """The lead, the engine insights in priority order, and the full-year bullet; each carries its drill target."""
    mon = L["materiality"]["monitoring_abs"]
    SP = lambda i: f"lenses[{L['id']}].summary.insights[{i}]"
    ins = [b for b in (concentration(model, L, mon, SP("concentration")), trend(model, L, lenses, mon), persistence(model, L, signals, mon, SP("persistence")),
                       margin(model, L, lenses), mix(model, L, mon), budget_bias(model, L, signals, mon)) if b]
    return {"lead": lead(model, L, lenses, mon), "insights": ins, "year": year(L, outlook, mon)}
