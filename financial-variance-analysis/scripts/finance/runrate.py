"""Run rate behind the Planning / Operational split.

For each account the run rate of month i is its average monthly amount over every earlier month in the
report window (the analysed month and the RR_WINDOW - 1 before it):
  * a month with no posting (blank or zero) is skipped, never averaged as zero;
  * with at least MIN_CHECK_MONTHS months, a single month far outside the account's normal range is left out,
    and so is an accrual that reverses the following month (both months). "Far outside" is the larger of
    SPREAD_K x the typical month-to-month spread, LEVEL_PCT x the typical level, and the monitoring threshold;
  * an account with no earlier month has no run rate: its whole variance is Operational and Planning is zero.

Planning = run rate - budget (how realistic the budget was); Operational = actual - run rate (how far the month
moved from normal). Both profit-oriented, so Planning + Operational = the reported variance. Actual on an
account with no budget line is Coverage, shown beside the split.
"""
from .common import is_num, mean, r2

RR_WINDOW = 12          # report window in months, the analysed month included
MIN_CHECK_MONTHS = 5    # fewer earlier months: no spike or reversal check
SPREAD_K = 3.0          # x median month-to-month change
LEVEL_PCT = 0.5         # x |median level|
REVERSAL_TOL = 0.25     # the two deviations cancel to within 25 % of the larger

LINE_DEF = (("ni", "Net income", 1.0), ("ebitda", "Adjusted EBITDA", 1.0), ("opex", "Operating expenses", -1.0),
            ("gp", "Gross profit", 1.0), ("cos", "Cost of sales", -1.0), ("rev", "Revenue", 1.0),
            ("syn", "Synergies and strategic investments", 1.0), ("nonop", "Non-operating income (expense)", 1.0))
COMPOSITE = {"gp": ("rev", "cos"), "ebitda": ("rev", "cos", "opex"), "ni": ("rev", "cos", "opex", "syn", "nonop")}


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return None if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def run_rate(A, i, periods, floor_abs, window=RR_WINDOW):
    """Run rate of month i from the po series A. Returns value (po) and the months used / left out."""
    idx = [k for k in range(max(0, i - (window - 1)), i) if is_num(A[k]) and A[k] != 0]
    out = {"value": None, "months_used": 0, "candidates": len(idx), "excluded": [], "threshold": None}
    if not idx:
        out["reason"] = "no earlier month with a posting in the report window"
        return out
    drop = set()
    if len(idx) >= MIN_CHECK_MONTHS:
        vals = [A[k] for k in idx]
        level = _median(vals)
        spread = _median([abs(vals[j] - vals[j - 1]) for j in range(1, len(vals))]) or 0.0
        thr = max(SPREAD_K * spread, LEVEL_PCT * abs(level), floor_abs)
        out["threshold"] = r2(thr)
        dev = {k: A[k] - level for k in idx}
        far = {k for k in idx if abs(dev[k]) > thr}
        for k in idx:   # accrual reversed the following month: both months out
            n = k + 1
            if k in far and n in far and k not in drop and (dev[k] > 0) != (dev[n] > 0) \
                    and abs(dev[k] + dev[n]) <= REVERSAL_TOL * max(abs(dev[k]), abs(dev[n])):
                drop |= {k, n}
                out["excluded"] += [{"month": periods[k]["label"], "amount": r2(A[k]), "reason": "accrual reversed the following month"},
                                    {"month": periods[n]["label"], "amount": r2(A[n]), "reason": "reversal of the prior month's accrual"}]
        rest = far - drop
        if len(rest) == 1:
            k = rest.pop()
            drop.add(k)
            out["excluded"].append({"month": periods[k]["label"], "amount": r2(A[k]), "reason": "one-off spike outside the account's normal range"})
    kept = [A[k] for k in idx if k not in drop]
    out["value"] = r2(mean(kept)) if kept else None
    out["months_used"] = len(kept)
    if not kept:
        out["reason"] = "every earlier month was left out"
    return out


def split(a, b, rr):
    """Planning / operational / coverage of one account-month (po). rr is the run rate value or None."""
    if not is_num(b) or b == 0:
        return {"planning": None, "operational": None, "coverage": a if is_num(a) else None}
    if not is_num(a):
        return {"planning": None, "operational": None, "coverage": None}
    if not is_num(rr):
        return {"planning": 0.0, "operational": a - b, "coverage": None}
    return {"planning": rr - b, "operational": a - rr, "coverage": None}


def build(model, floor_abs, months=RR_WINDOW):
    """Per-account run-rate series and per-line monthly actual / budget / run rate / planning / operational / coverage
    for the last `months` months to the as-of month. Lines are in display sign; the split is profit-oriented."""
    P, as_of = model.f.periods, model.as_of
    first = max(0, as_of - months + 1)
    span = list(range(first, as_of + 1))
    accounts, by_sec = {}, {}
    for a in model.mapped:
        s = model.series[model.aidx[a["id"]]]
        A, B = s["actual"], s["budget"]
        rr = {k: run_rate(A, k, P, floor_abs) for k in span}
        rec = {"run_rate": [r2(rr[k]["value"]) for k in span], "detail": rr[as_of], "split": []}
        for k in span:
            sp = split(A[k], B[k], rr[k]["value"])
            rec["split"].append(sp)
        accounts[a["id"]] = rec
        by_sec.setdefault(a["section"], []).append(a["id"])

    def agg(ids):
        z = lambda: [0.0] * len(span)
        o = {"run_rate": z(), "planning": z(), "operational": z(), "coverage": z(), "with_run_rate": [0] * len(span)}
        for aid in ids:
            rec = accounts[aid]
            for j in range(len(span)):
                if is_num(rec["run_rate"][j]):
                    o["run_rate"][j] += rec["run_rate"][j]; o["with_run_rate"][j] += 1
                for key in ("planning", "operational", "coverage"):
                    if is_num(rec["split"][j][key]):
                        o[key][j] += rec["split"][j][key]
        return o
    lines = {}
    for lid, label, ds in LINE_DEF:
        secs = COMPOSITE.get(lid, (lid,))
        ids = [aid for sec in secs for aid in by_sec.get(sec, [])]
        o = agg(ids)
        ls = model.line_series[lid]
        lines[lid] = {"id": lid, "label": label, "display_sign": ds, "accounts": len(ids),
                      "actual": [r2(None if ls["actual"][k] is None else ls["actual"][k] * ds) for k in span],
                      "budget": [r2(None if ls["budget"][k] is None else ls["budget"][k] * ds) for k in span],
                      "run_rate": [r2(v * ds) if n else None for v, n in zip(o["run_rate"], o["with_run_rate"])],
                      "accounts_with_run_rate": o["with_run_rate"],
                      "planning": [r2(v) for v in o["planning"]], "operational": [r2(v) for v in o["operational"]],
                      "coverage": [r2(v) for v in o["coverage"]]}
    ds_of = {a["id"]: model.display_sign[a["section"]] for a in model.mapped}
    dsp = lambda v, ds: r2(v * ds) if is_num(v) else None
    acct_out = {}
    for aid, rec in accounts.items():
        ds, det = ds_of[aid], rec["detail"]
        acct_out[aid] = {"display_sign": ds, "run_rate": [dsp(v, ds) for v in rec["run_rate"]],
                         "detail": {"value": dsp(det["value"], ds), "months_used": det["months_used"], "candidates": det["candidates"],
                                    "threshold": det["threshold"], "reason": det.get("reason"),
                                    "excluded": [{**x, "amount": dsp(x["amount"], ds)} for x in det["excluded"]]},
                         "planning": r2(rec["split"][-1]["planning"]), "operational": r2(rec["split"][-1]["operational"]),
                         "coverage": r2(rec["split"][-1]["coverage"])}
    return {"months": [P[k]["label"] for k in span], "as_of": P[as_of]["label"],
            "params": {"window_months": RR_WINDOW, "min_months_for_spike_check": MIN_CHECK_MONTHS, "spread_multiple": SPREAD_K,
                       "level_pct": LEVEL_PCT, "floor_abs": floor_abs, "reversal_tolerance": REVERSAL_TOL},
            "definition": {"run_rate": f"average monthly amount over every earlier month in the {RR_WINDOW}-month report window; blank months skipped; "
                                       "a single one-off spike and an accrual reversed the following month are left out (accounts with at least "
                                       f"{MIN_CHECK_MONTHS} earlier months); no earlier month means no run rate",
                           "planning": "run rate minus budget: how far the budget sits from normal, i.e. how realistic the budget was",
                           "operational": "actual minus run rate: how far the month moved from normal (with no run rate, the whole variance)",
                           "coverage": "actual on accounts with no budget line in the month: comparability, not performance"},
            "lines": lines, "accounts": acct_out}
