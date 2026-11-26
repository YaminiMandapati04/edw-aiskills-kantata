"""Since-last-run comparison for the recurring GTM dashboard.

Each page embeds its whole payload, so the previous month's HTML is the record of the
previous run: no separate state file. The page keeps one fixed name (pipeline_risk_readout.html)
and is rebuilt on every run; when a run is for a later month than the page already there, that
page is first kept as previous/<name> beside it, so daily reruns within a month all compare with
the last page of the month before. This module finds that page, reads its payload and lists
what changed, deterministically. The result goes into the build's JSON line for the
hand-over message; the page itself is unchanged (contract sda.gtm-analysis/2.0.0).

Compared on stable ground only: the last-twelve-month lens (it never resets at a year or
quarter boundary), the pipeline snapshot (unweighted; there is no coverage), the actions of the
LTM lens and the QC checks. Two runs are compared only when both are on the same contract
and data mode; otherwise the comparison says why it is unavailable.
"""
import json
import os
import re
import shutil

from .common import MINUS, BuildError, is_num, money, pct

PAYLOAD_RE = re.compile(r"window\.__SDA_PAYLOAD__=(\{.*?\});</script>", re.S)
PAGE_RE = re.compile(r"gtm_diagnostic_(\d{4}-\d{2})\.html$")
LENS = "LTM_pq"          # last twelve months against the twelve months to a quarter earlier


def read_page_payload(path):
    """The payload embedded in a rendered page (render.py escapes '</' as '<\\/')."""
    with open(path, encoding="utf-8") as f:
        m = PAYLOAD_RE.search(f.read())
    if not m:
        raise BuildError(f"{os.path.basename(path)}: no embedded payload, so it cannot be compared")
    return json.loads(m.group(1).replace("<\\/", "</"))


def _page_month(path):
    """YYYY-MM of the page's as-of month, or None when it is missing or has no payload."""
    if not os.path.isfile(path):
        return None
    try:
        return read_page_payload(path)["meta"]["as_of"]["month_end"][:7]
    except (BuildError, KeyError, TypeError, ValueError):
        return None


def find_previous(out_path, as_of_ym):
    """The page to compare with, for a build about to write out_path for as_of_ym, or None.

    If the page at out_path is for an earlier month, it is the previous run: keep a copy as
    previous/<name> (it is about to be overwritten) and use it. Otherwise (a rerun within the
    month, or a first run) use previous/<name> when it is for an earlier month."""
    kept = os.path.join(os.path.dirname(os.path.abspath(out_path)), "previous", os.path.basename(out_path))
    m = _page_month(out_path)
    if m and m < as_of_ym:
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        shutil.copyfile(out_path, kept)
        return kept
    m = _page_month(kept)
    return kept if m and m < as_of_ym else None


def _pp(d):
    if not is_num(d):
        return "n/a"
    v = round(d * 10000)
    return ("+" if v > 0 else MINUS if v < 0 else "") + f"{abs(v):,} bps"


def _signed(d):
    return "no change" if d == 0 else money(d, sign=True)


def _chg(now, before):
    return round(now - before, 2) if is_num(now) and is_num(before) else None


def since_last(cur, prev, prev_file=None):
    """What changed between two payloads. Returns a dict with plain-English 'lines'."""
    base = {"previous": {"file": os.path.basename(prev_file) if prev_file else None,
                         "as_of": prev["meta"]["as_of"]["month_end"] if prev else None}}
    if prev is None:
        return {"available": False, "reason": "no earlier run in the output folder (first run)", **base}
    if prev.get("contract_version") != cur.get("contract_version"):
        return {"available": False, "reason": f"the earlier run is on contract {prev.get('contract_version')}", **base}
    if prev["meta"]["data_mode"] != cur["meta"]["data_mode"]:
        return {"available": False, "reason": f"the earlier run is {prev['meta']['data_mode']} data, this one {cur['meta']['data_mode']}", **base}
    if prev["meta"]["as_of"]["month_end"] >= cur["meta"]["as_of"]["month_end"]:
        return {"available": False, "reason": "the earlier page is not for an earlier month", **base}
    lines = []

    # bookings, last twelve months (either page may lack the lens when history is short)
    cl, pl_ = cur["lenses"].get(LENS) or {}, prev["lenses"].get(LENS) or {}
    ck = {k["id"]: k for k in cl.get("kpis", [])}
    pk = {k["id"]: k for k in pl_.get("kpis", [])}
    kpis = []
    for kid, k in ck.items():
        if kid not in pk:
            continue
        b = pk[kid]
        row = {"id": kid, "label": k["label"], "kind": k["kind"], "now": k["actual"], "before": b["actual"], "change": _chg(k["actual"], b["actual"]),
               "vs_cmp_now": k.get("variance_pct") if k["kind"] == "money" else k.get("variance"),
               "vs_cmp_before": b.get("variance_pct") if b["kind"] == "money" else b.get("variance")}
        kpis.append(row)
    tot = next((r for r in kpis if r["id"] == "total"), None)
    if tot and is_num(tot["change"]):
        lines.append(f"Last-twelve-month bookings {money(tot['now'])}, {money(tot['change'], sign=True)} on the last run "
                     f"({money(tot['before'])}); growth on the prior quarter {pct(tot['vs_cmp_now'], sign=True)} against {pct(tot['vs_cmp_before'], sign=True)}.")
    wr = next((r for r in kpis if r["id"] == "win_rate"), None)
    if wr and is_num(wr["change"]):
        lines.append(f"Win rate (last twelve months) {pct(wr['now'], dec=0)}, {_pp(wr['change'])} on the last run.")

    # pipeline snapshot
    cp, pp_ = cur["pipeline"], prev["pipeline"]
    pipe = {k: {"now": cp.get(k), "before": pp_.get(k), "change": _chg(cp.get(k), pp_.get(k))} for k in ("open", "open_count")}
    if is_num(pipe["open"]["change"]):
        lines.append(f"Open pipeline {money(cp['open'])} ({_signed(pipe['open']['change'])}), "
                     f"{int(cp['open_count'])} open opportunities (was {int(pp_['open_count'])}).")
    ciq, piq = cp.get("in_quarter") or {}, pp_.get("in_quarter") or {}
    if is_num(ciq.get("open")):
        was = f"{money(piq['open'])} for {piq.get('quarter')} last run" if is_num(piq.get("open")) else "no reading last run"
        lines.append(f"Open pipeline dated to close in {ciq.get('quarter')} {money(ciq['open'])} ({was}).")

    # actions and QC
    ca = {(a["rule"], a["ref"]): a for a in cl.get("actions", [])}
    pa = {(a["rule"], a["ref"]): a for a in pl_.get("actions", [])}
    new = [ca[k]["question"] for k in ca if k not in pa]
    cleared = [pa[k]["question"] for k in pa if k not in ca]
    for q in new:
        lines.append(f"New decision: {q}")
    for q in cleared:
        lines.append(f"No longer raised: {q}")
    cq = {c["id"]: c["result"] for c in cur["qc"]["checks"]}
    pq = {c["id"]: c["result"] for c in prev["qc"]["checks"]}
    qc_changed = [{"id": k, "now": v, "before": pq.get(k)} for k, v in cq.items() if pq.get(k) != v]
    for c in qc_changed:
        lines.append(f"QC check {c['id']}: {c['before'] or 'absent'} → {c['now']}.")

    return {"available": True, **base, "lens": LENS, "bookings": kpis, "pipeline": pipe,
            "actions": {"new": new, "cleared": cleared}, "qc": {"now": cur["qc"]["status"], "before": prev["qc"]["status"], "changed": qc_changed},
            "lines": lines}
