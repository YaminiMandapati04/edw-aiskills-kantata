"""Cash flow block (payload key `cf`, contract 1.1.0).

Monthly flows as the mart stores them (inflows positive, outflows negative), so
a positive variance is always more cash than the comparator and reads as
favourable. QTD / YTD / LTM are sums of months, like the income statement.
Hierarchy: CASH_FLOW_L1 (Operations / Investing / Financing / FX) › L2 › L3;
the beginning / net / ending cash roll-ups (-10 / -12 / -11) feed the cash walk
and are never mixed into the L1 sums. The diagnosis gate does not cover this
block; it ships with the deterministic engine baseline only.
"""
import datetime as dt

from .common import natural_id, BuildError, Register, is_num, r2, r4, safe_div, slug, to_date, to_num, add
from .model import window_range, win_sum, BASIS_LABEL, WINDOW_LABEL
from .signals import signals_for

NEEDED = ["PERIOD_START_DATE", "CHART_OF_ACCOUNT_KEY", "ACCOUNT_NAME", "CASH_FLOW_L1"]
ACTUAL_COLS = ["TOTAL_MTD", "MTD"]
PY_COLS = ["TOTAL_PY_MTD", "PY_MTD"]
BUDGET_COLS = ["TOTAL_BUDGET_MTD", "BUDGET_MTD"]
L1_ORDER = ["operations", "investing", "financing", "fx"]
L1_LABEL = {"operations": "Cash from Operations", "investing": "Cash from Investing",
            "financing": "Cash from Financing", "fx": "FX Change"}
WALK_KEYS = {"beginning cash": "-10", "ending cash": "-11", "net cash flow": "-12"}


def _norm(s):
    return str(s or "").strip().lower()


def _l1_bucket(l1):
    n = _norm(l1)
    if "operation" in n:
        return "operations"
    if "investing" in n:
        return "investing"
    if "financing" in n:
        return "financing"
    if "fx" in n or "exchange" in n:
        return "fx"
    return None            # beginning/ending/net cash labels or unknown


def _pick(row0, cols, what):
    for c in cols:
        if c in row0:
            return c
    raise BuildError(f"Cash flow rows carry no {what} column (looked for {', '.join(cols)}). Run the CF query in references/dashboards.md.")


def cf_rows_from_workbook(path):
    """Local test mode: join the workbook's CASH_FLOW sheet into flat rows (roll-ups included)."""
    from .load import _sheet
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    if "CASH_FLOW" not in wb.sheetnames:
        return []
    acct = {str(a["CHART_OF_ACCOUNT_KEY"]): a for a in _sheet(wb, "ACCOUNT")}
    per = {p["ACCOUNTING_PERIOD_KEY"]: p for p in _sheet(wb, "PERIOD")}
    sub = {s["SUBSIDIARY_KEY"]: s["SUBSIDIARY_NAME"] for s in _sheet(wb, "SUBSIDIARY")}
    out = []
    for r in _sheet(wb, "CASH_FLOW"):
        a, p = acct.get(str(r["CHART_OF_ACCOUNT_KEY"])), per[r["ACCOUNTING_PERIOD_KEY"]]
        if a is None or not a.get("CASH_FLOW_L1"):
            continue
        out.append({"PERIOD_START_DATE": p["PERIOD_START_DATE"], "SUBSIDIARY_NAME": sub[r["SUBSIDIARY_KEY"]],
                    "CHART_OF_ACCOUNT_KEY": a["CHART_OF_ACCOUNT_KEY"], "ACCOUNT_NAME": a["ACCOUNT_NAME"],
                    "CASH_FLOW_L1": a.get("CASH_FLOW_L1"), "CASH_FLOW_L2": a.get("CASH_FLOW_L2"), "CASH_FLOW_L3": a.get("CASH_FLOW_L3"),
                    "MTD": r.get("MTD"), "PY_MTD": r.get("PY_MTD"), "BUDGET_MTD": r.get("BUDGET_MTD")})
    return out


def _series_env(rows, periods, subsidiary):
    row0 = rows[0]
    missing = [c for c in NEEDED if c not in row0]
    if missing:
        raise BuildError("Cash flow rows missing column(s): " + ", ".join(missing) + ". Run the CF query in references/dashboards.md.")
    a_col = _pick(row0, ACTUAL_COLS, "monthly flow")
    p_col = next((c for c in PY_COLS if c in row0), None)
    b_col = next((c for c in BUDGET_COLS if c in row0), None)
    if subsidiary:
        rows = [r for r in rows if _norm(r.get("SUBSIDIARY_NAME")) == _norm(subsidiary)]
    if not rows:
        raise BuildError("No cash-flow rows after filtering.")
    pidx = {dt.date.fromisoformat(p["start"]): p["idx"] for p in periods}
    np_ = len(periods)
    accounts, aidx, series, outside = [], {}, {}, 0
    keys_seen = set()
    for r in rows:
        raw_key = str(r["CHART_OF_ACCOUNT_KEY"]).strip()
        k = natural_id(raw_key, r["ACCOUNT_NAME"], r.get("CASH_FLOW_L1"), r.get("CASH_FLOW_L2"), r.get("CASH_FLOW_L3"))
        keys_seen.add(raw_key)
        d = to_date(r["PERIOD_START_DATE"]).replace(day=1)
        if d not in pidx:
            outside += 1
            continue
        if k not in aidx:
            aidx[k] = len(accounts)
            accounts.append({"id": k, "name": str(r["ACCOUNT_NAME"]), "l1": (r.get("CASH_FLOW_L1") or None),
                             "l2": (r.get("CASH_FLOW_L2") or None), "l3": (r.get("CASH_FLOW_L3") or None)})
            series[k] = {b: [None] * np_ for b in ("actual", "py", "budget")}
        i = pidx[d]
        s = series[k]
        s["actual"][i] = add(s["actual"][i], to_num(r.get(a_col)))
        s["py"][i] = add(s["py"][i], to_num(r.get(p_col))) if p_col else s["py"][i]
        s["budget"][i] = add(s["budget"][i], to_num(r.get(b_col))) if b_col else s["budget"][i]
    walk_ids = {"beginning": None, "ending": None, "net": None}
    for a in accounts:
        n = _norm(a["l1"])
        if n == "beginning cash":
            walk_ids["beginning"] = a["id"]
        elif n == "ending cash":
            walk_ids["ending"] = a["id"]
        elif n == "net cash flow":
            walk_ids["net"] = a["id"]
    real = [a for a in accounts if not a["id"].startswith("-") and _l1_bucket(a["l1"])]
    dropped = [a for a in accounts if not a["id"].startswith("-") and not _l1_bucket(a["l1"])]
    # component roll-ups: marts carry parts of the statement only as roll-up keys —
    # the indirect-method Net Income start of Operations, the FX effect on cash.
    # They join their section as flagged members. Subtotal roll-ups ("Cash before
    # Financing") duplicate other rows and are skipped, as are the walk anchors.
    anchors = {v for v in walk_ids.values() if v}
    extras = []
    for a in accounts:
        if not a["id"].startswith("-") or a["id"] in anchors:
            continue
        n = _norm(a["l1"])
        if "before" in n or "after" in n or not _l1_bucket(a["l1"]):
            continue
        a["name"] = a["name"].strip() or (a.get("l3") or a.get("l2") or a["l1"])
        a["rollup"] = True
        extras.append(a)
    n_keys = sum(1 for k in keys_seen if not k.startswith("-"))
    return real, dropped, extras, walk_ids, series, b_col is not None, p_col is not None, outside, n_keys


def _sum(series_list, np_):
    out = {b: [None] * np_ for b in ("actual", "py", "budget")}
    for s in series_list:
        for b in ("actual", "py", "budget"):
            for i in range(np_):
                out[b][i] = add(out[b][i], s[b][i])
    return out


def build(rows, periods, as_of, materiality, subsidiary=None, expect_accounts=None):
    """Build the `cf` payload block. `materiality` is the IS materiality dict (flows share its scale)."""
    if not rows:
        return {"available": False, "reason": "No cash-flow rows supplied (--cf-rows / CASH_FLOW sheet)."}
    real, dropped, extras, walk_ids, series, has_budget, has_py, outside, n_keys = _series_env(rows, periods, subsidiary)
    if expect_accounts is not None and n_keys != expect_accounts:
        raise BuildError(f"The CF data has {n_keys} real account key(s) but the probe counted {expect_accounts}. "
                         "The result was probably cut off: re-run the query in smaller period chunks.")
    if not real:
        return {"available": False, "reason": "No real cash-flow account maps to a CASH_FLOW_L1 section."}
    np_ = len(periods)
    # a budget that touches no real account — only roll-up key(s) such as the
    # indirect-method Net Income line, which may follow a different sign convention —
    # cannot carry a section-level comparison: vs-budget lenses are then unavailable
    # with the reason, never a misleading variance
    budget_reason = None
    if has_budget:
        bud_real = sum(1 for a in real if any(is_num(v) for v in series[a["id"]]["budget"]))
        if bud_real == 0:
            has_budget = False
            budget_reason = ("TOTAL_BUDGET_MTD carries no value on any real CF account (it sits only on roll-up key(s)), "
                             "so section-level vs-budget comparisons are not comparable.")
    members = real + extras
    for a in members:
        a["l1_bucket"] = _l1_bucket(a["l1"])
    # ---- groups: L2 inside an L1 section
    groups, group_of = [], {}
    for l1b in L1_ORDER:
        byl2 = {}
        for a in members:
            if a["l1_bucket"] != l1b:
                continue
            key = (a["l2"] or a["name"]).strip()
            gid = f"g:cf:{l1b}:{slug(key)}"
            g = byl2.setdefault(gid, {"id": gid, "label": key, "line": l1b, "accounts": []})
            g["accounts"].append(a["id"])
            group_of[a["id"]] = gid
        groups.extend(sorted(byl2.values(), key=lambda g: g["label"].lower()))
    # ---- line series
    ls = {l1b: _sum([series[a["id"]] for a in members if a["l1_bucket"] == l1b], np_) for l1b in L1_ORDER}
    for g in groups:
        ls[g["id"]] = _sum([series[x] for x in g["accounts"]], np_)
    ls["net"] = _sum([ls[b] for b in L1_ORDER], np_)
    capex = _sum([series[a["id"]] for a in real if "capital expenditure" in _norm(a["l2"])], np_)
    ls["capex"] = capex
    ls["fcf"] = _sum([ls["operations"], capex], np_)        # CapEx is stored negative, so this is CFO − CapEx spend
    mon = materiality["monitoring_abs"]

    def tier(v):
        if not is_num(v):
            return "immaterial"
        a = abs(v)
        return ("executive" if a >= materiality["executive_abs"] else "management" if a >= materiality["management_abs"]
                else "monitoring" if a >= mon else "immaterial")

    def status(v):
        if not is_num(v):
            return "not_comparable"
        return "in_line" if abs(v) < mon else ("ahead" if v > 0 else "behind")

    LINES = [("operations", "Cash from Operations"), ("investing", "Cash from Investing"), ("financing", "Cash from Financing"),
             ("fx", "FX Change"), ("net", "Net Cash Flow"), ("capex", "Capital expenditures"), ("fcf", "Free cash flow (CFO − CapEx)")]
    lenses = {}
    for w in ("MTD", "QTD", "YTD", "LTM"):
        for basis in ("budget", "py"):
            key = f"{w}_{basis}"
            rng = window_range(periods, as_of, w)
            avail = rng is not None and (basis != "budget" or has_budget) and (basis != "py" or has_py)
            L = {"id": key, "window": w, "basis": basis, "basis_label": BASIS_LABEL[basis], "window_label": WINDOW_LABEL[w], "available": avail}
            if rng is None:
                L["reason"] = "LTM needs twelve months of history up to the as-of period."
            elif not avail:
                L["reason"] = (budget_reason if basis == "budget" and budget_reason
                               else f"The CF extract carries no {BASIS_LABEL[basis]} column.")
            if not avail:
                lenses[key] = L
                continue
            L["range"] = {"start_idx": rng[0], "end_idx": rng[1], "start": periods[rng[0]]["start"], "end": periods[rng[1]]["end"],
                          "label": f"{w} to {periods[rng[1]]['label']}" if w != "MTD" else periods[rng[1]]["label"]}

            def vals(s):
                a, na = win_sum(s["actual"], rng)
                c, nc = win_sum(s[basis], rng)
                v = (a - c) if is_num(a) and is_num(c) else None
                return {"actual": r2(a), "comparator": r2(c), "variance": r2(v),
                        "variance_pct": r4(safe_div(v, abs(c)) if is_num(c) and c != 0 else None) if v is not None else None,
                        "months_with_actual": na, "months_with_comparator": nc,
                        "status": status(v), "tier": tier(v)}

            L["lines"] = []
            for lid, label in LINES:
                rec = vals(ls[lid])
                rec.update({"id": lid, "label": label, "derived": lid in ("capex", "fcf")})
                L["lines"].append(rec)
            L["groups"] = []
            for g in groups:
                rec = vals(ls[g["id"]])
                rec.update({"id": g["id"], "label": g["label"], "line": g["line"], "accounts": list(g["accounts"])})
                L["groups"].append(rec)
            L["accounts"] = []
            for a in members:
                rec = vals(series[a["id"]])
                rec.update({"id": a["id"], "line": a["l1_bucket"], "group_ref": group_of[a["id"]]})
                if a.get("rollup"):
                    rec["rollup"] = True
                L["accounts"].append(rec)
            ranked = sorted([x for x in L["accounts"] if is_num(x["variance"])], key=lambda x: -abs(x["variance"]))
            tot = sum(abs(x["variance"]) for x in ranked)
            for r_, x in enumerate(ranked, start=1):
                x["rank"] = r_
                x["share_of_abs_variance"] = r4(safe_div(abs(x["variance"]), tot)) if tot else None
            # cash walk over the window: beginning at window start, sections, ending at as-of
            beg = series[walk_ids["beginning"]]["actual"][rng[0]] if walk_ids["beginning"] else None
            end = series[walk_ids["ending"]]["actual"][rng[1]] if walk_ids["ending"] else None
            net_roll, _n = win_sum(series[walk_ids["net"]]["actual"], rng) if walk_ids["net"] else (None, 0)
            net_calc, _ = win_sum(ls["net"]["actual"], rng)
            # the walk uses the section sum (incl. FX); the mart's Net Cash Flow
            # roll-up excludes the FX effect and is kept beside it as net_rollup
            net = net_calc if is_num(net_calc) else net_roll
            gap = (beg + (net or 0.0) - end) if is_num(beg) and is_num(end) else None
            L["walk"] = {"beginning": r2(beg), "ending": r2(end), "net": r2(net), "net_rollup": r2(net_roll),
                         "net_from_sections": r2(net_calc), "gap": r2(gap),
                         "reconciles": gap is not None and abs(gap) <= max(0.05, abs(end or 0) * 1e-6),
                         "steps": [{"id": lid, "label": L1_LABEL[lid], "value": next(x for x in L["lines"] if x["id"] == lid)["actual"],
                                    "kind": "fav" if (next(x for x in L["lines"] if x["id"] == lid)["actual"] or 0) >= 0 else "unf"}
                                   for lid in L1_ORDER if is_num(next(x for x in L["lines"] if x["id"] == lid)["actual"])]}
            lenses[key] = L
    signals = {a["id"]: signals_for(series[a["id"]], as_of, mon, periods) for a in members}
    explanations = _explanations(lenses, {a["id"]: a for a in members})
    qc_notes = []
    if extras:
        qc_notes.append("Component roll-up(s) included in their section (the mart carries them only as roll-up keys): "
                        + "; ".join(f"{a['name']} ({a['id']}, {L1_LABEL[a['l1_bucket']]})" for a in extras)
                        + ". The mart's Net Cash Flow roll-up excludes the FX effect; the walk's net is the section sum including FX, with the roll-up kept beside it as net_rollup.")
    if not has_budget:
        qc_notes.append(budget_reason or "No budget column in the CF extract; budget lenses are unavailable.")
    else:
        nb = sum(1 for a in real if is_num(series[a["id"]]["budget"][as_of]))
        if nb < len(real):
            qc_notes.append(f"CF budget covers {nb} of {len(real)} accounts at the as-of month; uncovered accounts carry no variance and are never zero-filled.")
    if outside:
        qc_notes.append(f"{outside} CF row(s) fell outside the income-statement period axis and were ignored.")
    if dropped:
        qc_notes.append(f"{len(dropped)} CF account(s) have no recognised CASH_FLOW_L1 section and are left out: " + ", ".join(a["name"] for a in dropped[:6]))
    if not all(walk_ids.values()):
        qc_notes.append("Beginning/ending/net cash roll-ups (-10/-11/-12) are not all in the extract; the cash walk anchors are partial.")
    return {"available": True, "account_keys": n_keys,
            "accounts": [{**a, "series": {b: [r2(v) for v in series[a['id']][b]] for b in ("actual", "py", "budget")}} for a in members],
            "walk_series": {k: ({b: [r2(v) for v in series[v_id][b]] for b in ("actual", "py", "budget")} if v_id else None)
                            for k, v_id in walk_ids.items()},
            "line_series": {k: {b: [r2(v) for v in ls[k][b]] for b in ("actual", "py", "budget")}
                            for k in L1_ORDER + ["net", "capex", "fcf"]},
            "groups": groups, "group_of": group_of, "lenses": lenses, "signals": signals,
            "derived_members": {"capex": [a["id"] for a in real if "capital expenditure" in _norm(a["l2"])]},
            "explanations": explanations, "qc_notes": qc_notes,
            "semantics_note": "Flows as stored: inflows positive, outflows negative; a positive variance is always more cash than the comparator. QTD/YTD/LTM are sums of months. FCF = Cash from Operations + Capital expenditures (CapEx is stored negative). Net Cash Flow is the sum of the four sections including FX; component roll-ups (indirect-method Net Income, FX effect) are flagged members of their sections."}


def _explanations(lenses, by_id):
    out = {}
    for key, L in lenses.items():
        if not L.get("available"):
            continue
        reg_lines = []
        for rec in L["lines"]:
            reg = Register()
            path = f"cf.lenses[{key}].lines[{rec['id']}]"
            txt = (f"{rec['label']} is {reg.m(rec['actual'], path + '.actual')} against {reg.m(rec['comparator'], path + '.comparator')} "
                   f"{L['basis_label']}: {reg.m(rec['variance'], path + '.variance', sign=True)} (positive = more cash)."
                   if is_num(rec.get("variance")) else f"{rec['label']} has no {L['basis_label']} comparison in this window.")
            reg_lines.append({"id": rec["id"], "text": txt, "numbers": reg.numbers})
        reg_accts = []
        for rec in L["accounts"]:
            # a "no comparison" sentence informs nobody; quiet accounts render their
            # numbers and badges without prose, which keeps the payload shippable
            if not is_num(rec.get("variance")):
                continue
            a = by_id[rec["id"]]
            reg = Register()
            path = f"cf.lenses[{key}].accounts[{rec['id']}]"
            name = reg.lit(a["name"])
            txt = (f"{name} contributed {reg.m(rec['actual'], path + '.actual')} against {reg.m(rec['comparator'], path + '.comparator')} "
                   f"{L['basis_label']}: {reg.m(rec['variance'], path + '.variance', sign=True)}; {rec['tier']} tier."
                   if is_num(rec.get("variance")) else f"{name} has no {L['basis_label']} comparison in this window.")
            reg_accts.append({"id": rec["id"], "text": txt, "numbers": reg.numbers})
        out[key] = {"lines": reg_lines, "accounts": reg_accts}
    return out
