#!/usr/bin/env python3
"""Make the CFO Chronograph template safe to open in Excel, and pin it to the row map.

    python clean_template.py --src <original template.xlsx> [--out assets/chronograph_template.xlsx] [--map assets/chronograph_map.json]
    python clean_template.py --src <any broken workbook.xlsx> --out <repaired.xlsx> --no-pin     # repair an older file

Why: the Accel-KKR template carried ~55,000 leftover range names (17,000 of them #REF!, some pointing at workbooks
[3] and [4] that are not linked), a link to a SharePoint workbook, and a workbook view whose firstSheet points at a
sheet that no longer exists. Excel flags any one of these as "We found a problem with some content" and, when the
repair is declined, refuses to open the file; every workbook generated from it inherited the fault.

What it does: keeps only the Actual sheet, removes every defined name and external link, resets the workbook view
to the first sheet, then saves, runs check_workbook.py on the result and records the file's SHA-256 in the map, so
the build refuses any other template. Run it once when the template changes; the build also calls sanitize() on
every output before saving.
Exit codes: 0 written, 1 refused.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_OUT = os.path.join(SKILL, "assets", "chronograph_template.xlsx")
DEFAULT_MAP = os.path.join(SKILL, "assets", "chronograph_map.json")


def sanitize(wb, keep_sheet=None):
    """Remove what makes Excel repair the file. Returns what was removed."""
    removed = {"sheets": [], "defined_names": 0, "sheet_names": 0, "external_links": 0}
    if keep_sheet:
        for name in list(wb.sheetnames):
            if name != keep_sheet:
                del wb[name]
                removed["sheets"].append(name)
    removed["defined_names"] = len(list(wb.defined_names))
    for n in list(wb.defined_names):
        del wb.defined_names[n]
    for ws in wb.worksheets:
        removed["sheet_names"] += len(ws.defined_names)
        ws.defined_names.clear()
        ws.print_title_rows = None
        ws.print_title_cols = None
        ws.print_area = None
    removed["external_links"] = len(wb._external_links)
    wb._external_links = []
    for v in wb.views:
        v.firstSheet = 0
        v.activeTab = 0
    # the template was saved in manual calculation: formulas then show stale or blank values until F9
    from openpyxl.workbook.properties import CalcProperties
    calc = wb.calculation or CalcProperties()
    removed["calc_mode_was"] = calc.calcMode or "auto"
    calc.calcMode = "auto"
    calc.fullCalcOnLoad = True
    wb.calculation = calc
    wb.active = 0
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = ws is wb.worksheets[0]
    return removed


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def refuse(msg, **extra):
    print(json.dumps({"status": "REFUSED", "reason": msg, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="the template as received")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--no-pin", action="store_true", help="repair any workbook (e.g. an older Chronograph file): keep every sheet, leave the skill's template and map alone; --out is required")
    a = ap.parse_args()
    from openpyxl import load_workbook
    import check_workbook
    if a.no_pin and os.path.abspath(a.out) == os.path.abspath(DEFAULT_OUT):
        refuse("--no-pin needs its own --out: it never overwrites the skill's pinned template")
    if os.path.abspath(a.out) == os.path.abspath(a.src):
        refuse("--out must differ from --src: the original is kept")
    wb = load_workbook(a.src)
    if a.no_pin:
        removed = sanitize(wb)
    else:
        with open(a.map, encoding="utf-8") as fh:
            mp = json.load(fh)
        if mp["sheet"] not in wb.sheetnames:
            refuse(f"sheet {mp['sheet']!r} is not in {a.src} ({', '.join(wb.sheetnames)})")
        removed = sanitize(wb, keep_sheet=mp["sheet"])
    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".tpl-", suffix=".xlsx")
    os.close(fd)
    wb.save(tmp)
    problems = check_workbook.check(tmp)
    if problems:
        os.remove(tmp)
        refuse("the cleaned template still fails the workbook check", problems=problems[:20])
    os.replace(tmp, a.out)
    digest = sha256(a.out)
    if a.no_pin:
        print(json.dumps({"status": "WRITTEN", "out": a.out, "removed": removed, "pinned": False,
                          "size_bytes": {"before": os.path.getsize(a.src), "after": os.path.getsize(a.out)}}, indent=2))
        return 0
    with open(a.map, encoding="utf-8") as fh:
        text = fh.read()
    new_text, n = re.subn(r'("template_sha256":\s*)"[^"]*"', lambda m: f'{m.group(1)}"{digest}"', text, count=1)
    if n != 1:
        refuse(f"no template_sha256 entry in {a.map}")
    with open(a.map, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    print(json.dumps({"status": "WRITTEN", "out": a.out, "sha256": digest, "removed": removed,
                      "size_bytes": {"before": os.path.getsize(a.src), "after": os.path.getsize(a.out)}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
