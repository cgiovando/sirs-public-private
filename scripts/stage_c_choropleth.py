"""Compare detected vs predicted private share by department.

Three panels:
  1. Stage A only - private share of labelled set per ADM1
  2. Stage A + Stage C model fill-in - private share over ALL schools per ADM1
     (including model-predicted private from the unknowns)
  3. Delta - how much the Stage C fill-in shifts each department
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 110,
    }
)


PRIVATE_FINAL = {"private-secular", "private-religious", "community", "private-model"}
PUBLIC_FINAL = {"public", "public-model"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--predictions", required=True)
    p.add_argument("--adm1", default="data/cache/boundaries/ben_adm1.geojson")
    p.add_argument("--output", default="docs/figures/stage_c_choropleth_BEN_2026-04-30.png")
    args = p.parse_args()

    df = pd.read_parquet(args.predictions)
    adm1 = gpd.read_file(args.adm1).rename(columns={"shapeName": "adm1"})

    # Stage A view: of LABELLED only (excludes uncertain/unknown).
    a_priv = df["ownership_label"].isin(["private-secular", "private-religious", "community"])
    a_pub = df["ownership_label"] == "public"
    a_known = a_priv | a_pub

    # Stage A+C view: include model fill-in for the unknowns.
    c_priv = df["ownership_final"].isin(PRIVATE_FINAL)
    c_pub = df["ownership_final"].isin(PUBLIC_FINAL)
    c_known = c_priv | c_pub

    by = (
        df.assign(
            a_priv=a_priv.astype(int),
            a_pub=a_pub.astype(int),
            a_known=a_known.astype(int),
            c_priv=c_priv.astype(int),
            c_pub=c_pub.astype(int),
            c_known=c_known.astype(int),
        )
        .groupby("adm1")
        .agg(
            n=("school_id", "count"),
            a_priv=("a_priv", "sum"),
            a_known=("a_known", "sum"),
            c_priv=("c_priv", "sum"),
            c_known=("c_known", "sum"),
        )
        .reset_index()
    )
    by["a_share"] = by["a_priv"] / by["a_known"].clip(lower=1)
    by["c_share"] = by["c_priv"] / by["c_known"].clip(lower=1)
    by["delta"] = by["c_share"] - by["a_share"]

    a1 = adm1.merge(by, on="adm1", how="left")

    fig, axes = plt.subplots(1, 3, figsize=(16, 7))

    titles = [
        ("Stage A only\nprivate share of labelled", "a_share", "Reds"),
        ("Stage A + Stage C\nprivate share with model fill-in", "c_share", "Reds"),
        ("Delta (Stage C - Stage A)\npp shift per department", "delta", "RdBu_r"),
    ]
    for ax, (title, col, cmap) in zip(axes, titles):
        kwargs = dict(legend=True, edgecolor="white", linewidth=0.6, missing_kwds={"color": "#eeeeee"})
        if col == "delta":
            vmax = max(abs(a1["delta"].min()), abs(a1["delta"].max()), 0.03)
            kwargs["vmin"] = -vmax
            kwargs["vmax"] = vmax
        a1.plot(column=col, ax=ax, cmap=cmap, **kwargs)
        for _, row in a1.iterrows():
            c = row.geometry.representative_point()
            v = row[col]
            if pd.notna(v):
                if col == "delta":
                    label = f"{row['adm1']}\n{v*100:+.1f}pp"
                else:
                    label = f"{row['adm1']}\n{v*100:.1f}%"
            else:
                label = row["adm1"]
            ax.annotate(label, xy=(c.x, c.y), ha="center", fontsize=8)
        ax.set_title(title, fontsize=11, weight="bold", loc="left")
        ax.set_aspect("equal")
        ax.set_axis_off()

    fig.suptitle("Private-school share by department, before and after Stage C", fontsize=14, weight="bold")
    fig.tight_layout()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=140, bbox_inches="tight")
    print(f"wrote {args.output}")
    print()
    print(by.sort_values("c_share", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
