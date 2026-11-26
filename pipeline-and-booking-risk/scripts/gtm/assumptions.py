"""The assumptions list: every threshold, test and rule the GTM page relies on, in words a reader can check,
with the value in use for this build. Built from the payload the engine has just assembled (same shape as the
finance skill's meta.assumptions); the page formats nothing."""
from .common import is_num, money as _money


def _m(v):
    s = _money(v)
    return f"({s[1:]})" if s.startswith("−") else s


def _p(v, dec=0):
    return "—" if not is_num(v) else f"{v * 100:.{dec}f}%"


def build(payload, inp, consts):
    meta, pl, rk = payload["meta"], payload["pipeline"], payload.get("risk") or {}
    rows = []
    g = lambda title, items: rows.append({"group": title, "rows": [{"label": a, "value": b} for a, b in items if b is not None]})
    mat = meta["materiality"]
    g("Size thresholds (what counts as a move)", [
        ("Smallest move we report", f"{_m(mat['monitoring_month'])} a month (1% of last-twelve-month bookings ÷ 12), scaled to the window"),
        ("Notable / large move", "5× / 10× the smallest move; a monthly spike reaches the summary only above 10×"),
        ("Broad-based growth", f"at least {_p(consts['BREADTH_SHARE'])} of subsidiaries and of products with prior-quarter bookings up; otherwise the breadth is stated")])
    g("Which dates are reported", [
        ("Analysis date", f"{meta['as_of']['month_end']}: the latest completed bookings month-end"),
        ("Headline pipeline", f"PIPELINE_OVERVIEW snapshot at {pl.get('as_of')}" + (" (same date as bookings)" if pl.get("as_of") == meta["as_of"]["month_end"] else " (differs from bookings: see data checks)")),
        ("Deal lists, stage age, past due", f"current state at {pl.get('deals_as_of') or pl.get('as_of')}: the view keeps no deal-level history"),
        ("Fiscal year", (meta.get("fiscal") or {}).get("rule", "") + f"; this page is in {(meta.get('fiscal') or {}).get('year')}, quarter {(meta.get('fiscal') or {}).get('quarter')}"),
        ("Windows", "Month, fiscal Quarter to date (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec; the fiscal year is the calendar year) and Last twelve months, each against the same months one quarter earlier (Oct against Jul); fiscal Year to date (from 1 January) has no prior-quarter equivalent and is not offered as a lens. Trend lines, open pipeline a year earlier and the rest-of-year scenario (to 31 December) stay on the prior year")])
    g("Tie-outs to the governed view", [
        ("Booking lines vs BOOKINGS_OVERVIEW", "every month's TOTAL_BOOKINGS_MTD, to $1 or 0.1%; fiscal quarter, year to date and the last twelve months are built from those months (the mart's QTD, YTD and LTM columns are not used)"),
        ("Lost deals vs LOST_ACV_USD", "last twelve months, to $1 or 0.2%"),
        ("Bridges", "prior quarter + every step = this period, to the cent, by measure, product and subsidiary")])
    g("Pipeline values", [
        ("Weighted pipeline", "open opportunity line ACV × Salesforce probability ÷ 100 (WEIGHTED_OPEN_PIPELINE_ACV / WEIGHTED_PIPELINE_VALUE), over open stages Stage 0 to Invest; pipeline created, won and lost ACV are unweighted"),
        ("Close quarters", "weighted pipeline grouped by the fiscal (calendar) quarter of its close date"),
        ("Targets and coverage", "none: the view holds no pipeline or bookings target, so nothing is read against a target")])
    st, hv, nc = rk.get("stuck") or {}, rk.get("high_value") or {}, rk.get("not_closing") or {}
    g("Pipeline risk", [
        ("Stuck in stage", st.get("rule")),
        ("Not closing", nc.get("rule")),
        ("High value", f"{hv.get('rule')}; cut-off {_m(hv.get('cutoff'))}" if hv else None),
        ("Recurring ACV", rk.get("recurring_rule")),
        ("Method", "stage age and close-date moves are proxies: the view has no activity or next-step data")])
    v = (payload["lenses"].get(meta["primary_lens"]["id"]) or {}).get("velocity")
    cs = (payload["lenses"].get(meta["primary_lens"]["id"]) or {}).get("conv_size")
    g("Conversion and velocity", [
        ("Days to win", v["rule"] if v else None),
        ("Large deals (velocity)", v["hv_rule"] if v else None),
        ("Win rate by value", cs["rule"] if cs else "won ÷ (won + lost) ACV"),
        ("Small samples", f"fewer than {consts['MIN_CLOSED_FOR_RATE']} closed deals: shown, not read as a finding")])
    g("Bookings detail", [
        ("Recurring bookings", "Salesforce closed-won opportunity lines, on the close date; split by BOOKING_METRIC into ARR (New) (New Customer) and ARR (Upsell) (Upgrade, Renewal, Downgrade)"),
        ("Non-recurring bookings", "NetSuite one-time services revenue from the GL, by subsidiary (Power Settlements, ENELYTIX), on the period end date; product One Time Services, no account or opportunity"),
        ("Customers and deals", "recurring bookings only (non-recurring revenue has no account); a deal is one booked opportunity"),
        ("Re-papering", "same customer, measure and absolute amount with opposite sign in the window: paired, kept out of top deals, shown net on the customer"),
        ("Organic view", "excludes subsidiaries with no prior-quarter bookings in the window; acquisition status is management input"),
        ("Average deal value", "recurring bookings ÷ distinct booked opportunities in the window"),
        ("Analysis month", next((c["detail"] for c in payload["qc"]["checks"] if c["id"] == "as_of_complete"), None))])
    g("Scenarios (credit 0)", [
        ("What the pipeline could deliver", payload["outlook"].get("rule")),
        ("Rest of year", (payload.get("rest_of_year") or {}).get("rule"))])
    g("Not in the view", [(c.get("label") or k.replace("_", " ").capitalize(), c.get("reason")) for k, c in payload["capabilities"].items() if c.get("state") != "available"])
    return rows
