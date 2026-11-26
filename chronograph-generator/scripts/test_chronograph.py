#!/usr/bin/env python3
"""Prove the CFO Chronograph tooling on SYNTHETIC data (never real figures): the happy path and every refusal.

    python test_chronograph.py [--excel]      # --excel also open-tests the output in a hidden Excel (Windows)

Builds synthetic sql-exec results for all ten sources shaped like Yes Energy's views (unsigned P&L with a sign
multiplier, a fully labelled cash flow, New / Churn / Upsell / Downsell / FX ARR, bookings split into ARR New and ARR
Upsell, no coverage metric), runs
chronograph_queries.py and build_chronograph.py in a temporary folder, and checks:
  1  a consistent extract is WRITTEN, every gate passes, the file is clean, labelled SYNTHETIC, formulas kept;
     ARR FX lands in the Transactional downsell row (-1 x FX); rows with no Yes Energy source stay blank
  2  a P&L line that no longer ties to the governed revenue is REFUSED
  3  a balance sheet that does not balance is REFUSED (the Yes Energy view balances)
  4  a month missing from the ARR bridge is REFUSED
  5  a P&L line with activity that no template row takes is REFUSED
  6  a cut-off result (declares more rows than it holds) is REFUSED
  7  a template that differs from the pinned one is REFUSED
  8  check_workbook flags a workbook with a stale view, a broken name and an external link
  9  an as-of month that has not closed is REFUSED and the last closed month is named
 10  a cash-flow row without a label that no rule places is REFUSED
 11  a P&L line without a sign multiplier is REFUSED
 12  account exclusion is opt-in: none by default; given IDs filter bookings and pipeline only (null-safe),
     leave the finance and ARR queries unchanged, pass the guard; a malformed ID is REFUSED; the build reports the exclusion
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
ORDER_NAMES = ["pl", "pl_governed", "bs", "cf", "arr", "customers", "bookings", "pipeline", "hosting", "revolver"]


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
    """Nine results shaped like Yes Energy's views: P&L unsigned with P_AND_L_MULTIPLIER and tied to governed; the cash flow
    labels every row (Total Non-Cash Items, Effect of Exchange Rate on Cash); the balance sheet balances; the ARR bridge
    uses New / Churn / Upsell / Downsell / FX; bookings split ARR New / ARR Upsell; weighted pipeline is 0 and the first
    months have no snapshot."""
    pl, gov, bs, cf, arr, cust, bkg, ppl, host, revl = [], [], [], [], [], [], [], [], [], []
    cash, arr_end, logos = 5_000_000.0, 60_000_000.0, 4000
    for i, mo in enumerate(months):
        g = 1 + 0.01 * i
        rev = {("Recurring Revenue", "SaaS - Subscription", "MRR - Licenses Revenue"): 4_000_000 * g,
               ("Recurring Revenue", "SaaS - Subscription", "MRR - Self Serve Monthly"): 1_500_000 * g,
               ("Non-Recurring Revenue", "One-time Services", "Rev - Professional Service"): 350_000.0}
        cos = {("Recurring COGs", "SysOps", None): 600_000 * g, ("Recurring COGs", "Customer Support", None): 400_000.0,
               ("Non-Recurring COGs", "Professional Services", None): 150_000.0}
        opex = {("Fully loaded S&M Expense", "S&M Expense", "Sales Expense"): 700_000.0, ("Fully loaded S&M Expense", "S&M Expense", "Marketing Expense"): 300_000.0,
                ("Fully loaded S&M Expense", "S&M Expense", "Training"): 120_000.0,
                ("Fully loaded R&D", "R&D", "Engineering Expense"): 800_000.0, ("Fully loaded R&D", "R&D", "Product Expense"): 250_000.0,
                ("Fully loaded R&D", "R&D", "Other R&D Expense"): 60_000.0,
                ("Total G&A", "Finance Department", None): 400_000.0, ("Total G&A", "HR Department", None): 100_000.0,
                ("Total G&A", "IT Department", None): 150_000.0, ("Total G&A", "Other G&A Spend", None): 90_000.0}
        nonop = {("Depreciation & Amortization", "Depreciation & Amortization", None): 900_000.0,
                 ("Interest Expense", "Interest Expense", None): 500_000.0, ("Income Taxes", "Income Taxes", None): 50_000.0,
                 ("Other Non-Operating Income & Expense", "Transaction Costs", None): 20_000.0,
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
        # cash flow: NI + D&A add-back (Total Non-Cash Items) + working capital + capex + debt; FX on cash
        da, wc, capex, debt, fx = 900_000.0, 400_000.0, -300_000.0, -100_000.0, 5_000.0
        beg = cash
        net = ni + da + wc + capex + debt
        cash = beg + net + fx
        cf += [[mstart(mo), "Cash from Operations", "Income from Operations", "Net Income", "Net Income", "Net Income", ni],
               [mstart(mo), "Cash from Operations", "Income from Operations", "Total Non-Cash Items", "Assets", "Goodwill & Intangibles", da],
               [mstart(mo), "Cash from Operations", "Change in Working Capital", "Accounts Receivable", "Assets", "Accounts Receivable", wc],
               [mstart(mo), "Cash from Investing", "Capital Expenditures", "Capital Expenditures", "Assets", "Net Fixed Assets", capex],
               [mstart(mo), "Cash from Financing", "Change in Debt", "Señor Term Loan", "Total Liabilities & Share Holder Equity", "Non-Current Liabilities", debt],
               [mstart(mo), "FX Change", "Effect of Exchange Rate on Cash", "Effect of Exchange Rate on Cash", "Total Liabilities & Share Holder Equity", "Total Equity", fx],
               [mstart(mo), "Beginning Cash", "Beginning Cash", "Beginning Cash", "", "", beg],
               [mstart(mo), "Ending Cash", "Ending Cash", "Ending Cash", "", "", cash],
               [mstart(mo), "Net Cash Flow", "Net Change in Cash", "Net Cash Flow", "", "", net],
               [mstart(mo), "Cash before Financing", "Cash before Financing", "Cash before Financing", "", "", ni + da + wc + capex]]
        ar, gw, fixed, other_nca = 8_000_000.0, 150_000_000.0, 400_000.0, 2_000_000.0
        ap, ap2, dr, other_cl, debt_b = 300_000.0, 700_000.0, 20_000_000.0, 250_000.0, 80_000_000.0
        assets = cash + ar + gw + fixed + other_nca
        bs += [[mstart(mo), "Assets", "Current Assets", "Cash & Equivalents", "Yes Energy PNC Operating 4132", cash],
               [mstart(mo), "Assets", "Current Assets", "Accounts Receivable", "Accounts Receivable", ar],
               [mstart(mo), "Assets", "Non-Current Assets", "Goodwill & Intangibles", "Goodwill & Intangibles", gw],
               [mstart(mo), "Assets", "Non-Current Assets", "Net Fixed Assets", "Fixed Assets", fixed],
               [mstart(mo), "Assets", "Non-Current Assets", "Other Non-Current Assets", "Investment in Subsidiary", other_nca],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Accounts Payable", ap],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Accrued Expenses", ap2],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Deferred Revenue", dr],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Current Liabilities", "Other Current Liabilities", other_cl],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Liabilities", "Non-Current Liabilities", "Senior Debt", debt_b],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Equity", "Total Equity", "Retained earnings", -10_000_000.0],
               [mstart(mo), "Total Liabilities & Share Holder Equity", "Equity", "Total Equity", "Shareholder's Equity", assets - ap - ap2 - dr - other_cl - debt_b + 10_000_000.0]]
        new, churn, up, down, fxa = 500_000.0, -200_000.0, 700_000.0, -300_000.0, 40_000.0
        b = arr_end
        gdr = b + churn + down
        ndr = gdr + up
        arr_end = ndr + new + fxa                                        # the view adds FX after NDR
        ltm_b = b * 0.92
        for cat, v, l in (("Beginning ARR", b, ltm_b), ("New", new, new * 12), ("Churn", churn, churn * 12), ("Upsell", up, up * 12),
                          ("Downsell", down, down * 12), ("FX", fxa, fxa * 12), ("Gross Dollar Retention", gdr, ltm_b + churn * 12 + down * 12),
                          ("Net Dollar Retention", ndr, ltm_b + (churn + down + up) * 12), ("Ending ARR", arr_end, arr_end)):
            arr.append([mend(mo), cat, v, l])
        bl, nl, ll = logos, 90, -80
        logos = bl + nl + ll
        cust += [[mend(mo), "Beginning Customers", bl], [mend(mo), "New Customers", nl], [mend(mo), "Lost Customers", ll], [mend(mo), "Ending Customers", logos]]
        bkg.append([mend(mo), 400_000.0, 600_000.0, 1_000_000.0, 200_000.0, 1_200_000.0])
        # hosting accounts: unsigned like the P&L, a cost (-1); COGS where L3 = Cost of Sales, R&D for the rest
        host += [[mstart(mo), "COGS", -1.0, 600_000.0], [mstart(mo), "R&D", -1.0, 5_000.0]]
        revl += [[mstart(mo), "Revolver Size", 5_000_000.0], [mstart(mo), "Drawn Revolver", 1_000_000.0 if i % 2 else 0.0], [mstart(mo), "Principal Payments", 100_000.0]]
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
        "bookings": result(["AS_OF_DATE", "ARR_NEW_MTD", "ARR_UPSELL_MTD", "RECURRING_BOOKINGS_MTD", "NON_RECURRING_BOOKINGS_MTD", "TOTAL_BOOKINGS_MTD"], bkg, "synthetic-bkg"),
        "pipeline": result(["AS_OF_DATE", "OPEN_PIPELINE_VALUE_MTD", "WEIGHTED_PIPELINE_VALUE_MTD"], ppl, "synthetic-ppl"),
        "hosting": result(["PERIOD_START_DATE", "BUCKET", "P_AND_L_MULTIPLIER", "TOTAL_MTD"], host, "synthetic-host"),
        "revolver": result(["METRIC", "MONTH_START_DATE", "AMOUNT"], [[m_, d_, a_] for d_, m_, a_ in revl], "synthetic-rev"),
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
            step("1 Ending Cash includes FX, Beginning Cash chains to the prior month",
                 ws.cell(rows["Ending Cash"], 3).value == f"=C{rows['Net Cash Flow']}+C{rows['FX Change']}+C{rows['Beginning Cash']}"
                 and ws.cell(rows["Beginning Cash"], 4).value == f"=C{rows['Ending Cash']}")
            step("1 headcount is blank, not 0; the revolver is read from REVOLVER (a stored 0 written as 0)", ws.cell(rows["COGS HC Total"], 3).value is None and ws.cell(rows["$ Drawn Revolver"], 3).value == 0 and ws.cell(rows["$ Revolver Size"], 4).value == 5000)
            step("1 recurring bookings split into ARR New and ARR Upsell; Recurring Services is blank (the view has none)",
                 ws.cell(rows["Bookings - ARR (New)"], 3).value == 400 and ws.cell(rows["Bookings - ARR (Upsell)"], 3).value == 600
                 and ws.cell(rows["Bookings - Recurring Services"], 3).value is None)
            step("1 Cross-Sell and Price Increase are blank; FX sits in the Transactional row as -1 x FX; Churn and Downsell are filled",
                 all(ws.cell(rows[k], 3).value is None for k in ("(+) Cross-Sell", "(+) Price Increase"))
                 and ws.cell(rows["(-) Downsell/Contraction (Transactional)"], 3).value == -40
                 and ws.cell(rows["(-) Churn/Lost"], 3).value == 200 and ws.cell(rows["(-) Downsell/Contraction (Subscription)"], 3).value == 300
                 and ws.cell(rows["(-) Lost"], 3).value == 80)
            step("1 the cash flow's Total Non-Cash Items and FX Change are filled",
                 ws.cell(rows["Total Non-Cash Items"], 3).value == 900 and ws.cell(rows["FX Change"], 3).value == 5,
                 f"{ws.cell(rows['Total Non-Cash Items'], 3).value} / {ws.cell(rows['FX Change'], 3).value}")
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
            step("1 balance sheet: AP and Accrued Expenses from COA L4, Equity from COA L2, remainders for the Other rows",
                 ws.cell(rows["Accounts Payable"], 3).value == 300 and ws.cell(rows["Accrued Expenses"], 3).value == 700 and ws.cell(rows["Other Current Liabilities"], 3).value == 250
                 and ws.cell(rows["Net Fixed Assets"], 3).value == 400 and ws.cell(rows["Other Non-Current Assets"], 3).value == 2_000)
            kinds = {c["item"] for c in res.get("confirm_at_source", [])}
            step("1 the hand-over lists what to confirm at source (pipeline gap, weighted pipeline)",
                 {"Pipeline", "Pipeline | Weighted Pipeline"} <= kinds, json.dumps(sorted(kinds)))
            step("1 hosting rows read the hosting accounts, entered positive (COGs and R&D buckets); Net Capitalized Software is blank",
                 ws.cell(rows["Hosting/Cloud Costs (COGs)"], 3).value == 600 and ws.cell(rows["Hosting/Cloud Costs (R&D)"], 3).value == 5
                 and ws.cell(rows["Net Capitalized Software"], 3).value is None,
                 f"{ws.cell(rows['Hosting/Cloud Costs (COGs)'], 3).value} / {ws.cell(rows['Hosting/Cloud Costs (R&D)'], 3).value}")
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

        # 3 balance sheet does not balance: refused (the Yes Energy view balances, so A = L + E is a blocking gate)
        bad = copy.deepcopy(base)
        eq = next(r for r in bad["bs"]["result_set"]["data"] if r[4] == "Shareholder's Equity")
        eq[-1] = str(float(eq[-1]) - 5000)
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("3 a balance sheet that does not balance is refused", code == 1 and "Balance Sheet | A = L + E" in json.dumps(res.get("failed_rows", {})), json.dumps(res)[:300])

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

        # 10 a cash-flow row without a label that no rule places
        bad = copy.deepcopy(base)
        bad["cf"]["result_set"]["data"].append([mstart(months[3]), "", "", "", "Assets", "Suspense", "1234.000000"])
        bad["cf"]["result_set"]["resultSetMetaData"]["numRows"] = len(bad["cf"]["result_set"]["data"])
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("10 an unlabelled cash-flow row no rule places is refused", code == 1 and "Assets > Suspense" in json.dumps(res.get("unlabelled", [])), json.dumps(res)[:300])

        # 11 a P&L line without a sign multiplier
        bad = copy.deepcopy(base)
        bad["pl"]["result_set"]["data"][0][6] = ""
        write_raw(work, bad)
        code, res = run("build_chronograph.py", "--work", work, "--out", out, "--excel", "off")
        step("11 a P&L line without a sign multiplier is refused", code == 1 and "P_AND_L_MULTIPLIER" in res.get("reason", ""), json.dumps(res)[:300])

        # 12 account exclusion: opt-in, null-safe, on bookings / pipeline only (ARR has no Salesforce account)
        import sql_guard
        default_sql = {n: open(os.path.join(work, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ("pl", "arr", "customers", "bookings", "pipeline")}
        step("12 without --exclude-accounts no query filters accounts and the manifest lists none",
             not any("ACCOUNT_ID" in q for q in default_sql.values()) and man["scope"].get("exclude_accounts") == [])
        ids = ["0013r00002fpJz4AAE", "001UW000011EKiZYAW"]
        idfile = os.path.join(tmp, "ids.txt")
        with open(idfile, "w", encoding="utf-8") as fh:
            fh.write("# accounts to leave out\n0010Z000023EerWQAS\n0013r00002fpJz4AAE  # duplicate of the flag\n")
        w2 = os.path.join(tmp, "work_excl")
        code, res = run("chronograph_queries.py", "--as-of", as_of, "--work", w2, "--exclude-accounts", ",".join(ids), "--exclude-accounts-file", idfile)
        man2 = json.load(open(os.path.join(w2, "queries", "manifest.json"), encoding="utf-8")) if code == 0 else {}
        want = ids + ["0010Z000023EerWQAS"]
        step("12 IDs from the flag and a file are merged, de-duplicated and recorded in the manifest",
             code == 0 and res.get("excluded_accounts") == 3 and man2.get("scope", {}).get("exclude_accounts") == want, json.dumps(res)[:300])
        q2 = {n: open(os.path.join(w2, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ORDER_NAMES}
        clause = lambda col: f"AND ({col} IS NULL OR {col} NOT IN ('" + "', '".join(want) + "'))"
        step("12 bookings and pipeline filter DIM_ACCOUNT.ACCOUNT_ID, null-safe; ARR and customers are not filtered",
             not any("ACCOUNT_ID" in q2[n] for n in ("arr", "customers"))
             and all(clause("DIM_ACCOUNT.ACCOUNT_ID") in q2[n] for n in ("bookings", "pipeline")))
        step("12 the finance and ARR queries are unchanged by an account exclusion",
             all(q2[n] == open(os.path.join(work, "queries", f"{n}.sql"), encoding="utf-8").read() for n in ("pl", "pl_governed", "bs", "cf", "arr", "customers")))
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
            step("12 the document properties name the excluded accounts", "Excludes 3 Salesforce account(s)" in desc and want[0] in desc, desc[:200])
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
