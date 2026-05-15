"""Sanity-check the Stage A artifact and emit a one-page summary PNG.

- per-class counts
- per-confidence histogram
- per-source x label cross-tab
- compare public share against the reference national breakdown
- write a markdown summary to docs/

Run:
  python scripts/sanity_check.py \
    --input data/derived/stage_a_labels_BEN_2026-04-30.geojson \
    --out-png docs/figures/stage_a_BEN_2026-04-30.png \
    --out-md docs/sanity_BEN_2026-04-30.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 110,
    }
)

LABEL_COLORS = {
    "public": "#1f77b4",
    "private-secular": "#d73f3f",
    "private-religious": "#9467bd",
    "community": "#2ca02c",
    "public-mission": "#17becf",
    "government-assisted": "#8c564b",
    "unknown": "#bbbbbb",
}

# Reference: INFRE annuaires statistiques approximate national split for primary.
# Public ~83%, private ~17% per the 2022-23 figures. Reference points, not
# authoritative training data.
INFRE_REFERENCE_PRIMARY = {"public": 0.83, "private": 0.17}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-png", required=True)
    p.add_argument("--out-md", required=True)
    args = p.parse_args()

    gdf = gpd.read_file(args.input)
    n = len(gdf)
    counts = gdf["ownership_label"].value_counts()
    conf = gdf["ownership_confidence"].value_counts()
    src_x_label = gdf.groupby("join_source")["ownership_label"].value_counts().unstack(fill_value=0)

    # Public share excluding unknowns:
    labelled = gdf[gdf["ownership_label"] != "unknown"]
    pub_share = (labelled["ownership_label"] == "public").mean() if len(labelled) else 0
    priv_share = (labelled["ownership_label"].str.startswith("private")).mean() if len(labelled) else 0

    # Plot a 2x2 dashboard.
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(
        f"Stage A Benin pilot - {n} schools  (Giga + OSM, joined)",
        fontsize=14,
        weight="bold",
    )

    # 1. Class counts.
    ax = axes[0, 0]
    cs = counts.reindex([k for k in LABEL_COLORS if k in counts.index])
    bars = ax.barh(cs.index, cs.values, color=[LABEL_COLORS[k] for k in cs.index])
    ax.set_title("Ownership label counts")
    ax.invert_yaxis()
    for bar, v in zip(bars, cs.values):
        ax.text(v + n * 0.005, bar.get_y() + bar.get_height() / 2, f"{v}  ({v/n*100:.1f}%)", va="center", fontsize=9)
    ax.set_xlim(0, max(cs.values) * 1.3)

    # 2. Confidence histogram.
    ax = axes[0, 1]
    conf_order = ["high", "medium", "low", "none"]
    cv = conf.reindex(conf_order, fill_value=0)
    bars = ax.bar(cv.index, cv.values, color=["#3a7d3a", "#d4a017", "#d6ad33", "#bbbbbb"])
    ax.set_title("Ownership confidence distribution")
    for bar, v in zip(bars, cv.values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + n * 0.005, f"{v}\n({v/n*100:.1f}%)", ha="center", fontsize=9)
    ax.set_ylim(0, max(cv.values) * 1.18)

    # 3. Source x label stacked bar.
    ax = axes[1, 0]
    src_order = ["giga_only", "giga_osm", "osm_only"]
    label_order = [k for k in LABEL_COLORS if k in src_x_label.columns]
    cs = src_x_label.reindex(index=src_order, columns=label_order, fill_value=0)
    bottom = [0] * len(src_order)
    for col in label_order:
        ax.bar(cs.index, cs[col], bottom=bottom, label=col, color=LABEL_COLORS[col])
        bottom = [b + v for b, v in zip(bottom, cs[col])]
    ax.set_title("Label by join source")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    for i, src in enumerate(cs.index):
        total = cs.loc[src].sum()
        ax.text(i, total + n * 0.005, str(int(total)), ha="center", fontsize=9)

    # 4. Public share comparison.
    ax = axes[1, 1]
    ours_pub = pub_share
    ours_priv = priv_share
    ref_pub = INFRE_REFERENCE_PRIMARY["public"]
    ref_priv = INFRE_REFERENCE_PRIMARY["private"]
    x = ["Stage A\n(of labelled)", "INFRE 2022-23\n(primary, ref.)"]
    pub_vals = [ours_pub, ref_pub]
    priv_vals = [ours_priv, ref_priv]
    ax.bar(x, pub_vals, label="public", color=LABEL_COLORS["public"])
    ax.bar(x, priv_vals, bottom=pub_vals, label="private", color=LABEL_COLORS["private-secular"])
    ax.set_ylim(0, 1.0)
    ax.set_title("Public vs private share, labelled subset")
    for i, (p_, q_) in enumerate(zip(pub_vals, priv_vals)):
        ax.text(i, p_ / 2, f"{p_*100:.1f}%", ha="center", color="white", fontsize=10, weight="bold")
        ax.text(i, p_ + q_ / 2, f"{q_*100:.1f}%", ha="center", color="white", fontsize=10, weight="bold")
    ax.legend(loc="upper right", fontsize=8, frameon=False)

    Path(args.out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.subplots_adjust(top=0.93)
    fig.savefig(args.out_png, dpi=140)

    # Markdown summary.
    md = []
    md.append(f"# Stage A sanity check - Benin (2026-04-30)\n")
    md.append(f"**Total features:** {n}\n")
    md.append("## Ownership label counts\n")
    md.append("| label | count | share |\n|---|---:|---:|")
    for k, v in counts.items():
        md.append(f"| `{k}` | {v} | {v/n*100:.1f}% |")
    md.append("")
    md.append("## Confidence distribution\n")
    md.append("| confidence | count | share |\n|---|---:|---:|")
    for k in conf_order:
        v = conf.get(k, 0)
        md.append(f"| `{k}` | {v} | {v/n*100:.1f}% |")
    md.append("")
    md.append("## Label by join source\n")
    md.append("| source | " + " | ".join(label_order) + " | total |")
    md.append("|---|" + "---:|" * (len(label_order) + 1))
    for src in src_order:
        if src not in src_x_label.index:
            continue
        row = src_x_label.loc[src].reindex(label_order, fill_value=0)
        md.append(f"| `{src}` | " + " | ".join(str(int(v)) for v in row) + f" | {int(row.sum())} |")
    md.append("")
    md.append("## Public/private share, labelled subset\n")
    md.append(f"- Stage A public share (of labelled): **{pub_share*100:.1f}%**")
    md.append(f"- Stage A private share (of labelled): **{priv_share*100:.1f}%**")
    md.append(f"- INFRE 2022-23 primary reference: public {ref_pub*100:.0f}% / private {ref_priv*100:.0f}%\n")

    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text("\n".join(md))
    print(f"png -> {args.out_png}")
    print(f"md  -> {args.out_md}")


if __name__ == "__main__":
    main()
