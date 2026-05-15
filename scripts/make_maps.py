"""Three maps for the SIRS Weekly demo.

1. Point map of all 9,269 schools coloured by ownership_label, with the Benin
   ADM1 outline.
2. Choropleth of detected private share per ADM1 department.
3. Urban-rural gradient: private share as a function of distance-to-Cotonou,
   binned into deciles. Bonus: same against ADM1.

Outputs:
  docs/figures/map_BEN_2026-04-30.png
  docs/figures/map_BEN_choropleth_2026-04-30.png
  docs/figures/urban_gradient_BEN_2026-04-30.png
  docs/figures/by_department_BEN_2026-04-30.png

Adds an `adm1` column to the Stage A artifact in-place via spatial join (cheap;
the artifact gets rewritten with the additional column).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import Point

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
    "unknown": "#cccccc",
}

# Cotonou approximate centre (the economic capital, where private schooling concentrates).
COTONOU_LON, COTONOU_LAT = 2.3912, 6.3654


def benin_utm(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.to_crs(epsg=32631)  # UTM 31N covers Benin.


def add_adm1(stage_a: gpd.GeoDataFrame, adm1: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Spatial-join schools to ADM1 (department)."""
    a1 = adm1[["shapeName", "geometry"]].rename(columns={"shapeName": "adm1"}).to_crs(stage_a.crs)
    j = gpd.sjoin(stage_a, a1, how="left", predicate="intersects")
    j = j.drop(columns=["index_right"])
    # one row per school, even when ADM polygons overlap on borders
    j = j.drop_duplicates(subset=["school_id"]).reset_index(drop=True)
    return j


def make_point_map(stage_a: gpd.GeoDataFrame, adm1: gpd.GeoDataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 9), gridspec_kw={"width_ratios": [1.6, 1]})

    # Left: full-country point map.
    ax = axes[0]
    adm1.boundary.plot(ax=ax, color="#666666", linewidth=0.6)
    # Plot in order: unknown first (background), then public, then private (foreground).
    for label in ["unknown", "public", "private-secular", "private-religious", "community"]:
        sub = stage_a[stage_a["ownership_label"] == label]
        if sub.empty:
            continue
        ax.scatter(
            sub.geometry.x,
            sub.geometry.y,
            s=5 if label == "unknown" else 8,
            c=LABEL_COLORS[label],
            alpha=0.35 if label == "unknown" else 0.75,
            label=f"{label} ({len(sub):,})",
            linewidth=0,
        )
    ax.set_title("Benin schools, Stage A v0.1 labels", fontsize=13, weight="bold", loc="left")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_aspect("equal")
    ax.legend(loc="upper left", frameon=False, fontsize=9, scatterpoints=1, markerscale=2)
    # Annotate Cotonou.
    ax.scatter([COTONOU_LON], [COTONOU_LAT], marker="*", c="black", s=80, zorder=5)
    ax.annotate(
        "Cotonou",
        xy=(COTONOU_LON, COTONOU_LAT),
        xytext=(8, 8),
        textcoords="offset points",
        fontsize=10,
        weight="bold",
    )

    # Right: zoom on Greater Cotonou (where private schooling clusters).
    ax = axes[1]
    adm1.boundary.plot(ax=ax, color="#666666", linewidth=0.6)
    for label in ["unknown", "public", "private-secular", "private-religious", "community"]:
        sub = stage_a[stage_a["ownership_label"] == label]
        if sub.empty:
            continue
        ax.scatter(sub.geometry.x, sub.geometry.y, s=14, c=LABEL_COLORS[label], alpha=0.85, linewidth=0)
    ax.set_xlim(2.05, 2.7)
    ax.set_ylim(6.25, 6.7)
    ax.set_title("Zoom: Greater Cotonou / Porto-Novo", fontsize=13, weight="bold", loc="left")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_aspect("equal")
    ax.scatter([COTONOU_LON], [COTONOU_LAT], marker="*", c="black", s=80, zorder=5)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")


def make_choropleth(stage_a: gpd.GeoDataFrame, adm1: gpd.GeoDataFrame, out_path: Path) -> None:
    by_adm1 = (
        stage_a.assign(
            is_public=lambda d: (d["ownership_label"] == "public").astype(int),
            is_private=lambda d: d["ownership_label"].isin(
                ["private-secular", "private-religious", "community"]
            ).astype(int),
            is_known=lambda d: (d["ownership_label"] != "unknown").astype(int),
        )
        .groupby("adm1")
        .agg(
            n=("school_id", "count"),
            n_known=("is_known", "sum"),
            n_public=("is_public", "sum"),
            n_private=("is_private", "sum"),
        )
        .reset_index()
    )
    by_adm1["private_share_of_known"] = by_adm1["n_private"] / by_adm1["n_known"].clip(lower=1)
    by_adm1["unknown_share"] = 1 - by_adm1["n_known"] / by_adm1["n"].clip(lower=1)

    a1 = adm1.rename(columns={"shapeName": "adm1"}).merge(by_adm1, on="adm1", how="left")

    fig, axes = plt.subplots(1, 2, figsize=(14, 8))

    ax = axes[0]
    a1.plot(
        column="private_share_of_known",
        ax=ax,
        cmap="Reds",
        edgecolor="white",
        linewidth=0.6,
        legend=True,
        legend_kwds={"label": "private share (of labelled)", "shrink": 0.7},
        missing_kwds={"color": "#eeeeee"},
    )
    for _, row in a1.iterrows():
        c = row.geometry.representative_point()
        ax.annotate(
            row["adm1"],
            xy=(c.x, c.y),
            ha="center",
            fontsize=8,
            color="black",
        )
        if pd.notna(row["private_share_of_known"]):
            ax.annotate(
                f"{row['private_share_of_known']*100:.1f}%",
                xy=(c.x, c.y - 0.08),
                ha="center",
                fontsize=8,
                color="#444",
                weight="bold",
            )
    ax.set_title("Private share of labelled schools, by department", fontsize=13, weight="bold", loc="left")
    ax.set_aspect("equal")
    ax.set_axis_off()

    ax = axes[1]
    a1.plot(
        column="unknown_share",
        ax=ax,
        cmap="Greys",
        edgecolor="white",
        linewidth=0.6,
        legend=True,
        legend_kwds={"label": "unknown share (of all)", "shrink": 0.7},
        missing_kwds={"color": "#eeeeee"},
    )
    for _, row in a1.iterrows():
        c = row.geometry.representative_point()
        ax.annotate(row["adm1"], xy=(c.x, c.y), ha="center", fontsize=8)
        if pd.notna(row["unknown_share"]):
            ax.annotate(
                f"{row['unknown_share']*100:.0f}%",
                xy=(c.x, c.y - 0.08),
                ha="center",
                fontsize=8,
                color="#222",
                weight="bold",
            )
    ax.set_title("Unmatched (unknown) share, by department", fontsize=13, weight="bold", loc="left")
    ax.set_aspect("equal")
    ax.set_axis_off()

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    return by_adm1


def make_urban_gradient(stage_a: gpd.GeoDataFrame, out_path: Path) -> pd.DataFrame:
    """Distance from each school to Cotonou (km, Haversine via UTM).
    Bin into deciles; show private share, public share, and unknown share per decile.
    """
    g = benin_utm(stage_a).copy()
    cotonou = gpd.GeoSeries([Point(COTONOU_LON, COTONOU_LAT)], crs="EPSG:4326").to_crs(epsg=32631).iloc[0]
    g["dist_km"] = g.geometry.distance(cotonou) / 1000.0

    g["bin"] = pd.qcut(g["dist_km"], q=10, labels=False, duplicates="drop")
    binstats = g.groupby("bin").agg(
        n=("school_id", "count"),
        n_public=("ownership_label", lambda s: (s == "public").sum()),
        n_private=(
            "ownership_label",
            lambda s: s.isin(["private-secular", "private-religious", "community"]).sum(),
        ),
        n_unknown=("ownership_label", lambda s: (s == "unknown").sum()),
        dist_km_min=("dist_km", "min"),
        dist_km_max=("dist_km", "max"),
        dist_km_mean=("dist_km", "mean"),
    ).reset_index()
    binstats["public_share"] = binstats["n_public"] / binstats["n"]
    binstats["private_share"] = binstats["n_private"] / binstats["n"]
    binstats["unknown_share"] = binstats["n_unknown"] / binstats["n"]
    binstats["private_share_labelled"] = binstats["n_private"] / (binstats["n_public"] + binstats["n_private"]).clip(lower=1)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    ax = axes[0]
    bottom = np.zeros(len(binstats))
    for label, color in [
        ("public_share", LABEL_COLORS["public"]),
        ("private_share", LABEL_COLORS["private-secular"]),
        ("unknown_share", LABEL_COLORS["unknown"]),
    ]:
        ax.bar(
            binstats["dist_km_mean"],
            binstats[label],
            bottom=bottom,
            color=color,
            width=binstats["dist_km_max"] - binstats["dist_km_min"],
            edgecolor="white",
            linewidth=0.5,
            label=label.replace("_share", ""),
        )
        bottom = bottom + binstats[label].values
    ax.set_xlabel("distance from Cotonou (km, decile bins)")
    ax.set_ylabel("share of schools")
    ax.set_ylim(0, 1)
    ax.set_title("Label composition by distance to Cotonou", fontsize=12, weight="bold", loc="left")
    ax.legend(loc="lower right", frameon=False, fontsize=9)

    ax = axes[1]
    ax.plot(
        binstats["dist_km_mean"],
        binstats["private_share_labelled"] * 100,
        marker="o",
        color=LABEL_COLORS["private-secular"],
        linewidth=2,
    )
    ax.set_xlabel("distance from Cotonou (km, decile bins)")
    ax.set_ylabel("private share (% of labelled)")
    ax.set_title("Private share drops with distance from urban core", fontsize=12, weight="bold", loc="left")
    ax.axhline(17, color="#888", linestyle="--", linewidth=1)
    ax.text(
        binstats["dist_km_mean"].max() * 0.98,
        17.5,
        "INFRE national 17%",
        ha="right",
        color="#666",
        fontsize=9,
    )
    ax.set_ylim(0, max(binstats["private_share_labelled"].max() * 100 + 2, 20))
    ax.grid(axis="y", linestyle=":", color="#cccccc", alpha=0.6)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    return binstats


def make_by_department(by_adm1: pd.DataFrame, out_path: Path) -> None:
    by_adm1 = by_adm1.copy()
    by_adm1 = by_adm1.sort_values("private_share_of_known", ascending=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(
        by_adm1["adm1"],
        by_adm1["private_share_of_known"] * 100,
        color=[
            LABEL_COLORS["private-secular"] if v > 0.05 else "#bbbbbb"
            for v in by_adm1["private_share_of_known"]
        ],
    )
    for bar, n_priv, n_known, n in zip(
        bars, by_adm1["n_private"], by_adm1["n_known"], by_adm1["n"]
    ):
        ax.text(
            bar.get_width() + 0.3,
            bar.get_y() + bar.get_height() / 2,
            f"{int(n_priv)}/{int(n_known)} labelled  (n={int(n)})",
            va="center",
            fontsize=9,
            color="#333",
        )
    ax.axvline(17, color="#888", linestyle="--", linewidth=1)
    ax.text(17.3, len(by_adm1) - 0.4, "INFRE national 17%", color="#666", fontsize=9)
    ax.set_xlabel("private share (% of labelled)")
    ax.set_title("Detected private share by department", fontsize=13, weight="bold", loc="left")
    ax.set_xlim(0, max(by_adm1["private_share_of_known"].max() * 100 + 12, 25))

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/derived/stage_a_labels_BEN_2026-04-30.geojson")
    p.add_argument("--adm1", default="data/cache/boundaries/ben_adm1.geojson")
    p.add_argument("--out-dir", default="docs/figures")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stage_a = gpd.read_file(args.input)
    adm1 = gpd.read_file(args.adm1).to_crs(stage_a.crs)
    stage_a = add_adm1(stage_a, adm1)

    # Persist enriched artifact (non-destructive: write a side-file).
    enriched = Path(args.input).with_name(Path(args.input).stem + "_enriched.geojson")
    stage_a.to_file(enriched, driver="GeoJSON")
    print(f"enriched -> {enriched}")

    make_point_map(stage_a, adm1, out_dir / "map_BEN_2026-04-30.png")
    by_adm1 = make_choropleth(stage_a, adm1, out_dir / "map_BEN_choropleth_2026-04-30.png")
    binstats = make_urban_gradient(stage_a, out_dir / "urban_gradient_BEN_2026-04-30.png")
    make_by_department(by_adm1, out_dir / "by_department_BEN_2026-04-30.png")

    print("\n=== Department-level table ===")
    print(by_adm1.sort_values("private_share_of_known", ascending=False).to_string(index=False))

    print("\n=== Distance-from-Cotonou bins ===")
    print(
        binstats[
            [
                "dist_km_min",
                "dist_km_max",
                "n",
                "n_public",
                "n_private",
                "n_unknown",
                "private_share_labelled",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
