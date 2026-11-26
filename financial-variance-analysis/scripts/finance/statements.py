"""Balance sheet and cash flow readouts (contract 1.1.0): per lens, a pinned
headline and a ranked list of data insights, built only from values the `bs`
and `cf` blocks already emitted. Every figure in the prose is registered with
its payload path so the validator can refuse an unregistered token.

An insight is evidence, never a cause: an observed fact (the movement), an
analytical inference (where it sits, which structural signals fired on the
largest account) and a question management must answer. The diagnosis gate
covers the income statement only, so these ship as the engine baseline.
"""
from .common import Register, is_num, r4, safe_div, lower_words

TIER_RANK = {"executive": 0, "management": 1, "monitoring": 2, "immaterial": 3}
STATUS_WORD = {"ahead": "favourable", "behind": "unfavourable", "in_line": "in line", "higher": "higher", "lower": "lower",
               "not_comparable": "not comparable", "reported": "reported"}
BS_OWNER = {"current_assets": "Controller / Treasury", "noncurrent_assets": "Controller", "current_liabilities": "Controller / AP lead",
            "longterm_liabilities": "Treasury", "equity": "Controller"}
CF_OWNER = {"operations": "FP&A with the Controller", "investing": "FP&A / capital committee", "financing": "Treasury", "fx": "Treasury"}
BS_LINE_WORD = {"current_assets": "current assets", "noncurrent_assets": "non-current assets", "current_liabilities": "current liabilities",
                "longterm_liabilities": "long-term liabilities", "equity": "equity"}
CF_LINE_WORD = {"operations": "cash from operations", "investing": "cash from investing", "financing": "cash from financing", "fx": "the FX effect"}


def _rec(L, lid):
    return next((x for x in L.get("lines", []) if x["id"] == lid), None)


BUDGET_ONLY_TESTS = {"unbudgeted_activity", "budgeted_no_activity", "budget_outside_run_rate", "budget_near_run_rate_edge"}


def _signal_text(sig, labels, basis="budget"):
    """Fired structural signals for prose; budget-only tests are dropped when the comparator is prior year."""
    fired = [t for t in (sig or {}).get("fired", []) if basis == "budget" or t not in BUDGET_ONLY_TESTS]
    return [labels.get(t, t) for t in fired][:3]


def _labels(signals):
    out = {}
    for s in (signals or {}).values():
        for t in s.get("tests", []):
            out[t["id"]] = t["label"]
    return out


# ------------------------------------------------------------------ balance sheet

def _bs_value_key(L):
    return ("balance_variance", "balance", "comparator") if L["window"] == "MTD" else ("movement_variance", "movement", "comparator_movement")


def bs_readout(bs, payload_accounts=None):
    """Adds `headline` and `insights` to every available BS lens."""
    if not bs.get("available"):
        return
    names = {a["id"]: a["name"] for a in bs["accounts"]}
    labels = _labels(bs.get("signals"))
    mat = bs["materiality"]
    for key, L in bs["lenses"].items():
        if not L.get("available"):
            continue
        vk, ak, ck = _bs_value_key(L)
        base = f"bs.lenses[{key}]"
        ap = lambda a: f"{base}.accounts[{a['id']}]"
        lp = lambda r: f"{base}.lines[{r['id']}]"
        gp = lambda g: f"{base}.groups[{g['id']}]"
        # headline
        reg = Register()
        parts = []
        for lid, word in (("cash", "Cash"), ("working_capital", "Working capital"), ("net_debt", "Net debt")):
            r = _rec(L, lid)
            if r and is_num(r.get("balance")):
                tail = (f" ({reg.m(r['variance'], f'{base}.lines[{lid}].variance', sign=True)} vs {L['basis_label']}, {STATUS_WORD.get(r['status'], r['status'])})"
                        if is_num(r.get("variance")) else "")
                parts.append(f"{word} {reg.m(r['balance'], f'{base}.lines[{lid}].balance')}{tail}")
        ta = _rec(L, "assets")
        # one short sentence per point: the page shows each sentence as a bullet
        text = " ".join(x + "." for x in parts) if parts else f"Balance sheet for {L['range']['label']}."
        if ta and is_num(ta.get("balance")):
            text += f" Total assets {reg.m(ta['balance'], f'{base}.lines[assets].balance')}."
        mat_groups = [g for g in L["groups"] if g["tier"] in ("executive", "management")]
        text += (f" {len(mat_groups)} balance-sheet group(s) past the management threshold." if mat_groups
                 else " No balance-sheet group past the management threshold.")
        L["headline"] = {"text": text, "numbers": reg.numbers}
        # insights
        ins = []
        for lid, label, q in (("cash", "Cash & equivalents", "What moved cash against {b}, and is the level enough for the next quarter's commitments?"),
                              ("working_capital", "Working capital", "Is the working-capital movement timing (collections, payment runs) or a change in terms?"),
                              ("net_debt", "Net debt", "Did borrowings or cash drive net debt, and is it inside the covenant headroom?")):
            r = _rec(L, lid)
            if not r or not is_num(r.get("variance")) or abs(r["variance"]) < mat["monitoring_abs"]:
                continue
            reg = Register()
            p = f"{base}.lines[{lid}]"
            if L["window"] == "MTD":
                fact = (f"{label} ends at {reg.m(r['balance'], p + '.balance')} against {reg.m(r['comparator'], p + '.comparator')} {L['basis_label']}: "
                        f"{reg.m(r['variance'], p + '.variance', sign=True)}, {STATUS_WORD.get(r['status'])}.")
            else:
                fact = (f"{label} moved {reg.m(r['movement'], p + '.movement', sign=True)} over the window against a {L['basis_label']} movement of "
                        f"{reg.m(r['comparator_movement'], p + '.comparator_movement', sign=True)}: {reg.m(r['variance'], p + '.variance', sign=True)}, {STATUS_WORD.get(r['status'])}.")
            members = bs["derived_members"].get(lid) or []
            if lid == "working_capital":
                ca, cl = _rec(L, "current_assets"), _rec(L, "current_liabilities")
                infer = (f"Current assets contribute {reg.m(ca['variance'], f'{base}.lines[current_assets].variance', sign=True)} and current liabilities "
                         f"{reg.m(cl['variance'], f'{base}.lines[current_liabilities].variance', sign=True)} (a rise in liabilities lowers working capital)."
                         if ca and cl and is_num(ca.get("variance")) and is_num(cl.get("variance")) else None)
                accts = [a for a in L["accounts"] if a["line"] in ("current_assets", "current_liabilities")]
            else:
                accts = [a for a in L["accounts"] if a["id"] in members]
                infer = None
            accts = sorted([a for a in accts if is_num(a.get("variance"))], key=lambda a: -abs(a["variance"]))[:5]
            if accts and not infer:
                infer = "Largest accounts: " + "; ".join(f"{reg.lit(names.get(a['id'], a['id']))} {reg.m(a['variance'], ap(a) + '.variance', sign=True)}" for a in accts[:3]) + "."
            sts = [{"state": "observed_fact", "text": fact}]
            if infer:
                sts.append({"state": "analytical_inference", "text": infer})
            sts.append({"state": "management_input_required", "text": "The balance sheet shows the level and its movement; it does not show the transactions behind it. Confirm with the suggested owner."})
            ins.append({"id": f"bs:{lid}", "kind": "kpi", "subject_ref": lid, "label": label, "tier": r["tier"] if "tier" in r else None,
                        "amount": r["variance"], "status": r["status"], "statements": sts, "numbers": reg.numbers,
                        "accounts": [a["id"] for a in accts], "question": q.format(b=L["basis_label"]),
                        "owner": "Treasury" if lid != "working_capital" else "Controller / Treasury"})
        for g in sorted([g for g in L["groups"] if is_num(g.get("variance")) and g["tier"] in ("executive", "management")],
                        key=lambda g: (TIER_RANK[g["tier"]], -abs(g["variance"])))[:8]:
            reg = Register()
            p = f"{base}.groups[{g['id']}]"
            word = BS_LINE_WORD.get(g["line"], g["line"])
            if L["window"] == "MTD":
                fact = (f"{reg.lit(g['label'])} ({word}) ends at {reg.m(g['balance'], p + '.balance')} against {reg.m(g['comparator'], p + '.comparator')} "
                        f"{L['basis_label']}: {reg.m(g['variance'], p + '.variance', sign=True)}, {STATUS_WORD.get(g['status'])}; {g['tier']} tier.")
            else:
                fact = (f"{reg.lit(g['label'])} ({word}) moved {reg.m(g['movement'], p + '.movement', sign=True)} against a {L['basis_label']} movement of "
                        f"{reg.m(g['comparator_movement'], p + '.comparator_movement', sign=True)}: {reg.m(g['variance'], p + '.variance', sign=True)}; {g['tier']} tier.")
            accts = sorted([a for a in L["accounts"] if a["group_ref"] == g["id"] and is_num(a.get("variance"))], key=lambda a: -abs(a["variance"]))
            sts = [{"state": "observed_fact", "text": fact}]
            if accts:
                top = accts[0]
                share = r4(safe_div(abs(top["variance"]), sum(abs(a["variance"]) for a in accts)))
                txt = (f"{reg.lit(names.get(top['id'], top['id']))} carries {reg.m(top['variance'], ap(top) + '.variance', sign=True)} "
                       f"of the group's {len(accts)} account(s) with a variance")
                fired = _signal_text(bs["signals"].get(top["id"]), labels, L["basis"])
                txt += ("; signals on it: " + ", ".join(lower_words(f) for f in fired) + "." if fired else "; no structural signal fired on it.")
                sts.append({"state": "analytical_inference", "text": txt})
            sts.append({"state": "management_input_required",
                        "text": "Whether this is timing, a reclassification or a change in level needs the postings behind the balance; confirm with the suggested owner."})
            ins.append({"id": f"bs:{g['id']}", "kind": "group", "subject_ref": g["id"], "label": g["label"], "tier": g["tier"],
                        "amount": g["variance"], "status": g["status"], "statements": sts, "numbers": reg.numbers,
                        "accounts": [a["id"] for a in accts[:8]], "question": f"What moved {g['label']} in {L['range']['label']}, and does the level hold at the next close?",
                        "owner": BS_OWNER.get(g["line"], "Controller")})
        idn = L.get("identity") or {}
        if idn and not idn.get("balances") and is_num(idn.get("gap")):
            reg = Register()
            ins.append({"id": "bs:identity", "kind": "data_quality", "subject_ref": "identity", "label": "Balance sheet does not foot on the extracted accounts",
                        "tier": "monitoring", "amount": idn["gap"], "status": "not_comparable",
                        "statements": [{"state": "observed_fact", "text": f"Assets less liabilities and equity leave a gap of {reg.m(idn['gap'], f'{base}.identity.gap', sign=True)} at the as-of month."},
                                       {"state": "analytical_inference", "text": idn["note"]}],
                        "numbers": reg.numbers, "accounts": [], "question": "Which accounts outside the extract close the gap?", "owner": "Controller"})
        for n_, x in enumerate(sorted(ins, key=lambda x: (x["kind"] == "data_quality", TIER_RANK.get(x["tier"] or "monitoring", 2), -abs(x["amount"] or 0))), start=1):
            x["rank"] = n_
        L["insights"] = sorted(ins, key=lambda x: x["rank"])


# --------------------------------------------------------------------- cash flow

def add_cash_conversion(cf, is_lenses):
    """CFO / Adjusted EBITDA per lens, beside the CF lines (both values are engine-emitted)."""
    if not cf.get("available"):
        return
    for key, L in cf["lenses"].items():
        IL = is_lenses.get(key) or {}
        if not L.get("available") or not IL.get("available"):
            continue
        cfo = _rec(L, "operations")
        eb = next((x for x in IL["lines"] if x["id"] == "ebitda"), None)
        if not cfo or not eb:
            continue
        a = safe_div(cfo["actual"], eb["actual"]) if is_num(eb.get("actual")) and eb["actual"] > 0 else None
        c = safe_div(cfo["comparator"], eb["comparator"]) if is_num(eb.get("comparator")) and eb["comparator"] > 0 else None
        v = (a - c) if is_num(a) and is_num(c) else None
        L["lines"].append({"id": "cash_conversion", "label": "Cash conversion (CFO ÷ Adjusted EBITDA)", "kind": "ratio", "derived": True,
                           "actual": r4(a), "comparator": r4(c), "variance": r4(v), "ebitda_actual": eb["actual"], "ebitda_comparator": eb["comparator"],
                           "status": "not_comparable" if v is None else ("in_line" if abs(v) < 0.02 else "ahead" if v > 0 else "behind"),
                           "tier": "monitoring" if v is not None and abs(v) >= 0.05 else "immaterial"})


def cf_readout(cf, materiality):
    if not cf.get("available"):
        return
    names = {a["id"]: a["name"] for a in cf["accounts"]}
    labels = _labels(cf.get("signals"))
    mon = materiality["monitoring_abs"]
    for key, L in cf["lenses"].items():
        if not L.get("available"):
            continue
        base = f"cf.lenses[{key}]"
        ap = lambda a: f"{base}.accounts[{a['id']}]"
        lp = lambda r: f"{base}.lines[{r['id']}]"
        gp = lambda g: f"{base}.groups[{g['id']}]"
        reg = Register()
        cfo, fcf, net = _rec(L, "operations"), _rec(L, "fcf"), _rec(L, "net")
        parts = []
        for r, word in ((cfo, "Cash from operations"), (fcf, "Free cash flow"), (net, "Net cash flow")):
            if r and is_num(r.get("actual")):
                tail = (f" ({reg.m(r['variance'], lp(r) + '.variance', sign=True)} vs {L['basis_label']})" if is_num(r.get("variance")) else "")
                parts.append(f"{word} {reg.m(r['actual'], lp(r) + '.actual')}{tail}")
        # one short sentence per point: the page shows each sentence as a bullet
        text = " ".join(x + "." for x in parts) if parts else f"Cash flow for {L['range']['label']}."
        w = L.get("walk") or {}
        if is_num(w.get("beginning")) and is_num(w.get("ending")):
            text += (f" Cash {reg.m(w['beginning'], f'{base}.walk.beginning')} → {reg.m(w['ending'], f'{base}.walk.ending')}"
                     + (", walk reconciles." if w.get("reconciles") else f", unreconciled gap {reg.m(w['gap'], f'{base}.walk.gap', sign=True)}."))
        cc = _rec(L, "cash_conversion")
        if cc and is_num(cc.get("actual")):
            text += f" Cash conversion {reg.p(cc['actual'], f'{base}.lines[cash_conversion].actual', dec=0)} of Adjusted EBITDA."
        L["headline"] = {"text": text, "numbers": reg.numbers}
        ins = []
        for lid, q in (("operations", "Is the operating-cash gap earnings, working capital or timing, and does it reverse next month?"),
                       ("capex", "Is capital spend phased differently from plan, or has the programme changed?"),
                       ("fcf", "Does free cash flow cover debt service and planned investment at this run-rate?"),
                       ("financing", "Which borrowing, repayment or equity movement drove financing cash, and was it planned?")):
            r = _rec(L, lid)
            if not r or not is_num(r.get("variance")) or abs(r["variance"]) < mon:
                continue
            reg = Register()
            p = f"{base}.lines[{lid}]"
            sts = [{"state": "observed_fact", "text": f"{r['label']} is {reg.m(r['actual'], p + '.actual')} against {reg.m(r['comparator'], p + '.comparator')} {L['basis_label']}: "
                                                       f"{reg.m(r['variance'], p + '.variance', sign=True)}, {'more' if r['variance'] > 0 else 'less'} cash than the comparator; {r['tier']} tier."}]
            if lid == "fcf":
                cx = _rec(L, "capex")
                if cfo and cx and is_num(cfo.get("variance")) and is_num(cx.get("variance")):
                    sts.append({"state": "analytical_inference", "text": f"Operations contribute {reg.m(cfo['variance'], f'{base}.lines[operations].variance', sign=True)} and capital expenditure "
                                                                       f"{reg.m(cx['variance'], f'{base}.lines[capex].variance', sign=True)} to the gap."})
                accts = []
            else:
                gl = sorted([g for g in L["groups"] if (g["line"] == lid or (lid == "capex" and "capital expenditure" in g["label"].lower())) and is_num(g.get("variance"))],
                            key=lambda g: -abs(g["variance"]))[:3]
                if gl:
                    sts.append({"state": "analytical_inference", "text": "Largest groups: " + "; ".join(
                        f"{reg.lit(g['label'])} {reg.m(g['variance'], gp(g) + '.variance', sign=True)}" for g in gl) + "."})
                gids = {g["id"] for g in gl}
                accts = sorted([a for a in L["accounts"] if a["group_ref"] in gids and is_num(a.get("variance"))], key=lambda a: -abs(a["variance"]))[:8]
            sts.append({"state": "management_input_required", "text": "The cash-flow mart shows the flow by line; the receipts and payments behind it need the owner's review."})
            ins.append({"id": f"cf:{lid}", "kind": "kpi", "subject_ref": lid, "label": r["label"], "tier": r["tier"], "amount": r["variance"], "status": r["status"],
                        "statements": sts, "numbers": reg.numbers, "accounts": [a["id"] for a in accts], "question": q,
                        "owner": CF_OWNER.get(lid, "FP&A")})
        for g in sorted([g for g in L["groups"] if is_num(g.get("variance")) and g["tier"] in ("executive", "management")],
                        key=lambda g: (TIER_RANK[g["tier"]], -abs(g["variance"])))[:8]:
            reg = Register()
            p = f"{base}.groups[{g['id']}]"
            accts = sorted([a for a in L["accounts"] if a["group_ref"] == g["id"] and is_num(a.get("variance"))], key=lambda a: -abs(a["variance"]))
            sts = [{"state": "observed_fact", "text": f"{reg.lit(g['label'])} ({CF_LINE_WORD.get(g['line'], g['line'])}) is {reg.m(g['actual'], p + '.actual')} against "
                                                       f"{reg.m(g['comparator'], p + '.comparator')} {L['basis_label']}: {reg.m(g['variance'], p + '.variance', sign=True)}; {g['tier']} tier."}]
            if accts:
                top = accts[0]
                fired = _signal_text(cf["signals"].get(top["id"]), labels, L["basis"])
                sts.append({"state": "analytical_inference", "text": f"{reg.lit(names.get(top['id'], top['id']))} carries {reg.m(top['variance'], ap(top) + '.variance', sign=True)} "
                                                                   f"of the group's {len(accts)} account(s) with a variance"
                                                                   + ("; signals on it: " + ", ".join(lower_words(f) for f in fired) + "." if fired else "; no structural signal fired on it.")})
            sts.append({"state": "management_input_required", "text": "Whether the flow is timing or a new level needs the postings behind it; confirm with the suggested owner."})
            ins.append({"id": f"cf:{g['id']}", "kind": "group", "subject_ref": g["id"], "label": g["label"], "tier": g["tier"], "amount": g["variance"], "status": g["status"],
                        "statements": sts, "numbers": reg.numbers, "accounts": [a["id"] for a in accts[:8]],
                        "question": f"What moved {g['label']} in {L['range']['label']}, and does it repeat?", "owner": CF_OWNER.get(g["line"], "FP&A")})
        if w and w.get("gap") is not None and not w.get("reconciles"):
            reg = Register()
            ins.append({"id": "cf:walk", "kind": "data_quality", "subject_ref": "walk", "label": "Cash walk does not reconcile", "tier": "monitoring", "amount": w["gap"],
                        "status": "not_comparable", "statements": [{"state": "observed_fact", "text": f"Beginning cash plus the section flows misses ending cash by {reg.m(w['gap'], f'{base}.walk.gap', sign=True)}."}],
                        "numbers": reg.numbers, "accounts": [], "question": "Which flows are outside the extract?", "owner": "Controller"})
        for n_, x in enumerate(sorted(ins, key=lambda x: (x["kind"] == "data_quality", TIER_RANK.get(x["tier"] or "monitoring", 2), -abs(x["amount"] or 0))), start=1):
            x["rank"] = n_
        L["insights"] = sorted(ins, key=lambda x: x["rank"])
