#!/usr/bin/env python3
"""Smoke test of the finance diagnostic pipeline on the synthetic sample workbook, with no warehouse.

    python test_finance_pipeline.py [--out <folder>] [--keep] [--scale]

It generates the sample workbooks into a temp folder, runs analyze -> validate -> (an example diagnosis built from the
payload) -> gate -> render with and without the diagnosis, then checks the HTML (markers filled, no external request, the
payload parses back, the diagnosis banner present) and, when Chrome or Edge is installed, renders the page headless and
checks that every region is populated and no "undefined" / "NaN" reached the DOM. It renders the page from the trimmed
read-view and from the full payload and compares every lens and drill-down (finance/embed.py); --scale also builds a
~1,700-account page and checks it fits the 16 MB Artifact limit. Exit 0 = passed.

`example_diagnosis(payload)` is also the reference shape of a gate-passing diagnosis.json: it reuses the engine's own
insight statements (already registered) and adds the hypothesis block and the readout{} block the contract requires.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance import DIAGNOSIS_CONTRACT                     # noqa: E402
from finance.validate import validate_payload              # noqa: E402
from finance.diagnosis import validate_diagnosis, OPERATIONAL, SUMMARY_ROLES as ROLE_ORDER   # noqa: E402

PY = sys.executable
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
REGIONS = ["sum-exec", "kpis", "sum-movers", "sum-asks", "wfHost", "drvSel",
           "drv-runrate", "dimHost", "drv-commentary", "wf-fy", "out-commentary", "out-trend", "out-scenarios", "out-treatment",
           "glossary", "foot", "scope", "lens"]
# admitted conclusions render as summary bullets (li.rv), checked below; the review sections on Drivers and Outlook must render
# too (a missing helper once blanked the whole Outlook tab on the reviewed view)
DIAG_REGIONS = ["drv-reading", "out-reading"]


def run(args, cwd=None):
    r = subprocess.run([PY] + args, cwd=cwd or HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def example_diagnosis(payload, lens_id=None):
    """A gate-passing diagnosis built from the payload's own insights: the engine's statements are already registered."""
    lens_id = lens_id or payload["meta"]["primary_lens"]["id"]
    L = payload["lenses"][lens_id]
    drivers = [i for i in L["insights"] if i["kind"] == "driver"][:3]
    if not drivers:                                   # no material driver: lean on the outcome insights
        drivers = L["insights"][:3]
    PERS = {"recurring_level_change": "recurring", "persistent": "persistent", "coverage": "coverage", "seasonal": "seasonal",
            "timing_reversal": "timing", "one_off_candidate": "one_off", "undetermined": "undetermined"}
    findings = []
    for n, i in enumerate(drivers, start=1):
        sts = [{"state": s["state"], "text": s["text"], "numbers": [x for x in i["numbers"] if x["display"] in s["text"]], "evidence_refs": s.get("evidence_refs") or [f"lenses[{lens_id}].insights[{i['id']}]"]}
               for s in i["statements"]]
        sts.append({"state": "hypothesis", "text": "The movement reflects an item the ledger does not itemise; the owner's postings decide whether it repeats.",
                    "numbers": [], "evidence_refs": [f"lenses[{lens_id}].insights[{i['id']}]"], "claim_types": ["persistence"],
                    "hypothesis": {"evidence_for": i["causal_gap"]["known"] or ["the engine signals on the driver"], "missing_evidence": ["the largest postings in the window"], "closes_with": "the suggested owner confirms the item"}})
        findings.append({"id": f"f{n}", "title": i["label"] + (" moved " + i["numbers"][0]["display"] if i["kind"] == "driver" and i["numbers"] else ""),
                         "scope": {"drivers": [i["subject_ref"]] if i["kind"] == "driver" else [], "accounts": []},
                         "decision_relevance": i["decision_relevance"], "confidence": i["confidence"], "controllability": "not_assessed",
                         "persistence": PERS.get(i["persistence"], "undetermined"), "statements": sts,
                         "missing_evidence": ["the largest postings in the window"], "management_questions": [i["causal_gap"]["question"]], "addresses_tests": []})
    unresolved = [{"ref": d["id"], "reason": "not reviewed in the smoke test"} for d in L["drivers"] if d["tier"] == "executive" and d["id"] not in {f["scope"]["drivers"][0] for f in findings if f["scope"]["drivers"]}]
    roles = ["current_period_driver", "performance_quality", "forward_looking"]
    concl = []
    for k, role in enumerate(roles):
        f = findings[min(k, len(findings) - 1)]
        fact = next(s for s in f["statements"] if s["state"] == "observed_fact")
        concl.append({"role": role, "finding_ref": f["id"], "status": "mixed", "insight": ["Watch this driver", "Quality of the result", "What carries forward"][k], "state": "analytical_inference", "persistence": f["persistence"],
                      "text": fact["text"], "numbers": fact["numbers"], "evidence_refs": fact["evidence_refs"] or [f"lenses[{lens_id}]"], "response": "Confirm the item with the suggested owner before any forecast changes."})
    acts = L["actions"][:2]
    # the written summary: the engine's own registered bullets re-used as the writer's (heads, text, numbers, drill all valid), and the actions as questions
    sm = L["summary"]
    # the narrative roles, in order: headline, why, trend, meaning, attention (engine bullet id -> role)
    role_of = {"lead": "headline", "concentration": "why", "trend": "trend", "persistence": "meaning", "margin": "meaning", "mix": "meaning", "budget_bias": "attention", "year": "attention"}
    pool = [sm["lead"]] + sm["insights"] + ([sm["year"]] if sm.get("year") else [])
    src = [next((b for b in pool if role_of.get(b["id"]) == r), None) for r in ROLE_ORDER]
    src = [b for b in src if b]
    tone_of = {"fav": "favourable", "unf": "unfavourable", "neu": "neutral", "amb": "neutral", "ink": "outlook"}
    def short(t):
        w = t.split()
        return t if len(w) <= 60 else " ".join(w[:60]).rstrip(",;:(") + "."
    bullets = []
    for i, b in enumerate(src):
        x = {"id": b["id"], "role": role_of[b["id"]], "tone": tone_of.get(b["tone"], "neutral"), "head": b["head"].rstrip("."), "text": b["short"], "detail": short(b["text"]),
             "numbers": b["numbers"], "drill": b["drill"], "claim": b.get("claim") if i == 0 else None}
        ops = sorted({m.group(0).lower() for m in OPERATIONAL.finditer(x["head"] + " " + x["text"] + " " + x["detail"])})
        if ops:
            x["unverified"] = ops
        bullets.append(x)
    page = lambda: sum(len(b["head"].split()) + len(b["text"].split()) for b in bullets)
    bullets = [b for b in bullets if b["role"] != "meaning"]   # the executive summary holds exactly four bullets: what it means is folded into the others
    att = next((b for b in bullets if b["role"] == "attention"), None)
    if att is not None:
        att["data_needed"] = sorted({u for b in bullets for u in b.get("unverified", [])})
    def q12(t):
        w = t.rstrip("?").split()
        return (" ".join(w[:12]) if len(w) > 12 else " ".join(w)) + "?"
    decisions = [{"text": q12(a["question"]), "detail": (a["ask"]["text"].rstrip(".") + "?") if a.get("ask") and len(a["ask"]["text"].split()) <= 39 else q12(a["question"]), "owner": a["owner"]["role"], "drill": {"level": "action", "ids": [a["id"]]},
                  "amount": {"display": "", "value": a["exposure"]["amount"], "kind": "money", "transform": "abs", "source": a["exposure"]["source"]}, "numbers": (a["ask"]["numbers"] if a.get("ask") and len(a["ask"]["text"].split()) <= 39 else [])} for a in L["actions"][:2]]
    summary = {"bullets": bullets, "decisions": decisions}
    return {"contract": DIAGNOSIS_CONTRACT, "payload_hash": payload["analysis_hash"], "lens": {"window": L["window"], "basis": L["basis"]}, "written_by": "test_finance_pipeline (synthetic example)",
            "findings": findings, "unresolved": unresolved,
            "readout": {"headline": None, "conclusions": concl,
                    "decision_asks": [{"text": a["question"], "finding_ref": findings[0]["id"], "owner": a["owner"]["role"], "action_refs": [a["id"]], "numbers": []} for a in acts],
                    "driver_stories": [],
                    "structural_conclusions": [{"text": "The cost base moves with headcount more than with revenue.", "state": "analytical_inference",
                                                "hypothesis": True, "evidence_refs": ["lenses"], "numbers": []}],
                    "forecast_assumptions": [{"text": "The run-rate assumes the latest months repeat; no seasonality is included.", "state": "analytical_inference",
                                              "hypothesis": True, "evidence_refs": ["outlook"], "numbers": []}],
                    "lead_actions": [],
                    "account_interpretations": [], "summary": summary, "qc": {"business_cause": "No cause is attested; every reading is a hypothesis.", "open_gaps": ["synthetic sample data"]}}}


def check_html(path, expect_diag):
    s = open(path, encoding="utf-8").read()
    errs = []
    for m in ("SDA:TITLE", "SDA:CSS", "SDA:BANNER", "SDA:PAYLOAD", "SDA:JS"):
        if f"<!-- {m} -->" in s:
            errs.append(f"marker {m} not replaced")
    if re.search(r'(src|href)="https?://', s):
        errs.append("external request found")
    m = re.search(r'<script id="sda-payload" type="application/json">\n(.*?)\n</script>', s, re.S)
    if not m:
        errs.append("payload block missing")
    else:
        json.loads(m.group(1).replace("\\u003c", "<"))
    if 'id="pubBanner"' in s or "Data verified: every figure" in s:
        errs.append("status banner present (it was removed from every dashboard)")
    return errs


def headless_check(html_path, expect_diag):
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        return None, ["no Chrome / Edge found: headless DOM check skipped"]
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--dump-dom", "--virtual-time-budget=6000", url], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    dom = r.stdout
    errs = []
    if len(dom) < 100000:
        errs.append(f"DOM too small ({len(dom)} bytes): the script probably threw")
    body = dom[dom.find("<body"):dom.find('<script id="sda-payload"')] if '<script id="sda-payload"' in dom else dom
    for rid in REGIONS + (DIAG_REGIONS if expect_diag else []):
        if f'id="{rid}"' not in body:
            errs.append(f"region {rid} missing")
        else:
            i = body.index(f'id="{rid}"'); seg = body[i:i + 400]
            if ">" in seg and re.search(r'id="%s"[^>]*>\s*<' % rid, seg) is None and re.search(r'id="%s"[^>]*>\s*[^<\s]' % rid, seg) is None:
                errs.append(f"region {rid} empty")
    for bad in ("undefined", "NaN", "[object Object]", "adverse", "Adverse"):
        if bad in body:
            i = body.index(bad); errs.append(f"'{bad}' in DOM near: {body[max(0, i - 80):i + 40]!r}")
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script).*?</>", " ", body, flags=re.S))
    jargon = [w for w in ("engine baseline", "admitted diagnosis", "Diagnosis admitted", "engine reading", "payload", "Deterministic", "comparator", "Comparator",
                          "validation gate", "forecast credit", "rule-generated", "Data qualified", "proposed, not approved", "mechanical") if w in visible]
    if jargon:
        errs.append("technical wording on the page: " + ", ".join(jargon))
    if expect_diag and 'class=" rv"' not in body and 'class="lead rv"' not in body:
        errs.append("admitted conclusions not merged into the executive summary")
    m = re.search(r'<ul class="bul">(.*?)</ul>', body, re.S)
    if m and not 3 <= m.group(1).count("<li") <= 5:
        errs.append(f"executive summary has {m.group(1).count('<li')} bullets; 3 to 5 expected")
    if 'id="glsMode"' not in body or "All labels" not in body:
        errs.append("tab-aware glossary switch not rendered")
    if "Reviewed conclusions" in body:
        errs.append("separate Reviewed conclusions section rendered")
    if body.count('class="wf"') < 2:
        errs.append("expected two waterfalls (Drivers, Outlook)")
    return exe, errs


PROBE = """<script>
(function () {
  const out = [], P0 = window.__SDA_PAYLOAD__;
  const B = { drill: drillDrawer, acct: acctDrawer, driver: driverDrawer, kpi: kpiDrawer, line: lineDrawer, action: actionDrawer, finding: findingDrawer, qc: qcDrawer, outlook: outlookDrawer, node: nodeDrawer };
  try {
    for (const k of Object.keys(P0.lenses)) {
      const Lk = P0.lenses[k]; if (!Lk.available) continue;
      setLens(k); out.push('LENS ' + k + ' ' + document.getElementById('app').innerHTML);
      const sm = Lk.summary || {}, bul = [sm.lead].concat(sm.insights || [], sm.year ? [sm.year] : []).filter(Boolean);
      const nodes = []; for (const h of Object.values(Lk.hierarchy || {})) for (const n of h.nodes) { nodes.push(n.id); for (const c of n.children) nodes.push(c.id); }
      const refs = [].concat(Lk.accounts.map(a => 'acct:' + a.id), Lk.drivers.map(d => 'driver:' + d.id), (Lk.kpis || []).map(q => 'kpi:' + q.id),
        (Lk.lines || []).map(q => 'line:' + q.id), (Lk.actions || []).map(q => 'action:' + q.id), nodes.map(n => 'node:' + n),
        ((Lk.product_lines || {}).items || []).map(q => 'node:' + q.id), ((DIAGS[k] || {}).findings || []).map(f => 'finding:' + f.id),
        bul.map(b => drillRef(b.drill)), ['qc', 'outlook:mechanical']);
      for (const r of refs) {
        const i = r.indexOf(':'), kind = i < 0 ? r : r.slice(0, i), id = i < 0 ? null : r.slice(i + 1), sp = B[kind] ? B[kind](id) : null;
        if (!sp) { out.push(k + '|' + r + '|none'); continue; }
        out.push(k + '|' + r + '|' + sp.title + '|' + sp.sub + '|' + (sp.tags || []).join(''));
        for (const [t, f] of Object.entries(sp.tabs)) out.push(t + ':' + f());
      }
    }
  } catch (e) { out.push('PROBE ERROR ' + e.message + ' ' + (e.stack || '').split('\\n')[1]); }
  const pre = document.createElement('pre'); pre.id = 'probe'; pre.textContent = out.join('\\n'); document.body.appendChild(pre);
})();
</script>"""


def drawer_probe(html_path):
    """Every lens's whole page and every drill-down (accounts, drivers, KPIs, lines, actions, sub-groups, findings,
    summary drills, data checks, run-rate), headless; returns their text (None without a browser)."""
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        return None
    s = open(html_path, encoding="utf-8").read()
    probe = html_path[:-5] + "-probe.html"
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(s.replace("</body>", PROBE + "</body>") if "</body>" in s else s + PROBE)
    dom = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1440,1000", "--dump-dom", "--virtual-time-budget=15000",
                          "file:///" + os.path.abspath(probe).replace("\\", "/")], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600).stdout
    m = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
    return m.group(1) if m else "PROBE MISSING"


def page_body(html_path):
    """The rendered page body before the embedded payload, headless (None without a browser)."""
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        return None
    dom = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1440,1000", "--dump-dom", "--virtual-time-budget=6000",
                          "file:///" + os.path.abspath(html_path).replace("\\", "/")], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
    return dom[dom.find("<body"):dom.find('<script id="sda-payload"')]


def embed_checks(payload_path, diag_paths, out, step):
    """The trimmed page must render exactly as the full payload does: same opening view, same page and drill-downs in every lens."""
    for name, extra in (("baseline", ["--allow-missing-review"]), ("diagnosed", ["--diagnosis"] + diag_paths)):
        full, slim = os.path.join(out, f"{name}-full.html"), os.path.join(out, f"{name}-slim.html")
        c1, _ = run(["render_finance_dashboard.py", "--payload", payload_path, "--out", full, "--no-trim"] + extra)
        c2, log = run(["render_finance_dashboard.py", "--payload", payload_path, "--out", slim] + extra)
        if c1 or c2:
            step(f"render full and trimmed ({name})", False, log.strip().splitlines()[-1][:160]); continue
        r = json.loads(log[log.index("{"):])["embed"]
        step(f"embedded payload trimmed ({name})", r["stage"] == "A" and r["embedded_bytes"] < r["full_bytes"] and not r["kept_by_guard"],
             f"{r['full_bytes']:,} -> {r['embedded_bytes']:,} bytes" + (f"; named in the JS, kept: {r['kept_by_guard']}" if r["kept_by_guard"] else ""))
        b1, b2 = page_body(full), page_body(slim)
        if b1 is None:
            print("SKIP trimmed-page DOM comparison: no Chrome / Edge"); return
        step(f"trimmed page opens identically ({name})", b1 == b2)
        p1, p2 = drawer_probe(full), drawer_probe(slim)
        step(f"every lens and drill-down identical ({name})", p1 == p2 and "PROBE ERROR" not in p1 and len(p1) > 1000,
             p1[p1.find("PROBE ERROR"):][:200] if "PROBE ERROR" in p1 else "" if p1 == p2 else
             next((f"first difference near: {p1[max(0, i - 80):i + 80]!r}" for i in range(min(len(p1), len(p2))) if p1[i] != p2[i]), "lengths differ"))


def scale_checks(wb, out, step, n_accounts=1740):
    """Production scale with headroom: the Oct-26 extract has ~400 accounts (number + name within subsidiary) in 12
    drivers; this clones the sample to ~1,700 accounts in its 15 drivers, with varied sizes. The page must fit the
    Artifact limit."""
    import random
    from finance.load import rows_from_workbook
    from finance.embed import PAGE_LIMIT_BYTES
    base = [{k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows_from_workbook(wb)]
    acct = lambda r: (r.get("ACCOUNT_NUMBER"), r.get("ACCOUNT_NAME"), r.get("SUBSIDIARY_NAME"))
    keys = sorted({acct(r) for r in base}, key=str)
    rng, rows, c = random.Random(7), list(base), 0
    while len({acct(r) for r in rows}) < n_accounts:
        c += 1
        f = {k: rng.choice([0.002, 0.01, 0.05, 0.3, 1.0]) for k in keys}
        noise = {k: rng.uniform(0.8, 1.25) for k in keys}
        for r in base:
            if str(r["CHART_OF_ACCOUNT_KEY"]).startswith("-"):     # roll-up keys are not accounts to clone
                continue
            k = acct(r)
            # same number, new name: a new account (number + name) inside the same driver, as production has
            # ~12 drivers of up to ~120 accounts each, not one driver per account
            q = dict(r, ACCOUNT_NAME=f"{r['ACCOUNT_NAME']} {c:03d}", CHART_OF_ACCOUNT_KEY=f"{r['CHART_OF_ACCOUNT_KEY']}-{c:03d}")
            for m in ("TOTAL_MTD", "TOTAL_PY_MTD", "TOTAL_BUDGET_MTD"):
                if q.get(m) is not None:
                    q[m] = round(q[m] * f[k] * (noise[k] if m == "TOTAL_MTD" else 1.0), 2)
            rows.append(q)
    n = len({acct(r) for r in rows})
    src = os.path.join(out, "rows-scale.json"); json.dump(rows, open(src, "w", encoding="utf-8"))
    # the governed roll-ups of the scaled extract (month x subsidiary), summed by the engine's own sections so they tie
    from finance.load import Frame, load_scope
    from finance.model import Model
    scope = load_scope()
    fr = Frame(rows, exclude_subsidiaries=scope["exclude_subsidiaries"], scope=scope)
    mdl = Model(fr)
    gov = {}
    for (p, s, ai), v in fr.cells.items():
        sec = fr.accounts[ai]["section"]
        if sec is None or v[0] is None or p > mdl.as_of:
            continue
        po = v[0] * mdl.profit_sign_by["actual"][sec]
        o = gov.setdefault((p, fr.subs[s]), {"PERIOD_START_DATE": fr.periods[p]["start"], "SUBSIDIARY_NAME": fr.subs[s], "REVENUE_MTD": 0.0, "ADJUSTED_EBITDA_MTD": 0.0, "NET_INCOME_MTD": 0.0})
        o["REVENUE_MTD"] += po if sec == "rev" else 0.0
        o["ADJUSTED_EBITDA_MTD"] += po if sec in ("rev", "cos", "opex") else 0.0
        o["NET_INCOME_MTD"] += po
    gp = os.path.join(out, "governed-scale.json"); json.dump(list(gov.values()), open(gp, "w", encoding="utf-8"))
    ps, h = os.path.join(out, "payload-scale.json"), os.path.join(out, "scale.html")
    code, log = run(["analyze_finance.py", "--rows", src, "--governed", gp, "--out", ps])
    step(f"analyze at scale ({n:,} accounts)", code == 0, log.strip().splitlines()[-1][:200] if code else "")
    if code:
        return
    code, log = run(["render_finance_dashboard.py", "--payload", ps, "--out", h, "--allow-missing-review"])
    r = json.loads(log[log.index("{"):]).get("embed") or {}
    step("page fits the Artifact limit at scale", code == 0 and os.path.getsize(h) <= PAGE_LIMIT_BYTES,
         f"stage {r.get('stage')}, {r.get('full_bytes', 0):,} -> {r.get('page_bytes', 0):,} bytes, {r.get('accounts_trimmed', 0):,} accounts trimmed")
    if code == 0:
        exe, herrs = headless_check(h, False)
        if exe is not None:
            step("headless DOM at scale", not herrs, "; ".join(herrs[:4]))


def variant_rows(wb, path, budget_fn):
    """The sample workbook as query rows, with the budget column rewritten by budget_fn(row, value)."""
    from finance.load import rows_from_workbook
    rows = []
    for r in rows_from_workbook(wb):
        r = {k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in r.items()}
        if r["TOTAL_BUDGET_MTD"] is not None:
            r["TOTAL_BUDGET_MTD"] = budget_fn(r, float(r["TOTAL_BUDGET_MTD"]))
        rows.append(r)
    json.dump(rows, open(path, "w", encoding="utf-8"))
    return path


def governed_file(wb, path, tamper=None):
    """The workbook's GOVERNED sheet as the --governed file; tamper(row) may alter one row to force a refusal."""
    from finance.load import governed_from_workbook
    rows = [{k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in governed_from_workbook(wb)]
    if tamper:
        rows = [tamper(r) for r in rows]
    json.dump(rows, open(path, "w", encoding="utf-8"))
    return path


def yes_energy_checks(wb, out, payload, step):
    """Yes Energy's view: values stored unsigned with ACCOUNT.P_AND_L_MULTIPLIER; manual adjustment rows marked by
    INCOME_STATEMENT.ADJUSTMENT_TYPE: pro forma actuals on ordinary accounts, and the capitalisation of software and
    commissions on keys -8001 / -8002 (inside Adjusted EBITDA, no subsidiary) reversed on -8003 below EBITDA."""
    from finance.load import rows_from_workbook, governed_from_workbook, NO_SUB
    iso = lambda r: {k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in r.items()}
    rows, months = [], set()
    for r in map(iso, rows_from_workbook(wb)):
        m = 1.0 if str(r.get("COA_MAPPING_L3") or "").strip().lower() == "revenue" else -1.0
        q = dict(r, P_AND_L_MULTIPLIER=m, ACCOUNT_TYPE="Income" if m > 0 else "Expense", ADJUSTMENT_TYPE=None)
        for k in ("TOTAL_MTD", "TOTAL_PY_MTD", "TOTAL_BUDGET_MTD"):
            q[k] = None if q.get(k) is None else float(q[k]) * m          # stored unsigned, as the view keeps it
        rows.append(q)
        months.add((r["PERIOD_START_DATE"], r.get("PERIOD_END_DATE"), r.get("YEAR"), r.get("QUARTER"), r.get("PERIOD")))
    rev_row = next(r for r in rows if str(r.get("COA_MAPPING_L3")).lower() == "revenue" and r.get("SUBSIDIARY_NAME"))
    sub0 = rev_row["SUBSIDIARY_NAME"]
    CAP, PF = 40_000.0, 25_000.0
    base = lambda start, end, year, qtr, per: {"PERIOD": per, "PERIOD_START_DATE": start, "PERIOD_END_DATE": end, "YEAR": year, "QUARTER": qtr,
                                                "CLASS_NAME": None, "DEPARTMENT_NAME": None, "TOTAL_PY_MTD": None, "TOTAL_BUDGET_MTD": None}
    for start, end, year, qtr, per in sorted(months):
        b = base(start, end, year, qtr, per)
        rows.append({**b, "SUBSIDIARY_NAME": None, "CHART_OF_ACCOUNT_KEY": "-8002", "ACCOUNT_NUMBER": None, "ACCOUNT_NAME": "Capitalised Commissions",
                     "ACCOUNT_TYPE": "Expense", "ADJUSTMENT_TYPE": "Adjustment for Capitalized expenses", "COA_MAPPING_L2": "Adjusted EBITDA",
                     "COA_MAPPING_L3": "Operating Expenses", "COA_MAPPING_L4": "Fully loaded S&M Expense", "P_AND_L_MULTIPLIER": -1.0, "TOTAL_MTD": CAP})
        rows.append({**b, "SUBSIDIARY_NAME": None, "CHART_OF_ACCOUNT_KEY": "-8003", "ACCOUNT_NUMBER": None, "ACCOUNT_NAME": "Reversal of Capitalised Portions",
                     "ACCOUNT_TYPE": "OthExpense", "ADJUSTMENT_TYPE": "Adjustment for Capitalized expenses", "COA_MAPPING_L2": "Total Non-Operating Income (Expense)",
                     "COA_MAPPING_L3": "Total Non-Operating Income (Expense)", "COA_MAPPING_L4": "Reversal of Capitalized Portions", "P_AND_L_MULTIPLIER": -1.0, "TOTAL_MTD": -CAP})
        rows.append({**{k: rev_row.get(k) for k in rev_row}, **b, "SUBSIDIARY_NAME": sub0, "ADJUSTMENT_TYPE": "Pro Forma Actuals", "TOTAL_MTD": PF})
    rp = os.path.join(out, "rows-yes-energy.json"); json.dump(rows, open(rp, "w", encoding="utf-8"))
    gov = [iso(r) for r in governed_from_workbook(wb)]
    for g in gov:
        if g["SUBSIDIARY_NAME"] == sub0:
            g.update(REVENUE_MTD=float(g["REVENUE_MTD"]) + PF, ADJUSTED_EBITDA_MTD=float(g["ADJUSTED_EBITDA_MTD"]) + PF, NET_INCOME_MTD=float(g["NET_INCOME_MTD"]) + PF)
    for start, *_ in sorted(months):
        gov.append({"PERIOD_START_DATE": start, "SUBSIDIARY_NAME": None, "REVENUE_MTD": 0.0, "ADJUSTED_EBITDA_MTD": -CAP, "NET_INCOME_MTD": 0.0})
    gp = os.path.join(out, "gov-yes-energy.json"); json.dump(gov, open(gp, "w", encoding="utf-8"))
    pk = os.path.join(out, "p-yes-energy.json")
    code, log = run(["analyze_finance.py", "--rows", rp, "--governed", gp, "--out", pk])
    step("Yes Energy: unsigned values, pro forma and capitalisation adjustments build and tie to the governed totals", code == 0, log.strip().splitlines()[-1][:200] if code else "")
    if code:
        return
    k = json.load(open(pk, encoding="utf-8"))
    qc = {c["id"]: c for c in k["qc"]["checks"]}
    step("Yes Energy: signs are read from the multiplier", qc["sign_convention"]["result"] == "PASS" and "P_AND_L_MULTIPLIER" in qc["sign_convention"]["detail"])
    d = qc.get("adjustments_included", {}).get("detail", "")
    step("Yes Energy: QC names both adjustment types and confirms the capitalisation nets to zero at net income",
         qc.get("adjustments_included", {}).get("result") == "PASS" and "Pro Forma Actuals" in d and "Adjustment for Capitalized expenses" in d
         and "net to zero" in d and set(k["meta"]["scope"]["adjustments"]) == {"Pro Forma Actuals", "Adjustment for Capitalized expenses"}
         and NO_SUB in k["meta"]["scope"]["subsidiaries"], d[:200])
    ln = lambda p, lid: next(x for x in p["lenses"]["YTD_py"]["lines"] if x["id"] == lid)
    n = k["lenses"]["YTD_py"]["months"]
    step("Yes Energy: Adjusted EBITDA carries the capitalisation and the pro forma, net income only the pro forma",
         abs(ln(k, "ebitda")["actual_po"] - ln(payload, "ebitda")["actual_po"] - (PF - CAP) * n) < 0.05
         and abs(ln(k, "ni")["actual_po"] - ln(payload, "ni")["actual_po"] - PF * n) < 0.05,
         f"ebitda {ln(k, 'ebitda')['actual_po']} vs {ln(payload, 'ebitda')['actual_po']}; ni {ln(k, 'ni')['actual_po']} vs {ln(payload, 'ni')['actual_po']}")
    A = {x["id"]: x for x in k["lenses"]["YTD_py"]["adjustments"]["types"]}
    cap = A.get("adjustment_for_capitalized_expenses", {}).get("actual") or {}
    step("Yes Energy: the lens adjustments block gives each type's EBITDA and net income impact",
         abs(cap.get("ebitda", 0) + CAP * n) < 0.05 and abs(cap.get("ni", 1)) < 0.05
         and abs(A["pro_forma_actuals"]["actual"]["rev"] - PF * n) < 0.05, json.dumps(cap)[:200])
    code, log = run(["finance_brief.py", pk, "adjustments", "--lens", "YTD_py"])
    step("Yes Energy: the brief exposes the adjustments with cited figures", code == 0 and "adjustments.types[" in log, log[:160])
    bad = rows + [dict(rows[-3], CHART_OF_ACCOUNT_KEY="-10000", ACCOUNT_NAME="Unknown")]
    bp = os.path.join(out, "rows-yes-energy-bad.json"); json.dump(bad, open(bp, "w", encoding="utf-8"))
    code, log = run(["analyze_finance.py", "--rows", bp, "--governed", gp, "--out", os.path.join(out, "p-ye-bad.json")])
    step("Yes Energy: a negative key that is neither a roll-up nor a capitalisation key refuses the build", code != 0 and "-10000" in log, log.strip().splitlines()[-1][:160])
    bad = [dict(r, ADJUSTMENT_TYPE="Mystery Adjustment") if r.get("ADJUSTMENT_TYPE") == "Pro Forma Actuals" else r for r in rows]
    json.dump(bad, open(bp, "w", encoding="utf-8"))
    code, log = run(["analyze_finance.py", "--rows", bp, "--governed", gp, "--out", os.path.join(out, "p-ye-bad.json")])
    step("Yes Energy: an unknown adjustment type refuses the build (never dropped)", code != 0 and "Mystery Adjustment" in log, log.strip().splitlines()[-1][:160])


def fiscal_checks(payload, step):
    """Yes Energy's fiscal year is the calendar year: year to date starts on 1 January, quarters are calendar quarters,
    and the outlook runs to 31 December."""
    import datetime as _dt
    from finance.common import fiscal_period
    from finance.model import window_range
    L = payload["lenses"]
    asof = payload["meta"]["as_of"]
    step("Yes Energy fiscal year: year to date starts in January",
         all(L[k]["range"]["start"][5:7] == "01" for k in ("YTD_budget", "YTD_py") if L[k]["available"]) and L["YTD_py"]["available"],
         L["YTD_py"]["range"]["start"])
    q_start = f"{asof['start'][:4]}-{(int(asof['start'][5:7]) - 1) // 3 * 3 + 1:02d}-01"
    step("Yes Energy fiscal year: quarter to date runs on calendar quarters",
         L["QTD_py"]["range"]["start"] == q_start and asof["year"] == int(asof["start"][:4]), L["QTD_py"]["range"]["start"])
    o = payload["outlook"]
    step("Yes Energy fiscal year: the outlook is the calendar year with the months to December to run",
         o["fiscal_year"] == int(asof["start"][:4]) and o["remaining_months"] == 12 - int(asof["start"][5:7]), f"{o['fiscal_year']} {o['remaining_months']}")
    qc = {c["id"]: c for c in payload["qc"]["checks"]}
    step("Yes Energy fiscal year: QC states the fiscal calendar", qc.get("fiscal_calendar", {}).get("result") == "PASS")
    months = [_dt.date(2026, 1, 1), _dt.date(2026, 2, 1), _dt.date(2026, 4, 1), _dt.date(2026, 12, 1), _dt.date(2027, 1, 1)]
    got = [fiscal_period(m, 1) for m in months]
    P = [{"year": 2025 + (k // 12), "quarter": (k % 12) // 3 + 1} for k in range(24)]   # Jan 2025 .. Dec 2026
    step("Yes Energy fiscal year: without YEAR / QUARTER the start month 1 gives calendar FY and quarter",
         got == [(2026, 1), (2026, 1), (2026, 2), (2026, 4), (2027, 1)] and window_range(P, 20, "YTD") == (12, 20) and window_range(P, 20, "QTD") == (18, 20),
         str(got))


def selftest(html_path):
    """Load the page with #selftest: the page reports overlapping chart labels, month-label format, the Plan vs month
    row count and where the lead bullet's drill lands, into <pre id="selftest">."""
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        return None
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/") + "?selftest"
    dom = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1440,1000", "--dump-dom", "--virtual-time-budget=9000", url],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180).stdout
    m = re.search(r'<pre id="selftest">(.*?)</pre>', dom, re.S)
    if not m:
        return {"errors": ["self-test did not run (the script probably threw)"], "dom": dom}
    import html as _h
    res = json.loads(_h.unescape(m.group(1)))
    res["dom"] = dom
    return res


def v15_checks(wb, out, payload, payload_path, html_path, step):
    """The 1.5.0 cases planted in the sample: exclusions, governed reconciliation, account grain, one-sided
    movements, drill footing, summary drill targets, month labels and the Plan vs month bar cap."""
    m, acc = payload["meta"], {a["id"]: a for a in payload["accounts"]}
    step("scope lists every subsidiary when no default exclusion is set", m["scope"]["label"] == "All subsidiaries (3)" and not m["scope"]["excluded_subsidiaries"], m["scope"]["label"])
    code, log = run(["analyze_finance.py", "--workbook", wb, "--out", os.path.join(out, "p-excl.json"), "--exclude-subsidiary", "Acme Acquired"])
    xm = json.load(open(os.path.join(out, "p-excl.json"), encoding="utf-8"))["meta"]["scope"] if code == 0 else {}
    step("an explicit --exclude-subsidiary is applied and named in the scope", code == 0 and xm.get("label") == "All subsidiaries (2) excluding Acme Acquired", xm.get("label") or log.strip().splitlines()[-1][:160])
    rows = variant_rows(wb, os.path.join(out, "rows-plain.json"), lambda r, v: v)
    bad = governed_file(wb, os.path.join(out, "gov-tampered.json"),
                        lambda r: {**r, "ADJUSTED_EBITDA_MTD": r["ADJUSTED_EBITDA_MTD"] + 5} if r["SUBSIDIARY_NAME"] == "Acme UK" and str(r["PERIOD_START_DATE"]).startswith("2026-03") else r)
    code, log = run(["analyze_finance.py", "--rows", rows, "--governed", bad, "--out", os.path.join(out, "p-tampered.json")])
    step("a governed roll-up that disagrees refuses, naming subsidiary and month", code != 0 and "Acme UK 2026-03" in log, log.strip().splitlines()[-1][:160])
    code, log = run(["analyze_finance.py", "--rows", rows, "--out", os.path.join(out, "p-nogov.json")])
    step("--rows without --governed refuses", code != 0 and "--governed" in log)
    sub = next(a for a in payload["accounts"] if a["number"] == "4000" and a["subsidiary"] == "Acme US")
    B = payload["lenses"]["MTD_budget"]
    la = next(a for a in B["accounts"] if a["id"] == sub["id"])
    cls = (B["splits"].get(sub["id"]) or {}).get("class")
    step("account = number + name within subsidiary; classes are drill detail", sub["keys"] == ["4000", "4000-A", "4000-B"] and cls and not cls["comparable"]
         and abs(la["variance"] - (la["actual_po"] - la["comparator_po"])) < 0.02, f"keys {sub['keys']}")
    sm = next(a for a in payload["accounts"] if a["number"] == "6000")
    step("budget held on one entity: compared across subsidiaries", sm["budget_grain"] == "account" and sm["subsidiary"] is None and sm["budget_held_at"] == ["Acme US"])
    M = payload["lenses"]["MTD_py"]
    by = {acc[a["id"]]["name"]: a for a in M["accounts"]}
    step("one-sided accounts carry a movement and a basis", by["Consulting"]["movement_basis"] == "no_comparator" and by["Legacy Tools"]["movement_basis"] == "no_activity"
         and by["Consulting"]["variance"] is None and abs(by["Consulting"]["movement"]) > 0)
    Y = payload["lenses"]["YTD_py"]
    rc = Y["reconciliation"]["d:nonop:acct-7300"]
    step("one-off gain listed first in its drill, as new this period", acc[rc["items"][0]["account"]]["name"] == "Extinguishment of Debt" and rc["items"][0]["movement_basis"] == "no_comparator")
    ask = next(a["ask"]["text"] for a in Y["actions"] if a["subject_ref"] == "d:nonop:acct-7300")
    step("decision ask flags the one-off from facts", "booked in 2026-08 only" in ask and "exclude it from the run-rate" in ask, ask[:120])
    foot = all(abs(sum(i["movement"] for i in r["items"]) + ((r.get("other") or {}).get("movement") or 0) - r["total"]) < 0.02
               for L in payload["lenses"].values() if L["available"] for r in L["reconciliation"].values())
    step("every drill table foots to its driver total", foot)
    dept = M["reconciliation"]["d:opex:acct-6000"].get("by_department")
    step("department split of S&M Salaries foots", dept and dept["comparable"] and abs(sum(r["movement"] for r in dept["rows"]) - dept["total"]["movement"]) < 0.02)
    want = {"revenue_led": ["rev"], "cost_led": ["cos", "opex"], "growth_outpacing_cost": ["rev", "cos", "opex"], "growth_absorbed": ["rev", "cos", "opex"], "below_line_led": ["nonop", "syn"]}
    leads = [(k, L["summary"]["lead"]) for k, L in payload["lenses"].items() if L["available"]]
    step("summary leads drill to the level of their claim", all(b["drill"]["ids"] == want[b["claim"]] for _, b in leads if b["claim"] in want), "; ".join(f"{k}:{b['claim']}" for k, b in leads))
    lie = json.loads(json.dumps(payload))
    L0 = lie["lenses"]["MTD_budget"]
    L0["summary"]["lead"]["claim"] = "growth_outpacing_cost"
    errs = validate_payload(lie)
    step("a lead that contradicts the numbers is refused", any("contradicts the numbers" in e for e in errs))
    # v1.6: the department is named only when the driver spans departments; remainders list their members; each run-rate rule carries its own path
    from finance.synthesis import spans_departments
    one = {"comparable": True, "rows": [{"name": "900 - Admin", "movement": 247880.42}, {"name": "No department", "movement": 5000}, {"name": "500 - Finance", "movement": -0.88}], "other": None}
    two = {"comparable": True, "rows": [{"name": "200 - Sales", "movement": -436000}, {"name": "300 - Marketing", "movement": -40000}], "other": None}
    step("a single department (others moved by cents) is not named as where the movement sits", not spans_departments(one) and spans_departments(two))
    named = [(L, a) for L in payload["lenses"].values() if L["available"] for a in L.get("actions", [])
             if any(".by_department.rows[" in n["source"] for n in a["ask"]["numbers"])]
    step("department named in an ask only where the driver spans departments",
         all(spans_departments(L["reconciliation"][a["subject_ref"]]["by_department"]) for L, a in named), f"{len(named)} asks name a department")
    oth = [rc["other"] for L in payload["lenses"].values() if L["available"] for rc in L["reconciliation"].values() if rc.get("other")]
    step("every 'other accounts' row lists the accounts it groups", all(len(o["items"]) == o["count"] and abs(sum(i["movement"] for i in o["items"]) - o["movement"]) < 0.02 for o in oth), f"{len(oth)} remainders")
    sens = payload["outlook"]["lines"]["ebitda"]["mechanical"]["sensitivity"]
    step("each run-rate rule carries its own monthly path and gaps", all(len(x["path"]) == payload["outlook"]["lines"]["ebitda"]["remaining_months"] and "gap_vs_budget" in x for x in sens if x["value"] is not None)
         and len({round(x["value"]) for x in sens if x["value"] is not None}) > 1)
    st = selftest(html_path)
    if st is None:
        print("SKIP self-test: no Chrome / Edge found")
        return
    step("self-test ran without page errors", not st["errors"], "; ".join(st["errors"])[:200])
    step("month labels read Oct '26, never 202 '26", not st["bad_labels"] and "Oct '26" in st["dom"], ", ".join(st["bad_labels"]))
    step("Plan vs month is gone and By subsidiary is hidden against budget", st.get("plan_vs_month") is False and st.get("sub_on_budget") is False, f"{st.get('plan_vs_month')} {st.get('sub_on_budget')}")
    rs = st.get("rule_switch") or {}
    step("picking a run-rate rule updates the Outlook headline and picker", rs.get("after") == rs.get("want") and rs.get("before") != rs.get("after") and rs.get("select") == rs.get("rule"), json.dumps(rs))
    step("the run-rate info button opens the definition", st.get("rr_info") is True)
    gv = payload["outlook"].get("gap_view") or {}
    if gv.get("available"):                       # needs the full-year budget; the sample stops at the as-of month, PROD exercises this
        step("the full-year bridge and the gap panel follow the rule", rs.get("bridge_changed") and rs.get("gap_after") == rs.get("gap_want") and rs.get("gap_before") != rs.get("gap_after"), json.dumps({k: rs.get(k) for k in ("gap_before", "gap_after", "gap_want")}))
        gcat = st.get("gap_cat") or {}
        step("the gap panel's category list switches the drivers and total", gcat.get("total") == gcat.get("want"), json.dumps(gcat))
    else:
        step("without a full-year budget the gap panel says why", "remaining months cannot be set against it" in st["dom"])
    dr = st.get("drawer_rule") or {}
    step("a rule picked in the run-rate drawer updates the tab", dr.get("rule") == "period_flat" and dr.get("sub"), json.dumps(dr))
    step("gap view: operating drivers add up to the bridge's remaining step for every rule", not gv.get("available") or all(
         abs(rec["totals"]["ebitda"] - next(x for x in payload["outlook"]["lines"]["ebitda"]["mechanical"]["sensitivity"] if x["rule"] == k)["remaining_effect"]) < 1
         for k, rec in gv["rules"].items()), str(gv.get("reason", "")))
    step("By account and By department start collapsed", st.get("side_collapsed") and not any(st["side_collapsed"]), str(st.get("side_collapsed")))
    ox = st.get("other_expand") or {}
    if ox:                                             # the sample's drivers are small; PROD exercises this
        step("an 'other' row expands to its accounts", ox.get("hidden0") and ox.get("shown") and ox.get("rows", 0) > 0, json.dumps(ox))
    step("no overlapping chart labels on any tab", not st["overlaps"], "; ".join(st["overlaps"][:3]))
    tl = st.get("tilt") or []
    step("the Adjusted EBITDA bridge labels are tilted and clear each other", any(t.get("id") == "wf-drv" for t in tl) and all(t.get("clear") for t in tl), json.dumps(tl))
    cm = st.get("commentary") or {}
    step("What this means shows on every view (Drivers and Outlook)", st.get("meaning_missing") == [], json.dumps(st.get("meaning_missing")))
    dom = st.get("dom") or ""
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", dom, flags=re.S)
    eb_bad = re.findall(r".{0,40}\b(?:ebitda|Ebitda)\b.{0,20}", " ".join(st.get("ebitda_titles") or []) + " " + body)
    step("EBITDA is written in capitals on the page and in the EBITDA drawers",
         not eb_bad and len(st.get("ebitda_titles") or []) == 2 and st["ebitda_titles"][0].startswith("Adjusted EBITDA")
         and not any(t.startswith("error") for t in st["ebitda_titles"]), json.dumps(eb_bad[:5] or st.get("ebitda_titles")))
    prose = []
    def _strings(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k not in ("source", "id", "ref", "drill", "evidence_refs", "subject_ref"):
                    _strings(v)
        elif isinstance(o, list):
            for v in o:
                _strings(v)
        elif isinstance(o, str) and " " in o:
            prose.append(o)
    _strings(payload)
    eb_prose = [s[:80] for s in prose if re.search(r"\b(?:ebitda|Ebitda)\b", s)]
    step("EBITDA is written in capitals in every engine sentence", not eb_prose, json.dumps(eb_prose[:5]))
    sl = re.search(r'<section class="sgn" id="signLegend".*?</section>', dom, re.S)
    step("the sign and colour legend sits open above How to read this page (favourable, unfavourable, in line, negative amount)",
         bool(sl) and dom.find('id="signLegend"') < dom.find('class="gls-d"') and "<details" not in sl.group(0)
         and all(f'data-t="{t}"' in sl.group(0) for t in ("fav", "unf", "neu", "lvl")), sl.group(0)[:200] if sl else "missing")
    step("drillable commentary: 3-5 bullets beside the bridge (By driver and To net income) and on the Outlook",
         all(3 <= cm.get(k, 0) <= 5 for k in ("driver", "ni")) and cm.get("ni_head", "").startswith("Net income") and cm.get("link_opens")
         and (not (payload.get("outlook") or {}).get("state") == "calculated" or 3 <= cm.get("outlook", 0) <= 5), json.dumps(cm))
    asm = st.get("assumptions") or {}
    step("the Assumptions dropdown sits under How to read this page with every rule", asm.get("present") and asm.get("after_glossary") and asm.get("rows", 0) >= 30, json.dumps(asm))
    step("the data age stays out of the header (it is a data check and an assumption)", st.get("age_chip") is False)
    code, log = run(["finance_brief.py", payload_path, "summary_pack", "--lens", "MTD_py"])
    step("the brief's summary pack carries sources and the rules", code == 0 and '"source": "lenses[MTD_py].lines[ni].variance"' in log and "observation, then meaning" in log, log[:120] if code else "")
    # 1.4.0 engine rules
    m = payload["meta"]["materiality"]
    step("thresholds scale with the window: month x months, LTM twelve times the month", m["by_window"]["MTD"]["months"] == 1 and m["by_window"]["LTM"]["months"] == 12
         and abs(m["by_window"]["LTM"]["executive_abs"] - max(round(m["executive_abs"] * 12, -2), 100)) < 1 and all(x["materiality"]["months"] == x["months"] for x in payload["lenses"].values() if x["available"]),
         json.dumps({w: v["executive_abs"] for w, v in m["by_window"].items()}))
    flips = [a for x in payload["lenses"].values() if x["available"] for a in x["accounts"] if a.get("sign_flip")]
    step("a sign flip carries no percentage (dollar test only)", all(a["variance_pct"] is None for a in flips), f"{len(flips)} flips")
    Y = payload["lenses"]["YTD_py"]
    oo = Y["one_offs"]
    step("the planted one-off gain is named in the year-to-date lead with net income without it",
         oo["named"] and oo["named"][0]["test"] == "single_posting" and "Extinguishment" in oo["named"][0]["name"] and "Excluding the" in Y["summary"]["lead"]["text"]
         and abs(next(l for l in Y["lines"] if l["id"] == "ni")["variance"] - oo["named_total"] - oo["underlying_variance"]) < 0.02, Y["summary"]["lead"]["text"][-160:])
    ex = payload["outlook"].get("one_offs_excluded") or []
    step("the one-off month is taken out of the run-rate and listed", any("Extinguishment" in x["name"] for x in ex) and all("one-off months taken out" in x["how"] for x in payload["outlook"]["lines"]["ni"]["mechanical"]["sensitivity"]), f"{len(ex)} excluded")
    wt = next(c for c in payload["qc"]["checks"] if c["id"] == "window_tie_out")
    step("quarter, YTD and LTM are built from TOTAL_MTD; the view's own window columns are not read",
         wt["result"] == ("PASS" if next(c for c in payload["qc"]["checks"] if c["id"] == "governed_reconciliation")["result"] == "PASS" else "NOT_RUN") and "sum of TOTAL_MTD" in wt["detail"] and not wt.get("items"), wt["detail"][:160])
    step("target dates are the build date plus ten business days", all(a["date"]["note"].startswith("build date + 10 business days") for a in payload["lenses"][payload["meta"]["primary_lens"]["id"]]["actions"]) and payload["meta"]["target_date_rule"] == "build date + 10 business days")
    step("freshness is noted beyond 30 days", any(c["id"] == "data_freshness" for c in payload["qc"]["checks"]) and payload["meta"]["data_age_warn_days"] == 30)
    lint = json.loads(json.dumps(payload)); lint["lenses"]["MTD_py"]["story"]["lead"]["text"] += " This is driven by demand."
    step("engine prose with causal wording is refused by the invariants", any("causal wording in engine text" in e for e in validate_payload(lint)))
    step("with no bar selected the side panels show All accounts", st.get("default_panel") == "all", str(st.get("default_panel")))
    sb = payload["lenses"]["MTD_budget"]["reconciliation"]["d:opex:acct-6000"].get("by_subsidiary")
    step("budget held on one entity: the subsidiary split shows actuals, not variances", sb and not sb["comparable"] and sb["foots_on"] == "actual")
    py = payload["lenses"]["MTD_py"]["reconciliation"]["d:opex:acct-6000"].get("by_subsidiary")
    step("against prior year the subsidiary split shows variances that foot", py and py["comparable"] and abs(sum(r["movement"] for r in py["rows"]) - py["total"]["movement"]) < 0.02)
    bs = st.get("bridge_sync") or {}
    step("a bridge bar re-targets the usual-range and By-subsidiary panels", bs.get("driver") and bs.get("select") == bs.get("driver") and bs.get("runrate"), json.dumps(bs))
    step("drill tables stay inside their panel", not st.get("overflow"), "; ".join(st.get("overflow") or [])[:200])
    step("no drill row shows a zero movement", not st.get("zero_rows"), "; ".join(st.get("zero_rows") or [])[:200])
    step("the lead bullet opens its evidence with a reconciling table", bool(st.get("drill_title")) and st.get("drill_has_table"), str(st.get("drill_title")))
    step("a summary bullet opens its full sentence above the evidence", st.get("drill_intro") is True)
    step("decisions are short questions that open the full question above the evidence", st.get("ask_words") and all(n <= 12 for n in st["ask_words"]) and st.get("ask_intro") is True, json.dumps({"words": st.get("ask_words"), "intro": st.get("ask_intro"), "title": st.get("ask_title")}))
    html_src = open(html_path, encoding="utf-8").read()
    step("one fixed theme: no dark-mode rules in the page", "prefers-color-scheme" not in html_src and 'content="light only"' in html_src)
    # levels below L4 (contract 1.5.0)
    H = payload["lenses"]["YTD_py"]["hierarchy"]
    cogs = H.get("d:cos:recurring-cogs") or {"nodes": []}
    names = {n["name"]: n for n in cogs["nodes"]}
    step("L6 = L5 collapses: Web Hosting is one L5 node with no L6 child, and no node repeats its parent's name",
         "Web Hosting" in names and not names["Web Hosting"]["children"] and cogs["levels"] == ["L5"]
         and all(n["name"].casefold() != "recurring cogs" for n in cogs["nodes"]), json.dumps({k: [c["name"] for c in v["children"]] for k, v in names.items()}))
    step("a level that repeats L4 is collapsed: Non-Recurring COGS carries no sub-group", "d:cos:non-recurring-cogs" not in H)
    rev = H.get("d:rev:recurring-revenue") or {"nodes": []}
    saas = next((n for n in rev["nodes"] if n["name"] == "SaaS - Subscription"), None)
    step("revenue drills L4 > L5 > L6 > account: SaaS - Subscription holds the product lines, each with its accounts",
         saas is not None and rev["levels"] == ["L5", "L6"] and {c["name"] for c in saas["children"]} >= {"Platform - recurring"}
         and all(c["accounts"] for c in saas["children"]), json.dumps([c["name"] for c in (saas or {"children": []})["children"]]))
    pls = {x["name"]: x for x in payload["lenses"]["YTD_py"]["product_lines"]["items"]}
    step("an empty member is left out, never zero-filled: Legacy Product has no node and no product line in 2026, yet its account is in the payload",
         "Legacy Product" not in pls and not any(n["name"] == "Legacy Product" for d in H.values() for n in d["nodes"] for n in [n] + n["children"]) and any(a["number"] == "4200" for a in payload["accounts"]))
    rl = next(l for l in payload["lenses"]["YTD_py"]["lines"] if l["id"] == "rev")
    step("product lines foot to revenue", abs(sum(x["actual_po"] or 0 for x in pls.values()) - rl["actual_po"]) < 0.02 and abs(sum(x["movement"] or 0 for x in pls.values()) - rl["movement"]) < 0.02)
    bad = json.loads(json.dumps(payload)); bad["lenses"]["YTD_py"]["hierarchy"]["d:rev:recurring-revenue"]["nodes"][0]["movement"] += 100
    step("I13: a sub-group that does not foot to its driver is refused", any("do not foot to the parent" in e for e in validate_payload(bad)))
    bad2 = json.loads(json.dumps(payload)); bad2["lenses"]["YTD_py"]["hierarchy"]["d:rev:recurring-revenue"]["nodes"][0]["name"] = "Recurring Revenue"
    step("I13: a level that repeats its parent is refused", any("repeats its parent" in e for e in validate_payload(bad2)))
    step("QC reports the L5 and L6 footing controls", {"l5_footing", "l6_footing"} <= {c["id"] for c in payload["qc"]["checks"]} and all(c["result"] == "PASS" for c in payload["qc"]["checks"] if c["id"] in ("l5_footing", "l6_footing")))
    code, log = run(["finance_brief.py", payload_path, "driver", "--id", "d:rev:recurring-revenue", "--lens", "YTD_py"])
    step("the brief's driver op exposes the L5 / L6 path with citable sources", code == 0 and '"hierarchy"' in log and '"id": "d:rev:recurring-revenue/saas-subscription"' in log and "how_to_cite" in log, log[:120] if code else "")
    code, log = run(["finance_brief.py", payload_path, "account", "--id", next(a["id"] for a in payload["accounts"] if a["number"] == "4000"), "--lens", "YTD_py"])
    step("the page drills L4 > L5 > L6 > account and a collapsed level hides its descendants", st.get("hier_chain") == ["L5", "L6", "account"] and st.get("hier_collapse_hides_all") is True, json.dumps(st.get("hier_chain")))
    step("the Drivers tab carries no product-line or opex sub-group panel (sub-groups live in the driver drill)", st.get("removed_panels") is True)
    step("a sub-group opens its own drawer", st.get("node_drawer") is True)
    aw = st.get("acct_waterfall") or {}
    step("the account waterfall shows at most three named accounts plus Other, with the names in a key and none on the axis",
         1 <= aw.get("named", 0) <= 3 and aw.get("key_rows", 0) <= 4 and aw.get("names_on_axis") is False, json.dumps(aw))
    step("the brief's account op exposes the path down to L6", code == 0 and '"l6": "Platform - recurring"' in log and 'children[d:rev:recurring-revenue/saas-subscription/platform-recurring]' in log, log[:120] if code else "")
    step("every summary bullet is a short paragraph (head + at most 48 words)", st.get("bullet_words") and all(n <= 60 for n in st["bullet_words"]), str(st.get("bullet_words")))
    step("every engine bullet carries a short line without figures", all(b.get("short") and len(b["short"].split()) <= 15 and not re.search(r"\d", b["short"]) for x in payload["lenses"].values() if x["available"] for b in [x["summary"]["lead"]] + x["summary"]["insights"] + ([x["summary"]["year"]] if x["summary"].get("year") else [])))


def sign_and_budget_checks(wb, out, base, step):
    """A budget load that stores expenses with the opposite sign must give the same variances; an incomplete
    budget must be flagged, open the page on prior year and render the budget note."""
    is_rev = lambda r: str(r.get("COA_MAPPING_L3") or "").strip().lower() == "revenue"
    gov = governed_file(wb, os.path.join(out, "governed.json"))
    flipped = variant_rows(wb, os.path.join(out, "rows-budget-flipped.json"), lambda r, v: v if is_rev(r) else -v)
    p1 = os.path.join(out, "payload-budget-flipped.json")
    code, log = run(["analyze_finance.py", "--rows", flipped, "--governed", gov, "--out", p1])
    step("analyze (budget expenses stored with the opposite sign)", code == 0, log.strip().splitlines()[-1][:160] if code else "")
    if code == 0:
        f = json.load(open(p1, encoding="utf-8"))
        same = all(abs((f["lenses"][k]["bridge"]["end"]["value"] - f["lenses"][k]["bridge"]["start"]["value"])
                       - (base["lenses"][k]["bridge"]["end"]["value"] - base["lenses"][k]["bridge"]["start"]["value"])) < 1
                   for k in ("MTD_budget", "YTD_budget") if f["lenses"][k]["available"])
        step("budget sign detected per measure: variances unchanged", same and f["meta"]["sign_convention"]["mismatch"] == ["budget"])
        step("sign mismatch reported in QC", any(c["id"] == "sign_mismatch" for c in f["qc"]["checks"]))
    thin = variant_rows(wb, os.path.join(out, "rows-budget-thin.json"), lambda r, v: v * 0.2 if str(r.get("COA_MAPPING_L3") or "").strip().lower() == "cost of sales" else v)
    p2 = os.path.join(out, "payload-budget-thin.json")
    code, log = run(["analyze_finance.py", "--rows", thin, "--governed", gov, "--out", p2])
    step("analyze (incomplete cost-of-sales budget)", code == 0, log.strip().splitlines()[-1][:160] if code else "")
    if code == 0:
        t = json.load(open(p2, encoding="utf-8"))
        step("unreliable budget flagged; page opens on prior year (the default)",
             not t["meta"]["budget_check"]["reliable"] and t["meta"]["primary_lens"]["basis"] == "py"
             and any(c["id"] == "budget_reliability" and c["result"] == "WARN" for c in t["qc"]["checks"]))
        h = os.path.join(out, "budget-thin.html")
        code, log = run(["render_finance_dashboard.py", "--payload", p2, "--out", h, "--allow-missing-review"])
        step("render (incomplete budget)", code == 0, log.strip().splitlines()[-1][:120] if code else "")
        if code == 0:
            exe, herrs = headless_check(h, False)
            if exe is not None:
                step("headless DOM budget-thin.html", not herrs, "; ".join(herrs[:4]))
                dom = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--dump-dom", "--virtual-time-budget=6000",
                                      "file:///" + os.path.abspath(h).replace("\\", "/")], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
                step("budget note on the Outlook tab", "Budget not meaningful" in dom)



def memo_files(payload, folder, name="Zyxwq Consulting Ltd", tamper=False):
    """Synthetic GL memo files from a payload: each account-month split into a payroll run and vendor accruals (the
    amounts tie to the actuals), plus in the as-of month a prior-month accrual reversal and a named vendor invoice
    that net to zero. Profit-oriented amounts, as TOTAL_IS_CONVERTED_AMT is."""
    import csv as _csv
    import datetime as _dt
    os.makedirs(folder, exist_ok=True)
    P = payload["meta"]["periods"]
    k1 = payload["meta"]["as_of"]["idx"]
    mon = lambda lab: _dt.date(int(lab[:4]), int(lab[5:7]), 1).strftime("%b%y")
    files = []
    for k in range(0, k1 + 1):
        p = P[k]
        prev = P[k - 1]["label"] if k else p["label"]
        rows = []
        for a in payload["accounts"]:
            v = a["series"]["actual"][k]
            if v is None or v == 0:
                continue
            po = v / a["display_sign"]
            key, sub = a["keys"][0], a["subsidiaries"][0]
            sub = "" if sub == "Group level (no subsidiary)" else sub
            rows.append([p["start"], sub, key, "ACTUAL", f"{mon(p['label'])} Monthly payroll run #6006{k:04d}", round(po * 0.6, 2), 2])
            rows.append([p["start"], sub, key, "ACTUAL", f"{mon(p['label'])} Vendor Accruals", round(po - round(po * 0.6, 2), 2), 1])
        if k == k1 and rows:
            r0 = rows[0]
            rows.append([p["start"], r0[1], r0[2], "ACTUAL", f"{mon(prev)} Vendor Accruals reversal", 50000.0, 1])
            rows.append([p["start"], r0[1], r0[2], "ACTUAL", f"Invoice {name}", -50000.0 + (7777.0 if tamper else 0.0), 1])
        path = os.path.join(folder, f"memo-{p['label']}.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["PERIOD_START_DATE", "SUBSIDIARY_NAME", "CHART_OF_ACCOUNT_KEY", "SOURCE_TYPE", "MEMO", "TOTAL_IS_CONVERTED_AMT", "TRANSACTION_LINE_COUNT"])
            w.writerows(rows)
        files.append(path)
    return files


def memo_checks(wb, out, payload, step):
    """GL memos: reconciled to the actuals, themed, tables foot, names kept out of the review and off the page."""
    from finance.common import resolve_path
    folder = os.path.join(out, "memos")
    files = memo_files(payload, folder)
    pm = os.path.join(out, "finance_payload_memos.json")
    code, log = run(["analyze_finance.py", "--workbook", wb, "--out", pm, "--expect-accounts", "18", "--memos"] + files)
    step("memos: build with --memos", code == 0, log.strip().splitlines()[-1][:160] if log.strip() else "")
    if code != 0:
        print(log); return
    p = json.load(open(pm, encoding="utf-8"))
    errs = validate_payload(p)
    step("memos: payload invariants hold (memo tables add up to the lens)", not errs, "; ".join(errs[:4]))
    M = p["memos"]
    qc = {c["id"]: c["result"] for c in p["qc"]["checks"]}
    step("memos: reconciled and reported in QC", M.get("available") and qc.get("gl_memos") == "PASS", json.dumps(M.get("reconciliation")))
    L = p["lenses"]["MTD_py"]
    me = L["memo_evidence"]
    step("memos: every lens with its months in the extract carries memo evidence", me.get("available") and all((x.get("memo_evidence") or {}).get("available") for k, x in p["lenses"].items() if x["available"] and k.startswith(("MTD", "QTD", "YTD"))))
    d = next(x for x in L["drivers"] if x["id"] in me["drivers"])
    t = me["drivers"][d["id"]]
    step("memos: a month's themes collapse ('Sep26 Vendor Accruals' and 'Aug26 Vendor Accruals' are one theme)",
         sum(1 for x in t["themes"] if x["label"].lower() == "vendor accruals") == 1, json.dumps([x["label"] for x in t["themes"]]))
    step("memos: categories add up to the driver", abs(sum(c["actual"] or 0 for c in t["categories"]) + sum(x["actual"] for x in t["themes"] if x["id"] in ("rounding", "unmatched")) - d["actual"]) <= 0.05)
    step("memos: the planted vendor name is a restricted term", "Zyxwq" in M["restricted_terms"], ", ".join(M["restricted_terms"][:8]))
    rev = [(lid, x) for lid, tt in me["accounts"].items() for x in tt["themes"] if "accrual_reversal" in x["tags"]]
    step("memos: an accrual naming the prior month is tagged accrual_reversal", bool(rev))
    bad_files = memo_files(payload, os.path.join(out, "memos_bad"), tamper=True)
    code, log = run(["analyze_finance.py", "--workbook", wb, "--out", os.path.join(out, "bad_memos.json"), "--expect-accounts", "18", "--memos"] + bad_files)
    step("memos: a memo extract that does not reconcile is refused", code != 0 and "does not reconcile" in log, log.strip()[:160])
    diag = example_diagnosis(p)
    step("memos: the example diagnosis is admitted on a memo payload", not validate_diagnosis(p, diag)[0], "; ".join(validate_diagnosis(p, diag)[0][:3]))
    def mut(fn):
        d2 = json.loads(json.dumps(diag)); fn(d2); return validate_diagnosis(p, d2)[0]
    step("memos: a vendor name from a memo in the review is refused", any("comes from a GL memo" in e for e in mut(lambda x: x["findings"][0]["statements"][0].update({"text": x["findings"][0]["statements"][0]["text"] + " The invoice is from Zyxwq."}))))
    step("memos: a document number in the review is refused", any("document number" in e for e in mut(lambda x: x["readout"]["summary"]["bullets"][1].update({"detail": x["readout"]["summary"]["bullets"][1]["detail"] + " See journal #60063661."}))))
    aid, th = rev[0]
    ref = f"lenses[MTD_py].memo_evidence.accounts[{aid}].themes[{th['id']}]"
    resolve_path(p, ref)
    timing_fact = {"state": "observed_fact", "text": "The line memos show a prior-month accrual reversed in the month, a timing movement.", "numbers": [], "evidence_refs": [ref]}
    no_ref = dict(timing_fact, evidence_refs=[f"lenses[MTD_py].accounts[{aid}]"])
    step("memos: 'timing' is admitted when a cited memo theme is an accrual reversal, refused without it",
         not any("timing" in e for e in mut(lambda x: x["findings"][0]["statements"].append(timing_fact)))
         and any("timing" in e for e in mut(lambda x: x["findings"][0]["statements"].append(no_ref))))
    dp = os.path.join(out, "diag_memos.json")
    json.dump(diag, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
    ytd = example_diagnosis(p, "YTD_py")
    yp = os.path.join(out, "diag_memos_ytd.json")
    json.dump(ytd, open(yp, "w", encoding="utf-8"), ensure_ascii=False)
    html = os.path.join(out, "memos.html")
    code, log = run(["render_finance_dashboard.py", "--payload", pm, "--diagnosis", dp, yp, "--out", html])
    page = open(html, encoding="utf-8").read() if code == 0 and os.path.exists(html) else ""
    step("memos: the page renders and carries no memo text, name or evidence block",
         code == 0 and "Zyxwq" not in page and "memo_evidence" not in page and "Vendor Accruals reversal" not in page and "payroll run" not in page, log.strip()[-160:])

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder for the outputs (default: a temp folder)")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder")
    ap.add_argument("--scale", action="store_true", help="also run the ~1,700-account size check against the 16 MB Artifact limit (a few minutes)")
    a = ap.parse_args()
    out = a.out or tempfile.mkdtemp(prefix="sda-fin-")
    os.makedirs(out, exist_ok=True)
    failed = []
    def step(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail else ""))
        if not ok:
            failed.append(name)
    code, log = run(["make_sample_data.py", os.path.join(out, "sample-data")])
    step("sample workbooks", code == 0, log.strip().splitlines()[-1] if log.strip() else "")
    wb = os.path.join(out, "sample-data", "finance_sample.xlsx")
    payload_path = os.path.join(out, "finance_payload.json")
    code, log = run(["analyze_finance.py", "--workbook", wb, "--out", payload_path, "--expect-accounts", "18"])
    step("analyze", code == 0, log.strip().splitlines()[-1][:160] if log.strip() else "")
    if code != 0:
        print(log); return 1
    payload = json.load(open(payload_path, encoding="utf-8"))
    errs = validate_payload(payload)
    step("payload invariants", not errs, "; ".join(errs[:5]))
    L = payload["lenses"][payload["meta"]["primary_lens"]["id"]]
    step("bridge reconciles in every lens", all(x["bridge"]["control"]["reconciles"] for x in payload["lenses"].values() if x["available"]))
    def bridge_share_sums(x):
        drv = {d["id"]: d for d in x["drivers"]}
        return [round(sum(drv[s["id"]].get("share_of_abs_variance") or 0 for s in steps), 4)
                for steps in (x["bridge"]["steps"], x["bridge"]["to_net_income"]["steps"]) if steps]
    bss = {k: bridge_share_sums(x) for k, x in payload["lenses"].items() if x["available"]}
    step("driver shares add up to 100% on the Adjusted EBITDA bridge and on the steps to net income, in every lens",
         all(abs(s - 1) <= 0.01 for v in bss.values() for s in v), json.dumps(bss))
    step("planted October overspends surface", {"d:opex:acct-6300", "d:cos:recurring-cogs"} <= {i["subject_ref"] for i in L["insights"] if i["kind"] == "driver"},
         ", ".join(i["label"] for i in L["insights"] if i["kind"] == "driver"))
    lay = payload["lenses"]["MTD_budget"]["layers"]          # the analytical layers are Month vs Budget only
    step("page opens on Month vs Prior year by default", payload["meta"]["primary_lens"]["id"] == "MTD_py", payload["meta"]["primary_lens"]["id"])
    step("execution-dominant month", lay["primary_layer"] == "operational", lay["primary_layer"])
    diag = example_diagnosis(payload)
    diag_path = os.path.join(out, "diagnosis.json")
    json.dump(diag, open(diag_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    derrs, dwarns = validate_diagnosis(payload, diag)
    step("diagnosis gate admits the example", not derrs, "; ".join(derrs[:5]))
    bad = dict(diag); bad["findings"] = json.loads(json.dumps(diag["findings"])); bad["findings"][0]["statements"][0]["text"] += " That is $999k because of timing."
    berrs, _ = validate_diagnosis(payload, bad)
    step("diagnosis gate refuses an unregistered figure and causal wording", len(berrs) >= 2, "; ".join(berrs[:2]))
    loud = json.loads(json.dumps(diag)); loud["readout"]["conclusions"][0]["insight"] = "Costs up $38k because of marketing"
    step("diagnosis gate refuses an insight heading with figures or causal wording", bool(validate_diagnosis(payload, loud)[0]))
    def mut(fn):
        d2 = json.loads(json.dumps(diag)); fn(d2); return validate_diagnosis(payload, d2)[0]
    step("summary gate: a diagnosis without the written summary is refused", any("readout.summary is required" in e for e in mut(lambda d: d["readout"].pop("summary"))))
    step("summary gate: a figure alone is refused", any("figure alone" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"detail": d["readout"]["summary"]["bullets"][1]["numbers"][0]["display"] + " up."}))))
    step("summary gate: a page line over 48 words is refused", any("at most 48 words" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"text": "this line goes on and on " * 12}))))
    step("summary gate: an unregistered figure on the page line is refused", any("unregistered figure(s) in text" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"text": "Costs rose by $800k against the plan."}))))
    step("summary gate: a detail over 130 words is refused", any("at most 130 words" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"detail": d["readout"]["summary"]["bullets"][1]["detail"] + " " + "and so on " * 50}))))
    step("summary gate: an unregistered figure is refused", any("unregistered figure" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"detail": d["readout"]["summary"]["bullets"][1]["detail"] + " That is $999k."}))))
    step("summary gate: a drill that does not exist is refused", any("drill must name" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"drill": {"level": "driver", "ids": ["d:nope"]}}))))
    step("summary gate: a decision that is not a question is refused", any("is a question" in e for e in mut(lambda d: d["readout"]["summary"]["decisions"][0].update({"text": "Review the provision."}))))
    step("summary gate: a page question over 12 words is refused", any("at most 12 words" in e for e in mut(lambda d: d["readout"]["summary"]["decisions"][0].update({"text": "is this a one off or a timing effect or a new level that stays for good?"}))))
    step("summary gate: a figure in the page question is refused", any("carries no figures" in e for e in mut(lambda d: d["readout"]["summary"]["decisions"][0].update({"text": "Is the $800k charge a one-off?"}))))
    step("summary gate: causal wording in a bullet is refused", any("causal wording" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].update({"detail": d["readout"]["summary"]["bullets"][1]["detail"] + " This is because of timing."}))))
    B = lambda d, role: next(b for b in d["readout"]["summary"]["bullets"] if b["role"] == role)
    step("summary gate: a bullet without a narrative role is refused", any("carries a role" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][1].pop("role"))))
    step("summary gate: a summary without a trend bullet is refused", any("missing" in e and "trend" in e for e in mut(lambda d: d["readout"]["summary"].update({"bullets": [b for b in d["readout"]["summary"]["bullets"] if b["role"] != "trend"]}))))
    step("summary gate: roles out of narrative order are refused", any("narrative order" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"].insert(1, d["readout"]["summary"]["bullets"].pop(-1)))))
    def long_page(d):
        for b in d["readout"]["summary"]["bullets"]:
            b.update({"head": "One two three four five six seven eight nine ten", "text": "one two three four five six seven eight nine ten eleven twelve " * 4})
    step("summary gate: a page over 220 words is refused", any("at most 220" in e for e in mut(long_page)))
    step("summary gate: attribution down the hierarchy ('driven by') is admitted", not any("causal wording" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " The result is driven by the lines named here, which the drill shows in full."}))))
    step("summary gate: an unhedged business cause is refused", any("not in the data model" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " Spending rose with new hiring in the sales team this quarter.", "unverified": ["headcount"]}))))
    step("summary gate: a hedged business cause without unverified[] is refused", any("unverified[]" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " Spending may indicate hiring in the sales team, to be confirmed.", "unverified": []}))))
    step("summary gate: a hedged business cause, named and with the data asked for, is admitted", not mut(lambda d: (B(d, "why").update({"detail": B(d, "why")["detail"] + " Spending may indicate hiring in the sales team, to be confirmed.", "unverified": ["headcount"]}),
                                                                                                                 B(d, "attention").update({"data_needed": (B(d, "attention").get("data_needed") or []) + ["headcount by department (HR / Payroll)"]}))))
    step("summary gate: unverified drivers without data_needed on the attention bullet are refused", any("data_needed" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " Spending may indicate hiring, to be confirmed.", "unverified": ["headcount"]}))))
    step("summary gate: 'due to' is admitted only when hedged", any("causal wording" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " The gap is due to the lines named here."})))
         and not any("causal wording" in e for e in mut(lambda d: B(d, "why").update({"detail": B(d, "why")["detail"] + " The gap might be due to accrual phasing, to be confirmed."}))))
    step("drill gate: an account interpretation over 75 words is refused", any("at most 75 words" in e for e in mut(lambda d: d["readout"].update({"account_interpretations": [{"account": payload["lenses"]["MTD_py"]["accounts"][0]["id"], "text": "word " * 80, "numbers": []}]}))))
    step("summary gate: a first bullet not about net income is refused", any("about net income" in e for e in mut(lambda d: d["readout"]["summary"]["bullets"][0].update({"head": "Costs moved.", "text": "Costs moved against the result.", "detail": "Costs moved against the result and the gap sits in spending that management controls this month."}))))
    stale = dict(diag); stale["payload_hash"] = "0" * 64
    step("diagnosis gate refuses a stale hash", bool(validate_diagnosis(payload, stale)[0]))
    code, log = run(["render_finance_dashboard.py", "--payload", payload_path, "--out", os.path.join(out, "baseline.html")])
    step("render refuses without the Month and Year-to-date reviews", code != 0 and '"gate": "review"' in log and "YTD_py" in log, log.strip().splitlines()[-1][:120])
    code, log = run(["render_finance_dashboard.py", "--payload", payload_path, "--out", os.path.join(out, "baseline.html"), "--allow-missing-review"])
    step("render (engine baseline, missing review allowed)", code == 0, log.strip().splitlines()[-1][:120] if code else "")
    ytd = example_diagnosis(payload, "YTD_py")
    ytd_path = os.path.join(out, "diagnosis_ytd.json")
    json.dump(ytd, open(ytd_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    code, log = run(["render_finance_dashboard.py", "--payload", payload_path, "--diagnosis", diag_path, "--out", os.path.join(out, "half.html")])
    step("render refuses with only the Month review", code != 0 and "YTD_py" in log and "MTD_py" not in log.split("missing")[-1], log.strip().splitlines()[-1][:120])
    code, log = run(["render_finance_dashboard.py", "--payload", payload_path, "--diagnosis", diag_path, ytd_path, "--out", os.path.join(out, "diagnosed.html")])
    step("render (with the Month and Year-to-date diagnoses)", code == 0 and '"MTD_py"' in log and '"YTD_py"' in log, log.strip().splitlines()[-1][:120] if code else "")
    for name, exp in (("baseline.html", False), ("diagnosed.html", True)):
        p = os.path.join(out, name)
        if os.path.exists(p):
            e = check_html(p, exp); step(f"html checks {name}", not e, "; ".join(e))
            exe, herrs = headless_check(p, exp)
            if exe is None:
                print("SKIP headless DOM check: " + herrs[0])
            else:
                step(f"headless DOM {name}", not herrs, "; ".join(herrs[:4]))
    for key, label in (("MTD_py", "prior-year lens"), ("YTD_budget", "year-to-date lens")):
        step(f"{label} available", payload["lenses"][key]["available"])
    v15_checks(wb, out, payload, payload_path, os.path.join(out, "baseline.html"), step)
    yes_energy_checks(wb, out, payload, step)
    memo_checks(wb, out, payload, step)
    fiscal_checks(payload, step)
    sign_and_budget_checks(wb, out, payload, step)
    embed_checks(payload_path, [diag_path, ytd_path], out, step)
    if a.scale:
        scale_checks(wb, out, step)
    print(f"\nOutputs in {out}")
    if not a.keep and not a.out:
        shutil.rmtree(out, ignore_errors=True)
    print("\nRESULT: " + ("ALL PASSED" if not failed else "FAILED: " + ", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
