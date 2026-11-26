"""GL memo evidence: the human-written description on each ledger line, as evidence for the review.

The Finance view carries TRANSACTIONS_AND_ADJUSTMENTS.MEMO, the free-text NetSuite memo of each GL line (on a manual
adjustment it holds the adjustment reason). The extract (references/dashboards.md §2, memo query) returns one row per
month x subsidiary x account key x source type x memo with the income-statement amount (TOTAL_IS_CONVERTED_AMT, which
is TOTAL_MTD x P_AND_L_MULTIPLIER: profit-oriented, like the engine) and the line count.

What the engine does with it, deterministically:
  1. Reconcile: every account-month the memos cover must sum to the account's actual to $1, or the build refuses
     (a cut-off memo result would otherwise tell a partial story).
  2. Theme: each memo is reduced to a theme by removing what changes every month (month names, dates, document
     numbers), so "Sep26 Vendor Accruals" and "Aug26 Vendor Accruals" are one theme; the month the memo names is kept
     (`refers_to`) and flagged when it is earlier than the posting month (`prior_period_ref`).
  3. Tag: keywords give each theme accounting tags (accrual, reversal, payroll, amortization, interest, intercompany,
     reclass, prepaid, true-up, ...); `accrual_reversal` marks an accrual or reversal that names an earlier month.
  4. Tables: per lens, per driver and per material account, the themes ranked by their movement against the
     comparator (prior year) or by size (budget, which has no memos), the rest as "other", the prior-year memos that do
     not tie to the comparator as "unmatched"; every table adds up to the driver's or account's actual and comparator.
     Plus the run-rate months behind the outlook and the memos behind each one-off in the register.
  5. Restricted terms: the proper names in the memos (vendors, customers, people, systems) that are not words of the
     chart of accounts; the diagnosis gate refuses any of them in the review, so memos inform the commentary without
     their names or document numbers reaching the page.

A memo is what the person who posted the line wrote; it is evidence for a reading, never a verified cause. The page
never embeds memo text (embed.py drops these blocks); only the reviewed commentary written from it shows."""
import hashlib
import os
import re

from .common import BuildError, is_num, r2, r4, to_date, to_num
from .load import NO_SUB

TOP_DRIVER_THEMES, TOP_ACCOUNT_THEMES, TOP_LENS_THEMES, TOP_RUNRATE_THEMES = 8, 5, 10, 5
RUNRATE_MONTHS = 3
NEEDED = ("PERIOD_START_DATE", "CHART_OF_ACCOUNT_KEY", "MEMO", "TOTAL_IS_CONVERTED_AMT")

MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
          "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
          "nov": 11, "november": 11, "dec": 12, "december": 12}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
MONTH_YEAR = re.compile(r"\b" + _MON + r"[\s\-'/.]*('?\d{2}|\d{4})?\b", re.I)
DATE = re.compile(r"\b\d{1,4}[/.\-]\d{1,2}(?:[/.\-]\d{1,4})?\b")
DOCNUM = re.compile(r"#\s*\S+|\b[A-Za-z]*\d[\w\-/]{3,}\b|\b\d{3,}\b")
FISCAL = re.compile(r"\b(fy|q[1-4])\s*'?\d{0,4}\b", re.I)

TAGS = [("accrual", r"accru"), ("reversal", r"\brevers|\breverse\b|\brev\b"), ("reclass", r"reclass|re-class"),
        ("payroll", r"payroll|salar|wages|\bpay run\b"), ("commission", r"commission"), ("bonus", r"bonus"),
        ("amortization", r"amorti"), ("depreciation", r"depreci"), ("interest", r"interest"),
        ("intercompany", r"intercompany|inter-company|\bi/c\b|\bic\b"), ("prepaid", r"prepaid|prepayment|prepay"),
        ("true_up", r"true[\s\-]?up"), ("write_off", r"write[\s\-]?off|bad debt|provision"), ("fx", r"\bfx\b|revaluation|exchange"),
        ("allocation", r"alloc"), ("adjustment", r"adjust|\badj\b"), ("revenue", r"revenue|billing|mrr"),
        ("refund_credit", r"refund|credit note|credit memo"), ("tax", r"\btax|\bvat\b|\bgst\b"), ("severance", r"severance|termination")]
TAG_RX = [(t, re.compile(rx, re.I)) for t, rx in TAGS]
# one category per theme (the first tag in this order), so a category table adds up and survives a memo relabelled
# between years ("Payroll Invoice" last year, "Payroll" this year are both payroll)
CATEGORY_ORDER = ["accrual_reversal", "payroll", "bonus", "commission", "severance", "accrual", "interest", "amortization", "depreciation",
                  "reclass", "intercompany", "prepaid", "true_up", "write_off", "fx", "tax", "allocation", "adjustment", "refund_credit", "revenue"]
CATEGORY_LABEL = {"accrual_reversal": "accruals and reversals for an earlier month", "payroll": "payroll", "bonus": "bonus", "commission": "commission",
                  "severance": "severance", "accrual": "accruals for the period", "interest": "interest", "amortization": "amortisation",
                  "depreciation": "depreciation", "reclass": "reclassifications", "intercompany": "intercompany", "prepaid": "prepaid releases",
                  "true_up": "true-ups", "write_off": "write-offs and provisions", "fx": "exchange differences", "tax": "tax", "allocation": "allocations",
                  "adjustment": "adjustments", "refund_credit": "refunds and credits", "revenue": "revenue postings", "described": "other described postings",
                  "none": "no memo"}

# common words a memo may carry that are not names (the chart of accounts adds its own words per payload)
COMMON = set("""a an and or of the to for in on at by from with without per via vs net gross total sub new old other misc miscellaneous
monthly semi bi weekly annual annually quarterly daily month months year years quarter period periods ytd mtd prior current next last
accrual accruals accrued accrue reversal reverse reversed reversing reclass reclasses reclassification payroll payrolls salary salaries wages
bonus bonuses commission commissions amortization amortisation depreciation interest expense expenses income revenue revenues cost costs
intercompany loan loans prepaid prepaids prepayment true up write off provision fx revaluation exchange allocation allocations adjustment
adjustments adj invoice invoices billing credit debit note memo refund tax taxes vat gst severance services service fees fee subscription
subscriptions license licenses licence software hosting platform cloud support maintenance consulting professional ps rent lease office
travel meals entertainment marketing advertising events event conference insurance legal audit accounting bank charges charge recruiting
benefits benefit health pension retirement contractor contractors vendor vendors supplier suppliers customer customers employee employees
record recording recognised recognized recognition deferred unbilled journal entry entries je gl ap ar cash payment payments paid
company group holdings inc ltd limited llc corp plc gmbh bv sa pty usd gbp eur inr aud cad record allocation clearing suspense
reimbursement reimbursements expense report card corporate amex visa telecom phone internet utilities equipment hardware training
dues memberships recruitment relocation stock based compensation share options rsu payable receivable sales cogs opex capex""".split())


WORD = re.compile(r"[A-Za-z][A-Za-z&]*[A-Za-z]")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def doc_words():
    """Words of the skill's own reference documents: human-written finance English, never customer or vendor names."""
    out = set()
    for sub in ("references", "specialists"):
        d = os.path.join(SKILL_DIR, sub)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.endswith(".md"):
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    out |= {w.lower() for w in WORD.findall(fh.read())}
    return out


def _clean_text(s):
    return " ".join(str(s or "").split())


def months_named(text):
    """(year, month) tuples a memo names, where a year is given ("Sep26", "Aug-2026", "Sept 2026")."""
    out = []
    for m in MONTH_YEAR.finditer(text or ""):
        mon, yr = MONTHS.get(m.group(1).lower().rstrip(".")), m.group(2)
        if mon and yr:
            y = int(yr.strip("'"))
            out.append((y + 2000 if y < 100 else y, mon))
    return out


def theme_of(memo):
    """(key, label): the memo with month names, dates, fiscal tags and document numbers removed. Blank -> ('', '(no memo)')."""
    t = _clean_text(memo)
    if not t:
        return "", "(no memo)"
    x = MONTH_YEAR.sub(" ", t)
    x = FISCAL.sub(" ", x)
    x = DATE.sub(" ", x)
    x = DOCNUM.sub(" ", x)
    x = re.sub(r"\s+[-–:|]+\s*$|^\s*[-–:|]+\s+", " ", " ".join(x.split()))
    label = " ".join(x.split()).strip(" -–:|,;") or "(memo is a date or reference only)"
    key = re.sub(r"[^a-z0-9&]+", " ", label.lower()).strip()
    return key, label


def tags_of(label):
    return [t for t, rx in TAG_RX if rx.search(label)]


def _tid(key):
    return "m" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8] if key else "m-none"


def read_memos(paths):
    from .load import read_rows_file
    rows, seen = [], {}
    for p in paths:
        part = read_rows_file(p)
        if not part:
            continue
        miss = [c for c in NEEDED if c not in part[0]]
        if miss:
            raise BuildError(f"{p}: the memo extract lacks {', '.join(miss)}; run the memo query in references/dashboards.md §2")
        # keyed by the period's own start date: a year-end adjustment period (start date on the last day of the fiscal
        # year, e.g. 2025-01-31) is a separate file and folds into its month, as the statement marts fold it
        periods = {to_date(r["PERIOD_START_DATE"]) for r in part}
        for m in periods:
            if m in seen:
                raise BuildError(f"memo period {m:%Y-%m-%d} is in both {seen[m]} and {p}; one period per file")
            seen[m] = p
        rows.extend(part)
    return rows


class Memos:
    """Memo rows mapped onto the engine's accounts and months, reconciled to the actuals."""

    def __init__(self, rows, frame, model, tol=1.0):
        P = frame.periods
        pidx = {to_date(p["start"]).replace(day=1): i for i, p in enumerate(P)}
        by_unit = {}
        for a in frame.accounts:
            for k in a["keys"]:
                for s in a["subsidiaries"]:
                    by_unit[(k, s)] = a["id"]
        mapped = {a["id"] for a in model.mapped}
        self.cells = {}          # (aid, k) -> {key: [amount, lines, label_weights{label: abs}, refs set, source types set]}
        self.months = set()
        self.dropped = {"out_of_scope_subsidiary": 0, "unmapped_account": 0, "outside_extract_months": 0}
        unknown = {}
        subs = set(frame.subs)
        for r in rows:
            d = to_date(r["PERIOD_START_DATE"]).replace(day=1)
            k = pidx.get(d)
            if k is None or P[k]["future"] or k > model.as_of:
                self.dropped["outside_extract_months"] += 1
                continue
            sub = str(r.get("SUBSIDIARY_NAME") or NO_SUB)
            if sub not in subs:
                self.dropped["out_of_scope_subsidiary"] += 1
                continue
            amt = to_num(r.get("TOTAL_IS_CONVERTED_AMT")) or 0.0
            aid = by_unit.get((str(r["CHART_OF_ACCOUNT_KEY"]).strip(), sub))
            self.months.add(k)
            if aid is None:
                if amt:
                    unknown.setdefault((P[k]["label"], sub, str(r["CHART_OF_ACCOUNT_KEY"])), 0.0)
                    unknown[(P[k]["label"], sub, str(r["CHART_OF_ACCOUNT_KEY"]))] += amt
                continue
            if aid not in mapped:
                self.dropped["unmapped_account"] += 1
                continue
            key, label = theme_of(r.get("MEMO"))
            c = self.cells.setdefault((aid, k), {}).setdefault(key, [0.0, 0, {}, set(), set()])
            c[0] += amt
            c[1] += int(to_num(r.get("TRANSACTION_LINE_COUNT")) or 0)
            c[2][label] = c[2].get(label, 0.0) + abs(amt)
            for y, m in months_named(r.get("MEMO")):
                c[3].add((y, m))
            c[4].add(str(r.get("SOURCE_TYPE") or "ACTUAL"))
        unknown = {k: v for k, v in unknown.items() if abs(v) > tol}
        if unknown:
            raise BuildError(f"{len(unknown)} memo account-month(s) post to an account key the P&L extract does not carry: "
                             + "; ".join(f"{m} {s} key {k} {v:,.2f}" for (m, s, k), v in list(unknown.items())[:6])
                             + ". The memo query and the data query must share the scope (references/dashboards.md §2).")
        # reconcile every covered account-month to the actual (profit-oriented both sides)
        bad, checked = [], 0
        for k in sorted(self.months):
            for a in model.mapped:
                act = model.series[model.aidx[a["id"]]]["actual"][k]
                memo = sum(v[0] for v in self.cells.get((a["id"], k), {}).values())
                checked += 1
                if abs((act if is_num(act) else 0.0) - memo) > tol:
                    bad.append((P[k]["label"], a["name"], act, memo))
        if bad:
            raise BuildError(f"The GL memo extract does not reconcile to the P&L actuals in {len(bad)} account-month(s) (tolerance ${tol:g}): "
                             + "; ".join(f"{m} {n} actual {0 if a is None else a:,.2f} vs memos {b:,.2f}" for m, n, a, b in bad[:6])
                             + ". Re-run the memo query for those months with --expect-rows (a cut-off result) and the same scope as the data query.")
        self.checked = checked
        self.P = P
        self.model = model

    # ---------------------------------------------------------------- aggregation
    def _agg(self, aids, rng):
        """{key: rec} over accounts x months in rng (inclusive)."""
        out = {}
        if rng is None:
            return out
        for aid in aids:
            for k in range(rng[0], rng[1] + 1):
                for key, c in self.cells.get((aid, k), {}).items():
                    o = out.setdefault(key, {"amount": 0.0, "lines": 0, "labels": {}, "refs": set(), "sources": set(), "by_account": {}, "posted": set()})
                    o["amount"] += c[0]
                    o["lines"] += c[1]
                    for lb, w in c[2].items():
                        o["labels"][lb] = o["labels"].get(lb, 0.0) + w
                    o["refs"] |= c[3]
                    o["sources"] |= c[4]
                    o["by_account"][aid] = o["by_account"].get(aid, 0.0) + c[0]
                    o["posted"].add(k)
        return out

    def covers(self, rng):
        return rng is not None and all(k in self.months for k in range(rng[0], rng[1] + 1))

    def _label(self, key, *recs):
        w = {}
        for r in recs:
            for lb, x in ((r or {}).get("labels") or {}).items():
                w[lb] = w.get(lb, 0.0) + x
        return max(sorted(w), key=lambda lb: w[lb]) if w else ("(no memo)" if not key else key)

    def _prior_ref(self, rec):
        """The memo names a month earlier than the month it posted in (an accrual or its reversal for an earlier month)."""
        if not rec:
            return False
        d = to_date(self.P[min(rec["posted"])]["start"])
        return any((ry, rm) < (d.year, d.month) for ry, rm in rec["refs"])

    def _theme(self, key, cur, cmp, dsign, has_cmp, top_accounts=0):
        lab = self._label(key, cur, cmp)
        tags = tags_of(lab)
        prior = self._prior_ref(cur)
        if prior and ({"accrual", "reversal"} & set(tags)):
            tags.append("accrual_reversal")
        if prior:
            tags.append("prior_period_ref")
        a = (cur or {}).get("amount", 0.0)
        c = (cmp or {}).get("amount", 0.0) if has_cmp else None
        rec = {"id": _tid(key), "label": lab, "actual": r2(a * dsign), "comparator": r2(c * dsign) if has_cmp else None,
               "variance": r2(a - c) if has_cmp else None, "lines": (cur or {}).get("lines", 0), "comparator_lines": (cmp or {}).get("lines", 0) if has_cmp else None,
               "tags": tags, "refers_to": sorted(f"{y}-{m:02d}" for y, m in (cur or {}).get("refs", set()))[:3],
               "source_type": "/".join(sorted((cur or {}).get("sources") or (cmp or {}).get("sources") or {"ACTUAL"})),
               "_a": a, "_c": c or 0.0}
        if top_accounts:
            ba = {}
            for x in (cur, cmp):
                for aid, v in ((x or {}).get("by_account") or {}).items():
                    ba[aid] = ba.get(aid, 0.0) + abs(v)
            rec["accounts"] = [aid for aid, _ in sorted(ba.items(), key=lambda t: -t[1])[:top_accounts]]
        return rec

    def table(self, aids, rng, cmp_rng, dsign, lens_actual_po, lens_comparator_po, has_cmp, top, top_accounts=0):
        """Themes for a set of accounts, top N plus 'other' and (prior year) 'unmatched'; foots to the lens actual and comparator."""
        cur = self._agg(aids, rng)
        cmp = self._agg(aids, cmp_rng) if has_cmp else {}
        keys = set(cur) | set(cmp)
        th = [self._theme(k, cur.get(k), cmp.get(k), dsign, has_cmp, top_accounts) for k in keys]
        th = [t for t in th if abs(t["_a"]) >= 0.005 or abs(t["_c"]) >= 0.005]
        rank = (lambda t: -abs(t["_a"] - t["_c"])) if has_cmp else (lambda t: -abs(t["_a"]))
        th.sort(key=lambda t: (rank(t), t["id"]))
        tot_abs = sum(abs(t["_a"] - t["_c"]) if has_cmp else abs(t["_a"]) for t in th)
        head, rest = th[:top], th[top:]
        for t in head:
            t["share_of_abs_movement"] = r4((abs(t["_a"] - t["_c"]) if has_cmp else abs(t["_a"])) / tot_abs) if tot_abs else None
        out = [{k: v for k, v in t.items() if not k.startswith("_")} for t in head]
        ra, rc = sum(t["_a"] for t in rest), sum(t["_c"] for t in rest)
        if rest:
            out.append({"id": "other", "label": f"{len(rest)} other memo theme(s)", "actual": r2(ra * dsign), "comparator": r2(rc * dsign) if has_cmp else None,
                        "variance": r2(ra - rc) if has_cmp else None, "lines": sum(t["lines"] for t in rest), "tags": [], "themes": len(rest)})
        memo_a = sum(v["amount"] for v in cur.values())
        memo_c = sum(v["amount"] for v in cmp.values())
        # the monthly reconciliation allows $1 per account-month; over a window the cents add up, so the residual is a line
        cur_gap = (lens_actual_po or 0.0) - memo_a
        cmp_gap = ((lens_comparator_po or 0.0) - memo_c) if has_cmp else 0.0
        tie = None
        if has_cmp:
            tie = {"memo_total": r2(memo_c * dsign), "comparator": r2((lens_comparator_po or 0.0) * dsign), "gap": r2(cmp_gap * dsign), "ties": abs(cmp_gap) <= 1.0}
            if abs(cmp_gap) > 1.0:
                out.append({"id": "unmatched", "label": "prior-year amount not in the prior-year memos (restated or remapped since)", "actual": 0.0,
                            "comparator": r2(cmp_gap * dsign), "variance": r2(-cmp_gap), "lines": 0, "tags": []})
                cmp_gap = 0.0
        if abs(cur_gap) >= 0.005 or abs(cmp_gap) >= 0.005:
            out.append({"id": "rounding", "label": "difference to the ledger within the reconciliation tolerance ($1 per account-month)",
                        "actual": r2(cur_gap * dsign), "comparator": r2(cmp_gap * dsign) if has_cmp else None,
                        "variance": r2(cur_gap - cmp_gap) if has_cmp else None, "lines": 0, "tags": []})
        cats = {}
        for t in th:
            c = "none" if t["id"] == "m-none" else next((x for x in CATEGORY_ORDER if x in t["tags"]), "described")
            o = cats.setdefault(c, [0.0, 0.0, 0])
            o[0] += t["_a"]; o[1] += t["_c"]; o[2] += 1
        categories = [{"id": c, "label": CATEGORY_LABEL[c], "actual": r2(a * dsign), "comparator": r2(cc * dsign) if has_cmp else None,
                       "variance": r2(a - cc) if has_cmp else None, "themes": n}
                      for c, (a, cc, n) in sorted(cats.items(), key=lambda kv: (-(abs(kv[1][0] - kv[1][1]) if has_cmp else abs(kv[1][0])), kv[0]))]
        return {"themes": out, "categories": categories, "theme_count": len(th), "actual_total": r2((lens_actual_po or 0.0) * dsign),
                "comparator_total": r2((lens_comparator_po or 0.0) * dsign) if has_cmp else None, "comparator_tie": tie,
                "blank_memo_share": r4(abs(cur.get("", {}).get("amount", 0.0)) / sum(abs(v["amount"]) for v in cur.values())) if cur and sum(abs(v["amount"]) for v in cur.values()) else None}

    # ---------------------------------------------------------------- per lens
    def lens_block(self, L):
        rng = (L["range"]["start_idx"], L["range"]["end_idx"])
        if not self.covers(rng):
            missing = [self.P[k]["label"] for k in range(rng[0], rng[1] + 1) if k not in self.months]
            return {"available": False, "reason": f"no memo extract for {', '.join(missing)}"}
        has_cmp = L["basis"] == "py"
        cmp_rng = (rng[0] - 12, rng[1] - 12) if has_cmp and rng[0] >= 12 else None
        if has_cmp and not self.covers(cmp_rng):
            has_cmp, cmp_rng = False, None
            cmp_note = "the prior-year months are not in the memo extract, so themes show the current window only"
        else:
            cmp_note = None if L["basis"] == "py" else "the budget has no memos: themes show what posted in the window, ranked by size"
        M = self.model
        ds = M.display_sign
        acc = {a["id"]: a for a in L["accounts"]}
        drivers = {}
        for d in L["drivers"]:
            if not d["accounts"]:
                continue
            drivers[d["id"]] = self.table(d["accounts"], rng, cmp_rng, ds[d["section"]], d["actual_po"], d["comparator_po"], has_cmp, TOP_DRIVER_THEMES, top_accounts=3)
        accounts = {}
        for a in L["accounts"]:
            if a.get("tier") in ("executive", "management", "monitoring") or a.get("movement_tier") in ("executive", "management", "monitoring"):
                accounts[a["id"]] = self.table([a["id"]], rng, cmp_rng, ds[a["section"]], a["actual_po"], a["comparator_po"], has_cmp, TOP_ACCOUNT_THEMES)
        # the whole P&L: profit-oriented (display sign +1), the themes that move net income most
        all_ids = [a["id"] for a in L["accounts"]]
        ni = next(x for x in L["lines"] if x["id"] == "ni")
        top = self.table(all_ids, rng, cmp_rng, 1.0, ni["actual_po"], ni["comparator_po"], has_cmp, TOP_LENS_THEMES, top_accounts=3)
        drv_of = M.driver_of
        for t in top["themes"]:
            if t.get("accounts"):
                t["drivers"] = list(dict.fromkeys(drv_of.get(x) for x in t["accounts"] if drv_of.get(x)))
        return {"available": True, "basis": "prior year" if has_cmp else ("budget (no memos)" if L["basis"] == "budget" else "current window only"),
                "note": cmp_note, "months": [self.P[k]["label"] for k in range(rng[0], rng[1] + 1)],
                "comparator_months": [self.P[k]["label"] for k in range(cmp_rng[0], cmp_rng[1] + 1)] if cmp_rng else [],
                "orientation": "actual and comparator as the lens shows them (costs positive); variance profit-oriented (+ favourable), like the lens",
                "net_income": top, "drivers": drivers, "accounts": accounts}

    def run_rate(self, drivers):
        """The memos in the trailing months the outlook's run-rate rule averages, per driver (actuals only)."""
        k1 = self.model.as_of
        rng = (k1 - RUNRATE_MONTHS + 1, k1)
        if not self.covers(rng):
            return {"available": False, "reason": "the run-rate months are not all in the memo extract"}
        ds = self.model.display_sign
        out = {}
        for d in drivers:
            if d["accounts"]:
                tot = sum(sum(v[0] for v in self.cells.get((aid, k), {}).values()) for aid in d["accounts"] for k in range(rng[0], rng[1] + 1))
                out[d["id"]] = self.table(d["accounts"], rng, None, ds[d["section"]], tot, None, False, TOP_RUNRATE_THEMES)
        return {"available": True, "months": [self.P[k]["label"] for k in range(rng[0], rng[1] + 1)], "drivers": out,
                "reading": "themes tagged accrual_reversal, true_up, reclass or one-off-looking labels inside these months move the trailing average the outlook extends"}

    def one_offs(self, items):
        """The memos behind each one-off in the register: what the posting person called the month's amount."""
        out = []
        ds = self.model.display_sign
        sec = {a["id"]: a["section"] for a in self.model.mapped}
        for x in items:
            k = x["month_idx"]
            if k not in self.months:
                continue
            tot = sum(v[0] for v in self.cells.get((x["account"], k), {}).values())
            t = self.table([x["account"]], (k, k), None, ds[sec[x["account"]]], tot, None, False, 3)
            out.append({"id": f"{x['account']}@{x['month']}", "account": x["account"], "month": x["month"], "themes": t["themes"]})
        return out

    def restricted_terms(self, vocabulary):
        """Proper names in the memos: capitalised words that are not chart-of-accounts words, words of the engine's own
        prose or the skill's reference documents, or common accounting words (vendors, customers, people, places,
        systems, acronyms). A word written in lower case somewhere in a memo is not exempt: names are often typed that way."""
        labels = {lab for cells in self.cells.values() for c in cells.values() for lab in c[2]}
        vocab = {w.lower() for w in vocabulary} | COMMON | set(MONTHS)
        known = lambda w: any(x in vocab for x in (w, w[:-1] if w.endswith("s") else None, w[:-2] if w.endswith("es") else None, w[:-3] + "y" if w.endswith("ies") else None) if x)
        terms = set()
        for lab in labels:
            for w in WORD.findall(lab):
                if len(w) >= 3 and w[0].isupper() and not known(w.lower()):
                    terms.add(w)
        return sorted(terms)


def build(rows, frame, model, lenses, one_off_items, tol=1.0):
    """Attach lens['memo_evidence'] to every available lens; return the top-level payload['memos'] block."""
    m = Memos(rows, frame, model, tol)
    for L in lenses.values():
        if L.get("available"):
            L["memo_evidence"] = m.lens_block(L)
    vocab = set()
    for a in model.mapped:
        for f in ("name", "l2", "l3", "l4", "l5", "l6"):
            vocab |= set(WORD.findall(str(a.get(f) or ""))) | set(re.findall(r"[A-Za-z]+", str(a.get(f) or "")))
    for d in model.drivers:
        vocab |= set(WORD.findall(d["label"])) | set(re.findall(r"[A-Za-z]+", d["label"]))
    for s in frame.subs:
        vocab |= set(re.findall(r"[A-Za-z]+", s))
    for key in getattr(frame, "dcells", {}):            # class and department names are drill detail on the page
        for name in key[3:5]:
            vocab |= set(WORD.findall(str(name)))
    # the engine's own prose is finance language, not names: its words are allowed
    def words(o):
        if isinstance(o, str):
            vocab.update(w.lower() for w in WORD.findall(o))
        elif isinstance(o, dict):
            for v in o.values():
                words(v)
        elif isinstance(o, list):
            for v in o:
                words(v)
    for L in lenses.values():
        if L.get("available"):
            for k in ("insights", "explanations", "summary", "readout", "story", "patterns", "actions", "kpi_diagnoses"):
                words(L.get(k))
    vocab |= doc_words()
    lab = lambda k: model.f.periods[k]["label"]
    return {"available": True, "source": "FINANCE_ANALYTICS TRANSACTIONS_AND_ADJUSTMENTS.MEMO (NetSuite line memo; adjustment reason on manual adjustments)",
            "months": [lab(k) for k in sorted(m.months)], "reconciliation": {"account_months_checked": m.checked, "tolerance": tol, "result": "PASS"},
            "dropped": m.dropped, "run_rate": m.run_rate(lenses[f"MTD_py"]["drivers"] if lenses.get("MTD_py", {}).get("available") else model.drivers),
            "one_offs": m.one_offs(one_off_items), "restricted_terms": m.restricted_terms(vocab),
            "use": "evidence for the review: what the person who posted the lines called them. Describe themes in accounting words; never quote "
                   "a memo, a name (vendor, customer, person, system) or a document number. A memo is not a verified cause."}
