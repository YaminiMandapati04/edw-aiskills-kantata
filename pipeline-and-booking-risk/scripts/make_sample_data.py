#!/usr/bin/env python3
"""Generate a SYNTHETIC sample workbook that mirrors the structure of the GTM semantic view,
for testing the skill without a warehouse connection (see references/local-mode.md).

    python make_sample_data.py [outdir]        # default: ../assets/sample-data

Writes gtm_sample.xlsx. Deterministic (fixed seed).
Every figure is invented. Never present these numbers as real.

The data is internally consistent on purpose, so analysis can be checked:
  * stage history ends in each opportunity's current stage;
  * booking metrics follow the view: recurring lines are Salesforce won New Sales and
    Seat Expansion opportunities; non-recurring lines are NetSuite revenue by subsidiary;
  * quarters and years are fiscal (1 February to 31 January).
"""
import datetime as dt
import os
import random
import sys

from openpyxl import Workbook

SEED = 20261103
LATEST = dt.date(2026, 10, 31)                       # latest closed month-end in the samples
MONTHS = [dt.date(2024 + (i // 12), i % 12 + 1, 1) for i in range(34)]   # 2024-01 .. 2026-10


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


# ----------------------------------------------------------------------- gtm

def gtm(rng):
    customers = ["Globex Industries", "Initech", "Umbrella Group", "Wayne Industries", "Stark Systems", "Tyrell Corp",
                 "Hooli", "Pied Piper", "Soylent Foods", "Cyberdyne Systems", "Vandelay Industries", "Oscorp",
                 "Aperture Labs", "Massive Dynamic", "Weyland Corp", "Nakatomi Trading", "Rekall", "Black Mesa"]
    subs = ["Acme US", "Acme UK"]
    prods = [("OX", 0.7), ("SX", 0.3)]
    # booking lines as the view holds them: Salesforce recurring lines (BOOKING_METRIC Recurring Services, an opportunity,
    # account and product, no subsidiary) and NetSuite non-recurring revenue (one line per month and subsidiary on the
    # period end date, no account, product or opportunity)
    lines, order = [], 0
    for i, m in enumerate(MONTHS):
        qend = 1.3 if m.month in (1, 4, 7, 10) else 1.0               # fiscal quarter-end close pattern (FY starts in February)
        for _ in range(rng.randint(8, 12)):
            order += 1
            p = rng.choices([x[0] for x in prods], [x[1] for x in prods])[0]
            new = rng.random() < 0.42
            acv = rng.uniform(15_000, 110_000) * (1 + 0.012 * i) * qend
            if not new and m >= dt.date(2026, 2, 1):
                acv *= 1.12                                              # planted: seat expansion stepping up in FY2027
            c = rng.choice(customers)
            if m == dt.date(2026, 10, 1) and new and rng.random() < 0.5:
                c = rng.choice(["Globex Industries", "Hooli"])           # planted: October concentration
                acv *= 3.2
            if rng.random() < 0.03:
                acv = -acv * 0.5                                         # a credit nets off
            lines.append([dt.date(m.year, m.month, rng.randint(1, 28)), "Recurring Services", "Salesforce",
                          "New Sales" if new else "Seat Expansion", p, f"006B{order:06d}", c, None, round(acv, 2)])
        for s in subs:
            nr = rng.uniform(180_000, 260_000) * (0.75 if m >= dt.date(2026, 2, 1) else 1.0)   # planted: non-recurring shrinking in FY2027
            lines.append([month_end(m), "Non-Recurring", "NetSuite", None, None, None, None, s, round(nr, 2)])
    bl_hdr = ["BOOKING_DATE", "BOOKING_METRIC", "BOOKING_SOURCE", "OPPORTUNITY_TYPE", "PRODUCT", "OPPORTUNITY_ID",
              "ACCOUNT_NAME", "SUBSIDIARY_NAME", "BOOKING_ACV_USD"]

    # the stage mapping: 00 - PROSPECT is not a pipeline stage; 01 to 06 are; 07 closes won or lost
    stages = [("01 - ENGAGE", 2), ("02 - DISCOVER", 3), ("03 - EVALUATE", 4), ("04 - PROPOSE", 5), ("05 - SECURE", 6), ("06 - NEGOTIATE", 7)]
    owners = ["Ava Chen", "Ben Ortiz", "Cara Singh", "Dev Patel", "Eli Novak"]
    sources = ["Marketing", "Sales", "Expansion/Renewal", "Operations"]
    stuck_group = ["Initech", "Oscorp"]
    # risk fields draw from their own generator, so every earlier draw (and every earlier planted signal) is unchanged
    rng2 = random.Random(SEED + 7)
    opps, hist = [], []
    for n in range(1, 601):
        src = rng.choice(sources)
        if rng.random() < 0.24:                                          # live pipeline
            created = LATEST - dt.timedelta(days=rng.randint(5, 200))
            status = "Open"
        else:                                                            # history; planted: Operations deals convert worse
            created = LATEST - dt.timedelta(days=rng.randint(130, 760))
            status = rng.choices(["Closed Won", "Closed Lost"], [0.35, 0.65] if src == "Operations" else [0.55, 0.45])[0]
        acv = round(rng.uniform(20_000, 170_000), 2)
        si = rng.randint(0, 5) if status == "Open" else (5 if status == "Closed Won" else rng.randint(0, 4))
        day, path = created, []
        for j in range(si + 1):
            start = day
            day = day + dt.timedelta(days=rng.randint(6, 38))
            path.append((stages[j], start, day))
        slow = False
        if status == "Open":
            slow = n % 7 == 0                                            # planted: deals long in their stage
            last_start = LATEST - dt.timedelta(days=rng.randint(130, 220) if slow else rng.randint(2, 40))
            path[-1] = (path[-1][0], max(created, last_start), None)
            lo, hi = rng.choices([(-50, -1), (0, 61), (62, 151), (152, 240)], [0.10, 0.50, 0.32, 0.08])[0]
            close = LATEST + dt.timedelta(days=rng.randint(lo, hi))
            cur = path[-1][0]
        else:
            close = min(path[-1][2], LATEST)
            cur = ("07 - CLOSE (WON)", 8) if status == "Closed Won" else ("07 - CLOSE (LOST)", 9)
        prod = rng.choice([x[0] for x in prods])
        owner = rng.choice(owners)
        account = rng.choice(customers)
        otype = rng.choice(["New Sales", "Seat Expansion"])
        if slow and cur[0] in ("04 - PROPOSE", "05 - SECURE"):          # planted: a two-customer group stuck late in the funnel
            account = rng2.choice(stuck_group)
        name = f"{account} - {otype}"
        sqo = path[2][1] if len(path) > 2 else None                      # pipeline creation: reaching 03 - EVALUATE (the SQO stage)
        opps.append([f"006{n:06d}", name, account, owner, prod, src, otype, status, cur[0], cur[1],
                     close, created, sqo, acv, LATEST, rng.choice(["NorAm", "EMEA"])])
        # stage runs; the close date at the end of each run; planted: some open deals pushed out 1 to 3 times (30 days each),
        # the pushes falling on the last runs (the last one into the current close date)
        pushes = rng2.choice([1, 2, 3]) if status == "Open" and rng2.random() < 0.3 else 0
        L = len(path)
        for j, (st, s, e) in enumerate(path, start=1):
            last = j == L and status == "Open"
            asof = close - dt.timedelta(days=30 * min(pushes, L - j + 1))
            hist.append([f"006{n:06d}", name, j, st[0], "Open", s, e, asof, 1 if last else 0, owner, acv])
        if status != "Open":                                             # the closing run
            hist.append([f"006{n:06d}", name, L + 1, cur[0], status, path[-1][2], None, close, 1, owner, acv])
    opp_hdr = ["OPPORTUNITY_ID", "OPPORTUNITY_NAME", "ACCOUNT_NAME", "OWNER_NAME", "PRODUCT", "OPPORTUNITY_SOURCE", "OPPORTUNITY_TYPE",
               "STATUS", "STAGE_NAME", "STAGE_ORDER", "CLOSE_DATE", "CREATED_DATE", "PIPELINE_CREATION_DATE", "ACV_USD",
               "DATA_REFRESHED_AT", "REGION"]
    hist_hdr = ["OPPORTUNITY_ID", "OPPORTUNITY_NAME", "STAGE_RUN_NO", "STAGE_NAME", "STATUS", "STAGE_START_DATE", "STAGE_END_DATE",
                "CLOSE_DATE", "IS_CURRENT_STAGE", "OWNER_NAME", "ACV_USD"]
    return [
        ("BOOKING_LINES", bl_hdr, lines),
        ("OPPORTUNITIES", opp_hdr, opps),
        ("OPPORTUNITY_STAGE_HISTORY", hist_hdr, hist),
    ]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sample-data")
    os.makedirs(out, exist_ok=True)
    note = ["SYNTHETIC SAMPLE DATA: every figure is invented, for testing the semantic-data-analyst-gtm skill without a warehouse.",
            "Structure mirrors the sheets and columns of the GTM_ANALYTICS semantic view; see references/local-mode.md.",
            f"Latest closed month in the sample: {LATEST.isoformat()}. Months: 2024-01 to 2026-10."]
    rng = random.Random(SEED)
    write(os.path.join(out, "gtm_sample.xlsx"), gtm(rng),
          note + ["Planted for testing: October 2026 new-sales bookings concentrated in two customers; seat expansion stepping up and non-recurring revenue "
                 "shrinking in FY2027 (from February 2026); fiscal quarter-end close pattern (January, April, July, October); Operations-sourced deals convert worse; "
                 "open deals long in their stage; Initech and Oscorp stuck in 04 - PROPOSE / 05 - SECURE; "
                 "about 30% of open deals with their close date pushed out 1 to 3 times."])
    return 0


if __name__ == "__main__":
    sys.exit(main())
