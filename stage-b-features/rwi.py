"""Meta Relative Wealth Index per school point.

The HDX RWI is a CSV of (lat, lon, rwi, error) at ~2.4 km Bing tile resolution.
For each school we take the nearest cell. RWI is z-scored within country and
ranges roughly [-2, +2]; higher = wealthier.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point


def add_rwi(schools: gpd.GeoDataFrame, rwi_csv: Path) -> pd.DataFrame:
    rwi = pd.read_csv(rwi_csv)
    s_m = schools.to_crs(epsg=32631)
    rwi_g = gpd.GeoDataFrame(
        rwi,
        geometry=[Point(lon, lat) for lon, lat in zip(rwi["longitude"], rwi["latitude"])],
        crs="EPSG:4326",
    ).to_crs(epsg=32631)

    s_xy = np.column_stack([s_m.geometry.x.values, s_m.geometry.y.values])
    r_xy = np.column_stack([rwi_g.geometry.x.values, rwi_g.geometry.y.values])

    tree = cKDTree(r_xy)
    dists, idx = tree.query(s_xy, k=1)
    rwi_vals = rwi_g["rwi"].values[idx]
    rwi_err = rwi_g["error"].values[idx]

    return pd.DataFrame(
        {
            "school_id": schools["school_id"].values,
            "rwi": np.round(rwi_vals, 3),
            "rwi_error": np.round(rwi_err, 3),
            "rwi_cell_dist_m": np.round(dists, 1),
        }
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--rwi", default="data/cache/rwi/ben_rwi.csv")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    schools = gpd.read_file(args.input)
    out = add_rwi(schools, Path(args.rwi))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"wrote {len(out)} rows -> {args.output}")
    print(out[["rwi", "rwi_error", "rwi_cell_dist_m"]].describe().to_string())


if __name__ == "__main__":
    main()
