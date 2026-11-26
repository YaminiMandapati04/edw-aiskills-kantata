#!/usr/bin/env python3
"""Generate a SYNTHETIC sample workbook that mirrors the structure of the Finance semantic view,
for testing the skill without a warehouse connection (see references/local-mode.md).

    python make_sample_data.py [outdir]        # default: ../assets/sample-data

Writes finance_sample.xlsx. Deterministic (fixed seed).
Every figure is invented. Never present these numbers as real.

The data is internally consistent on purpose, so analysis can be checked:
  * Finance: transaction lines sum exactly to each INCOME_STATEMENT MTD figure; QTD, YTD,
    LTM and prior-year columns are computed from the monthly series; roll-up rows (-8, -9, -3)
    equal the sum of the real accounts; ending cash = beginning cash + net cash flow.
"""
import datetime as dt
import os
import random
import sys

from openpyxl import Workbook

SEED = 20261103
LATEST = dt.date(2026, 10, 31)                       # latest closed month-end in the samples
MONTHS = [dt.date(2024 + (i // 12), i % 12 + 1, 1) for i in range(34)]   # 2024-01 .. 2026-10
FY_START = 2                                                               # Kantata's fiscal year runs February to January


def month_end(d):
    nxt = dt.date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def write(path, sheets, readme):
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for i, line in enumerate(readme, start=1):
        ws.cell(i, 1, line)
    for name, header, rows in sheets:
        s = wb.create_sheet(name)
        s.append(header)
        for r in rows:
            s.append(list(r))
    wb.save(path)
    print("wrote", path, {n: len(r) for n, _, r in sheets})


# ------------------------------------------------------------------- finance

def finance(rng):
    # (key, number, name, stmt, L1, L2, L3, L4, base monthly amount, growth/month, sign)
    A = [
        ("4000", "4000", "Subscription Revenue", "P&L", "Net Income", "Adjusted EBITDA", "Revenue", "Recurring Revenue", 900_000, 0.016, 1),
        ("4100", "4100", "Services Revenue", "P&L", "Net Income", "Adjusted EBITDA", "Revenue", "Non-Recurring Revenue", 180_000, 0.006, 1),
        ("5000", "5000", "Hosting Costs", "P&L", "Net Income", "Adjusted EBITDA", "Cost of Sales", "Recurring COGS", 140_000, 0.014, -1),
        ("5100", "5100", "Customer Support Salaries", "P&L", "Net Income", "Adjusted EBITDA", "Cost of Sales", "Recurring COGS", 120_000, 0.010, -1),
        ("5200", "5200", "Services Delivery Costs", "P&L", "Net Income", "Adjusted EBITDA", "Cost of Sales", "Non-Recurring COGS", 110_000, 0.006, -1),
        ("6000", "6000", "S&M Salaries", "P&L", "Net Income", "Adjusted EBITDA", "OpEx", "", 210_000, 0.012, -1),
        ("6100", "6100", "R&D Salaries", "P&L", "Net Income", "Adjusted EBITDA", "OpEx", "", 260_000, 0.010, -1),
        ("6200", "6200", "G&A Salaries", "P&L", "Net Income", "Adjusted EBITDA", "OpEx", "", 150_000, 0.006, -1),
        ("6300", "6300", "Marketing Programs", "P&L", "Net Income", "Adjusted EBITDA", "OpEx", "", 70_000, 0.012, -1),
        ("6400", "6400", "Software and Tools", "P&L", "Net Income", "Adjusted EBITDA", "OpEx", "", 45_000, 0.010, -1),
        ("7000", "7000", "Interest Expense", "P&L", "Net Income", "Total Non-Operating Income (Expense)", "Interest", "", 30_000, 0.0, -1),
        ("7100", "7100", "Income Taxes", "P&L", "Net Income", "Total Non-Operating Income (Expense)", "Taxes", "", 25_000, 0.004, -1),
    ]
    holder = [("-8", "Revenue"), ("-9", "Adjusted EBITDA"), ("-3", "Net Income")]
    CF = [  # key, name, L1, L2, L3
        ("9001", "Net Income", "Cash from Operations", "Income from Operations", "Net Income"),
        ("9002", "Depreciation and Amortization", "Cash from Operations", "Income from Operations", "Total Non-Cash Items"),
        ("9003", "Change in Accounts Receivable", "Cash from Operations", "Change in Working Capital", "Change in Working Capital"),
        ("9004", "Change in Accounts Payable", "Cash from Operations", "Change in Working Capital", "Change in Working Capital"),
        ("9005", "Capital Expenditures", "Cash from Investing", "Capital Expenditures", "Capital Expenditures"),
        ("9006", "Change in Debt", "Cash from Financing", "Change in Debt", "Change in Debt"),
    ]
    BS = [  # key, name, L1, L2, L3, debt
        ("1000", "Cash", "Assets", "Current Assets", "Cash & Cash Equivalents", 0),
        ("1100", "Accounts Receivable", "Assets", "Current Assets", "Accounts Receivable", 0),
        ("2000", "Accounts Payable", "Liabilities", "Current Liabilities", "Accounts Payable", 0),
        ("2100", "Deferred Revenue", "Liabilities", "Current Liabilities", "Deferred Revenue", 0),
        ("2500", "Revolving Credit Facility", "Liabilities", "Long-Term Liabilities", "Debt", 1),
    ]
    # levels below L4, as the view carries them: L6 repeats L5 where there is no finer split (Web Hosting, Operational
    # Services), Non-Recurring COGS repeats L4 at L5 (collapsed), 4200 Legacy Product is a product line with no activity in 2026
    L56 = {"4000": ("SaaS - Subscription", "Platform - recurring"), "4000-A": ("SaaS - Subscription", "Platform - recurring"),
           "4000-B": ("SaaS - Subscription", "Platform - recurring"),
           "4100": ("One-time Services", "Platform"), "4200": ("One-time Services", "Legacy Product"),
           "5000": ("Web Hosting", "Web Hosting"), "5100": ("Operational Services", "Operational Services"), "5200": ("Non-Recurring COGS", "Non-Recurring COGS")}
    acct_rows = []
    for k, n, name, stmt, l1, l2, l3, l4, *_ in A:
        acct_rows.append([k, n, name, stmt, l1, l2, l3, l4, *L56.get(k, (None, None)), None, None, None, 1])
    for k, name in holder:
        acct_rows.append([k, None, name, "P&L", "Net Income", None, None, None, None, None, None, None, None, 1])
    for k, name, c1, c2, c3 in CF:
        acct_rows.append([k, k, name, "CF", None, None, None, None, None, None, c1, c2, c3, 1])
    for k, name, c1, c2, c3 in [("-10", "Beginning Cash", "Beginning Cash", None, None),
                                ("-11", "Ending Cash", "Ending Cash", None, None),
                                ("-12", "Net Cash Flow", "Net Cash Flow", None, None)]:
        acct_rows.append([k, None, name, "CF", None, None, None, None, None, None, c1, c2, c3, 1])
    for k, name, l1, l2, l3, debt in BS:
        acct_rows.append([k, k, name, "BS", l1, l2, l3, None, None, None, None, None, None, 1])
    acct_rows.append(["-1000", None, "Total Debt", "BS", "Total Debt", None, None, None, None, None, None, None, None, 1])
    acct_hdr = ["CHART_OF_ACCOUNT_KEY", "ACCOUNT_NUMBER", "ACCOUNT_NAME", "FINANCIAL_STATEMENT",
                "COA_MAPPING_L1", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "COA_MAPPING_L5", "COA_MAPPING_L6",
                "CASH_FLOW_L1", "CASH_FLOW_L2", "CASH_FLOW_L3", "P_AND_L_MULTIPLIER"]

    period_rows = []
    for i, m in enumerate(MONTHS):
        fy, fq = (m.year + (m.month >= FY_START), (m.month - FY_START) % 12 // 3 + 1)   # fiscal year from February, named by its end
        period_rows.append([i + 1, m.strftime("%b %Y"), m, month_end(m), fy, f"Q{fq}", m.month])
    subs = [(1, "Acme US"), (2, "Acme UK")]
    share = {1: 0.62, 2: 0.38}
    season = [0.96, 0.97, 1.0, 1.0, 1.01, 1.03, 0.99, 0.98, 1.02, 1.03, 1.02, 1.05]

    # monthly actuals per account x subsidiary (negative for costs)
    act, bud, txn = {}, {}, []
    tid = 100000
    cust = ["Globex Industries", "Initech", "Umbrella Group", "Wayne Industries", "Stark Systems", "Tyrell Corp"]
    vend = ["AWS", "Salesforce", "WeWork", "Payroll Provider", "Google Ads", "Atlassian"]
    for (k, n, name, stmt, l1, l2, l3, l4, base, g, sign) in A:
        for sid, _ in subs:
            for i, m in enumerate(MONTHS):
                v = base * share[sid] * (1 + g) ** i * season[m.month - 1] * rng.uniform(0.97, 1.03)
                bud[(k, sid, i)] = round(sign * v * rng.uniform(0.97, 1.03), 2)     # budget set before any overspend
                if k == "6300" and m == dt.date(2026, 10, 1):
                    v *= 1.35                                   # planted one-off: marketing overspend
                if k == "5000" and m == dt.date(2026, 10, 1):
                    v *= 1.12
                act[(k, sid, i)] = round(sign * v, 2)
    # transactions that sum exactly to each monthly actual
    for (k, n, name, stmt, l1, l2, l3, l4, base, g, sign) in A:
        for sid, _ in subs:
            for i, m in enumerate(MONTHS):
                total = act[(k, sid, i)]
                nl = rng.randint(2, 4)
                cuts = sorted(rng.uniform(0.15, 0.85) for _ in range(nl - 1))
                parts = [round(total * (b - a), 2) for a, b in zip([0] + cuts, cuts + [1])]
                parts[-1] = round(total - sum(parts[:-1]), 2)
                for ln, amt in enumerate(parts, start=1):
                    tid += 1
                    day = rng.randint(1, month_end(m).day)
                    ttype = "Invoice" if l3 == "Revenue" else ("Bill" if l3 in ("Cost of Sales", "OpEx") else "Journal")
                    party = rng.choice(cust) if l3 == "Revenue" else rng.choice(vend)
                    txn.append([f"TXN-{tid}", f"{tid}-{ln}", k, sid, i + 1, dt.date(m.year, m.month, day), ttype, amt, party, "USD"])

    def window(series, i, kind):
        """series: monthly list (None = no row that month). Returns window value at month index i or None."""
        tot = lambda xs: None if all(x is None for x in xs) else sum(x for x in xs if x is not None)
        if kind == "MTD":
            return series[i]
        if kind == "QTD":
            q0 = i - (MONTHS[i].month - 1) % 3
            return tot(series[q0:i + 1])
        if kind == "YTD":
            y0 = i - (MONTHS[i].month - 1)
            return tot(series[y0:i + 1])
        if kind == "LTM":
            return tot(series[i - 11:i + 1]) if i >= 11 else None
        raise ValueError(kind)

    def rowvals(a_series, b_series, i):
        py = lambda kind: (window(a_series, i - 12, kind) if i >= 12 else None)
        r = lambda x: None if x is None else round(x, 2)
        return [r(window(a_series, i, "MTD")), r(window(a_series, i, "QTD")), r(window(a_series, i, "YTD")),
                r(window(a_series, i, "LTM")), r(py("MTD")), r(py("YTD")),
                r(window(b_series, i, "MTD")), r(window(b_series, i, "YTD"))]

    n = len(MONTHS)
    series_a = {(k, sid): [act[(k, sid, i)] for i in range(n)] for (k, *_ ) in A for sid, _ in subs}
    series_b = {(k, sid): [bud[(k, sid, i)] for i in range(n)] for (k, *_ ) in A for sid, _ in subs}
    groups = {"-8": ("4000", "4100"), "-9": ("4000", "4100", "5000", "5100", "5200", "6000", "6100", "6200", "6300", "6400"),
              "-3": tuple(a[0] for a in A)}
    for hk, members in groups.items():
        for sid, _ in subs:
            series_a[(hk, sid)] = [round(sum(series_a[(m, sid)][i] for m in members), 2) for i in range(n)]
            series_b[(hk, sid)] = [round(sum(series_b[(m, sid)][i] for m in members), 2) for i in range(n)]
    # ---- planted cases for the 1.5.0 engine (README lists them); applied after the roll-up rows above ----
    subs_all = subs + [(3, "Acme Acquired")]
    span = lambda lo, hi, base, sign, g=0.0: [round(sign * base * (1 + g) ** i * rng.uniform(0.97, 1.03), 2) if lo <= MONTHS[i] <= hi else None for i in range(n)]
    D = dt.date
    extra = [("4000-A", "4000", "Subscription Revenue", "Adjusted EBITDA", "Revenue", "Recurring Revenue"),   # key = account x class
             ("4000-B", "4000", "Subscription Revenue", "Adjusted EBITDA", "Revenue", "Recurring Revenue"),
             ("6500", "6500", "Consulting", "Adjusted EBITDA", "OpEx", ""),                                  # new in 2026-07
             ("6600", "6600", "Legacy Tools", "Adjusted EBITDA", "OpEx", ""),                                # stopped after 2025-12
             ("7300", "7300", "Extinguishment of Debt", "Total Non-Operating Income (Expense)", "Other income", ""),   # one-off gain
             ("4200", "4200", "Legacy Product Services", "Adjusted EBITDA", "Revenue", "Non-Recurring Revenue")]                   # product line with no 2026 activity
    for k, num, name, l2, l3, l4 in extra:
        acct_rows.append([k, num, name, "P&L", "Net Income", l2, l3, l4, *L56.get(k, (None, None)), None, None, None, 1])
    nones = [None] * n
    # Acme Acquired: acquired 2025-11, budgeted from 2026-01
    series_a[("4000", 3)] = span(D(2025, 11, 1), D(2026, 10, 1), 120_000, 1, 0.01)
    series_b[("4000", 3)] = [round(v * 0.98, 2) if v is not None and MONTHS[i] >= D(2026, 1, 1) else None for i, v in enumerate(series_a[("4000", 3)])]
    # Subscription Revenue at Acme US posts on three classes; the budget sits on the blank class only
    base_a, base_b = series_a[("4000", 1)], series_b[("4000", 1)]
    series_a[("4000-A", 1)] = [round(v * 0.35, 2) for v in base_a]
    series_a[("4000-B", 1)] = [round(v * 0.25, 2) for v in base_a]
    series_a[("4000", 1)] = [round(v - p - j, 2) for v, p, j in zip(base_a, series_a[("4000-A", 1)], series_a[("4000-B", 1)])]
    series_b[("4000-A", 1)] = series_b[("4000-B", 1)] = nones
    series_b[("4000", 1)] = base_b
    # S&M Salaries: the budget is held on Acme US for both entities
    series_b[("6000", 1)] = [round(x + y, 2) for x, y in zip(series_b[("6000", 1)], series_b[("6000", 2)])]
    series_b[("6000", 2)] = nones
    # one-sided accounts and a one-off gain below EBITDA
    series_a[("6500", 1)], series_b[("6500", 1)] = span(D(2026, 7, 1), D(2026, 10, 1), 40_000, -1), nones
    series_a[("6600", 2)] = span(D(2024, 1, 1), D(2025, 12, 1), 15_000, -1)
    series_b[("6600", 2)] = [v if v is not None and MONTHS[i].year == 2025 else None for i, v in enumerate(series_a[("6600", 2)])]
    series_a[("7300", 1)], series_b[("7300", 1)] = [1_500_000.0 if m == D(2026, 8, 1) else None for m in MONTHS], nones
    series_a[("4200", 1)], series_b[("4200", 1)] = span(D(2024, 10, 1), D(2024, 12, 1), 12_000, 1), nones     # a product line with no activity in 2026 or in its prior-year window
    CLASS = {"4000-A": "CLASS A", "4000-B": "CLASS B"}
    DEPT = {"6000": [("200 - Sales", 0.7), ("250 - Customer Success", 0.3)], "6300": [("300 - Marketing", 1.0)],
            "6100": [("400 - Engineering", 1.0)], "6200": [("500 - Finance", 1.0)]}
    real = [a[0] for a in A] + [e[0] for e in extra]
    is_rows, gov = [], {}
    for key in real + [h[0] for h in holder]:
        for sid, _ in subs_all:
            if (key, sid) not in series_a:
                continue
            for dept, share in DEPT.get(key, [(None, 1.0)]):
                sa = [None if v is None else round(v * share, 2) for v in series_a[(key, sid)]]
                sb = [None if v is None else round(v * share, 2) for v in series_b.get((key, sid), nones)]
                for i in range(n):
                    vals = rowvals(sa, sb, i)
                    if vals[0] is None and vals[4] is None and vals[6] is None:
                        continue
                    is_rows.append([key, sid, i + 1] + vals + [CLASS.get(key), dept])
                    if key in real and sa[i] is not None:
                        l3 = next((a[6] for a in A if a[0] == key), None) or next(e[4] for e in extra if e[0] == key)
                        g = gov.setdefault((sid, i), [0.0, 0.0, 0.0])
                        g[0] += sa[i] if l3 == "Revenue" else 0.0
                        g[1] += sa[i] if l3 in ("Revenue", "Cost of Sales", "OpEx") else 0.0
                        g[2] += sa[i]
    gov_rows = []
    for (sid, i), g in sorted(gov.items()):
        row = [MONTHS[i], dict(subs_all)[sid], round(g[0], 2), round(g[1], 2), round(g[2], 2)]
        gov_rows.append(row)
    is_hdr = ["CHART_OF_ACCOUNT_KEY", "SUBSIDIARY_KEY", "ACCOUNTING_PERIOD_KEY",
              "MTD", "QTD", "YTD", "LTM", "PY_MTD", "PY_YTD", "BUDGET_MTD", "BUDGET_YTD", "CLASS_NAME", "DEPARTMENT_NAME"]

    # cash flow (monthly) and balance sheet
    cf_rows, bs_rows = [], []
    for sid, _ in subs:
        cash = 5_000_000.0
        ni = series_a[("-3", sid)]
        cf_hist = {}
        debt = 4_000_000.0
        cash_hist, ar_hist, ap_hist, dr_hist, debt_hist = [], [], [], [], []
        net_hist = []
        for i in range(n):
            da = round(0.03 * abs(series_a[("5000", sid)][i]) * 4, 2)
            d_ar = round(-0.05 * (series_a[("4000", sid)][i] - (series_a[("4000", sid)][i - 1] if i else series_a[("4000", sid)][i])) * 3 + rng.uniform(-15000, 15000), 2)
            d_ap = round(rng.uniform(-12000, 18000), 2)
            capex = round(-rng.uniform(20000, 60000) * (2.2 if MONTHS[i] == dt.date(2026, 6, 1) else 1), 2)
            d_debt = 1_000_000.0 if MONTHS[i] == dt.date(2025, 3, 1) else (-50_000.0 if MONTHS[i].month == 12 else 0.0)
            lines = {"9001": ni[i], "9002": da, "9003": d_ar, "9004": d_ap, "9005": capex, "9006": d_debt}
            net = round(sum(lines.values()), 2)
            beg = round(cash, 2)
            cash = round(cash + net, 2)
            debt += d_debt
            for k, v in lines.items():
                cf_hist.setdefault(k, []).append(v)
            cf_hist.setdefault("-10", []).append(beg)
            cf_hist.setdefault("-11", []).append(cash)
            cf_hist.setdefault("-12", []).append(net)
            cash_hist.append(cash)
            ar_hist.append(round(abs(series_a[("4000", sid)][i] + series_a[("4100", sid)][i]) * 1.8, 2))
            ap_hist.append(round(abs(series_a[("5000", sid)][i] + series_a[("6400", sid)][i]) * 2.0, 2))
            dr_hist.append(round(abs(series_a[("4000", sid)][i]) * 2.5, 2))
            debt_hist.append(round(debt, 2))
        for k, vals in cf_hist.items():
            for i in range(n):
                b = round(vals[i] * rng.uniform(0.95, 1.05), 2) if k in ("9001", "9005") else None
                cf_rows.append([k, sid, i + 1, vals[i], vals[i - 12] if i >= 12 else None, b])
        for k, vals in (("1000", cash_hist), ("1100", ar_hist), ("2000", ap_hist), ("2100", dr_hist), ("2500", debt_hist), ("-1000", debt_hist)):
            for i in range(n):
                bs_rows.append([k, sid, i + 1, vals[i], vals[i - 12] if i >= 12 else None, round(vals[i] * rng.uniform(0.97, 1.04), 2)])
    bs_hdr = ["CHART_OF_ACCOUNT_KEY", "SUBSIDIARY_KEY", "ACCOUNTING_PERIOD_KEY", "MTD", "PY_MTD", "BUDGET_MTD"]

    return [
        ("ACCOUNT", acct_hdr, acct_rows),
        ("PERIOD", ["ACCOUNTING_PERIOD_KEY", "PERIOD", "PERIOD_START_DATE", "PERIOD_END_DATE", "YEAR", "QUARTER", "MONTH"], period_rows),
        ("SUBSIDIARY", ["SUBSIDIARY_KEY", "SUBSIDIARY_NAME"], [list(s) for s in subs_all]),
        ("INCOME_STATEMENT", is_hdr, is_rows),
        ("GOVERNED", ["PERIOD_START_DATE", "SUBSIDIARY_NAME", "REVENUE_MTD", "ADJUSTED_EBITDA_MTD", "NET_INCOME_MTD"], gov_rows),
        ("BALANCE_SHEET", bs_hdr, bs_rows),
        ("CASH_FLOW", bs_hdr, cf_rows),
        ("TRANSACTIONS", ["TRANSACTION_ID", "TRANSACTION_LINE_ID", "CHART_OF_ACCOUNT_KEY", "SUBSIDIARY_KEY",
                          "ACCOUNTING_PERIOD_KEY", "TRANSACTION_DATE", "TRANSACTION_TYPE", "AMOUNT", "CUSTOMER_NAME",
                          "CURRENCY_CODE"], txn),
    ]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sample-data")
    os.makedirs(out, exist_ok=True)
    note = ["SYNTHETIC SAMPLE DATA: every figure is invented, for testing the semantic-data-analyst-finance skill without a warehouse.",
            "Structure mirrors the sheets and columns of the semantic view named in the file; see references/local-mode.md.",
            f"Latest closed month in the sample: {LATEST.isoformat()}. Months: 2024-01 to 2026-10."]
    rng = random.Random(SEED)
    write(os.path.join(out, "finance_sample.xlsx"), finance(rng),
          note + ["Finance sign convention in this sample: revenue positive, expenses negative, so P&L rows sum to net income.",
                  "Planted for testing: Marketing Programs and Hosting Costs overspend in 2026-10; capex spike in 2026-06; debt draw in 2025-03.",
                  "Also planted: Acme Acquired from its 2025-11 acquisition; Subscription Revenue at Acme US on three "
                  "classes with the budget on the blank class; S&M Salaries budgeted on Acme US for both entities; Consulting new from 2026-07; "
                  "Legacy Tools stopped after 2025-12; a one-off Extinguishment of Debt gain in 2026-08; departments on opex; the GOVERNED sheet."])
    return 0


if __name__ == "__main__":
    sys.exit(main())
