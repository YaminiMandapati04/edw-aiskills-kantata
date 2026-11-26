# Renderer prototype

Prototype renderer variant kept for reference. It is **not** loaded by
`scripts/render_finance_dashboard.py`; the pinned renderer is `../../finance_analytics.{js,css}`.
Earlier variants (v2 to v7) and the Summary wireframes were removed; they are in git history.

| Variant | What it is |
|---|---|
| `v8/` | Renderer restyled on the reference report design system (dark-grey banner, lime accent, mono labels, dark table headers, square corners, light and dark themes) |

Build a page with it:

    python v8/build_v8.py --payload <finance_payload.json> --out <file.html> [--diagnosis <diagnosis.json>]

`build_v8.py` runs the pinned `render_finance_dashboard.py` (same validation, admission gate, banner and
inlining) but points it at the template, CSS and JS in `v8/`.
