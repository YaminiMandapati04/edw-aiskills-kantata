"""One-off months.

A one-off candidate is a single unusual month: an account month outside its trailing six-month range by at least the
larger of the monitoring threshold, twice the trailing residual spread and 3% of the level, measured against the trend
reference (the same test the monthly signals run). The register lists the candidates at or above the management
threshold inside a window; the ones at or above a quarter of the window's net-income movement are "named": the lead
says what net income does without them, and the run-rate outlook takes their months out before averaging."""
from .common import is_num, r2
from .signals import TRAILING, MIN_TRAILING
from .synthesis import account_label

NAMING_SHARE = 0.25


def find(model, rng, threshold):
    """One-off candidates for every mapped account over the months in rng (inclusive), profit-oriented."""
    from .signals import runrate_of, REL_FLOOR
    P = model.f.periods
    items = []
    for a in model.mapped:
        A = model.series[model.aidx[a["id"]]]["actual"]
        for k in range(rng[0], rng[1] + 1):
            if not is_num(A[k]):
                continue
            rr = runrate_of(A, k, P)
            base = {"account": a["id"], "name": account_label(model, a["id"]), "driver": model.driver_of.get(a["id"]), "section": a["section"],
                    "month": P[k]["label"], "month_idx": k, "actual": r2(A[k])}
            if rr["eligible"]:
                ref = rr["reference"]
                dist = A[k] - ref
                floor = max(threshold, 2 * (rr["resid_stdev"] or 0.0), REL_FLOOR * abs(ref))
                if (A[k] < rr["min"] or A[k] > rr["max"]) and abs(dist) >= floor:
                    items.append({**base, "reference": r2(ref), "reference_basis": rr["reference_basis"], "amount": r2(dist),
                                  "trailing_min": rr["min"], "trailing_max": rr["max"], "significance_floor": r2(floor), "test": "outlier_month"})
            elif k >= MIN_TRAILING and A[k] != 0 and all(not is_num(A[j]) or A[j] == 0 for j in range(max(0, k - TRAILING), k))                     and all(not is_num(A[j]) or A[j] == 0 for j in range(k + 1, model.as_of + 1)) and abs(A[k]) >= threshold:
                # a single posting on an account with no recent history: nothing to compare with, so the whole amount is the candidate
                items.append({**base, "reference": 0.0, "reference_basis": "no trailing activity", "amount": r2(A[k]), "trailing_min": 0.0, "trailing_max": 0.0,
                              "significance_floor": r2(threshold), "test": "single_posting"})
    items.sort(key=lambda x: (-abs(x["amount"]), x["account"], x["month"]))
    _pair_offsets(items)
    return items


def _pair_offsets(items):
    """Two flagged items in the same month that cancel each other (within 5% of the larger) are a booking pair, such as
    intercompany revenue against intercompany cost: kept in the register, marked, and never named or taken out."""
    by_month = {}
    for x in items:
        by_month.setdefault(x["month"], []).append(x)
    for xs in by_month.values():
        for a in xs:
            if a.get("offset_with"):
                continue
            for b in xs:
                if b is a or b.get("offset_with") or a["amount"] * b["amount"] >= 0:
                    continue
                if abs(a["amount"] + b["amount"]) <= 0.05 * max(abs(a["amount"]), abs(b["amount"])):
                    a["offset_with"], b["offset_with"] = b["account"], a["account"]
                    break


def register(L, items):
    """The window's one-off register and what net income does without the named items."""
    r = L["range"]
    mine = [x for x in items if r["start_idx"] <= x["month_idx"] <= r["end_idx"]]
    ni = next(x for x in L["lines"] if x["id"] == "ni")
    nv = ni["variance"]
    big = L["materiality"]["executive_abs"]
    named = [x for x in mine if is_num(nv) and nv != 0 and not x.get("offset_with") and abs(x["amount"]) >= max(NAMING_SHARE * abs(nv), big)]
    named_total = r2(sum(x["amount"] for x in named))
    return {"items": mine, "count": len(mine), "total": r2(sum(x["amount"] for x in mine)),
            "named": named, "named_count": len(named), "named_total": named_total,
            "naming_rule": f"an item at or above {int(NAMING_SHARE * 100)}% of the window's net-income movement, and at least the window's large threshold, is named in the lead; offsetting pairs are never named",
            "underlying_variance": r2(nv - named_total) if named and is_num(nv) else None,
            "underlying_basis": "net income variance with the named one-off amounts (actual minus the account's trend reference) taken out of the actual side; the comparator is not adjusted"}

