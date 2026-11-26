"""Payload invariants. The renderer refuses a payload that fails any of them;
the diagnosis gate refuses a diagnosis written against a payload whose
analysis hash has changed."""
from . import CONTRACT_VERSION
from .common import is_num, resolve_path, unregistered_tokens, sha256_of
from .diagnosis import CAUSAL, FORBIDDEN

TOL = 0.02


def _num_ok(payload, n):
    """A registered number must resolve to its value (after scale / transform) within tolerance."""
    if n.get("kind") == "literal":
        return True
    try:
        v = resolve_path(payload, n["source"])
    except (KeyError, IndexError, TypeError):
        return n["source"].endswith(".actions") and isinstance(n.get("value"), (int, float))
    if isinstance(v, list) and n["source"].endswith(".actions"):
        return len(v) == n["value"]
    if not is_num(v):
        return False
    if n.get("scale") is not None:
        v = v * n["scale"]
    if n.get("transform") == "abs":
        v = abs(v)
    if not is_num(n.get("value")):
        return False
    tol = 0.5 if n.get("kind") == "money" else 0.0006 if n.get("kind") in ("pct", "pts") else 0.00006 if n.get("kind") == "bps" else 0.5
    return abs(v - n["value"]) <= tol


def check_prose(payload, text, numbers, where, errs):
    """Engine prose: every figure registered, and the same wording lint the diagnosis gate applies to the model."""
    bad = unregistered_tokens(text, numbers)
    if bad:
        errs.append(f"{where}: unregistered figure(s) in text: {', '.join(bad)}")
    m = CAUSAL.search(text)
    if m:
        errs.append(f"{where}: causal wording in engine text ('{m.group(0)}'): the engine states what moved, never why")
    for rx, label in FORBIDDEN:
        if rx.search(text):
            errs.append(f"{where}: forbidden phrase in engine text: {label}")
    for n in numbers:
        if not _num_ok(payload, n):
            errs.append(f"{where}: registered figure {n.get('display')} does not resolve to {n.get('source')}")


def _foot(t, where, errs):
    """A drill table foots on movement when the comparator is held at that level, otherwise on the actual."""
    key = t["foots_on"]
    parts = sum(r[key] or 0.0 for r in t["rows"]) + ((t.get("other") or {}).get(key) or 0.0)
    if abs(parts - (t["total"][key] or 0.0)) > TOL:
        errs.append(f"{where}: rows do not foot to the total {key}")
    o = t.get("other")
    if o and "items" in o and (len(o["items"]) != o["count"] or abs(sum(x[key] or 0.0 for x in o["items"]) - (o.get(key) or 0.0)) > TOL):
        errs.append(f"{where}: the remainder's members do not foot to it")


def _claim_contradiction(claim, L, lines, payload):
    """Re-check a summary claim against the lens figures; returns why it is wrong, or None."""
    v = lambda k: lines[k]["variance"]
    rv, nv, ev, ebv = v("rev"), v("ni"), v("ebitda"), v("ebm")
    cv, below = L["totals"]["cost_variance"], L["totals"]["below_line_variance"]
    if claim == "revenue_led" and not (is_num(rv) and is_num(cv) and abs(rv) >= abs(cv) and is_num(nv) and (rv > 0) == (nv > 0)):
        return "revenue is not the largest contributor in the direction of net income"
    if claim == "cost_led" and not (is_num(rv) and is_num(cv) and abs(cv) > abs(rv)):
        return "costs are not the largest contributor"
    if claim == "growth_outpacing_cost" and not (is_num(ev) and ev > 0 and is_num(ebv) and ebv >= 0):
        return "EBITDA or its margin did not rise"
    if claim == "below_line_led" and not (is_num(below) and is_num(ev) and abs(below) > abs(ev)):
        return "the below-the-line move is smaller than the EBITDA move"
    if claim == "margin_up" and not (is_num(ebv) and ebv > 0):
        return "the margin did not rise"
    if claim == "margin_down" and not (is_num(ebv) and ebv < 0):
        return "the margin did not fall"
    if claim in ("trend_continuing", "trend_reversal", "trend_new", "trend_easing"):
        from .summary import trend_reading, trend_windows
        ws = trend_windows(payload["lenses"], L["basis"])
        val = lambda w: next((x["variance"] for x in payload["lenses"][f"{w}_{L['basis']}"]["lines"] if x["id"] == "ni"), None)
        got = trend_reading(val("MTD"), [val(w) for w in ws[1:]], L["materiality"]["monitoring_abs"]) if ws else None
        if got != claim[6:]:
            return f"net income across the windows reads {got or 'not material'}, not {claim[6:]}"
    if claim == "margin_mixed":
        M = payload["lenses"].get(f"MTD_{L['basis']}") or {}
        mv = next((x["variance"] for x in M.get("lines", []) if x["id"] == "ebm"), None)
        if not (is_num(mv) and is_num(ebv) and (mv > 0) != (ebv > 0)):
            return "the window and the latest month move the same way"
    return None


def validate_payload(payload):
    errs = []
    if payload.get("contract_version") != CONTRACT_VERSION:
        errs.append(f"contract_version must be {CONTRACT_VERSION}")
        return errs
    lenses = payload.get("lenses") or {}
    if set(lenses) != {f"{w}_{b}" for w in ("MTD", "QTD", "YTD", "LTM") for b in ("budget", "py")}:
        errs.append("lenses must hold the eight window x comparator combinations")
    M = payload["meta"]["materiality"]
    for key, L in lenses.items():
        if not L.get("available"):
            continue
        LP = f"lenses[{key}]"
        m = L.get("materiality") or M
        if m is not M and (m.get("months") != L.get("months") or any(abs(m[f"{k}_abs"] - max(round(M[f"{k}_abs"] * m["months"], -2), 100.0)) > 0.5 for k in ("executive", "management", "monitoring"))):
            errs.append(f"{LP}: materiality is not the month's thresholds scaled to {L.get('months')} month(s)")
        lines = {x["id"]: x for x in L["lines"]}
        # I1 statement foots (po): gp = rev + cos, ebitda = gp + opex, ni = ebitda + syn + nonop
        po = lambda k: lines[k]["actual_po"] or 0.0
        for sub, parts in (("gp", ("rev", "cos")), ("ebitda", ("gp", "opex")), ("ni", ("ebitda", "syn", "nonop"))):
            if abs(po(sub) - sum(po(p) for p in parts)) > TOL:
                errs.append(f"{LP}: {sub} does not foot to {'+'.join(parts)}")
        # sections = sum of accounts = sum of drivers
        for sec in ("rev", "cos", "opex", "syn", "nonop"):
            acc = sum(a["actual_po"] or 0.0 for a in L["accounts"] if a["section"] == sec)
            drv = sum(d["actual_po"] or 0.0 for d in L["drivers"] if d["section"] == sec)
            if abs(acc - po(sec)) > TOL or abs(drv - po(sec)) > TOL:
                errs.append(f"{LP}: section {sec} does not equal the sum of its accounts / drivers")
        # I2 bridge reconciles
        b = L["bridge"]
        if is_num(b["start"]["value"]) and is_num(b["end"]["value"]):
            tot = b["start"]["value"] + sum(s["value"] for s in b["steps"])
            if abs(tot - b["end"]["value"]) > TOL or not b["control"]["reconciles"]:
                errs.append(f"{LP}: bridge does not reconcile (residual {b['control']['residual']})")
            for s in b["steps"]:
                if abs(sum(c["amount"] for c in s["contributions"]) - s["value"]) > TOL:
                    errs.append(f"{LP}: step {s['id']} contributions do not sum to the step")
            ni = b["to_net_income"]
            if not ni["control"]["reconciles"]:
                errs.append(f"{LP}: net income extension does not reconcile")
        # I3 tiers recomputed
        for a in L["accounts"] + L["drivers"]:
            v, p = a["variance"], a["variance_pct"]
            if not is_num(v):
                want = "immaterial"
            elif abs(v) >= m["executive_abs"]:
                want = "executive"
            elif abs(v) >= m["management_abs"] and (p is None or abs(p) * 100 >= m["management_pct"]):
                want = "management"
            elif abs(v) >= m["monitoring_abs"]:
                want = "monitoring"
            else:
                want = "immaterial"
            if a["tier"] != want:
                errs.append(f"{LP}: tier of {a['id']} is {a['tier']}, recomputed {want}")
        # I4 shares
        sh = sum(a["share_of_abs_variance"] or 0 for a in L["accounts"] if a.get("share_of_abs_variance") is not None)
        if sh and abs(sh - 1) > 0.01:
            errs.append(f"{LP}: account shares of absolute variance sum to {sh:.3f}")
        # driver shares add up to 100% within each bridge (Adjusted EBITDA; steps to net income)
        for scope in sorted({d.get("share_scope") for d in L["drivers"] if d.get("share_scope")}):
            sh = sum(d.get("share_of_abs_variance") or 0 for d in L["drivers"] if d.get("share_scope") == scope)
            if sh and abs(sh - 1) > 0.01:
                errs.append(f"{LP}: {scope} driver shares of movement sum to {sh:.3f}")
        # I5 layers
        lay = L.get("layers") or {}
        if lay.get("state") == "calculated" and not lay["control"]["reconciles"]:
            errs.append(f"{LP}: layers do not reconcile (residual {lay['control']['residual']})")
        # I6 prose provenance
        X = L.get("explanations") or {}
        for rec in X.get("accounts", []):
            check_prose(payload, rec["text"]["expanded"], rec["numbers"], f"{LP}.explanations.accounts[{rec['id']}]", errs)
        for rec in X.get("drivers", []):
            check_prose(payload, rec["text"]["concise"], rec["numbers"], f"{LP}.explanations.drivers[{rec['id']}]", errs)
        for rec in X.get("lines", []):
            check_prose(payload, rec["text"]["concise"], rec["numbers"], f"{LP}.explanations.lines[{rec['id']}]", errs)
        s = X.get("summary") or {}
        if s:
            check_prose(payload, " ".join([s["outcome"], s["layer_qualification"], s["activity"]]), s["numbers"], f"{LP}.explanations.summary", errs)
        for ins in L.get("insights", []):
            check_prose(payload, " ".join(st["text"] for st in ins["statements"]), ins["numbers"], f"{LP}.insights[{ins['id']}]", errs)
        for kd in L.get("kpi_diagnoses", []):
            check_prose(payload, kd["answer"] + " " + (kd.get("outlook") or ""), kd["numbers"], f"{LP}.kpi_diagnoses[{kd['kpi']}]", errs)
        ro = L.get("readout") or {}
        if ro:
            check_prose(payload, " ".join([ro["answers"]["ahead_or_behind"], ro["answers"]["what_drove"]]), ro["numbers"], f"{LP}.readout", errs)
        st = L.get("story")
        if not st:
            errs.append(f"{LP}: story missing")
        else:
            for name, piece in (("lead", st["lead"]), ("growth", st["growth"]), ("accounts", st["accounts"])):
                check_prose(payload, piece["text"], piece["numbers"], f"{LP}.story.{name}", errs)
            for piece in st["lines"]:
                check_prose(payload, piece["text"], piece["numbers"], f"{LP}.story.lines[{piece['id']}]", errs)
            pat = st["growth"].get("pattern")
            if pat:
                try:
                    if resolve_path(payload, pat["source"]).get("reading") != pat["reading"]:
                        errs.append(f"{LP}.story.growth: pattern reading differs from {pat['source']}")
                except (KeyError, IndexError, TypeError, AttributeError):
                    errs.append(f"{LP}.story.growth: pattern source {pat['source']} does not resolve")
        hl = L.get("headline") or {}
        for name, sl in (hl.get("slots") or {}).items():
            if sl["display"] not in hl["text"]:
                errs.append(f"{LP}.headline: slot {name} display missing from text")
            try:
                v = resolve_path(payload, sl["source"])
            except (KeyError, IndexError, TypeError):
                errs.append(f"{LP}.headline: slot {name} source does not resolve")
                continue
            if isinstance(v, list):
                v = len(v)
            if is_num(sl["value"]) and is_num(v) and abs(v - sl["value"]) > 0.5:
                errs.append(f"{LP}.headline: slot {name} value differs from its source")
        # I10 drill tables foot: accounts (top N + remainder) = driver movement; department / class / subsidiary splits foot
        acc_by = {a["id"]: a for a in L["accounts"]}
        drv_by = {d["id"]: d for d in L["drivers"]}
        for a in L["accounts"]:
            mv, ap_, cp = a.get("movement"), a["actual_po"], a["comparator_po"]
            want = (ap_ - cp) if is_num(ap_) and is_num(cp) else ap_ if is_num(ap_) else (-cp if is_num(cp) else None)
            if (mv is None) != (want is None) or (is_num(mv) and abs(mv - want) > TOL):
                errs.append(f"{LP}: account {a['id']} movement does not equal actual minus comparator")
        for did, rc in (L.get("reconciliation") or {}).items():
            d = drv_by.get(did)
            if d is None:
                errs.append(f"{LP}.reconciliation[{did}]: unknown driver"); continue
            parts = sum(i["movement"] for i in rc["items"]) + ((rc.get("other") or {}).get("movement") or 0.0)
            if not is_num(rc["total"]) or abs(parts - rc["total"]) > TOL:
                errs.append(f"{LP}.reconciliation[{did}]: account movements do not sum to the total")
            ro = rc.get("other")
            if ro and (len(ro.get("items") or []) != ro["count"] or abs(sum(i["movement"] for i in ro["items"]) - ro["movement"]) > TOL):
                errs.append(f"{LP}.reconciliation[{did}]: the other accounts do not foot to the remainder")
            if is_num(d["variance"]) and abs(rc["total"] - d["variance"]) > TOL:
                errs.append(f"{LP}.reconciliation[{did}]: total differs from the driver variance")
            if abs(sum(acc_by[x]["movement"] or 0.0 for x in d["accounts"]) - (rc["total"] or 0.0)) > TOL:
                errs.append(f"{LP}.reconciliation[{did}]: driver accounts do not foot to the total")
            dep = rc.get("by_department")
            if dep:
                _foot(dep, f"{LP}.reconciliation[{did}].by_department", errs)
                key = "movement" if dep["comparable"] else "actual"
                ref = d["movement"] if key == "movement" else d["actual"]
                if is_num(ref) and abs((dep["total"][key] or 0.0) - ref) > TOL:
                    errs.append(f"{LP}.reconciliation[{did}].by_department: total {key} differs from the driver")
        for did, rc in (L.get("reconciliation") or {}).items():
            sb = rc.get("by_subsidiary")
            if sb and did in drv_by:
                _foot(sb, f"{LP}.reconciliation[{did}].by_subsidiary", errs)
                ref = drv_by[did]["movement"] if sb["comparable"] else drv_by[did]["actual"]
                if is_num(ref) and abs((sb["total"][sb["foots_on"]] or 0.0) - ref) > TOL:
                    errs.append(f"{LP}.reconciliation[{did}].by_subsidiary: total differs from the driver")
        if L.get("by_subsidiary"):
            _foot(L["by_subsidiary"], f"{LP}.by_subsidiary", errs)
        for aid, sp in (L.get("splits") or {}).items():
            a = acc_by.get(aid)
            for dim, t in sp.items():
                _foot(t, f"{LP}.splits[{aid}].{dim}", errs)
                if a and is_num(a["actual"]) and abs((t["total"]["actual"] or 0.0) - a["actual"]) > TOL:
                    errs.append(f"{LP}.splits[{aid}].{dim}: actuals do not foot to the account")
        # I11 summary bullets: provenance, a drill target that resolves, and a claim that agrees with the numbers
        sm = L.get("summary")
        if not sm:
            errs.append(f"{LP}: summary missing")
        else:
            for b in [sm["lead"]] + sm["insights"] + ([sm["year"]] if sm.get("year") else []):
                where = f"{LP}.summary.{b['id']}"
                check_prose(payload, b["head"] + " " + b["text"], b["numbers"], where, errs)
                if not b.get("short") or len(b["short"].split()) > 15:
                    errs.append(f"{where}: short line missing or over 15 words")
                dr = b.get("drill") or {}
                ok_ids = {"section": {"rev", "cos", "opex", "syn", "nonop", "ebitda"}, "line": set(lines), "driver": set(drv_by), "outlook": {"mechanical", "ytd"}}.get(dr.get("level"))
                if ok_ids is None or not dr.get("ids") or any(i not in ok_ids for i in dr["ids"] + dr.get("support", [])):
                    errs.append(f"{where}: drill target {dr} does not resolve")
                bad = _claim_contradiction(b.get("claim"), L, lines, payload)
                if bad:
                    errs.append(f"{where}: lead '{b['head']}' contradicts the numbers ({bad})")
        # I12 one-off register: named items are register items, totals add up, underlying = net income variance less the named amounts
        oo = L.get("one_offs")
        if not oo:
            errs.append(f"{LP}: one_offs missing")
        else:
            keys = {(x["account"], x["month"]) for x in oo["items"]}
            if any((x["account"], x["month"]) not in keys for x in oo["named"]) or oo["named_count"] != len(oo["named"]) or oo["count"] != len(oo["items"]):
                errs.append(f"{LP}.one_offs: named items are not register items or the counts differ")
            if abs(sum(x["amount"] for x in oo["named"]) - oo["named_total"]) > TOL or abs(sum(x["amount"] for x in oo["items"]) - oo["total"]) > TOL:
                errs.append(f"{LP}.one_offs: totals do not add up")
            nv = lines["ni"]["variance"]
            if oo["named"] and is_num(nv) and (not is_num(oo["underlying_variance"]) or abs(nv - oo["named_total"] - oo["underlying_variance"]) > TOL):
                errs.append(f"{LP}.one_offs: underlying variance is not net income less the named one-offs")
            for x in oo["items"]:
                if abs((x["actual"] - x["reference"]) - x["amount"]) > TOL or abs(x["amount"]) < x["significance_floor"] - TOL or (x["test"] == "outlier_month" and not (x["actual"] < x["trailing_min"] or x["actual"] > x["trailing_max"])):
                    errs.append(f"{LP}.one_offs: {x['account']} {x['month']} does not meet the one-off test it claims")
        # I13 levels below L4: every sub-group foots to its parent (movement and both sides), no level repeats its parent, product lines foot to revenue
        for did, h in (L.get("hierarchy") or {}).items():
            d = drv_by.get(did)
            if d is None:
                errs.append(f"{LP}.hierarchy[{did}]: unknown driver"); continue

            def check(nodes, parent, where):
                for k in ("actual_po", "comparator_po", "movement"):
                    parts = [n[k] for n in nodes if is_num(n[k])]
                    want = parent[k]
                    if parts or is_num(want):
                        if not is_num(want) and parts:
                            if abs(sum(parts)) > TOL:
                                errs.append(f"{where}: sub-groups carry {k} but the parent does not")
                        elif abs(sum(parts) - (want or 0.0)) > TOL:
                            errs.append(f"{where}: sub-groups do not foot to the parent {k} ({sum(parts)} vs {want})")
                for n in nodes:
                    if n["name"].strip().casefold() == str(parent.get("name") or parent.get("label") or "").strip().casefold():
                        errs.append(f"{where}: level {n['level']} repeats its parent's name ({n['name']}); it should have been collapsed")
                    if n["children"]:
                        check(n["children"], n, f"{where}.nodes[{n['id']}]")
            check(h["nodes"], {"actual_po": d["actual_po"], "comparator_po": d["comparator_po"], "movement": d["movement"], "label": d["label"]}, f"{LP}.hierarchy[{did}]")
            if h["levels"] and any(l not in ("L5", "L6") for l in h["levels"]):
                errs.append(f"{LP}.hierarchy[{did}]: unknown level in {h['levels']}")
        pl = L.get("product_lines")
        if pl:
            rev = lines["rev"]
            for k in ("actual_po", "movement"):
                parts = sum(x[k] or 0.0 for x in pl["items"])
                if is_num(rev[k]) and abs(parts - rev[k]) > TOL:
                    errs.append(f"{LP}.product_lines: items do not foot to revenue {k} ({parts} vs {rev[k]})")
            ids = [x["id"] for x in pl["items"]]
            if len(ids) != len(set(ids)):
                errs.append(f"{LP}.product_lines: duplicate product line ids")
        # I7 actions reference drivers that exist
        dids = {d["id"] for d in L["drivers"]}
        for a in L.get("actions", []):
            if a.get("ask"):
                check_prose(payload, a["ask"]["text"], a["ask"]["numbers"], f"{LP}.actions[{a['id']}].ask", errs)
        for a in L.get("actions", []):
            if a["subject_ref"] not in dids:
                errs.append(f"{LP}.actions[{a['id']}]: unknown driver {a['subject_ref']}")
    # I8 outlook identity
    o = payload.get("outlook") or {}
    if o.get("state") == "calculated":
        for lid, rec in o["lines"].items():
            if is_num(rec["fy_budget"]) and is_num(rec["ytd"]["variance"]) and is_num(rec["mechanical"]["remaining_effect"]):
                if abs(rec["fy_budget"] + rec["ytd"]["variance"] + rec["mechanical"]["remaining_effect"] - rec["mechanical"]["value"]) > TOL:
                    errs.append(f"outlook.lines.{lid}: identity does not hold")
            for x in rec["mechanical"].get("sensitivity", []):
                if is_num(x["value"]) and x.get("path") is not None:
                    if len(x["path"]) != rec["remaining_months"] or abs(rec["ytd"]["actual"] + sum(x["path"]) - x["value"]) > max(TOL, 0.01 * max(1, len(x["path"]))):
                        errs.append(f"outlook.lines.{lid}: rule {x['rule']} path does not add up to its full year")
                    if is_num(rec["fy_budget"]) and is_num(rec["ytd"]["variance"]) and is_num(x.get("remaining_effect")) and abs(rec["fy_budget"] + rec["ytd"]["variance"] + x["remaining_effect"] - x["value"]) > TOL:
                        errs.append(f"outlook.lines.{lid}: rule {x['rule']} identity does not hold")
        gv = o.get("gap_view") or {}
        for rule, rec in (gv.get("rules") or {}).items() if gv.get("available") else ():
            for key in ("ebitda", "ni"):
                x = next((y for y in o["lines"][key]["mechanical"]["sensitivity"] if y["rule"] == rule), None)
                if x and is_num(x.get("remaining_effect")) and abs(rec["totals"][key] - x["remaining_effect"]) > max(TOL, 0.01 * len(rec["drivers"])):
                    errs.append(f"outlook.gap_view.{rule}: drivers do not add up to the {key} remaining-months effect ({rec['totals'][key]} vs {x['remaining_effect']})")
    # I14 GL memo tables foot to the lens: themes (top, other, unmatched) add up to the actual and the comparator
    if (payload.get("memos") or {}).get("available"):
        if not isinstance(payload["memos"].get("restricted_terms"), list):
            errs.append("memos.restricted_terms missing: the diagnosis gate needs it to keep memo names off the page")
        for key, L in lenses.items():
            me = L.get("memo_evidence") if L.get("available") else None
            if not me or not me.get("available"):
                continue
            tabs = [("net_income", me["net_income"])] + [(f"drivers[{k}]", t) for k, t in me["drivers"].items()] + [(f"accounts[{k}]", t) for k, t in me["accounts"].items()]
            for name, t in tabs:
                th = t["themes"]
                tol = max(TOL, 0.01 * len(th))
                if abs(sum(x["actual"] or 0.0 for x in th) - (t["actual_total"] or 0.0)) > tol:
                    errs.append(f"lenses[{key}].memo_evidence.{name}: memo themes do not add up to the actual")
                if t.get("comparator_total") is not None and abs(sum(x["comparator"] or 0.0 for x in th) - t["comparator_total"]) > tol:
                    errs.append(f"lenses[{key}].memo_evidence.{name}: memo themes do not add up to the comparator")
                cs = t.get("categories") or []
                extra = sum(x["actual"] or 0.0 for x in th if x["id"] in ("unmatched", "rounding"))
                if abs(sum(c["actual"] or 0.0 for c in cs) + extra - (t["actual_total"] or 0.0)) > max(TOL, 0.01 * (len(cs) + len(th))):
                    errs.append(f"lenses[{key}].memo_evidence.{name}: memo categories do not add up to the actual")
            for did, t in me["drivers"].items():
                d = next((x for x in L["drivers"] if x["id"] == did), None)
                if d is None or abs((d["actual"] or 0.0) - (t["actual_total"] or 0.0)) > TOL:
                    errs.append(f"lenses[{key}].memo_evidence.drivers[{did}]: total does not equal the driver's actual")
    # I9 hash
    body = {k: v for k, v in payload.items() if k not in ("analysis_hash", "diagnosis")}
    if payload.get("analysis_hash") != sha256_of(body):
        errs.append("analysis_hash does not match the payload content (edited or stale)")
    return errs
