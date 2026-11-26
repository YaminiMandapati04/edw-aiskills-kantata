"""GTM payload builder.

Reads the governed inputs from live.load() (GTM_ANALYTICS extracts), or a workbook
laid out as in references/local-mode.md shaped into the same inputs, and emits the
payload the renderer displays (contract sda.gtm-analysis/2.0.0):

  * bookings lenses for Month, Quarter to date and Last twelve months, each
    against the same months one quarter earlier (Year to date is not built: it
    has no prior-quarter equivalent): KPIs, drivers by measure, product and
    subsidiary, three reconciled bridges, concentration;
  * monthly series and per-driver signals (usual range, deviation, new level,
    seasonal echo) at the as-of month;
  * conversion per window (win rate, won and lost ACV, loss reasons, sources);
  * the open pipeline at the as-of date: open pipeline by expected close quarter,
    stage mix, stage age, past-due and aged deals (no targets: the view has none);
  * a mechanical scenario for the current and next quarter (credit 0);
  * insights, proposed actions, QC and the analysis hash.

Every reportable figure is computed here. Prose is composed from these figures
only, with negatives in brackets and mn / k scale. Quarters and years are fiscal:
Yes Energy's fiscal year is the calendar year, 1 January to 31 December (common.FY_START_MONTH)."""
import datetime as dt
import re

from openpyxl import load_workbook

from . import CONTRACT_VERSION, RENDERER_VERSION
from .common import BuildError, is_num, mean, median, month_add, month_end, safe_div, sha256_of, slug, stdev, to_date, to_num
from .common import FY_START_MONTH, fy_of, fy_start, is_quarter_end, qlabel, qstart
from .common import money as _money, pct as _pct

# Recurring bookings are Salesforce closed-won opportunity lines, split by BOOKING_METRIC: ARR (New) (New Customer
# opportunities) -> arr_new, ARR (Upsell) (Upgrade, Renewal and Downgrade opportunities) -> arr_upsell. Non-recurring
# bookings are NetSuite one-time services revenue from the GL (BOOKING_METRIC = Non-Recurring).
MEASURES = [("arr_new", "New ARR", "ARR (New)"), ("arr_upsell", "Upsell ARR", "ARR (Upsell)"),
            ("non_recurring", "Non-recurring", "Non-Recurring Bookings")]
METRIC_TO_MEASURE = {m[2]: m[0] for m in MEASURES} | {"Non-Recurring": "non_recurring"}
RECURRING_METRICS = ("Recurring Bookings",)   # a line-level recurring metric with no ARR split (legacy extracts only)
NO_ACCOUNT, NO_SUBSIDIARY, NO_PRODUCT = "No account (non-recurring)", "No subsidiary (recurring)", "No product (non-recurring)"
WINDOWS = ["MTD", "QTD", "YTD", "LTM"]
WINDOW_LABELS = {"MTD": "Month", "QTD": "Quarter to date", "YTD": "Year to date", "LTM": "Last twelve months"}
# Compare basis: each window against the same months one quarter earlier (Oct 2026 → Jul 2026); lenses are <WINDOW>_pq.
# Fiscal quarters are three-month blocks, so a quarter to date shifted back three months is the prior fiscal quarter to date.
# Year to date (from 1 January) has no prior-quarter equivalent, so it is not built as a lens.
BASIS = "pq"
PQ_WINDOWS = ("MTD", "QTD", "LTM")
CMP_SHORT = "last quarter"
LATE_STAGE_ORDER = 5              # Align onwards (STAGE_ORDER 1 = Stage 0 ... 5 = Align, 6 = Validate, 7 = Invest)
AGED_MULTIPLE = 2.0               # open deal older than 2x the typical days for its stage
MIN_CLOSED_FOR_RATE = 8           # fewer closed deals than this: win rate shown, not read as a finding
RR_MONTHS = 6
# pipeline risk (references/dashboards.md "Facts of the live view")
STUCK_MULTIPLE = 2.0              # open deal in its stage longer than 2x the median stay of other customers' deals
MIN_STAYS = 5                     # fewer completed stays than this in a stage: no median, nothing flagged
MIN_STAY_DAYS = 1                 # same-day pass-throughs (0 days) are not stays: half the live history is such hops
BREADTH_SHARE = 0.60              # "broad-based" only when at least 60% of subsidiaries and of products with prior-quarter bookings are up
MIN_P90_RUNS = 30                 # stage-age benchmark: fewer non-zero completed runs than this -> "not tested"
HIGH_VALUE_ACV = 100000.0         # velocity split: won deals of $100k ACV or more (fixed, so the live extract can band in SQL)
CLOSED_STAGES = {"07 - CLOSE (WON)", "07 - CLOSE (LOST)", "Closed Won", "Closed Lost", "Closed"}
# one-off product families: their ACV is excluded from recurring ACV. Yes Energy opportunity ACV is the estimated
# product ARR change of each line, so none is one-off.
ONE_OFF_FAMILIES = ()
_ONE_OFF = {f.lower() for f in ONE_OFF_FAMILIES}


# ------------------------------------------------------------------ wording
def money(v, sign=False):
    """Bracketed negatives for prose: −$76k -> ($76k)."""
    s = _money(v, sign=sign)
    return f"({s[1:]})" if s.startswith("−") else s


def pct(v, sign=False, dec=1):
    s = _pct(v, sign=sign, dec=dec)
    return f"({s[1:]})" if s.startswith("−") else s


def pts(v):
    if not is_num(v):
        return "—"
    b = round(abs(v) * 10000)
    if b == 0:
        return "0 bps"
    return f"({b:,}) bps" if v < 0 else f"+{b:,} bps"


def mult(v):
    return "—" if not is_num(v) else f"{v:.1f}×"


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _sub_state(inp, a, b, total):
    """Bookings in the window by NetSuite subscription state, at line grain: positive lines, reversals (negative lines) and net.
    Facts only: the state is the subscription's state today, not at booking, so it reads as where the booked value now stands."""
    agg = {}
    for r in inp["sub_state"]:
        if a <= r["m"] <= b:
            t = agg.setdefault(r["state"], {"pos": 0.0, "rev": 0.0, "rev_lines": 0, "lines": 0, "net": 0.0})
            for k in t:
                t[k] += r[k]
    if not agg:
        return None
    rows = [{"state": k, **{kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}} for k, v in agg.items()]
    rows.sort(key=lambda r: -r["pos"])
    T = {k: round(sum(r[k] for r in rows), 2) for k in ("pos", "rev", "net", "rev_lines", "lines")}
    out = {"rows": rows, "total": T, "control": round(T["net"] - total, 2),
           "rule": "booking lines in the window grouped by SUBSCRIPTION_STATE (the subscription's state today); positive = lines above 0, "
                   "reversals = lines below 0, net = both; ties to total bookings"}
    bullets = []
    neg = [r for r in rows if r["net"] < -0.5]
    big = min(rows, key=lambda r: r["rev"])
    if big["rev"] < -0.5 and T["rev"] < -0.5:
        if len(neg) == 1 and neg[0]["state"] == big["state"]:
            only = " It is the only status with a negative net."
        else:
            only = f" Negative net: {join_and([r['state'] for r in neg])}." if neg else ""
        bullets.append({"head": f"{big['state']} carries the reversals.",
                        "text": f"{big['state']} holds {money(big['rev'])} of the {money(T['rev'])} reversals ({pct(big['rev'] / T['rev'], dec=0)}).{only}"})
    cus = {}
    for r in inp.get("state_customer") or []:
        if a <= r["m"] <= b:
            c = cus.setdefault(r["customer"], {})
            t = c.setdefault(r["state"], {"pos": 0.0, "rev": 0.0, "net": 0.0})
            for k in t:
                t[k] += r[k]
    top = []
    for name, st in cus.items():
        rev = sum(v["rev"] for v in st.values())
        if rev < -0.5:
            top.append({"customer": name, "rev": round(rev, 2), "pos": round(sum(v["pos"] for v in st.values()), 2),
                        "net": round(sum(v["net"] for v in st.values()), 2), "share": round(rev / T["rev"], 4) if T["rev"] else None,
                        "by_state": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in st.items()}})
    top.sort(key=lambda c: c["rev"])
    out["top_customers"] = top[:5]
    if top and is_num(top[0]["share"]) and top[0]["share"] >= 0.2:
        c = top[0]
        ps = max(c["by_state"].items(), key=lambda kv: kv[1]["pos"])
        rs = min(c["by_state"].items(), key=lambda kv: kv[1]["rev"])
        if abs(c["net"]) < 0.25 * abs(c["rev"]):
            txt = (f"{c['customer']}: {money(c['rev'])} of reversals, mostly in {rs[0]} ({money(-rs[1]['rev'])} of it), against "
                   f"{money(ps[1]['pos'])} of positive lines in {ps[0]}; its net for the window is {money(c['net'])}, "
                   "so most of it is the same contracts re-papered, not lost value.")
        else:
            txt = f"{c['customer']}: {money(c['rev'])} of reversals, mostly in {rs[0]}; its net for the window is {money(c['net'])}."
        bullets.append({"head": f"One customer is {pct(c['share'], dec=0)} of the reversals.", "text": txt})
    pend = next((r for r in rows if r["state"] == "Active/Renewal Pending"), None)
    if pend and pend["net"] > 0.5 and T["net"] > 0.5:
        bullets.append({"head": "Renewal is due on a large share.",
                        "text": f"{money(pend['net'])} of the window's net bookings ({pct(pend['net'] / T['net'], dec=0)}) "
                                "sits on subscriptions now in Active/Renewal Pending."})
    ren = next((r for r in rows if r["state"] == "Renewed"), None)
    if ren is not None and T["net"] > 0.5:
        bullets.append({"head": "Little is marked renewed.",
                        "text": f"Lines on subscriptions marked Renewed total {money(ren['net'])} in the window ({pct(ren['net'] / T['net'], dec=0)} of net)."})
    out["bullets"] = bullets
    return out


def join_and(xs):
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + " and " + xs[-1] if xs else "")


def month_name(d):
    return d.strftime("%B")


# ------------------------------------------------------------------ loading
def _norm(s):
    return re.sub(r"[^0-9A-Za-z_]+", "_", str(s).strip()).strip("_").upper()


def read_workbook(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        name = _norm(ws.title)
        if name.startswith("README") or name.startswith("_"):
            continue
        rows = ws.iter_rows(values_only=True)
        hdr = next(rows, None)
        if not hdr:
            continue
        keys = [_norm(h) for h in hdr]
        out[name] = [dict(zip(keys, r)) for r in rows if any(v is not None for v in r)]
    for need in ("BOOKING_LINES", "OPPORTUNITIES"):
        if need not in out:
            raise BuildError(f"workbook has no {need} sheet (see references/local-mode.md)")
    return out


# ------------------------------------------------------------------ windows
def window_months(as_of, w):
    if w == "MTD":
        return as_of, as_of
    if w == "QTD":
        return qstart(as_of), as_of
    if w == "YTD":
        return fy_start(as_of), as_of
    return month_add(as_of, -11), as_of


def shift_year(d, n=-1):
    return dt.date(d.year + n, d.month, 1)


def shift_quarter(d, n=-1):
    """The same month n quarters away: the Compare basis (Oct 2026 → Jul 2026)."""
    return month_add(d, 3 * n)


def in_months(d, a, b):
    m = dt.date(d.year, d.month, 1)
    return a <= m <= b


def range_label(a, b):
    if a == b:
        return a.strftime("%b %Y")
    return f"{a.strftime('%b %Y')} – {b.strftime('%b %Y')}"


def stage_order_of(name):
    """STAGE_ORDER from a numbered stage name prefix (NN - NAME = NN + 1); 99 when there is no prefix. Yes Energy stages
    (Stage 0, Proposed Renewal, Qualify ... Invest) carry no prefix: their order comes from DIM_STAGE_MAPPING.STAGE_ORDER."""
    m = re.match(r"^(\d{2})\s*-", str(name or ""))
    return int(m.group(1)) + 1 if m else 99


def measure_of(metric, otype):
    """Booking metric (and, for recurring lines, the opportunity type) -> measure id; None for a blank metric."""
    m = str(metric or "").strip()
    if m in RECURRING_METRICS:
        t = str(otype or "").strip().lower()
        if t.startswith("new"):
            return "arr_new"
        if "expansion" in t or t.startswith("seat") or t.startswith("upsell"):
            return "arr_upsell"
        if t in ("upgrade", "renewal", "downgrade"):
            return "arr_upsell"
        raise BuildError(f"recurring booking line with opportunity type {otype!r}: expected New Customer, Upgrade, Renewal or Downgrade")
    return METRIC_TO_MEASURE.get(m)


def _true(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def _from_workbook(wb, product=None):
    """Local test mode: shape the workbook into the inputs the governed loader (live.py) produces.
    Counts are distinct opportunities, as the governed WON_ / LOST_ / CREATED metrics count."""
    opps = []
    for r in wb["OPPORTUNITIES"]:
        if int(to_num(r.get("IS_RENEWAL")) or 0) == 1:
            continue
        if product and r.get("PRODUCT") != product:
            continue
        opps.append({"id": str(r["OPPORTUNITY_ID"]), "name": str(r.get("OPPORTUNITY_NAME") or ""), "owner": str(r.get("OWNER_NAME") or ""),
                     "product": str(r.get("PRODUCT") or ""), "source": str(r.get("OPPORTUNITY_SOURCE") or r.get("DEAL_SOURCE") or "Unknown"),
                     "status": str(r.get("STATUS") or ""),
                     "stage": str(r.get("STAGE_NAME") or ""), "stage_order": int(to_num(r.get("STAGE_ORDER")) or 99),
                     "close": to_date(r["CLOSE_DATE"]) if r.get("CLOSE_DATE") else None,
                     "ecq": qlabel(to_date(r["CLOSE_DATE"])) if r.get("CLOSE_DATE") else "",
                     "created": to_date(r["PIPELINE_CREATION_DATE"]) if r.get("PIPELINE_CREATION_DATE") else None,
                     "opened": to_date(r["CREATED_DATE"]) if r.get("CREATED_DATE") else None,
                     "acv": to_num(r.get("ACV_USD")) or 0.0, "probability": to_num(r.get("PROBABILITY")),
                     "loss": str(r.get("LOSS_REASON") or "") or None,
                     "account": str(r.get("ACCOUNT_NAME") or "") or None, "family": r.get("PRODUCT_FAMILY"),
                     "stype": r.get("OPPORTUNITY_TYPE") or r.get("SUBSCRIPTION_TYPE"),
                     "refreshed": to_date(r["DATA_REFRESHED_AT"]) if r.get("DATA_REFRESHED_AT") else None})
    agg = {}
    for o in opps:
        if not o["close"] or o["status"] not in ("Closed Won", "Closed Lost"):
            continue
        m, won = dt.date(o["close"].year, o["close"].month, 1), o["status"] == "Closed Won"
        keys = [("source", o["source"]), ("product", o["product"])] + ([("loss", o["loss"] or "Not given")] if not won else [])
        for dim, label in keys:
            a = agg.setdefault((m, dim, label), {"won_acv": 0.0, "lost_acv": 0.0, "won": set(), "lost": set()})
            a["won_acv" if won else "lost_acv"] += o["acv"]
            a["won" if won else "lost"].add(o["id"])
    closed = [{"m": m, "dim": dim, "label": label, "won_acv": a["won_acv"], "lost_acv": a["lost_acv"], "won_n": len(a["won"]), "lost_n": len(a["lost"])}
              for (m, dim, label), a in agg.items()]
    cr = {}
    for o in opps:
        if o["created"]:
            c = cr.setdefault(dt.date(o["created"].year, o["created"].month, 1), {"acv": 0.0, "ids": set()})
            c["acv"] += o["acv"]
            c["ids"].add(o["id"])
    created = [{"m": m, "acv": c["acv"], "n": len(c["ids"])} for m, c in cr.items()]
    # stage history as the view keeps it: one row per opportunity per stage run (STAGE_RUN_NO), with the close date
    # at the end of each run and the stage STATUS; days in a run = STAGE_END_DATE - STAGE_START_DATE
    hist = sorted(wb.get("OPPORTUNITY_STAGE_HISTORY", []), key=lambda h: (str(h["OPPORTUNITY_ID"]), to_num(h.get("STAGE_RUN_NO")) or 0))

    def run_days(h):
        s, e = h.get("STAGE_START_DATE"), h.get("STAGE_END_DATE")
        return (to_date(e) - to_date(s)).days if s and e else None
    open_ids = {o["id"] for o in opps if o["status"] == "Open"}
    lost_ids = {o["id"] for o in opps if o["status"] == "Closed Lost"}
    typical = {}
    for h in hist:
        if is_num(run_days(h)):
            typical.setdefault(str(h["STAGE_NAME"]), []).append(run_days(h))
    cur_start = {str(h["OPPORTUNITY_ID"]): to_date(h["STAGE_START_DATE"]) for h in hist
                 if _true(h.get("IS_CURRENT_STAGE")) and str(h["OPPORTUNITY_ID"]) in open_ids}
    # risk inputs, in the shape live.load() produces
    runs = [{"opp": str(h["OPPORTUNITY_ID"]), "no": h.get("STAGE_RUN_NO"), "stage": str(h["STAGE_NAME"]), "days": run_days(h)}
            for h in hist if is_num(run_days(h))]
    close_hist, lost_at = {}, {}
    for h in hist:
        k = str(h["OPPORTUNITY_ID"])
        if k in open_ids:
            close_hist.setdefault(k, []).append(to_date(h["CLOSE_DATE"]) if h.get("CLOSE_DATE") else None)
        if k in lost_ids and str(h.get("STATUS")) == "Open":
            lost_at[k] = str(h["STAGE_NAME"])      # runs are in order: the last open run is the stage the deal was lost at
    lost_lines = [{"id": o["id"], "name": o["name"], "account": o["account"], "owner": o["owner"], "product": o["product"], "family": o["family"],
                   "stype": o["stype"], "source": o["source"], "reason": o["loss"], "close": o["close"], "acv": o["acv"],
                   "lost_stage": lost_at.get(o["id"]) or (o["stage"] if o["stage"] not in CLOSED_STAGES else None)}
                  for o in opps if o["status"] == "Closed Lost"]
    won = {}
    for o in opps:
        start = o["opened"] or o["created"]
        if o["status"] == "Closed Won" and o["close"] and start:
            w = won.setdefault(o["id"], {"close": o["close"], "created": start, "acv": 0.0})
            w["acv"] += o["acv"]
            w["created"] = min(w["created"], start)
    velocity = velocity_rows([{"m": dt.date(w["close"].year, w["close"].month, 1), "days": (w["close"] - w["created"]).days, "acv": w["acv"]}
                              for w in won.values()])
    # booking lines under the view's names (BOOKING_DATE, ACCOUNT_NAME, OPPORTUNITY_ID) shaped to the engine's keys, as live.load() does
    lines = [{"BOOKINGS_DATE": r.get("BOOKING_DATE") or r.get("BOOKINGS_DATE"), "BOOKING_METRIC": r.get("BOOKING_METRIC"),
              "OPPORTUNITY_TYPE": r.get("OPPORTUNITY_TYPE"), "BOOKING_ACV_USD": r.get("BOOKING_ACV_USD"), "PRODUCT": r.get("PRODUCT"),
              "SUBSIDIARY_NAME": r.get("SUBSIDIARY_NAME"), "COMPANY_NAME": r.get("ACCOUNT_NAME") or r.get("COMPANY_NAME"),
              "SOURCE_ORDER": r.get("OPPORTUNITY_ID") or r.get("SOURCE_ORDER")} for r in wb["BOOKING_LINES"]]
    # open pipeline is weighted, as live.load() hands it over: ACV x PROBABILITY / 100 (created, won and lost stay unweighted)
    def weighted(o):
        p = o.get("probability")
        return dict(o, acv=o["acv"] * p / 100 if is_num(p) else o["acv"], acv_unweighted=o["acv"])
    return {"lines": lines, "open_deals": [weighted(o) for o in opps if o["status"] == "Open"], "closed": closed, "created": created,
            "velocity": velocity,
            "stage_days": {k: round(mean(v), 1) for k, v in typical.items()}, "cur_start": cur_start,
            "cards": None, "bookings_mart": None, "loss_reasons_available": any(o["loss"] for o in opps), "late_stage_order": LATE_STAGE_ORDER,
            "stage_runs": runs, "accounts": {o["id"]: o["account"] for o in opps if o["account"]}, "close_hist": close_hist, "lost_lines": lost_lines,
            "refreshed": max([o["refreshed"] for o in opps if o["refreshed"]] or [None], key=lambda d: d or dt.date.min)}


# ------------------------------------------------------------------ velocity
def velocity_rows(per_opp):
    """Closed-won opportunities -> monthly rows by size band: {m, band, n, sum_days, acv}. The live extract
    (gtm-velocity) arrives in this shape already, banded at HIGH_VALUE_ACV in Snowflake."""
    agg = {}
    for w in per_opp:
        if not is_num(w.get("days")) or w["days"] < 0 or (w.get("acv") or 0.0) <= 0:
            continue                    # credits and zero-ACV wins are not conversions
        k = (w["m"], "hv" if (w.get("acv") or 0.0) >= HIGH_VALUE_ACV else "std")
        a = agg.setdefault(k, {"m": k[0], "band": k[1], "n": 0, "sum_days": 0.0, "acv": 0.0, "same_day": 0})
        if w["days"] < 1:               # created and won on the day (store orders, quotes): no sales cycle to measure
            a["same_day"] += 1
            continue
        a["n"] += 1
        a["sum_days"] += w["days"]
        a["acv"] += w.get("acv") or 0.0
    return list(agg.values())


def _velocity(rows, a, b):
    """Average days from opportunity created to closed won, for deals won in months a..b (count-weighted)."""
    def part(rs):
        n = sum(r["n"] for r in rs)
        return {"n": n, "avg_days": round(sum(r["sum_days"] for r in rs) / n, 1) if n else None, "acv": round(sum(r["acv"] for r in rs), 2),
                "same_day": sum(r.get("same_day", 0) for r in rs)}
    rs = [r for r in rows if a <= r["m"] <= b]
    return dict(part(rs), hv=part([r for r in rs if r["band"] == "hv"]), std=part([r for r in rs if r["band"] == "std"]))


# ------------------------------------------------------------------ pipeline risk
def is_one_off(family):
    return str(family or "").strip().lower() in _ONE_OFF


def _split(acv, family, stype):
    """Recurring ACV of one line and its kind (new / upsell / unsplit); one-off families carry none."""
    if is_one_off(family):
        return 0.0, None
    s = str(stype or "").strip().lower()
    return acv, ("new" if s.startswith("new") else "upsell" if s else "unsplit")


def _roll_up(rows):
    """Lines -> one record per opportunity: ACV and recurring ACV (new / upsell / unsplit) summed over its lines."""
    deals = {}
    for o in rows:
        d = deals.get(o["id"])
        if d is None:
            d = deals[o["id"]] = {k: o.get(k) for k in ("id", "name", "account", "owner", "source", "stage", "stage_order", "close", "ecq", "reason", "lost_stage")}
            d.update(products=[], acv=0.0, recurring=0.0, rec={"new": 0.0, "upsell": 0.0, "unsplit": 0.0})
        a = o.get("acv") or 0.0
        d["acv"] += a
        r, kind = _split(a, o.get("family"), o.get("stype"))
        if kind:
            d["recurring"] += r
            d["rec"][kind] += r
        if o.get("product") and o["product"] not in d["products"]:
            d["products"].append(o["product"])
    return list(deals.values())


def _block(ds, base_acv=None):
    acv, rec = sum(d["acv"] for d in ds), sum(d["recurring"] for d in ds)
    out = {"count": len(ds), "acv": round(acv, 2), "recurring": round(rec, 2),
           "new": round(sum(d["rec"]["new"] for d in ds), 2), "upsell": round(sum(d["rec"]["upsell"] for d in ds), 2),
           "unsplit": round(sum(d["rec"]["unsplit"] for d in ds), 2)}
    if base_acv is not None:
        out["share"] = round(acv / base_acv, 4) if base_acv else None
    return out


def _group(ds, key, missing):
    g = {}
    for d in ds:
        g.setdefault(d.get(key) or missing, []).append(d)
    tot = sum(d["acv"] for d in ds)
    return sorted([dict(_block(v), id=slug(k), label=k, share=round(sum(d["acv"] for d in v) / tot, 4) if tot else None) for k, v in g.items()],
                  key=lambda r: (-r["acv"], r["label"]))


def _deal_out(d):
    iso = lambda x: x.isoformat() if x else None
    flags = (["past due"] if d.get("past_due") else []) + ([f"pushed ×{d['pushes']}"] if d.get("pushes") else []) + (["stuck"] if d.get("stuck") else [])
    return {"id": d["id"], "name": d["name"], "account": d.get("account") or "Unknown account", "owner": d.get("owner"), "product": ", ".join(d["products"]),
            "source": d.get("source"), "stage": d.get("stage"), "close": iso(d.get("close")), "orig_close": iso(d.get("orig_close")),
            "pushes": d.get("pushes"), "days_overdue": d.get("days_overdue"), "age_days": d.get("age"), "median_days": d.get("median"),
            "ratio": d.get("ratio"), "acv": round(d["acv"], 2), "recurring": round(d["recurring"], 2), "new": round(d["rec"]["new"], 2),
            "upsell": round(d["rec"]["upsell"], 2), "flags": flags}


def _stage_medians(inp):
    """(overall, loo): overall = {stage: (median days, stays)}; loo(stage, account) = the median of other accounts' stays.
    Live: precomputed in Snowflake (gtm-stage-medians). Local: from the completed stays, one per opportunity and
    stage change (the history repeats each change per product). Stays shorter than MIN_STAY_DAYS are left out."""
    sm = inp.get("stage_medians")
    if sm:
        overall, per = sm.get("overall") or {}, sm.get("loo") or {}

        def loo(stage, acct):
            m, n = per.get((stage, acct)) or overall.get(stage) or (None, 0)
            return m if n >= MIN_STAYS else None
        return overall, loo
    seen, by_stage = set(), {}
    accounts = inp.get("accounts") or {}
    for r in inp.get("stage_runs") or []:
        k = (r["opp"], r.get("no"), r["stage"])
        if k in seen or r["stage"] in CLOSED_STAGES or not is_num(r.get("days")) or r["days"] < MIN_STAY_DAYS:
            continue
        seen.add(k)
        by_stage.setdefault(r["stage"], []).append((accounts.get(r["opp"]), float(r["days"])))
    overall = {sn: (median([x for _, x in v]), len(v)) for sn, v in by_stage.items()}

    def loo(stage, acct):
        xs = [days for a, days in by_stage.get(stage, []) if a is None or a != acct]
        return median(xs) if len(xs) >= MIN_STAYS else None
    return overall, loo


def _risk(inp, open_lines, data_asof, as_of, overall, loo):
    deals = _roll_up(open_lines)
    open_acv = sum(d["acv"] for d in deals)
    hist = inp.get("close_hist") or {}
    cur_start = inp.get("cur_start") or {}
    p90 = inp.get("stage_p90")

    for d in deals:
        seq = [x for x in (hist.get(d["id"], []) + [d["close"]]) if x]
        d["pushes"] = sum(1 for a, b in zip(seq, seq[1:]) if b > a)
        d["orig_close"] = seq[0] if seq else None
        d["past_due"] = bool(d["close"] and d["close"] < data_asof)
        d["days_overdue"] = (data_asof - d["close"]).days if d["past_due"] else None
        d["not_closing"] = d["past_due"] or d["pushes"] >= 1
        st = cur_start.get(d["id"])
        d["age"] = (data_asof - st).days if st else None
        if p90 is not None:
            b = p90.get(d["stage"])
            med = b["p90"] if b and b["runs"] >= MIN_P90_RUNS and is_num(b["p90"]) else None
            mult_ = 1.0
        else:
            med, mult_ = loo(d["stage"], d.get("account")), STUCK_MULTIPLE
        d["median"] = round(med, 1) if med is not None else None
        d["ratio"] = round(d["age"] / med, 2) if (med and d["age"] is not None) else None
        d["stuck"] = bool(is_num(d["ratio"]) and d["ratio"] > mult_)
    by_rec = lambda d: (-d["recurring"], -d["acv"], d["id"])

    # 1. deals not closing
    nc = [d for d in deals if d["not_closing"]]
    not_closing = dict(_block(nc, open_acv), rule="open deals past their expected close date, or whose close date has been pushed out at least once",
                       pushes_available=bool(hist), past_due=_block([d for d in deals if d["past_due"]], open_acv),
                       pushed=_block([d for d in deals if d["pushes"] >= 1], open_acv),
                       by_stage=sorted(_group(nc, "stage", "Unknown"), key=lambda r: next((d["stage_order"] for d in nc if d["stage"] == r["label"]), 99)),
                       by_owner=_group(nc, "owner", "Unassigned"), deals=[_deal_out(d) for d in sorted(nc, key=by_rec)[:25]])

    # 2. customers stuck in a stage
    stuck = [d for d in deals if d["stuck"]]
    cust = {}
    for d in stuck:
        cust.setdefault(d.get("account") or "Unknown account", []).append(d)
    customers = sorted([dict(_block(v), id=slug(k), customer=k, stages=sorted({d["stage"] for d in v}, key=lambda s: next(d["stage_order"] for d in v if d["stage"] == s)),
                             max_ratio=max(d["ratio"] for d in v), longest_days=max(d["age"] for d in v),
                             deals=[_deal_out(d) for d in sorted(v, key=by_rec)]) for k, v in cust.items()],
                       key=lambda r: (-r["recurring"], -r["acv"], r["customer"]))
    stage_rows = []
    for so, sn in sorted({(d["stage_order"], d["stage"]) for d in deals}):
        if p90 is not None:
            b = p90.get(sn) or {}
            n_stays = b.get("runs", 0)
            med = b.get("p90") if n_stays >= MIN_P90_RUNS else None
        else:
            med, n_stays = overall.get(sn) or (None, 0)
            med = med if n_stays >= MIN_STAYS else None
        in_stage = [d for d in deals if d["stage"] == sn]
        st_d = [d for d in in_stage if d["stuck"]]
        stage_rows.append({"id": slug(sn), "stage": sn, "order": so, "stays": n_stays, "median_days": round(med, 1) if med is not None else None,
                           "threshold_days": round((1.0 if p90 is not None else STUCK_MULTIPLE) * med, 1) if med is not None else None, "open_deals": len(in_stage),
                           "stuck_deals": len(st_d), "stuck_acv": round(sum(d["acv"] for d in st_d), 2),
                           "stuck_recurring": round(sum(d["recurring"] for d in st_d), 2)})
    stuck_rule = (f"current stage older than the 90th percentile of completed stays in that stage (non-zero stays of pipeline stages ending in the last 24 months; "
                  f"at least {MIN_P90_RUNS} stays, else not tested)" if p90 is not None else
                  f"current stage older than {STUCK_MULTIPLE:.0f}× the median completed stay in that stage across other customers' deals")
    stuck_v = dict(_block(stuck, open_acv), rule=stuck_rule, benchmark="p90" if p90 is not None else "median",
                   multiple=1.0 if p90 is not None else STUCK_MULTIPLE, min_stays=MIN_STAYS, min_stay_days=MIN_STAY_DAYS, customer_count=len(customers), customers=customers[:20],
                   stages=stage_rows, available=bool(overall) and bool(cur_start))

    # 3. high-value opportunities: ACV of HIGH_VALUE_ACV or more, the same line as the velocity split, so every
    #    high-value card on the page reads one population
    cutoff = HIGH_VALUE_ACV
    hv = sorted([d for d in deals if d["acv"] >= cutoff], key=lambda d: (-d["acv"], d["id"]))
    hv_acv = sum(d["acv"] for d in hv)
    hv_flag = [d for d in hv if d["not_closing"] or d["stuck"]]
    hv_nc = [d for d in hv if d["not_closing"]]
    hv_st = [d for d in hv if d["stuck"]]
    by_stage_of = lambda ds: sorted(_group(ds, "stage", "Unknown"), key=lambda r: next((d["stage_order"] for d in ds if d["stage"] == r["label"]), 99))
    hv_cust = sorted({d.get("account") or "Unknown account" for d in hv_st})
    high_value = dict(_block(hv, open_acv), rule=f"open deals of {money(HIGH_VALUE_ACV)} ACV or more",
                      cutoff=round(cutoff, 2), flagged=dict(_block(hv_flag, open_acv), share_of_hv=round(sum(d["acv"] for d in hv_flag) / hv_acv, 4) if hv_acv else None),
                      not_closing=dict(_block(hv_nc, open_acv), share_of_hv=round(sum(d["acv"] for d in hv_nc) / hv_acv, 4) if hv_acv else None,
                                       past_due=_block([d for d in hv_nc if d["past_due"]]), pushed=_block([d for d in hv_nc if d["pushes"] >= 1]),
                                       by_stage=by_stage_of(hv_nc), by_owner=_group(hv_nc, "owner", "Unassigned"),
                                       deals=[_deal_out(d) for d in sorted(hv_nc, key=lambda d: (-d["acv"], d["id"]))]),
                      stuck=dict(_block(hv_st, open_acv), share_of_hv=round(sum(d["acv"] for d in hv_st) / hv_acv, 4) if hv_acv else None,
                                 customer_count=len(hv_cust), by_stage=by_stage_of(hv_st),
                                 deals=[_deal_out(d) for d in sorted(hv_st, key=lambda d: (-d["acv"], d["id"]))]),
                      deals=[_deal_out(d) for d in hv])

    # 4. everything flagged (not closing or stuck), by stage, for the tab's chart
    flag = [d for d in deals if d["not_closing"] or d["stuck"]]
    at_risk = dict(_block(flag, open_acv), rule="open deals that are not closing or stuck",
                   by_stage=sorted(_group(flag, "stage", "Unknown"), key=lambda r: next((d["stage_order"] for d in flag if d["stage"] == r["label"]), 99)))

    # insights and actions for the tab (prose from the figures above only)
    split_ok = any(str(o.get("stype") or "").strip() for o in open_lines)
    ins = []
    if nc:
        ins.append({"id": "not_closing", "tone": "unf", "ref": "risk:not_closing", "head": "Deals are not closing.",
                    "text": f"{plural(len(nc), 'open deal')} {'is' if len(nc) == 1 else 'are'} past their close date or pushed out: {money(not_closing['acv'])} ACV, "
                            f"{pct(not_closing['share'], dec=0)} of open pipeline at {data_asof.isoformat()}, of which {money(not_closing['recurring'])} is recurring"
                            + (f" ({money(not_closing['new'])} new, {money(not_closing['upsell'])} upsell)" if split_ok else "")
                            + f"; {not_closing['past_due']['count']} past due, {not_closing['pushed']['count']} pushed out."})
    if customers:
        top = customers[:2]
        ins.append({"id": "stuck", "tone": "unf", "ref": "risk:stuck", "head": "Customers stuck in the funnel.",
                    "text": f"{plural(len(customers), 'customer')} {'has' if len(customers) == 1 else 'have'} deals in their stage "
                            + ("longer than 90% of completed stays in that stage (P90)" if p90 is not None else f"more than {mult(STUCK_MULTIPLE)} the usual stay")
                            + f": {money(stuck_v['recurring'])} recurring ACV at stake if they don't convert. "
                            f"Largest: {join_and([c['customer'] + ' (' + money(c['recurring']) + ', ' + join_and(c['stages']) + ')' for c in top])}."})
    if hv:
        ins.append({"id": "high_value", "tone": "unf" if hv_flag else "neu", "ref": "risk:high_value", "head": "High-value deals.",
                    "text": f"Open deals of {money(cutoff)} ACV or more hold {money(high_value['acv'])}, "
                            f"{pct(high_value['share'], dec=0)} of open pipeline at {data_asof.isoformat()}; {len(hv_flag)} of the {len(hv)}, {money(high_value['flagged']['acv'])}, "
                            f"{'is' if len(hv_flag) == 1 else 'are'} not closing or stuck."})
    due = (month_end(as_of) + dt.timedelta(days=30)).isoformat()
    acts = []
    if nc:
        acts.append({"id": "a:not_closing", "rule": "not_closing_share", "ref": "risk:not_closing",
                     "question": f"Re-qualify or re-date {plural(len(nc), 'deal')} that {'is' if len(nc) == 1 else 'are'} not closing? {money(not_closing['recurring'])} recurring ACV.",
                     "owner": "RevOps with Sales managers", "date": due, "exposure": not_closing["recurring"], "exposure_label": "recurring ACV",
                     "evidence": ["owner confirmation of each deal", "updated close dates", "why each close date moved"]})
    if customers:
        acts.append({"id": "a:stuck", "rule": "stuck_customers", "ref": "risk:stuck",
                     "question": f"Engage the {plural(len(customers), 'customer')} stuck in their stage (largest: {join_and([c['customer'] for c in customers[:2]])})? "
                                 f"{money(stuck_v['recurring'])} recurring ACV at stake.",
                     "owner": "Account executives with Sales leadership", "date": due, "exposure": stuck_v["recurring"], "exposure_label": "recurring ACV at stake",
                     "evidence": ["the blocker on each deal", "a dated next step agreed with the customer"]})
    if hv_flag:
        acts.append({"id": "a:high_value", "rule": "high_value_at_risk", "ref": "risk:high_value",
                     "question": f"Put an executive sponsor on {plural(len(hv_flag), 'high-value deal')} that {'is' if len(hv_flag) == 1 else 'are'} not closing or stuck?",
                     "owner": "Sales leadership", "date": due, "exposure": high_value["flagged"]["acv"], "exposure_label": "ACV",
                     "evidence": ["deal reviews for each", "executive contact on the customer side"]})
    no_family = [o for o in open_lines if ONE_OFF_FAMILIES and (not str(o.get("family") or "").strip() or str(o.get("family")).strip().lower() == "none")]
    return {"as_of": data_asof.isoformat(), "open": {"count": len(deals), "acv": round(open_acv, 2), "recurring": round(sum(d["recurring"] for d in deals), 2),
                                                     "no_family_lines": len(no_family), "no_family_acv": round(sum(o.get("acv") or 0.0 for o in no_family), 2),
                                                     "split_available": any(str(o.get("stype") or "").strip() for o in open_lines)},
            "recurring_rule": ("line ACV excluding one-off product families: " + ", ".join(ONE_OFF_FAMILIES)) if ONE_OFF_FAMILIES else
                              "the opportunity line ACV (estimated product ARR change): all of it is recurring",
            "not_closing": not_closing, "stuck": stuck_v, "high_value": high_value, "at_risk": at_risk, "insights": _add_short(ins), "actions": _add_ask_short(acts),
            "method": "proxy: the view has no activity or next-step data"}


def _lost(lost_deals, a, b, pa, pb, label, cmp_label):
    m = lambda d: dt.date(d.year, d.month, 1)
    cur = [d for d in lost_deals if d["close"] and a <= m(d["close"]) <= b]
    prv = [d for d in lost_deals if d["close"] and pa <= m(d["close"]) <= pb]
    blk, pblk = _block(cur), _block(prv)
    var = round(blk["acv"] - pblk["acv"], 2)
    out = dict(blk, cmp=pblk, variance=var, variance_pct=round(var / pblk["acv"], 4) if pblk["acv"] else None,
               by_reason=_group(cur, "reason", "Not given"), by_stage=_group(cur, "lost_stage", "Unknown"),
               by_product=_group([dict(d, product=", ".join(d["products"])) for d in cur], "product", "Unassigned"), by_source=_group(cur, "source", "Unknown"),
               reason_available=any(d.get("reason") for d in lost_deals), stage_available=any(d.get("lost_stage") for d in lost_deals),
               deals=[dict(_deal_out(d), reason=d.get("reason") or "Not given", lost_stage=d.get("lost_stage") or "Unknown")
                      for d in sorted(cur, key=lambda d: (-d["acv"], d["id"]))[:15]])
    if cur:
        r0 = out["by_reason"][0] if out["reason_available"] else None
        s0 = out["by_stage"][0] if out["stage_available"] else None
        out["headline"] = (f"{plural(len(cur), 'deal')} lost in {label}, {money(blk['acv'])} ACV ({money(blk['recurring'])} recurring), against "
                           f"{money(pblk['acv'])} in {cmp_label}"
                           + (f"; {r0['label']} is the largest reason ({pct(r0['share'], dec=0)} of lost ACV)" if r0 else "")
                           + (f"; most value was lost at {s0['label']} ({pct(s0['share'], dec=0)})" if s0 else "") + ".")
    else:
        out["headline"] = f"No deals lost in {label}."
    return out


# ------------------------------------------------------------------ build
def build(path, as_of=None, window=None, title=None, source=None, data_mode=None, product=None, provenance=None):
    """`path` is a local workbook (test mode) or the inputs dict from live.load() (governed mode)."""
    if isinstance(path, dict):
        inp, data_mode = path, data_mode or "governed"
    else:
        inp, data_mode = _from_workbook(read_workbook(path), product), data_mode or "local"
    governed = data_mode == "governed"
    cards, bmart = inp.get("cards"), inp.get("bookings_mart")
    late_order = inp.get("late_stage_order", LATE_STAGE_ORDER)
    lines = []
    blank_metric = cancels = 0
    for r in inp["lines"]:
        d, v = to_date(r["BOOKINGS_DATE"]), to_num(r.get("BOOKING_ACV_USD"))
        mid = measure_of(r.get("BOOKING_METRIC"), r.get("OPPORTUNITY_TYPE"))
        if v is None:
            continue
        if mid is None:
            blank_metric += 1
            continue
        if product and r.get("PRODUCT") != product:
            continue
        if v < 0:
            cancels += 1
        nr = mid == "non_recurring"
        # NetSuite (non-recurring) lines carry a subsidiary but no account, product or opportunity; Salesforce
        # (recurring) lines carry an account, product and opportunity but no subsidiary
        lines.append({"d": d, "m": dt.date(d.year, d.month, 1), "measure": mid,
                      "product": str(r.get("PRODUCT") or (NO_PRODUCT if nr else "Unassigned")),
                      "sub": str(r.get("SUBSIDIARY_NAME") or (NO_SUBSIDIARY if not nr else "Unassigned")),
                      "cust": str(r.get("COMPANY_NAME") or "") or (None if nr else "Unknown account"),
                      "order": str(r.get("SOURCE_ORDER") or ""), "acv": v})
    if not lines:
        raise BuildError("no booking lines with a booking metric")
    first = min(x["m"] for x in lines)
    last = max(x["m"] for x in lines)
    as_of_note = None
    if not as_of:
        # the bookings month-end is complete only once NetSuite has closed it: a latest month whose non-recurring revenue is
        # below a tenth of its usual level is a month not yet closed, so the analysis steps back to the month before
        nr_of = lambda mm: sum(x["acv"] for x in lines if x["m"] == mm and x["measure"] == "non_recurring")
        prior = [nr_of(month_add(last, -k)) for k in range(1, 7)]
        base = median([v for v in prior if v > 0]) if any(v > 0 for v in prior) else None
        if base and nr_of(last) < 0.1 * base and month_add(last, -1) >= first:
            as_of_note = (f"{last:%B %Y} non-recurring bookings are {money(nr_of(last))} against a usual {money(base)}: NetSuite has not closed the month, "
                          f"so the analysis month is {month_add(last, -1):%B %Y}")
            last = month_add(last, -1)
    as_of = dt.date(int(as_of[:4]), int(as_of[5:7]), 1) if as_of else last
    if as_of < first or as_of > last:
        raise BuildError(f"as-of {as_of:%Y-%m} is outside the booking data ({first:%Y-%m} to {last:%Y-%m})")
    months = []
    m = month_add(as_of, -23) if month_add(as_of, -23) > first else first
    while m <= as_of:
        months.append(m)
        m = month_add(m, 1)
    as_idx = len(months) - 1
    products = sorted({x["product"] for x in lines})
    subs = sorted({x["sub"] for x in lines})

    closed_rows, created_rows = inp["closed"], inp["created"]
    loss_ok = inp.get("loss_reasons_available", False)
    lost_deals = _roll_up(inp.get("lost_lines") or [])
    vel_rows = inp.get("velocity")             # None: not supplied (older extract sets)

    def conv_size(a, b):
        rows = inp.get("conv_size")
        if rows is None:
            return None
        rs = [r for r in rows if a <= r["m"] <= b]
        w, l_ = sum(r["won_pos"] for r in rs), sum(r["lost_pos"] for r in rs)
        w5, l5 = sum(r["won_5k"] for r in rs), sum(r["lost_5k"] for r in rs)
        return {"value_win_rate": round(w / (w + l_), 4) if (w + l_) > 0 else None, "won_pos": round(w, 2), "lost_pos": round(l_, 2),
                "won_neg": round(sum(r["won_neg"] for r in rs), 2), "win_rate_5k": round(w5 / (w5 + l5), 4) if (w5 + l5) else None,
                "won_5k": w5, "lost_5k": l5,
                "rule": "value win rate = won ÷ (won + lost) ACV of opportunities with positive ACV; negative-ACV wins shown apart; count win rate on deals of $5k or more"}

    def velocity(a, b, pa, pb):
        if vel_rows is None:
            return None
        cur, prv = _velocity(vel_rows, a, b), _velocity(vel_rows, pa, pb)
        var = round(cur["avg_days"] - prv["avg_days"], 1) if is_num(cur["avg_days"]) and is_num(prv["avg_days"]) else None
        hv_var = round(cur["hv"]["avg_days"] - prv["hv"]["avg_days"], 1) if is_num(cur["hv"]["avg_days"]) and is_num(prv["hv"]["avg_days"]) else None
        cur["hv"] = dict(cur["hv"], variance_days=hv_var, small_sample=cur["hv"]["n"] < MIN_CLOSED_FOR_RATE)
        return dict(cur, cmp=prv, variance_days=var, small_sample=cur["n"] < MIN_CLOSED_FOR_RATE,
                    rule="average days from opportunity created to closed won (Salesforce), deals won in the window; same-day wins (created and won on the day) are left out",
                    hv_rule=f"won deals of {money(HIGH_VALUE_ACV)} ACV or more")

    # -------- bookings sums
    def sums(a, b):
        out = {"total": 0.0, "measure": {k: 0.0 for k, _, _ in MEASURES}, "product": {p: 0.0 for p in products},
               "sub": {s: 0.0 for s in subs}, "cust": {}, "acct_total": 0.0, "order_total": 0.0, "orders": {}, "order_meta": {}, "order_measures": {}}
        for x in lines:
            if a <= x["m"] <= b:
                out["total"] += x["acv"]
                out["measure"][x["measure"]] += x["acv"]
                out["product"][x["product"]] += x["acv"]
                out["sub"][x["sub"]] += x["acv"]
                if x["cust"] is not None:
                    out["cust"][x["cust"]] = out["cust"].get(x["cust"], 0.0) + x["acv"]
                    out["acct_total"] += x["acv"]
                if x["order"]:
                    out["order_total"] += x["acv"]
                out["orders"][x["order"]] = out["orders"].get(x["order"], 0.0) + x["acv"]
                om = out["order_measures"].setdefault(x["order"], {})
                om[x["measure"]] = om.get(x["measure"], 0.0) + x["acv"]
                meta = out["order_meta"].get(x["order"])
                if meta is None or (x["acv"] and not meta[4]):      # a 0-value line never labels an order
                    out["order_meta"][x["order"]] = (x["cust"], x["product"], x["measure"], x["d"], bool(x["acv"]))
        return out

    # -------- monthly series
    def series_for(key=None, val=None):
        act = []
        for mm in months:
            act.append(round(sum(x["acv"] for x in lines if x["m"] == mm and (key is None or x[key] == val)), 2))
        py = []
        for mm in months:
            p = shift_year(mm)
            py.append(round(sum(x["acv"] for x in lines if x["m"] == p and (key is None or x[key] == val)), 2) if p >= first else None)
        return {"actual": act, "py": py}

    drivers = [{"id": "m:" + k, "label": lbl, "dimension": "measure"} for k, lbl, _ in MEASURES]
    drivers += [{"id": "p:" + slug(p), "label": p, "dimension": "product", "value": p} for p in products]
    drivers += [{"id": "s:" + slug(s), "label": s, "dimension": "subsidiary", "value": s} for s in subs]
    series = {"total": series_for()}
    for d in drivers:
        key = {"measure": "measure", "product": "product", "subsidiary": "sub"}[d["dimension"]]
        series[d["id"]] = series_for(key, d["id"][2:] if d["dimension"] == "measure" else d["value"])

    ltm_total = sums(month_add(as_of, -11), as_of)["total"]
    monitoring_month = max(5000.0, round(0.01 * abs(ltm_total) / 12, -2))

    # -------- signals
    def signals_for(s):
        a = s["actual"]
        i = as_idx
        prior = [v for v in a[max(0, i - RR_MONTHS):i] if is_num(v)]
        rr = {"months": len(prior), "eligible": len(prior) >= RR_MONTHS}
        tests, fired = [], []
        if rr["eligible"]:
            mn, mx = min(prior), max(prior)
            rr.update({"mean": round(mean(prior), 2), "min": round(mn, 2), "max": round(mx, 2), "stdev": round(stdev(prior) or 0, 2)})
            cur = a[i]
            side = 1 if cur > mx + monitoring_month else (-1 if cur < mn - monitoring_month else 0)
            tests.append({"id": "outlier_month", "label": "Latest month outside its usual range", "state": "fired" if side else "not_fired",
                          "evidence": {"actual": cur, "min": mn, "max": mx}})
            if side:
                fired.append("outlier_month")
            prev_win = [v for v in a[max(0, i - RR_MONTHS - 1):i - 1] if is_num(v)]
            step = 0
            if len(prev_win) >= RR_MONTHS and i >= 1:
                pm, px = min(prev_win), max(prev_win)
                if a[i] > px + monitoring_month and a[i - 1] > px + monitoring_month:
                    step = 1
                elif a[i] < pm - monitoring_month and a[i - 1] < pm - monitoring_month:
                    step = -1
            tests.append({"id": "step_change", "label": "New level held for two months", "state": "fired" if step else "not_fired"})
            if step:
                fired.append("step_change")
            j = i - 12
            echo = False
            if side and j >= RR_MONTHS:
                pw = [v for v in a[j - RR_MONTHS:j] if is_num(v)]
                if pw and is_num(a[j]):
                    echo = (side > 0 and a[j] > max(pw) + monitoring_month) or (side < 0 and a[j] < min(pw) - monitoring_month)
            tests.append({"id": "seasonal_echo", "label": "Same month last year moved the same way", "state": "fired" if echo else ("not_fired" if j >= RR_MONTHS else "not_tested")})
            if echo:
                fired.append("seasonal_echo")
            hint = "recurring_level_change" if step else ("seasonal" if echo else ("one_off_candidate" if side else "undetermined"))
        else:
            rr["reason"] = f"fewer than {RR_MONTHS} earlier months"
            hint = "undetermined"
        return {"runrate": rr, "tests": tests, "fired": fired, "persistence_hint": hint}

    signals = {did: signals_for(series[did]) for did in ["total"] + [d["id"] for d in drivers]}

    # -------- conversion
    def conversion(a, b):
        rows = [c for c in closed_rows if a <= c["m"] <= b]

        def rate(w, lo):
            return round(w / (w + lo), 4) if (w or lo) else None

        def by(dim):
            g = {}
            for c in rows:
                if c["dim"] == dim:
                    x = g.setdefault(c["label"], [0, 0, 0.0, 0.0])
                    x[0] += c["won_n"]
                    x[1] += c["lost_n"]
                    x[2] += c["won_acv"]
                    x[3] += c["lost_acv"]
            return g
        src = by("source")      # opportunity-level, so the sources add to the totals
        won_n, lost_n = sum(v[0] for v in src.values()), sum(v[1] for v in src.values())
        won_acv, lost_acv = sum(v[2] for v in src.values()), sum(v[3] for v in src.values())

        def table(g):
            out = [{"id": slug(k), "label": k, "win_rate": rate(v[0], v[1]), "won": v[0], "lost": v[1], "won_acv": round(v[2], 2)} for k, v in g.items() if v[0] + v[1]]
            return sorted(out, key=lambda r: -(r["won"] + r["lost"]))
        reasons = by("loss") if loss_ok else {}
        cr = [c for c in created_rows if a <= c["m"] <= b]
        return {"closed": won_n + lost_n, "win_rate": rate(won_n, lost_n),
                "win_rate_value": round(won_acv / (won_acv + lost_acv), 4) if (won_acv + lost_acv) > 0 else None,
                "won": {"acv": round(won_acv, 2), "count": won_n}, "lost": {"acv": round(lost_acv, 2), "count": lost_n},
                "created": {"acv": round(sum(c["acv"] for c in cr), 2), "count": sum(c["n"] for c in cr)},
                "by_source": table(src), "by_product": table(by("product")), "loss_reasons_available": loss_ok,
                "loss_reasons": sorted([{"id": slug(k), "label": k, "acv": round(v[3], 2), "count": v[1], "share": round(v[3] / lost_acv, 4) if lost_acv else None}
                                        for k, v in reasons.items() if v[1]], key=lambda r: -r["acv"])}

    # -------- lenses
    lenses = {}
    for w in WINDOWS:
        a, b = window_months(as_of, w)
        pa, pb = shift_quarter(a), shift_quarter(b)
        lid = f"{w}_{BASIS}"
        if w not in PQ_WINDOWS:
            lenses[lid] = {"id": lid, "window": w, "basis": BASIS, "available": False,
                           "reason": "fiscal year to date (from 1 January) has no prior-quarter equivalent: shifted back a quarter it is not a fiscal period"}
            continue
        if pa < first:
            lenses[lid] = {"id": lid, "window": w, "basis": BASIS, "available": False, "reason": "no prior-quarter months in the data"}
            continue
        cur, prv = sums(a, b), sums(pa, pb)
        nmonths = (b.year - a.year) * 12 + b.month - a.month + 1
        mon = monitoring_month * nmonths
        mat = {"monitoring_abs": mon, "management_abs": 5 * mon, "executive_abs": 10 * mon}

        def item(did, label, act, cmp):
            var = act - cmp
            return {"id": did, "label": label, "actual": round(act, 2), "comparator": round(cmp, 2), "variance": round(var, 2),
                    "variance_pct": round(var / abs(cmp), 4) if cmp else None}

        dims = {"measure": [item("m:" + k, lbl, cur["measure"][k], prv["measure"][k]) for k, lbl, _ in MEASURES],
                "product": [item("p:" + slug(p), p, cur["product"][p], prv["product"][p]) for p in products],
                "subsidiary": [item("s:" + slug(s), s, cur["sub"][s], prv["sub"][s]) for s in subs]}
        for k, rows in dims.items():
            gross = sum(abs(r["variance"]) for r in rows) or 1.0
            for r in rows:
                r["share_of_abs_variance"] = round(abs(r["variance"]) / gross, 4)
                av = abs(r["variance"])
                r["tier"] = "executive" if av >= mat["executive_abs"] else "management" if av >= mat["management_abs"] else "monitoring" if av >= mon else "below"
        tot = item("total", "Total bookings", cur["total"], prv["total"])

        def bridge(rows, order=None):
            rs = rows if order is None else sorted(rows, key=lambda r: -abs(r["variance"]))
            steps = [{"id": r["id"], "label": r["label"], "value": r["variance"]} for r in rs]
            ctl = round(tot["comparator"] + sum(s["value"] for s in steps) - tot["actual"], 2)
            if abs(ctl) > 0.01:
                raise BuildError(f"bridge does not reconcile for {lid}: {ctl}")
            return {"start": {"label": "Prior quarter", "value": tot["comparator"]}, "end": {"label": "This period", "value": tot["actual"]},
                    "steps": steps, "control": ctl}
        bridges = {"by_measure": bridge(dims["measure"]), "by_product": bridge(dims["product"], True), "by_subsidiary": bridge(dims["subsidiary"], True)}
        rec_a = cur["measure"]["arr_new"] + cur["measure"]["arr_upsell"]
        rec_p = prv["measure"]["arr_new"] + prv["measure"]["arr_upsell"]
        if abs(rec_a + cur["measure"]["non_recurring"] - cur["total"]) > 0.01:
            raise BuildError("Total = Recurring + Non-recurring fails")
        n_orders, n_orders_p = len([o for o, v in cur["orders"].items() if o]), len([o for o, v in prv["orders"].items() if o])
        conv, conv_p = conversion(a, b), conversion(pa, pb)
        cust_sorted = sorted(cur["cust"].items(), key=lambda kv: -kv[1])
        top_c = [{"id": slug(c), "label": c, "actual": round(v, 2), "cmp": round(prv["cust"].get(c, 0.0), 2), "share": round(v / cur["acct_total"], 4) if cur["acct_total"] else None}
                 for c, v in cust_sorted[:10]]
        movers = sorted(((c, cur["cust"].get(c, 0.0) - prv["cust"].get(c, 0.0)) for c in set(cur["cust"]) | set(prv["cust"])), key=lambda kv: -abs(kv[1]))
        rec_var = (cur["acct_total"] - prv["acct_total"])
        mlabel = dict((k, l) for k, l, _ in MEASURES)
        # re-papering: same customer, same measure, same absolute amount, opposite sign inside the window
        pos_by, neg_by = {}, {}
        for o, ms in cur["order_measures"].items():
            for mk, v in ms.items():
                if abs(v) >= 1:
                    (pos_by if v > 0 else neg_by).setdefault((cur["order_meta"][o][0], mk, round(abs(v), 2)), []).append(o)
        paired, repaper = set(), {}
        for k, ps in pos_by.items():
            ns = neg_by.get(k, [])
            n = min(len(ps), len(ns))
            if n:
                paired.update(ps[:n] + ns[:n])
                r = repaper.setdefault(k[0], {"pairs": 0, "groups": []})
                r["pairs"] += n
                r["groups"].append((k[2], len(ps), len(ns), mlabel[k[1]]))

        def order_label(o):
            ms = {k: v for k, v in cur["order_measures"][o].items() if abs(v) >= 0.5}
            if not ms:
                return mlabel[cur["order_meta"][o][2]], None
            lead = max(ms, key=lambda k: abs(ms[k]))
            split = (" + ".join(f"{money(v)} {mlabel[k]}" for k, v in sorted(ms.items(), key=lambda kv: -abs(kv[1])))) if len(ms) > 1 else None
            return mlabel[lead], split
        top_o = []
        for o, v in sorted(cur["orders"].items(), key=lambda kv: -kv[1]):
            if o in paired or not o:
                continue
            lab, split = order_label(o)
            top_o.append({"id": o, "label": o, "customer": cur["order_meta"][o][0], "product": cur["order_meta"][o][1], "measure": lab, "split": split,
                          "date": cur["order_meta"][o][3].isoformat(), "acv": round(v, 2), "share": round(v / cur["acct_total"], 4) if cur["acct_total"] else None})
            if len(top_o) == 10:
                break
        for c in top_c:
            r = repaper.get(c["label"])
            if r:
                g0 = max(r["groups"], key=lambda g: g[0] * g[2])
                c["repapered"] = {"pairs": r["pairs"], "amount": g0[0], "bookings": g0[1], "cancellations": g0[2], "measure": g0[3],
                                  "note": f"{plural(g0[1], 'booking')} and {plural(g0[2], 'cancellation')} of {money(g0[0])} {g0[3]} are paired (re-papered); "
                                          f"shown net" + (f", with {plural(len(r['groups']) - 1, 'smaller paired amount')}" if len(r["groups"]) > 1 else "") + "."}
        top2 = sum(c["actual"] for c in top_c[:2])
        conc = {"top_customers": top_c, "top_orders": top_o, "base": round(cur["acct_total"], 2),
                "top2_share": round(top2 / cur["acct_total"], 4) if cur["acct_total"] else None,
                "top5_share": round(sum(c["actual"] for c in top_c[:5]) / cur["acct_total"], 4) if cur["acct_total"] else None,
                "largest_order_share": top_o[0]["share"] if top_o else None,
                "customer_movers": [{"id": slug(c), "label": c, "variance": round(v, 2)} for c, v in movers[:8]],
                "top2_movers_share_of_change": round(sum(v for _, v in movers[:2]) / rec_var, 4) if rec_var else None,
                "customers": len([c for c, v in cur["cust"].items() if v > 0]), "repapered_orders": len(paired),
                "rule": "customers ranked on recurring (Salesforce) bookings, shares of recurring bookings: non-recurring revenue (NetSuite) has no account; "
                        "orders are booked opportunities; re-papered pairs (same customer, measure and absolute amount, opposite sign) left out of the top orders"}

        def up_share(dim):
            rows = [r for r in dims[dim] if abs(r["comparator"]) >= 0.5]
            ups = [r for r in rows if r["variance"] > 0]
            return {"up": len(ups), "of": len(rows), "share": round(len(ups) / len(rows), 4) if rows else None}
        breadth = {"subsidiary": up_share("subsidiary"), "product": up_share("product"), "threshold": BREADTH_SHARE}
        new_ent = [r for r in dims["subsidiary"] if abs(r["comparator"]) < 0.5 and r["actual"] >= 0.5]
        ex = sum(r["actual"] for r in new_ent)
        organic = {"excluded": [{"label": r["label"], "actual": r["actual"]} for r in new_ent], "actual": round(tot["actual"] - ex, 2),
                   "comparator": tot["comparator"], "variance_pct": round((tot["actual"] - ex) / tot["comparator"] - 1, 4) if tot["comparator"] else None,
                   "rule": "excluding entities with no prior-quarter bookings in the window; whether each is an acquisition is management input required"}
        g2n = None
        if inp.get("gross_net") is not None:
            gm = {}
            for r in inp["gross_net"]:
                if a <= r["m"] <= b:
                    for key in (METRIC_TO_MEASURE.get(r["metric"]), "total"):
                        if key:
                            t = gm.setdefault(key, {"gross": 0.0, "negative": 0.0, "neg_lines": 0, "net": 0.0})
                            t["gross"] += r["gross"]
                            t["negative"] += r["negative"]
                            t["neg_lines"] += r["neg_lines"]
                            t["net"] += r["net"]
            g2n = {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in gm.items()}
            if "total" in g2n:
                g2n["total"]["negative_share"] = round(-g2n["total"]["negative"] / g2n["total"]["gross"], 4) if g2n["total"]["gross"] else None
                g2n["control"] = round(g2n["total"]["net"] - tot["actual"], 2)
        sst = _sub_state(inp, a, b, tot["actual"]) if inp.get("sub_state") is not None else None
        kp = [
            dict(item("arr_new", mlabel["arr_new"], cur["measure"]["arr_new"], prv["measure"]["arr_new"]), kind="money"),
            dict(item("arr_upsell", mlabel["arr_upsell"], cur["measure"]["arr_upsell"], prv["measure"]["arr_upsell"]), kind="money"),
            dict(item("recurring", "Recurring", rec_a, rec_p), kind="money"),
            dict(item("non_recurring", "Non-recurring", cur["measure"]["non_recurring"], prv["measure"]["non_recurring"]), kind="money"),
            dict(tot, id="total", kind="money"),
            {"id": "recurring_share", "label": "Recurring share", "kind": "ratio", "actual": round(rec_a / cur["total"], 4) if cur["total"] else None,
             "comparator": round(rec_p / prv["total"], 4) if prv["total"] else None},
            {"id": "aov", "label": "Average deal value", "kind": "money", "actual": round(cur["order_total"] / n_orders, 2) if n_orders else None,
             "comparator": round(prv["order_total"] / n_orders_p, 2) if n_orders_p else None, "orders": n_orders, "orders_cmp": n_orders_p,
             "rule": "recurring bookings ÷ distinct booked opportunities in the window (non-recurring revenue has no opportunity)"},
            {"id": "pipeline_created", "label": "Pipeline created", "kind": "money", "actual": conv["created"]["acv"], "comparator": conv_p["created"]["acv"],
             "count": conv["created"]["count"], "count_cmp": conv_p["created"]["count"]},
            {"id": "win_rate", "label": "Win rate", "kind": "ratio", "actual": conv["win_rate"], "comparator": conv_p["win_rate"],
             "closed": conv["closed"], "closed_cmp": conv_p["closed"], "small_sample": conv["closed"] < MIN_CLOSED_FOR_RATE},
        ]
        for k in kp:
            if k.get("kind") == "ratio" or k["id"] in ("aov", "pipeline_created"):
                if is_num(k["actual"]) and is_num(k["comparator"]):
                    k["variance"] = round(k["actual"] - k["comparator"], 4 if k["kind"] == "ratio" else 2)
                    k["variance_pct"] = round(k["variance"] / abs(k["comparator"]), 4) if k["kind"] == "money" and k["comparator"] else None
                else:
                    k["variance"], k["variance_pct"] = None, None
            floor = 0.01 if k["kind"] == "ratio" else (mon if k["id"] != "aov" else 0.02 * abs(k["comparator"] or 0))
            k["status"] = "in_line" if not is_num(k.get("variance")) or abs(k["variance"]) < floor else ("ahead" if k["variance"] > 0 else "behind")
        lenses[lid] = {"id": lid, "window": w, "basis": BASIS, "available": True, "window_label": WINDOW_LABELS[w].lower(),
                       "basis_label": "prior quarter", "cmp_short": CMP_SHORT, "months": nmonths,
                       "range": {"start": a.isoformat(), "end": month_end(b).isoformat(), "label": range_label(a, b),
                                 "cmp_label": range_label(pa, pb)},
                       "materiality": mat, "kpis": kp, "drivers": dims, "bridge": bridges, "concentration": conc,
                       "conversion": conv, "conversion_cmp": conv_p, "velocity": velocity(a, b, pa, pb),
                       "breadth": breadth, "organic": organic, "gross_to_net": g2n, "sub_state": sst, "conv_size": conv_size(a, b), "conv_size_cmp": conv_size(pa, pb),
                       "lost": _lost(lost_deals, a, b, pa, pb, range_label(a, b), range_label(pa, pb)) if inp.get("lost_lines") is not None else None}

    # -------- pipeline (point in time). Weighted values (the loader applies ACV x probability); the view holds no pipeline target, so there is no coverage.
    open_ = inp["open_deals"]
    data_asof = max([o["refreshed"] for o in open_ if o.get("refreshed")] or [inp.get("refreshed") or month_end(as_of)])
    # close quarters are anchored on the date the deal values are from: the analysis month-end when the month-end snapshot by
    # close month is supplied (gtm-snapshot-ecq), else the deal refresh date (current state). Anchoring current-state deals on
    # an earlier analysis month would show a quarter that has already ended as $0 (no open deal can still close in it).
    snap_q = inp.get("snapshot_ecq") is not None
    q_anchor = as_of if snap_q else dt.date(data_asof.year, data_asof.month, 1)
    cq = qstart(q_anchor)
    quarters = [qlabel(month_add(cq, 3 * k)) for k in range(4)]
    iq = 1 if snap_q and is_quarter_end(as_of) else 0   # a month-end snapshot at a quarter end: the quarter to close is the next one

    def nopps(xs):
        return len({o["id"] for o in xs})
    def cq_row(rid, label, oq):
        return {"id": rid, "quarter": label, "open": round(sum(o["acv"] for o in oq), 2), "count": nopps(oq),
                "late_stage": round(sum(o["acv"] for o in oq if o["stage_order"] >= late_order), 2)}
    past_due = [o for o in open_ if o["close"] and o["close"] < data_asof]
    cov = [cq_row(q, q, [o for o in open_ if o["ecq"] == q and o["close"] and o["close"] >= data_asof]) for q in quarters]
    buckets_cs = ([cq_row("past-due", "Past due", past_due)] if past_due else []) + cov
    later = [o for o in open_ if o["close"] and o["close"] >= data_asof and o["ecq"] > quarters[-1]]
    nodate = [o for o in open_ if not o["close"]]
    buckets_cs += ([cq_row("later", "Later", later)] if later else []) + ([cq_row("no-date", "No close date", nodate)] if nodate else [])
    overall_med, loo_med = _stage_medians(inp)
    med_days = {sn: round(m, 1) for sn, (m, n) in overall_med.items() if n >= MIN_STAYS and is_num(m)}
    stage_days, cur_start = (med_days or inp["stage_days"]), inp["cur_start"]
    typical_word = "median" if med_days else "average"
    flagged = []
    for o in open_:
        st = cur_start.get(o["id"])
        age = (data_asof - st).days if st else None
        typ = stage_days.get(o["stage"])
        aged = bool(age is not None and typ and age > AGED_MULTIPLE * typ)
        pdue = bool(o["close"] and o["close"] < data_asof)
        o["_age"], o["_typ"], o["_aged"], o["_pdue"] = age, typ, aged, pdue
        if aged or pdue:
            flagged.append(o)
    open_acv = sum(o["acv"] for o in open_)

    def tier(xs):
        v = sum(o["acv"] for o in xs)
        return {"value": round(v, 2), "count": nopps(xs), "share": round(v / open_acv, 4) if open_acv else None}
    stage_names = sorted({(o["stage_order"], o["stage"]) for o in open_})
    qcols = ["Past due"] + quarters[:3] + ["Later"]

    def qcol(o):
        if o["_pdue"]:
            return "Past due"
        return o["ecq"] if o["ecq"] in quarters[:3] else "Later"
    grid = []
    for so, sn in stage_names:
        row = {"id": slug(sn), "stage": sn, "order": so, "cells": []}
        for c in qcols:
            xs = [o for o in open_ if o["stage"] == sn and qcol(o) == c]
            row["cells"].append({"col": c, "acv": round(sum(o["acv"] for o in xs), 2), "count": nopps(xs)})
        grid.append(row)
    created_trend = {"labels": [mm.strftime("%b '%y") for mm in months[-13:]], "actual": [], "py": []}
    cr_by_m = {}
    for c in created_rows:
        cr_by_m[c["m"]] = cr_by_m.get(c["m"], 0.0) + c["acv"]
    for mm in months[-13:]:
        created_trend["actual"].append(round(cr_by_m.get(mm, 0.0), 2))
        created_trend["py"].append(round(cr_by_m[shift_year(mm)], 2) if shift_year(mm) in cr_by_m else None)
    velocity_trend = None
    if vel_rows is not None:
        vm = lambda mm, band=None: _velocity([r for r in vel_rows if band is None or r["band"] == band], mm, mm)["avg_days"]
        velocity_trend = {"labels": [mm.strftime("%b '%y") for mm in months[-13:]], "actual": [vm(mm) for mm in months[-13:]],
                          "py": [vm(shift_year(mm)) for mm in months[-13:]], "hv": [vm(mm, "hv") for mm in months[-13:]]}
    deals = [{"id": o["id"], "name": o["name"], "owner": o["owner"], "product": o["product"], "stage": o["stage"], "acv": round(o["acv"], 2),
              "close": o["close"].isoformat() if o["close"] else None, "age_days": o["_age"], "typical_days": o["_typ"],
              "flags": [f for f, on in (("past due", o["_pdue"]), ("aged in stage", o["_aged"])) if on]}
             for o in sorted(flagged, key=lambda o: -o["acv"])[:12]]
    ltm_conv = lenses[f"LTM_{BASIS}"]["conversion"] if lenses.get(f"LTM_{BASIS}", {}).get("available") else conversion(month_add(as_of, -11), as_of)
    val_rate = safe_div(ltm_conv["won"]["acv"], ltm_conv["won"]["acv"] + ltm_conv["lost"]["acv"])
    n_open = nopps(open_)
    late_names = sorted({(o["stage_order"], o["stage"]) for o in open_ if o["stage_order"] >= late_order})
    late_label = f"{late_names[0][1]} onwards" if late_names else "late stage"
    py = None
    if cards:
        py = {"open": cards.get("OPEN_PIPELINE_VALUE_PYMTD"),
              "open_count": int(cards["OPEN_OPPORTUNITIES_PYMTD"]) if is_num(cards.get("OPEN_OPPORTUNITIES_PYMTD")) else None,
              "avg_value": cards.get("AVG_OPPORTUNITY_VALUE_ACV_PYMTD"), "label": "a year earlier", "source": "PIPELINE_OVERVIEW KPI cards (PY twins)"}
        py = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in py.items()}
        now = {"open": open_acv, "open_count": nopps(open_)}
        now["avg_value"] = now["open"] / now["open_count"] if now["open_count"] else None
        for k in ("open", "open_count", "avg_value"):
            py[k + "_var_pct"] = round(now[k] / py[k] - 1, 4) if is_num(now[k]) and is_num(py[k]) and py[k] else None
    pipeline = {"as_of": data_asof.isoformat(), "open": round(open_acv, 2),
                "open_count": n_open, "avg_value": round(open_acv / n_open, 2) if n_open else None,
                "late_stage": round(sum(o["acv"] for o in open_ if o["stage_order"] >= late_order), 2), "late_stage_label": late_label, "py": py,
                "by_close_quarter": buckets_cs, "close_quarters_as_of": data_asof.isoformat(), "grid_as_of": data_asof.isoformat(),
                "in_quarter": {"quarter": cov[iq]["quarter"], "open": cov[iq]["open"], "count": cov[iq]["count"], "as_of": data_asof.isoformat()},
                "by_stage_quarter": {"columns": qcols, "rows": grid},
                "stage_days": [{"id": slug(sn), "stage": sn, "days": stage_days[sn]} for so, sn in stage_names if sn in stage_days],
                "risk": {"past_due": tier(past_due), "aged": tier([o for o in open_ if o["_aged"]]), "flagged": tier(flagged), "deals": deals,
                         "aged_rule": f"current stage older than {AGED_MULTIPLE:.0f}× the {typical_word} days for that stage",
                         "typical": typical_word,
                         "method": "proxy: the view has no activity or next-step data"},
                "created_trend": created_trend, "velocity_trend": velocity_trend}

    risk = _risk(inp, open_, data_asof, as_of, overall_med, loo_med)

    # one analysis date: the bookings month-end. Headline pipeline is the PIPELINE_OVERVIEW snapshot at that date;
    # deal-level detail exists only as current state and is labelled with its refresh date.
    analysis_date = month_end(as_of)
    snap = inp.get("snapshot")
    pipeline["analysis_date"] = analysis_date.isoformat()
    pipeline["deals_as_of"] = data_asof.isoformat()
    if snap and str(snap.get("AS_OF_DATE"))[:10] == analysis_date.isoformat():
        cnt = int(snap["OPEN_OPPORTUNITIES_MTD"]) if is_num(snap.get("OPEN_OPPORTUNITIES_MTD")) else None
        pipeline.update({"as_of": analysis_date.isoformat(), "open": round(snap["OPEN_PIPELINE_VALUE_MTD"], 2), "open_count": cnt,
                         "avg_value": round(snap["AVG_OPPORTUNITY_VALUE_ACV_MTD"], 2) if is_num(snap.get("AVG_OPPORTUNITY_VALUE_ACV_MTD")) else None,
                         "source": "PIPELINE_OVERVIEW snapshot at the analysis date"})
        pyv = {"open": snap.get("OPEN_PIPELINE_VALUE_PYMTD"),
               "open_count": int(snap["OPEN_OPPORTUNITIES_PYMTD"]) if is_num(snap.get("OPEN_OPPORTUNITIES_PYMTD")) else None,
               "avg_value": snap.get("AVG_OPPORTUNITY_VALUE_ACV_PYMTD")}
        pyv = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in pyv.items()}
        for k in ("open", "open_count", "avg_value"):
            pyv[k + "_var_pct"] = round(pipeline[k] / pyv[k] - 1, 4) if is_num(pipeline[k]) and is_num(pyv[k]) and pyv[k] else None
        pipeline["py"] = dict(pyv, label="a year earlier", source="PIPELINE_OVERVIEW snapshot, prior-year twins")
        pipeline["current"] = {"as_of": data_asof.isoformat(), "open": round(open_acv, 2), "count": n_open,
                               "change": round(open_acv - pipeline["open"], 2),
                               "note": f"open pipeline {money(pipeline['open'])} at {analysis_date.isoformat()} to {money(open_acv)} at {data_asof.isoformat()} (current state, used for the deal lists)"}
    ecq = inp.get("snapshot_ecq")
    if ecq is not None:
        # the snapshot at the analysis date by stage and close date: past due (close date before the analysis date), the four
        # fiscal close quarters, later; the buckets foot to the snapshot card. The stage x quarter grid is built from the same rows.
        def col_of(r):
            c = r["close"]
            if c is None:
                return "No close date"
            if (c < analysis_date.replace(day=1)) if r.get("by_month") else (c < analysis_date):
                return "Past due"
            q = qlabel(c)
            return q if q in quarters else ("Later" if q > quarters[-1] else "Past due")
        agg = {}
        for r in ecq:
            k = col_of(r)
            a = agg.setdefault(k, {"open": 0.0, "count": 0, "late": 0.0})
            a["open"] += r["open"]
            a["count"] += r["count"]
            if stage_order_of(r.get("stage")) >= late_order and r.get("stage"):
                a["late"] += r["open"]
        has_stage = any(r.get("stage") for r in ecq)
        mk = lambda rid, label: {"id": rid, "quarter": label, "open": round(agg.get(label, {}).get("open", 0.0), 2), "count": agg.get(label, {}).get("count", 0),
                                 "late_stage": round(agg.get(label, {}).get("late", 0.0), 2) if has_stage else None}
        cov = [mk(q, q) for q in quarters]
        buckets = ([mk("past-due", "Past due")] if "Past due" in agg else []) + cov + ([mk("later", "Later")] if "Later" in agg else []) \
            + ([mk("no-date", "No close date")] if "No close date" in agg else [])
        upd = dict(by_close_quarter=buckets, earlier_quarters_open=None, close_quarters_as_of=analysis_date.isoformat(),
                   in_quarter={"quarter": cov[iq]["quarter"], "open": cov[iq]["open"], "count": cov[iq]["count"], "as_of": analysis_date.isoformat()})
        if has_stage:
            cols = ["Past due"] + quarters[:3] + ["Later"]
            cell = lambda r: (lambda k: k if k in cols else ("Later" if k in quarters else "Past due"))(col_of(r))
            stages = sorted({(stage_order_of(r["stage"]), r["stage"]) for r in ecq if r.get("stage")})
            grid_s = []
            for so, sn in stages:
                cells = []
                for c in cols:
                    xs = [r for r in ecq if r.get("stage") == sn and cell(r) == c]
                    cells.append({"col": c, "acv": round(sum(r["open"] for r in xs), 2), "count": sum(r["count"] for r in xs)})
                grid_s.append({"id": slug(sn), "stage": sn, "order": so, "cells": cells})
            upd.update(by_stage_quarter={"columns": cols, "rows": grid_s}, grid_as_of=analysis_date.isoformat())
        pipeline.update(**upd)
    # ageing by the opportunity created date (CREATED_DATE, set on every opportunity; in the Yes Energy view PIPELINE_CREATION_DATE
    # equals CREATED_DATE, so a deal missing one is rare) and pipeline dated more than two quarters out
    age_from = lambda o: o.get("opened") or o.get("pipe_created")
    pre = [o for o in open_ if not o.get("pipe_created")]
    if open_ and any("pipe_created" in o for o in open_):
        st_pre = {}
        for o in pre:
            st_pre[o["stage"]] = st_pre.get(o["stage"], 0.0) + o["acv"]
        pipeline["not_yet_created"] = {"acv": round(sum(o["acv"] for o in pre), 2), "count": nopps(pre), "as_of": data_asof.isoformat(),
                                       "share": round(sum(o["acv"] for o in pre) / open_acv, 4) if open_acv else None,
                                       "by_stage": [{"stage": k, "acv": round(v, 2)} for k, v in sorted(st_pre.items(), key=lambda kv: -kv[1])],
                                       "rule": "open deals with no PIPELINE_CREATION_DATE (it equals the created date in the view), so pipeline created does not count them yet"}
    if any(age_from(o) for o in open_):
        buckets = {"under 90 days": 0.0, "90–365 days": 0.0, "over 365 days": 0.0, "no created date": 0.0}
        for o in open_:
            pc = age_from(o)
            k = "no created date" if not pc else "under 90 days" if (data_asof - pc).days < 90 else "90–365 days" if (data_asof - pc).days <= 365 else "over 365 days"
            buckets[k] += o["acv"]
        far = sum(o["acv"] for o in open_ if o["ecq"] and o["ecq"] > quarters[2])
        pipeline["ageing"] = {"as_of": data_asof.isoformat(), "basis": "opportunity created date" if any(o.get("opened") for o in open_) else "pipeline creation date", "buckets": [{"label": k, "acv": round(v, 2), "share": round(v / open_acv, 4) if open_acv else None}
                                                                          for k, v in buckets.items() if v],
                              "far_out": {"acv": round(far, 2), "share": round(far / open_acv, 4) if open_acv else None, "beyond": quarters[2]}}
    # won opportunity ACV (OPPORTUNITIES) vs recurring bookings (BOOKING_LINES) by fiscal quarter: a labelled
    # reconciliation of two Salesforce scopes (pipeline segments vs bookings teams), never added together
    wq, bq = {}, {}
    for c in closed_rows:
        if c["dim"] == "source" and c["m"] <= as_of:
            wq[qlabel(c["m"])] = wq.get(qlabel(c["m"]), 0.0) + c["won_acv"]
    for x in lines:
        if x["m"] <= as_of and x["measure"] != "non_recurring":
            bq[qlabel(x["m"])] = bq.get(qlabel(x["m"]), 0.0) + x["acv"]
    full_q = [q for q in sorted(set(wq) & set(bq)) if q < qlabel(as_of) or is_quarter_end(as_of)][-7:]
    pipeline["won_vs_booked"] = [{"quarter": q, "won": round(wq[q], 2), "booked": round(bq[q], 2), "ratio": round(bq[q] / wq[q], 2) if wq[q] else None} for q in full_q]
    # rest of the fiscal year (scenario, credit 0): what the remaining months to 31 December must deliver
    fy0 = fy_start(as_of)
    fy_last = month_add(fy0, 11)
    if as_of < fy_last:
        k = (as_of.year - fy0.year) * 12 + as_of.month - fy0.month            # months of this fiscal year before the as-of month
        pfy0, pfy_last = month_add(fy0, -12), month_add(fy_last, -12)
        tot_in = lambda a_, b_: sum(x["acv"] for x in lines if a_ <= x["m"] <= b_)
        py_full = tot_in(pfy0, pfy_last)
        py_rest = tot_in(month_add(pfy0, k + 1), pfy_last)
        ytd_now = tot_in(fy0, as_of)
        ytd_py = tot_in(pfy0, month_add(pfy0, k))
        have_py = first <= pfy0
        g = ytd_now / ytd_py - 1 if ytd_py else None
        rest = f"{month_name(month_add(as_of, 1))}–{month_name(fy_last)}"
        rest_of_year = {"months": rest, "fiscal_year": f"FY{fy_of(as_of)}", "py_full": round(py_full, 2) if have_py else None, "py_rest": round(py_rest, 2),
                        "ytd": round(ytd_now, 2), "to_match_py": round(py_full - ytd_now, 2) if have_py else None,
                        "to_hold_growth": round(py_rest * (1 + g), 2) if g is not None else None,
                        "growth": round(g, 4) if g is not None else None, "credit": 0,
                        "rule": f"fiscal year FY{fy_of(as_of)} (1 January to 31 December): to match last fiscal year: last fiscal year's total less this fiscal "
                                f"year to date; to hold the growth rate: last year's {rest} × (1 + fiscal-year-to-date growth)",
                        "complete": have_py}
        # recurring won since the analysis month (Salesforce won ACV after the last closed month, up to the deal refresh date):
        # already in the data but not yet in a closed bookings month; non-recurring revenue arrives with the NetSuite close
        since = [c for c in closed_rows if c["dim"] == "source" and as_of < c["m"] <= dt.date(data_asof.year, data_asof.month, 1) and c["m"] <= fy_last]
        if since:
            ws = round(sum(c["won_acv"] for c in since), 2)
            rest_of_year.update(won_since=ws, won_since_from=month_add(as_of, 1).isoformat(), won_since_to=data_asof.isoformat(),
                                still_to_match=round(rest_of_year["to_match_py"] - ws, 2) if rest_of_year["to_match_py"] is not None else None,
                                won_since_rule="recurring (Salesforce won ACV) closed after the analysis month, to the deal refresh date; "
                                               "non-recurring revenue for those months is not closed yet")
    else:
        rest_of_year = None

    # -------- outlook (mechanical scenario)
    sc = []
    wvb = {r["quarter"]: r for r in pipeline.get("won_vs_booked") or []}
    pyq = lambda q: f"FY{int(q[2:6]) - 1}{q[6:]}" if re.match(r"^FY\d{4}-Q[1-4]$", str(q or "")) else None
    ltm_cs = (lenses.get(f"LTM_{BASIS}") or {}).get("conv_size") or {}
    v_rate = ltm_cs.get("value_win_rate") if is_num(ltm_cs.get("value_win_rate")) else val_rate
    c_rate = ltm_cs.get("win_rate_5k") if is_num(ltm_cs.get("win_rate_5k")) else None
    for row in [r for r in cov if r["id"] in quarters][:2]:
        a_v = row["open"] * v_rate if v_rate is not None else None
        a_c = row["open"] * c_rate if c_rate is not None else None
        vals = [v for v in (a_v, a_c) if is_num(v)]
        sc.append({"id": row["quarter"], "quarter": row["quarter"], "open": row["open"],
                   "win_rate_applied": round(v_rate, 4) if v_rate is not None else None, "at_win_rate": round(a_v, 2) if is_num(a_v) else None,
                   "count_rate_applied": round(c_rate, 4) if c_rate is not None else None, "at_count_rate": round(a_c, 2) if is_num(a_c) else None,
                   "low": round(min(vals), 2) if vals else None, "high": round(max(vals), 2) if vals else None,
                   "py_quarter": pyq(row["quarter"]), "py_won": wvb.get(pyq(row["quarter"]), {}).get("won"), "py_booked": wvb.get(pyq(row["quarter"]), {}).get("booked")})
        # actuals since the analysis date: won ACV closed in this quarter's months after the analysis month, to the refresh date
        qs_ = next((month_add(cq, 3 * k) for k in range(4) if qlabel(month_add(cq, 3 * k)) == row["quarter"]), None)
        if qs_ is not None:
            q_end = month_end(month_add(qs_, 2))
            ms = [c for c in closed_rows if c["dim"] == "source" and as_of < c["m"] <= dt.date(data_asof.year, data_asof.month, 1) and qs_ <= c["m"] <= month_add(qs_, 2)]
            if ms:
                sc[-1].update(won_since=round(sum(c["won_acv"] for c in ms), 2), won_since_to=min(data_asof, q_end).isoformat(),
                              quarter_ended=q_end < data_asof, quarter_end=q_end.isoformat())
    outlook = {"scenario": sc, "rule": "open pipeline dated to close in the quarter × the last-twelve-month win rate, by value and by count (deals of $5k or more): "
                                       "the lower and higher of the two; only deals already in the pipeline, so deals created and won inside the quarter come on top; "
                                       "compared with the opportunity ACV won in the same quarter last year",
               "credit": 0, "note": "Salesforce opportunity ACV (recurring), not non-recurring revenue. A mechanical range, not a forecast; nothing enters a forecast until a named owner accepts it."}

    # -------- insights, actions, story per lens
    for lid, L in lenses.items():
        if not L["available"]:
            continue
        L["insights"] = _insights(L, signals, series, months, as_of)
        L["actions"] = _actions(L, as_of)
        L["pipeline_insights"] = _pipeline_insights(L, pipeline, risk)
        L["pipeline_actions"] = _pipeline_actions(L, pipeline, risk, as_of)
        _add_short(L["insights"]); _add_short(L["pipeline_insights"]); _add_ask_short(L["actions"]); _add_ask_short(L["pipeline_actions"])
        for k, dims in L["drivers"].items():
            for r in dims:
                r["reading"] = _driver_reading(L, r, signals.get(r["id"]), series.get(r["id"]), as_of)
        L["headline"] = {"text": L["insights"][0]["text"]}

    # -------- QC
    checks = [{"id": "hierarchy", "result": "PASS", "detail": "Total = Recurring + Non-recurring and Recurring = New ARR + Upsell ARR in every lens."},
              {"id": "bridges_reconcile", "result": "PASS", "detail": "Prior quarter + every step = this period, to the cent, for the measure, product and subsidiary bridges."},
              {"id": "blank_metric_lines", "result": "INFO" if blank_metric else "PASS", "detail": f"{plural(blank_metric, 'line')} with no booking metric left out (they count in no metric)."},
              {"id": "cancellations", "result": "INFO", "detail": f"{plural(cancels, 'negative booking line')} (credits on won opportunities or non-recurring revenue) net off inside their month."}]
    if as_of_note:
        checks.append({"id": "as_of_complete", "result": "INFO", "detail": as_of_note + "."})
    if bmart:
        # every month of the page against the mart's MTD at that month-end; the page's fiscal windows (from 1 January) and
        # LTM are sums of these same months. The mart's own QTD / YTD / LTM columns are not used: they are tagged to the keys
        # present at one month, so keys missing from the as-of month drop out and the window is incomplete.
        diffs, n_cmp = [], 0
        for mm in months:
            theirs = bmart.get(mm)
            if not is_num(theirs):
                continue
            n_cmp += 1
            mine = sums(mm, mm)["total"]
            if abs(mine - theirs) > max(1.0, 0.001 * abs(theirs)):
                diffs.append(f"{mm:%b %Y} lines {money(mine)} vs mart {money(theirs)}")
        checks.append({"id": "mart_tie_out", "result": "WARN" if diffs or not n_cmp else "PASS",
                       "detail": ("Booking lines differ from the BOOKINGS_OVERVIEW mart: " + "; ".join(diffs[:6])) if diffs else
                       "No month of the page is in the BOOKINGS_OVERVIEW extract." if not n_cmp else
                       f"Booking lines tie to BOOKINGS_OVERVIEW TOTAL_BOOKINGS_MTD for all {n_cmp} months; fiscal quarter and year to date are built from those months "
                       "(the mart's QTD, YTD and LTM columns are not used)."})
    if cards and is_num(cards.get("OPEN_PIPELINE_VALUE_MTD")) and str(cards.get("AS_OF_DATE"))[:10] != data_asof.isoformat():
        checks.append({"id": "open_pipeline_tie_out", "result": "INFO",
                       "detail": f"Live card dated {str(cards.get('AS_OF_DATE'))[:10]}, deal lines {data_asof.isoformat()}: not compared. "
                                 + (pipeline.get("current") or {}).get("note", "")})
    elif cards and is_num(cards.get("OPEN_PIPELINE_VALUE_MTD")):
        d = open_acv - cards["OPEN_PIPELINE_VALUE_MTD"]
        checks.append({"id": "open_pipeline_tie_out", "result": "PASS" if abs(d) <= max(1.0, 0.002 * cards["OPEN_PIPELINE_VALUE_MTD"]) else "WARN",
                       "detail": f"Open pipeline from opportunity lines {money(open_acv)} vs the PIPELINE_OVERVIEW card {money(cards['OPEN_PIPELINE_VALUE_MTD'])}; "
                                 f"{n_open} open opportunities vs {int(cards.get('OPEN_OPPORTUNITIES_MTD') or 0)} on the card."})
    bq_ = pipeline.get("by_close_quarter") or []
    if bq_:
        b_acv, b_n = sum(r["open"] for r in bq_), sum(r["count"] for r in bq_)
        ok = abs(b_acv - pipeline["open"]) <= max(1.0, 0.001 * abs(pipeline["open"])) and (pipeline.get("open_count") is None or b_n == pipeline["open_count"])
        checks.append({"id": "close_quarters_foot", "result": "PASS" if ok else "WARN",
                       "detail": f"Open pipeline by close quarter (past due, the fiscal quarters and later) sums to {money(b_acv)} and {plural(b_n, 'deal')}, "
                                 f"against the headline {money(pipeline['open'])} and {plural(pipeline.get('open_count') or 0, 'deal')} at {pipeline['as_of']}."})
    Lq = lenses.get(f"LTM_{BASIS}")
    if Lq and Lq.get("available") and Lq.get("lost") is not None:
        mine, gov = Lq["lost"]["acv"], Lq["conversion"]["lost"]["acv"]
        ok = abs(mine - gov) <= max(1.0, 0.002 * abs(gov))
        checks.append({"id": "lost_tie_out", "result": "PASS" if ok else "WARN",
                       "detail": f"Lost deals over the last twelve months {money(mine)} vs the LOST_ACV_USD total {money(gov)}."})
    if inp.get("snapshot") is not None or governed:
        aligned = pipeline["as_of"] == month_end(as_of).isoformat()
        checks.append({"id": "as_of_alignment", "result": "PASS" if aligned else "FAIL",
                       "detail": (f"Bookings and headline pipeline both dated {month_end(as_of).isoformat()}." if aligned else
                                  f"Headline pipeline dated {pipeline['as_of']} but bookings close {month_end(as_of).isoformat()}: supply gtm-cards-snapshot at the bookings month-end.")})
        checks.append({"id": "deal_detail_refresh", "result": "INFO", "detail": f"Deal lists, stage age and past-due are current state as at {data_asof.isoformat()} (the view keeps no deal-level history)."})
    else:
        checks.append({"id": "refresh", "result": "INFO", "detail": f"Local workbook: opportunities as at {data_asof.isoformat()}; bookings closed to {month_end(as_of).isoformat()}."})
    g2 = (lenses.get(f"QTD_{BASIS}") or {}).get("gross_to_net")
    if g2 and "control" in g2:
        checks.append({"id": "gross_to_net_tie_out", "result": "PASS" if abs(g2["control"]) <= 0.05 else "WARN",
                       "detail": f"Gross {money(g2['total']['gross'])} less cancellations {money(g2['total']['negative'])} ({g2['total']['neg_lines']} lines) = net {money(g2['total']['net'])}, "
                                 f"against the quarter-to-date total (difference {g2['control']:.2f})."})
    s2 = (lenses.get(f"QTD_{BASIS}") or {}).get("sub_state")
    if s2:
        checks.append({"id": "status_tie_out", "result": "PASS" if abs(s2["control"]) <= 0.05 else "WARN",
                       "detail": f"Bookings by subscription status sum to {money(s2['total']['net'])} ({money(s2['total']['pos'])} positive, "
                                 f"{money(s2['total']['rev'])} reversals), against the quarter-to-date total (difference {s2['control']:.2f})."})
    caveats = ["Local test data: a synthetic workbook, not governed view output." if data_mode == "local" else None,
               "Windows are computed from booking and opportunity lines (the workbook has no KPI marts)." if data_mode == "local" else None,
               "Open pipeline a year ago is not in the workbook, so open pipeline shows no prior year." if not py else None,
               f"Fiscal year is the calendar year, 1 January to 31 December (FY{fy_of(as_of)} runs {fy_start(as_of):%b %Y} to {month_add(fy_start(as_of), 11):%b %Y}); "
               "quarters are Jan–Mar, Apr–Jun, Jul–Sep and Oct–Dec.",
               "Recurring bookings are Salesforce closed-won opportunity lines (ARR (New) for New Customer, ARR (Upsell) for Upgrade, Renewal and Downgrade), "
               "on the close date; non-recurring bookings are NetSuite one-time services revenue from the GL, on the period end date.",
               "Pipeline values are weighted ACV (line ACV × Salesforce probability ÷ 100). Pipeline created, won and lost ACV are unweighted. "
               "The view holds no pipeline or bookings target, so there is no coverage ratio and nothing is read against a target.",
               "Win rate counts distinct opportunities closed in the window (governed WON_ and LOST_ metrics by close month)." if governed else None,
               "The view has no loss reason, so lost ACV is not split by reason." if not loss_ok else None,
               "Recurring bookings and pipeline (Salesforce) are never added to non-recurring revenue (NetSuite) beyond the governed Total Bookings." if governed else None,
               "Stage age is a proxy for stalled deals: the view has no activity data.",
               f"Recurring ACV: {risk['recurring_rule']}" + ("; new ARR (New Customer) vs upsell ARR (Upgrade, Renewal, Downgrade) by opportunity type." if risk["open"]["split_available"] else "."),
               "Close-date pushes are seen only at stage changes (the close date recorded at each change, then today's)." if risk["not_closing"]["pushes_available"]
               else "No close-date history was supplied, so 'not closing' covers past-due deals only.",
               (f"Stuck: an open deal longer in its current stage than 90% of completed stays in that stage (P90, at least {MIN_P90_RUNS} stays; "
                f"same-day pass-throughs are not counted)." if inp.get("stage_p90") is not None else
                f"Stuck compares each open deal with the median completed stay in its stage across other customers' deals (at least {MIN_STAYS} stays; "
                f"same-day pass-throughs under {MIN_STAY_DAYS} day are not counted as stays)."),
               (f"Pipeline created counts a deal on PIPELINE_CREATION_DATE (equal to the created date): {money(pipeline['not_yet_created']['acv'])} of open pipeline at "
                f"{pipeline['not_yet_created']['as_of']} ({plural(pipeline['not_yet_created']['count'], 'deal')}, mostly earlier stages) has not reached it yet. "
                "Pipeline age uses the opportunity created date, which every deal has.") if pipeline.get("not_yet_created") else None,
               (f"Headline pipeline, close quarters and the stage table are the PIPELINE_OVERVIEW snapshot at {pipeline['as_of']}; deal lists, stage age, "
                f"not-closing and stuck are current state at {pipeline['deals_as_of']}.") if pipeline.get("as_of") != pipeline.get("deals_as_of") else None,
               "No opportunity type was supplied, so recurring ACV is not split into new ARR and upsell ARR." if not risk["open"]["split_available"] else None,
               f"{plural(risk['open']['no_family_lines'], 'open line')} ({money(risk['open']['no_family_acv'])}) {'has' if risk['open']['no_family_lines'] == 1 else 'have'} "
               "no product family and count as recurring." if risk["open"]["no_family_lines"] else None,
               "Stage history is kept as stage runs: close-date pushes are seen between runs (the close date at the end of each run, then today's)."]
    caveats += ["Close quarters on the month-end snapshot use the close date held at that date, grouped into fiscal quarters."
                if inp.get("snapshot_ecq") is not None else None,
                "Upsell ARR is ARR (Upsell): Upgrade, Renewal and Downgrade opportunities; renewals are booked as the ARR change on the renewal line."]
    caveats = [c for c in caveats if c]
    qc = {"status": "CLEAN" if all(c["result"] in ("PASS", "INFO") for c in checks) else "NOTES", "checks": checks, "caveats": caveats}
    capabilities = {"invoices": {"state": "not_available", "reason": "No invoice fact: recurring bookings stop at the won opportunity and non-recurring bookings at the income statement line."},
                    "renewals": {"state": "not_available", "label": "Renewals coming due",
                                 "reason": "Renewal opportunities are in the view (opportunity type Renewal), but no subscription end date is held, so "
                                           "customers 1, 3 or 6 months from the end of their term, and how many have renewed, cannot be counted.",
                                 "needs": "the subscription end date (not in the view)"},
                    "discounts": {"state": "not_available", "label": "Discounting",
                                  "reason": "No list price or discount is held on opportunities, so the discount given to each customer and "
                                            "what a deeper or smaller discount would do to bookings cannot be read.",
                                  "needs": "list price, or discount %, on the Salesforce opportunity"},
                    "retention": {"state": "elsewhere", "label": "Churn and retention",
                                  "reason": "Churned ARR and gross and net dollar retention are in the ARR view (ARR_ANALYTICS), answered by the ARR skill.",
                                  "needs": None},
                    "activity": {"state": "not_available", "reason": "No activity or next-step fields; stage age is the proxy."},
                    "plan": {"state": "not_available", "label": "Targets and coverage",
                             "reason": "No bookings plan, budget or pipeline target is in the view, so nothing is read against a target and there is no coverage ratio."},
                    "loss_reasons": {"state": "available" if loss_ok else "not_available",
                                     "reason": "Loss reason on closed-lost opportunities." if loss_ok else "The view has no loss reason on closed-lost opportunities."}}

    prim = window or "QTD"
    if lenses.get(f"{prim}_{BASIS}", {}).get("available"):
        prim_id, prim_reason = f"{prim}_{BASIS}", "requested or default (quarter to date against the same point last quarter)"
    else:
        prim_id = next((k for k, v in lenses.items() if v["available"]), None)
        if prim_id is None:
            raise BuildError("no window has prior-quarter months in the data: the Compare basis needs at least four months of bookings")
        prim_reason = f"{WINDOW_LABELS.get(prim, prim).lower()} is not available against the prior quarter ({lenses.get(f'{prim}_{BASIS}', {}).get('reason', 'unknown window')}), so the page opens on {lenses[prim_id]['window_label']}"
    meta = {"title": title or "GTM review", "view": "GTM_ANALYTICS", "data_mode": data_mode, "currency": "USD",
            "as_of": {"label": as_of.strftime("%b %Y"), "name": as_of.strftime("%B %Y"), "month": month_name(as_of), "month_end": month_end(as_of).isoformat(),
                      "quarter": qlabel(as_of), "fiscal_year": f"FY{fy_of(as_of)}", "idx": as_idx},
            "fiscal": {"start_month": FY_START_MONTH, "year": f"FY{fy_of(as_of)}", "year_start": fy_start(as_of).isoformat(), "quarter": qlabel(as_of),
                       "rule": "fiscal year is the calendar year, 1 January to 31 December"},
            "primary_lens": {"id": prim_id, "reason": prim_reason},
            "scope": {"products": products, "subsidiaries": subs, "filtered_to": product, "note": None},
            "months": [mm.strftime("%b '%y") for mm in months], "months_of_history": len(months), "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "materiality": {"monitoring_month": monitoring_month, "basis": "1% of last-twelve-month bookings a month, scaled to the window; management 5×, executive 10×"},
            "thresholds": [
                {"id": "stage_age", "value": "P90" if inp.get("stage_p90") is not None else f"{STUCK_MULTIPLE:.0f}× median",
                 "basis": risk["stuck"]["rule"], "sensitivity": {k: {"p90": v.get("p90"), "p75": v.get("p75"), "mean": v.get("mean"), "runs": v.get("runs")}
                                                                for k, v in (inp.get("stage_p90") or {}).items()}},
                {"id": "past_due", "value": "close date before the refresh date", "basis": "reported apart from stage age"},
                {"id": "materiality", "value": monitoring_month, "basis": "1% of last-twelve-month bookings a month; the Summary shows a monthly signal only above 10× (executive)"},
                {"id": "min_closed", "value": MIN_CLOSED_FOR_RATE, "basis": "fewer closed deals than this: rate shown, not read as a finding"},
                {"id": "breadth", "value": BREADTH_SHARE, "basis": "share of subsidiaries and products with prior-quarter bookings that must be up before 'broad-based'"},
                {"id": "high_value", "value": HIGH_VALUE_ACV, "basis": "open and won deals of this ACV or more"}], "sources": [source or "GTM_ANALYTICS"], "extracts": provenance or [], "renderer_version": RENDERER_VERSION,
            "window_labels": WINDOW_LABELS, "basis_labels": {BASIS: "Prior quarter"}, "data_refreshed_at": data_asof.isoformat()}
    payload = {"contract_version": CONTRACT_VERSION, "meta": meta, "series": series, "drivers": drivers, "signals": signals, "lenses": lenses,
               "pipeline": pipeline, "risk": risk, "rest_of_year": rest_of_year, "outlook": outlook, "qc": qc, "capabilities": capabilities}
    from . import assumptions as _asm
    meta["assumptions"] = _asm.build(payload, inp, {"BREADTH_SHARE": BREADTH_SHARE, "MIN_CLOSED_FOR_RATE": MIN_CLOSED_FOR_RATE})
    payload["analysis_hash"] = sha256_of({k: v for k, v in payload.items() if k != "meta"} | {"meta": {k: v for k, v in meta.items() if k != "generated_at"}})
    return payload


# ------------------------------------------------------------------ prose
def _kpi(L, kid):
    return next(k for k in L["kpis"] if k["id"] == kid)


def _move(v, word_up="up", word_down="down"):
    return f"{word_up} {money(abs(v))}" if v >= 0 else f"{word_down} {money(abs(v))}"


def _insights(L, signals, series, months, as_of):
    out = []
    tot, new, up, nr = (_kpi(L, k) for k in ("total", "arr_new", "arr_upsell", "non_recurring"))
    var, mon = tot["variance"], L["materiality"]["monitoring_abs"]
    meas = sorted(L["drivers"]["measure"], key=lambda r: -abs(r["variance"]))
    lead_m = meas[0]
    share_net = lead_m["variance"] / var if var else 0
    where = f"{money(abs(var))} ({pct(abs(tot['variance_pct']))}) {'ahead of' if var > 0 else 'behind'} {L['range']['cmp_label']} ({CMP_SHORT})" if abs(var) >= mon else f"in line with {L['range']['cmp_label']} ({CMP_SHORT})"
    if abs(var) < mon:
        head, mean_ = f"In line with {CMP_SHORT}.", "no measure moved enough to change the picture"
    elif share_net >= 0.6 and lead_m["variance"] * var > 0:
        kind = {"m:arr_new": "New-sales-led", "m:arr_upsell": "Expansion-led", "m:non_recurring": "Non-recurring-led"}[lead_m["id"]]
        head = f"{kind} {'growth' if var > 0 else 'decline'}."
        mean_ = f"{lead_m['label']} carries {pct(share_net, dec=0)} of the change"
    else:
        br = L.get("breadth") or {}
        bs, bp = br.get("subsidiary") or {}, br.get("product") or {}
        broad = (is_num(bs.get("share")) and bs["share"] >= BREADTH_SHARE and is_num(bp.get("share")) and bp["share"] >= BREADTH_SHARE)
        mean_ = f"new ARR {money(new['variance'], True)}, upsell ARR {money(up['variance'], True)}, non-recurring {money(nr['variance'], True)}"
        if broad:
            head = f"Broad-based {'growth' if var > 0 else 'decline'}."
        else:
            head = f"{'Growth' if var > 0 else 'Decline'} from {bs.get('up', 0)} of {bs.get('of', 0)} subsidiaries." if bs.get("of") else "Mixed result."
            worst = min(L["drivers"]["product"], key=lambda r: r["variance"]) if L["drivers"]["product"] else None
            if worst and worst["variance"] < 0:
                mean_ += f"; {bp.get('up', 0)} of {bp.get('of', 0)} products up, {worst['label']} {money(worst['variance'])}"
    out.append({"id": "lead", "tone": "fav" if var >= mon else "unf" if var <= -mon else "neu", "lead": True, "ref": "kpi:total",
                "head": head, "text": f"Total bookings {money(tot['actual'])} for {L['range']['label']}, {where}: {mean_}."})

    cands = []
    # repeatable? concentration in a few customers
    c = L["concentration"]
    mv = c["customer_movers"][:2]
    if var > mon and is_num(c["top2_movers_share_of_change"]) and c["top2_movers_share_of_change"] >= 0.4 and all(m["variance"] > 0 for m in mv):
        sh = c["top2_movers_share_of_change"]
        part = (f"more than the whole net increase of {money(var)}, so the other customers are flat to down in total" if sh >= 1
                else f"{pct(sh, dec=0)} of the increase")
        cands.append((1, {"id": "concentration", "tone": "neu", "ref": "conc:customers", "head": "Growth rests on a few customers.",
                          "text": f"Two customers ({join_and([m['label'] for m in mv])}) add {money(mv[0]['variance'] + mv[1]['variance'])}, "
                                  f"{part}: confirm these orders repeat before treating the level as run-rate."}))
    elif is_num(c["top2_share"]) and c["top2_share"] >= 0.3:
        cands.append((2, {"id": "concentration", "tone": "neu", "ref": "conc:customers", "head": "Concentrated in two customers.",
                          "text": f"The two largest customers hold {pct(c['top2_share'], dec=0)} of recurring bookings in the window: a single delayed deal moves the result."}))
    # persistence of the latest month (month view only: a window total has no usual monthly range)
    sid = next((r["id"] for r in meas if "outlier_month" in signals[r["id"]]["fired"]), "total") if L["window"] == "MTD" else None
    sig = signals.get(sid) if sid else None
    if sig and "outlier_month" in sig["fired"] and is_num(sig["runrate"].get("mean")) and \
            abs(series[sid]["actual"][-1] - sig["runrate"]["mean"]) >= L["materiality"]["executive_abs"]:
        rr, a = sig["runrate"], series[sid]["actual"][-1]
        lbl = next((r["label"] for r in meas if r["id"] == sid), "Total bookings")
        h = sig["persistence_hint"]
        mean_ = {"one_off_candidate": "treat it as a one-off until next month confirms the level", "seasonal": "the same month moved the same way last year, so read it as seasonal",
                 "recurring_level_change": "a second month at this level, so it reads as a new level"}.get(h, "watch next month")
        cands.append((1, {"id": "persistence", "tone": "neu", "ref": "driver:" + sid if sid != "total" else "kpi:total",
                          "head": {"one_off_candidate": "Likely a one-off month.", "seasonal": "Seasonal, not a trend.", "recurring_level_change": "A new level."}.get(h, "An unusual month."),
                          "text": f"{lbl} in {month_name(as_of)} is {money(a)}, against a usual {money(rr['min'])}–{money(rr['max'])} a month: {mean_}."}))
    # quality: recurring share and mix
    rs = _kpi(L, "recurring_share")
    if is_num(rs.get("variance")) and abs(rs["variance"]) >= 0.01:
        better = rs["variance"] > 0
        cands.append((3, {"id": "quality", "tone": "fav" if better else "unf", "ref": "kpi:recurring_share",
                          "head": "Better-quality bookings." if better else "Lower-quality bookings.",
                          "text": f"Recurring share {pct(rs['actual'])}, {pts(rs['variance'])} on {CMP_SHORT}, with non-recurring {money(nr['variance'], True)}: "
                                  f"{'more of each dollar booked repeats next year' if better else 'less of each dollar booked repeats next year'}."}))
    # what moved: the largest product up and down
    prod = sorted([r for r in L["drivers"]["product"] if abs(r["variance"]) >= mon], key=lambda r: -r["variance"])
    ups, downs = [r for r in prod if r["variance"] > 0][:2], [r for r in prod if r["variance"] < 0][-1:]
    if ups or downs:
        lead_txt = join_and([f"{r['label']} ({money(r['variance'], True)})" for r in ups])
        down_txt = f"{downs[0]['label']} is the largest decline, {money(abs(downs[0]['variance']))} below {CMP_SHORT}" if downs else "no product fell materially"
        cands.append((2, {"id": "products", "tone": "neu", "ref": "driver:" + (ups or downs)[0]["id"], "head": "Growth is uneven across products." if downs else "Products move together.",
                          "text": (f"{lead_txt} lead{'s' if len(ups) == 1 else ''} the change; " if ups else "") + f"{down_txt}: "
                                  + ("the gains carry the declining line, so check whether its customers are moving to another product." if downs else "the gain is not one product's story.")}))
    org = L.get("organic") or {}
    if org.get("excluded") and is_num(org.get("variance_pct")) and is_num(tot.get("variance_pct")):
        names = join_and([e["label"] for e in org["excluded"]])
        cands.append((2, {"id": "organic", "tone": "neu", "ref": "kpi:total", "head": "Part of the growth is new subsidiaries.",
                          "text": f"{names} had no bookings in the same months {CMP_SHORT} ({money(sum(e['actual'] for e in org['excluded']))} now); without "
                                  f"{'it' if len(org['excluded']) == 1 else 'them'} growth is {pct(org['variance_pct'], sign=True)} against {pct(tot['variance_pct'], sign=True)}: "
                                  "whether this is an acquisition is for management to confirm."}))
    # deal size vs volume
    aov = _kpi(L, "aov")
    if is_num(aov.get("variance_pct")) and aov.get("orders_cmp"):
        vol = aov["orders"] / aov["orders_cmp"] - 1
        if abs(aov["variance_pct"]) >= 0.05 and abs(aov["variance_pct"]) > 2 * abs(vol):
            bigger = aov["variance_pct"] > 0
            cands.append((3, {"id": "size", "tone": "neu", "ref": "kpi:aov", "head": "Deal size, not volume." if bigger else "Smaller deals.",
                              "text": f"Deals booked {pct(vol, sign=True)} on {CMP_SHORT} while the average deal {pct(aov['variance_pct'], sign=True)} to {money(aov['actual'])}: "
                                      + ("fewer, larger deals make the result lumpier and more exposed to a single slip." if bigger else "more, smaller deals spread the risk but need more volume to grow.")}))
    cands.sort(key=lambda x: x[0])
    picked = [x[1] for x in cands[:4]]
    order = ["persistence", "concentration", "organic", "products", "quality", "size"]
    out += sorted(picked, key=lambda x: order.index(x["id"]))
    return out


def _driver_reading(L, r, sig, ser, as_of):
    out = []
    if is_num(r.get("share_of_abs_variance")):
        out.append(f"{pct(r['share_of_abs_variance'], dec=0)} of the gross movement across its dimension over the {L['window_label']}")
    if sig and sig["runrate"].get("eligible") and ser:
        rr, a = sig["runrate"], ser["actual"][-1]
        if "outlier_month" in sig["fired"]:
            out.append(f"{month_name(as_of)} at {money(a)} sits outside its usual {money(rr['min'])}–{money(rr['max'])} a month")
        else:
            out.append(f"{month_name(as_of)} at {money(a)} sits within its usual {money(rr['min'])}–{money(rr['max'])} a month")
        if "step_change" in sig["fired"]:
            out.append("a new level that has held for two months")
        if "seasonal_echo" in sig["fired"]:
            out.append(f"the same move happened last {month_name(as_of)}, so likely seasonal")
    return [o[0].upper() + o[1:] + "." for o in out]


def _actions(L, as_of):
    """Decisions for the Bookings tab: questions about the bookings result only (pipeline asks live on the Pipeline tab)."""
    acts = []
    due = (month_end(as_of) + dt.timedelta(days=30)).isoformat()
    c = L["concentration"]
    mv = c["customer_movers"][:2]
    tot = _kpi(L, "total")
    if tot["variance"] > 0 and is_num(c["top2_movers_share_of_change"]) and c["top2_movers_share_of_change"] >= 0.4 and all(m["variance"] > 0 for m in mv):
        acts.append({"id": "a:concentration", "rule": "concentrated_growth", "ref": "conc:customers",
                     "question": f"Do the increases from {join_and([m['label'] for m in mv])} repeat, or should the run-rate exclude them?",
                     "owner": "Sales leadership with FP&A", "date": due, "exposure": round(mv[0]["variance"] + mv[1]["variance"], 2), "exposure_label": "of the increase",
                     "evidence": ["contract terms and start dates", "whether similar deals sit in late-stage pipeline"]})
    downs = sorted([r for r in L["drivers"]["product"] if r["variance"] <= -L["materiality"]["management_abs"]], key=lambda r: r["variance"])
    if downs:
        d = downs[0]
        acts.append({"id": "a:product", "rule": "product_decline", "ref": "driver:" + d["id"],
                     "question": f"What is behind the {d['label']} decline? {money(abs(d['variance']))} below {CMP_SHORT} over the {L['window_label']}.",
                     "owner": f"{d['label']} product lead with Sales", "date": due, "exposure": round(abs(d["variance"]), 2), "exposure_label": f"below {CMP_SHORT}",
                     "evidence": ["cancellations and downgrades in the product", "customers moving to another product", "the open pipeline for the product"]})
    rs, nr = _kpi(L, "recurring_share"), _kpi(L, "non_recurring")
    if is_num(rs.get("variance")) and rs["variance"] <= -0.02 and nr["variance"] > 0:
        acts.append({"id": "a:quality", "rule": "quality_drop", "ref": "kpi:recurring_share",
                     "question": f"Plan next year on recurring bookings only? Recurring share fell {pts(rs['variance'])} to {pct(rs['actual'])} while non-recurring added {money(nr['variance'])}.",
                     "owner": "FP&A with Sales leadership", "date": due, "exposure": round(nr["variance"], 2), "exposure_label": "non-recurring growth",
                     "evidence": ["the non-recurring orders behind the growth", "whether each is a project or a repeat order"]})
    prio = ["concentrated_growth", "product_decline", "quality_drop"]
    return sorted(acts, key=lambda a: prio.index(a["rule"]))[:3]


def _short_line(b):
    """The one line shown on the page for a bullet: no figures; the full text opens one click down."""
    h, t = b.get("head", ""), b.get("tone")
    i = b.get("id")
    if i == "lead":
        stand = "ahead of" if t == "fav" else "behind" if t == "unf" else "in line with"
        return f"Total bookings are {stand} {CMP_SHORT}: {h.rstrip('.').lower()}."
    if i == "velocity":
        return ("Deals are taking longer to win, pushing bookings into later quarters." if t == "unf" else
                f"Deals are closing faster than {CMP_SHORT}, bringing bookings forward." if t == "fav" else
                "The sales cycle is steady, so timing rests on the close dates.")
    if i == "concentration":
        return ("Two customers carry most of the increase; confirm their deals repeat." if h.startswith("Growth rests")
                else "One delayed deal from either would move the result.")
    if i == "persistence":
        return {"Likely a one-off month.": "The latest month sits outside its usual range; treat it as one-off for now.",
                "Seasonal, not a trend.": "The latest month moved as it did last year: seasonal, not a trend.",
                "A new level.": "A second month at this level: it reads as a new level."}.get(h, "The latest month is unusual; watch next month before calling a trend.")
    if i == "quality":
        return "Recurring share rose, so more of each dollar booked repeats next year." if t == "fav" else "Recurring share fell, so less of each dollar booked repeats next year."
    if i == "products":
        return "Product gains carry a declining line; check where its customers are going." if h.startswith("Growth is uneven") else "The gain is spread across products, not one product's story."
    if i == "size":
        return "Fewer, larger deals make the result lumpier and more exposed to a slip." if h.startswith("Deal size") else "More, smaller deals spread the risk but need more volume to grow."
    if i == "high_value":
        return "Some of the largest open deals are not closing or are stuck." if t == "unf" else "The largest open deals are moving."
    if i == "not_closing":
        return "Forecasts built on these close dates overstate next quarter."
    if i == "stuck":
        return "Each needs a dated next step or should leave the pipeline."
    if i == "conversion":
        if h.startswith("Most of the value") or h.startswith("Conversion by value"):
            return "Most of the value is lost; winning the large deals decides the year." if t == "unf" else "Value conversion holds; the large deals still decide the year."
        return ("Winning the large deals decides the year." if h.startswith("Large deals")
                else "More of the pipeline is turning into bookings." if h.startswith("Conversion improving") else "Less of the pipeline is turning into bookings.")
    first = re.split(r"[:;]", b.get("text", ""))[0].split()
    return " ".join(first[:15]).rstrip(",.") + "."


def _add_short(items):
    for b in items or []:
        if b.get("id") == "velocity":                       # the bold lead carries no figures; the days are in the text
            b["head"] = "Slower to win." if b.get("tone") == "unf" else "Faster to win." if b.get("tone") == "fav" else "Steady sales cycle."
        b["short"] = _short_line(b)
    return items


def _add_ask_short(acts):
    """The question on the page: the first question clause, at most twelve words; the full question opens one click down."""
    for a in acts or []:
        q = (a.get("question") or "").strip()
        first = q.split("?")[0].strip()
        w = first.split()
        if len(w) > 14:                                    # cut at the last comma inside the first twelve words, else at twelve words
            head12 = " ".join(w[:12])
            first = head12[:head12.rfind(",")] if "," in head12 else head12
        a["short"] = first.rstrip(",;:") + "?"
    return acts


def _pipeline_insights(L, pipeline, risk):
    """Executive summary for the Pipeline tab: velocity first, then what is exposed (high value, not closing, stuck)
    and conversion. Weighted pipeline values; no targets. Every figure comes from the payload; each bullet says what it impacts."""
    v, h, op = L.get("velocity"), pipeline["in_quarter"], pipeline["open"]
    in_q = h.get("open")
    in_share = in_q / op if is_num(in_q) and op else None
    out, cands = [], []
    if v and is_num(v["avg_days"]):
        var = v["variance_days"]
        small = v.get("small_sample")
        slower, faster = (not small) and is_num(var) and var >= 3, (not small) and is_num(var) and var <= -3
        hv = v["hv"]
        hv_txt = f"; deals of {money(HIGH_VALUE_ACV)} or more took {hv['avg_days']:.0f} days ({plural(hv['n'], 'deal')})" if is_num(hv["avg_days"]) else ""
        cmp_txt = f", against {v['cmp']['avg_days']:.0f} days {CMP_SHORT}" if is_num(v["cmp"]["avg_days"]) else ""
        meaning = ("a longer cycle pushes more of it into later quarters' bookings" if slower else
                   "a shorter cycle brings bookings forward" if faster else "the cycle is steady, so timing rests on the close dates")
        tail = (f" Of {money(op)} open pipeline, {money(in_q)} ({pct(in_share, dec=0)}) is dated to close in {h['quarter']}: {meaning}." if is_num(in_q)
                else f" {cap_(meaning)}.")
        head = (f"Deals take {v['avg_days']:.0f} days to win, {abs(var):.0f} days {'slower' if slower else 'faster'} than {CMP_SHORT}." if (slower or faster)
                else f"Deals take {v['avg_days']:.0f} days to win, on a small sample." if small
                else f"Deals take {v['avg_days']:.0f} days to win, in line with {CMP_SHORT}.")
        out.append({"id": "velocity", "tone": "unf" if slower else "fav" if faster else "neu", "lead": True, "ref": "velocity",
                    "head": head, "text": f"Deals won in {L['range']['label']} took {v['avg_days']:.0f} days on average from opportunity to close "
                                          f"({plural(v['n'], 'deal')}" + (f"; {plural(v['same_day'], 'same-day win')} left out" if v["same_day"] else "") + f"){cmp_txt}{hv_txt}.{tail}"})
    hvb = risk["high_value"]
    r_open, r_asof = risk["open"]["acv"], risk["as_of"]           # the deal lists are current state: shares and remainders use that total
    if hvb["count"]:
        fl = hvb["flagged"]
        left = r_open - fl["acv"] if r_open else None
        cands.append((1, {"id": "high_value", "tone": "unf" if fl["count"] else "neu", "ref": "risk:high_value", "head": "High-value deals carry the pipeline.",
                          "text": f"{plural(hvb['count'], 'deal')} of {money(hvb['cutoff'])} or more hold {money(hvb['acv'])}, {pct(hvb['share'], dec=0)} of the "
                                  f"{money(r_open)} open pipeline at {r_asof}"
                                  + (f"; {fl['count']} of them, {money(fl['acv'])} or {pct(fl['share'], dec=0)} of the pipeline, are not closing or stuck: if they slip, "
                                     f"open pipeline falls to {money(left)}." if fl["count"] else ": none is flagged, so the large deals are moving.")}))
    nc = risk["not_closing"]
    if nc["count"]:
        top = max(nc["by_stage"], key=lambda r: r["acv"]) if nc["by_stage"] else None
        cands.append((2, {"id": "not_closing", "tone": "unf", "ref": "risk:not_closing", "head": "Close dates keep moving.",
                          "text": f"{plural(nc['count'], 'deal')}, {money(nc['acv'])} or {pct(nc['share'], dec=0)} of open pipeline at {r_asof}, {'is' if nc['count'] == 1 else 'are'} "
                                  f"past due or pushed out ({nc['pushed']['count']} pushed, {nc['past_due']['count']} past due)"
                                  + (f"; the most sits in {top['label']} ({money(top['acv'])})" if top else "")
                                  + ": forecasts built on these close dates overstate the next quarter."}))
    st = risk["stuck"]
    if st.get("customer_count"):
        cands.append((3, {"id": "stuck", "tone": "unf", "ref": "risk:stuck", "head": "Customers stuck in the funnel.",
                          "text": f"{plural(st['customer_count'], 'customer')} {'has' if st['customer_count'] == 1 else 'have'} deals in their stage "
                                  + ("longer than 90% of completed stays (P90)" if st.get("benchmark") == "p90" else f"over {mult(st['multiple'])} the median stay")
                                  + f", {money(st['recurring'])} recurring ACV at stake; the largest are "
                                  f"{join_and([c['customer'] for c in st['customers'][:2]])}: each needs a dated next step or should leave the pipeline."}))
    conv, wr = L["conversion"], _kpi(L, "win_rate")
    lo = L.get("lost")
    cs, csp = L.get("conv_size"), L.get("conv_size_cmp")
    if cs and is_num(cs["value_win_rate"]):
        dv = cs["value_win_rate"] - csp["value_win_rate"] if csp and is_num(csp.get("value_win_rate")) else None
        lost_txt = f"; lost ACV {money(lo['acv'])}, {pct(lo['variance_pct'], sign=True)} on {CMP_SHORT}" if lo and is_num(lo.get("variance_pct")) else ""
        k5 = f"; deals of $5k or more win {pct(cs['win_rate_5k'], dec=0)} by count ({cs['won_5k']} won, {cs['lost_5k']} lost)" if is_num(cs.get("win_rate_5k")) else ""
        neg = f", excluding {money(abs(cs['won_neg']))} of negative-ACV wins" if cs["won_neg"] < -0.5 else ""
        cands.append((2, {"id": "conversion", "tone": "unf" if cs["value_win_rate"] < 0.4 or (is_num(dv) and dv < -0.03) else "neu", "ref": "conv:win",
                          "head": "Most of the value is lost." if cs["value_win_rate"] < 0.4 else "Conversion by value.",
                          "text": f"Value win rate {pct(cs['value_win_rate'], dec=0)}" + (f" ({pts(dv)} on {CMP_SHORT})" if is_num(dv) else "") + f"{neg}{k5}{lost_txt}: "
                                  "winning the large deals decides the year."}))
    elif not wr.get("small_sample") and is_num(conv["win_rate"]):
        gap = is_num(conv.get("win_rate_value")) and conv["win_rate"] - conv["win_rate_value"] >= 0.2
        lost_txt = f"; lost ACV {money(lo['acv'])}, {pct(lo['variance_pct'], sign=True)} on {CMP_SHORT}" if lo and is_num(lo.get("variance_pct")) else ""
        if gap or (is_num(wr.get("variance")) and abs(wr["variance"]) >= 0.03):
            cands.append((2 if gap else 3, {"id": "conversion", "tone": "unf" if gap or (wr.get("variance") or 0) < 0 else "fav", "ref": "conv:win",
                                            "head": "Large deals are lost far more often." if gap else ("Conversion improving." if wr["variance"] > 0 else "Conversion slipping."),
                                            "text": f"Win rate {pct(conv['win_rate'], dec=0)} by count ({pts(wr.get('variance'))} on {CMP_SHORT})"
                                                    + (f" but {pct(conv['win_rate_value'], dec=0)} by value: {money(conv['lost']['acv'])} lost against "
                                                       f"{money(conv['won']['acv'])} won" if gap else "")
                                                    + f"{lost_txt}: " + ("winning the large deals decides the year." if gap else
                                                                         "more of the pipeline turns into bookings." if wr["variance"] > 0 else
                                                                         "less of the pipeline turns into bookings.")}))
    cands.sort(key=lambda x: x[0])
    order = ["high_value", "not_closing", "stuck", "conversion"]
    out += sorted([x[1] for x in cands[:5 - len(out)]], key=lambda x: order.index(x["id"]))
    return out[:5]


def _pipeline_actions(L, pipeline, risk, as_of):
    """Decisions for the Pipeline tab: the risk asks (there is no target, so no cover or generation asks)."""
    acts = list(risk["actions"])
    prio = ["high_value_at_risk", "not_closing_share", "stuck_customers"]
    return sorted(acts, key=lambda a: prio.index(a["rule"]))[:3]


def cap_(t):
    return t[:1].upper() + t[1:] if t else t
