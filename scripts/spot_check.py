"""Stratified random spot-check sample for manual review.

Pulls 10 records each from {high, medium, none} confidence (low is empty in v0.1)
plus 10 records sampled from the 'unknown' label specifically. Writes a CSV
with empty `manual_label` and `manual_notes` columns for the user to fill in.

Run:
  python scripts/spot_check.py \
    --input data/derived/stage_a_labels_BEN_2026-04-30.geojson \
    --output docs/spot_check_BEN_2026-04-30.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

SAMPLE_PER_BAND = 10


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    gdf = gpd.read_file(args.input)

    samples = []
    for conf in ("high", "medium", "none"):
        sub = gdf[gdf["ownership_confidence"] == conf]
        if len(sub) == 0:
            continue
        n = min(SAMPLE_PER_BAND, len(sub))
        samples.append(sub.sample(n=n, random_state=args.seed).assign(_band=conf))

    # Extra band: 10 unknowns specifically (overlaps with conf=none/medium).
    unk = gdf[gdf["ownership_label"] == "unknown"]
    if len(unk):
        samples.append(unk.sample(n=min(SAMPLE_PER_BAND, len(unk)), random_state=args.seed + 1).assign(_band="unknown"))

    out = pd.concat(samples, axis=0, ignore_index=True)
    out["lon"] = out.geometry.x.round(6)
    out["lat"] = out.geometry.y.round(6)
    out["manual_label"] = ""
    out["manual_notes"] = ""

    cols = [
        "_band",
        "school_id",
        "name",
        "ownership_label",
        "ownership_confidence",
        "join_source",
        "name_giga",
        "name_osm",
        "operator_type",
        "religion",
        "match_dist_m",
        "match_name_score",
        "audit",
        "lon",
        "lat",
        "manual_label",
        "manual_notes",
    ]
    out = out[cols]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"wrote {len(out)} sample rows -> {args.output}")
    print(out.groupby("_band")["ownership_label"].value_counts().to_string())


if __name__ == "__main__":
    main()
