"""Balance sheet block (payload key `bs`, contract 1.1.0).

Balances are point-in-time month-end figures, stored as the mart stores them
(assets positive, liabilities and equity positive in the sample mart). Nothing
is summed across months: the MTD lens compares the as-of balance with its
comparator; QTD / YTD / LTM lenses compare MOVEMENTS (as-of balance minus the
balance at the month before the window start) with the comparator's movement
over the same months. The diagnosis gate does not cover this block; it ships
with the deterministic engine baseline only.
"""
import datetime as dt

from .common import money, natural_id, BuildError, Register, is_num, r2, r4, safe_div, slug, to_date, to_num, add
from .model import window_range, BASIS_LABEL, WINDOW_LABEL
from .signals import signals_for

NEEDED = ["PERIOD_START_DATE", "CHART_OF_ACCOUNT_KEY", "ACCOUNT_NAME", "COA_MAPPING_L1", "COA_MAPPING_L2", "COA_MAPPING_L3"]
ACTUAL_COLS = ["ENDING_BALANCE_CONVERTED", "ENDING_BALANCE", "MTD"]
PY_COLS = ["ENDING_BALANCE_PY_CONVERTED", "ENDING_BALANCE_PY", "PY_MTD"]
BUDGET_COLS = ["ENDING_BALANCE_BUDGET", "BUDGET_MTD"]

# good: which direction of movement is favourable. "up" = growth favourable,
# "down" = reduction favourable, "neutral" = reported without a judgement.
LINE_SPEC = [
    ("assets", "Total assets", "up"),
    ("current_assets", "Current assets", "up"),
    ("noncurrent_assets", "Non-current assets", "neutral"),
    ("liabilities", "Total liabilities", "down"),
    ("current_liabilities", "Current liabilities", "down"),
    ("longterm_liabilities", "Long-term liabilities", "down"),
    ("equity", "Equity", "up"),
    ("liab_equity", "Total liabilities & equity", "neutral"),
]
KPI_SPEC = [
    ("cash", "Cash & equivalents", "up"),
    ("working_capital", "Working capital", "up"),
    ("net_debt", "Net debt", "down"),
    ("assets", "Total assets", "up"),
]


def _norm(s):
    return str(s or "").strip().lower()


def _pick(row0, cols, what):
    for c in cols:
        if c in row0:
            return c
    raise BuildError(f"Balance sheet rows carry no {what} column (looked for {', '.join(cols)}). Run the BS query in references/dashboards.md.")


def bs_rows_from_workbook(path):
    """Local test mode: join the workbook's BALANCE_SHEET sheet into flat rows."""
    from .load import _sheet
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    if "BALANCE_SHEET" not in wb.sheetnames:
        return []
    acct = {str(a["CHART_OF_ACCOUNT_KEY"]): a for a in _sheet(wb, "ACCOUNT")}
    per = {p["ACCOUNTING_PERIOD_KEY"]: p for p in _sheet(wb, "PERIOD")}
    sub = {s["SUBSIDIARY_KEY"]: s["SUBSIDIARY_NAME"] for s in _sheet(wb, "SUBSIDIARY")}
    out = []
    for r in _sheet(wb, "BALANCE_SHEET"):
        a, p = acct.get(str(r["CHART_OF_ACCOUNT_KEY"])), per[r["ACCOUNTING_PERIOD_KEY"]]
        if a is None or str(a.get("FINANCIAL_STATEMENT")) != "BS":
            continue
        out.append({"PERIOD_START_DATE": p["PERIOD_START_DATE"], "SUBSIDIARY_NAME": sub[r["SUBSIDIARY_KEY"]],
                    "CHART_OF_ACCOUNT_KEY": a["CHART_OF_ACCOUNT_KEY"], "ACCOUNT_NAME": a["ACCOUNT_NAME"],
                    "FINANCIAL_STATEMENT": "BS",
                    "COA_MAPPING_L1": a.get("COA_MAPPING_L1"), "COA_MAPPING_L2": a.get("COA_MAPPING_L2"),
                    "COA_MAPPING_L3": a.get("COA_MAPPING_L3"),
                    "MTD": r.get("MTD"), "PY_MTD": r.get("PY_MTD"), "BUDGET_MTD": r.get("BUDGET_MTD")})
    return out


def _series_env(rows, periods, subsidiary):
    """Accounts (real + roll-ups kept apart) and per-account month series aligned to the IS period axis."""
    row0 = rows[0]
    missing = [c for c in NEEDED if c not in row0]
    if missing:
        raise BuildError("Balance sheet rows missing column(s): " + ", ".join(missing) + ". Run the BS query in references/dashboards.md.")
    a_col = _pick(row0, ACTUAL_COLS, "balance")
    p_col = _pick(row0, PY_COLS, "prior-year balance")
    b_col = next((c for c in BUDGET_COLS if c in row0), None)
    if "FINANCIAL_STATEMENT" in row0:
        rows = [r for r in rows if _norm(r.get("FINANCIAL_STATEMENT")) in ("bs", "balance sheet")]
    if subsidiary:
        rows = [r for r in rows if _norm(r.get("SUBSIDIARY_NAME")) == _norm(subsidiary)]
    if not rows:
        raise BuildError("No balance-sheet rows after filtering (FINANCIAL_STATEMENT = 'BS').")
    pidx = {dt.date.fromisoformat(p["start"]): p["idx"] for p in periods}
    np_ = len(periods)
    accounts, aidx, series, outside = [], {}, {}, 0
    keys_seen = set()
    for r in rows:
        raw_key = str(r["CHART_OF_ACCOUNT_KEY"]).strip()
        k = natural_id(raw_key, r["ACCOUNT_NAME"], r.get("COA_MAPPING_L1"), r.get("COA_MAPPING_L2"), r.get("COA_MAPPING_L3"))
        keys_seen.add(raw_key)
        d = to_date(r["PERIOD_START_DATE"]).replace(day=1)
        if d not in pidx:
            outside += 1
            continue
        if k not in aidx:
            aidx[k] = len(accounts)
            accounts.append({"id": k, "name": str(r["ACCOUNT_NAME"]), "l1": (r.get("COA_MAPPING_L1") or None),
                             "l2": (r.get("COA_MAPPING_L2") or None), "l3": (r.get("COA_MAPPING_L3") or None)})
            series[k] = {b: [None] * np_ for b in ("actual", "py", "budget")}
        i = pidx[d]
        s = series[k]
        s["actual"][i] = add(s["actual"][i], to_num(r.get(a_col)))
        s["py"][i] = add(s["py"][i], to_num(r.get(p_col)))
        s["budget"][i] = add(s["budget"][i], to_num(r.get(b_col))) if b_col else s["budget"][i]
    rollups = {a["id"]: a for a in accounts if a["id"].startswith("-")}
    real = [a for a in accounts if not a["id"].startswith("-")]
    n_keys = sum(1 for k in keys_seen if not k.startswith("-"))
    return real, rollups, series, b_col is not None, outside, n_keys


def _sum(series_list, np_):
    out = {b: [None] * np_ for b in ("actual", "py", "budget")}
    for s in series_list:
        for b in ("actual", "py", "budget"):
            for i in range(np_):
                out[b][i] = add(out[b][i], s[b][i])
    return out


def _l1_bucket(l1, l2=None):
    """assets | liabilities | equity. Some marts put a combined side at L1
    ('Total Liabilities & Share Holder Equity') and the real role at L2 —
    the startswith tests skip the combined label and the L2 fallback catches it."""
    for n in (_norm(l1), _norm(l2)):
        if n.startswith("asset"):
            return "assets"
        if n.startswith("liabilit"):
            return "liabilities"
        if n.startswith("equity") or n.startswith("total equity") or n.startswith("share holder equity") or n.startswith("shareholder"):
            return "equity"
    return None


def _l2_bucket(l1b, l2, l3=None):
    """current/non-current split: read from whichever of L2/L3 carries it (some
    marts put 'Current Liabilities' at L3 under a plain 'Liabilities' L2)."""
    cands = [_norm(l2), _norm(l3)]
    if l1b == "assets":
        n = next((c for c in cands if "current" in c), cands[0])
        return "current_assets" if "current" in n and not n.startswith("non") else "noncurrent_assets"
    if l1b == "liabilities":
        n = next((c for c in cands if "current" in c or "long" in c), cands[0])
        return "current_liabilities" if "current" in n and not n.startswith("non") and "long" not in n else "longterm_liabilities"
    return "equity"


DEBT_WORDS = ("debt", "loan", "revolv", "credit facilit", "notes payable", "borrowing", "term facility")


def _debt_accounts(mapped):
    """Liability accounts that carry borrowings: by mapping or by account name (debt often sits under a
    generic 'Long-Term Liabilities' L3). Lease liabilities are left out of net debt."""
    out = []
    for a in mapped:
        if a.get("l1_bucket") != "liabilities" or a.get("rollup"):
            continue
        txt = " ".join(_norm(x) for x in (a["name"], a["l2"], a["l3"]))
        if any(w in txt for w in DEBT_WORDS) and "lease" not in _norm(a["name"]):
            out.append(a["id"])
    return out


def _status(variance, good, threshold):
    if not is_num(variance):
        return "not_comparable"
    if abs(variance) < threshold:
        return "in_line"
    if good == "neutral":
        return "higher" if variance > 0 else "lower"
    fav = variance > 0 if good == "up" else variance < 0
    return "ahead" if fav else "behind"


def build(rows, periods, as_of, subsidiary=None, expect_accounts=None):
    """Build the `bs` payload block. `periods`/`as_of` come from the IS frame (shared axis)."""
    if not rows:
        return {"available": False, "reason": "No balance-sheet rows supplied (--bs-rows / BALANCE_SHEET sheet)."}
    real, rollups, series, has_budget, outside, n_keys = _series_env(rows, periods, subsidiary)
    if expect_accounts is not None and n_keys != expect_accounts:
        raise BuildError(f"The BS data has {n_keys} real account key(s) but the probe counted {expect_accounts}. "
                         "The result was probably cut off: re-run the query in smaller period chunks.")
    np_ = len(periods)
    # a budget column with values on no (or almost no) real account cannot carry a
    # comparison: vs-budget lenses are then unavailable with the reason, never n/a cells
    if has_budget:
        bud_real = sum(1 for a in real if any(is_num(v) for v in series[a["id"]]["budget"]))
        if bud_real == 0:
            has_budget = False
            budget_reason = "ENDING_BALANCE_BUDGET carries no value on any real BS account in the extract, so vs-budget comparisons are not comparable."
        else:
            budget_reason = None
    else:
        bud_real = 0
        budget_reason = None
    for a in real:
        a["l1_bucket"] = _l1_bucket(a["l1"], a["l2"])
        a["l2_bucket"] = _l2_bucket(a["l1_bucket"], a["l2"], a["l3"]) if a["l1_bucket"] else None
    unmapped = [a for a in real if a["l1_bucket"] is None]
    mapped = [a for a in real if a["l1_bucket"]]
    if not mapped:
        return {"available": False, "reason": "No BS account maps to Assets, Liabilities or Equity (COA_MAPPING_L1)."}
    # component roll-ups: equity parts some marts carry only as roll-up keys
    # (Retained Earnings, CTA, Net Income). They join their section as flagged
    # members — without them the sheet cannot foot. Subtotal/duplicate keys
    # (-15 total, -1000 total debt) and roll-ups outside the tree stay out.
    extras = []
    for k, a in rollups.items():
        if k in ("-15", "-1000"):
            continue
        b = _l1_bucket(a["l1"], a["l2"])
        if not b:
            continue
        a["l1_bucket"] = b
        a["l2_bucket"] = _l2_bucket(b, a["l2"], a["l3"])
        a["name"] = (a["name"] or "").strip() or (a.get("l3") or a.get("l2") or a["l1"])
        a["rollup"] = True
        extras.append(a)
    mapped = mapped + extras
    # ---- side sign: some marts store Liabilities & Equity in credit sign (negative).
    # Detected from the as-of identity (assets ≈ −(L+E)) and normalised so that
    # liabilities and equity read positive, every 'good' direction keeps its meaning,
    # and the sheet foots. Recorded as a QC caveat — never silent.
    le_ids = [a["id"] for a in mapped if a["l1_bucket"] in ("liabilities", "equity")]
    as_sum = sum(series[a["id"]]["actual"][as_of] or 0.0 for a in mapped if a["l1_bucket"] == "assets")
    le_sum = sum(series[i]["actual"][as_of] or 0.0 for i in le_ids)
    le_flipped = False
    if as_sum > 0 and le_sum < 0 and abs(as_sum + le_sum) <= max(abs(as_sum), abs(le_sum)) * 0.25:
        le_flipped = True
        for i in le_ids:
            for b in ("actual", "py", "budget"):
                series[i][b] = [None if v is None else -v for v in series[i][b]]
    # ---- groups: L3 inside an L2 bucket (the drill level between line and account)
    groups, group_of = [], {}
    for l2b in ("current_assets", "noncurrent_assets", "current_liabilities", "longterm_liabilities", "equity"):
        byl3 = {}
        for a in mapped:
            if a["l2_bucket"] != l2b:
                continue
            key = (a["l3"] or a["name"]).strip()
            gid = f"g:bs:{slug(l2b)}:{slug(key)}"
            g = byl3.setdefault(gid, {"id": gid, "label": key, "line": l2b, "l1_bucket": a["l1_bucket"], "accounts": []})
            g["accounts"].append(a["id"])
            group_of[a["id"]] = gid
        groups.extend(sorted(byl3.values(), key=lambda g: g["label"].lower()))
    # ---- line series
    ls = {}
    for l2b in ("current_assets", "noncurrent_assets", "current_liabilities", "longterm_liabilities", "equity"):
        ls[l2b] = _sum([series[a["id"]] for a in mapped if a["l2_bucket"] == l2b], np_)
    ls["assets"] = _sum([ls["current_assets"], ls["noncurrent_assets"]], np_)
    ls["liabilities"] = _sum([ls["current_liabilities"], ls["longterm_liabilities"]], np_)
    ls["liab_equity"] = _sum([ls["liabilities"], ls["equity"]], np_)
    for gid in [g["id"] for g in groups]:
        g = next(x for x in groups if x["id"] == gid)
        ls[gid] = _sum([series[x] for x in g["accounts"]], np_)
    # derived
    wc = {b: [None if (ls["current_assets"][b][i] is None and ls["current_liabilities"][b][i] is None)
              else (ls["current_assets"][b][i] or 0.0) - (ls["current_liabilities"][b][i] or 0.0) for i in range(np_)] for b in ("actual", "py", "budget")}
    cash_accts = [a["id"] for a in mapped if "cash" in _norm(a["l3"])]
    cash = _sum([series[k] for k in cash_accts], np_) if cash_accts else {b: [None] * np_ for b in ("actual", "py", "budget")}
    if "-1000" in rollups:
        debt = series["-1000"]
        debt_basis = "Total Debt roll-up (-1000)"
    else:
        dk = _debt_accounts(mapped)
        debt = _sum([series[k] for k in dk], np_) if dk else {b: [None] * np_ for b in ("actual", "py", "budget")}
        debt_basis = (f"sum of {len(dk)} liability account(s) named or mapped as debt, loans, borrowings or credit facilities "
                      "(debt issuance costs included as stored; lease liabilities excluded)") if dk else "no debt account found"
    nd = {b: [None if (debt[b][i] is None and cash[b][i] is None) else (debt[b][i] or 0.0) - (cash[b][i] or 0.0) for i in range(np_)] for b in ("actual", "py", "budget")}
    ls["working_capital"], ls["cash"], ls["net_debt"] = wc, cash, nd
    # ---- materiality scaled to total assets at as-of
    ta = abs(ls["assets"]["actual"][as_of] or 0.0)
    mat = {"executive_abs": max(round(ta * 0.005, -2), 100.0), "management_abs": max(round(ta * 0.001, -2), 100.0),
           "monitoring_abs": max(round(ta * 0.0003, -2), 100.0), "basis": "total assets at the as-of month", "total_assets_basis": r2(ta)}
    mon = mat["monitoring_abs"]

    def tier(v):
        if not is_num(v):
            return "immaterial"
        a = abs(v)
        return "executive" if a >= mat["executive_abs"] else "management" if a >= mat["management_abs"] else "monitoring" if a >= mon else "immaterial"

    # ---- lenses
    def vals(s, basis, rng, good):
        end, cend = s["actual"][as_of], s[basis][as_of]
        open_i = rng[0] - 1
        mv = cmv = None
        if open_i >= 0:
            if is_num(end) and is_num(s["actual"][open_i]):
                mv = end - s["actual"][open_i]
            if is_num(cend) and is_num(s[basis][open_i]):
                cmv = cend - s[basis][open_i]
        var_end = (end - cend) if is_num(end) and is_num(cend) else None
        var_mv = (mv - cmv) if is_num(mv) and is_num(cmv) else None
        primary = var_end if rng[0] == rng[1] == as_of else var_mv   # MTD compares balances; windows compare movements
        return {"balance": r2(end), "comparator": r2(cend), "balance_variance": r2(var_end),
                "balance_variance_pct": r4(safe_div(var_end, abs(cend)) if is_num(cend) and cend != 0 else None),
                "movement": r2(mv), "comparator_movement": r2(cmv), "movement_variance": r2(var_mv),
                "variance": r2(primary), "status": _status(primary, good, mon), "tier": tier(primary), "good": good}

    lenses = {}
    for w in ("MTD", "QTD", "YTD", "LTM"):
        for basis in ("budget", "py"):
            key = f"{w}_{basis}"
            rng = window_range(periods, as_of, w)
            L = {"id": key, "window": w, "basis": basis, "basis_label": BASIS_LABEL[basis], "window_label": WINDOW_LABEL[w],
                 "available": rng is not None and (basis != "budget" or has_budget)}
            if rng is None:
                L["reason"] = "LTM needs twelve months of history up to the as-of period."
            elif basis == "budget" and not has_budget:
                L["reason"] = budget_reason or "The BS extract carries no budget column (ENDING_BALANCE_BUDGET)."
            if not L["available"]:
                lenses[key] = L
                continue
            L["range"] = {"start_idx": rng[0], "end_idx": rng[1], "start": periods[rng[0]]["start"], "end": periods[rng[1]]["end"],
                          "label": f"{w} to {periods[rng[1]]['label']}" if w != "MTD" else periods[rng[1]]["label"]}
            L["semantics"] = ("month-end balance vs " + BASIS_LABEL[basis]) if w == "MTD" else \
                (f"movement over the window (as-of balance minus the balance before {periods[rng[0]]['label']}) vs the {BASIS_LABEL[basis]} movement")
            good_of = dict((i, g) for i, _, g in LINE_SPEC)
            L["lines"] = []
            for lid, label, good in LINE_SPEC:
                rec = vals(ls[lid], basis, rng, good)
                rec.update({"id": lid, "label": label})
                L["lines"].append(rec)
            for lid, label, good in (("cash", "Cash & equivalents", "up"), ("working_capital", "Working capital", "up"), ("net_debt", "Net debt", "down")):
                rec = vals(ls[lid], basis, rng, good)
                rec.update({"id": lid, "label": label, "derived": True})
                L["lines"].append(rec)
            ca, cl = ls["current_assets"], ls["current_liabilities"]
            cr_a = safe_div(ca["actual"][as_of], cl["actual"][as_of])
            cr_c = safe_div(ca[basis][as_of], cl[basis][as_of])
            L["lines"].append({"id": "current_ratio", "label": "Current ratio", "kind": "ratio", "derived": True, "good": "up",
                               "balance": r4(cr_a), "comparator": r4(cr_c),
                               "variance": r4((cr_a - cr_c) if is_num(cr_a) and is_num(cr_c) else None),
                               "status": "not_comparable" if not (is_num(cr_a) and is_num(cr_c)) else ("ahead" if cr_a >= cr_c else "behind")})
            L["groups"] = []
            for g in groups:
                rec = vals(ls[g["id"]], basis, rng, good_of.get(g["line"], "neutral"))
                rec.update({"id": g["id"], "label": g["label"], "line": g["line"], "accounts": list(g["accounts"])})
                L["groups"].append(rec)
            L["accounts"] = []
            for a in mapped:
                rec = vals(series[a["id"]], basis, rng, good_of.get(a["l2_bucket"], "neutral"))
                rec.update({"id": a["id"], "line": a["l2_bucket"], "group_ref": group_of[a["id"]]})
                if a.get("rollup"):
                    rec["rollup"] = True
                L["accounts"].append(rec)
            ranked = sorted([x for x in L["accounts"] if is_num(x["variance"])], key=lambda x: -abs(x["variance"]))
            tot = sum(abs(x["variance"]) for x in ranked)
            for r_, x in enumerate(ranked, start=1):
                x["rank"] = r_
                x["share_of_abs_variance"] = r4(safe_div(abs(x["variance"]), tot)) if tot else None
            # balance identity (soft): assets vs liabilities + equity at as-of
            av, lev = ls["assets"]["actual"][as_of], ls["liab_equity"]["actual"][as_of]
            L["identity"] = {"assets": r2(av), "liabilities_and_equity": r2(lev),
                             "gap": r2((av - lev) if is_num(av) and is_num(lev) else None),
                             "balances": is_num(av) and is_num(lev) and abs(av - lev) <= max(0.02, ta * 0.001),
                             "note": "Checked at the as-of month on the extracted accounts; a gap usually means accounts outside the extract (e.g. retained earnings roll-forward), not an error in the mart."}
            lenses[key] = L
    # ---- signals and explanations on the as-of month series
    signals = {a["id"]: signals_for(series[a["id"]], as_of, mon, periods) for a in mapped}
    explanations = _explanations(lenses, mapped, mat)
    qc_notes = []
    if extras:
        qc_notes.append("Component roll-up(s) included in their section (the mart carries them only as roll-up keys): "
                        + "; ".join(f"{a['name']} ({a['id']})" for a in extras) + ".")
    if le_flipped:
        qc_notes.append("Liabilities and equity are stored in credit sign (negative) in the mart; the engine normalised the side to read positive so the sheet foots and status directions keep their meaning. Confirm the storage convention with the view owner.")
    if not has_budget:
        qc_notes.append(budget_reason or "No budget column in the BS extract; budget lenses are unavailable.")
    else:
        qc_notes.append("BS budget uses ENDING_BALANCE_BUDGET, which has no _CONVERTED twin in the view: confirm it is stored in the reporting currency before relying on budget variances.")
    if outside:
        qc_notes.append(f"{outside} BS row(s) fell outside the income-statement period axis and were ignored.")
    if unmapped:
        qc_notes.append(f"{len(unmapped)} BS account(s) have no Assets/Liabilities/Equity L1 and are left out: " + ", ".join(a["name"] for a in unmapped[:6]))
    asof_lens = lenses.get("MTD_py") or {}
    if asof_lens.get("available") and not asof_lens["identity"]["balances"]:
        qc_notes.append(f"Assets do not equal Liabilities + Equity on the extracted accounts [gap {money(asof_lens['identity']['gap'])}]: the extract is a partial balance sheet; totals are 'of extracted accounts'.")
    return {"available": True, "account_keys": n_keys,
            "accounts": [{**a, "series": {b: [r2(v) for v in series[a['id']][b]] for b in ("actual", "py", "budget")}} for a in mapped],
            "unmapped_accounts": [{"id": a["id"], "name": a["name"], "l1": a["l1"]} for a in unmapped],
            "line_series": {k: {b: [r2(v) for v in ls[k][b]] for b in ("actual", "py", "budget")}
                            for k in [x[0] for x in LINE_SPEC] + ["cash", "working_capital", "net_debt"]},
            "groups": groups, "group_of": group_of, "materiality": mat, "net_debt_basis": debt_basis,
            "derived_members": {"cash": cash_accts,
                                "debt": (["-1000"] if "-1000" in rollups else _debt_accounts(mapped))},
            "lenses": lenses, "signals": signals, "explanations": explanations, "qc_notes": qc_notes,
            "semantics_note": "Balances are point-in-time. MTD compares month-end balances; QTD/YTD/LTM compare movements over the window. Positive status follows each line's declared direction (assets up-good, debt down-good)."}


def _explanations(lenses, mapped, mat):
    """Concise registered text per line for every available lens (engine baseline)."""
    by_id = {a["id"]: a for a in mapped}
    out = {}
    for key, L in lenses.items():
        if not L.get("available"):
            continue
        reg_lines = []
        for rec in L["lines"]:
            reg = Register()
            path = f"bs.lenses[{key}].lines[{rec['id']}]"
            if rec.get("kind") == "ratio":
                txt = (f"{rec['label']} is {reg.p(rec['balance'], path + '.balance', dec=0)} against "
                       f"{reg.p(rec['comparator'], path + '.comparator', dec=0)} {L['basis_label']}."
                       if is_num(rec.get("balance")) and is_num(rec.get("comparator")) else f"{rec['label']} is not comparable in this lens.")
            elif L["window"] == "MTD":
                txt = (f"{rec['label']} ends the month at {reg.m(rec['balance'], path + '.balance')} against "
                       f"{reg.m(rec['comparator'], path + '.comparator')} {L['basis_label']}: "
                       f"{reg.m(rec['balance_variance'], path + '.balance_variance', sign=True)}."
                       if is_num(rec.get("balance_variance")) else f"{rec['label']} has no {L['basis_label']} comparison this month.")
            else:
                txt = (f"{rec['label']} moved {reg.m(rec['movement'], path + '.movement', sign=True)} over the window against a "
                       f"{L['basis_label']} movement of {reg.m(rec['comparator_movement'], path + '.comparator_movement', sign=True)}: "
                       f"{reg.m(rec['movement_variance'], path + '.movement_variance', sign=True)}."
                       if is_num(rec.get("movement_variance")) else f"{rec['label']} has no comparable movement in this window.")
            reg_lines.append({"id": rec["id"], "text": txt, "numbers": reg.numbers})
        reg_accts = []
        for rec in L["accounts"]:
            # a "no comparison" sentence informs nobody; quiet accounts render their
            # numbers and badges without prose, which keeps the payload shippable
            if not (is_num(rec.get("balance_variance")) or is_num(rec.get("movement_variance"))):
                continue
            a = by_id[rec["id"]]
            reg = Register()
            path = f"bs.lenses[{key}].accounts[{rec['id']}]"
            name = reg.lit(a["name"])
            if L["window"] == "MTD" and is_num(rec.get("balance_variance")):
                txt = (f"{name} ends at {reg.m(rec['balance'], path + '.balance')} against {reg.m(rec['comparator'], path + '.comparator')} "
                       f"{L['basis_label']}: {reg.m(rec['balance_variance'], path + '.balance_variance', sign=True)}; {rec['tier']} tier.")
            elif is_num(rec.get("movement_variance")):
                txt = (f"{name} moved {reg.m(rec['movement'], path + '.movement', sign=True)} vs a {L['basis_label']} movement of "
                       f"{reg.m(rec['comparator_movement'], path + '.comparator_movement', sign=True)}; {rec['tier']} tier.")
            else:
                txt = f"{name} has no {L['basis_label']} comparison in this window."
            reg_accts.append({"id": rec["id"], "text": txt, "numbers": reg.numbers})
        out[key] = {"lines": reg_lines, "accounts": reg_accts}
    return out
