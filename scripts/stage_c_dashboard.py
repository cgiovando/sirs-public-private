"""Stage C result dashboard and maps.

Outputs:
  docs/figures/stage_c_dashboard_BEN_2026-04-30.png     (4-panel diagnostic)
  docs/figures/stage_c_unknowns_map_BEN_2026-04-30.png  (predictions on unknowns)
  docs/figures/stage_c_calibration_BEN_2026-04-30.png   (calibration curve)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 110,
    }
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--predictions", required=True)
    p.add_argument("--metrics", required=True)
    p.add_argument("--adm1", default="data/cache/boundaries/ben_adm1.geojson")
    p.add_argument("--out-dir", default="docs/figures")
    args = p.parse_args()

    df = pd.read_parquet(args.predictions)
    metrics = json.loads(Path(args.metrics).read_text())
    adm1 = gpd.read_file(args.adm1).to_crs("EPSG:4326")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # === 1. Diagnostic dashboard ===
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    auc_shuf = metrics.get("cv_shuffled_roc_auc", metrics.get("cv_roc_auc"))
    auc_grp = metrics.get("cv_grouped_adm1_roc_auc")
    bri_shuf = metrics.get("cv_shuffled_brier", metrics.get("cv_brier"))
    bri_grp = metrics.get("cv_grouped_adm1_brier")
    title = (
        f"Stage C v0.2 - Benin (n_train={metrics['n_train']:,}, "
        f"AUC shuffled={auc_shuf:.3f} / ADM1-grouped={auc_grp:.3f}, "
        f"Brier {bri_shuf:.3f} / {bri_grp:.3f})"
    )
    fig.suptitle(title, fontsize=13, weight="bold")

    # 1a. Probability histogram, split by Stage A label.
    ax = axes[0, 0]
    pub_mask = df["ownership_confidence"] == "high"
    train_pub = df.loc[pub_mask & (df["ownership_label"] == "public"), "stage_c_p_private"]
    train_priv = df.loc[pub_mask & df["ownership_label"].isin(
        ["private-secular", "private-religious", "community"]), "stage_c_p_private"]
    unknowns = df.loc[df["ownership_label"] == "unknown", "stage_c_p_private"]
    bins = np.linspace(0, 1, 31)
    ax.hist(train_pub, bins=bins, alpha=0.7, label=f"Stage A public (n={len(train_pub)})", color="#1f77b4")
    ax.hist(train_priv, bins=bins, alpha=0.7, label=f"Stage A private (n={len(train_priv)})", color="#d73f3f")
    ax.hist(unknowns, bins=bins, alpha=0.55, label=f"Stage A unknown (n={len(unknowns)})", color="#888888")
    ax.set_xlabel("p(private) from Stage C")
    ax.set_ylabel("count (log)")
    ax.set_yscale("log")
    ax.set_title("Predicted probability by Stage A class")
    ax.legend(fontsize=9, frameon=False)

    # 1b. Calibration curve.
    ax = axes[0, 1]
    cc = metrics["calibration_curve"]
    ax.plot(cc["mean_predicted"], cc["fraction_positive"], "o-", color="#3a7d3a", label="model")
    ax.plot([0, 1], [0, 1], "k--", linewidth=0.8, label="perfect")
    ax.set_xlabel("mean predicted p(private)")
    ax.set_ylabel("fraction positive in bin")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Reliability diagram (5-fold CV, 10 quantile bins)")
    ax.legend(fontsize=9, frameon=False)
    ax.grid(linestyle=":", color="#cccccc", alpha=0.6)

    # 1c. Top features (signed).
    ax = axes[1, 0]
    fi = pd.DataFrame(metrics["feature_importance"]).head(10)
    fi = fi.iloc[::-1]
    colors = ["#d73f3f" if c > 0 else "#1f77b4" for c in fi["coef_mean"]]
    ax.barh(fi["feature"], fi["coef_mean"], color=colors)
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_title("Top 10 coefficients\n(positive -> pushes toward private)")
    ax.set_xlabel("standardised coefficient")

    # 1d. Final-label composition - conservative AND prior-shifted side by side.
    ax = axes[1, 1]
    order = [
        "public",
        "public-model",
        "private-secular",
        "private-religious",
        "community",
        "private-model",
        "uncertain",
        "unknown",
    ]
    palette = {
        "public": "#1f77b4",
        "public-model": "#7faed1",
        "private-secular": "#d73f3f",
        "private-religious": "#9467bd",
        "community": "#2ca02c",
        "private-model": "#e88a8a",
        "uncertain": "#f0c040",
        "unknown": "#bbbbbb",
    }
    cons = df["ownership_final"].value_counts().reindex(order, fill_value=0)
    adj_col = "ownership_final_adj" if "ownership_final_adj" in df.columns else "ownership_final"
    adj = df[adj_col].value_counts().reindex(order, fill_value=0)
    n = len(df)
    y = np.arange(len(order))
    h = 0.4
    ax.barh(y - h/2, cons.values, height=h, color=[palette[k] for k in order], edgecolor="white", label="conservative")
    ax.barh(y + h/2, adj.values, height=h, color=[palette[k] for k in order], edgecolor="white", alpha=0.55, hatch="//", label="prior-shifted")
    ax.set_yticks(y)
    ax.set_yticklabels(order)
    ax.invert_yaxis()
    for i, k in enumerate(order):
        if cons[k] > 0:
            ax.text(cons[k] + n * 0.005, i - h/2, f"{int(cons[k]):,}", va="center", fontsize=8)
        if adj[k] > 0:
            ax.text(adj[k] + n * 0.005, i + h/2, f"{int(adj[k]):,}", va="center", fontsize=8, color="#444")
    max_val = max(cons.values.max(), adj.values.max())
    ax.set_xlim(0, max_val * 1.35)
    ax.set_title(f"Final label - conservative (top) vs prior-shifted (bottom)\nn={n:,}")
    ax.legend(loc="lower right", fontsize=8, frameon=False)

    fig.tight_layout()
    fig.subplots_adjust(top=0.93)
    fig.savefig(out_dir / "stage_c_dashboard_BEN_2026-04-30.png", dpi=140)

    # === 2. Map of unknown predictions ===
    fig, axes = plt.subplots(1, 2, figsize=(15, 8), gridspec_kw={"width_ratios": [1.6, 1]})
    fig.suptitle("Stage C predictions for the 2,732 Stage-A unknowns", fontsize=13, weight="bold")

    unk = df[df["ownership_label"] == "unknown"].copy()
    unk["geometry"] = gpd.points_from_xy(unk["lon"], unk["lat"])
    unk_g = gpd.GeoDataFrame(unk, geometry="geometry", crs="EPSG:4326")

    ax = axes[0]
    adm1.boundary.plot(ax=ax, color="#666666", linewidth=0.6)
    sc = ax.scatter(
        unk_g.geometry.x,
        unk_g.geometry.y,
        c=unk_g["stage_c_p_private"],
        cmap="RdBu_r",
        vmin=0,
        vmax=1,
        s=8,
        alpha=0.75,
        linewidth=0,
    )
    cb = plt.colorbar(sc, ax=ax, shrink=0.7)
    cb.set_label("predicted p(private)")
    ax.set_aspect("equal")
    ax.set_title("All unknowns, coloured by predicted p(private)")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")

    ax = axes[1]
    adm1.boundary.plot(ax=ax, color="#666666", linewidth=0.6)
    sc = ax.scatter(
        unk_g.geometry.x,
        unk_g.geometry.y,
        c=unk_g["stage_c_p_private"],
        cmap="RdBu_r",
        vmin=0,
        vmax=1,
        s=20,
        alpha=0.85,
        linewidth=0,
    )
    ax.set_xlim(2.05, 2.7)
    ax.set_ylim(6.25, 6.7)
    ax.set_aspect("equal")
    ax.set_title("Zoom: Greater Cotonou / Porto-Novo")

    fig.tight_layout()
    fig.subplots_adjust(top=0.93)
    fig.savefig(out_dir / "stage_c_unknowns_map_BEN_2026-04-30.png", dpi=140, bbox_inches="tight")

    # === 3. Summary stats printed for the writeup ===
    print("=== Stage C Summary ===")
    print(f"Trained on: {metrics['n_train']:,} high-conf rows  ({metrics['n_public_train']:,} public, {metrics['n_private_train']:,} private)")
    print(f"5-fold CV ROC-AUC: {metrics['cv_roc_auc']:.3f}")
    print(f"5-fold CV Brier:   {metrics['cv_brier']:.3f}")
    print()
    print("Predictions on the 2,732 Stage-A unknowns:")
    print(unk["stage_c_band"].value_counts().to_string())
    print()
    print(f"Predicted private share (p>=0.5) overall: {(df['stage_c_p_private'] >= 0.5).mean()*100:.2f}%")
    print(f"Predicted private share (p>=0.3) overall: {(df['stage_c_p_private'] >= 0.3).mean()*100:.2f}%")
    print()
    print("Final-label composition:")
    print(df["ownership_final"].value_counts().to_string())


if __name__ == "__main__":
    main()
