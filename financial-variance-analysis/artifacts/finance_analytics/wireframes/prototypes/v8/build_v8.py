#!/usr/bin/env python3
"""Prototype v8: renderer 1.3.0 restyled on the reference report design system (dark-grey banner, lime accent, mono labels, dark table headers, square corners, light and dark themes).

    python build_v8.py --payload <finance_payload.json> --out <file.html> [--diagnosis <diagnosis.json>]

Runs the pinned render_finance_dashboard.py (same validation, admission gate, banner and inlining) but points it
at the template, CSS and JS in this folder. The pinned renderer in artifacts/finance_analytics/ is not touched.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "scripts"))
sys.path.insert(0, SCRIPTS)
import render_finance_dashboard as r  # noqa: E402

r.ASSETS = HERE
if __name__ == "__main__":
    sys.exit(r.main())
