"""Read the one query result (CSV / JSON chunks) or a local workbook into a
Frame: contiguous fiscal months, subsidiaries, P&L accounts and the
period x subsidiary x account cells (MTD, PY_MTD, BUDGET_MTD), plus the
class x department drill cells beneath each account.

Account identity. CHART_OF_ACCOUNT_KEY is account x class in the view, so it is
not the account. The engine's account is the account number and name within a
subsidiary; class and department are drill detail beneath it. Where the budget
for an account is held on some subsidiaries while actuals post on others, the
account is compared across subsidiaries (the budget's own grain) and the
subsidiary split becomes drill detail too. The summary roll-up keys in
config/scope.json are dropped. The capitalisation keys in config/scope.json
(-8001 Capitalised Software, -8002 Capitalised Commissions, -8003 Reversal of
Capitalised Portions) are real rows and are kept; any other negative key
refuses the build.

Adjustments. INCOME_STATEMENT.ADJUSTMENT_TYPE marks the manual adjustment rows:
'Pro Forma Actuals' and 'Pro Forma Adjustments' (pro forma) and 'Adjustment for
Capitalized expenses' (capitalised software and commissions charged inside
Adjusted EBITDA, with their reversal below EBITDA, so the pair nets to zero at
net income). They are never excluded: they are part of the governed revenue,
Adjusted EBITDA and net income. frame.adjustments keeps, per adjustment type,
the monthly actual impact on revenue, Adjusted EBITDA and net income, so every
surface can say which adjustments are included and what they did.

Signs. When the extract carries ACCOUNT.P_AND_L_MULTIPLIER, the view stores
values unsigned and the multiplier gives each account its profit orientation
(revenue +1, costs -1, add-backs +1); every measure is multiplied by it on load,
so the rows sum to net income.

Fiscal calendar. Quarters and years come from the view's PERIOD.QUARTER / YEAR
(fiscal = calendar year at Yes Energy); config/scope.json fiscal_year_start_month (1 = January) fills them
when absent and is checked against them when present (frame.fiscal)."""
import csv
import datetime as dt
import hashlib
import json
import os

from .common import BuildError, to_date, to_num, month_add, month_end, add, fiscal_period

NEEDED = ["PERIOD_START_DATE", "CHART_OF_ACCOUNT_KEY", "ACCOUNT_NAME", "COA_MAPPING_L2", "COA_MAPPING_L3",
          "TOTAL_MTD", "TOTAL_PY_MTD", "TOTAL_BUDGET_MTD"]
SCOPE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "scope.json")
NO_CLASS, NO_DEPT = "No class", "No department"
NO_SUB = "Group level (no subsidiary)"                  # rows the view holds without a subsidiary (capitalisation adjustments)


def load_scope(path=None):
    with open(path or SCOPE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _s(v):
    return str(v).strip() if v not in (None, "") else ""


def read_rows_file(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("rows") or data.get("data") or []
        rows = data
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return [{str(k).upper().strip(): v for k, v in r.items()} for r in rows]


def read_rows(paths):
    """Merge chunk files; chunks must not share a month or it would be counted twice."""
    if isinstance(paths, str):
        paths = [paths]
    rows, seen = [], {}
    for path in paths:
        part = read_rows_file(path)
        months = {to_date(r["PERIOD_START_DATE"]).replace(day=1) for r in part if r.get("PERIOD_START_DATE") not in (None, "")}
        for m in months:
            if m in seen:
                raise BuildError(f"{os.path.basename(path)} and {os.path.basename(seen[m])} both contain {m:%Y-%m}: "
                                 "chunks must not overlap, or the month would be counted twice.")
            seen[m] = path
        rows.extend(part)
    return rows


def _sheet(wb, name):
    data = list(wb[name].iter_rows(values_only=True))
    hdr = [str(h).upper().strip() if h is not None else "" for h in data[0]]
    return [dict(zip(hdr, r)) for r in data[1:] if any(c is not None for c in r)]


def rows_from_workbook(path):
    """Local test mode: join the workbook sheets into the flat rows the query returns."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    acct = {str(a["CHART_OF_ACCOUNT_KEY"]): a for a in _sheet(wb, "ACCOUNT") if a.get("FINANCIAL_STATEMENT") == "P&L"}
    per = {p["ACCOUNTING_PERIOD_KEY"]: p for p in _sheet(wb, "PERIOD")}
    sub = {s["SUBSIDIARY_KEY"]: s["SUBSIDIARY_NAME"] for s in _sheet(wb, "SUBSIDIARY")}
    out = []
    for r in _sheet(wb, "INCOME_STATEMENT"):
        a, p = acct.get(str(r["CHART_OF_ACCOUNT_KEY"])), per[r["ACCOUNTING_PERIOD_KEY"]]
        if a is None:
            continue
        out.append({
            "PERIOD": p.get("PERIOD"), "PERIOD_START_DATE": p["PERIOD_START_DATE"], "PERIOD_END_DATE": p["PERIOD_END_DATE"],
            "YEAR": p.get("YEAR"), "QUARTER": p.get("QUARTER"), "SUBSIDIARY_NAME": sub[r["SUBSIDIARY_KEY"]],
            "CHART_OF_ACCOUNT_KEY": a["CHART_OF_ACCOUNT_KEY"], "ACCOUNT_NUMBER": a.get("ACCOUNT_NUMBER"), "ACCOUNT_NAME": a["ACCOUNT_NAME"],
            "COA_MAPPING_L2": a.get("COA_MAPPING_L2"), "COA_MAPPING_L3": a.get("COA_MAPPING_L3"),
            "COA_MAPPING_L4": a.get("COA_MAPPING_L4"), "COA_MAPPING_L5": a.get("COA_MAPPING_L5"), "COA_MAPPING_L6": a.get("COA_MAPPING_L6"),
            "CLASS_NAME": r.get("CLASS_NAME"), "DEPARTMENT_NAME": r.get("DEPARTMENT_NAME"), "ADJUSTMENT_TYPE": r.get("ADJUSTMENT_TYPE"),
            "TOTAL_MTD": r.get("MTD"), "TOTAL_PY_MTD": r.get("PY_MTD"), "TOTAL_BUDGET_MTD": r.get("BUDGET_MTD")})
    return out


def governed_from_workbook(path):
    """Local test mode: the GOVERNED sheet (month x subsidiary REVENUE_MTD, ADJUSTED_EBITDA_MTD, NET_INCOME_MTD), if present."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    return _sheet(wb, "GOVERNED") if "GOVERNED" in wb.sheetnames else None


class Frame:
    """periods: list of dicts {label,start,end,year,quarter,month,name,future}
    subs: list of subsidiary names; accounts: list of dicts; cells: {(p,s,a): [mtd, py, bud]}"""

    def __init__(self, rows, as_of=None, subsidiary=None, expect_accounts=None, exclude_subsidiaries=(), scope=None):
        if not rows:
            raise BuildError("The result set is empty: nothing to analyse.")
        missing = [c for c in NEEDED if c not in rows[0]]
        if missing:
            raise BuildError("Missing column(s): " + ", ".join(missing) + ". Run the query in references/dashboards.md.")
        scope = scope or load_scope()
        rollups = {str(k) for k in scope["rollup_keys"]}
        cap_keys = {str(k): v for k, v in (scope.get("capitalisation_keys") or {}).items()}
        adj_types = {_s(k).lower(): v for k, v in (scope.get("adjustment_types") or {}).items()}
        if "FINANCIAL_STATEMENT" in rows[0]:
            rows = [r for r in rows if str(r.get("FINANCIAL_STATEMENT") or "P&L").strip().upper() in ("P&L", "PL", "P AND L", "INCOME STATEMENT")]
        rows = [r for r in rows if _s(r["CHART_OF_ACCOUNT_KEY"]) not in rollups]
        # signs: apply the view's per-account P&L multiplier when the extract carries it
        self.multiplier_applied = "P_AND_L_MULTIPLIER" in rows[0] if rows else False
        if self.multiplier_applied:
            signed = []
            for r in rows:
                m = to_num(r.get("P_AND_L_MULTIPLIER"))
                if m is None:
                    raise BuildError(f"Account key {_s(r['CHART_OF_ACCOUNT_KEY'])} ({_s(r['ACCOUNT_NAME']) or 'no name'}) has no P_AND_L_MULTIPLIER; "
                                     "the sign of its values is unknown. Probe it (references/view-finance.md §3).")
                q = dict(r)
                for k in ("TOTAL_MTD", "TOTAL_PY_MTD", "TOTAL_BUDGET_MTD"):
                    v = to_num(q.get(k))
                    q[k] = None if v is None else v * m
                signed.append(q)
            rows = signed
        def adj_class(r):
            t = _s(r.get("ADJUSTMENT_TYPE"))
            if not t or t.lower() in ("none", "null"):
                return None
            if t.lower() not in adj_types:
                raise BuildError(f"Unknown ADJUSTMENT_TYPE '{t}' (account {_s(r['ACCOUNT_NAME']) or _s(r['CHART_OF_ACCOUNT_KEY'])}). "
                                 "Probe it (references/dashboards.md §2) and add it to config/scope.json adjustment_types; never drop the rows.")
            return adj_types[t.lower()]
        is_adj = lambda r: _s(r["CHART_OF_ACCOUNT_KEY"]) in cap_keys
        unknown = sorted({(_s(r["CHART_OF_ACCOUNT_KEY"]), _s(r["ACCOUNT_NAME"])) for r in rows
                          if _s(r["CHART_OF_ACCOUNT_KEY"]).startswith("-") and not is_adj(r)})
        if unknown:
            raise BuildError("Negative key(s) that are neither a listed roll-up nor a capitalisation key (config/scope.json "
                             "capitalisation_keys): " + ", ".join(f"{k} ({n or 'no name'})" for k, n in unknown)
                             + ". Probe them (references/dashboards.md §2) and add roll-ups to config/scope.json rollup_keys.")
        if not rows:
            raise BuildError("Only roll-up rows came back; query the accounts.")
        # scope: excluded subsidiaries are dropped and reported; the extract should already filter them
        excl = {e.strip().lower(): e for e in exclude_subsidiaries or ()}
        self.excluded = {e: 0 for e in exclude_subsidiaries or ()}
        kept = []
        for r in rows:
            n = _s(r.get("SUBSIDIARY_NAME")).lower()
            if n in excl:
                self.excluded[excl[n]] += 1
            else:
                kept.append(r)
        rows = kept
        if not rows:
            raise BuildError("Every row belongs to an excluded subsidiary.")
        self.scope_subsidiary = None
        if subsidiary:
            names = {str(r.get("SUBSIDIARY_NAME") or "") for r in rows}
            match = [n for n in names if n.strip().lower() == subsidiary.strip().lower()]
            if not match:
                raise BuildError(f"Subsidiary '{subsidiary}' is not in the data. Present: {', '.join(sorted(names))}.")
            rows = [r for r in rows if str(r.get("SUBSIDIARY_NAME") or "") == match[0]]
            self.scope_subsidiary = match[0]

        n_acct = len({_s(r["CHART_OF_ACCOUNT_KEY"]) for r in rows})
        self.n_keys = n_acct
        if expect_accounts is not None and n_acct != expect_accounts:
            raise BuildError(f"The data has {n_acct} account key(s) but the probe counted {expect_accounts}. The result was probably cut off: "
                             "re-run the query one month per statement and pass every file to --rows.")

        starts = sorted({to_date(r["PERIOD_START_DATE"]).replace(day=1) for r in rows})
        for a, b in zip(starts, starts[1:]):
            if b != month_add(a, 1):
                raise BuildError(f"Periods are not contiguous: {a:%Y-%m} is followed by {b:%Y-%m}. Re-run the query without a filter that skips months.")
        pidx = {d: i for i, d in enumerate(starts)}
        fsm = int(scope.get("fiscal_year_start_month") or 1)
        self.fiscal = {"start_month": fsm, "source": "PERIOD.YEAR / QUARTER", "mismatch": []}
        meta = {}
        for r in rows:
            d = to_date(r["PERIOD_START_DATE"]).replace(day=1)
            if d in meta:
                continue
            e = r.get("PERIOD_END_DATE")
            q = str(r.get("QUARTER") or "").upper().lstrip("Q").strip()
            y = r.get("YEAR")
            fy, fq = fiscal_period(d, fsm)
            if not q or y in (None, ""):
                self.fiscal["source"] = f"derived from fiscal_year_start_month {fsm}"
            elif (int(float(y)), int(float(q))) != (fy, fq):
                self.fiscal["mismatch"].append(f"{d:%Y-%m} is FY{int(float(y))} Q{int(float(q))} in the view, FY{fy} Q{fq} by the configured start month")
            meta[d] = {"end": to_date(e) if e not in (None, "") else month_end(d),
                       "quarter": int(float(q)) if q else fq,
                       "year": int(float(y)) if y not in (None, "") else fy,
                       "name": str(r.get("PERIOD")) if r.get("PERIOD") not in (None, "") else None}

        self.subs = sorted({str(r.get("SUBSIDIARY_NAME") or NO_SUB) for r in rows})
        sidx = {s: i for i, s in enumerate(self.subs)}
        self.has_l5 = any(_s(r.get("COA_MAPPING_L5")) for r in rows)
        self.has_l6 = any(_s(r.get("COA_MAPPING_L6")) for r in rows)
        self.has_class = any(_s(r.get("CLASS_NAME")) for r in rows)
        self.has_department = any(_s(r.get("DEPARTMENT_NAME")) for r in rows)

        # natural account: number + name + mapping
        def natural(r):
            maps = (_s(r.get("COA_MAPPING_L2")), _s(r.get("COA_MAPPING_L3")), _s(r.get("COA_MAPPING_L4")))
            return ("acct", _s(r.get("ACCOUNT_NUMBER")), _s(r["ACCOUNT_NAME"])) + maps
        sub_of = lambda r: str(r.get("SUBSIDIARY_NAME") or NO_SUB)
        bud_subs, act_subs = {}, {}
        for r in rows:
            nat = natural(r)
            b, a, p = to_num(r["TOTAL_BUDGET_MTD"]), to_num(r["TOTAL_MTD"]), to_num(r["TOTAL_PY_MTD"])
            if b not in (None, 0):
                bud_subs.setdefault(nat, set()).add(sub_of(r))
            if a not in (None, 0) or p not in (None, 0):
                act_subs.setdefault(nat, set()).add(sub_of(r))
        # budget grain: pooled across subsidiaries when the budget sits on some subsidiaries and actuals post on others
        pooled = {nat for nat, sb in bud_subs.items() if (act_subs.get(nat, set()) - sb) and len(sb | act_subs.get(nat, set())) > 1}
        self.accounts, aidx = [], {}
        unit_of = {}
        for r in rows:
            nat = natural(r)
            unit = (nat,) if nat in pooled else (nat, sub_of(r))
            unit_of[id(r)] = unit
            if unit in aidx:
                self.accounts[aidx[unit]]["keys"].add(_s(r["CHART_OF_ACCOUNT_KEY"]))
                self.accounts[aidx[unit]]["subsidiaries"].add(sub_of(r))
                continue
            aidx[unit] = len(self.accounts)
            sub = None if nat in pooled else sub_of(r)
            self.accounts.append({"id": "a" + hashlib.sha1(repr(unit).encode("utf-8")).hexdigest()[:12], "name": _s(r["ACCOUNT_NAME"]),
                                  "number": _s(r.get("ACCOUNT_NUMBER")) or None, "subsidiary": sub,
                                  "subsidiaries": {sub_of(r)}, "keys": {_s(r["CHART_OF_ACCOUNT_KEY"])}, "adjustment": is_adj(r),
                                  "budget_grain": "account" if nat in pooled else "subsidiary",
                                  "budget_held_at": sorted(bud_subs.get(nat, ())),
                                  "l2": (r.get("COA_MAPPING_L2") or None), "l3": (r.get("COA_MAPPING_L3") or None),
                                  "l4": (r.get("COA_MAPPING_L4") or None), "l5": (_s(r.get("COA_MAPPING_L5")) or None), "l6": (_s(r.get("COA_MAPPING_L6")) or None)})
        for a in self.accounts:
            a["subsidiaries"], a["keys"] = sorted(a["subsidiaries"]), sorted(a["keys"])
        self.cells, self.dcells = {}, {}
        adj_raw = {}                                          # adjustment type -> period -> {rev, ebitda, ni, components}
        for r in rows:
            p, s, a = pidx[to_date(r["PERIOD_START_DATE"]).replace(day=1)], sidx[sub_of(r)], aidx[unit_of[id(r)]]
            vals = [to_num(r["TOTAL_MTD"]), to_num(r["TOTAL_PY_MTD"]), to_num(r["TOTAL_BUDGET_MTD"])]
            key = (p, s, a)
            self.cells[key] = [add(o, v) for o, v in zip(self.cells[key], vals)] if key in self.cells else vals
            dk = (p, a, s, _s(r.get("CLASS_NAME")) or NO_CLASS, _s(r.get("DEPARTMENT_NAME")) or NO_DEPT)
            self.dcells[dk] = [add(o, v) for o, v in zip(self.dcells[dk], vals)] if dk in self.dcells else vals
            t = _s(r.get("ADJUSTMENT_TYPE"))
            cls = adj_class(r)
            if cls and vals[0] not in (None, 0):
                v = vals[0]
                cell = adj_raw.setdefault(t, {"class": cls, "by_period": {}})["by_period"].setdefault(p, {"rev": 0.0, "ebitda": 0.0, "ni": 0.0, "components": {}})
                cell["ni"] += v
                if _s(r.get("COA_MAPPING_L2")).lower() == "adjusted ebitda":
                    cell["ebitda"] += v
                if _s(r.get("COA_MAPPING_L3")).lower() == "revenue":
                    cell["rev"] += v
                comp = cap_keys.get(_s(r["CHART_OF_ACCOUNT_KEY"])) or (_s(r.get("COA_MAPPING_L4")) or "Other")
                cell["components"][comp] = cell["components"].get(comp, 0.0) + v

        # as-of: the latest closed month, unless declared. An open month (early accrual reversals,
        # FX revaluation, a $0.01 rounding line) carries a few actuals; it is closed only when at
        # least half as many accounts post a non-zero actual as in the busiest earlier month.
        has_actual, posted = {}, {}
        for (p, s, a), v in self.cells.items():
            if v[0] is not None:
                has_actual[p] = True
                if v[0] != 0:
                    posted.setdefault(p, set()).add(a)
        self.skipped_open = []
        if as_of:
            want = dt.date(int(as_of[:4]), int(as_of[5:7]), 1)
            if want not in pidx:
                raise BuildError(f"--as-of {as_of} is not in the data ({starts[0]:%Y-%m} to {starts[-1]:%Y-%m}).")
            self.as_of = pidx[want]
            if not has_actual.get(self.as_of):
                raise BuildError(f"--as-of {as_of} carries no actuals in the data.")
        else:
            actual_idx = [p for p in range(len(starts)) if has_actual.get(p)]
            if not actual_idx:
                raise BuildError("No month carries an actual value.")
            n = {p: len(posted.get(p, ())) for p in actual_idx}
            closed = [p for p in actual_idx if n[p] >= 0.5 * max([n[q] for q in actual_idx if q < p] or [0])]
            self.as_of = max(closed)
            self.skipped_open = [f"{starts[p]:%Y-%m}" for p in actual_idx if p > self.as_of]
        self.periods = []
        for i, d in enumerate(starts):
            m = meta[d]
            self.periods.append({"idx": i, "label": f"{d:%Y-%m}", "start": d.isoformat(), "end": m["end"].isoformat(),
                                 "year": m["year"], "quarter": m["quarter"], "month": d.month, "name": m["name"],
                                 "future": i > self.as_of})
        self.aidx, self.sidx, self.pidx = aidx, sidx, pidx
        # adjustments: per type, the monthly actual impact up to the as-of month (profit-oriented: + raises profit)
        self.adjustments = {}
        for t, d in sorted(adj_raw.items()):
            months = [{"period": self.periods[p]["label"], "idx": p, **{k: round(v, 2) for k, v in c.items() if k != "components"},
                       "components": {k: round(v, 2) for k, v in sorted(c["components"].items())}}
                      for p, c in sorted(d["by_period"].items()) if p <= self.as_of]
            if months:
                self.adjustments[t] = {"class": d["class"], "months": months}
