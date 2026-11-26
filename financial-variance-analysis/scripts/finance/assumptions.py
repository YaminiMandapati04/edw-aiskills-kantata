"""The assumptions list: every threshold, test and rule the page relies on, in the words a reader can check,
grouped and already formatted. The page shows it as the "Assumptions" dropdown under "How to read this page"
and computes nothing from it; the values come from the same objects the engine used."""
from .common import is_num, money, pct
from .signals import TRAILING, MIN_TRAILING, PERSIST_MIN, REL_FLOOR
from .oneoffs import NAMING_SHARE

WLABEL = {"MTD": "Month", "QTD": "Quarter to date", "YTD": "Year to date", "LTM": "Last twelve months"}


def _m(v):
    return money(v) if is_num(v) else "—"


def build(model, frame, outlook, qc, one_offs, mode, as_of_label, build_date, data_age_days, scope_cfg, as_of_given):
    M = model.materiality
    by = M["by_window"]
    rows = []
    g = lambda title, items, note=None: rows.append({"group": title, "rows": [{"label": a, "value": b} for a, b in items], "note": note})

    g("Size thresholds (what counts as a move)",
      [(f"{WLABEL[w]} ({by[w]['months']} month{'s' if by[w]['months'] != 1 else ''})",
        f"large {_m(by[w]['executive_abs'])} · notable {_m(by[w]['management_abs'])} · smallest reported {_m(by[w]['monitoring_abs'])}") for w in ("MTD", "QTD", "YTD", "LTM")]
      + [("Rule", f"{M['pct_of_window_revenue']['executive']}% / {M['pct_of_window_revenue']['management']}% / {M['pct_of_window_revenue']['monitoring']}% of an average month's revenue "
                  f"({_m(M['average_month_revenue'])}, from {M['basis']} of {_m(M['annual_revenue_basis'])}) times the months in the window, rounded to the nearest $100"
                  + (" (analyst-declared amounts)" if M["source"] == "analyst-declared" else "")),
         ("Notable also needs", f"at least {M['management_pct']:g}% of the budget or prior-year figure; when that figure is zero or of the opposite sign (a credit became an expense), the dollar test alone applies and no percentage is shown"),
         ("Smaller moves", "read as in line; they are still in every drill table")])
    g("Unusual months and one-offs",
      [("Unusual month", f"outside the account's trailing {TRAILING}-month range by at least the larger of {_m(M['monitoring_abs'])}, twice the trailing residual spread and {int(REL_FLOOR * 100)}% of the level, measured against the trend reference (at least {MIN_TRAILING} trailing months needed)"),
       ("Single posting", f"an amount of {_m(M['management_abs'])} or more on an account with no activity in the {TRAILING} months before and none after"),
       ("Register", f"one-offs of {_m(M['management_abs'])} or more over the last twelve months: {len(one_offs)} found, {sum(1 for x in one_offs if x.get('offset_with'))} of them in offsetting pairs (such as intercompany revenue against intercompany cost), which are listed but never named or taken out"),
       ("Named in the lead", f"an item at or above {int(NAMING_SHARE * 100)}% of the window's net-income movement and at least the window's large threshold; the lead then gives net income without it"),
       ("Run-rate", "the flagged months are replaced by the account's trend reference before any run-rate rule is applied; year to date stays as reported")])
    g("Where a movement sits",
      [("Sub-groups below L4", "the finance system's levels 5 and 6 sit under each driver (L4 › L5 › L6 › account); a level that repeats its parent is collapsed, a member with no activity in the window is left out, and each level adds up to the one above to the cent or the page is not produced"),
       ("Department named", "only when at least two departments each hold 5% or more of the gross movement; otherwise the department is not mentioned"),
       ("Other accounts", "the accounts outside the top rows of a drill, listed in full when expanded; every drill table foots to its total to the cent")])
    gv = (qc.get("checks") and next((c for c in qc["checks"] if c["id"] == "window_tie_out"), None)) or {}
    g("Tie-outs to the finance system",
      [("Each month", f"revenue, Adjusted EBITDA and net income by month and subsidiary within {_m(scope_cfg.get('governed_tolerance', 1.0))} of the view's own roll-ups; the build stops on any difference"
                      + ("" if mode == "governed" else " (not run on local test data)")),
       ("Quarter, year to date, twelve months", f"the sum of TOTAL_MTD over the months in each window, so a window ties whenever its months tie; result: {gv.get('result', 'NOT_RUN')}. "
                                                "The view's own QTD, YTD and LTM columns are not used: each is tagged to a chart-of-accounts key at one month, so keys missing from the month reported drop out and the rolled-up column is incomplete"),
       ("Statement", "gross profit = revenue + cost of sales; Adjusted EBITDA = gross profit + operating expenses; net income = Adjusted EBITDA + below-the-line lines; every bridge and drill reconciles to the cent or the page is not produced")])
    skipped = getattr(frame, "skipped_open", []) or []
    g("Which month is reported",
      [("Closed month", f"{as_of_label}, given by the analyst" if as_of_given else f"{as_of_label}: the latest month with at least half the posting accounts of the busiest earlier month"
        + (f"; {', '.join(skipped)} skipped as still open" if skipped else "")),
       ("Open months", "a month with only a few early postings is skipped; a later restatement of a closed month is not detectable from counts, so the close flag from the finance team prevails where known")])
    bc = model.budget_chk or {}
    g("Budget usability",
      [("Usable budget", "a section's budget is usable when it sits between 0.5x and 2x actuals over the last six closed months carrying both; outside that it reflects the load, not performance, and the line is read against prior year"),
       ("Result", "usable" if bc.get("reliable") else f"not usable for {', '.join(bc.get('failed') or [])}" if bc else "not assessed")])
    O = outlook or {}
    rules = {"trailing_3_mean": "trailing three-month average (the Summary headline)", "trailing_6_mean": "trailing six-month average", "period_flat": "latest month held flat", "trend_extrapolation": "twelve-month trend extended"}
    g("Full-year outlook",
      [("Rules", "; ".join(rules[r] for r in O.get("rules", [])) or "—"),
       ("What it is", "year to date as reported plus the remaining months at the rule: a projection rule, not a forecast; no seasonality, pipeline or management view"),
       ("One-offs", f"{len(O.get('one_offs_excluded', []))} flagged month(s) taken out of the run-rate (listed in the run-rate drawer)"),
       ("Full-year budget", "in the extract, so each rule is set against it" if O.get("fy_budget_available") else "not in the extract: the remaining months cannot be set against budget"),
       ("If current gaps continue", "each driver's remaining months at the rule against its budget for those months; the operating drivers add up to the bridge's remaining-months step")])
    adj = {n: d["months"] for n, d in (getattr(frame, "adjustments", None) or {}).items() if d.get("months")}
    g("Scope",
      [("Adjustments", ("; ".join(f"{n}: {m[0]['period']} to {m[-1]['period']} ({len(m)} months)" for n, m in adj.items())
                        + ". Pro forma actuals and adjustments, and the capitalisation of software and commissions (charged inside Adjusted EBITDA, reversed below it), "
                        "are included as the finance system reports them") if adj else "none in the extract"),
       ("Subsidiaries", f"{len(frame.subs)} in scope" + (f"; excluded: {', '.join(frame.excluded)}" if frame.excluded else "") + (f"; filtered to {frame.scope_subsidiary}" if frame.scope_subsidiary else "; consolidated as stored, eliminations not documented")),
       ("Fiscal year", (lambda fc: (f"starts 1 {['January','February','March','April','May','June','July','August','September','October','November','December'][fc['start_month'] - 1]}, "
                                     f"named by the year it ends in; quarter and year to date follow it ({fc['source']})") if fc else "as the extract's YEAR / QUARTER")(getattr(frame, "fiscal", None))),
       ("Currency", "US dollars as converted in the marts; exchange-rate effects are not separated")])
    g("Signals on an account's history",
      [("Reference", f"the trailing {TRAILING}-month trend extended one month, or the mean when fewer than four months carry a value"),
       ("Persistent gap", f"off budget on the same side in at least {PERSIST_MIN} of the last six months, with the cumulative gap at least the smallest reported move or 1.5% of the cumulative budget"),
       ("New level", "a step entered last month and held this month against the six months before"),
       ("Timing", "this month's gap to budget undoes at least half of last month's, the other way"),
       ("Seasonal", "the same month last year moved the same way against its own reference")])
    g("Dates and review",
      [("Built", f"{build_date}, {data_age_days} days after the period end (noted on the page when over 30)"),
       ("Target dates", "build date + 10 business days; suggestions for discussion, not assigned commitments"),
       ("AI review", "the Month and Year-to-date views need an admitted AI review before the page is published; every figure in it is checked against this data and causal wording is refused"),
       ("Data mode", "read from the finance system's reporting layer" if mode == "governed" else "local test data: made-up figures, never to be presented as real")])
    return rows
