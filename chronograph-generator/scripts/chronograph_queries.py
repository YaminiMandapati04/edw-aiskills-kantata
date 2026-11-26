#!/usr/bin/env python3
"""Write the ten fixed extract queries for one CFO Chronograph refresh, guard-check them and record a manifest.

    python chronograph_queries.py --as-of 2026-09 [--months 24] [--work work/]
                                  [--exclude-accounts 0013r00002fpJz4AAE,001UW000011EKiZYAW] [--exclude-accounts-file ids.txt]

The refresh runs these statements and nothing else: one query per source, monthly, consolidated over the scope in
config/scope.json. Each is written to <work>/queries/<name>.sql after sql_guard.py accepts it; run each file's text
verbatim with the Snowflake sql-exec tool and save the full result to <work>/raw/<name>.json (see references/extract.md).

  pl           FINANCE_ANALYTICS  INCOME_STATEMENT.TOTAL_MTD by month x COA L2..L6 x P_AND_L_MULTIPLIER (P&L, roll-up keys out;
                                  the view stores values unsigned, the multiplier gives each account its sign)
  pl_governed  FINANCE_ANALYTICS  REVENUE_MTD, ADJUSTED_EBITDA_MTD, NET_INCOME_MTD by month (the P&L tie-out)
  bs           FINANCE_ANALYTICS  BALANCE_SHEET.ENDING_BALANCE_CONVERTED by month x COA L1..L4
  cf           FINANCE_ANALYTICS  CASH_FLOW.TOTAL_MTD by month x CASH_FLOW_L1..L3 x COA L1 / L3 (the COA levels classify the
                                  rows the view leaves without a cash-flow label: group adjustments and the translation reserve)
  arr          ARR_ANALYTICS      ARR_BRIDGE TOTAL_MTD and TOTAL_LTM by month-end x CATEGORY (USD as the view stores it)
  customers    ARR_ANALYTICS      CUSTOMER_BRIDGE.TOTAL_LTM by month-end x CATEGORY (LTM: each category measured against the
                                  closing customer count 12 months back; Beginning Customers is that count)
  bookings     GTM_ANALYTICS      BOOKINGS_OVERVIEW recurring, non-recurring and total MTD bookings by month-end
  pipeline     GTM_ANALYTICS      PIPELINE_OVERVIEW open and weighted pipeline by month-end (the view has no coverage ratio)
  revolver     FINANCE_ANALYTICS  REVOLVER.REVOLVER_AMOUNT by METRIC x month start (Revolver Size), USD. Finance's manual table
                                  (PROD_DB.MANUAL.REVOLVER): no subsidiary dimension and no relationship to any other table, so it
                                  never carries a subsidiary filter. METRIC values are separate measures, never added.
  revolver_drawn FINANCE_ANALYTICS BALANCE_SHEET.ENDING_BALANCE_CONVERTED by month for ACCOUNT_NUMBER 280360 (config/scope.json
                                  revolver_drawn_account): Drawn Revolver, the balance sheet MTD value of the revolver account
Account exclusion: the internal test accounts in config/scope.json exclude_accounts are always left out; Salesforce account
IDs the user names (--exclude-accounts / --exclude-accounts-file) are added on top. They are filtered out of arr and customers
(CUSTOMER.ACCOUNT_ID) and of bookings and pipeline (DIM_ACCOUNT.ACCOUNT_ID), by ID only, never by name. Rows with no account
(NetSuite non-recurring bookings) are kept. FINANCE_ANALYTICS has no Salesforce account, so the P&L, balance
sheet and cash flow always cover every customer. Each ID must be an 18-character Salesforce ID (the views store that form).
Exit codes: 0 written, 1 refused.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ARR_BASIS = "month-to-date bridge, USD as ARR_ANALYTICS stores it"     # the view has one basis (no actual-rate metrics)

# the columns each saved result must carry (the build refuses anything else)
EXPECTED_COLUMNS = {
    "pl": ["PERIOD_START_DATE", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "COA_MAPPING_L5", "COA_MAPPING_L6", "P_AND_L_MULTIPLIER", "TOTAL_MTD"],
    "pl_governed": ["PERIOD_START_DATE", "REVENUE_MTD", "ADJUSTED_EBITDA_MTD", "NET_INCOME_MTD"],
    "bs": ["PERIOD_START_DATE", "COA_MAPPING_L1", "COA_MAPPING_L2", "COA_MAPPING_L3", "COA_MAPPING_L4", "ENDING_BALANCE_CONVERTED"],
    "cf": ["PERIOD_START_DATE", "CASH_FLOW_L1", "CASH_FLOW_L2", "CASH_FLOW_L3", "COA_MAPPING_L1", "COA_MAPPING_L3", "TOTAL_MTD"],
    "arr": ["MONTH_END_DATE", "CATEGORY", "TOTAL_MTD", "TOTAL_LTM"],
    "customers": ["MONTH_END_DATE", "CATEGORY", "TOTAL_LTM"],
    "bookings": ["AS_OF_DATE", "RECURRING_BOOKINGS_MTD", "NON_RECURRING_BOOKINGS_MTD", "TOTAL_BOOKINGS_MTD"],
    "pipeline": ["AS_OF_DATE", "OPEN_PIPELINE_VALUE_MTD", "WEIGHTED_PIPELINE_VALUE_MTD"],
    "revolver": ["METRIC", "MONTH_START_DATE", "REVOLVER_AMOUNT"],
    "revolver_drawn": ["PERIOD_START_DATE", "ENDING_BALANCE_CONVERTED"],
}
ORDER = list(EXPECTED_COLUMNS)


def refuse(msg, **extra):
    print(json.dumps({"status": "REFUSED", "reason": msg, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def month_start(label):
    y, m = int(label[:4]), int(label[5:7])
    return dt.date(y, m, 1)


def month_end(d):
    return dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(days=1)


def add_months(d, n):
    k = d.year * 12 + d.month - 1 + n
    return dt.date(k // 12, k % 12 + 1, 1)


def sql_list(values):
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


SF_ID = re.compile(r"^[A-Za-z0-9]{18}$")


def parse_accounts(values, files):
    """The Salesforce account IDs to exclude, from --exclude-accounts (comma or space separated, repeatable) and
    --exclude-accounts-file (one or more per line; '#' starts a comment). Duplicates dropped, order kept."""
    tokens = []
    for v in values or []:
        tokens += re.split(r"[\s,;]+", v)
    for f in files or []:
        try:
            with open(f, encoding="utf-8-sig") as fh:
                for line in fh:
                    tokens += re.split(r"[\s,;]+", line.split("#", 1)[0])
        except OSError as e:
            refuse(f"cannot read --exclude-accounts-file {f}: {e.strerror}")
    ids, bad = [], []
    for t in (t.strip().strip("'\"") for t in tokens):
        if not t:
            continue
        if not SF_ID.match(t):
            bad.append(t)
        elif t not in ids:
            ids.append(t)
    if bad:
        refuse("--exclude-accounts takes 18-character Salesforce account IDs (letters and digits only); these are not: "
               + ", ".join(bad[:10]) + (" ..." if len(bad) > 10 else ""),
               hint="a 15-character ID needs its 3-character suffix: copy the 18-character ID from Salesforce")
    return ids


def account_filter(column, accounts):
    """Null-safe NOT IN: keeps rows with no account (a bare NOT IN would drop them)."""
    if not accounts:
        return ""
    return f"\n    AND ({column} IS NULL OR {column} NOT IN ({sql_list(accounts)}))"


def expected_columns(name):
    return list(EXPECTED_COLUMNS[name])


def build_queries(view_db, view_schema, first, last, exclusions, rollup_keys, l6_kept, accounts=(), drawn_account="280360"):
    fq = lambda v: f"{view_db}.{view_schema}.{v}"
    fs, ls = first.isoformat(), last.isoformat()
    fe, le = month_end(first).isoformat(), month_end(last).isoformat()
    excl_fin = f"\n    AND SUBSIDIARY.SUBSIDIARY_NAME NOT IN ({sql_list(exclusions)})" if exclusions else ""
    excl_bkg = f"\n    AND BOOKINGS_OVERVIEW.SUBSIDIARY_NAME NOT IN ({sql_list(exclusions)})" if exclusions else ""
    keys = sql_list(rollup_keys)
    acct_arr = account_filter("CUSTOMER.ACCOUNT_ID", accounts)          # ARR_ANALYTICS: bridge -> CUSTOMER
    acct_gtm = account_filter("DIM_ACCOUNT.ACCOUNT_ID", accounts)       # GTM_ANALYTICS: overview -> DIM_ACCOUNT
    return {
        "pl": f"""SELECT PERIOD_START_DATE, COA_MAPPING_L2, COA_MAPPING_L3, COA_MAPPING_L4, COA_MAPPING_L5,
       IFF(COA_MAPPING_L5 IN ({sql_list(l6_kept)}), COA_MAPPING_L6, NULL) AS COA_MAPPING_L6,
       P_AND_L_MULTIPLIER, SUM(TOTAL_MTD) AS TOTAL_MTD
FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS PERIOD.PERIOD_START_DATE, ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3, ACCOUNT.COA_MAPPING_L4, ACCOUNT.COA_MAPPING_L5, ACCOUNT.COA_MAPPING_L6,
             ACCOUNT.P_AND_L_MULTIPLIER
  METRICS    INCOME_STATEMENT.TOTAL_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '{fs}' AND '{ls}'
    AND ACCOUNT.FINANCIAL_STATEMENT = 'P&L'
    AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ({keys}){excl_fin}
)
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY 1, 2, 3, 4, 5, 6, 7""",
        "pl_governed": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS PERIOD.PERIOD_START_DATE
  METRICS    INCOME_STATEMENT.REVENUE_MTD, INCOME_STATEMENT.ADJUSTED_EBITDA_MTD, INCOME_STATEMENT.NET_INCOME_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '{fs}' AND '{ls}'{excl_fin}
)
ORDER BY 1""",
        "bs": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS PERIOD.PERIOD_START_DATE, ACCOUNT.COA_MAPPING_L1, ACCOUNT.COA_MAPPING_L2, ACCOUNT.COA_MAPPING_L3, ACCOUNT.COA_MAPPING_L4
  METRICS    BALANCE_SHEET.ENDING_BALANCE_CONVERTED
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '{fs}' AND '{ls}'
    AND ACCOUNT.FINANCIAL_STATEMENT = 'BS'
    AND ACCOUNT.CHART_OF_ACCOUNT_KEY NOT IN ({keys}){excl_fin}
)
ORDER BY 1, 2, 3, 4, 5""",
        "cf": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS PERIOD.PERIOD_START_DATE, ACCOUNT.CASH_FLOW_L1, ACCOUNT.CASH_FLOW_L2, ACCOUNT.CASH_FLOW_L3, ACCOUNT.COA_MAPPING_L1, ACCOUNT.COA_MAPPING_L3
  METRICS    CASH_FLOW.TOTAL_MTD
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '{fs}' AND '{ls}'{excl_fin}
)
ORDER BY 1, 2, 3, 4, 5, 6""",
        "arr": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('ARR_ANALYTICS')}
  DIMENSIONS ARR_BRIDGE.MONTH_END_DATE, ARR_BRIDGE.CATEGORY
  METRICS    ARR_BRIDGE.TOTAL_MTD, ARR_BRIDGE.TOTAL_LTM
  WHERE      ARR_BRIDGE.MONTH_END_DATE BETWEEN '{fe}' AND '{le}'{acct_arr}
)
ORDER BY 1, 2""",
        "customers": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('ARR_ANALYTICS')}
  DIMENSIONS CUSTOMER_BRIDGE.MONTH_END_DATE, CUSTOMER_BRIDGE.CATEGORY
  METRICS    CUSTOMER_BRIDGE.TOTAL_LTM
  WHERE      CUSTOMER_BRIDGE.MONTH_END_DATE BETWEEN '{fe}' AND '{le}'{acct_arr}
)
ORDER BY 1, 2""",
        "bookings": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('GTM_ANALYTICS')}
  DIMENSIONS BOOKINGS_OVERVIEW.AS_OF_DATE
  METRICS    BOOKINGS_OVERVIEW.RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.NON_RECURRING_BOOKINGS_MTD, BOOKINGS_OVERVIEW.TOTAL_BOOKINGS_MTD
  WHERE      BOOKINGS_OVERVIEW.AS_OF_DATE BETWEEN '{fe}' AND '{le}'{excl_bkg}{acct_gtm}
)
ORDER BY 1""",
        "pipeline": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('GTM_ANALYTICS')}
  DIMENSIONS PIPELINE_OVERVIEW.AS_OF_DATE
  METRICS    PIPELINE_OVERVIEW.OPEN_PIPELINE_VALUE_MTD, PIPELINE_OVERVIEW.WEIGHTED_PIPELINE_VALUE_MTD
  WHERE      PIPELINE_OVERVIEW.AS_OF_DATE BETWEEN '{fe}' AND '{le}'{acct_gtm}
)
ORDER BY 1""",
        # no subsidiary or account filter, ever: the REVOLVER table relates to no other table
        "revolver": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS REVOLVER.METRIC, REVOLVER.MONTH_START_DATE
  METRICS    REVOLVER.REVOLVER_AMOUNT
  WHERE      REVOLVER.MONTH_START_DATE BETWEEN '{fs}' AND '{ls}'
)
ORDER BY 1, 2""",
        # Drawn Revolver: the balance sheet month-end balance of the revolver account (a balance sheet line, so the
        # subsidiary exclusion applies as it does to bs)
        "revolver_drawn": f"""SELECT * FROM SEMANTIC_VIEW(
  {fq('FINANCE_ANALYTICS')}
  DIMENSIONS PERIOD.PERIOD_START_DATE
  METRICS    BALANCE_SHEET.ENDING_BALANCE_CONVERTED
  WHERE      PERIOD.PERIOD_START_DATE BETWEEN '{fs}' AND '{ls}'
    AND ACCOUNT.ACCOUNT_NUMBER = '{drawn_account}'{excl_fin}
)
ORDER BY 1""",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="last month of the window, YYYY-MM (default: the month before the current month)")
    ap.add_argument("--months", type=int, default=24, help="months in the window (default 24; the template holds at most 36)")
    ap.add_argument("--work", default="work")
    ap.add_argument("--exclude-accounts", action="append", metavar="IDS",
                    help="Salesforce account IDs (18 characters) to leave out of ARR, customers, bookings and pipeline, on top of the internal test accounts in config/scope.json; comma separated, repeatable")
    ap.add_argument("--exclude-accounts-file", action="append", metavar="FILE", help="a text file of account IDs to exclude (one or more per line, '#' comments)")
    ap.add_argument("--scope", default=os.path.join(SKILL, "config", "scope.json"))
    a = ap.parse_args()
    import sql_guard
    with open(a.scope, encoding="utf-8") as fh:
        scope = json.load(fh)
    today = dt.date.today()
    as_of = a.as_of or add_months(today.replace(day=1), -1).strftime("%Y-%m")
    try:
        last = month_start(as_of)
    except ValueError:
        refuse(f"--as-of {as_of!r} is not YYYY-MM")
    if not (1 <= a.months <= 36):
        refuse("--months must be between 1 and 36 (the template holds 36 month columns)")
    if last >= today.replace(day=1):
        refuse(f"{as_of} has not closed yet (today is {today.isoformat()}); pick a closed month")
    first = add_months(last, -(a.months - 1))
    default_accounts = list(scope.get("exclude_accounts") or [])
    bad_default = [x for x in default_accounts if not SF_ID.match(str(x))]
    if bad_default:
        refuse(f"config/scope.json exclude_accounts holds IDs that are not 18-character Salesforce account IDs: {', '.join(map(str, bad_default))}")
    requested = parse_accounts(a.exclude_accounts, a.exclude_accounts_file)
    accounts = list(dict.fromkeys(default_accounts + requested))      # standing test accounts first, then the request
    drawn_account = str(scope.get("revolver_drawn_account") or "")
    if not re.fullmatch(r"[0-9]{3,12}", drawn_account):
        refuse(f"config/scope.json revolver_drawn_account {drawn_account!r} is not an account number")
    qs = build_queries(scope["database"], scope["schema"], first, last, scope["exclude_subsidiaries"], scope["rollup_keys"], scope["pl_l6_kept_under_l5"], accounts, drawn_account)
    qdir = os.path.join(a.work, "queries")
    os.makedirs(qdir, exist_ok=True)
    os.makedirs(os.path.join(a.work, "raw"), exist_ok=True)
    manifest = {"as_of": as_of, "months": a.months, "first_month": first.strftime("%Y-%m"), "arr_basis": ARR_BASIS,
                "scope": {"exclude_subsidiaries": scope["exclude_subsidiaries"], "exclude_accounts": accounts,
                          "exclude_accounts_default": default_accounts, "exclude_accounts_requested": [x for x in requested if x not in default_accounts],
                          "database": scope["database"], "schema": scope["schema"],
                          "revolver": "FINANCE_ANALYTICS REVOLVER (Finance's manual table) has no subsidiary dimension: never filtered by subsidiary",
                          "revolver_drawn_account": drawn_account},
                "mode": "governed", "created": dt.datetime.now().isoformat(timespec="seconds"), "queries": {}}
    for name in ORDER:
        sql = qs[name]
        verdict = sql_guard.check(sql)
        if not verdict.get("ok"):
            refuse(f"query {name} failed the read-only guard: {verdict.get('reason')}")
        path = os.path.join(qdir, f"{name}.sql")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(sql + "\n")
        manifest["queries"][name] = {"sql": path, "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                                     "raw": os.path.join(a.work, "raw", f"{name}.json"), "columns": expected_columns(name)}
    with open(os.path.join(qdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(json.dumps({"status": "WRITTEN", "as_of": as_of, "window": [first.strftime("%Y-%m"), as_of], "arr_basis": ARR_BASIS,
                      "excluded_accounts": len(accounts), "excluded_accounts_default": len(default_accounts),
                      "queries": [manifest["queries"][n]["sql"] for n in ORDER], "save_results_to": os.path.join(a.work, "raw", "<name>.json"),
                      "next": "run each .sql file verbatim with sql-exec; save each full result to work/raw/<name>.json; then build_chronograph.py"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
