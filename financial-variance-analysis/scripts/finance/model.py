"""Statement model: sections, profit orientation, drivers (L4 groups), monthly
series, windows, lens values, materiality tiers, the EBITDA bridge and the
planning / operational / coverage layers.

Sign convention. Every internal figure is PROFIT-ORIENTED ("po"): positive adds
to profit. Revenue po = stored revenue; expense po = -(cost). Variance = actual
po - comparator po, so a positive variance is favourable on every line. Display
values show costs as positive numbers (display_sign = -1 on expense sections)
and everything else in profit terms."""
import math

from .common import is_num, add, safe_div, r2, r4, mean, stdev, slug
from .load import NO_SUB

SECTION_ORDER = ["rev", "cos", "opex", "syn", "nonop"]
SECTION_LABEL = {"rev": "Revenue", "cos": "Cost of sales", "opex": "Operating expenses",
                 "syn": "Synergies and strategic investments", "nonop": "Non-operating income (expense)"}
WINDOWS = ["MTD", "QTD", "YTD", "LTM"]
BASES = ["budget", "py"]
BASIS_LABEL = {"budget": "budget", "py": "prior year"}
BRIDGE_TOL = 0.02     # steps are driver movements rounded to the cent, so their sum may sit a cent or two off (validate.TOL)
WINDOW_LABEL = {"MTD": "month", "QTD": "quarter to date", "YTD": "year to date", "LTM": "last twelve months"}
TIERS = ["executive", "management", "monitoring", "immaterial"]
# driver shares of movement are taken within the bridge the driver sits on, so each bridge's shares add up to 100%
SHARE_SCOPES = {"ebitda": ("rev", "cos", "opex"), "below_ebitda": ("syn", "nonop")}


def _norm(s):
    return str(s or "").strip().lower()


def section_of(l2, l3):
    l2n, l3n = _norm(l2), _norm(l3)
    if l3n == "revenue":
        return "rev"
    if l3n in ("cost of sales", "cogs", "cost of goods sold", "cost of revenue"):
        return "cos"
    if l3n in ("opex", "operating expenses", "operating expense") or "opex" in l3n:
        return "opex"
    if "synerg" in l2n:
        return "syn"
    if l2n.startswith("total non-operating") or l3n in ("depreciation", "amortization", "amortisation", "interest", "taxes",
                                                          "income taxes", "other income", "other expense", "other income (expense)"):
        return "nonop"
    return None


def movement(a, c):
    """Driver-consistent movement: actual minus comparator, a missing side counted as absent for that period (not as a
    figure). The basis says which: both sides present, activity with no comparator, or a comparator with no activity.
    A driver's variance is the sum of its accounts' movements, so every ranking and share uses this, never variance."""
    if is_num(a) and is_num(c):
        return a - c, "both"
    if is_num(a):
        return a, "no_comparator"
    if is_num(c):
        return -c, "no_activity"
    return None, None


def _same(a, b):
    """Two hierarchy names that mean the same level (a level that repeats its parent carries no information)."""
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def window_range(periods, i, w):
    s = i
    if w == "MTD":
        return (i, i)
    if w == "QTD":
        while s > 0 and periods[s - 1]["year"] == periods[i]["year"] and periods[s - 1]["quarter"] == periods[i]["quarter"]:
            s -= 1
        return (s, i)
    if w == "YTD":
        while s > 0 and periods[s - 1]["year"] == periods[i]["year"]:
            s -= 1
        return (s, i)
    if w == "LTM":
        return (i - 11, i) if i >= 11 else None
    raise ValueError(w)


def win_sum(series, rng):
    if rng is None:
        return None, 0
    tot, n = None, 0
    for k in range(rng[0], rng[1] + 1):
        v = series[k]
        if is_num(v):
            tot = add(tot, v)
            n += 1
    return tot, n


class Model:
    def __init__(self, frame, expense_sign=None, materiality=None, budget_sign=None):
        self.f = frame
        P = frame.periods
        self.np = len(P)
        self.as_of = frame.as_of
        # ---- sections and sign detection
        for a in frame.accounts:
            a["section"] = section_of(a["l2"], a["l3"])
        self.unmapped = [a for a in frame.accounts if a["section"] is None]
        stored = {}                                    # (acct_idx) -> {actual, py, budget} summed over subsidiaries
        for (p, s, ai), v in frame.cells.items():
            d = stored.setdefault(ai, {"actual": [None] * self.np, "py": [None] * self.np, "budget": [None] * self.np})
            d["actual"][p] = add(d["actual"][p], v[0]); d["py"][p] = add(d["py"][p], v[1]); d["budget"][p] = add(d["budget"][p], v[2])
        # each measure is detected on its own: a budget load can store expenses with the opposite sign to actuals
        def stored_sign(b, secs, upto):
            tot = sum(x for ai, d in stored.items() if frame.accounts[ai]["section"] in secs
                      for p, x in enumerate(d[b]) if is_num(x) and p <= upto)
            return None if tot == 0 else ("negative" if tot < 0 else "positive")
        last = self.np - 1
        det = {b: {"expenses": stored_sign(b, ("cos", "opex"), self.as_of if b != "budget" else last),
                   "revenue": stored_sign(b, ("rev",), self.as_of if b != "budget" else last)} for b in ("actual", "py", "budget")}
        exp_act = expense_sign or det["actual"]["expenses"] or "positive"
        declared = {"actual": expense_sign, "py": expense_sign, "budget": budget_sign}
        by = {}
        for b in ("actual", "py", "budget"):
            e = declared[b] or det[b]["expenses"] or exp_act
            r = det[b]["revenue"] or det["actual"]["revenue"] or "positive"
            by[b] = {"expenses_stored": e, "revenue_stored": r, "expenses_detected": det[b]["expenses"],
                     "source": "declared" if declared[b] else "detected from the data"}
        mism = [b for b in ("py", "budget") if (by[b]["expenses_stored"], by[b]["revenue_stored"]) != (by["actual"]["expenses_stored"], by["actual"]["revenue_stored"])]
        self.sign = {"expenses_stored": by["actual"]["expenses_stored"], "expenses_detected": det["actual"]["expenses"],
                     "revenue_stored": by["actual"]["revenue_stored"],
                     "source": "declared" if expense_sign else "detected from the data (not confirmed by the view owner; open item 9)",
                     "by_measure": by, "mismatch": mism}
        self.profit_sign_by = {b: {"rev": 1.0 if by[b]["revenue_stored"] == "positive" else -1.0,
                                   **{s: (1.0 if by[b]["expenses_stored"] == "negative" else -1.0) for s in ("cos", "opex", "syn", "nonop")}}
                               for b in ("actual", "py", "budget")}
        self.profit_sign = self.profit_sign_by["actual"]
        self.display_sign = {"rev": 1.0, "cos": -1.0, "opex": -1.0, "syn": 1.0, "nonop": 1.0}
        # ---- po series per account (summed over scope) and per account x subsidiary
        self.series = {}
        self.sub_series = {}
        for ai, d in stored.items():
            sec = frame.accounts[ai]["section"]
            if sec is None:
                continue
            self.series[ai] = {b: [None if v is None else v * self.profit_sign_by[b][sec] for v in d[b]] for b in ("actual", "py", "budget")}
        for (p, s, ai), v in frame.cells.items():
            sec = frame.accounts[ai]["section"]
            if sec is None:
                continue
            d = self.sub_series.setdefault((ai, s), {"actual": [None] * self.np, "py": [None] * self.np, "budget": [None] * self.np})
            for b, k in (("actual", 0), ("py", 1), ("budget", 2)):
                d[b][p] = add(d[b][p], None if v[k] is None else v[k] * self.profit_sign_by[b][sec])
        self.mapped = [a for a in frame.accounts if a["section"]]
        # ---- drivers: L4 groups inside a section, else the account itself
        self.drivers, self.driver_of = [], {}
        for sec in SECTION_ORDER:
            groups = {}
            for a in self.mapped:
                if a["section"] != sec:
                    continue
                key = (a["l4"] or "").strip()
                if key:
                    gid = f"d:{sec}:{slug(key)}"
                    g = groups.setdefault(gid, {"id": gid, "label": key, "section": sec, "accounts": [], "level": "L4"})
                else:                                  # no L4: the account (number and name, across subsidiaries) is the driver
                    gid = f"d:{sec}:acct-{slug(a.get('number') or a['name'].split(' (')[0])}"
                    g = groups.setdefault(gid, {"id": gid, "label": a["name"], "section": sec, "accounts": [], "level": "account"})
                g["accounts"].append(a["id"])
                self.driver_of[a["id"]] = gid
            def order(g):
                l = g["label"].lower()
                return (0 if l.startswith("recurring") else 1 if l.startswith("non") else 2, l)
            self.drivers.extend(sorted(groups.values(), key=order))
        # ---- line series (po)
        self.aidx = {a["id"]: i for i, a in enumerate(frame.accounts)}
        # ---- levels below L4: L5 > L6 under each driver; a level that repeats its parent is collapsed (no node)
        self.nodes, self.node_path = {}, {}
        for d in self.drivers:
            for aid in d["accounts"]:
                a = frame.accounts[self.aidx[aid]]
                parent_name, parent_id, path = d["label"], d["id"], []
                for lvl, name in (("L5", a.get("l5")), ("L6", a.get("l6"))):
                    name = (name or "").strip()
                    if not name or _same(name, parent_name):
                        continue
                    nid = f"{parent_id}/{slug(name.replace('+', ' plus'))}"       # Tracking+ must not collide with Tracking
                    k = 2
                    while nid in self.nodes and not _same(self.nodes[nid]["name"], name):
                        nid = f"{parent_id}/{slug(name.replace('+', ' plus'))}-{k}"; k += 1
                    n = self.nodes.setdefault(nid, {"id": nid, "driver": d["id"], "section": d["section"], "level": lvl, "name": name, "parent": parent_id, "accounts": []})
                    n["accounts"].append(aid)
                    path.append(nid)
                    parent_name, parent_id = name, nid
                self.node_path[aid] = path
        self.dby = {}                                  # account id -> [(period, subsidiary idx, class, department, [mtd, py, bud])]
        for (p, ai, si, cls, dept), v in frame.dcells.items():
            if frame.accounts[ai]["section"] is not None:
                self.dby.setdefault(frame.accounts[ai]["id"], []).append((p, si, cls, dept, v))
        self.line_series = {}
        for sec in SECTION_ORDER:
            self.line_series[sec] = self._sum_series([self.series[self.aidx[a["id"]]] for a in self.mapped if a["section"] == sec])
        for did in [d["id"] for d in self.drivers]:
            d = self.driver(did)
            self.line_series[did] = self._sum_series([self.series[self.aidx[x]] for x in d["accounts"]])
        L = self.line_series
        L["gp"] = self._sum_series([L["rev"], L["cos"]])
        L["ebitda"] = self._sum_series([L["gp"], L["opex"]])
        L["ni"] = self._sum_series([L["ebitda"], L["syn"], L["nonop"]])
        # ---- materiality
        self.materiality = self._materiality(materiality)

    # ------------------------------------------------ governed reconciliation
    def governed_check(self, governed, tol=1.0, excluded=()):
        """Compare the extract with the view's governed roll-ups, month x subsidiary, for every month up to the as-of
        month: REVENUE_MTD, ADJUSTED_EBITDA_MTD and NET_INCOME_MTD within `tol`. Returns (checked, mismatches)."""
        from .common import to_date
        P = self.f.periods
        pidx = {p["start"]: i for i, p in enumerate(P)}
        mine = {}
        for (p, s, ai), v in self.f.cells.items():
            sec = self.f.accounts[ai]["section"]
            if sec is None or v[0] is None or p > self.as_of:
                continue
            po = v[0] * self.profit_sign_by["actual"][sec]
            o = mine.setdefault((p, self.f.subs[s]), {"REVENUE_MTD": 0.0, "ADJUSTED_EBITDA_MTD": 0.0, "NET_INCOME_MTD": 0.0})
            if sec == "rev":
                o["REVENUE_MTD"] += po
            if sec in ("rev", "cos", "opex"):
                o["ADJUSTED_EBITDA_MTD"] += po
            o["NET_INCOME_MTD"] += po
        excl = {e.strip().lower() for e in excluded}
        scope_sub = self.f.scope_subsidiary
        checked, bad, seen = 0, [], set()
        for g in governed:
            sub = str(g.get("SUBSIDIARY_NAME") or NO_SUB)
            if sub.strip().lower() in excl or (scope_sub and sub != scope_sub):
                continue
            start = to_date(g["PERIOD_START_DATE"]).replace(day=1).isoformat()
            p = pidx.get(start)
            if p is None or p > self.as_of:
                continue
            seen.add((p, sub))
            m = mine.get((p, sub), {})
            for k in ("REVENUE_MTD", "ADJUSTED_EBITDA_MTD", "NET_INCOME_MTD"):
                gv = g.get(k)
                gv = float(gv) if gv not in (None, "") else 0.0
                ev = m.get(k, 0.0)
                checked += 1
                if abs(gv - ev) > tol:
                    bad.append({"month": P[p]["label"], "subsidiary": sub, "metric": k, "governed": r2(gv), "extract": r2(ev), "difference": r2(gv - ev)})
        for (p, sub), m in mine.items():                      # activity in the extract with no governed row
            if (p, sub) not in seen and any(abs(x) > tol for x in m.values()):
                bad.append({"month": P[p]["label"], "subsidiary": sub, "metric": "all", "governed": None, "extract": r2(m["ADJUSTED_EBITDA_MTD"]), "difference": None})
        return checked, bad

    # ------------------------------------------------------------ helpers
    def driver(self, did):
        return next(d for d in self.drivers if d["id"] == did)

    def _sum_series(self, items):
        out = {b: [None] * self.np for b in ("actual", "py", "budget")}
        for s in items:
            for b in ("actual", "py", "budget"):
                for p in range(self.np):
                    out[b][p] = add(out[b][p], s[b][p])
        return out

    PCT = {"executive": 2.5, "management": 1.25, "monitoring": 0.35}      # % of the window's revenue (an average month x months)

    def _materiality(self, override):
        """Size thresholds scale with the window: a share of an average month's revenue times the months in the window,
        so a 'large' month move and a 'large' year move are the same share of what the window sells. The MTD set
        also sits at the top level for the monthly signal tests."""
        rng = window_range(self.f.periods, self.as_of, "LTM")
        rev, n = win_sum(self.line_series["rev"]["actual"], rng if rng else (0, self.as_of))
        if not rng:
            n = self.as_of + 1
            rev = (rev or 0.0) * 12.0 / max(1, n)
            basis = f"revenue annualised from {n} month(s)"
        else:
            basis = "LTM revenue"
        rev = abs(rev or 0.0)
        avg = rev / 12.0
        pct = dict(self.PCT)
        mtd = {k: max(round(avg * pct[k] / 100.0, -2), 100.0) for k in ("executive", "management", "monitoring")}
        source = "defaults scaled to revenue"
        if override:
            for k in ("executive", "management", "monitoring"):
                if override.get(f"{k}_abs") is not None:
                    mtd[k] = float(override[f"{k}_abs"])
                    pct[k] = r4(100.0 * mtd[k] / avg) if avg else None
            source = "analyst-declared"
        mgmt_pct = float(override["management_pct"]) if override and override.get("management_pct") is not None else 5.0
        by = {}
        for w in WINDOWS:
            r = window_range(self.f.periods, self.as_of, w)
            months = (r[1] - r[0] + 1) if r else 12
            by[w] = {"window": w, "months": months, "management_pct": mgmt_pct,
                     **{f"{k}_abs": max(round(mtd[k] * months, -2), 100.0) for k in ("executive", "management", "monitoring")}}
        m = {**{k: v for k, v in by["MTD"].items() if k.endswith("_abs")}, "management_pct": mgmt_pct, "pct_of_window_revenue": pct,
             "basis": basis, "annual_revenue_basis": r2(rev), "average_month_revenue": r2(avg), "source": source, "by_window": by,
             "rule": "a share of an average month's revenue times the months in the window; the management tier also needs 5% of the comparator"}
        return m

    def tier(self, variance, variance_pct, window="MTD"):
        m = self.materiality["by_window"][window]
        if not is_num(variance):
            return "immaterial"
        v = abs(variance)
        if v >= m["executive_abs"]:
            return "executive"
        if v >= m["management_abs"] and (variance_pct is None or abs(variance_pct) * 100 >= m["management_pct"]):
            return "management"
        if v >= m["monitoring_abs"]:
            return "monitoring"
        return "immaterial"

    # ------------------------------------------------------------- lenses
    def lens(self, window, basis):
        """Values for one window x comparator at the as-of period."""
        P = self.f.periods
        rng = window_range(P, self.as_of, window)
        key = f"{window}_{basis}"
        out = {"id": key, "window": window, "basis": basis, "basis_label": BASIS_LABEL[basis], "window_label": WINDOW_LABEL[window],
               "available": rng is not None, "range": None, "months": 0}
        if rng is None:
            out["reason"] = "LTM needs twelve months of history up to the as-of period."
            return out
        out["range"] = {"start_idx": rng[0], "end_idx": rng[1], "start": P[rng[0]]["start"], "end": P[rng[1]]["end"],
                        "label": f"{window} to {P[rng[1]]['label']}" if window != "MTD" else P[rng[1]]["label"]}
        out["months"] = rng[1] - rng[0] + 1
        out["materiality"] = self.materiality["by_window"][window]

        def vals(series, dsign, kind="amt"):
            a, na = win_sum(series["actual"], rng)
            c, nc = win_sum(series[basis], rng)
            v = (a - c) if is_num(a) and is_num(c) else None
            mv, mb = movement(a, c)
            flip = is_num(a) and is_num(c) and a * c < 0            # a credit became an expense (or the reverse): a % is meaningless
            return {"actual": r2(None if a is None else a * dsign), "comparator": r2(None if c is None else c * dsign),
                    "actual_po": r2(a), "comparator_po": r2(c), "variance": r2(v),
                    "variance_pct": r4(safe_div(v, abs(c)) if is_num(c) and c != 0 and not flip else None) if v is not None else None,
                    "sign_flip": flip, "movement": r2(mv), "movement_basis": mb,
                    "months_with_actual": na, "months_with_comparator": nc, "display_sign": dsign}

        rev = vals(self.line_series["rev"], 1.0)
        lines = {}
        for lid, dsign in (("rev", 1.0), ("cos", -1.0), ("gp", 1.0), ("opex", -1.0), ("ebitda", 1.0), ("syn", 1.0), ("nonop", 1.0), ("ni", 1.0)):
            lines[lid] = vals(self.line_series[lid], dsign)
            lines[lid]["id"] = lid
            lines[lid]["pct_of_revenue"] = r4(safe_div(lines[lid]["actual_po"], rev["actual_po"]))
            lines[lid]["pct_of_revenue_comparator"] = r4(safe_div(lines[lid]["comparator_po"], rev["comparator_po"]))
        for mid, num in (("gpm", "gp"), ("ebm", "ebitda"), ("nim", "ni")):
            ma, mc = safe_div(lines[num]["actual_po"], rev["actual_po"]), safe_div(lines[num]["comparator_po"], rev["comparator_po"])
            lines[mid] = {"id": mid, "kind": "ratio", "actual": r4(ma), "comparator": r4(mc),
                          "variance": r4((ma - mc) if is_num(ma) and is_num(mc) else None)}
        out["lines"] = [lines[k] for k in ("rev", "cos", "gp", "gpm", "opex", "ebitda", "ebm", "syn", "nonop", "ni", "nim")]
        cv = [lines[k]["variance"] for k in ("cos", "opex")]
        out["totals"] = {"cost_variance": r2(sum(cv)) if all(is_num(x) for x in cv) else None,
                         "below_line_variance": r2(lines["ni"]["variance"] - lines["ebitda"]["variance"]) if is_num(lines["ni"]["variance"]) and is_num(lines["ebitda"]["variance"]) else None}
        # accounts
        accts = []
        for a in self.mapped:
            v = vals(self.series[self.aidx[a["id"]]], self.display_sign[a["section"]])
            v.update({"id": a["id"], "section": a["section"], "driver_ref": self.driver_of[a["id"]],
                      "pct_of_revenue": r4(safe_div(abs(v["actual_po"]) if is_num(v["actual_po"]) else None, rev["actual_po"])),
                      "budget_status": "no_comparator" if not is_num(v["comparator_po"]) or (basis == "budget" and v["months_with_comparator"] == 0) else "comparable"})
            v["tier"] = self.tier(v["variance"], v["variance_pct"], window)
            v["movement_tier"] = self.tier(v["movement"], None, window)
            accts.append(v)
        # rank and share on movement: a one-sided account (new or stopped) moves the driver as much as a two-sided one
        tot_abs = sum(abs(x["movement"]) for x in accts if is_num(x["movement"]))
        ranked = sorted([x for x in accts if is_num(x["movement"]) and x["movement"] != 0], key=lambda x: (-abs(x["movement"]), x["id"]))
        for r, x in enumerate(ranked, start=1):
            x["rank"] = r
            x["share_of_abs_variance"] = r4(safe_div(abs(x["movement"]), tot_abs)) if tot_abs else None
        out["accounts"] = accts
        # drivers
        drv = []
        for d in self.drivers:
            v = vals(self.line_series[d["id"]], self.display_sign[d["section"]])
            v.update({"id": d["id"], "label": d["label"], "section": d["section"], "accounts": list(d["accounts"]), "level": d["level"]})
            v["tier"] = self.tier(v["variance"], v["variance_pct"], window)
            v["pct_of_revenue"] = r4(safe_div(abs(v["actual_po"]) if is_num(v["actual_po"]) else None, rev["actual_po"]))
            v["movement_tier"] = self.tier(v["movement"], None, window)
            mine = [x for x in accts if x["driver_ref"] == d["id"] and is_num(x["movement"])]
            v["one_sided_movement"] = r2(sum(x["movement"] for x in mine if x["movement_basis"] != "both"))
            v["two_sided_movement"] = r2(sum(x["movement"] for x in mine if x["movement_basis"] == "both"))
            drv.append(v)
        for r, x in enumerate(sorted([x for x in drv if is_num(x["movement"]) and x["movement"] != 0], key=lambda x: (-abs(x["movement"]), x["id"])), start=1):
            x["rank"] = r
        # a driver's share is of the bridge it sits on: operating drivers (the Adjusted EBITDA bridge) add up to 100%,
        # and the synergy / non-operating drivers (the steps to net income) add up to 100% on their own
        for scope, secs in SHARE_SCOPES.items():
            mine = [x for x in drv if x["section"] in secs]
            dtot = sum(abs(x["movement"]) for x in mine if is_num(x["movement"]))
            for x in mine:
                x["share_scope"] = scope
                if is_num(x["movement"]) and x["movement"] != 0:
                    x["share_of_abs_variance"] = r4(safe_div(abs(x["movement"]), dtot)) if dtot else None
        out["drivers"] = drv
        # facts: account x subsidiary (display actual / comparator, oriented variance)
        facts = []
        for (ai, si), s in sorted(self.sub_series.items()):
            a = self.f.accounts[ai]
            ds = self.display_sign[a["section"]]
            av, _ = win_sum(s["actual"], rng); cv, _ = win_sum(s[basis], rng)
            facts.append([a["id"], self.f.subs[si], r2(None if av is None else av * ds), r2(None if cv is None else cv * ds),
                          r2((av - cv) if is_num(av) and is_num(cv) else None)])
        out["facts"] = {"columns": ["account", "subsidiary", "actual", "comparator", "variance"], "rows": facts}
        # kpis
        out["kpis"] = self._kpis(lines, window)
        out["bridge"] = self._bridge(lines, drv, accts)
        out["concentration"] = self._concentration(accts, drv)
        out["reconciliation"] = self._reconciliation(drv, accts, rng, basis)
        out["hierarchy"], out["product_lines"] = self._hierarchy(drv, rng, basis, vals, lines["rev"])
        out["splits"] = self._account_splits(accts, rng, basis)
        # every account by subsidiary, profit-oriented (contribution to net income)
        out["by_subsidiary"] = self._split(self._dim_sums(rng, basis, [a["id"] for a in accts], "subsidiary"), 1.0, basis, "subsidiary", top=25)
        return out

    # ------------------------------------------------------ levels below L4
    def _hierarchy(self, drv, rng, basis, vals, rev_line):
        """Per driver, the L5 nodes with their L6 children, each valued like a driver over the window. A node with no
        activity in the window (no actual and no comparator) is left out, never zero-filled; the ones kept still foot to
        the driver because the missing ones are zero. Product lines: the deepest revenue nodes, footing to revenue."""
        out, lines = {}, []
        by_parent = {}
        for n in self.nodes.values():
            by_parent.setdefault(n["parent"], []).append(n)

        def build(n, dsign):
            v = vals(self._sum_series([self.series[self.aidx[x]] for x in n["accounts"]]), dsign)
            active = (is_num(v["actual_po"]) and abs(v["actual_po"]) >= 0.005) or (is_num(v["comparator_po"]) and abs(v["comparator_po"]) >= 0.005)
            kids = [c for c in (build(k, dsign) for k in sorted(by_parent.get(n["id"], []), key=lambda k: k["name"])) if c]
            if not active and not kids:
                return None
            rec = {"id": n["id"], "level": n["level"], "name": n["name"], "parent": n["parent"], "accounts": list(n["accounts"]),
                   **{k: v[k] for k in ("actual", "comparator", "actual_po", "comparator_po", "variance", "variance_pct", "movement", "movement_basis", "display_sign")},
                   "children": kids}
            return rec

        for d in drv:
            top = [c for c in (build(n, self.display_sign[d["section"]]) for n in sorted(by_parent.get(d["id"], []), key=lambda k: k["name"])) if c]
            if not top:
                continue
            levels = sorted({x["level"] for x in top} | {c["level"] for x in top for c in x["children"]})
            tot = sum(x["movement"] or 0.0 for x in top)
            for x in top:
                x["share_of_driver"] = r4(safe_div(abs(x["movement"] or 0.0), sum(abs(y["movement"] or 0.0) for y in top))) if any(is_num(y["movement"]) for y in top) else None
            top.sort(key=lambda x: (-abs(x["movement"] or 0.0), x["name"]))
            out[d["id"]] = {"driver": d["id"], "levels": levels, "nodes": top,
                            "total": {"actual_po": d["actual_po"], "comparator_po": d["comparator_po"], "movement": d["movement"], "movement_basis": d["movement_basis"]},
                            "unsplit_accounts": [a for a in d["accounts"] if not self.node_path.get(a)]}
            if d["section"] == "rev":
                def leaves(x):
                    return [y for c in x["children"] for y in leaves(c)] if x["children"] else [x]
                for x in top:
                    for leaf in leaves(x):
                        lines.append({"id": leaf["id"], "name": leaf["name"], "level": leaf["level"], "driver": d["id"], "driver_label": d["label"],
                                      **{k: leaf[k] for k in ("actual", "comparator", "actual_po", "comparator_po", "variance", "variance_pct", "movement", "movement_basis")}})
                rest = [a for a in d["accounts"] if not self.node_path.get(a)]
                if rest:
                    v = vals(self._sum_series([self.series[self.aidx[x]] for x in rest]), 1.0)
                    if (is_num(v["actual_po"]) and abs(v["actual_po"]) >= 0.005) or (is_num(v["comparator_po"]) and abs(v["comparator_po"]) >= 0.005):
                        lines.append({"id": d["id"] + "/unsplit", "name": f"{d['label']} (no product line)", "level": "L4", "driver": d["id"], "driver_label": d["label"],
                                      **{k: v[k] for k in ("actual", "comparator", "actual_po", "comparator_po", "variance", "variance_pct", "movement", "movement_basis")}})
        pl = None
        if lines:
            tot_abs = sum(abs(x["movement"] or 0.0) for x in lines)
            for x in lines:
                x["share_of_revenue"] = r4(safe_div(x["actual_po"], rev_line["actual_po"])) if is_num(x["actual_po"]) else None
                x["share_of_movement"] = r4(safe_div(abs(x["movement"] or 0.0), tot_abs)) if tot_abs else None
            lines.sort(key=lambda x: (-(x["actual_po"] or 0.0), x["name"]))
            pl = {"level": "L6" if any(x["level"] == "L6" for x in lines) else "L5", "items": lines,
                  "total": {"actual_po": rev_line["actual_po"], "comparator_po": rev_line["comparator_po"], "movement": rev_line["movement"], "movement_basis": rev_line["movement_basis"]},
                  "basis": "the deepest revenue sub-groups of the view (product lines), footing to revenue; nodes with no activity in the window are left out"}
        return out, pl

    # ------------------------------------------------------ drill detail
    def _dim_sums(self, rng, basis, acct_ids, dim, dept=None):
        """Window sums (profit-oriented) of actual and comparator per member of one drill dimension ('department',
        'class', 'subsidiary' or 'account') over the given accounts; `dept` restricts to one department."""
        out = {}
        ci = {"budget": 2, "py": 1}[basis]
        for aid in acct_ids:
            sec = self.f.accounts[self.aidx[aid]]["section"]
            sa, sc = self.profit_sign_by["actual"][sec], self.profit_sign_by[basis][sec]
            for p, si, cls, dp, v in self.dby.get(aid, ()):
                if p < rng[0] or p > rng[1] or (dept is not None and dp != dept):
                    continue
                key = {"department": dp, "class": cls, "subsidiary": self.f.subs[si], "account": aid}[dim]
                o = out.setdefault(key, [None, None])
                if v[0] is not None:
                    o[0] = add(o[0], v[0] * sa)
                if v[ci] is not None:
                    o[1] = add(o[1], v[ci] * sc)
        return out

    def _split(self, sums, dsign, basis, dim, top=8, min_members=1):
        """One reconciling drill table. Prior year is actuals at every level, and accounts are the base unit, so those
        splits always compare. A budget split by subsidiary, class or department compares only when every member with
        activity also carries a budget; otherwise the budget is held at a coarser grain, rows show actuals with 'no
        comparator at this level' and the table foots on the actual rather than inventing member variances. Members
        with no movement are left out and counted (zero_count); the table still foots."""
        rows = [(k, a, c) for k, (a, c) in sums.items() if (is_num(a) and a != 0) or (is_num(c) and c != 0)]
        with_act = {k for k, a, c in rows if is_num(a) and a != 0}
        with_cmp = {k for k, a, c in rows if is_num(c) and c != 0}
        comparable = basis == "py" or dim == "account" or not with_cmp or with_act <= with_cmp
        zero, every = 0, rows                   # totals come from every member; dropped rows move by zero
        tiny = []
        if comparable:                          # exact zeros are left out and counted; cents-level moves go to the remainder
            mvs = [(x, abs(movement(x[1], x[2])[0] or 0)) for x in rows]
            keep, tiny = [x for x, m in mvs if m >= 0.5], [x for x, m in mvs if 0.005 <= m < 0.5]
            zero, rows = len(mvs) - len(keep) - len(tiny), keep
        if len(rows) < min_members:
            return None
        recs = []
        for k, a, c in rows:
            mv, mb = movement(a, c)
            recs.append({"name": k, "actual": r2(None if a is None else a * dsign), "comparator": r2(None if c is None else c * dsign),
                         "movement": r2(mv) if comparable else None, "movement_basis": mb if comparable else "no_comparator_at_level",
                         "_rank": abs(mv if comparable else (a or 0))})
        recs.sort(key=lambda x: (-x["_rank"], x["name"]))
        for x in recs:
            del x["_rank"]
        shown, rest = recs[:top], recs[top:]
        for k, a, c in tiny:
            mv, mb = movement(a, c)
            rest.append({"name": k, "actual": r2(None if a is None else a * dsign), "comparator": r2(None if c is None else c * dsign), "movement": r2(mv), "movement_basis": mb})
        tot_a = sum(a for _, a, _ in every if is_num(a)) if any(is_num(a) for _, a, _ in every) else None
        tot_c = sum(c for _, _, c in every if is_num(c)) if any(is_num(c) for _, _, c in every) else None
        tot_mv, tot_b = movement(tot_a, tot_c)
        other = None
        if rest:
            if not comparable:
                rest.sort(key=lambda x: (-abs(x["actual"] or 0), x["name"]))
            other = {"count": len(rest), "actual": r2(sum(x["actual"] or 0 for x in rest)),
                     "movement": r2(sum(x["movement"] or 0 for x in rest)) if comparable else None,
                     "items": [dict(x, movement=x["movement"] if comparable else None) for x in rest]}     # what the remainder holds, for the expandable row
        return {"comparable": comparable, "foots_on": "movement" if comparable else "actual", "rows": shown, "other": other, "zero_count": zero,
                "total": {"actual": r2(None if tot_a is None else tot_a * dsign), "comparator": r2(None if tot_c is None else tot_c * dsign),
                          "movement": r2(tot_mv), "movement_basis": tot_b}}

    def _reconciliation(self, drv, accts, rng, basis, top=8):
        """Per driver: the accounts' movements (top N, the remainder, the total = driver movement), and the top-down
        Department > Account split of the same total. Validated to the cent; the renderer only displays it."""
        by_acct = {a["id"]: a for a in accts}
        out = {}
        for d in drv:
            moved = [by_acct[x] for x in d["accounts"] if is_num(by_acct[x]["movement"]) and by_acct[x]["movement"] != 0]
            items = sorted([a for a in moved if abs(a["movement"]) >= 0.5], key=lambda a: (-abs(a["movement"]), a["id"]))
            if not items and not is_num(d["movement"]):
                continue
            shown, rest = items[:top], items[top:] + [a for a in moved if abs(a["movement"]) < 0.5]   # cents-level moves join the remainder
            rec = {"driver": d["id"], "total": d["movement"], "total_basis": d["movement_basis"],
                   "items": [{"account": a["id"], "movement": a["movement"], "movement_basis": a["movement_basis"]} for a in shown],
                   "other": {"count": len(rest), "movement": r2(sum(a["movement"] for a in rest)),
                             "items": [{"account": a["id"], "movement": a["movement"], "movement_basis": a["movement_basis"]} for a in rest]} if rest else None,
                   "start": d["comparator_po"], "end": d["actual_po"],
                   "zero_count": len(d["accounts"]) - len(moved)}       # accounts in the driver that did not move in this view
            ds = self.display_sign[d["section"]]
            # by subsidiary: compares only where the budget is held by subsidiary (always against prior year)
            rec["by_subsidiary"] = self._split(self._dim_sums(rng, basis, d["accounts"], "subsidiary"), ds, basis, "subsidiary", top=25)
            if self.f.has_department:
                sp = self._split(self._dim_sums(rng, basis, d["accounts"], "department"), ds, basis, "department", top=top)
                if sp:
                    for row in sp["rows"]:
                        acc = self._split(self._dim_sums(rng, basis, d["accounts"], "account", dept=row["name"]), ds, basis, "account", top=3)
                        row["accounts"] = acc["rows"] if acc else []
                        row["accounts_other"] = acc["other"] if acc else None
                        row["accounts_comparable"] = acc["comparable"] if acc else None
                        row["accounts_zero"] = acc["zero_count"] if acc else 0
                    rec["by_department"] = sp
            out[d["id"]] = rec
        return out

    def _account_splits(self, accts, rng, basis):
        """Per account with more than one member in a dimension: the subsidiary, class and department split of the
        window (actuals always; movement only where the comparator is held at that level)."""
        out = {}
        for a in accts:
            if not (is_num(a["movement"]) or is_num(a["actual_po"])):
                continue
            ds = a["display_sign"]
            rec = {}
            for dim, flag in (("subsidiary", True), ("class", self.f.has_class), ("department", self.f.has_department)):
                if not flag:
                    continue
                sp = self._split(self._dim_sums(rng, basis, [a["id"]], dim), ds, basis, dim, top=10, min_members=2)
                if sp:
                    rec[dim] = sp
            if rec:
                out[a["id"]] = rec
        return out

    def _kpis(self, lines, window="MTD"):
        mon = self.materiality["by_window"][window]["monitoring_abs"]
        def status(v):
            if not is_num(v):
                return "not_comparable"
            return "in_line" if abs(v) < mon else ("ahead" if v > 0 else "behind")
        def k(id_, label, line, margin=None, cost=False):
            L = lines[line]
            d = {"id": id_, "label": label, "line": line, "actual": L["actual"], "comparator": L["comparator"], "variance": L["variance"],
                 "variance_pct": L["variance_pct"], "status": status(L["variance"]), "is_cost": cost}
            if margin:
                M = lines[margin]
                d.update({"margin_actual": M["actual"], "margin_comparator": M["comparator"], "margin_bps": M["variance"]})
            return d
        return [k("revenue", "Revenue", "rev"), k("gross_profit", "Gross profit", "gp", "gpm"), k("ebitda", "Adjusted EBITDA", "ebitda", "ebm"),
                k("opex", "Operating expenses", "opex", cost=True), k("net_income", "Net income", "ni", "nim"),
                k("cogs", "Cost of sales", "cos", cost=True), k("nonop", "Non-operating income (expense)", "nonop")]

    def _bridge(self, lines, drv, accts):
        by_acct = {a["id"]: a for a in accts}
        def steps_for(sections):
            # steps on movement: a driver active in only one period (no comparator at all) still moves EBITDA
            steps = []
            for d in drv:
                if d["section"] not in sections or not is_num(d["movement"]) or d["movement"] == 0:
                    continue
                contribs = []
                for aid in d["accounts"]:
                    a = by_acct[aid]
                    if is_num(a["movement"]) and a["movement"] != 0:
                        contribs.append({"account": aid, "amount": a["movement"], "movement_basis": a["movement_basis"],
                                         "share_of_step": r4(safe_div(a["movement"], d["movement"]))})
                contribs.sort(key=lambda c: -abs(c["amount"]))
                steps.append({"id": d["id"], "label": d["label"], "section": d["section"], "value": d["movement"], "movement_basis": d["movement_basis"],
                              "kind": "fav" if d["movement"] >= 0 else "unf", "tier": d["tier"], "contributions": contribs})
            return steps
        start, end = lines["ebitda"]["comparator_po"], lines["ebitda"]["actual_po"]
        steps = steps_for(("rev", "cos", "opex"))
        resid = r2((end - start - sum(s["value"] for s in steps)) if is_num(start) and is_num(end) else None)
        ni_steps = steps_for(("syn", "nonop"))
        ni_start, ni_end = lines["ebitda"]["actual_po"], lines["ni"]["actual_po"]
        ni_resid = r2((lines["ni"]["actual_po"] - lines["ni"]["comparator_po"] - (end - start) - sum(s["value"] for s in ni_steps))
                      if is_num(start) and is_num(end) and is_num(lines["ni"]["actual_po"]) and is_num(lines["ni"]["comparator_po"]) else None)
        return {"start": {"label": "Comparator Adjusted EBITDA", "value": r2(start)}, "end": {"label": "Actual Adjusted EBITDA", "value": r2(end)},
                "steps": steps, "control": {"residual": resid, "reconciles": resid is not None and abs(resid) <= BRIDGE_TOL},
                "to_net_income": {"start": {"label": "Adjusted EBITDA variance", "value": r2((end - start) if is_num(start) and is_num(end) else None)},
                                  "steps": ni_steps, "end": {"label": "Net income variance", "value": lines["ni"]["variance"]},
                                  "control": {"residual": ni_resid, "reconciles": ni_resid is not None and abs(ni_resid) <= BRIDGE_TOL}}}

    def _concentration(self, accts, drv):
        ranked = [x for x in sorted(accts, key=lambda x: (-abs(x["movement"] or 0), x["id"])) if is_num(x["movement"]) and x["movement"] != 0]
        tot = sum(abs(x["movement"]) for x in ranked)
        top3 = ranked[:3]
        mat = [x for x in accts if x["tier"] in ("executive", "management") or (not is_num(x["variance"]) and x["movement_tier"] in ("executive", "management"))]
        return {"top3_share": r4(safe_div(sum(abs(x["movement"]) for x in top3), tot)) if tot else None,
                "top3_accounts": [x["id"] for x in top3], "accounts_total": len(accts), "accounts_with_variance": len(ranked),
                "one_sided_accounts": len([x for x in ranked if x["movement_basis"] != "both"]),
                "one_sided_movement": r2(sum(x["movement"] for x in ranked if x["movement_basis"] != "both")),
                "two_sided_movement": r2(sum(x["movement"] for x in ranked if x["movement_basis"] == "both")),
                "material_accounts": len(mat), "adverse_accounts": len([x for x in ranked if x["movement"] < 0]),
                "favourable_accounts": len([x for x in ranked if x["movement"] > 0]),
                "material_drivers": len([d for d in drv if d["tier"] in ("executive", "management")]),
                "abs_variance_total": r2(tot)}

    # ------------------------------------------------------------- layers
    def layers(self, lens, signals):
        """MTD vs budget only: variance = planning (trailing mean - budget) + operational
        (actual - trailing mean) + coverage (unbudgeted actual) + unsplit (no eligible run-rate)."""
        if lens["window"] != "MTD" or lens["basis"] != "budget":
            return {"state": "not_calculated", "reason": "The run-rate split applies to a single month against budget: planning = run-rate reference minus budget, operational = month minus the reference (trailing six-month trend extended one month)."}
        per_acct, per_driver = [], {}
        tot = {"planning": 0.0, "operational": 0.0, "coverage": 0.0, "unsplit": 0.0, "reported": 0.0}
        for a in lens["accounts"]:
            sg = signals[a["id"]]
            rr = sg["runrate"]
            rec = {"id": a["id"], "driver_ref": a["driver_ref"], "reported": a["variance"], "planning": None, "operational": None, "coverage": None, "unsplit": None, "basis": None}
            if not is_num(a["comparator_po"]) or a["budget_status"] == "no_comparator":
                rec["coverage"] = a["actual_po"]; rec["basis"] = "no budget line: the whole actual is coverage, not performance"
                tot["coverage"] += a["actual_po"] or 0.0
            elif not is_num(a["variance"]):
                rec["basis"] = "no actual"
            elif rr["eligible"]:
                m = rr["reference"]
                rec["planning"] = r2(m - a["comparator_po"]); rec["operational"] = r2(a["actual_po"] - m)
                rec["basis"] = f"run-rate reference {r2(m)} ({rr['reference_basis']})"
                tot["planning"] += rec["planning"]; tot["operational"] += rec["operational"]
            else:
                rec["unsplit"] = a["variance"]; rec["basis"] = rr["reason"]
                tot["unsplit"] += a["variance"]
            if is_num(a["variance"]):
                tot["reported"] += a["variance"]
            per_acct.append(rec)
            d = per_driver.setdefault(a["driver_ref"], {"id": a["driver_ref"], "planning": 0.0, "operational": 0.0, "coverage": 0.0, "unsplit": 0.0, "reported": 0.0})
            for k in ("planning", "operational", "coverage", "unsplit", "reported"):
                if is_num(rec[k]):
                    d[k] += rec[k]
        for d in per_driver.values():
            for k in list(d.keys()):
                if k != "id":
                    d[k] = r2(d[k])
        tot = {k: r2(v) for k, v in tot.items()}
        resid = r2(tot["reported"] - (tot["planning"] + tot["operational"] + tot["unsplit"]) - 0.0)
        # coverage is activity outside the reported variance (unbudgeted accounts carry no variance), so the control is on budgeted accounts
        gross = abs(tot["planning"]) + abs(tot["operational"]) + abs(tot["unsplit"])
        shares = {k: r4(safe_div(abs(tot[k]), gross)) if gross else None for k in ("planning", "operational", "unsplit")}
        primary = "mixed"
        for k in ("planning", "operational"):
            if shares[k] is not None and shares[k] >= 0.6 and (tot[k] >= 0) == (tot["reported"] >= 0):
                primary = k
        return {"state": "calculated", "totals": tot, "shares_of_gross": shares, "primary_layer": primary,
                "control": {"residual": resid, "reconciles": abs(resid) < 0.01,
                            "identity": "reported = planning + operational + unsplit (budgeted accounts); coverage is unbudgeted activity shown beside it"},
                "accounts": per_acct, "drivers": list(per_driver.values()),
                "definitions": {"planning": "run-rate reference minus budget: how far the budget sits from recent activity (budget realism, not execution); the reference is the trailing six-month trend extended one month",
                                "operational": "month minus run-rate reference: how far the month moved from its own recent level (not proven controllable)",
                                "coverage": "actual on accounts with no budget line: comparability, not performance",
                                "unsplit": "variance on budgeted accounts with fewer than three trailing months, kept whole"}}

    # ------------------------------------------------------ monthly series
    def budget_check(self, months=6, lo=0.5, hi=2.0):
        """Is the budget usable as a comparator? Per section, the budget's size against actuals over the last
        `months` closed months that carry both. A budget under half or over twice the actuals (or of the opposite
        sign) is not meaningful for variance work: an incomplete load, a missing account family or a broken sign."""
        out = {}
        for sec in ("rev", "cos", "opex"):
            s = self.line_series.get(sec)
            if not s:
                continue
            ks = [k for k in range(max(0, self.as_of - months + 1), self.as_of + 1) if is_num(s["actual"][k]) and is_num(s["budget"][k])]
            if not ks:
                out[sec] = {"label": SECTION_LABEL[sec], "months": 0, "actual": None, "budget": None, "ratio": None, "ok": None}
                continue
            a, b = sum(s["actual"][k] for k in ks), sum(s["budget"][k] for k in ks)
            ratio = safe_div(b, a)
            out[sec] = {"label": SECTION_LABEL[sec], "months": len(ks), "actual": r2(a), "budget": r2(b), "ratio": r4(ratio),
                        "ok": bool(is_num(ratio) and lo <= ratio <= hi)}
        failed = [v["label"] for v in out.values() if v["ok"] is False]
        return {"sections": out, "reliable": not failed, "failed": failed, "rule": f"budget within {lo:g}x-{hi:g}x of actuals over the last {months} closed months, same sign"}

    def series_block(self):
        """Monthly series for the statement lines (po and display), with YoY and margins computed here so the renderer draws only."""
        P = self.f.periods
        out = []
        rev = self.line_series["rev"]
        for lid, label, ds in (("rev", "Revenue", 1.0), ("cos", "Cost of sales", -1.0), ("gp", "Gross profit", 1.0), ("opex", "Operating expenses", -1.0),
                               ("ebitda", "Adjusted EBITDA", 1.0), ("syn", "Synergies and strategic investments", 1.0),
                               ("nonop", "Non-operating income (expense)", 1.0), ("ni", "Net income", 1.0)):
            s = self.line_series[lid]
            rec = {"id": lid, "label": label, "display_sign": ds,
                   "actual": [r2(None if v is None else v * ds) for v in s["actual"]],
                   "py": [r2(None if v is None else v * ds) for v in s["py"]],
                   "budget": [r2(None if v is None else v * ds) for v in s["budget"]],
                   "variance_vs_budget": [r2((a - b) if is_num(a) and is_num(b) else None) for a, b in zip(s["actual"], s["budget"])],
                   "yoy_pct": [r4(safe_div((a - p), abs(p)) if is_num(a) and is_num(p) and p != 0 else None) for a, p in zip(s["actual"], s["py"])]}
            if lid in ("gp", "ebitda", "ni"):
                rec["margin_pct"] = [r4(safe_div(a, r)) for a, r in zip(s["actual"], rev["actual"])]
                rec["margin_pct_budget"] = [r4(safe_div(b, r)) for b, r in zip(s["budget"], rev["budget"])]
                rec["margin_pct_py"] = [r4(safe_div(p, r)) for p, r in zip(s["py"], rev["py"])]
            if lid in ("cos", "opex"):
                rec["pct_of_revenue"] = [r4(safe_div(-a, r) if is_num(a) else None) for a, r in zip(s["actual"], rev["actual"])]
            out.append(rec)
        return out
