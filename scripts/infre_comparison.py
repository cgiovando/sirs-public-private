"""Three-panel choropleth: Stage A detected vs Stage C prior-shifted vs INFRE 2021-22 truth.

Reveals the calibration gap by department.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.rcParams.update(
    {"font.family": "sans-serif", "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 110}
)

PRIVATE_FINAL = {"private-secular", "private-religious", "community", "private-model"}
PUBLIC_FINAL = {"public", "public-model"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--predictions", default="data/derived/stage_c_predictions_BEN_2026-04-30.parquet")
    p.add_argument("--priors", default="data/cache/infre/benin_dept_priors_2021_2022.parquet")
    p.add_argument("--adm1", default="data/cache/boundaries/ben_adm1.geojson")
    p.add_argument("--output", default="docs/figures/infre_comparison_BEN_2026-04-30.png")
    args = p.parse_args()

    df = pd.read_parquet(args.predictions)
    priors = pd.read_parquet(args.priors)
    adm1 = gpd.read_file(args.adm1).rename(columns={"shapeName": "adm1"})

    # Stage A view: of LABELLED only
    a_priv = df["ownership_label"].isin(["private-secular", "private-religious", "community"])
    a_pub = df["ownership_label"] == "public"
    a_known = a_priv | a_pub

    # Stage C adjusted view: of ALL incl. model fill-in
    c_priv = df["ownership_final_adj"].isin(PRIVATE_FINAL)
    c_pub = df["ownership_final_adj"].isin(PUBLIC_FINAL)
    c_known = c_priv | c_pub

    by = (
        df.assign(a_priv=a_priv.astype(int), a_known=a_known.astype(int),
                  c_priv=c_priv.astype(int), c_known=c_known.astype(int))
        .groupby("adm1")
        .agg(n=("school_id", "count"),
             a_priv=("a_priv", "sum"), a_known=("a_known", "sum"),
             c_priv=("c_priv", "sum"), c_known=("c_known", "sum"))
        .reset_index()
    )
    by["a_share"] = by["a_priv"] / by["a_known"].clip(lower=1)
    by["c_share"] = by["c_priv"] / by["c_known"].clip(lower=1)

    # INFRE prior keyed by department (geoBoundaries spelling)
    by = by.merge(priors[["department", "private_share"]].rename(columns={"department": "adm1", "private_share": "infre_share"}),
                  on="adm1", how="left")

    a1 = adm1.merge(by, on="adm1", how="left")

    fig, axes = plt.subplots(1, 3, figsize=(17, 7))

    titles = [
        ("Stage A (deterministic)\nprivate share of labelled", "a_share"),
        ("Stage C (prior-shifted)\nprivate share with model fill-in", "c_share"),
        ("INFRE 2021-22 truth\nprivate share, primary only", "infre_share"),
    ]
    vmax = max(a1[c].max() for _, c in titles if a1[c].notna().any())
    vmax = max(vmax, 0.7)
    for ax, (title, col) in zip(axes, titles):
        a1.plot(column=col, ax=ax, cmap="Reds",
                edgecolor="white", linewidth=0.6, vmin=0, vmax=vmax,
                legend=True,
                legend_kwds={"label": "private share", "shrink": 0.6},
                missing_kwds={"color": "#eeeeee"})
        for _, row in a1.iterrows():
            c = row.geometry.representative_point()
            v = row[col]
            label = f"{row['adm1']}"
            if pd.notna(v):
                label += f"\n{v*100:.0f}%"
            ax.annotate(label, xy=(c.x, c.y), ha="center", fontsize=8)
        ax.set_title(title, fontsize=12, weight="bold", loc="left")
        ax.set_aspect("equal")
        ax.set_axis_off()

    fig.suptitle("Private-school share by department - detection vs population prior", fontsize=14, weight="bold")
    fig.tight_layout()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=140, bbox_inches="tight")
    print(f"wrote {args.output}")
    print()
    print(by.sort_values("infre_share", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
