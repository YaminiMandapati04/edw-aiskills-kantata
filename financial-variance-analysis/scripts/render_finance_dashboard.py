#!/usr/bin/env python3
"""Render the three-tab finance diagnostic (Summary, Drivers, Outlook), renderer 1.7.0: payload (+ admitted diagnoses, one per view; Month and Year to date on the page's basis are required unless --allow-missing-review) -> one offline HTML file.

Usage:
  python render_finance_dashboard.py --payload work/finance_payload.json --out outputs/budget_vs_actuals_readout.html [--diagnosis work/diagnosis.json]

The renderer refuses an invalid payload or a diagnosis that fails the admission gate, and writes no HTML
in that case. The pinned template, CSS and JS in artifacts/finance_analytics/ are never modified per
engagement; everything variable travels in the payload. The page embeds a read-view of the payload
(finance/embed.py): fields the page never reads are dropped, and when the page would still exceed the
16 MB Artifact limit, immaterial accounts lose their drill-down detail; a page still over the limit is
refused. The full payload on disk is unchanged. The output is written atomically.
Exit codes: 0 rendered, 1 refused.
"""
import argparse
import datetime as dt
import html as html_escape
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "artifacts", "finance_analytics"))
MARKERS = {"title": "<!-- SDA:TITLE -->", "css": "<!-- SDA:CSS -->", "banner": "<!-- SDA:BANNER -->", "payload": "<!-- SDA:PAYLOAD -->", "js": "<!-- SDA:JS -->"}
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from finance import RENDERER_VERSION                      # noqa: E402
from finance.validate import validate_payload             # noqa: E402
from finance.diagnosis import validate_diagnosis          # noqa: E402
from finance.embed import embed_view                      # noqa: E402


def fail(msg, **extra):
    print(json.dumps({"status": "REFUSED", "reason": msg, **extra}, indent=2, ensure_ascii=False))
    sys.exit(1)


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        fail(f"cannot read pinned asset {path}: {exc}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--out", required=True, help="output .html file, or a folder (file named budget_vs_actuals_readout.html: no month in the name, so a scheduled run rewrites the same file)")
    ap.add_argument("--diagnosis", nargs="*", default=[], help="diagnosis.json file(s) written against this payload, one per view; each is admitted only if it passes the gate")
    ap.add_argument("--allow-missing-review", action="store_true", help="publish without the required Month and Year-to-date reviews (the build output lists which are missing)")
    ap.add_argument("--no-trim", action="store_true", help="embed the full payload (tests only: proves the trimmed page renders the same)")
    args = ap.parse_args()
    try:
        with open(args.payload, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        fail(f"payload is not readable JSON: {exc}")
    errs = validate_payload(payload)
    if errs:
        fail("payload failed its invariants; no HTML written", gate="invariant", reasons=errs[:40])
    diags = {}
    for path in args.diagnosis:
        try:
            with open(path, encoding="utf-8") as fh:
                diag = json.load(fh)
        except Exception as exc:
            fail(f"diagnosis {path} is not readable JSON: {exc}")
        derrs, dwarns = validate_diagnosis(payload, diag)
        if derrs:
            fail(f"diagnosis {os.path.basename(path)} refused by the admission gate; fix the diagnosis, never the payload; no HTML written", gate="diagnosis", reasons=derrs[:40], warnings=dwarns[:20])
        key = f"{diag['lens']['window']}_{diag['lens']['basis']}"
        if key in diags:
            fail(f"two diagnoses for the {key} view; keep one")
        diag = dict(diag)
        diag["admitted_at"] = dt.datetime.now().isoformat(timespec="seconds")
        diag["warnings"] = dwarns
        diags[key] = diag
    primary = payload["meta"]["primary_lens"]
    required = [k for k in (f"MTD_{primary['basis']}", f"YTD_{primary['basis']}") if payload["lenses"].get(k, {}).get("available")]
    missing = [k for k in required if k not in diags]
    if missing and not args.allow_missing_review:
        fail("the Month and Year-to-date views need an admitted AI review before the page is published; no HTML written "
             "(write them with finance_brief.py, or pass --allow-missing-review to publish with a visible notice)", gate="review", missing=missing)
    payload["diagnoses"] = diags
    payload["diagnosis"] = diags.get(primary["id"]) or (next(iter(diags.values())) if diags else None)
    payload["review"] = {"required": required, "admitted": sorted(diags), "missing": missing}
    diag = payload["diagnosis"]
    tpl = read(os.path.join(ASSETS, "template.html"))
    for name, marker in MARKERS.items():
        if tpl.count(marker) != 1:
            fail(f"pinned template must contain exactly one {name} marker ({marker})")
    meta = payload["meta"]
    title = " · ".join(x for x in (meta.get("title"), meta.get("as_of_label"), meta["scope"].get("filtered_to") or "all subsidiaries") if x)
    css, js = read(os.path.join(ASSETS, "finance_analytics.css")), read(os.path.join(ASSETS, "finance_analytics.js"))
    page_banner = ""                                   # no status banner on the page (removed by request)

    def build_html(view):
        raw = json.dumps(view, ensure_ascii=False, separators=(",", ":"))
        # "</script>" or "<!--" inside the JSON would break the HTML tokenizer; JSON escapes keep JSON.parse identical
        safe = raw.replace("<", "\\u003c").replace("-->", "--\\u003e")
        if "<" in safe or "-->" in safe:
            fail("payload escaping failed closed")
        return (tpl.replace(MARKERS["title"], html_escape.escape(title, quote=True))
                .replace(MARKERS["css"], "<style>\n%s\n</style>" % css)
                .replace(MARKERS["banner"], page_banner)
                .replace(MARKERS["payload"], '<script id="sda-payload" type="application/json">\n%s\n</script>\n<script>window.__SDA_PAYLOAD__ = JSON.parse(document.getElementById("sda-payload").textContent);</script>' % safe)
                .replace(MARKERS["js"], "<script>\n%s\n</script>" % js))

    # the page embeds a read-view of the validated payload (finance/embed.py), sized for the 16 MB Artifact cap
    html, embed = embed_view(payload, build_html, js=js, trim=not args.no_trim)
    if embed["over_limit"]:
        fail(f"page is {embed['page_bytes']:,} bytes, over the {embed['limit_bytes']:,}-byte Artifact limit even after trimming; no HTML written",
             gate="size", embed=embed, hint="narrow the scope (one subsidiary) or the account set, then re-run analyze and render")
    out = args.out if args.out.lower().endswith(".html") else os.path.join(args.out, "budget_vs_actuals_readout.html")
    out_dir = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".sda-render-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, out)
        tmp = None
    except OSError as exc:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
        fail(f"cannot write {out}: {exc}")
    L = payload["lenses"][meta["primary_lens"]["id"]]
    print(json.dumps({"status": "RENDERED", "out": out, "bytes": len(html.encode("utf-8")), "renderer": RENDERER_VERSION, "offline": True, "external_requests": 0,
                      "as_of": meta["as_of_label"], "primary_lens": L["id"], "diagnosis_admitted": sorted(diags), "review_missing": missing, "diagnosis_warnings": {k: d.get("warnings", []) for k, d in diags.items()},
                      "qc": payload["qc"]["status"], "embed": embed, "note":"Single-file offline HTML. Open directly in a browser; no network access required."}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
