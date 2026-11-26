#!/usr/bin/env python3
"""Smoke test of the whole local pipeline, with no Claude and no warehouse.

    python run_local_demo.py [--out outputs/local-demo] [--samples ../assets/sample-data]

On the GTM sample workbook it: loads the data into SQLite, runs a headline
analysis, builds a result bundle, validates it, checks a chat-style answer against it, builds the
Excel file, HTML dashboard and PNG charts, then re-reads those files and verifies them.

It does what Claude is instructed to do (SKILL.md, "One set of numbers"), scripted, so you can
confirm the tooling works on your machine before testing the skill itself. Exit 0 = passed.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bundle as B                       # noqa: E402
import local_data as L                   # noqa: E402

MM = 1e6


def q(con, sql):
    return con.execute(sql).fetchall()


def gtm(con):
    meas = q(con, """
SELECT BOOKING_METRIC,
  SUM(CASE WHEN BOOKING_DATE BETWEEN '2026-02-01' AND '2026-10-31' THEN BOOKING_ACV_USD END),
  SUM(CASE WHEN BOOKING_DATE BETWEEN '2025-02-01' AND '2025-10-31' THEN BOOKING_ACV_USD END)
FROM BOOKING_LINES GROUP BY BOOKING_METRIC ORDER BY BOOKING_METRIC""")
    tot_y = sum(r[1] for r in meas)
    tot_p = sum(r[2] for r in meas)
    cust = q(con, """
SELECT ACCOUNT_NAME, SUM(BOOKING_ACV_USD) FROM BOOKING_LINES
WHERE BOOKING_DATE BETWEEN '2026-10-01' AND '2026-10-31' AND ACCOUNT_NAME IS NOT NULL GROUP BY ACCOUNT_NAME ORDER BY SUM(BOOKING_ACV_USD) DESC LIMIT 5""")
    oct_total = q(con, "SELECT SUM(BOOKING_ACV_USD) FROM BOOKING_LINES WHERE BOOKING_DATE BETWEEN '2026-10-01' AND '2026-10-31' AND ACCOUNT_NAME IS NOT NULL")[0][0]
    rows = [[r[0], r[1] / MM, r[2] / MM, r[1] / r[2] - 1] for r in meas]
    rows.append(["Total bookings", tot_y / MM, tot_p / MM, tot_y / tot_p - 1])
    top2 = (cust[0][1] + cust[1][1]) / oct_total
    return {
        "meta": {"title": "Bookings fiscal YTD vs prior year (local demo)", "question": "How are bookings tracking, and who drove October?",
                 "period": "FY2027 YTD (Feb-Oct 2026) vs FY2026 YTD (Feb-Oct 2025)", "as_of": "2026-10-31", "currency": "USD", "scale": "$ millions",
                 "sources": ["gtm_sample.xlsx: BOOKING_LINES"], "data_mode": "local"},
        "headline": (f"Bookings are ${tot_y / MM:.1f}mn fiscal year to date, {abs(tot_y / tot_p - 1) * 100:.1f}% "
                     f"{'above' if tot_y >= tot_p else 'below'} the same period last year. {cust[0][0]} and {cust[1][0]} "
                     f"account for {top2 * 100:.0f}% of October recurring bookings."),
        "kpis": [{"label": "Total bookings fiscal YTD", "value": tot_y / MM, "format": "currency_mm", "delta": tot_y / tot_p - 1,
                  "delta_format": "percent", "note": "vs prior-year YTD", "source": {"table": "by_measure", "column": "YTD ($mn)", "row": len(rows) - 1}},
                 {"label": "Top two customers, share of October recurring", "value": top2, "format": "percent",
                  "source": {"table": "concentration", "column": "Share", "row": 0}}],
        "tables": [
            {"id": "by_measure", "title": "Bookings by measure, fiscal YTD vs prior year", "provenance": "derived",
             "columns": [{"name": "Measure", "type": "text"}, {"name": "YTD ($mn)", "type": "currency_mm"},
                         {"name": "Prior-year YTD ($mn)", "type": "currency_mm"}, {"name": "Change", "type": "percent"}],
             "rows": rows, "sql": "SUM(BOOKING_ACV_USD) on BOOKING_LINES by BOOKING_METRIC over fiscal YTD (from 1 February) and the prior-year fiscal YTD"},
            {"id": "oct_customers", "title": "Top 5 customers, Oct 2026 recurring bookings", "provenance": "derived",
             "columns": [{"name": "Customer", "type": "text"}, {"name": "Bookings ($mn)", "type": "currency_mm", "total": "sum"},
                         {"name": "Share of October", "type": "percent"}],
             "rows": [[r[0], r[1] / MM, r[1] / oct_total] for r in cust],
             "sql": "SUM(BOOKING_ACV_USD) on BOOKING_LINES by ACCOUNT_NAME (recurring lines) for Oct 2026"},
            {"id": "concentration", "title": "October concentration", "provenance": "derived",
             "columns": [{"name": "Measure", "type": "text"}, {"name": "Share", "type": "percent"}],
             "rows": [["Top two customers' share of October recurring bookings", top2]],
             "sql": "(first two customers' October bookings) / (October bookings with an account)"},
        ],
        "charts": [{"id": "gtm_measure", "title": "Bookings by measure ($mn)", "type": "column", "table": "by_measure", "x": "Measure",
                    "y": ["YTD ($mn)", "Prior-year YTD ($mn)"], "provenance": "derived"}],
        "findings": [{"text": f"The top two customers' share of October bookings is {top2 * 100:.0f}%.", "evidence": "established"}],
        "caveats": ["Synthetic sample workbook. October bookings are concentrated by design.",
                    "Fiscal year 1 February to 31 January (FY2027 = Feb 2026 to Jan 2027)."],
    }


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join("outputs", "local-demo"))
    ap.add_argument("--samples", default=os.path.join(HERE, "..", "assets", "sample-data"))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    books = [os.path.join(a.samples, f"{n}_sample.xlsx") for n in ("gtm",)]
    if not all(os.path.exists(b) for b in books):
        print("Sample workbook missing; generating it.")
        subprocess.run([sys.executable, os.path.join(HERE, "make_sample_data.py"), a.samples], check=True)
    db = os.path.join(out, "local.db")

    class NS:
        pass
    ns = NS()
    ns.workbooks, ns.db = books, db
    print("== Load")
    L.cmd_load(ns)
    con = sqlite3.connect(db)

    failures = 0
    summary = []
    for name, fn in (("gtm", gtm),):
        print(f"\n== {name}")
        b = fn(con)
        bpath = os.path.join(out, f"{name}.bundle.json")
        json.dump(b, open(bpath, "w", encoding="utf-8"), indent=1)
        errs = B.validate(b)
        if errs:
            failures += 1
            print("  bundle INVALID:\n   - " + "\n   - ".join(errs))
            summary.append((name, "-", "bundle invalid"))
            continue
        fp = B.fingerprint(b)
        print(f"  bundle valid, Bundle ID {fp}")
        answer = b["headline"] + "\n\n" + "\n".join(f["text"] for f in b["findings"]) + f"\n\nBundle ID: {fp}\n"
        apath = os.path.join(out, f"{name}.answer.md")
        open(apath, "w", encoding="utf-8").write(answer)
        bad = [m for s, m in B.answer_problems(b, answer) if s == "error"]
        print("  chat answer check:", "passed" if not bad else "FAILED")
        for m in bad:
            print("   -", m)
        xl, ht, ch = (os.path.join(out, f"{name}.xlsx"), os.path.join(out, f"{name}.html"), os.path.join(out, f"{name}-charts"))
        steps = [[sys.executable, os.path.join(HERE, "export_xlsx.py"), bpath, xl],
                 [sys.executable, os.path.join(HERE, "build_dashboard.py"), bpath, ht],
                 [sys.executable, os.path.join(HERE, "make_chart.py"), bpath, "--outdir", ch],
                 [sys.executable, os.path.join(HERE, "verify_outputs.py"), bpath, "--xlsx", xl, "--html", ht, "--charts", ch]]
        ok = not bad
        for cmd in steps:
            rc, txt = run(cmd)
            print("  " + os.path.basename(cmd[1]) + ":", txt.splitlines()[-1] if txt else rc)
            if rc != 0:
                ok = False
                print("\n".join("    " + l for l in txt.splitlines()[:12]))
        failures += 0 if ok else 1
        summary.append((name, fp, "PASS" if ok else "FAIL"))

    print("\n== Result")
    for name, fp, st in summary:
        print(f"  {name:<8} Bundle ID {fp:<12} {st}")
    print(f"\nFiles are in {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
