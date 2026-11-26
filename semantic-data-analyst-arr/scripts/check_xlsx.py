#!/usr/bin/env python3
"""Recalculate a workbook and report formula errors.

Usage:  python check_xlsx.py book.xlsx

Recalculation needs LibreOffice (soffice) on PATH or in a standard install
folder. The workbook is converted in a temp folder and the recalculated copy is
scanned for #REF!, #DIV/0!, #NAME? etc. The original file is not modified.
Without LibreOffice the script says so and exits 2: the file is then unchecked.

Exit code 0 = no errors, 1 = errors found, 2 = could not recalculate.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

from openpyxl import load_workbook

ERRORS = ("#REF!", "#DIV/0!", "#NAME?", "#VALUE!", "#N/A", "#NUM!", "#NULL!")


def find_soffice():
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for pat in (r"C:\Program Files\LibreOffice*\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice*\program\soffice.exe"):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


def main():
    if len(sys.argv) != 2:
        print("usage: check_xlsx.py book.xlsx", file=sys.stderr)
        return 2
    src = os.path.abspath(sys.argv[1])
    soffice = find_soffice()
    if not soffice:
        print("LibreOffice not found: formulas were NOT recalculated. Install it, or open the "
              "workbook in Excel and check the total rows.")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, src],
                       check=True, capture_output=True, timeout=120)
        out = os.path.join(tmp, os.path.basename(src))
        wb = load_workbook(out, data_only=True)
        problems = []
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value in ERRORS:
                        problems.append(f"{ws.title}!{c.coordinate}: {c.value}")
    if problems:
        print(f"{len(problems)} formula error(s):")
        for p in problems[:50]:
            print(" -", p)
        return 1
    print("Recalculated: 0 errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
