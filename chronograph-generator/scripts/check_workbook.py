#!/usr/bin/env python3
"""Check that an .xlsx will open in Excel without "We found a problem with some content".

    python check_workbook.py <file.xlsx> [--excel auto|on|off]

Structural checks (always): every part parses; every part has a content type; every internal relationship target
exists; no external links; no defined names that are invalid, #REF! or point at another workbook; the workbook view's
firstSheet / activeTab point at a sheet that exists; sheet names are unique and at most 31 characters; no formula
holds #REF! or a reference to another workbook; numeric cells hold numbers; calculation is not manual.
--results (outputs): every formula carries its calculated result.

Excel check (--excel auto, the default): on Windows with Excel installed, the file is opened read-only in a separate
hidden Excel instance (excel_open_check.ps1) and the check fails when Excel cannot open it or writes a repair log.
With --results it also recalculates the workbook in Excel and fails unless Excel's results equal the stored ones
and the workbook opened in automatic calculation.
--excel on makes a missing Excel a failure; --excel off skips it.
Prints one JSON object. Exit codes: 0 clean, 1 problems found.
"""
import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
      "ct": "http://schemas.openxmlformats.org/package/2006/content-types"}
NAME_RE = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.\\]*$")
EXTERNAL_REF_RE = re.compile(r"\[\d+\]")


def _rels_path(part):
    d, f = posixpath.split(part)
    return posixpath.join(d, "_rels", f + ".rels")


def _resolve(base_part, target):
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def check(path, require_results=False):
    """Return a list of problems (empty when the file is clean). require_results: every formula must carry its
    calculated result (an output must read correctly before Excel recalculates)."""
    problems = []
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"not a zip package: {exc}"]
    names = set(z.namelist())
    xml = {}
    for n in names:
        if n.endswith((".xml", ".rels", ".vml")):
            try:
                xml[n] = ET.fromstring(z.read(n))
            except ET.ParseError as exc:
                problems.append(f"{n}: XML does not parse ({exc})")
    ct = xml.get("[Content_Types].xml")
    if ct is None:
        return problems + ["[Content_Types].xml missing"]
    defaults = {e.get("Extension").lower() for e in ct.findall("ct:Default", NS)}
    overrides = {e.get("PartName").lstrip("/") for e in ct.findall("ct:Override", NS)}
    for n in names:
        if n.endswith("/") or n == "[Content_Types].xml":
            continue
        if n not in overrides and n.rsplit(".", 1)[-1].lower() not in defaults:
            problems.append(f"{n}: no content type")
    for o in overrides:
        if o not in names:
            problems.append(f"content type declared for a missing part: {o}")
    # relationships
    for n in [x for x in names if x.endswith(".rels")]:
        root = xml.get(n)
        if root is None:
            continue
        owner = n.replace("_rels/", "")[:-5] if n != "_rels/.rels" else ""
        for rel in root.findall("pr:Relationship", NS):
            if rel.get("TargetMode") == "External":
                problems.append(f"{n}: external relationship to {rel.get('Target')}")
                continue
            tgt = _resolve(owner, rel.get("Target"))
            if tgt not in names:
                problems.append(f"{n}: relationship target missing: {tgt}")
    if any(n.startswith("xl/externalLinks/") for n in names):
        problems.append("the package carries external links (xl/externalLinks)")
    wbx = xml.get("xl/workbook.xml")
    if wbx is None:
        return problems + ["xl/workbook.xml missing"]
    sheets = wbx.findall("m:sheets/m:sheet", NS)
    if not sheets:
        problems.append("the workbook has no sheets")
    seen = set()
    for s in sheets:
        nm = s.get("name") or ""
        if len(nm) > 31 or nm.lower() in seen or re.search(r"[\[\]:*?/\\]", nm):
            problems.append(f"invalid or duplicate sheet name: {nm!r}")
        seen.add(nm.lower())
    if wbx.find("m:externalReferences", NS) is not None:
        problems.append("workbook.xml lists external references")
    calc = wbx.find("m:calcPr", NS)
    if calc is not None and calc.get("calcMode") == "manual":
        problems.append("the workbook is set to manual calculation: Excel shows stale formula results until F9")
    for v in wbx.findall("m:bookViews/m:workbookView", NS):
        for attr in ("firstSheet", "activeTab"):
            val = v.get(attr)
            if val is not None and not (0 <= int(val) < len(sheets)):
                problems.append(f"workbookView {attr}={val} but the workbook has {len(sheets)} sheet(s)")
    bad_names = []
    for dn in wbx.findall("m:definedNames/m:definedName", NS):
        nm, txt = dn.get("name") or "", dn.text or ""
        if not NAME_RE.match(nm) or "#REF!" in txt or EXTERNAL_REF_RE.search(txt) or "[" in nm:
            bad_names.append(nm)
        lsid = dn.get("localSheetId")
        if lsid is not None and not (0 <= int(lsid) < len(sheets)):
            bad_names.append(nm)
    if bad_names:
        problems.append(f"{len(bad_names)} broken defined name(s), e.g. {bad_names[:5]}")
    # sheet contents
    rels = xml.get(_rels_path("xl/workbook.xml"))
    targets = {r.get("Id"): _resolve("xl/workbook.xml", r.get("Target")) for r in (rels.findall("pr:Relationship", NS) if rels is not None else [])}
    for s in sheets:
        part = targets.get(s.get("{%s}id" % NS["r"]))
        root = xml.get(part) if part else None
        if root is None:
            problems.append(f"sheet {s.get('name')!r}: part missing")
            continue
        for sv in root.findall("m:sheetViews/m:sheetView", NS):
            has_pane = sv.find("m:pane", NS) is not None
            panes = [sel.get("pane") for sel in sv.findall("m:selection", NS)]
            if (not has_pane and any(p not in (None, "topLeft") for p in panes)) or len(panes) != len(set(panes)):
                problems.append(f"sheet {s.get('name')!r}: selections refer to panes the view does not have ({panes})")
        bad_f, bad_v, no_result = [], [], []
        for c in root.iter("{%s}c" % NS["m"]):
            f = c.find("m:f", NS)
            if f is not None and f.text and ("#REF!" in f.text or EXTERNAL_REF_RE.search(f.text)):
                bad_f.append(c.get("r"))
            v = c.find("m:v", NS)
            if require_results and f is not None and (v is None or v.text in (None, "")):
                no_result.append(c.get("r"))
            if c.get("t") in (None, "n") and v is not None and v.text not in (None, ""):
                try:
                    float(v.text)
                except ValueError:
                    bad_v.append(c.get("r"))
        if bad_f:
            problems.append(f"sheet {s.get('name')!r}: {len(bad_f)} formula(s) with #REF! or another workbook, e.g. {bad_f[:5]}")
        if bad_v:
            problems.append(f"sheet {s.get('name')!r}: {len(bad_v)} numeric cell(s) holding text, e.g. {bad_v[:5]}")
        if no_result:
            problems.append(f"sheet {s.get('name')!r}: {len(no_result)} formula(s) saved without a result (shown blank or stale until Excel recalculates), e.g. {no_result[:5]}")
    return problems


def excel_available():
    if os.name != "nt" or not shutil.which("powershell"):
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application"))
        return True
    except OSError:
        return False


def excel_open(path, timeout=240):
    """Open the file in a hidden Excel instance. Returns {opened, repaired, error, log}."""
    script = os.path.join(HERE, "excel_open_check.ps1")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                              "-Paths", os.path.abspath(path)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"opened": False, "repaired": None, "error": f"Excel did not answer within {timeout}s"}
    line = next((l for l in reversed(out.stdout.strip().splitlines()) if l.startswith("{")), None)
    if not line:
        return {"opened": False, "repaired": None, "error": (out.stderr or out.stdout).strip()[:500] or "no output from Excel check"}
    res = json.loads(line)
    if res.get("log"):
        res["log"] = re.sub(r"\s+", " ", res["log"])[:1500]
    return res


def excel_finalize(path, timeout=300):
    """Have Excel recalculate and save the workbook in place (excel_finalize.ps1). A file Excel saved after a full
    calculation loads without stale cells in a manual-calculation session. Excel records the folder it saved from
    (x15ac:absPath); that local path is removed again. Returns {saved, error}."""
    import tempfile
    script = os.path.join(HERE, "excel_finalize.ps1")
    # work in the system temp folder: a synced folder (OneDrive) can hold a fresh file locked, and Excel then
    # cannot open it for writing
    work = tempfile.mkdtemp(prefix="chrono-xl-")
    src = os.path.join(work, "in.xlsx")
    dst = os.path.join(work, "out.xlsx")
    shutil.copyfile(path, src)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                              "-Src", src, "-Dst", dst], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        shutil.rmtree(work, ignore_errors=True)
        return {"saved": False, "error": f"Excel did not answer within {timeout}s"}
    line = next((l for l in reversed(out.stdout.strip().splitlines()) if l.startswith("{")), None)
    res = json.loads(line) if line else {"saved": False, "error": (out.stderr or out.stdout).strip()[:500]}
    if not res.get("saved") or not os.path.exists(dst):
        shutil.rmtree(work, ignore_errors=True)
        return {"saved": False, "error": res.get("error") or "Excel did not write the file"}
    tmp = os.path.join(work, "final.xlsx")
    with zipfile.ZipFile(dst) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/workbook.xml":
                data = re.sub(rb"<mc:AlternateContent[^>]*><mc:Choice Requires=\"x15\"><x15ac:absPath [^>]*/></mc:Choice></mc:AlternateContent>", b"", data)
            zout.writestr(item, data)
    shutil.copyfile(tmp, path)
    shutil.rmtree(work, ignore_errors=True)
    return {"saved": True, "error": None}


def stored_results(path):
    """{cell: stored result} for every formula cell of the first sheet."""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = {}
    for c in root.iter("{%s}c" % NS["m"]):
        if c.find("m:f", NS) is not None:
            v = c.find("m:v", NS)
            out[c.get("r")] = float(v.text) if v is not None and v.text not in (None, "") else None
    return out


def compare_recalc(path, rc):
    """Excel's recalculated values vs the stored results: the count of cells that differ by more than half a cent."""
    excel_vals = rc.pop("values", None) or {}
    stored = stored_results(path)
    bad = []
    for coord, mine in stored.items():
        theirs = excel_vals.get(coord)
        if mine is None or not isinstance(theirs, (int, float)) or abs(theirs - mine) > 0.000005 + 1e-9 * abs(mine):
            bad.append({"cell": coord, "stored": mine, "excel": theirs})
    extra = sorted(set(excel_vals) - set(stored))
    examples = bad[:5] + [{"cell": e, "stored": None, "excel": excel_vals[e]} for e in extra[:5]]
    rc.update({"compared": len(stored), "mismatches": len(bad) + len(extra), "examples": examples[:5]})
    return rc


def run(path, excel="auto", require_results=False):
    problems = check(path, require_results)
    result = {"file": path, "structure": "PASS" if not problems else "FAIL", "problems": problems}
    if excel == "off":
        result["excel"] = "SKIPPED"
    elif not excel_available():
        result["excel"] = "UNAVAILABLE"
        if excel == "on":
            problems.append("Excel is not available on this machine (--excel on)")
    else:
        res = excel_open(path)
        rc = compare_recalc(path, res["recalc"]) if res.get("recalc") else {}
        res["recalc"] = rc
        ok = res.get("opened") and not res.get("repaired")
        if ok and require_results and rc.get("mismatches", 1) != 0:
            ok = False
            problems.append(f"Excel's own recalculation differs from the stored results in {rc.get('mismatches')} cell(s), e.g. {rc.get('examples')}")
        if ok and require_results and rc.get("stale_in_manual_session") != "none":
            ok = False
            problems.append("in a manual-calculation Excel session the file loads with stale cells (shown struck through): it was not saved by Excel after a full calculation")
        result["excel"] = "PASS" if ok else "FAIL"
        result["excel_detail"] = res
        if not res.get("opened") or res.get("repaired"):
            problems.append("Excel " + ("repaired the file: " + (res.get("log") or "") if res.get("repaired") else "could not open the file: " + str(res.get("error"))))
    result["status"] = "CLEAN" if not problems else "PROBLEMS"
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--excel", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--results", action="store_true", help="require stored formula results and an Excel recalculation that matches them")
    a = ap.parse_args()
    res = run(a.path, a.excel, a.results)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["status"] == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
