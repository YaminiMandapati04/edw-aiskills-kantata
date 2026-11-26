#!/usr/bin/env python3
"""Prove the CFO Chronograph tooling on SYNTHETIC data (never real figures): the happy path and every refusal.

    python test_chronograph.py [--excel]      # --excel also open-tests the output in a hidden Excel (Windows)

Builds synthetic sql-exec results for all ten sources shaped like Kantata's views (unsigned P&L with a sign
multiplier, cash-flow rows without a cash-flow label, New / Churn / Upsell / Downsell ARR, an LTM customer bridge, the
revolver table, no coverage metric), runs
chronograph_queries.py and build_chronograph.py in a temporary folder, and checks:
  1  a consistent extract is WRITTEN, every gate passes, the file is clean, labelled SYNTHETIC, formulas kept;
     cash flow is mapped strictly (an unlabelled row goes in no line and is reported; Total Non-Cash Items blank; the
     cash totals read the view's labels); rows with no Kantata source stay blank
  2  a P&L line that no longer ties to the governed revenue is REFUSED
  3  a balance sheet that does not balance is WRITTEN and reported (the Kantata view does not balance)
  4  a month missing from the ARR bridge is REFUSED
  5  a P&L line with activity that no template row takes is REFUSED
  6  a cut-off result (declares more rows than it holds) is REFUSED
  7  a template that differs from the pinned one is REFUSED
  8  check_workbook flags a workbook with a stale view, a broken name and an external link
  9  an as-of month that has not closed is REFUSED and the last closed month is named
 10  a cash-flow row without a label is placed in no line and reported; lines that do not add up to the view's Cash
     before Financing are REFUSED
 11  a P&L line without a sign multiplier is REFUSED
 12  account exclusion: the five internal test accounts in config/scope.json are always excluded (by ID, never by
     name); given IDs are added on top and filter ARR, customers, bookings and pipeline (null-safe), leave the finance
     queries unchanged, pass the guard; a malformed ID is REFUSED; the build reports the exclusion
 13  customers are LTM; Renewal Rate % = (Beginning + Lost) / Beginning, blank where Beginning is 0; Principal Payments
     is blank until the revolver table carries it, then fills (part-filled is REFUSED); Revolver Size fills from the revolver result and Drawn Revolver from the balance sheet
     account (a stored 0 stays 0), Unused = Size - Drawn; the revolver query never carries a subsidiary or account
     filter; a missing revolver or drawn month, an unknown METRIC (including a Drawn Revolver row in the table) and
     Drawn above Size are REFUSED
Exit codes: 0 all pass, 1 a check failed.
"""
import argparse
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = []
ORDER_NAMES = ["pl", "pl_governed", "bs", "cf", "arr", "customers", "bookings", "pipeline", "revolver", "revolver_drawn"]


def step(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True, encoding="utf-8")
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def month_list(as_of, n):
    y, m = int(as_of[:4]), int(as_of[5:7])
    k0 = y * 12 + m - 1 - (n - 1)
    return [f"{(k0 + i) // 12:04d}-{(k0 + i) % 12 + 1:02d}" for i in range(n)]


def mstart(mo):
    return f"{mo}-01"


def mend(mo):
    y, m = int(mo[:4]), int(mo[5:7])
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()


def result(cols, rows, qid):
    return {"query_id": qid, "result_set": {"data": [[("" if v is None else (f"{v:.6f}" if isinstance(v, float) else str(v))) for v in r] for r in rows],
            "resultSetMetaData": {"format": "jsonv2", "numRows": len(rows), "partition": 0, "partitionInfo": [{"rowCount": len(rows)}],
                                  "rowType": [{"name": c} for c in cols]}}}


def synthetic(months):
    """Nine results shaped like Kantata's views: P&L unsigned with P_AND_L_MULTIPLIER and tied to governed; the cash flow
    carries a non-cash add-back and the translation reserve without a cash-flow label; the balance sheet balances;
    the ARR bridge uses New / Churn / Upsell / Downsell; the customer bridge is LTM (Beginning = the count 12 months
    back) and foots; weighted pipeline is 0 and the first months have no snapshot; the revolver table carries Revolver
    Size every month; the revolver account's balance (Drawn Revolver) is 0 in the second month."""
    pl, gov, bs, cf, arr, cust, bkg, ppl, rvl, drw = [], [], [], [], [], [], [], [], [], []
    cash, arr_end, logos = 5_000_000.0, 60_000_000.0, 4000
    for i, mo in enumerate(months):
        g = 1 + 0.01 * i
        rev = {("Recurring Revenue", "SaaS - Subscription", "MRR - Licenses Revenue"): 4_000_000 * g,
               ("Recurring Revenue", "SaaS - Subscription", "MRR - Self Serve Monthly"): 1_500_000 * g,
               ("Non-Recurring Revenue", "One-time Services", "Rev - Professional Service"): 350_000.0}
        cos = {("Recurring COGs", "Webhosting", None): 600_000 * g, ("Recurring COGs", "Salary", None): 400_000.0,
               ("Non-Recurring COGs", "Salary", None): 150_000.0}
        opex = {("Fully Loaded S&M Expense", "S&M Expense", "Sales Expense"): 700_000.0, ("Fully Loaded S&M Expense", "S&M Expense", "Marketing Expense"): 300_000.0,
                ("Fully Loaded S&M Expense", "S&M Expense", "Training"): 120_000.0,
                ("Fully Loaded R&D", "R&D", "Engineering Expense"): 800_000.0, ("Fully Loaded R&D", "R&D", "Product Expense"): 250_000.0,
                ("Fully Loaded R&D", "R&D", "Other R&D Expense"): 60_000.0,
                ("G&A", "Finance Department", None): 400_000.0, ("G&A", "HR Department", None): 100_000.0,
                ("G&A", "IT Department", None): 150_000.0, ("G&A", "Other G&A Spend", None): 90_000.0}
        nonop = {("Depreciation & Amortization", "Depreciation", None): 900_000.0,
                 ("Interest Expense", "Interest", None): 500_000.0, ("Income Taxes", "Taxation", None): 50_000.0,
                 ("Other Non-Operating Income & Expense", "Severance", None): 20_000.0,
                 ("Other Non-Operating Income & Expense", "Other Items", None): 30_000.0}
        # the view stores P&L values unsigned; the multiplier (+1 revenue, -1 costs) signs them
        for k, v in rev.items():
            pl.append([mstart(mo), "Adjusted EBITDA", "Revenue", *k, 1.0, v])
        for k, v in cos.items():
            pl.append([mstart(mo), "Adjusted EBITDA", "Cost of Sales", *k, -1.0, v])
        for k, v in opex.items():
            pl.append([mstart(mo), "Adjusted EBITDA", "Operating Expenses", *k, -1.0, v])
        for k, v in nonop.items():
            pl.append([mstart(mo), "Total Non-Operating Income (Expense)", "Total Non-Operating Income (Expense)", *k, -1.0, v])
        r, c, o, n = sum(rev.values()), sum(cos.values()), sum(opex.values()), sum(nonop.values())
        ebitda = r - c - o
        ni = ebitda - n
        gov.append([mstart(mo), r, ebitda, ni])
        # cash flow: NI + D&A add-back (no cash-flow label) + working capital + capex + debt; translation reserve (no label) as FX
        da, wc, capex, debt, fx = 900_000.0, 400_000.0, -300_000.0, -100_000.0, 5_000.0
        beg = cash
        net = ni + da + wc + capex + debt
        cash = beg + net + fx
        cf += [[mstart(mo), "Cash from Operations", "Income from Operations", "Net Income", "Net Income", "Net Income", ni],
               [mstart(mo), "", "", "", "Net Income", "Total Non-Operating Income (Expense)", da],
               [mstart(mo), "Cash from Operations", "Change in Working Capital", "Accounts Receivable", "Assets", "Accounts Receivable", wc],
               [mstart(mo), "Cash from Investing", "Capital Expenditures", "Fixed Assets", "Assets", "Other Non-Current Assets", capex],
               [mstart(mo), "Cash from Financing", "Change in debt", "Long Term Liabilities", "Total Liabilities & Share Holder Equity", "Long-Term Liabilities", debt],
               [mstart(mo), "FX Change", "FX Change", "FX Change", "Total Liabilities & Share Holder Equity", "FX on retranslation", fx],
               [mstart(mo), "Beginning Cash", "Beginning Cash", "Beginning Cash", "", "", beg],
               [mstart(mo), "Ending Cash", "Ending Cash", "Ending Cash", "", "", cash],
               [mstart(mo), "Net Cash Flow", "Net Change in Cash", "Net Cash Flow", "", "", net],
               [mstart(mo), "Cash before Financing", "Cash before Financing", "Cash before Financing", "", "", ni + wc + capex]]
        ar, gw, fixed, other_nca = 8_000_000.0, 150_000_000.0, 400_000.0, 2_000_000.0
        ap, ap2, dr, other_cl, debt_b = 300_000.0, 700_000.0, 20_000_000.0, 250_000.0, 80_000_000.0
        assets = cash + ar + gw + fixed + other_nca
        bs += [[mstart(mo), "Assets", "Current Assets", "Cash & Cash Equivalents", "Bank", cash],
               [mstart(mo), "Assets", "Current Assets", "Accounts Receivable", "Trade debtors", ar],
               [mstart(mo), "Assets", "Non-Current Assets", "Goodwill & Intangibles", "Intangible fixed assets", gw],
               [mstart(mo), "Assets", "Non-Current Assets", "Other Non-Current Assets", "Tangible fixed assets", fixed],
               [mstart(mo), "Assets", "Non-Current Assets", "Other Non-Current Assets", "Investments", other_nca],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Accounts Payable", ap],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Acounts Payable", ap2],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Deferred Revenue", dr],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "VAT Liability", other_cl],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Long-Term Liabilities", "Senior Debt", debt_b],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Equity", "Retained earnings", "Retained earnings", -10_000_000.0],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Equity", "Share capital", "Share capital", assets - ap - ap2 - dr - other_cl - debt_b + 10_000_000.0]]
        new, churn, up, down = 500_000.0, -200_000.0, 700_000.0, -300_000.0
        b = arr_end
        gdr = b + churn + down
        ndr = gdr + up
        arr_end = ndr + new
        ltm_b = b * 0.92
        for cat, v, l in (("Beginning ARR", b, ltm_b), ("New", new, new * 12), ("Churn", churn, churn * 12), ("Upsell", up, up * 12),
                          ("Downsell", down, down * 12), ("Gross Dollar Retention", gdr, ltm_b + churn * 12 + down * 12),
                          ("Net Dollar Retention", ndr, ltm_b + (churn + down + up) * 12), ("Ending ARR", arr_end, arr_end)):
            arr.append([mend(mo), cat, v, l])
        logos += 10                                                     # month-end count (MTD Ending = LTM Ending)
        bl, ll = logos - 120, -950                                      # LTM: the count 12 months back, LTM lost
        nl = logos - bl - ll                                            # the LTM bridge foots
        cust += [[mend(mo), "Beginning Customers", bl], [mend(mo), "New Customers", nl], [mend(mo), "Lost Customers", ll], [mend(mo), "Ending Customers", logos]]
        rvl += [["Revolver Size", mstart(mo), 25_000_000]]
        drw += [[mstart(mo), 0.0 if i == 1 else 17_000_000.0]]
        bkg.append([mend(mo), 1_000_000.0, 200_000.0, 1_200_000.0])
        if i >= 2:                                                      # no pipeline snapshot for the first two months
            ppl.append([mend(mo), 20_000_000.0, 0.0])
    ppl.append([dt.date.today().isoformat(), 1.0, 1.0])                # a today row: ignored (not a month-end)
    return {
        "pl": result(["PERIOD_START_DATE", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "COA_MAPPING_L5", "COA_MAPPING_L6", "P_AND_L_MULTIPLIER", "TOTAL_MTD"], pl, "synthetic-pl"),
        "pl_governed": result(["PERIOD_START_DATE", "REVENUE_MTD", "ADJUSTED_EBITDA_MTD", "NET_INCOME_MTD"], gov, "synthetic-gov"),
        "bs": result(["PERIOD_START_DATE", "COA_MAPPING_L1", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "ENDING_BALANCE_CONVERTED"], bs, "synthetic-bs"),
        "cf": result(["PERIOD_START_DATE", "CASH_FLOW_L1", "CASH_FLOW_L2", "CASH_FLOW_L3", "COA_MAPPING_L1", "COA_MAPPING_L3", "TOTAL_MTD"], cf, "synthetic-cf"),
        "arr": result(["MONTH_END_DATE", "CATEGORY", "TOTAL_MTD", "TOTAL_LTM"], arr, "synthetic-arr"),
        "customers": result(["MONTH_END_DATE", "CATEGORY", "TOTAL_LTM"], cust, "synthetic-cust"),
        "bookings": result(["AS_OF_DATE", "RECURRING_BOOKINGS_MTD", "NON_RECURRING_BOOKINGS_MTD", "TOTAL_BOOKINGS_MTD"], bkg, "synthetic-bkg"),
        "pipeline": result(["AS_OF_DATE", "OPEN_PIPELINE_VALUE_MTD", "WEIGHTED_PIPELINE_VALUE_MTD"], ppl, "synthetic-ppl"),
        "revolver": result(["METRIC", "MONTH_START_DATE", "REVOLVER_AMOUNT"], rvl, "synthetic-rev"),
        "revolver_drawn": result(["PERIOD_START_DATE", "ENDING_BALANCE_CONVERTED"], drw, "synthetic-drawn"),
    }


def write_raw(work, data):
    for name, obj in data.items():
        with open(os.path.join(work, "raw", f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel", action="store_true", help="also open-test the happy-path output in a hidden Excel")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="chrono-test-")
    work, out = os.path.join(tmp, "work"), os.path.join(tmp, "outputs")
    today = dt.date.today()
    k = today.year * 12 + today.month - 2
    as_of = f"{k // 12:04d}-{k % 12 + 1:02d}"
    try:
        code, res = run("chronograph_queries.py", "--as-of", as_of, "--work", work)
        step("chronograph_queries writes ten guard-checked queries and a manifest", code == 0 and len(res.get("queries", [])) == 10, json.dumps(res)[:200])
        man_path = os.path.join(work, "queries", "manifest.json")
        man = json.load(open(man_path, encoding="utf-8"))
        man["mode"] = "synthetic"
        json.dump(man, open(man_path, "w", encoding="utf-8"), indent=2)
        months = month_list(as_of, man["months"])
        base = synthetic(months)
        excel = "auto" if a.excel else "off"

        # 1 happy path
        write_raw(work, base)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", excel)
        step("1 a consistent extract is written and every gate passes", code == 0 and res.get("checks", {}).get("result") == "PASS", json.dumps(res)[:400])
        if code == 0:
            from openpyxl import load_workbook
            wb = load_workbook(res["out"])
            ws = wb.active
            rows = {}
            for r in range(1, ws.max_row + 1):
                if ws.cell(r, 2).value:
                    rows.setdefault(str(ws.cell(r, 2).value).strip(), r)          # first occurrence (P&L Net Income before the cash flow's)
            step("1 one sheet named 'Accel-KKR Chronograph', title without 'Template', no defined names, labelled SYNTHETIC in B2", wb.sheetnames == ["Accel-KKR Chronograph"] and ws["B1"].value == "Accel-KKR Portfolio Company Monthly Reporting" and not list(wb.defined_names)
                 and str(ws["B2"].value).startswith("SYNTHETIC TEST DATA"), str(ws["B2"].value)[:80])
            last = ws.max_column
            step("1 header on row 3, months from column C, totals stay formulas, S&M SUM includes Other S&M",
                 ws["B3"].value == "P&L Items" and last == 2 + len(months) and str(ws.cell(rows["Total Revenue"], last).value).startswith("=")
                 and ws.cell(rows["S&M Expense"], 3).value == f"=SUM(C{rows['Sales Expense']}:C{rows['Other S&M Expense']})",
                 f"cols {last}, S&M {ws.cell(rows['S&M Expense'], 3).value}")
            step("1 PF Adjusted EBITDA keeps the template's formula (Adjusted EBITDA + the synergy rows) in every month",
                 all(ws.cell(rows["PF Adjusted EBITDA"], c).value == f"={col}{rows['Adjusted EBITDA']}+SUM({col}{rows['Unrealized Synergies']}:{col}{rows['Strategic Investments / Other']})"
                     for c, col in ((c, ws.cell(1, c).column_letter) for c in range(3, last + 1))),
                 str(ws.cell(rows["PF Adjusted EBITDA"], 3).value))
            cfl = {}
            for r_ in base["cf"]["result_set"]["data"]:
                if r_[1] in ("Beginning Cash", "Ending Cash", "Net Cash Flow", "Cash before Financing"):
                    cfl[(r_[0][:7], r_[1])] = float(r_[-1])
            step("1 Beginning Cash, Cash Before Financing, Net Cash Flow and Ending Cash read the view's labels in every month (thousands)",
                 all(abs(ws.cell(rows[lab], 3 + i).value - cfl[(mo, key)] / 1000) < 1e-6
                     for lab, key in (("Beginning Cash", "Beginning Cash"), ("Ending Cash", "Ending Cash"), ("Net Cash Flow", "Net Cash Flow"), ("Cash Before Financing", "Cash before Financing"))
                     for i, mo in enumerate(months)))
            step("1 headcount rows are blank, not 0", ws.cell(rows["COGS HC Total"], 3).value is None)
            step("1 recurring bookings sit in Recurring Services; New and Upsell are blank (the view does not split them)",
                 isinstance(ws.cell(rows["Bookings - Recurring Services"], 3).value, (int, float))
                 and ws.cell(rows["Bookings - ARR (New)"], 3).value is None and ws.cell(rows["Bookings - ARR (Upsell)"], 3).value is None)
            step("1 ARR rows Kantata does not carry are blank; Churn and Downsell are filled",
                 all(ws.cell(rows[k], 3).value is None for k in ("(+) Cross-Sell", "(+) Price Increase", "(-) Downsell/Contraction (Transactional)"))
                 and ws.cell(rows["(-) Churn/Lost"], 3).value == 200 and ws.cell(rows["(-) Downsell/Contraction (Subscription)"], 3).value == 300
                 and ws.cell(rows["(-) Lost"], 3).value == 950)
            step("1 strict mapping: the unlabelled row goes in no line (Total Non-Cash Items blank), FX Change from its label",
                 ws.cell(rows["Total Non-Cash Items"], 3).value is None and ws.cell(rows["FX Change"], 3).value == 5
                 and str(ws.cell(rows["Income from Operations"], 3).value).startswith("="),
                 f"{ws.cell(rows['Total Non-Cash Items'], 3).value} / {ws.cell(rows['FX Change'], 3).value}")
            nrec = next((i for i in res.get("reconciling_items", []) if i["row"] == "Cash Flow Statement | Net Cash Flow"), {})
            step("1 the gap between the view's Net Cash Flow and the lines (the unlabelled row) is reported, not placed",
                 nrec.get("months_different") == len(months) and all(abs(d["difference"] - 900_000) < 1 for d in nrec.get("differences", [])),
                 json.dumps(nrec)[:300])
            step("1 weighted pipeline (0 in every month) and coverage are blank; pipeline months without a snapshot are blank",
                 all(ws.cell(rows["Weighted Pipeline"], c).value is None for c in range(3, 3 + len(months)))
                 and ws.cell(rows["Quarterly Pipeline Coverage Ratio"], 3).value is None
                 and ws.cell(rows["Unweighted Pipeline"], 3).value is None and ws.cell(rows["Unweighted Pipeline"], 5).value == 20_000)
            step("1 the template's convention: revenue positive, costs, D&A and taxes entered positive (subtracted by its formulas)",
                 ws.cell(rows["Sales Expense"], 3).value == 700 and ws.cell(rows["SaaS - Subscription"], 3).value > 0
                 and ws.cell(rows["Depreciation & Amortization"], 3).value == 900 and ws.cell(rows["Income Taxes"], 3).value == 50)
            step("1 cash flow: working-capital change and capex entered positive as uses of cash, financing signed",
                 ws.cell(rows["Change in Working Capital"], 3).value == -400 and ws.cell(rows["Capital Expenditures"], 3).value == 300
                 and ws.cell(rows["Change in Debt"], 3).value == -100)
            step("1 the build reports the rows entered positive",
                 {"Profit & Loss | Sales Expense", "Cash Flow Statement | Capital Expenditures", "ARR Bridge | (-) Churn/Lost", "Customer Bridge | (-) Lost"} <= set(res.get("entered_positive", [])))
            step("1 balance sheet: two AP accounts summed, Equity from COA L2, remainders for the Other rows",
                 ws.cell(rows["Accounts Payable"], 3).value == 1_000 and ws.cell(rows["Other Current Liabilities"], 3).value == 250
                 and ws.cell(rows["Net Fixed Assets"], 3).value == 400 and ws.cell(rows["Other Non-Current Assets"], 3).value == 2_000)
            kinds = {c["item"] for c in res.get("confirm_at_source", [])}
            step("1 the hand-over lists what to confirm at source (pipeline gap, weighted pipeline, unlabelled cash-flow rows)",
                 {"Pipeline", "Pipeline | Weighted Pipeline", "Cash flow | rows without a cash-flow label"} <= kinds, json.dumps(sorted(kinds)))
            step("1 retention rows are derived ratios formatted as percent", ws.cell(rows["Net Retention %"], 3).number_format == "0.0%" and 0 < ws.cell(rows["Net Retention %"], 3).value < 2)
            shown = load_workbook(res["out"], data_only=True).active             # what Excel shows before it recalculates
            heads = [shown.cell(3, c).value for c in range(3, shown.max_column + 1)]
            step("1 every month header shows a month-end date (not only the first)", len(heads) == len(months) and all(
                 isinstance(h, dt.datetime) and h.strftime("%Y-%m") == months[i] for i, h in enumerate(heads)), str(heads[:3]))
            gov_rev = [float(r[1]) for r in base["pl_governed"]["result_set"]["data"]]
            step("1 totals carry their calculated result (Total Revenue, in thousands, x 1,000 = governed revenue every month)",
                 all(abs((shown.cell(rows["Total Revenue"], 3 + i).value or 0) * 1000 - gov_rev[i]) <= 1 for i in range(len(months))))
            step("1 amounts held in thousands (values divided by 1,000) with one decimal, US grouping above 100,000.0, customer counts unscaled",
                 ws.cell(rows["Total Revenue"], 3).number_format == "#,##0.0;\\(#,##0.0\\);\\-"
                 and ws.cell(rows["Goodwill & Intangibles"], 3).number_format == "#\\,##0.0;\\(#\\,##0.0\\);\\-"
                 and ws.cell(rows["Ending Customers"], 3).number_format == "#,##0;\\(#,##0\\);\\-"
                 and ws.cell(rows["Net Retention %"], 3).number_format == "0.0%"
                 and shown.cell(rows["Goodwill & Intangibles"], 3).value == 150_000,
                 f"{ws.cell(rows['Total Revenue'], 3).number_format} | {ws.cell(rows['Goodwill & Intangibles'], 3).number_format}")
            step("1 no frozen panes, nothing in column A, provenance in the document properties",
                 ws.freeze_panes is None and all(c.value is None for c in ws["A"]) and "FINANCE_ANALYTICS" in (wb.properties.description or ""))
            step("1 automatic calculation (no stale values)", wb.calculation.calcMode in (None, "auto") and res.get("formula_results_stored", 0) > 0)
            step("1 the workbook check is clean", res["workbook_check"]["status"] == "CLEAN" and (not a.excel or res["workbook_check"]["excel"] in ("PASS", "UNAVAILABLE")), json.dumps(res["workbook_check"]))

        # 2 P&L does not tie
        bad = copy.deepcopy(base)
        bad["pl"]["result_set"]["data"][0][-1] = str(float(bad["pl"]["result_set"]["data"][0][-1]) + 5000)
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("2 a P&L that does not tie to governed revenue is refused", code == 1 and "Profit & Loss | Total Revenue" in json.dumps(res.get("failed_rows", {})), json.dumps(res)[:300])

        # 3 balance sheet does not balance: reported, not blocking (Kantata's view does not balance)
        bad = copy.deepcopy(base)
        eq = next(r for r in bad["bs"]["result_set"]["data"] if r[3] == "Share capital")
        eq[-1] = str(float(eq[-1]) - 5000)
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        recon = next((i for i in res.get("reconciling_items", []) if i["row"] == "Balance Sheet | A = L + E"), {})
        step("3 a balance sheet that does not balance is written and the gap reported", code == 0 and recon.get("months_different") == 1
             and any(c["item"] == "Balance Sheet | A = L + E" for c in res.get("confirm_at_source", [])), json.dumps(res)[:300])

        # 4 a month missing from the ARR bridge
        bad = copy.deepcopy(base)
        bad["arr"]["result_set"]["data"] = [r for r in bad["arr"]["result_set"]["data"] if r[0] != mend(months[5])]
        bad["arr"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["arr"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("4 a month missing from the ARR bridge is refused", code == 1 and months[5] in res.get("reason", ""), json.dumps(res)[:300])

        # 5 a P&L line with activity that no row takes (governed moves with it, so only coverage can catch it)
        bad = copy.deepcopy(base)
        for i, mo in enumerate(months):
            bad["pl"]["result_set"]["data"].append([mstart(mo), "Adjusted EBITDA", "Revenue", "Grant Income", "Grant Income", "Grant Income", "1.0000", "1000.000000"])
            g = bad["pl_governed"]["result_set"]["data"][i]
            for j in (1, 2, 3):
                g[j] = str(float(g[j]) + 1000)
        bad["pl"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["pl"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("5 a P&L line with activity and no template row is refused", code == 1 and "Grant Income" in json.dumps(res), json.dumps(res)[:300])

        # 6 a cut-off result
        bad = copy.deepcopy(base)
        bad["bookings"]["result_set"]["resultSetMetaData"]["numRows"] += 5
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("6 a cut-off result is refused", code == 1 and "cut off" in res.get("reason", ""), json.dumps(res)[:300])

        # 7 a template that is not the pinned one
        write_raw(work, base)
        from openpyxl import load_workbook
        other = os.path.join(tmp, "other_template.xlsx")
        w = load_workbook(os.path.join(SKILL, "assets", "chronograph_template.xlsx"))
        w.active["B1"] = "Edited title"
        w.save(other)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off", "--template", other)
        step("7 a template that differs from the pinned one is refused", code == 1 and "template_sha256" in res.get("reason", ""), json.dumps(res)[:300])

        # 8 check_workbook flags the faults that made Excel repair the old template
        import check_workbook
        from openpyxl.workbook.defined_name import DefinedName
        broken = os.path.join(tmp, "broken.xlsx")
        w = load_workbook(os.path.join(SKILL, "assets", "chronograph_template.xlsx"))
        w.views[0].firstSheet = 1
        w.defined_names["Broken"] = DefinedName("Broken", attr_text="#REF!")
        w.save(broken)
        probs = check_workbook.check(broken)
        step("8 check_workbook flags a stale view and a #REF! name", any("firstSheet" in p for p in probs) and any("defined name" in p for p in probs), json.dumps(probs))
        w = load_workbook(os.path.join(SKILL, "assets", "chronograph_template.xlsx"))
        w.calculation.calcMode = "manual"
        w.save(broken)
        probs = check_workbook.check(broken, require_results=True)
        step("8 check_workbook flags manual calculation and formulas saved without a result",
             any("manual calculation" in p for p in probs) and any("without a result" in p for p in probs), json.dumps(probs))
        clean = check_workbook.check(os.path.join(SKILL, "assets", "chronograph_template.xlsx"))
        step("8 the pinned template passes the structural check", clean == [], json.dumps(clean))

        # 9 the as-of month has not closed (a few accruals, almost no revenue)
        bad = copy.deepcopy(base)
        g = bad["pl_governed"]["result_set"]["data"][-1]
        g[1] = "60000.000000"
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("9 an as-of month that has not closed is refused and the last closed month is named",
             code == 1 and "has not closed" in res.get("reason", "") and res.get("use_as_of") == months[-2], json.dumps(res)[:300])

        # 10 strict mapping: another unlabelled row is placed nowhere and reported; lines that miss the view's Cash before Financing are refused
        bad = copy.deepcopy(base)
        bad["cf"]["result_set"]["data"].append([mstart(months[3]), "", "", "", "Assets", "Suspense", "1234.000000"])
        bad["cf"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["cf"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        unl = next((c for c in res.get("confirm_at_source", []) if c["item"] == "Cash flow | rows without a cash-flow label"), {})
        step("10 an unlabelled cash-flow row is placed in no line and reported", code == 0 and "Assets > Suspense" in unl.get("detail", ""), json.dumps(res)[:300])
        bad = copy.deepcopy(base)
        wcr = next(r for r in bad["cf"]["result_set"]["data"] if r[0] == mstart(months[2]) and r[2] == "Change in Working Capital")
        wcr[-1] = str(float(wcr[-1]) + 5000)
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("10 cash-flow lines that do not add up to the view's Cash before Financing are refused",
             code == 1 and "Cash Flow Statement | Cash Before Financing" in json.dumps(res.get("failed_rows", {})), json.dumps(res)[:300])

        # 11 a P&L line without a sign multiplier
        bad = copy.deepcopy(base)
        bad["pl"]["result_set"]["data"][0][6] = ""
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("11 a P&L line without a sign multiplier is refused", code == 1 and "P_AND_L_MULTIPLIER" in res.get("reason", ""), json.dumps(res)[:300])

        # 12 account exclusion: the standing test accounts always, user IDs on top; null-safe, on ARR / customers / bookings / pipeline only
        import sql_guard
        scope_cfg = json.load(open(os.path.join(SKILL, "config", "scope.json"), encoding="utf-8"))
        test_ids = scope_cfg["exclude_accounts"]
        default_sql = {n: open(os.path.join(work, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ORDER_NAMES}
        dclause = lambda col: f"AND ({col} IS NULL OR {col} NOT IN ('" + "', '".join(test_ids) + "'))"
        step("12 without --exclude-accounts the five internal test accounts are still excluded (manifest and queries)",
             len(test_ids) == 5 and man["scope"].get("exclude_accounts") == test_ids and man["scope"].get("exclude_accounts_default") == test_ids
             and all(dclause("CUSTOMER.ACCOUNT_ID") in default_sql[n] for n in ("arr", "customers"))
             and all(dclause("DIM_ACCOUNT.ACCOUNT_ID") in default_sql[n] for n in ("bookings", "pipeline"))
             and not any("ACCOUNT_ID" in default_sql[n] for n in ("pl", "pl_governed", "bs", "cf", "revolver", "revolver_drawn")))
        step("12 the exclusion is by ID only: no query filters on an account name",
             not any("ACCOUNT_NAME" in q or "ILIKE" in q.upper() or "%test%" in q.lower() for q in default_sql.values()))
        ids = ["0013r00002fpJz4AAE", "001UW000011EKiZYAW"]
        idfile = os.path.join(tmp, "ids.txt")
        with open(idfile, "w", encoding="utf-8") as fh:
            fh.write("# accounts to leave out\n0010Z000023EerWQAS\n0013r00002fpJz4AAE  # duplicate of the flag\n")
        w2 = os.path.join(tmp, "work_excl")
        code, res = run("chronograph_queries.py", "--as-of", as_of, "--work", w2, "--exclude-accounts", ",".join(ids), "--exclude-accounts-file", idfile)
        man2 = json.load(open(os.path.join(w2, "queries", "manifest.json"), encoding="utf-8")) if code == 0 else {}
        want = list(dict.fromkeys(test_ids + ids + ["0010Z000023EerWQAS"]))
        step("12 IDs from the flag and a file are added to the test accounts, de-duplicated and recorded in the manifest",
             code == 0 and res.get("excluded_accounts") == 7 and man2.get("scope", {}).get("exclude_accounts") == want
             and man2["scope"].get("exclude_accounts_requested") == ["001UW000011EKiZYAW", "0010Z000023EerWQAS"], json.dumps(res)[:300])
        q2 = {n: open(os.path.join(w2, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ORDER_NAMES}
        clause = lambda col: f"AND ({col} IS NULL OR {col} NOT IN ('" + "', '".join(want) + "'))"
        step("12 ARR and customers filter CUSTOMER.ACCOUNT_ID, bookings and pipeline DIM_ACCOUNT.ACCOUNT_ID, null-safe",
             all(clause("CUSTOMER.ACCOUNT_ID") in q2[n] for n in ("arr", "customers"))
             and all(clause("DIM_ACCOUNT.ACCOUNT_ID") in q2[n] for n in ("bookings", "pipeline")))
        step("12 the finance queries are unchanged by an account exclusion",
             all(q2[n] == open(os.path.join(work, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ("pl", "pl_governed", "bs", "cf")))
        step("12 every filtered query passes the read-only guard", all(sql_guard.check(q2[n]).get("ok") for n in ORDER_NAMES))
        for bad_id, why in (("0013r00002fpJz4", "15-character"), ("0013r00002fpJz4AAE'); DROP TABLE x;--", "injection")):
            code, res = run("chronograph_queries.py", "--as-of", as_of, "--work", os.path.join(tmp, "work_bad"), "--exclude-accounts", bad_id)
            step(f"12 a {why} ID is refused and no queries are written", code == 1 and "18-character" in res.get("reason", "")
                 and not os.path.exists(os.path.join(tmp, "work_bad", "queries", "arr.sql")), json.dumps(res)[:300])
        m2 = os.path.join(w2, "queries", "manifest.json")
        man2["mode"] = "synthetic"
        json.dump(man2, open(m2, "w", encoding="utf-8"), indent=2)
        os.makedirs(os.path.join(w2, "raw"), exist_ok=True)
        write_raw(w2, base)
        code, res = run("build_chronograph.py", "--work", w2, "--out", os.path.join(tmp, "out_excl"), "--excel", "off")
        sc = res.get("scope", {})
        step("12 a build with excluded accounts passes every gate and reports them with the finance caveat",
             code == 0 and res.get("checks", {}).get("result") == "PASS" and sc.get("excluded_accounts") == want
             and "P&L" in sc.get("excluded_accounts_note", ""), json.dumps(res)[:300])
        if code == 0:
            from openpyxl import load_workbook
            desc = load_workbook(res["out"]).properties.description or ""
            step("12 the document properties name the excluded accounts", "Excludes 7 Salesforce account(s) (5 internal test account(s)" in desc and want[-1] in desc, desc[:200])

        # 13 customers LTM, renewal rate, principal payments, revolver
        write_raw(work, base)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 the build with the LTM customer bridge and the revolver passes every gate", code == 0 and res.get("checks", {}).get("result") == "PASS", json.dumps(res)[:400])
        if code == 0:
            from openpyxl import load_workbook
            wb = load_workbook(res["out"])
            ws = wb.active
            shown = load_workbook(res["out"], data_only=True).active
            rows = {}
            for r in range(1, ws.max_row + 1):
                if ws.cell(r, 2).value:
                    rows.setdefault(str(ws.cell(r, 2).value).strip(), r)
            cust = {}
            for d, c, v in base["customers"]["result_set"]["data"]:
                cust.setdefault(d[:7], {})[c] = float(v)
            ok = all(abs(ws.cell(rows["Renewal Rate %"], 3 + i).value - (cust[mo]["Beginning Customers"] + cust[mo]["Lost Customers"]) / cust[mo]["Beginning Customers"]) < 1e-6
                     for i, mo in enumerate(months))
            step("13 Renewal Rate % = (Beginning + Lost) / Beginning from the LTM counts, formatted 0.0%, with a derived note",
                 ok and ws.cell(rows["Renewal Rate %"], 3).number_format == "0.0%" and "CUSTOMER_BRIDGE LTM" in (ws.cell(rows["Renewal Rate %"], 2).comment.text if ws.cell(rows["Renewal Rate %"], 2).comment else "")
                 and any(d["row"] == "ARR Bridge | Renewal Rate %" for d in res.get("derived", [])))
            step("13 Customer Bridge rows carry the LTM note and Beginning Customers is the LTM count",
                 all(ws.cell(rows[k], 2).comment and "TOTAL_LTM" in ws.cell(rows[k], 2).comment.text for k in ("Beginning Customers", "(-) Lost", "Ending Customers"))
                 and ws.cell(rows["Beginning Customers"], 3).value == cust[months[0]]["Beginning Customers"])
            pp = rows["Principal Payments"]
            step("13 Principal Payments is blank (never 0) while the revolver table has no Principal Payments rows, and listed with its reason",
                 all(ws.cell(pp, c).value is None for c in range(3, 3 + len(months)))
                 and any(b["row"] == "Liquidity | Principal Payments" and "Principal Payments" in (b.get("reason") or "") for b in res.get("blank", [])))
            rs, rd, ru = rows["$ Revolver Size"], rows["$ Drawn Revolver"], rows["$ Unused Revolver"]
            step("13 Revolver Size fills from the revolver result and Drawn Revolver from the balance sheet account (thousands), a stored 0 stays 0, every month written (no chain), with the account note",
                 all(ws.cell(rs, c).value == 25_000 for c in range(3, 3 + len(months)))
                 and ws.cell(rd, 3).value == 17_000 and ws.cell(rd, 4).value == 0 and ws.cell(rd, 5).value == 17_000
                 and ws.cell(rd, 2).comment is not None and "account 280360" in ws.cell(rd, 2).comment.text,
                 f"{ws.cell(rs, 4).value} / {ws.cell(rd, 4).value}")
            step("13 Unused Revolver stays the template formula and shows Size - Drawn",
                 str(ws.cell(ru, 3).value).startswith("=") and all(abs((shown.cell(ru, c).value or 0) - ((shown.cell(rs, c).value or 0) - (shown.cell(rd, c).value or 0))) < 1e-6 for c in range(3, 3 + len(months)))
                 and shown.cell(ru, 3).value == 8_000 and shown.cell(ru, 4).value == 25_000)
            step("13 the Drawn <= Size gate ran, and revolver rows are no longer reported blank",
                 not any(b["row"].startswith("Liquidity | $") or b["row"] == "ARR Bridge | Renewal Rate %" for b in res.get("blank", []))
                 and res.get("last_month", {}).get("Liquidity | $ Drawn Revolver") == 17_000_000)
        # Renewal Rate blank (never 0) where Beginning Customers is 0
        bad = copy.deepcopy(base)
        for r in bad["customers"]["result_set"]["data"]:
            if r[0] == mend(months[3]):
                if r[1] == "Beginning Customers":
                    r[2] = "0"
                elif r[1] == "Lost Customers":
                    r[2] = "0"
                elif r[1] == "New Customers":
                    end = next(x for x in bad["customers"]["result_set"]["data"] if x[0] == r[0] and x[1] == "Ending Customers")
                    r[2] = end[2]
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        if code == 0:
            from openpyxl import load_workbook
            ws = load_workbook(res["out"]).active
            rr = next(r for r in range(1, ws.max_row + 1) if str(ws.cell(r, 2).value or "").strip() == "Renewal Rate %")
            step("13 Renewal Rate % is blank, not 0, where Beginning Customers is 0", ws.cell(rr, 6).value is None and ws.cell(rr, 5).value is not None)
        else:
            step("13 Renewal Rate % is blank, not 0, where Beginning Customers is 0", False, json.dumps(res)[:300])
        # the revolver query: no subsidiary or account filter, even with exclusions
        import chronograph_queries as cq
        qs = cq.build_queries("PROD_DB", "SEMANTIC_VIEWS", dt.date(2025, 1, 1), dt.date(2026, 12, 1), ["Some Sub"], ["-1"], ["R&D"], ["0013r00002fpJz4AAE"])
        step("13 the revolver query carries no subsidiary or account filter even when both are excluded, and passes the guard",
             "SUBSIDIARY" not in qs["revolver"] and "ACCOUNT_ID" not in qs["revolver"] and "SUBSIDIARY" in qs["pl"]
             and "REVOLVER.REVOLVER_AMOUNT" in qs["revolver"] and "BETWEEN '2025-01-01' AND '2026-12-01'" in qs["revolver"] and sql_guard.check(qs["revolver"]).get("ok"))
        step("13 the manifest records that the revolver has no subsidiary dimension", "no subsidiary" in man["scope"].get("revolver", ""))
        step("13 the drawn query reads the balance sheet for account 280360, carries the subsidiary exclusion like bs, no account filter, passes the guard",
             "BALANCE_SHEET.ENDING_BALANCE_CONVERTED" in qs["revolver_drawn"] and "ACCOUNT.ACCOUNT_NUMBER = '280360'" in qs["revolver_drawn"]
             and "SUBSIDIARY.SUBSIDIARY_NAME NOT IN ('Some Sub')" in qs["revolver_drawn"] and "ACCOUNT_ID" not in qs["revolver_drawn"]
             and sql_guard.check(qs["revolver_drawn"]).get("ok") and man["scope"].get("revolver_drawn_account") == "280360")
        # a missing drawn month
        bad = copy.deepcopy(base)
        bad["revolver_drawn"]["result_set"]["data"] = [r for r in bad["revolver_drawn"]["result_set"]["data"] if r[0] != mstart(months[5])]
        bad["revolver_drawn"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver_drawn"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 a missing Drawn Revolver month is refused", code == 1 and "no data for" in res.get("reason", "") and months[5] in res.get("reason", "") and "280360" in res.get("reason", ""), json.dumps(res)[:300])
        # a Drawn Revolver row appearing in the REVOLVER table: a second source, refused rather than silently ignored
        bad = copy.deepcopy(base)
        bad["revolver"]["result_set"]["data"].append(["Drawn Revolver", mstart(months[2]), "17000000"])
        bad["revolver"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 a Drawn Revolver METRIC in the REVOLVER table is refused (Drawn comes from the balance sheet)", code == 1 and "Drawn Revolver" in res.get("reason", ""), json.dumps(res)[:300])
        # Principal Payments once Finance adds it to the revolver table; part-filled is refused
        bad = copy.deepcopy(base)
        bad["revolver"]["result_set"]["data"] += [["Principal Payments", mstart(mo), "250000"] for mo in months]
        bad["revolver"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        ok = False
        if code == 0:
            from openpyxl import load_workbook
            ws = load_workbook(res["out"]).active
            pr = next(r for r in range(1, ws.max_row + 1) if str(ws.cell(r, 2).value or "").strip() == "Principal Payments")
            ok = all(ws.cell(pr, c).value == 250 for c in range(3, 3 + len(months)))
        step("13 Principal Payments fills from the revolver table's Principal Payments METRIC once present (thousands)", ok, json.dumps(res)[:300])
        bad["revolver"]["result_set"]["data"] = [r for r in bad["revolver"]["result_set"]["data"] if not (r[0] == "Principal Payments" and r[1] == mstart(months[3]))]
        bad["revolver"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 Principal Payments in only some months is refused", code == 1 and "Principal Payments" in res.get("reason", "") and months[3] in res.get("reason", ""), json.dumps(res)[:300])
        # a missing revolver month
        bad = copy.deepcopy(base)
        bad["revolver"]["result_set"]["data"] = [r for r in bad["revolver"]["result_set"]["data"] if not (r[0] == "Revolver Size" and r[1] == mstart(months[4]))]
        bad["revolver"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 a missing revolver month is refused", code == 1 and "no data for" in res.get("reason", "") and months[4] in res.get("reason", "") and "Revolver Size" in res.get("reason", ""), json.dumps(res)[:300])
        # a null amount is missing, never filled
        bad = copy.deepcopy(base)
        next(r for r in bad["revolver"]["result_set"]["data"] if r[0] == "Revolver Size" and r[1] == mstart(months[6]))[2] = ""
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 a revolver month with no amount is refused, not filled", code == 1 and "no data for" in res.get("reason", "") and months[6] in res.get("reason", ""), json.dumps(res)[:300])
        # an unknown METRIC
        bad = copy.deepcopy(base)
        bad["revolver"]["result_set"]["data"].append(["Letter of Credit", mstart(months[2]), "100"])
        bad["revolver"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["revolver"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 a revolver METRIC with no row to hold it is refused", code == 1 and "Letter of Credit" in res.get("reason", ""), json.dumps(res)[:300])
        # drawn above size
        bad = copy.deepcopy(base)
        next(r for r in bad["revolver_drawn"]["result_set"]["data"] if r[0] == mstart(months[7]))[1] = "26000000"
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("13 Drawn Revolver above Revolver Size is refused", code == 1 and "Liquidity | $ Drawn Revolver" in json.dumps(res.get("failed_rows", {})), json.dumps(res)[:300])
    finally:
        if a.keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    n_fail = RESULTS.count(False)
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} checks passed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
