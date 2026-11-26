#!/usr/bin/env python3
"""Render each chart in a result bundle to a brand-coloured PNG.

Usage:  python make_chart.py bundle.json --outdir outputs/ [--only chart_id] [--dpi 160]

Chart types: line, column, bar (horizontal), waterfall. Non-governed charts
(derived / scenario) carry their provenance in the title so they can't be
mistaken for actuals.
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import bundle as B

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Calibri", "Carlito", "Arial", "DejaVu Sans"]


def hexc(h):
    return "#" + h


def axis_formatter(ctype):
    def f(x, _):
        return B.fmt(x, ctype) if x != 0 else "0"
    return FuncFormatter(f)


def style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(hexc(B.GRAY3))
        ax.spines[side].set_linewidth(0.75)
    ax.tick_params(colors=hexc(B.GRAY5), labelsize=9, length=0)
    ax.grid(axis="y", color=hexc(B.GRAY2), linewidth=0.75)
    ax.set_axisbelow(True)


def title_for(ch):
    t = ch["title"]
    p = ch.get("provenance", "governed")
    if p != "governed":
        t += f"  ({B.provenance_label(p).lower()})"
    return t


def render(b, ch, outpath, dpi):
    t = B.table_by_id(b, ch["table"])
    xs = [str(v) for v in B.col_values(t, ch["x"])]
    ycols = ch["y"]
    ctype = B.col_type(t, ycols[0])
    kind = ch["type"]
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    fig.patch.set_facecolor("white")

    if kind == "line":
        for i, y in enumerate(ycols):
            vals = [v if v is not None else float("nan") for v in B.col_values(t, y)]
            col = hexc(B.LINE_PALETTE[i % len(B.LINE_PALETTE)])
            ax.plot(xs, vals, color=col, linewidth=2, marker="o", markersize=4, label=y)
        ax.axhline(0, color=hexc(B.GRAY3), linewidth=0.75)
        if len(xs) > 8:
            step = max(1, len(xs) // 8)
            ax.set_xticks(range(0, len(xs), step))
            ax.set_xticklabels(xs[::step])
    elif kind == "column":
        k = len(ycols)
        width = 0.8 / k
        for i, y in enumerate(ycols):
            vals = [v or 0 for v in B.col_values(t, y)]
            pos = [j + (i - (k - 1) / 2) * width for j in range(len(xs))]
            ax.bar(pos, vals, width=width * 0.92, color=hexc(B.BAR_PALETTE[i % len(B.BAR_PALETTE)]), label=y)
            if k == 1 or len(xs) <= 6:
                for px, v in zip(pos, vals):
                    ax.annotate(B.fmt(v, ctype), (px, v), ha="center",
                                va="bottom" if v >= 0 else "top", fontsize=8, color=hexc(B.GRAY5),
                                xytext=(0, 2 if v >= 0 else -2), textcoords="offset points")
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels(xs)
        ax.axhline(0, color=hexc(B.GRAY3), linewidth=0.75)
    elif kind == "bar":
        k = len(ycols)
        height = 0.8 / k
        for i, y in enumerate(ycols):
            vals = [v or 0 for v in B.col_values(t, y)]
            pos = [j + (i - (k - 1) / 2) * height for j in range(len(xs))]
            ax.barh(pos, vals, height=height * 0.92, color=hexc(B.BAR_PALETTE[i % len(B.BAR_PALETTE)]), label=y)
            for py, v in zip(pos, vals):
                ax.annotate(B.fmt(v, ctype), (v, py), va="center", ha="left" if v >= 0 else "right",
                            fontsize=8, color=hexc(B.GRAY5), xytext=(3 if v >= 0 else -3, 0),
                            textcoords="offset points")
        ax.set_yticks(range(len(xs)))
        ax.set_yticklabels(xs)
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=hexc(B.GRAY2), linewidth=0.75)
        ax.margins(x=0.12)
    elif kind == "waterfall":
        vals = [v or 0 for v in B.col_values(t, ycols[0])]
        totals = set(ch.get("totals") or [])
        run, bottoms, heights, colors, ends = 0.0, [], [], [], []
        for i, (lab, v) in enumerate(zip(xs, vals)):
            if lab in totals or i == 0:
                bottoms.append(0)
                heights.append(v)
                colors.append(hexc(B.NAVY))
                run = v
            else:
                start, run = run, run + v
                bottoms.append(min(start, run))
                heights.append(abs(v))
                colors.append(hexc(B.MINT if v >= 0 else B.ALMOND))
            ends.append(run)
        ax.bar(range(len(xs)), heights, bottom=bottoms, color=colors, width=0.62)
        for i, (lab, v) in enumerate(zip(xs, vals)):
            top = bottoms[i] + heights[i]
            ax.annotate(B.fmt(v, ctype), (i, top), ha="center", va="bottom", fontsize=8,
                        color=hexc(B.GRAY5), xytext=(0, 2), textcoords="offset points")
            if i < len(xs) - 1:
                ax.plot([i + 0.31, i + 1 - 0.31], [ends[i], ends[i]], color=hexc(B.GRAY4), linewidth=0.75)
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels(xs)
        ax.margins(y=0.12)

    style_axes(ax)
    if kind != "bar":
        ax.yaxis.set_major_formatter(axis_formatter(ctype))
    else:
        ax.xaxis.set_major_formatter(axis_formatter(ctype))
    if len(ycols) > 1 and kind != "waterfall":
        ax.legend(frameon=False, fontsize=9, labelcolor=hexc(B.GRAY5), loc="upper left",
                  bbox_to_anchor=(0, -0.12), ncol=len(ycols))
    ax.set_title(title_for(ch), loc="left", fontsize=12, fontweight="bold", color=hexc(B.NAVY), pad=12)
    if len(max(xs, key=len, default="")) > 10 and kind in ("column", "line", "waterfall") and len(xs) > 5:
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    # period and scale only: a bundle can span several views, so naming one source here could mislabel a chart
    foot = " · ".join(x for x in [b["meta"].get("period"), b["meta"].get("scale")] if x)
    if foot:
        fig.text(0.01, 0.01, foot, fontsize=7.5, color=hexc(B.GRAY4), ha="left")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp = f"Bundle ID {B.fingerprint(b)}" + ("  |  LOCAL TEST DATA" if b.get("meta", {}).get("data_mode") == "local" else "")
    fig.text(0.995, 0.005, stamp, ha="right", va="bottom", fontsize=7, color=hexc(B.GRAY4))
    fig.savefig(outpath, dpi=dpi, facecolor="white", metadata={"Description": f"Bundle ID: {B.fingerprint(b)}"})
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--only")
    ap.add_argument("--dpi", type=int, default=160)
    a = ap.parse_args()
    b = B.load(a.bundle)
    errs = B.validate(b)
    if errs:
        print("Bundle problems — fix before charting:")
        for e in errs:
            print(" -", e)
        return 1
    os.makedirs(a.outdir, exist_ok=True)
    charts = [c for c in b.get("charts", []) if not a.only or c["id"] == a.only]
    if not charts:
        print("No charts in bundle." if not a.only else f"No chart with id '{a.only}'.")
        return 1
    for ch in charts:
        out = os.path.join(a.outdir, f"{ch['id']}.png")
        render(b, ch, out, a.dpi)
        print("Wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
