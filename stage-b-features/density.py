"""School-neighbour density features.

For each school point:
  schools_within_1km, schools_within_5km, dist_to_nearest_school_m

Computed in metric CRS (UTM 31N) using a buffered self-join.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


def utm31n(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.to_crs(epsg=32631)


def add_density(schools: gpd.GeoDataFrame) -> pd.DataFrame:
    s = utm31n(schools)[["school_id", "geometry"]].copy()
    s["_idx"] = range(len(s))

    # Pre-compute buffered geometries for both radii.
    out = pd.DataFrame({"school_id": s["school_id"].values})

    for radius_m, col in [(1000, "schools_within_1km"), (5000, "schools_within_5km")]:
        buf = s.copy()
        buf["geometry"] = buf.geometry.buffer(radius_m)
        joined = gpd.sjoin(buf[["_idx", "geometry"]], s[["_idx", "geometry"]], predicate="intersects", how="left")
        # subtract 1 (self), zero-clip
        counts = joined.groupby("_idx_left").size().reindex(s["_idx"]).fillna(1).astype(int) - 1
        out[col] = counts.values

    # Nearest-neighbour distance (excluding self): KDTree query for the 2nd-nearest.
    from scipy.spatial import cKDTree
    coords = np.column_stack([s.geometry.x.values, s.geometry.y.values])
    tree = cKDTree(coords)
    dists, _ = tree.query(coords, k=2)
    out["dist_to_nearest_school_m"] = np.round(dists[:, 1], 1)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    gdf = gpd.read_file(args.input)
    out = add_density(gdf)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"wrote {len(out)} rows -> {args.output}")
    print(out[["schools_within_1km", "schools_within_5km", "dist_to_nearest_school_m"]].describe().to_string())


if __name__ == "__main__":
    main()
