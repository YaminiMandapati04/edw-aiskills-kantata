"""Mechanical full-year outlook: year to date plus a run-rate rule for the
remaining months, with the sensitivity to the rule, against the full-year
budget where the extract carries it. A projection rule, never a forecast; no
management adjustment is ever included."""
from .common import is_num, r2, r4, mean, ols_slope, safe_div


def _adjusted(model, one_offs):
    """Actual series with each flagged one-off amount taken out of its month, for every section, line and driver holding the account."""
    lines_of = {"rev": ("rev", "gp", "ebitda", "ni"), "cos": ("cos", "gp", "ebitda", "ni"), "opex": ("opex", "ebitda", "ni"),
                "syn": ("syn", "ni"), "nonop": ("nonop", "ni")}
    out = {}
    for x in one_offs or []:
        if x.get("offset_with"):
            continue
        for key in lines_of.get(x["section"], ()) + ((x["driver"],) if x.get("driver") else ()):
            s = model.line_series.get(key)
            if not s:
                continue
            if key not in out:
                out[key] = list(s["actual"])
            if is_num(out[key][x["month_idx"]]):
                out[key][x["month_idx"]] -= x["amount"]
    return out


def compute(model, signals, mtd_budget_lens, one_offs=None):
    P = model.f.periods
    i = model.as_of
    adj = _adjusted(model, one_offs)
    adj_actual = lambda key: adj.get(key) or model.line_series[key]["actual"]
    fy = P[i]["year"]
    fy_idx = [p["idx"] for p in P if p["year"] == fy]
    realized = [k for k in fy_idx if k <= i]
    # periods per fiscal year: a complete earlier year in the frame, else 12
    years = {}
    for p in P:
        years.setdefault(p["year"], []).append(p["idx"])
    complete = [len(v) for y, v in years.items() if y < fy and len(v) >= 12]
    ppy = max(complete) if complete else 12
    remaining = ppy - len(realized)
    fy_in_frame = len(fy_idx)
    out = {"state": "calculated" if realized else "not_calculated", "fiscal_year": fy, "periods_per_year": ppy, "periods_realized": len(realized),
           "remaining_months": remaining, "fy_periods_in_extract": fy_in_frame,
           "fy_budget_available": fy_in_frame >= ppy, "lines": {}, "rules": ["trailing_3_mean", "trailing_6_mean", "period_flat", "trend_extrapolation"],
           "one_offs_excluded": [{k: x[k] for k in ("account", "name", "driver", "section", "month", "amount", "test")} for x in (one_offs or []) if not x.get("offset_with")],
           "one_offs_rule": "a month flagged as a one-off (outside the account's trailing range by a significant amount, at the management threshold) is replaced by the account's trend reference before any run-rate rule is applied; year to date stays as reported"}
    if not realized:
        out["reason"] = "No realized period in the fiscal year."
        return out
    if fy_in_frame < ppy:
        out["note"] = (f"The extract carries {fy_in_frame} of {ppy} fiscal-year periods, so the full-year budget is not available: run the query through the fiscal year end "
                       f"(budget columns are populated for future months) to compare the mechanical outlook with the full-year budget.")
    prev_year_idx = years.get(fy - 1, [])
    for lid in ("rev", "ebitda", "ni"):
        s = model.line_series[lid]
        ytd_a = sum(s["actual"][k] or 0 for k in realized)
        ytd_b = sum(s["budget"][k] or 0 for k in realized) if any(is_num(s["budget"][k]) for k in realized) else None
        fy_b = sum(s["budget"][k] or 0 for k in fy_idx) if out["fy_budget_available"] and any(is_num(s["budget"][k]) for k in fy_idx) else None
        rem_b = (fy_b - ytd_b) if is_num(fy_b) and is_num(ytd_b) else None
        A = adj_actual(lid)
        hist = [A[k] for k in range(max(0, i - 11), i + 1)]
        t3 = mean([A[k] for k in range(max(0, i - 2), i + 1)])
        t6 = mean([A[k] for k in range(max(0, i - 5), i + 1)])
        flat = A[i]
        slope, icpt = ols_slope(hist)
        n = len([h for h in hist if is_num(h)])
        trend_rr = None
        trend_val = None
        if slope is not None:
            future = [icpt + slope * (n - 1 + m) for m in range(1, remaining + 1)]
            trend_val = ytd_a + sum(future)
            trend_rr = mean(future) if future else None
        sens = [{"rule": "trailing_3_mean", "label": "Trailing three-month average", "run_rate": r2(t3), "value": r2(ytd_a + remaining * t3) if is_num(t3) else None},
                {"rule": "trailing_6_mean", "label": "Trailing six-month average", "run_rate": r2(t6), "value": r2(ytd_a + remaining * t6) if is_num(t6) else None},
                {"rule": "period_flat", "label": "Latest month held flat", "run_rate": r2(flat), "value": r2(ytd_a + remaining * flat) if is_num(flat) else None},
                {"rule": "trend_extrapolation", "label": "Twelve-month trend extrapolated", "run_rate": r2(trend_rr), "value": r2(trend_val)}]
        # each rule carries its own monthly path, months used and gaps, so the page can switch rules without computing
        lbl = lambda a, b: [P[k]["label"] for k in range(max(0, a), b + 1)]
        used = {"trailing_3_mean": lbl(i - 2, i), "trailing_6_mean": lbl(i - 5, i), "period_flat": lbl(i, i), "trend_extrapolation": lbl(i - 11, i)}
        how = {"trailing_3_mean": "the average of the last three closed months", "trailing_6_mean": "the average of the last six closed months",
               "period_flat": "the latest closed month, repeated", "trend_extrapolation": "a straight line fitted to the last twelve months, extended"}
        py_fy = sum(s["actual"][k] or 0 for k in prev_year_idx) if len(prev_year_idx) >= ppy else None
        for x in sens:
            rr = x["run_rate"]
            x["path"] = ([r2(v) for v in future] if x["rule"] == "trend_extrapolation" and slope is not None
                         else [rr] * remaining if is_num(rr) else [])
            x["months_used"], x["how"] = used[x["rule"]], how[x["rule"]] + (" (one-off months taken out)" if lid in adj else "")
            rem_val = r2(x["value"] - ytd_a) if is_num(x["value"]) else None
            x["remaining_value"] = rem_val
            x["remaining_effect"] = r2(rem_val - rem_b) if is_num(rem_val) and is_num(rem_b) else None
            x["gap_vs_budget"] = r2(x["value"] - fy_b) if is_num(x["value"]) and is_num(fy_b) else None
            x["gap_vs_prior_year"] = r2(x["value"] - py_fy) if is_num(x["value"]) and is_num(py_fy) else None
        mech = sens[0]
        vals = [x["value"] for x in sens if is_num(x["value"])]
        spread = r4(safe_div((max(vals) - min(vals)), abs(mech["value"])) if vals and is_num(mech["value"]) and mech["value"] else None)
        rec = {"id": lid, "ytd": {"actual": r2(ytd_a), "budget": r2(ytd_b), "variance": r2(ytd_a - ytd_b) if is_num(ytd_b) else None},
               "fy_budget": r2(fy_b), "remaining_budget": r2(rem_b), "periods_realized": len(realized), "periods_total": ppy, "remaining_months": remaining,
               "mechanical": {"rule": mech["rule"], "run_rate": mech["run_rate"], "value": mech["value"],
                              "remaining_effect": r2(remaining * t3 - rem_b) if is_num(t3) and is_num(rem_b) else None,
                              "sensitivity": sens, "sensitivity_spread_pct": spread,
                              "basis": f"year to date actual plus {remaining} remaining month(s) at the trailing three-month average of the line"},
               "gap_vs_budget": r2(mech["value"] - fy_b) if is_num(mech["value"]) and is_num(fy_b) else None,
               "prior_year_full_year": r2(py_fy), "gap_vs_prior_year": r2(mech["value"] - py_fy) if is_num(mech["value"]) and is_num(py_fy) else None,
               "identity": "fy_budget + ytd_variance + remaining_effect = mechanical (when the full-year budget is available)"}
        out["lines"][lid] = rec
    out["gap_view"] = _gap_view(model, signals, mtd_budget_lens, i, fy_idx, remaining, out, adj_actual)
    # persistence view: material drivers in the MTD vs budget lens
    pv = []
    L = mtd_budget_lens
    if L and L.get("available"):
        for d in L["drivers"]:
            if d["tier"] not in ("executive", "management") or not is_num(d["variance"]):
                continue
            lead = max((a for a in L["accounts"] if a["driver_ref"] == d["id"] and is_num(a["variance"])), key=lambda a: abs(a["variance"]), default=None)
            hint = signals[lead["id"]]["persistence_hint"] if lead else "undetermined"
            persists = hint in ("recurring_level_change", "persistent")
            pv.append({"driver": d["id"], "label": d["label"], "monthly_variance": d["variance"], "persistence_hint": hint,
                       "treatment": "carry" if persists else ("reverses" if hint == "timing_reversal" else "none proposed"),
                       "remaining_effect_if_persists": r2(d["variance"] * remaining) if persists else None, "forecast_credit": 0,
                       "note": "proposal only; a named person must accept the treatment before it enters any forecast"})
    out["persistence_view"] = pv
    out["persistence_totals"] = {"proposed_carry": r2(sum(x["remaining_effect_if_persists"] or 0 for x in pv)), "declared_by_management": None, "approved_mitigation": None}
    return out


RULES = ("trailing_3_mean", "trailing_6_mean", "period_flat", "trend_extrapolation")
CATEGORY = {"rev": "ebitda", "cos": "ebitda", "opex": "ebitda", "syn": "below", "nonop": "below"}


def _rule_path(vals, i, remaining):
    """The remaining months under each rule for one series (missing months count as zero, so driver paths add up to the line's)."""
    v = [x if is_num(x) else 0.0 for x in vals]
    t3, t6 = mean(v[max(0, i - 2): i + 1]), mean(v[max(0, i - 5): i + 1])
    slope, icpt = ols_slope(v[max(0, i - 11): i + 1])
    n = len(v[max(0, i - 11): i + 1])
    return {"trailing_3_mean": [t3] * remaining, "trailing_6_mean": [t6] * remaining, "period_flat": [v[i]] * remaining,
            "trend_extrapolation": [icpt + slope * (n - 1 + m) for m in range(1, remaining + 1)] if slope is not None else None}


def _gap_view(model, signals, L, i, fy_idx, remaining, out, adj_actual):
    """If current gaps continue, per run-rate rule: each driver's remaining months at the rule's run-rate against its
    remaining budget. The revenue, cost of sales and operating-expense drivers add up to the EBITDA bridge's
    'remaining months vs budget' step for the same rule; the below-the-line drivers to the rest of net income's."""
    if not out["fy_budget_available"] or remaining <= 0:
        return {"available": False, "reason": "The full-year budget is not in the extract, so the remaining months cannot be set against it." if remaining > 0 else "No month of the fiscal year is left."}
    rem_idx = [k for k in fy_idx if k > i]
    lens_drv = {d["id"]: d for d in (L or {}).get("drivers", [])} if L and L.get("available") else {}
    hint = {}
    for did in lens_drv:
        lead = max((a for a in L["accounts"] if a["driver_ref"] == did and is_num(a["variance"])), key=lambda a: abs(a["variance"]), default=None)
        hint[did] = signals[lead["id"]]["persistence_hint"] if lead else "undetermined"
    rules = {r: {"drivers": [], "totals": {}} for r in RULES}
    for d in model.drivers:
        s = model.line_series.get(d["id"])
        if not s or d["section"] not in CATEGORY:
            continue
        rem_b = sum(s["budget"][k] or 0 for k in rem_idx)
        paths = _rule_path(adj_actual(d["id"]), i, remaining)
        for r in RULES:
            pth = paths[r]
            if pth is None:
                continue
            val = sum(pth)
            eff = val - rem_b
            if abs(eff) < 0.005 and abs(val) < 0.005:
                continue
            rules[r]["drivers"].append({"driver": d["id"], "label": d["label"], "section": d["section"], "category": CATEGORY[d["section"]],
                                        "run_rate": r2(mean(pth)), "remaining_value": r2(val), "remaining_budget": r2(rem_b), "remaining_effect": r2(eff),
                                        "persistence_hint": hint.get(d["id"], "undetermined")})
    for r, rec in rules.items():
        rec["drivers"].sort(key=lambda x: (-abs(x["remaining_effect"] or 0), x["driver"]))
        for key in ("rev", "cos", "opex", "syn", "nonop", "ebitda", "below"):
            rec["totals"][key] = r2(sum(x["remaining_effect"] for x in rec["drivers"] if key in (x["section"], x["category"])))
        rec["totals"]["ni"] = r2(rec["totals"]["ebitda"] + rec["totals"]["below"])
    return {"available": True, "remaining_months": remaining, "rules": rules,
            "basis": f"each driver's remaining {remaining} month(s) at the rule's run-rate, against its budget for those months"}
