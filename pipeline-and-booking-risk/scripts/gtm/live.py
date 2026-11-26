"""Governed loader: turns saved GTM_ANALYTICS extracts into the engine's inputs.

Each extract is one governed SEMANTIC_VIEW statement saved as a file: the sql-exec JSON
result (result_set.data + rowType) or a CSV with the column names the view returned.
The statements and file names are in references/dashboards.md §2:

  gtm-lines-*.json          BOOKING_LINES by booking date, metric, opportunity type, product, subsidiary, account and opportunity
  gtm-open-*.json           open OPPORTUNITIES lines (account, owner, product, source, type, stage, close date, open ACV and WEIGHTED open ACV)
  gtm-conv-source.json      won / lost ACV and opportunities by close month and opportunity source
  gtm-conv-product.json     the same by close month and product
  gtm-created.json          PIPELINE_CREATED_ACV and OPPORTUNITIES_CREATED by creation month
  gtm-stage-current*.json   every stage run of the open opportunities (start date, close date at the end of each run), one or more chunks
  gtm-stage-medians.json    median completed stay per stage, and per stage and account the median of OTHER accounts' stays (optional)
  gtm-stage-p90.json        P90 / P75 / mean of completed non-zero stays per pipeline stage (optional)
  gtm-lost-*.json           closed-lost opportunities (account, product, source, close date, LOST_ACV_USD) (optional)
  gtm-lost-stage.json       the stage each lost opportunity was lost at (optional)
  gtm-velocity.json         closed-won opportunities by close month and size band: count and days from created to won (optional)
  gtm-conv-size.json        won / lost ACV of positive-ACV opportunities and $5k+ counts by close month (optional)
  gtm-cards.json            PIPELINE_OVERVIEW KPI cards at IS_LATEST (open, counts, average, created; PY twins)
  gtm-cards-snapshot.json   the same cards at the bookings month-end (the headline pipeline date)
  gtm-snapshot-ecq.json     weighted pipeline at the bookings month-end by stage and close date (grouped here into fiscal quarters) (recommended)
  gtm-bookings-mart.json    BOOKINGS_OVERVIEW TOTAL_BOOKINGS_MTD at every month-end (tie-out only)

Pipeline is WEIGHTED (ACV x Salesforce PROBABILITY / 100): the open lines carry WEIGHTED_OPEN_PIPELINE_ACV, the
cards and the snapshot carry WEIGHTED_PIPELINE_VALUE_* / WEIGHTED_PIPELINE_ACV_ASAT, and this loader hands the engine
the weighted figure as "open" / "acv" so every pipeline figure (close quarters, stage grid, risk tiers) is weighted and
ties to the weighted card. The unweighted value is kept alongside (OPEN_PIPELINE_VALUE_*_UNWEIGHTED, "acv_unweighted")
for context only. Pipeline created, won and lost stay unweighted (the view has no weighted twins).
The view has no pipeline targets, no loss reason and no subscription state: none of them is read.
Quarters are fiscal, and the fiscal year is the calendar year (common.FY_START_MONTH = 1).

Fails closed: a file whose returned rows differ from the reported row count (a capped tool
result), overlapping line chunks or a missing month all raise BuildError."""
import csv
import datetime as dt
import glob
import json
import os

from .common import BuildError, qlabel, to_date, to_num

REQUIRED = ("gtm-lines-*", "gtm-open-*", "gtm-conv-source", "gtm-conv-product", "gtm-created")
LATE_STAGE_ORDER = 5            # Align onwards (DIM_STAGE_MAPPING.STAGE_ORDER; 1 = Stage 0, 7 = Invest)


def read_rows(path):
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{k.strip().upper(): (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rs = doc.get("result_set", doc)
    meta = rs.get("resultSetMetaData", {})
    cols = [c["name"].upper() for c in meta.get("rowType", [])]
    data = rs.get("data", [])
    if not cols:
        raise BuildError(f"{os.path.basename(path)}: no column names (rowType) in the result")
    n = meta.get("numRows")
    if n is not None and int(n) != len(data):
        raise BuildError(f"{os.path.basename(path)}: {len(data)} rows returned but the statement reported {n}; "
                         "the tool capped the result, so split the extract into smaller chunks")
    return [dict(zip(cols, r)) for r in data]


def _files(folder, stem):
    out = sorted(glob.glob(os.path.join(folder, stem + ".json")) + glob.glob(os.path.join(folder, stem + ".csv")))
    return out


def _month(d):
    return dt.date(d.year, d.month, 1)


def _true(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def _src(r):
    return str(r.get("OPPORTUNITY_SOURCE") or r.get("DEAL_SOURCE") or "Unknown")


def load(folder):
    """Return (inputs, provenance) for engine.build()."""
    for stem in REQUIRED:
        if not _files(folder, stem):
            raise BuildError(f"missing extract {stem} in {folder} (see references/dashboards.md §2)")
    prov = []

    # bookings lines, chunked by date: no overlap, no gap. Shaped to the engine's line keys:
    # BOOKINGS_DATE, COMPANY_NAME (the Salesforce account) and SOURCE_ORDER (the opportunity).
    lines, spans = [], []
    for f in _files(folder, "gtm-lines-*"):
        rows = read_rows(f)
        ds = [to_date(r.get("BOOKING_DATE") or r.get("BOOKINGS_DATE")) for r in rows]
        if ds:
            spans.append((min(ds), max(ds), os.path.basename(f)))
        for r, d in zip(rows, ds):
            lines.append({"BOOKINGS_DATE": d, "BOOKING_METRIC": r.get("BOOKING_METRIC"), "OPPORTUNITY_TYPE": r.get("OPPORTUNITY_TYPE"),
                          # lines are held to the cent: the view carries 6 decimals, and with hundreds of products per-step rounding would
                          # otherwise leave the bridges a few cents out
                          "BOOKING_ACV_USD": round(to_num(r.get("BOOKING_ACV_USD")) or 0.0, 2), "PRODUCT": r.get("PRODUCT"), "SUBSIDIARY_NAME": r.get("SUBSIDIARY_NAME"),
                          "COMPANY_NAME": r.get("ACCOUNT_NAME") or r.get("COMPANY_NAME"),
                          "SOURCE_ORDER": r.get("OPPORTUNITY_ID") or r.get("SOURCE_ORDER")})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})
    spans.sort()
    for (a0, a1, fa), (b0, b1, fb) in zip(spans, spans[1:]):
        if _month(b0) <= _month(a1):
            raise BuildError(f"line chunks overlap: {fa} ends {a1} and {fb} starts {b0}")
    months = sorted({_month(x["BOOKINGS_DATE"]) for x in lines})
    m = months[0]
    while m <= months[-1]:
        if m not in months:
            raise BuildError(f"no booking lines for {m:%Y-%m}: a chunk is missing")
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)

    # open pipeline: one row per opportunity line; the governed open metric applies the open filter, so a row with no open
    # ACV is not pipeline. The engine works on the WEIGHTED value (WEIGHTED_OPEN_PIPELINE_ACV = ACV x probability / 100).
    open_deals = []
    for f in _files(folder, "gtm-open-*"):
        rows = read_rows(f)
        if rows and "WEIGHTED_OPEN_PIPELINE_ACV" not in rows[0]:
            raise BuildError(f"{os.path.basename(f)}: no WEIGHTED_OPEN_PIPELINE_ACV column; the open extract must carry the weighted metric "
                             "(references/dashboards.md §2)")
        for r in rows:
            unw = to_num(r.get("OPEN_PIPELINE_ACV")) or 0.0
            if unw == 0:
                continue
            acv = to_num(r.get("WEIGHTED_OPEN_PIPELINE_ACV")) or 0.0
            close = to_date(r["CLOSE_DATE"]) if r.get("CLOSE_DATE") else None
            open_deals.append({"id": str(r["OPPORTUNITY_ID"]), "name": str(r.get("OPPORTUNITY_NAME") or ""), "owner": str(r.get("OWNER_NAME") or ""),
                               "product": str(r.get("PRODUCT") or ""), "source": _src(r),
                               "stage": str(r.get("STAGE_NAME") or ""), "stage_order": int(to_num(r.get("STAGE_ORDER")) or 99),
                               "close": close, "ecq": qlabel(close) if close else "", "acv": acv, "acv_unweighted": unw,
                               "probability": to_num(r.get("PROBABILITY")),
                               "account": str(r.get("ACCOUNT_NAME") or "") or None, "family": r.get("PRODUCT_FAMILY"),
                               "stype": r.get("OPPORTUNITY_TYPE"),
                               "pipe_created": to_date(str(r["PIPELINE_CREATION_DATE"])[:10]) if r.get("PIPELINE_CREATION_DATE") else None,
                               "opened": to_date(str(r["CREATED_DATE"])[:10]) if r.get("CREATED_DATE") else None,
                               "refreshed": to_date(str(r["DATA_REFRESHED_AT"])[:10]) if r.get("DATA_REFRESHED_AT") else None})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})

    # conversion aggregates (governed WON_ / LOST_ metrics); source is opportunity-level, so its rows add to the totals
    closed = []
    for stem, dim in (("gtm-conv-source", "source"), ("gtm-conv-product", "product")):
        f = _files(folder, stem)[0]
        rows = read_rows(f)
        for r in rows:
            label = _src(r) if dim == "source" else str(r.get("PRODUCT") or "Unknown")
            closed.append({"m": _month(to_date(r["CLOSE_MONTH"])), "dim": dim, "label": label,
                           "won_acv": to_num(r.get("WON_ACV_USD")) or 0.0, "lost_acv": to_num(r.get("LOST_ACV_USD")) or 0.0,
                           "won_n": int(to_num(r.get("WON_OPPORTUNITIES")) or 0), "lost_n": int(to_num(r.get("LOST_OPPORTUNITIES")) or 0)})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})

    f = _files(folder, "gtm-created")[0]
    rows = read_rows(f)
    created = [{"m": _month(to_date(r["CREATED_MONTH"])), "acv": to_num(r.get("PIPELINE_CREATED_ACV")) or 0.0,
                "n": int(to_num(r.get("OPPORTUNITIES_CREATED")) or 0)} for r in rows]
    prov.append({"file": os.path.basename(f), "rows": len(rows)})

    # stage runs of the open opportunities: the current run gives the stage start; the close date at the end of each
    # run gives the pushes (one row per opportunity per STAGE_RUN_NO)
    cur_start, hist_rows, flagged_start = {}, {}, {}
    for f in _files(folder, "gtm-stage-current*"):
        rows = read_rows(f)
        for r in rows:
            d = to_date(r["STAGE_START_DATE"]) if r.get("STAGE_START_DATE") else None
            k = str(r["OPPORTUNITY_ID"])
            if d and (k not in cur_start or d > cur_start[k]):
                cur_start[k] = d
            if d and _true(r.get("IS_CURRENT_STAGE")):
                flagged_start[k] = d       # the current-stage row wins over the latest start date
            run = to_num(r.get("STAGE_RUN_NO") if r.get("STAGE_RUN_NO") is not None else r.get("STAGE_CHANGE_NO")) or 0
            cd = r.get("CLOSE_DATE") or r.get("CLOSE_DATE_ASOF")
            hist_rows.setdefault(k, {})[run] = to_date(cd) if cd else None
        prov.append({"file": os.path.basename(f), "rows": len(rows)})
    cur_start.update(flagged_start)
    close_hist = {k: [v[n] for n in sorted(v)] for k, v in hist_rows.items()}

    # pipeline risk (optional extracts): stage medians, lost opportunities and the stage each was lost at
    medians, lost_lines, lost_at = None, None, {}
    for f in _files(folder, "gtm-stage-medians"):
        rows = read_rows(f)
        medians = medians or {"overall": {}, "loo": {}}
        for r in rows:
            m, n = to_num(r.get("MEDIAN_DAYS")), int(to_num(r.get("STAYS")) or 0)
            if r.get("ACCOUNT_NAME") in (None, ""):
                medians["overall"][str(r["STAGE_NAME"])] = (m, n)
            else:
                medians["loo"][(str(r["STAGE_NAME"]), str(r["ACCOUNT_NAME"]))] = (m, n)
        prov.append({"file": os.path.basename(f), "rows": len(rows)})
    for f in _files(folder, "gtm-lost-stage"):
        rows = read_rows(f)
        lost_at.update({str(r["OPPORTUNITY_ID"]): str(r["PREVIOUS_STAGE_NAME"]) for r in rows if r.get("PREVIOUS_STAGE_NAME")})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})
    for f in [x for x in _files(folder, "gtm-lost-*") if not os.path.basename(x).startswith("gtm-lost-stage")]:
        rows = read_rows(f)
        lost_lines = lost_lines or []
        for r in rows:
            acv = to_num(r.get("LOST_ACV_USD")) or 0.0
            if acv == 0:
                continue
            lost_lines.append({"id": str(r["OPPORTUNITY_ID"]), "name": str(r.get("OPPORTUNITY_NAME") or ""), "account": str(r.get("ACCOUNT_NAME") or "") or None,
                               "owner": str(r.get("OWNER_NAME") or ""), "product": str(r.get("PRODUCT") or ""), "family": r.get("PRODUCT_FAMILY"),
                               "stype": r.get("OPPORTUNITY_TYPE"), "source": _src(r), "reason": None,
                               "close": to_date(r["CLOSE_DATE"]) if r.get("CLOSE_DATE") else None, "acv": acv})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})
    for x in lost_lines or []:
        x["lost_stage"] = lost_at.get(x["id"])

    # velocity (optional): closed-won opportunities by close month and size band, banded in Snowflake at $100k ACV
    velocity = None
    for f in _files(folder, "gtm-velocity"):
        rows = read_rows(f)
        velocity = velocity or []
        for r in rows:
            band = str(r.get("BAND") or "").strip().lower()
            if band not in ("hv", "std"):
                raise BuildError(f"{os.path.basename(f)}: BAND must be 'hv' or 'std', got {r.get('BAND')!r}")
            velocity.append({"m": _month(to_date(r["CLOSE_MONTH"])), "band": band, "n": int(to_num(r.get("WON_OPPS")) or 0),
                             "sum_days": to_num(r.get("SUM_DAYS")) or 0.0, "acv": to_num(r.get("WON_ACV")) or 0.0,
                             "same_day": int(to_num(r.get("SAME_DAY")) or 0)})
        prov.append({"file": os.path.basename(f), "rows": len(rows)})

    def one(stem):
        fs = _files(folder, stem)
        if not fs:
            return None
        rows = read_rows(fs[0])
        prov.append({"file": os.path.basename(fs[0]), "rows": len(rows)})
        return rows

    def card(rows):
        """KPI cards with the pipeline value switched to WEIGHTED: OPEN_PIPELINE_VALUE_<W> takes WEIGHTED_PIPELINE_VALUE_<W>
        (the unweighted value is kept as <name>_UNWEIGHTED) and the average opportunity value is weighted value / open count."""
        if not rows:
            return None
        c = {k: (to_num(v) if k != "AS_OF_DATE" else str(v)[:10]) for k, v in rows[0].items()}
        for w in ("MTD", "PYMTD", "QTD", "PYQTD", "YTD", "PYYTD", "LTM", "PYLTM"):
            o, wt = f"OPEN_PIPELINE_VALUE_{w}", f"WEIGHTED_PIPELINE_VALUE_{w}"
            if o in c or wt in c:
                if wt not in c:
                    raise BuildError(f"KPI card extract has {o} but not {wt}: pipeline is weighted (references/dashboards.md §2)")
                c[o + "_UNWEIGHTED"], c[o] = c.get(o), c[wt]
                n = c.get(f"OPEN_OPPORTUNITIES_{w}")
                c[f"AVG_OPPORTUNITY_VALUE_ACV_{w}"] = c[wt] / n if c[wt] is not None and n else None
        return c
    cards = card(one("gtm-cards"))
    snapshot = card(one("gtm-cards-snapshot"))

    # the bookings mart, one row per month-end: TOTAL_BOOKINGS_MTD by month (its QTD / YTD / LTM are never used)
    bm = one("gtm-bookings-mart")
    mart = {_month(to_date(r["AS_OF_DATE"])): to_num(r.get("TOTAL_BOOKINGS_MTD")) for r in bm if r.get("AS_OF_DATE")} if bm else None

    # weighted pipeline at the bookings month-end by stage and close date (or close month, older extracts); the engine groups
    # it into past due / fiscal close quarters / later, so the buckets foot to the weighted snapshot card
    ecq_rows = one("gtm-snapshot-ecq")
    snapshot_ecq = None
    if ecq_rows is not None:
        snapshot_ecq = []
        for r in ecq_rows:
            cd = r.get("CLOSE_DATE") or r.get("CLOSE_MONTH")
            snapshot_ecq.append({"stage": str(r.get("STAGE_NAME") or "") or None, "close": to_date(str(cd)[:10]) if cd else None,
                                 "by_month": not r.get("CLOSE_DATE"), "open": to_num(r.get("WEIGHTED_PIPELINE_ACV_ASAT")) or 0.0,
                                 "open_unweighted": to_num(r.get("OPEN_PIPELINE_ACV_ASAT")),
                                 "count": int(to_num(r.get("OPEN_OPPORTUNITIES_ASAT")) or 0)})

    cs = one("gtm-conv-size")
    conv_size = [{"m": _month(to_date(r["CLOSE_MONTH"])), "won_pos": to_num(r.get("WON_ACV_POS")) or 0.0, "lost_pos": to_num(r.get("LOST_ACV_POS")) or 0.0,
                  "won_neg": to_num(r.get("WON_NEG_ACV")) or 0.0, "won_5k": int(to_num(r.get("WON_5K")) or 0), "lost_5k": int(to_num(r.get("LOST_5K")) or 0)}
                 for r in cs] if cs is not None else None
    sp = one("gtm-stage-p90")
    stage_p90 = {str(r["STAGE_NAME"]): {"p90": to_num(r.get("P90_DAYS")), "p75": to_num(r.get("P75_DAYS")), "mean": to_num(r.get("MEAN_DAYS")),
                                        "runs": int(to_num(r.get("RUNS")) or 0)} for r in sp} if sp is not None else None

    inputs = {"snapshot": snapshot, "snapshot_ecq": snapshot_ecq, "conv_size": conv_size, "stage_p90": stage_p90,
              "lines": lines, "open_deals": open_deals, "closed": closed, "created": created,
              "stage_days": {}, "cur_start": cur_start, "cards": cards, "bookings_mart": mart,
              "loss_reasons_available": False, "late_stage_order": LATE_STAGE_ORDER,
              "stage_medians": medians, "close_hist": close_hist, "lost_lines": lost_lines, "velocity": velocity}
    return inputs, prov
