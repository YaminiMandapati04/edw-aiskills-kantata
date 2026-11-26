#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from a result bundle.

Usage:  python build_dashboard.py bundle.json out.html [--fonts-dir DIR]

- No external scripts, fonts or network calls; works offline.
- Charts are inline SVG. Every data point carries a native hover tooltip
  (<title>): "<x>: <value>" for line/column/bar, "<step>: <delta>" for bridges.
- Light and dark mode via CSS variables (prefers-color-scheme).
- Tables show provenance (Governed / Derived / Scenario), SUM totals where
  flagged, a capped-rows note, and the SQL in a collapsible block.
- --fonts-dir: folder holding the Messina Sans .otf files (from Fonts.zip's
  Managed/ folder) to embed as base64. Without it the brand fallback stack
  (Calibri / Courier New) is used.

Brand: Accordion. Sharp corners, no shadows or gradients.
"""
import argparse
import base64
import glob
import html
import math
import os
import sys

import bundle as B

esc = html.escape

W = 680
H = 320


# ------------------------------------------------------------------ helpers

def nice_scale(vmin, vmax, n=5):
    if vmin == vmax:
        vmax = vmin + (abs(vmin) * 0.1 or 1)
    span = vmax - vmin
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    lo = math.floor(vmin / step + 1e-9) * step
    hi = math.ceil(vmax / step - 1e-9) * step
    k = int(round((hi - lo) / step))
    return lo, hi, [lo + i * step for i in range(k + 1)]


def axis_label(v, ctype):
    return "0" if abs(v) < 1e-12 else B.fmt(v, ctype)


def badge(prov):
    cls = {"governed": "b-gov", "derived": "b-der", "scenario": "b-sce"}.get(prov, "b-gov")
    return f'<span class="badge {cls}">{esc(B.provenance_label(prov))}</span>'


def num_class(v):
    return " neg" if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0 else ""


def font_faces(fonts_dir):
    if not fonts_dir:
        return ""
    specs = [
        ("MessinaSans-Regular*.otf", "Messina Sans", 400),
        ("MessinaSans-SemiBold*.otf", "Messina Sans", 600),
        ("MessinaSans-Bold*.otf", "Messina Sans", 700),
        ("MessinaSansMono-Regular*.otf", "Messina Sans Mono", 400),
    ]
    out = []
    for pat, fam, wt in specs:
        for path in glob.glob(os.path.join(fonts_dir, pat)):
            with open(path, "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            out.append(f"@font-face{{font-family:'{fam}';font-weight:{wt};"
                       f"src:url(data:font/otf;base64,{data}) format('opentype');}}")
            break
    return "\n".join(out)


# --------------------------------------------------------------- SVG charts

def svg_wrap(inner, height, label):
    return (f'<svg viewBox="0 0 {W} {height}" width="100%" role="img" aria-label="{esc(label)}" '
            f'xmlns="http://www.w3.org/2000/svg">{inner}</svg>')


def x_labels(xs, xpos, y, n):
    longest = max(len(x) for x in xs)
    cap = 14 if longest <= 7 else 10          # short labels (e.g. "Nov-25") fit more per axis
    step = max(1, math.ceil(n / cap))
    rotate = longest > 9 and n > 5
    out = []
    for i, lab in enumerate(xs):
        if i % step:
            continue
        if rotate:
            out.append(f'<text class="ax" x="{xpos(i):.1f}" y="{y + 14}" text-anchor="end" '
                       f'transform="rotate(-30 {xpos(i):.1f} {y + 14})">{esc(lab)}</text>')
        else:
            out.append(f'<text class="ax" x="{xpos(i):.1f}" y="{y + 16}" text-anchor="middle">{esc(lab)}</text>')
    return "".join(out)


def legend(names, palette, kind):
    items, x = [], 0
    for i, nme in enumerate(names):
        cls = f"s{(i % 5) + 1}"
        if kind == "line":
            items.append(f'<g transform="translate({x},0)"><line class="l {cls}" x1="0" y1="-4" x2="14" y2="-4"/>'
                         f'<text class="ax" x="19" y="0">{esc(nme)}</text></g>')
        else:
            items.append(f'<g transform="translate({x},0)"><rect class="f {cls}" x="0" y="-9" width="10" height="10"/>'
                         f'<text class="ax" x="15" y="0">{esc(nme)}</text></g>')
        x += 44 + 7.2 * len(nme)
    return f'<g transform="translate(56,14)">{"".join(items)}</g>'


def chart_svg(b, ch):
    t = B.table_by_id(b, ch["table"])
    xs = [str(v) for v in B.col_values(t, ch["x"])]
    ys = ch["y"]
    ctype = B.col_type(t, ys[0])
    series = [[(v if v is not None else None) for v in B.col_values(t, y)] for y in ys]
    kind = ch["type"]
    n = len(xs)
    multi = len(ys) > 1
    mt = 34 if multi else 14
    mb = 52
    ml, mr = 56, 16
    height = H

    def tip(i, si=0, val=None):
        v = series[si][i] if val is None else val
        base = f"{xs[i]}: {B.fmt(v, ctype)}"
        return f"{base} ({ys[si]})" if multi else base

    # ---- horizontal bars
    if kind == "bar":
        ml = int(min(230, max(70, 12 + 7.2 * max(len(x) for x in xs))))
        mb = 30
        mt = 34 if multi else 12
        height = max(170, mt + mb + 34 * n * (1 if not multi else 1.2))
        allv = [v for s in series for v in s if v is not None]
        lo, hi, ticks = nice_scale(min(0, min(allv, default=0)), max(0, max(allv, default=1)))
        x0, x1, y0, y1 = ml, W - 56, mt, height - mb
        sx = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
        out = []
        for tk in ticks:
            out.append(f'<line class="grid" x1="{sx(tk):.1f}" y1="{y0}" x2="{sx(tk):.1f}" y2="{y1}"/>')
            out.append(f'<text class="ax" x="{sx(tk):.1f}" y="{y1 + 16}" text-anchor="middle">{esc(axis_label(tk, ctype))}</text>')
        band = (y1 - y0) / n
        k = len(ys)
        bh = band * 0.72 / k
        for i, lab in enumerate(xs):
            cy = y0 + (i + 0.5) * band
            out.append(f'<text class="ax" x="{x0 - 8}" y="{cy + 4:.1f}" text-anchor="end">{esc(lab)}</text>')
            for si in range(k):
                v = series[si][i]
                if v is None:
                    continue
                by = cy + (si - (k - 1) / 2) * bh - bh / 2
                xa, xb = sorted((sx(0), sx(v)))
                out.append(f'<rect class="f s{si % 5 + 1}" x="{xa:.1f}" y="{by:.1f}" width="{max(xb - xa, 0.5):.1f}" '
                           f'height="{bh * 0.94:.1f}"><title>{esc(tip(i, si))}</title></rect>')
                out.append(f'<text class="val{num_class(v)}" x="{(xb + 4) if v >= 0 else (xa - 4):.1f}" y="{by + bh * 0.66:.1f}" '
                           f'text-anchor="{"start" if v >= 0 else "end"}">{esc(B.fmt(v, ctype))}</text>')
        out.append(f'<line class="axis" x1="{sx(0):.1f}" y1="{y0}" x2="{sx(0):.1f}" y2="{y1}"/>')
        if multi:
            out.append(legend(ys, B.BAR_PALETTE, "bar"))
        return svg_wrap("".join(out), int(height), ch["title"])

    # ---- vertical charts share y scaling
    if kind == "waterfall":
        totals = set(ch.get("totals") or [])
        vals = [v or 0 for v in series[0]]
        run, bars, ends = 0.0, [], []
        for i, (lab, v) in enumerate(zip(xs, vals)):
            if lab in totals or i == 0:
                bars.append((0, v, "tot"))
                run = v
            else:
                start, run = run, run + v
                bars.append((start, run, "up" if v >= 0 else "down"))
            ends.append(run)
        allv = [p for a in bars for p in a[:2]] + [0]
        lo, hi, ticks = nice_scale(min(allv), max(allv))
    else:
        allv = [v for s in series for v in s if v is not None]
        vmin, vmax = min(allv, default=0), max(allv, default=1)
        if kind != "line" or vmin < 0 or vmin < 0.4 * vmax:
            vmin = min(0, vmin)
        if vmax < 0:
            vmax = 0
        lo, hi, ticks = nice_scale(vmin, vmax)

    x0, x1, y0, y1 = ml, W - mr, mt, height - mb
    sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)
    band = (x1 - x0) / n
    xpos = lambda i: x0 + (i + 0.5) * band
    out = []
    for tk in ticks:
        out.append(f'<line class="grid" x1="{x0}" y1="{sy(tk):.1f}" x2="{x1}" y2="{sy(tk):.1f}"/>')
        out.append(f'<text class="ax" x="{x0 - 8}" y="{sy(tk) + 4:.1f}" text-anchor="end">{esc(axis_label(tk, ctype))}</text>')
    zero_y = sy(0) if lo <= 0 <= hi else y1
    out.append(f'<line class="axis" x1="{x0}" y1="{zero_y:.1f}" x2="{x1}" y2="{zero_y:.1f}"/>')
    label_y = y1 if lo >= 0 else sy(lo)
    out.append(x_labels(xs, xpos, label_y, n))

    if kind == "line":
        for si, s in enumerate(series):
            segs, cur = [], []
            for i, v in enumerate(s):                  # break the line at missing values: never bridge a gap
                if v is None:
                    if cur:
                        segs.append(cur)
                    cur = []
                else:
                    cur.append((xpos(i), sy(v), i, v))
            if cur:
                segs.append(cur)
            for seg in segs:
                if len(seg) > 1:
                    d = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py, _, _) in enumerate(seg))
                    out.append(f'<path class="l s{si % 5 + 1}" d="{d}" fill="none"/>')
                for px, py, i, v in seg:
                    out.append(f'<circle class="f s{si % 5 + 1}" cx="{px:.1f}" cy="{py:.1f}" r="3.5"/>')
                    out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="11" fill="#000" fill-opacity="0">'
                               f'<title>{esc(tip(i, si))}</title></circle>')
    elif kind == "column":
        k = len(ys)
        gw = band * 0.74
        bw = gw / k
        for i in range(n):
            for si in range(k):
                v = series[si][i]
                if v is None:
                    continue
                bx = xpos(i) - gw / 2 + si * bw
                ya, yb = sorted((sy(0), sy(v)))
                out.append(f'<rect class="f s{si % 5 + 1}" x="{bx + 1:.1f}" y="{ya:.1f}" width="{bw - 2:.1f}" '
                           f'height="{max(yb - ya, 0.5):.1f}"><title>{esc(tip(i, si))}</title></rect>')
                if k <= 2 and n <= 8:
                    ty = (ya - 4) if v >= 0 else (yb + 11)
                    out.append(f'<text class="val{num_class(v)}" x="{bx + bw / 2:.1f}" y="{ty:.1f}" '
                               f'text-anchor="middle">{esc(B.fmt(v, ctype))}</text>')
    elif kind == "waterfall":
        bw = band * 0.62
        for i, (a, c, role) in enumerate(bars):
            top, bot = max(a, c), min(a, c)
            cls = {"tot": "s1", "up": "pos", "down": "adv"}[role]
            delta = vals[i]
            label = B.fmt(delta, ctype)
            out.append(f'<rect class="f {cls}" x="{xpos(i) - bw / 2:.1f}" y="{sy(top):.1f}" width="{bw:.1f}" '
                       f'height="{max(sy(bot) - sy(top), 1.5):.1f}"><title>{esc(xs[i])}: {esc(label)}</title></rect>')
            out.append(f'<text class="val{num_class(delta)}" x="{xpos(i):.1f}" y="{sy(top) - 4:.1f}" '
                       f'text-anchor="middle">{esc(label)}</text>')
            if i < n - 1:
                out.append(f'<line class="conn" x1="{xpos(i) + bw / 2:.1f}" y1="{sy(ends[i]):.1f}" '
                           f'x2="{xpos(i + 1) - bw / 2:.1f}" y2="{sy(ends[i]):.1f}"/>')
    if multi:
        out.append(legend(ys, B.BAR_PALETTE, "line" if kind == "line" else "bar"))
    return svg_wrap("".join(out), height, ch["title"])


# ------------------------------------------------------------------- tables

def table_html(t):
    cols = t["columns"]
    head = "".join(
        f'<th class="{"num" if c.get("type", "text") in B.NUMERIC_TYPES else ""}">{esc(c["name"])}</th>' for c in cols)
    body = []
    for r in t["rows"]:
        tds = []
        for c, v in zip(cols, r):
            ct = c.get("type", "text")
            if ct in B.NUMERIC_TYPES:
                tds.append(f'<td class="num{num_class(v)}">{esc(B.fmt(v, ct))}</td>')
            else:
                tds.append(f'<td>{esc(B.fmt(v, ct))}</td>')
        body.append(f'<tr>{"".join(tds)}</tr>')
    foot = ""
    if any(c.get("total") for c in cols) and t["rows"]:
        cells = []
        for i, c in enumerate(cols):
            ct = c.get("type", "text")
            if i == 0:
                cells.append("<td>Total</td>")
            elif c.get("total") == "sum":
                s = sum(r[i] for r in t["rows"] if isinstance(r[i], (int, float)))
                cells.append(f'<td class="num{num_class(s)}">{esc(B.fmt(s, ct))}</td>')
            else:
                cells.append("<td></td>")
        foot = f'<tfoot><tr>{"".join(cells)}</tr></tfoot>'
    return f'<div class="tscroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody>{foot}</table></div>'


# --------------------------------------------------------------------- page

CSS = """
:root{--bg:#FFFFFF;--surface:#F2F4F9;--surface2:#DEE2E9;--text:#525965;--head:#1F242F;--muted:#818995;
--line:#C2C7CF;--grid:#DEE2E9;--s1:#1F242F;--s2:#EEFB87;--s3:#818995;--s4:#3BA184;--s5:#BF9856;
--pos:#3BA184;--adv:#BF9856;--alert:#B23A3A;--band:#F2F4F9;--tabhead:#1F242F;--tabheadtxt:#FFFFFF;
--banner:#1F242F;--bannertxt:#FFFFFF;--accent:#EEFB87;}
@media (prefers-color-scheme: dark){:root{color-scheme:dark;--bg:#12151C;--surface:#1B202A;--surface2:#2A303B;
--text:#C2C7CF;--head:#F2F4F9;--muted:#818995;--line:#393F4A;--grid:#2A303B;--s1:#F2F4F9;--s2:#EEFB87;--s3:#818995;
--s4:#3BA184;--s5:#BF9856;--alert:#E57373;--band:#1B202A;--tabhead:#393F4A;--tabheadtxt:#FFFFFF;--banner:#1F242F;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:'Messina Sans',Calibri,Carlito,Arial,sans-serif;
font-size:14px;line-height:1.5;letter-spacing:-0.01em}
.mono{font-family:'Messina Sans Mono','Courier New',monospace}
header.banner{background:var(--banner);color:var(--bannertxt);padding:28px 40px 22px;border-bottom:3px solid var(--accent)}
header.banner h1{margin:0 0 6px;font-size:26px;line-height:1.1;font-weight:700;letter-spacing:-0.02em;color:#fff}
header.banner .q{margin:0 0 12px;color:#C2C7CF;font-size:14px}
header.banner .meta{font-family:'Messina Sans Mono','Courier New',monospace;font-size:11px;color:var(--accent);
text-transform:uppercase;letter-spacing:0.02em}
main{max-width:1180px;margin:0 auto;padding:28px 40px 60px}
h2{font-size:17px;font-weight:600;color:var(--head);margin:34px 0 12px;letter-spacing:-0.02em}
.headline{font-size:17px;line-height:1.45;color:var(--head);border-left:3px solid var(--accent);
background:var(--surface);padding:14px 18px;margin:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:22px 0 0}
.kpi{background:var(--surface);border:0.75px solid var(--line);padding:14px 16px}
.kpi .lab{font-family:'Messina Sans Mono','Courier New',monospace;font-size:10.5px;text-transform:uppercase;color:var(--muted)}
.kpi .val{font-size:28px;font-weight:700;color:var(--head);line-height:1.15;margin:4px 0 2px;letter-spacing:-0.02em}
.kpi .del{font-size:12.5px;color:var(--text)}
.kpi .del.neg,.neg{color:var(--alert)}
.kpi .del.posd{color:var(--pos)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:16px}
.card{background:var(--bg);border:0.75px solid var(--line);padding:14px 16px 10px}
.card h3{margin:0 0 6px;font-size:14px;font-weight:600;color:var(--head);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.badge{font-family:'Messina Sans Mono','Courier New',monospace;font-size:10px;font-weight:400;text-transform:uppercase;
padding:2px 7px;letter-spacing:0.02em;white-space:nowrap}
.b-gov{background:var(--accent);color:#1F242F}
.b-der{background:var(--surface2);color:var(--head)}
.b-sce{background:#1F242F;color:#fff;border:0.75px solid var(--accent)}
svg text.ax{font-size:13px;fill:var(--muted)}
svg text.val{font-size:12.5px;fill:var(--text)}
svg text.val.neg{fill:var(--alert)}
svg .grid{stroke:var(--grid);stroke-width:0.75}
svg .axis{stroke:var(--line);stroke-width:1}
svg .conn{stroke:var(--muted);stroke-width:0.75}
svg .l{stroke-width:2.2;stroke-linejoin:round}
svg .l.s1{stroke:var(--s1)} svg .l.s2{stroke:var(--s4)} svg .l.s3{stroke:var(--s5)} svg .l.s4{stroke:var(--s3)} svg .l.s5{stroke:var(--s4)}
svg .f.s1{fill:var(--s1)} svg .f.s2{fill:var(--s2)} svg .f.s3{fill:var(--s3)} svg .f.s4{fill:var(--s4)} svg .f.s5{fill:var(--s5)}
svg .f.pos{fill:var(--pos)} svg .f.adv{fill:var(--adv)}
svg rect.f:hover,svg circle.f:hover{opacity:.82}
.tscroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th{background:var(--tabhead);color:var(--tabheadtxt);font-family:'Messina Sans Mono','Courier New',monospace;font-size:10.5px;
font-weight:400;text-transform:uppercase;text-align:left;padding:8px 10px;white-space:nowrap}
td{padding:7px 10px;border-bottom:0.75px solid var(--grid);color:var(--text)}
tbody tr:nth-child(odd) td{background:var(--band)}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
tfoot td{background:var(--surface2);color:var(--head);font-weight:600;border-bottom:none}
.note{font-size:12px;color:var(--muted);margin:6px 0 0}
details{margin-top:8px} summary{cursor:pointer;font-family:'Messina Sans Mono','Courier New',monospace;font-size:11px;color:var(--muted);text-transform:uppercase}
pre{background:var(--surface);border:0.75px solid var(--line);padding:10px 12px;overflow-x:auto;font-size:12px;margin:6px 0 0;
font-family:'Messina Sans Mono','Courier New',monospace;color:var(--head);white-space:pre-wrap}
.finding{display:grid;grid-template-columns:110px 90px 1fr;gap:12px;padding:9px 0;border-bottom:0.75px solid var(--grid)}
.ev{font-family:'Messina Sans Mono','Courier New',monospace;font-size:10.5px;text-transform:uppercase;padding-top:3px}
.ev.est{color:var(--head);font-weight:600} .ev.hyp{color:var(--adv)}
.tag{font-family:'Messina Sans Mono','Courier New',monospace;font-size:10.5px;color:var(--muted);padding-top:3px;text-transform:uppercase}
ul.clean{margin:0;padding-left:18px} ul.clean li{margin:4px 0}
.defs dt{font-weight:600;color:var(--head);margin-top:10px} .defs dd{margin:2px 0 0 0}
footer{margin-top:44px;padding-top:14px;border-top:0.75px solid var(--line);font-size:12px;color:var(--muted)}
@media print{header.banner{-webkit-print-color-adjust:exact;print-color-adjust:exact} .card{break-inside:avoid}}
@media (max-width:720px){main{padding:20px 16px} header.banner{padding:20px 16px} .grid2{grid-template-columns:1fr}
.finding{grid-template-columns:1fr;gap:2px}}
"""


def kpi_html(k):
    fmtk = k.get("format", "number")
    delta = ""
    if k.get("delta") is not None:
        d = k["delta"]
        dfmt = k.get("delta_format", fmtk)
        sign = "+" if d > 0 else ""
        txt = f"{sign}{B.fmt(d, dfmt)}"
        good = d > 0 if k.get("good", "up") == "up" else d < 0   # "good": "down" for costs and other lines where lower is better
        cls = "posd" if good else ("neg" if d != 0 else "")
        note = f' {esc(k["note"])}' if k.get("note") else ""
        delta = f'<div class="del {cls}">{esc(txt)}{note}</div>'
    elif k.get("note"):
        delta = f'<div class="del">{esc(k["note"])}</div>'
    return (f'<div class="kpi"><div class="lab">{esc(k["label"])}</div>'
            f'<div class="val{num_class(k["value"])}">{esc(B.fmt(k["value"], fmtk))}</div>{delta}</div>')


def build(b, fonts_dir=None):
    meta = b.get("meta", {})
    parts = [f"<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
             f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             f"<meta name=\"color-scheme\" content=\"light dark\">"
             f"<meta name=\"bundle-id\" content=\"{B.fingerprint(b)}\">"
             f"<title>{esc(meta.get('title', 'Analysis'))}</title><style>{font_faces(fonts_dir)}{CSS}</style></head><body>"]

    meta_bits = [meta.get("period"), meta.get("currency"), meta.get("scale"),
                 f"As of {meta['as_of']}" if meta.get("as_of") else None,
                 ("Source: " + ", ".join(meta["sources"])) if meta.get("sources") else None]
    parts.append('<header class="banner">'
                 f'<h1>{esc(meta.get("title", "Analysis"))}</h1>'
                 + (f'<p class="q">{esc(meta["question"])}</p>' if meta.get("question") else "")
                 + f'<div class="meta">{esc(" · ".join(x for x in meta_bits if x))}</div></header><main>')

    if meta.get("data_mode") == "local":
        parts.append(f'<p class="note" style="color:var(--adv);font-weight:600">{esc(B.LOCAL_BANNER)}</p>')
    if b.get("headline"):
        parts.append(f'<p class="headline">{esc(b["headline"])}</p>')
    if b.get("kpis"):
        parts.append('<div class="kpis">' + "".join(kpi_html(k) for k in b["kpis"]) + "</div>")

    if b.get("findings"):
        parts.append("<h2>Findings</h2>")
        for f in b["findings"]:
            ev = f.get("evidence", "established")
            parts.append(f'<div class="finding"><div class="ev {"est" if ev == "established" else "hyp"}">{esc(ev)}</div>'
                         f'<div class="tag">{esc(f.get("tag", ""))}</div><div>{esc(f["text"])}</div></div>')

    if b.get("charts"):
        parts.append("<h2>Charts</h2><div class=\"grid2\">")
        for ch in b["charts"]:
            parts.append(f'<div class="card"><h3>{esc(ch["title"])}{badge(ch.get("provenance", "governed"))}</h3>'
                         f'{chart_svg(b, ch)}</div>')
        parts.append("</div>")

    if b.get("tables"):
        parts.append("<h2>Detail</h2>")
        for t in b["tables"]:
            parts.append(f'<div class="card" style="margin-bottom:16px"><h3>{esc(t["title"])}{badge(t.get("provenance", "governed"))}</h3>'
                         f'{table_html(t)}')
            if t.get("capped"):
                parts.append(f'<p class="note">Showing {len(t["rows"])} of {esc(str(t.get("row_count_total", "?")))} rows (capped).</p>')
            if t.get("sql"):
                parts.append(f'<details><summary>SQL / derivation</summary><pre>{esc(t["sql"])}</pre></details>')
            parts.append("</div>")

    if b.get("definitions"):
        parts.append("<h2>Definitions</h2><dl class=\"defs\">")
        for d in b["definitions"]:
            view = f' <span class="mono" style="color:var(--muted);font-size:11px">{esc(d["view"])}</span>' if d.get("view") else ""
            parts.append(f'<dt>{esc(d.get("metric", ""))}{view}</dt><dd>{esc(d.get("definition", ""))}</dd>')
        parts.append("</dl>")

    if b.get("caveats"):
        parts.append("<h2>Data caveats</h2><ul class=\"clean\">" + "".join(f"<li>{esc(c)}</li>" for c in b["caveats"]) + "</ul>")

    src = ("Built from an uploaded local workbook for testing; not governed semantic-view results. "
           if meta.get("data_mode") == "local" else "Built from governed semantic-view results. ")
    parts.append(f"<footer>{src}Charts and tables are labelled Governed, Derived or "
                 "Scenario; scenario figures rest on stated assumptions and are not actuals. "
                 f"<span class=\"mono\" id=\"bundle-id\">Bundle ID: {B.fingerprint(b)}</span></footer></main></body></html>")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("out")
    ap.add_argument("--fonts-dir")
    a = ap.parse_args()
    b = B.load(a.bundle)
    errs = B.validate(b)
    if errs:
        print("Bundle problems — fix before building:")
        for e in errs:
            print(" -", e)
        return 1
    doc = build(b, a.fonts_dir)
    for bad in ("None", "nan", "NaN", "undefined", "INJECT_"):
        # only flag in visible text zones, not in CSS/JS-free attributes
        if f">{bad}<" in doc:
            print(f"WARNING: '{bad}' rendered as visible text — check the bundle.")
    if not doc.rstrip().endswith("</html>"):
        print("ERROR: output does not end with </html>")
        return 1
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"Wrote {a.out}  ({len(doc) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
