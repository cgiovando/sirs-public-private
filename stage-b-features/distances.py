"""Distance-based features for Stage B.

For each school point, compute:
  dist_to_cotonou_km, dist_to_porto_novo_km, dist_to_parakou_km,
  dist_to_nearest_major_city_km, nearest_major_city,
  dist_to_coast_km

Plus, given the OSM `amenity=place_of_worship` pull (separate file),
nearest mosque / nearest church distance.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

# Approximate centres of Benin's largest urban areas. Sourced manually; intent
# is "is this school near a place where private schools concentrate", not a
# precise geocoder.
BENIN_MAJOR_CITIES = {
    "Cotonou": (2.3912, 6.3654),
    "Porto-Novo": (2.6253, 6.4969),
    "Parakou": (2.6035, 9.3370),
    "Abomey-Calavi": (2.3553, 6.4480),
    "Bohicon": (2.0666, 7.1781),
    "Djougou": (1.6660, 9.7090),
    "Natitingou": (1.3784, 10.3210),
    "Lokossa": (1.7172, 6.6388),
}


def utm31n(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.to_crs(epsg=32631)


def cities_gdf() -> gpd.GeoDataFrame:
    rows = [{"city": name, "geometry": Point(lon, lat)} for name, (lon, lat) in BENIN_MAJOR_CITIES.items()]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def add_city_distances(schools: gpd.GeoDataFrame) -> pd.DataFrame:
    """Append per-city distances and nearest-city columns. Returns a DataFrame
    with `school_id` and the distance columns; merge into the feature frame."""
    s_m = utm31n(schools)
    c_m = utm31n(cities_gdf())

    out = pd.DataFrame({"school_id": schools["school_id"].values})
    nearest_dist = np.full(len(s_m), np.inf)
    nearest_name = np.array([""] * len(s_m), dtype=object)

    for _, c in c_m.iterrows():
        name = c["city"]
        d = s_m.geometry.distance(c.geometry).values / 1000.0
        col = f"dist_to_{name.lower().replace('-', '_')}_km"
        out[col] = np.round(d, 3)
        better = d < nearest_dist
        nearest_dist = np.where(better, d, nearest_dist)
        nearest_name = np.where(better, name, nearest_name)

    out["dist_to_nearest_major_city_km"] = np.round(nearest_dist, 3)
    out["nearest_major_city"] = nearest_name
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Stage A artifact (GeoJSON)")
    p.add_argument("--output", required=True, help="Output parquet with distance features")
    args = p.parse_args()

    gdf = gpd.read_file(args.input)
    out = add_city_distances(gdf)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"wrote {len(out)} rows -> {args.output}")
    print(out[["dist_to_nearest_major_city_km", "nearest_major_city"]].describe(include="all").to_string())


if __name__ == "__main__":
    main()
