"""Account-level structural signals on the monthly profit-oriented series at
the as-of month. Each test is `fired`, `not_fired` or `not_tested` (with a
reason); a fired test is EVIDENCE for a hypothesis, never a cause. The
persistence hint and the candidate hypotheses are rule outputs that an
analyst or the diagnosis may accept, reject or leave open.

Run-rate reference. A growing line always sits above its trailing mean, so
the reference is the trailing six-month TREND extended one month (ordinary
least squares), falling back to the trailing mean when fewer than four months
carry a value. Every test that compares the month or the budget with "recent
activity" uses that reference plus a significance floor: the larger of the
monitoring threshold and twice the trailing residual spread."""
from .common import is_num, mean, stdev, r2, r4, safe_div, ols_slope

TRAILING = 6           # months before the as-of month used as the run-rate reference
MIN_TRAILING = 3
MIN_TREND = 4
PERSIST_MIN = 4
CV_FIXED = 0.03
CV_VOLATILE = 0.30
YOY_BREAK = 0.15       # 15 points away from the trailing YoY mean
REL_FLOOR = 0.03       # 3 % of the reference level

TEST_LABEL = {
    "budget_outside_run_rate": "Budget set away from recent months",
    "budget_near_run_rate_edge": "Budget at the edge of recent months",
    "outlier_month": "Month outside its usual range",
    "step_change": "New level, held for two months",
    "reversal_signal": "Last month's gap reversed this month",
    "persistent_gap": "Off budget in the same direction for months",
    "seasonal_echo": "Same month last year moved the same way",
    "unbudgeted_activity": "Activity with no budget line",
    "budgeted_no_activity": "Budget with no activity",
    "escalator": "Grows by the same step every month",
    "fixed_level": "Steady fixed amount",
    "volatile_series": "Swings a lot month to month",
    "yoy_break": "Growth on last year changed pace",
    "new_account": "Account started posting recently",
    "dormant_account": "Account stopped posting",
}

PERSISTENCE_LABEL = {
    "recurring_level_change": "recurring: a new level held for two months",
    "timing_reversal": "timing: undoes last month's move (likely a cut-off or accrual)",
    "one_off_candidate": "possibly one-off: a single unusual month",
    "seasonal": "seasonal: the same month last year moved the same way",
    "persistent": "lasting: the gap to budget has held for most recent months",
    "coverage": "no budget line: nothing to compare with",
    "undetermined": "unclear: not enough history to say whether it repeats",
}


def _t(id_, state, evidence=None, note=None):
    d = {"id": id_, "label": TEST_LABEL[id_], "state": state}
    if evidence:
        d["evidence"] = {k: (r4(v) if isinstance(v, float) else v) for k, v in evidence.items()}
    if note:
        d["note"] = note
    return d


def runrate_of(A, i, periods):
    """Trailing reference for month i: trend-extended level (or the mean), with range, spread and residual spread."""
    idx = [k for k in range(max(0, i - TRAILING), i) if is_num(A[k])]
    vals = [A[k] for k in idx]
    rr = {"months": len(vals), "mean": r2(mean(vals)), "min": r2(min(vals)) if vals else None, "max": r2(max(vals)) if vals else None,
          "stdev": r2(stdev(vals)), "cv": None, "eligible": len(vals) >= MIN_TRAILING, "reference": None, "reference_basis": None,
          "resid_stdev": None, "reason": None if len(vals) >= MIN_TRAILING else f"only {len(vals)} trailing month(s) with a value; {MIN_TRAILING} needed",
          "window": [periods[k]["label"] for k in idx]}
    if rr["mean"] not in (None, 0) and rr["stdev"] is not None:
        rr["cv"] = r4(abs(rr["stdev"] / rr["mean"]))
    if rr["eligible"]:
        if len(vals) >= MIN_TREND:
            slope, icpt = ols_slope(vals)
            fitted = [icpt + slope * k for k in range(len(vals))]
            resid = [v - f for v, f in zip(vals, fitted)]
            rr["reference"] = r2(icpt + slope * len(vals))
            rr["reference_basis"] = "trailing six-month trend extended one month"
            rr["resid_stdev"] = r2(stdev(resid)) if len(resid) >= 3 else rr["stdev"]
            rr["slope_per_month"] = r2(slope)
        else:
            rr["reference"] = rr["mean"]; rr["reference_basis"] = "trailing mean (fewer than four months for a trend)"; rr["resid_stdev"] = rr["stdev"]
    return rr


def signals_for(series, as_of, monitoring_abs, periods):
    """series: {actual, py, budget} po lists. Returns the signal record for one account."""
    A, Y, B = series["actual"], series["py"], series["budget"]
    i = as_of
    a, b, py = A[i], B[i], Y[i]
    rr = runrate_of(A, i, periods)
    tests = []
    nt = lambda id_, note=None: _t(id_, "not_tested", note=note or rr["reason"] or "value missing")
    has_b = is_num(b) and b != 0
    has_a = is_num(a) and a != 0
    tests.append(_t("unbudgeted_activity", "fired" if (has_a and not has_b) else "not_fired", {"actual": a, "budget": b}))
    tests.append(_t("budgeted_no_activity", "fired" if (has_b and not has_a) else "not_fired", {"actual": a, "budget": b}))
    if rr["eligible"]:
        lo, hi, m, ref = rr["min"], rr["max"], rr["mean"], rr["reference"]
        floor = max(monitoring_abs, 2 * (rr["resid_stdev"] or 0), REL_FLOOR * abs(ref))
        if has_b:
            dist = b - ref
            outside = b < lo or b > hi
            sig = abs(dist) >= floor
            tests.append(_t("budget_outside_run_rate", "fired" if sig else "not_fired",
                            {"budget": b, "reference": ref, "reference_basis": rr["reference_basis"], "distance_from_reference": dist, "significance_floor": floor,
                             "trailing_min": lo, "trailing_max": hi, "trailing_mean": m, "trailing_months": rr["months"], "outside_raw_range": outside,
                             "direction": ("more_favourable" if dist > 0 else "less_favourable") if sig else None}))
            edge = (not sig) and abs(dist) >= monitoring_abs and (b < lo or b > hi)
            tests.append(_t("budget_near_run_rate_edge", "fired" if edge else "not_fired", {"budget": b, "reference": ref, "distance_from_reference": dist}))
        else:
            tests.append(nt("budget_outside_run_rate", "no budget line")); tests.append(nt("budget_near_run_rate_edge", "no budget line"))
        if is_num(a):
            dist = a - ref
            out_m = (a < lo or a > hi) and abs(dist) >= floor
            tests.append(_t("outlier_month", "fired" if out_m else "not_fired",
                            {"actual": a, "reference": ref, "reference_basis": rr["reference_basis"], "distance_from_reference": dist, "significance_floor": floor,
                             "trailing_min": lo, "trailing_max": hi, "trailing_mean": m, "direction": ("above_reference" if dist > 0 else "below_reference") if out_m else None}))
        else:
            tests.append(nt("outlier_month"))
        # step change: the step entered at i-1 and held at i, against the six months before i-1
        old_idx = [k for k in range(max(0, i - 1 - TRAILING), i - 1) if is_num(A[k])]
        if is_num(a) and i >= 2 and is_num(A[i - 1]) and is_num(A[i - 2]) and len(old_idx) >= MIN_TRAILING:
            old = [A[k] for k in old_idx]
            rr_old = runrate_of(A, i - 1, periods)
            slope_old = rr_old.get("slope_per_month") or 0.0
            old_mean = mean([rr_old["reference"], rr_old["reference"] + slope_old])     # the old trend carried to the two new months
            old_sd = (rr_old["resid_stdev"] or stdev(old) or 0.0)
            new_level = mean([A[i - 1], a])
            diff = new_level - old_mean
            sig = abs(diff) >= max(monitoring_abs, 2 * old_sd, 0.05 * abs(old_mean))
            entered = abs(A[i - 1] - A[i - 2]) >= 0.5 * abs(diff)
            held = abs(a - A[i - 1]) <= 0.5 * abs(diff) if diff else False
            same_side = ((A[i - 1] - old_mean) > 0) == (diff > 0) and ((a - old_mean) > 0) == (diff > 0)
            fired = sig and entered and held and same_side
            tests.append(_t("step_change", "fired" if fired else "not_fired",
                            {"last_two": [A[i - 1], a], "earlier_mean": old_mean, "earlier_basis": "trend of the six months before the step, carried forward", "earlier_min": min(old), "earlier_max": max(old), "new_level": new_level,
                             "step": diff, "entered_at": periods[i - 1]["label"], "direction": ("up" if diff > 0 else "down") if fired else None}))
        else:
            tests.append(nt("step_change", "fewer than two recent months with an earlier reference"))
        cv = rr["cv"]
        tests.append(_t("fixed_level", "fired" if (cv is not None and cv < CV_FIXED) else "not_fired", {"cv": cv}))
        tests.append(_t("volatile_series", "fired" if (cv is not None and cv > CV_VOLATILE) else "not_fired", {"cv": cv}))
    else:
        for tid in ("budget_outside_run_rate", "budget_near_run_rate_edge", "outlier_month", "step_change", "fixed_level", "volatile_series"):
            tests.append(nt(tid))
    # reversal: prior-month variance vs budget of opposite sign and comparable size
    v_now = (a - b) if is_num(a) and is_num(b) else None
    v_prev = (A[i - 1] - B[i - 1]) if i >= 1 and is_num(A[i - 1]) and is_num(B[i - 1]) else None
    if is_num(v_now) and is_num(v_prev) and abs(v_now) >= monitoring_abs:
        rev_ = (v_now > 0) != (v_prev > 0) and abs(v_prev) >= 0.5 * abs(v_now) and abs(v_now) >= 0.5 * abs(v_prev)
        tests.append(_t("reversal_signal", "fired" if rev_ else "not_fired", {"variance_now": v_now, "variance_prior_month": v_prev, "prior_month": periods[i - 1]["label"], "net_two_months": v_now + v_prev}))
    else:
        tests.append(nt("reversal_signal", "needs this month's and last month's variance to budget above the monitoring threshold"))
    # persistent gap: monthly variances vs budget over the last six months including this one
    vs = [(A[k] - B[k]) for k in range(max(0, i - 5), i + 1) if is_num(A[k]) and is_num(B[k])]
    cum_budget = sum(abs(B[k]) for k in range(max(0, i - 5), i + 1) if is_num(A[k]) and is_num(B[k]))
    if len(vs) >= PERSIST_MIN and is_num(v_now) and v_now != 0:
        same = sum(1 for v in vs if (v > 0) == (v_now > 0))
        cum = sum(vs)
        fired = same >= PERSIST_MIN and abs(cum) >= max(monitoring_abs, 0.015 * cum_budget) and abs(v_now) >= 0.5 * monitoring_abs
        tests.append(_t("persistent_gap", "fired" if fired else "not_fired", {"months_same_side": same, "months_compared": len(vs), "cumulative_variance": cum, "cumulative_budget": cum_budget}))
    else:
        tests.append(nt("persistent_gap", "fewer than four recent months with both actual and budget"))
    # seasonal echo: did the same month last year move the same way against its own reference?
    j = i - 12
    if j >= 1 and is_num(A[j]) and is_num(a) and rr["eligible"]:
        rr_py = runrate_of(A, j, periods)
        if rr_py["eligible"]:
            d_now, d_py = a - rr["reference"], A[j] - rr_py["reference"]
            echo = abs(d_now) >= monitoring_abs and (d_now > 0) == (d_py > 0) and abs(d_py) >= 0.5 * abs(d_now)
            tests.append(_t("seasonal_echo", "fired" if echo else "not_fired",
                            {"move_now_vs_reference": d_now, "move_last_year_vs_its_reference": d_py, "last_year_month": periods[j]["label"]}))
        else:
            tests.append(nt("seasonal_echo", "too little history before the same month last year"))
    else:
        tests.append(nt("seasonal_echo", "no actual for the same month last year"))
    # escalator: constant growth factor over the last six values
    pts = [A[k] for k in range(max(0, i - 5), i + 1)]
    if all(is_num(x) and x != 0 for x in pts) and len(pts) >= 5 and all((x > 0) == (pts[0] > 0) for x in pts):
        g = [pts[k + 1] / pts[k] for k in range(len(pts) - 1)]
        gs = stdev(g)
        esc = gs is not None and gs <= 0.002 and abs(mean(g) - 1) >= 0.001
        tests.append(_t("escalator", "fired" if esc else "not_fired", {"mean_growth": mean(g), "growth_stdev": gs}))
    else:
        tests.append(nt("escalator", "needs six consecutive non-zero months of one sign"))
    # yoy break (po basis; the explanation re-expresses it on the display basis)
    yoy = [safe_div(A[k] - Y[k], abs(Y[k])) for k in range(max(0, i - 6), i) if is_num(A[k]) and is_num(Y[k]) and Y[k] != 0]
    yoy = [y for y in yoy if y is not None]
    y_now = safe_div(a - py, abs(py)) if is_num(a) and is_num(py) and py != 0 else None
    if y_now is not None and len(yoy) >= 3:
        brk = abs(y_now - mean(yoy)) >= YOY_BREAK and abs((a - py)) >= monitoring_abs
        tests.append(_t("yoy_break", "fired" if brk else "not_fired", {"yoy_now": y_now, "trailing_yoy_mean": mean(yoy), "yoy_amount": a - py}))
    else:
        tests.append(nt("yoy_break", "needs a prior-year value this month and three trailing year-on-year points"))
    nz = [k for k in range(0, i + 1) if is_num(A[k]) and A[k] != 0]
    first = nz[0] if nz else None
    tests.append(_t("new_account", "fired" if (first is not None and i - first < MIN_TRAILING and i >= MIN_TRAILING) else "not_fired",
                    {"first_month_with_activity": periods[first]["label"] if first is not None else None}))
    recent_zero = all((not is_num(A[k]) or A[k] == 0) for k in range(max(0, i - 2), i + 1))
    tests.append(_t("dormant_account", "fired" if (nz and recent_zero and nz[-1] < i - 2) else "not_fired",
                    {"last_month_with_activity": periods[nz[-1]]["label"] if nz else None}))

    fired = {t["id"] for t in tests if t["state"] == "fired"}
    if "unbudgeted_activity" in fired:
        hint = "coverage"
    elif "step_change" in fired:
        hint = "recurring_level_change"
    elif "reversal_signal" in fired:
        hint = "timing_reversal"
    elif "persistent_gap" in fired:
        hint = "persistent"
    elif "seasonal_echo" in fired:
        hint = "seasonal"
    elif "outlier_month" in fired:
        hint = "one_off_candidate"
    else:
        hint = "undetermined"
    corroborating = len(fired & {"step_change", "reversal_signal", "persistent_gap", "seasonal_echo", "outlier_month", "budget_outside_run_rate", "yoy_break"})
    confidence = "high" if corroborating >= 3 else "medium" if corroborating == 2 else "low"
    return {"runrate": rr, "tests": tests, "fired": sorted(fired), "persistence_hint": hint,
            "persistence_label": PERSISTENCE_LABEL[hint], "confidence": confidence,
            "volatility": ("fixed" if "fixed_level" in fired else "volatile" if "volatile_series" in fired else "moderate" if rr["cv"] is not None else "not_assessed")}
