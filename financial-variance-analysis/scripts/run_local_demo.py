#!/usr/bin/env python3
"""Smoke test of the whole local pipeline, with no Claude and no warehouse.

    python run_local_demo.py [--out outputs/local-demo] [--samples ../assets/sample-data]

For the finance sample workbook it: loads the data into SQLite, runs a headline
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


def finance(con):
    hl = q(con, """
SELECT CASE i.CHART_OF_ACCOUNT_KEY WHEN '-8' THEN 'Revenue' ELSE 'Adjusted EBITDA' END,
       SUM(i.MTD), SUM(i.BUDGET_MTD), SUM(i.MTD) - SUM(i.BUDGET_MTD), SUM(i.PY_MTD)
FROM INCOME_STATEMENT i JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD = 'Oct 2026' AND i.CHART_OF_ACCOUNT_KEY IN ('-8','-9')
GROUP BY i.CHART_OF_ACCOUNT_KEY ORDER BY i.CHART_OF_ACCOUNT_KEY DESC""")
    var = q(con, """
SELECT a.ACCOUNT_NAME, a.COA_MAPPING_L3, SUM(i.MTD), SUM(i.BUDGET_MTD), SUM(i.MTD) - SUM(i.BUDGET_MTD)
FROM INCOME_STATEMENT i JOIN ACCOUNT a ON a.CHART_OF_ACCOUNT_KEY = i.CHART_OF_ACCOUNT_KEY
JOIN PERIOD p ON p.ACCOUNTING_PERIOD_KEY = i.ACCOUNTING_PERIOD_KEY
WHERE p.PERIOD = 'Oct 2026' AND a.FINANCIAL_STATEMENT = 'P&L' AND a.CHART_OF_ACCOUNT_KEY NOT LIKE '-%'
GROUP BY a.ACCOUNT_NAME, a.COA_MAPPING_L3 ORDER BY ABS(SUM(i.MTD) - SUM(i.BUDGET_MTD)) DESC LIMIT 5""")
    by_name = {r[0]: r for r in hl}                 # look rows up by label, never by position
    rev, ebitda = by_name['Revenue'], by_name['Adjusted EBITDA']
    top = var[0]
    side = "adverse" if top[4] < 0 else "favourable"
    return {
        "meta": {"title": "Oct 2026 results and top variances (local demo)", "question": "How did we do vs budget, and what stands out?",
                 "period": "Oct 2026 vs budget", "as_of": "2026-10-31", "currency": "USD", "scale": "$ millions",
                 "sources": ["finance_sample.xlsx: INCOME_STATEMENT, ACCOUNT, PERIOD"], "data_mode": "local"},
        "headline": (f"Oct 2026 revenue was ${rev[1] / MM:.1f}mm against a budget of ${rev[2] / MM:.1f}mm, and Adjusted EBITDA was "
                     f"${ebitda[1] / MM:.1f}mm. {top[0]} is the largest account variance, ${abs(top[4]) / MM:.2f}mm {side} to budget."),
        "kpis": [
            {"label": "Revenue", "value": rev[1] / MM, "format": "currency_mm", "source": {"table": "headline", "column": "Actual ($mm)", "row": 0}},
            {"label": "Adjusted EBITDA", "value": ebitda[1] / MM, "format": "currency_mm", "source": {"table": "headline", "column": "Actual ($mm)", "row": 1}},
        ],
        "tables": [
            {"id": "headline", "title": "Revenue and Adjusted EBITDA, Oct 2026", "provenance": "derived",
             "columns": [{"name": "Measure", "type": "text"}, {"name": "Actual ($mm)", "type": "currency_mm"},
                         {"name": "Budget ($mm)", "type": "currency_mm"}, {"name": "Variance ($mm)", "type": "currency_mm"},
                         {"name": "Prior year ($mm)", "type": "currency_mm"}],
             "rows": [[r[0], r[1] / MM, r[2] / MM, r[3] / MM, r[4] / MM] for r in (rev, ebitda)],   # Revenue first, then EBITDA
             "sql": "SUM of INCOME_STATEMENT MTD, BUDGET_MTD, PY_MTD for keys -8 and -9, period Oct 2026"},
            {"id": "variances", "title": "Top 5 account variances vs budget", "provenance": "derived",
             "columns": [{"name": "Account", "type": "text"}, {"name": "Category", "type": "text"},
                         {"name": "Actual ($mm)", "type": "currency_mm"}, {"name": "Budget ($mm)", "type": "currency_mm"},
                         {"name": "Variance ($mm)", "type": "currency_mm"}],
             "rows": [[r[0], r[1], r[2] / MM, r[3] / MM, r[4] / MM] for r in var],
             "sql": "INCOME_STATEMENT joined to ACCOUNT and PERIOD, real accounts only, ordered by absolute variance"},
        ],
        "charts": [{"id": "fin_variance", "title": "Variance vs budget by account ($mm)", "type": "bar", "table": "variances",
                    "x": "Account", "y": ["Variance ($mm)"], "provenance": "derived"}],
        "findings": [{"text": f"{top[0]} actual was ${abs(top[2]) / MM:.2f}mm against a budget of ${abs(top[3]) / MM:.2f}mm.", "evidence": "established"}],
        "caveats": ["Synthetic sample workbook. Sign convention in the sample: expenses negative, so a negative variance is adverse."],
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
    books = [os.path.join(a.samples, "finance_sample.xlsx")]
    if not all(os.path.exists(b) for b in books):
        print("Sample workbooks missing; generating them.")
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
    for name, fn in (("finance", finance),):
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
