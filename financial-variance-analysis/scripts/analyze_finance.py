#!/usr/bin/env python3
"""Deterministic finance analysis: query rows (or a local workbook) -> finance_payload.json.

Usage:
  python analyze_finance.py --rows part1.csv part2.csv --out work/finance_payload.json --as-of 2026-10 \
      [--expect-accounts N] [--subsidiary "Acme US"] [--expense-sign negative|positive] [--budget-sign negative|positive] \
      [--materiality executive=250000,management=50000,management_pct=5,monitoring=15000] \
      [--window MTD --basis py|budget] [--source "FINANCE_ANALYTICS"] [--scope-note "..."] [--title "..."]
  python analyze_finance.py --workbook finance_sample.xlsx --out work/finance_payload.json      (local test mode)

The payload (contract sda.finance-analysis/1.5.0) carries, for every window (MTD, QTD, YTD, LTM) and
comparator (budget, prior year) at the as-of period: statement lines, drivers (L4 groups), accounts, the
EBITDA bridge with account contributions, the planning / operational / coverage layers (MTD vs budget),
patterns, ranked insights, the executive readout, the net-income-first story, KPI diagnoses, the deterministic explanation of every
account, driver and statement line, ranked follow-up actions and the pinned headline; plus per-account
structural signals, monthly series for the drawer trend charts, the mechanical full-year outlook and QC.
Every figure in generated prose is registered with its payload path. The renderer computes nothing economic.
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance import CONTRACT_VERSION, RENDERER_VERSION                               # noqa: E402
from finance.common import BuildError, sha256_of, is_num, r2                         # noqa: E402
from finance.load import Frame, read_rows, read_rows_file, rows_from_workbook, governed_from_workbook, load_scope, NO_SUB   # noqa: E402
from finance.model import Model, WINDOWS, BASES                                      # noqa: E402
from finance.signals import signals_for                                              # noqa: E402
from finance import synthesis, explain, outlook as outlook_mod, summary as summary_mod, oneoffs, assumptions, memos as memos_mod   # noqa: E402
from finance.validate import validate_payload                                        # noqa: E402


def parse_materiality(s):
    if not s:
        return None
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        k = k.strip()
        key = {"executive": "executive_abs", "management": "management_abs", "monitoring": "monitoring_abs", "management_pct": "management_pct"}.get(k, k)
        out[key] = float(v)
    return out


def qc_checks(frame, model, args, mode):
    P = frame.periods
    as_of = P[model.as_of]
    today = dt.date.today()
    lag = (today - dt.date.fromisoformat(as_of["end"])).days
    hist = model.as_of + 1
    checks = []
    def c(id_, result, detail, **extra):
        checks.append({"id": id_, "result": result, "detail": detail, **extra})
    by = model.sign["by_measure"]
    if frame.multiplier_applied:
        c("sign_convention", "PASS", "Signs come from the view's own per-account P&L multiplier (ACCOUNT.P_AND_L_MULTIPLIER): revenue and add-backs "
          "positive, costs negative, so the accounts sum to net income.")
    else:
        c("sign_convention", "PASS" if model.sign["source"] == "declared" else "WARN",
          f"Costs are recorded as {model.sign['expenses_stored']} numbers and revenue as {model.sign['revenue_stored']} ({'as declared' if model.sign['source'] == 'declared' else 'worked out from the data'}). Check one known cost account before relying on the favourable / unfavourable labels.")
    if model.sign["mismatch"]:
        c("sign_mismatch", "WARN", "; ".join(f"{'Budget' if b == 'budget' else 'Prior year'} stores expenses {by[b]['expenses_stored']} and revenue {by[b]['revenue_stored']} ({by[b]['source']}); actuals store expenses {by['actual']['expenses_stored']} and revenue {by['actual']['revenue_stored']}" for b in model.sign["mismatch"])
          + ". Each measure was normalised to profit orientation on its own sign, so variances compare like with like; ask the data team to align the load.")
    bc = model.budget_chk
    c("budget_reliability", "PASS" if bc["reliable"] else "WARN",
      "Budget is within range of actuals for revenue, cost of sales and operating expenses." if bc["reliable"] else
      "Budget not meaningful for " + ", ".join(f"{v['label']} (budget {v['ratio']:.2f}x actuals)" if v["ratio"] is not None else f"{v['label']} (opposite sign)" for v in bc["sections"].values() if v["ok"] is False)
      + f" ({bc['rule']}). Budget variances on these lines reflect the budget load, not performance.")
    c("unmapped_accounts", "PASS" if not model.unmapped else "WARN",
      "All accounts map to Revenue, Cost of sales, OpEx, Synergies or Non-operating." if not model.unmapped else
      f"{len(model.unmapped)} account(s) are not mapped and are left out of every total: " + ", ".join(a["name"] for a in model.unmapped))
    fc = getattr(frame, "fiscal", None)
    if fc:
        mon = dt.date(2000, fc["start_month"], 1).strftime("%B")
        c("fiscal_calendar", "WARN" if fc["mismatch"] else "PASS",
          (f"Quarter to date and year to date follow the fiscal year starting 1 {mon} (named by the year it ends in), from {fc['source']}."
           if not fc["mismatch"] else
           f"The view's fiscal year and quarter disagree with fiscal_year_start_month {fc['start_month']} in config/scope.json: "
           + "; ".join(fc["mismatch"][:3]) + ". The page follows the view's columns; correct the setting."))
    if frame.adjustments:
        c("adjustments_included", "PASS", "Group adjustment accounts (account type '" + str(load_scope().get("adjustment_account_type")) + "', below EBITDA, part of the "
          "finance system's net income) are included: " + "; ".join(f"{n}, {m[0]} to {m[-1]} ({len(m)} month(s))" for n, m in frame.adjustments.items() if m)
          + ". Rows with no subsidiary show as '" + NO_SUB + "'.")
    if frame.excluded:
        c("scope_exclusions", "PASS", "Excluded: " + "; ".join(f"{e}" for e, n in frame.excluded.items())
          + ". Scope reads " + json.dumps(model.scope_label) + ".")
    gv = getattr(model, "governed", None)
    c("governed_reconciliation", "PASS" if gv else ("NOT_RUN" if mode == "local" else "FAIL"),
      f"Revenue, Adjusted EBITDA and net income tie to the finance system's own monthly totals within $1, for every month and subsidiary ({gv['checked']} checks)."
      if gv else "No governed roll-ups supplied (local test data).")
    skipped = getattr(frame, "skipped_open", [])
    n5 = [n for n in model.nodes.values() if n["level"] == "L5"]
    n6 = [n for n in model.nodes.values() if n["level"] == "L6"]
    if frame.has_l5 or frame.has_l6:
        c("l5_footing", "PASS", f"{len(n5)} L5 sub-group(s) under {len({n['driver'] for n in n5})} driver(s); each foots to its driver (L4) to the cent in every view, or the page is not produced (invariant I13). A level that repeats its parent is collapsed.")
        c("l6_footing", "PASS" if n6 else "NOT_RUN", f"{len(n6)} L6 sub-group(s) under {len({n['parent'] for n in n6})} L5 group(s); each foots to its L5 group to the cent in every view (invariant I13)." if n6 else "Every L6 repeats its L5 in this extract, so there is no L6 level to foot.")
    else:
        c("l5_footing", "NOT_RUN", "The extract carries no COA_MAPPING_L5 / L6 columns: drills stop at L4. Re-run the data query in references/dashboards.md §2.")
    # Quarter, year to date and twelve months are the sum of TOTAL_MTD over the months in each window. The view's own
    # QTD / YTD / LTM columns are never read: each is tagged to a chart-of-accounts key at one month, so a key present in an
    # earlier month but missing from the as-of month drops out and the rolled-up column is incomplete.
    c("window_tie_out", "PASS" if gv else "NOT_RUN",
      ("Quarter, year-to-date and twelve-month figures are the sum of TOTAL_MTD over the months in each window, and every month ties to the "
       "finance system's own monthly totals (above), so every window does too. The view's own QTD, YTD and LTM columns are not used: each is "
       "tagged to a chart-of-accounts key at one month, so keys present in earlier months but missing from the month reported drop out and "
       "those columns come out incomplete.") if gv else
      "Quarter, year-to-date and twelve-month figures are the sum of TOTAL_MTD over the months in each window; the months were not tied to "
      "the finance system's own monthly totals (no governed roll-ups supplied).")
    if skipped:
        c("open_months", "WARN", f"{', '.join(skipped)} {'are' if len(skipped) > 1 else 'is'} still open (only a few early postings), so the page reports {as_of['label']}, the latest closed month.")
    c("history", "PASS" if hist >= 24 else "WARN", f"{hist} month(s) of history to {as_of['label']}; prior-year and LTM comparisons need 24 for full coverage.")
    ltm = [k for k in range(max(0, model.as_of - 11), model.as_of + 1)]
    py_cov = sum(1 for k in ltm if is_num(model.line_series['rev']['py'][k]))
    c("prior_year_coverage", "PASS" if py_cov == len(ltm) else "WARN", f"Prior-year revenue present in {py_cov} of the last {len(ltm)} months.")
    n_b = sum(1 for a in model.mapped if is_num(model.series[model.aidx[a['id']]]['budget'][model.as_of]) and model.series[model.aidx[a['id']]]['budget'][model.as_of] != 0)
    c("budget_coverage", "PASS" if n_b == len(model.mapped) else "WARN", f"{n_b} of {len(model.mapped)} accounts have a budget in {as_of['label']}; the rest are shown as having no budget line, never as a zero budget.")
    fut = [p for p in P if p["future"]]
    c("fiscal_year_budget", "PASS" if fut else "WARN", f"{len(fut)} future month(s) of budget in the extract." if fut else "No future months in the extract: the full-year budget comparison is unavailable (extend the query to the fiscal year end).")
    c("data_freshness", "PASS" if lag <= 30 else "WARN", f"As-of period ends {as_of['end']}; built {today.isoformat()} ({lag} days later{'; over 30 days, so check for later postings before relying on it' if lag > 30 else ''}).")
    c("completeness", "PASS" if args.expect_accounts else "NOT_RUN", f"The number of accounts matched the count taken from the finance system ({args.expect_accounts}), so nothing was cut off." if args.expect_accounts else "No account count was supplied, so a cut-off extract could not be detected by the build.")
    mb = getattr(model, "memo_block", None) or {}
    c("gl_memos", "PASS" if mb.get("available") else "NOT_RUN",
      (f"GL line memos for {len(mb['months'])} month(s) ({mb['months'][0]} to {mb['months'][-1]}) reconcile to the actuals for every account and month "
       f"({mb['reconciliation']['account_months_checked']} checks, within ${mb['reconciliation']['tolerance']:g}); the AI review reads them as evidence of what the postings were, "
       "never as a verified cause, and the page shows no memo text or names.") if mb.get("available") else
      "No GL memos supplied: the review reads the statement marts only (run the memo query in references/dashboards.md §2 and pass --memos).")
    c("data_mode", "PASS" if mode == "governed" else "WARN", "Read directly from the finance system's reporting layer." if mode == "governed" else "Test data from a workbook: made-up figures, never to be presented as real.")
    c("scope", "PASS", f"{len(frame.subs)} subsidiar{'y' if len(frame.subs) == 1 else 'ies'} in scope" + (f" (filtered to {frame.scope_subsidiary})" if frame.scope_subsidiary else " (consolidated as stored; eliminations not documented)") + ".")
    caveats = [x["detail"] for x in checks if x["result"] in ("WARN", "FAIL")]
    return {"status": "QUALIFIED" if caveats else "CLEAN", "checks": checks, "caveats": caveats,
            "unmapped_accounts": [{"id": a["id"], "name": a["name"], "l2": a["l2"], "l3": a["l3"]} for a in model.unmapped]}


def build(args):
    scope_cfg = load_scope()
    excluded = list(args.exclude_subsidiary or []) + ([] if args.no_default_exclusions else list(scope_cfg["exclude_subsidiaries"]))
    excluded = list(dict.fromkeys(excluded))
    if args.workbook:
        rows, mode = rows_from_workbook(args.workbook), "local"
        governed = governed_from_workbook(args.workbook)
        sources = [args.source or (os.path.basename(args.workbook) + " (INCOME_STATEMENT, ACCOUNT, PERIOD, SUBSIDIARY)")]
    else:
        rows, mode = read_rows(args.rows), "governed"
        if not args.governed:
            raise BuildError("--governed is required with --rows: the month x subsidiary REVENUE_MTD, ADJUSTED_EBITDA_MTD and NET_INCOME_MTD "
                             "from the view (references/dashboards.md §2, governed query). The build reconciles the extract to them and refuses on a gap.")
        governed = []
        for g in args.governed:
            governed.extend(read_rows_file(g))
        sources = [args.source or "FINANCE_ANALYTICS semantic view"]
    frame = Frame(rows, as_of=args.as_of, subsidiary=args.subsidiary, expect_accounts=args.expect_accounts,
                  exclude_subsidiaries=excluded, scope=scope_cfg)
    model = Model(frame, expense_sign=args.expense_sign, materiality=parse_materiality(args.materiality), budget_sign=args.budget_sign)
    model.budget_chk = model.budget_check()
    model.build_date = dt.date.today()
    model.governed = None
    if governed is not None:
        checked, bad = model.governed_check(governed, tol=scope_cfg.get("governed_tolerance", 1.0), excluded=excluded)
        if bad:
            raise BuildError(f"The extract does not reconcile to the governed roll-ups in {len(bad)} place(s) (tolerance ${scope_cfg.get('governed_tolerance', 1.0):g}): "
                             + "; ".join(f"{b['subsidiary']} {b['month']} {b['metric']} governed {b['governed']} vs extract {b['extract']}" for b in bad[:8])
                             + ". Fix the extract or the scope (an excluded subsidiary, a missing chunk, a dropped key); never adjust the tolerance.")
        model.governed = {"checked": checked, "months": len({g['PERIOD_START_DATE'] for g in governed})}
    # the page opens on prior year unless the user asks for budget
    args.basis = args.basis or "py"
    P = frame.periods
    as_of = P[model.as_of]
    signals = {a["id"]: signals_for(model.series[model.aidx[a["id"]]], model.as_of, model.materiality["monitoring_abs"], P) for a in model.mapped}
    # outlook needs the MTD/budget lens for the persistence view; lenses need the outlook for the full-year insight: build in two passes
    lenses = {}
    for w in WINDOWS:
        for b in BASES:
            L = model.lens(w, b)
            if L["available"]:
                L["layers"] = model.layers(L, signals)
                L["patterns"] = synthesis.patterns(model, L, signals)
            lenses[L["id"]] = L
    # one-off months over the last twelve months at the management threshold: the register per window, and taken out of the run-rate
    one_offs = oneoffs.find(model, (max(0, model.as_of - 11), model.as_of), model.materiality["management_abs"])
    for L in lenses.values():
        if L["available"]:
            L["one_offs"] = oneoffs.register(L, one_offs)
    outlook = outlook_mod.compute(model, signals, lenses.get("MTD_budget"), one_offs)
    for L in lenses.values():
        if not L["available"]:
            continue
        L["_remaining_months"] = outlook.get("remaining_months")
        L["insights"] = synthesis.insights(model, L, signals, outlook)
        L["actions"] = explain.actions(model, L, signals, as_of)
        del L["_remaining_months"]
        by_driver = {a["subject_ref"]: a for a in L["actions"]}
        ins_by = {i["subject_ref"]: i for i in L["insights"] if i["kind"] == "driver"}
        L["explanations"] = {
            "accounts": [explain.account_explanation(model, L, a, signals[a["id"]], by_driver, as_of) for a in L["accounts"]],
            "drivers": [explain.driver_explanation(model, L, d, ins_by.get(d["id"]), by_driver.get(d["id"]), lenses) for d in L["drivers"]],
            "lines": explain.line_explanations(model, L, lenses),
            "summary": explain.summary(model, L, L["actions"], as_of)}
        L["readout"] = synthesis.readout(model, L, outlook)
        L["story"] = synthesis.story(model, L, lenses)
        L["kpi_diagnoses"] = synthesis.kpi_diagnoses(model, L, outlook)
        L["headline"] = explain.headline(model, L, outlook)
    for L in lenses.values():                          # needs every lens's lines (the twin comparison) and its actions
        if L["available"]:
            L["summary"] = summary_mod.summary(model, L, lenses, outlook, signals)
    # GL memos: the human-written description of the ledger lines, reconciled to the actuals, as evidence for the review
    memo_block = {"available": False, "reason": "no memo extract supplied (--memos); the review reads the statement marts only"}
    if args.memos:
        memo_block = memos_mod.build(memos_mod.read_memos(args.memos), frame, model, lenses, one_offs, tol=scope_cfg.get("governed_tolerance", 1.0))
    model.memo_block = memo_block
    primary = f"{args.window}_{args.basis}"
    if not lenses[primary]["available"]:
        raise BuildError(f"The primary lens {primary} is not available: {lenses[primary].get('reason')}")
    scope_note = args.scope_note or (f"Subsidiary: {frame.scope_subsidiary} only" if frame.scope_subsidiary else None)
    excl_named = [e for e in frame.excluded]
    model.scope_label = None
    scope_label = (f"{frame.scope_subsidiary} only" if frame.scope_subsidiary else
                   f"All subsidiaries ({len(frame.subs)})" + (f" excluding {', '.join(excl_named[:-1]) + ' and ' + excl_named[-1] if len(excl_named) > 1 else excl_named[0]}" if excl_named else ""))
    model.scope_label = scope_label
    qc = qc_checks(frame, model, args, mode)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "meta": {"title": args.title or "Finance diagnostic", "view": "FINANCE_ANALYTICS", "data_mode": mode, "currency": "USD (converted, as stored in the marts)",
                 "as_of": as_of, "as_of_label": as_of["label"], "primary_lens": {"window": args.window, "basis": args.basis, "id": primary},
                 "scope": {"subsidiaries": frame.subs, "filtered_to": frame.scope_subsidiary, "note": scope_note, "accounts": len(model.mapped), "unmapped": len(model.unmapped),
                           "excluded_subsidiaries": excl_named, "excluded_reasons": {e: scope_cfg.get("exclude_subsidiaries_reason", {}).get(e) for e in excl_named},
                           "label": scope_label, "adjustments": frame.adjustments,
                           "account_grain": "account number and name within subsidiary; class and department are drill detail; compared across subsidiaries where the budget is held on another entity",
                           "hierarchy": ["L3", "L4"] + (["L5"] if frame.has_l5 else []) + (["L6"] if frame.has_l6 else []) + ["account"] + (["class"] if frame.has_class else []),
                           "drill_dimensions": [d for d, f in (("subsidiary", True), ("class", frame.has_class), ("department", frame.has_department)) if f]},
                 "periods": P, "months_of_history": model.as_of + 1, "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                 "build_date": model.build_date.isoformat(), "data_age_days": (model.build_date - dt.date.fromisoformat(as_of["end"])).days, "data_age_warn_days": 30,
                 "target_date_rule": "build date + 10 business days",
                 "sign_convention": model.sign, "budget_check": model.budget_chk, "materiality": model.materiality, "sources": sources, "renderer_version": RENDERER_VERSION,
                 "window_labels": {"MTD": "Month", "QTD": "Quarter to date", "YTD": "Year to date", "LTM": "Last twelve months"},
                 "basis_labels": {"budget": "Budget", "py": "Prior year"}},
        "accounts": [{**a, "driver_ref": model.driver_of.get(a["id"]), "node_path": model.node_path.get(a["id"], []), "display_sign": model.display_sign.get(a["section"]),
                      "series": {"actual": [r2(None if v is None else v * model.display_sign[a["section"]]) for v in model.series[model.aidx[a["id"]]]["actual"]],
                                 "py": [r2(None if v is None else v * model.display_sign[a["section"]]) for v in model.series[model.aidx[a["id"]]]["py"]],
                                 "budget": [r2(None if v is None else v * model.display_sign[a["section"]]) for v in model.series[model.aidx[a["id"]]]["budget"]],
                                 "variance_vs_budget": [r2((x - y) if is_num(x) and is_num(y) else None) for x, y in zip(model.series[model.aidx[a["id"]]]["actual"], model.series[model.aidx[a["id"]]]["budget"])]}}
                     for a in model.mapped],
        "unmapped_accounts": [{"id": a["id"], "name": a["name"], "l2": a["l2"], "l3": a["l3"], "l4": a["l4"]} for a in model.unmapped],
        "drivers": model.drivers,
        "nodes": [{k: v for k, v in n.items()} for n in model.nodes.values()],
        "product_lines": {"level": "L6" if any(n["level"] == "L6" and n["section"] == "rev" for n in model.nodes.values()) else "L5",
                          "items": [{"id": n["id"], "name": n["name"], "level": n["level"], "driver": n["driver"], "parent": n["parent"],
                                     "series": {b: [r2(v) for v in model._sum_series([model.series[model.aidx[x]] for x in n["accounts"]])[b]] for b in ("actual", "py", "budget")}}
                                    for n in model.nodes.values() if n["section"] == "rev" and not any(m["parent"] == n["id"] for m in model.nodes.values())],
                          "basis": "monthly, profit-oriented (revenue positive): the deepest revenue sub-groups of the view"},
        "statement_series": model.series_block(),
        "signals": signals,
        "lenses": lenses,
        "outlook": outlook,
        "memos": memo_block,
        "qc": qc,
        "capabilities": {"price_volume_mix": {"state": "not_calculated", "reason": "The figures have no quantities or unit prices, so a change cannot be split into price, volume and mix; that needs order or subscription data."},
                         "fx": {"state": "not_assessed", "reason": "Amounts arrive already converted to US dollars, so the effect of exchange-rate moves cannot be shown separately."},
                         "dimensions": {"state": "subsidiary_class_department" if frame.has_department else "subsidiary_class" if frame.has_class else "subsidiary_only",
                                        "reason": "Each account can be split by subsidiary, class and department; location is not included."},
                         "hierarchy_below_l4": {"state": "available" if frame.has_l5 else "not_in_view", "reason": "The finance system's sub-groups below the main account groups (levels 5 and 6) are not in this extract; drills stop at L4." if not frame.has_l5 else "Levels 5 and 6 of the chart of accounts are carried under each driver (L4 > L5 > L6 > account); a level that repeats its parent is collapsed, and revenue is split by product line."},
                         "transactions": {"state": "not_carried", "reason": "Individual transactions are not on this page; ask for them in chat and they will be tied back to these figures."}},
    }
    payload["meta"]["assumptions"] = assumptions.build(model, frame, outlook, qc, one_offs, mode, as_of["label"], model.build_date.isoformat(),
                                                       payload["meta"]["data_age_days"], scope_cfg, bool(args.as_of))
    payload["analysis_hash"] = sha256_of(payload)
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--rows", nargs="+", help="CSV or JSON result file(s); several files = period chunks")
    src.add_argument("--workbook", help="local finance workbook (local test mode)")
    ap.add_argument("--out", required=True, help="payload JSON to write")
    ap.add_argument("--as-of", help="as-of month YYYY-MM (default: latest month with actuals); later months are used for budget only")
    ap.add_argument("--subsidiary", help="analyse one subsidiary only (default: all, consolidated as stored)")
    ap.add_argument("--exclude-subsidiary", action="append", help="leave a subsidiary out (repeatable); added to the defaults in config/scope.json")
    ap.add_argument("--no-default-exclusions", action="store_true", help="do not apply the exclude_subsidiaries list in config/scope.json")
    ap.add_argument("--governed", nargs="+", help="governed roll-up file(s): month x subsidiary REVENUE_MTD, ADJUSTED_EBITDA_MTD, NET_INCOME_MTD (required with --rows)")
    ap.add_argument("--memos", nargs="+", help="GL memo extract file(s), one month per file (references/dashboards.md §2, memo query); reconciled to the actuals, refused on a gap")
    ap.add_argument("--expect-accounts", type=int, help="distinct real accounts the probe counted; the build stops on a mismatch")
    ap.add_argument("--expense-sign", choices=["negative", "positive"], help="declare how expenses are stored in actuals and prior year; default: detected from the data")
    ap.add_argument("--budget-sign", choices=["negative", "positive"], help="declare how expenses are stored in the budget; default: detected from the budget itself")
    ap.add_argument("--materiality", help="executive=,management=,management_pct=,monitoring= (dollar thresholds; default scaled to LTM revenue)")
    ap.add_argument("--window", default="MTD", choices=WINDOWS, help="primary lens window (default MTD)")
    ap.add_argument("--basis", choices=BASES, help="primary lens comparator (default py: prior year)")
    ap.add_argument("--source", help="source line for the footer")
    ap.add_argument("--scope-note", help="plain-English scope note when the data is a deliberate subset")
    ap.add_argument("--title", help="dashboard title")
    args = ap.parse_args()
    try:
        payload = build(args)
        errs = validate_payload(payload)
        if errs:
            print(json.dumps({"status": "REFUSED", "gate": "invariant", "reasons": errs[:40], "note": "No payload written."}, indent=2))
            return 1
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except (BuildError, KeyError, ValueError, OSError) as e:
        print(json.dumps({"status": "REFUSED", "reason": str(e)}, indent=2))
        return 1
    L = payload["lenses"][payload["meta"]["primary_lens"]["id"]]
    print(json.dumps({"status": "OK", "out": args.out, "contract": CONTRACT_VERSION, "analysis_hash": payload["analysis_hash"][:16],
                      "as_of": payload["meta"]["as_of_label"], "mode": payload["meta"]["data_mode"], "accounts": len(payload["accounts"]),
                      "unmapped": len(payload["unmapped_accounts"]), "subsidiaries": payload["meta"]["scope"]["subsidiaries"],
                      "months_of_history": payload["meta"]["months_of_history"], "primary_lens": L["id"],
                      "material_drivers": L["concentration"]["material_drivers"], "actions": len(L["actions"]), "qc": payload["qc"]["status"],
                      "headline": L["headline"]["text"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
