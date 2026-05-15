"""Distance to nearest religious POI from OSM `amenity=place_of_worship`.

Per-school features:
  dist_to_mosque_m, dist_to_church_m, dist_to_any_worship_m,
  worship_within_500m  (count, any religion)

Religion classification uses OSM `religion` tag:
  muslim -> mosque
  christian | catholic | protestant -> church
  other / unset -> "any"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from shapely.geometry import Point

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

ISO2_FOR_ISO3 = {"BEN": "BJ", "NER": "NE", "MLI": "ML", "GIN": "GN", "GHA": "GH"}


def overpass_query(iso2: str) -> str:
    return f"""
[out:json][timeout:180];
area["ISO3166-1"="{iso2}"]->.a;
(
  node["amenity"="place_of_worship"](area.a);
  way["amenity"="place_of_worship"](area.a);
  relation["amenity"="place_of_worship"](area.a);
);
out center;
""".strip()


def fetch(iso2: str, cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"querying overpass for place_of_worship in {iso2}...")
    r = requests.post(
        OVERPASS_URL,
        data={"data": overpass_query(iso2)},
        headers={"User-Agent": "sirs-public-private/0.1 (giovand@gmail.com)"},
        timeout=300,
    )
    r.raise_for_status()
    data = r.json()
    cache_path.write_text(json.dumps(data))
    return data


def to_gdf(data: dict) -> gpd.GeoDataFrame:
    rows = []
    for el in data.get("elements", []):
        if "lat" in el and "lon" in el:
            lon, lat = float(el["lon"]), float(el["lat"])
        elif "center" in el:
            lon, lat = float(el["center"]["lon"]), float(el["center"]["lat"])
        else:
            continue
        tags = el.get("tags") or {}
        rows.append(
            {
                "religion": (tags.get("religion") or "").lower(),
                "denomination": (tags.get("denomination") or "").lower(),
                "geometry": Point(lon, lat),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def add_worship_features(schools: gpd.GeoDataFrame, worship: gpd.GeoDataFrame) -> pd.DataFrame:
    s_m = schools.to_crs(epsg=32631)
    w_m = worship.to_crs(epsg=32631)

    def rel_class(r: str, d: str) -> str:
        if "muslim" in r or "islam" in r:
            return "mosque"
        if any(k in r for k in ("christian", "catholic", "protestant")) or any(
            k in d for k in ("catholic", "protestant", "evangelical", "baptist", "methodist", "presbyterian", "anglican")
        ):
            return "church"
        return "other"

    w_m = w_m.assign(_class=[rel_class(r, d) for r, d in zip(w_m["religion"], w_m["denomination"])])

    s_coords = np.column_stack([s_m.geometry.x.values, s_m.geometry.y.values])

    out = pd.DataFrame({"school_id": schools["school_id"].values})

    def kd_dist(filtered: gpd.GeoDataFrame) -> np.ndarray:
        if len(filtered) == 0:
            return np.full(len(s_coords), np.nan)
        c = np.column_stack([filtered.geometry.x.values, filtered.geometry.y.values])
        tree = cKDTree(c)
        d, _ = tree.query(s_coords, k=1)
        return d

    out["dist_to_mosque_m"] = np.round(kd_dist(w_m[w_m["_class"] == "mosque"]), 1)
    out["dist_to_church_m"] = np.round(kd_dist(w_m[w_m["_class"] == "church"]), 1)
    out["dist_to_any_worship_m"] = np.round(kd_dist(w_m), 1)

    # Count of any-religion worship within 500m.
    if len(w_m):
        c = np.column_stack([w_m.geometry.x.values, w_m.geometry.y.values])
        tree = cKDTree(c)
        counts = [len(tree.query_ball_point(p, r=500)) for p in s_coords]
        out["worship_within_500m"] = counts
    else:
        out["worship_within_500m"] = 0

    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--iso3", required=True)
    p.add_argument("--cache-dir", default="data/cache")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    iso2 = ISO2_FOR_ISO3[args.iso3]
    data = fetch(iso2, Path(args.cache_dir) / f"overpass_worship_{iso2}.json")
    worship = to_gdf(data)
    print(f"loaded {len(worship)} worship POIs")
    print(worship["religion"].value_counts(dropna=False).head().to_string())

    schools = gpd.read_file(args.input)
    out = add_worship_features(schools, worship)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"wrote {len(out)} rows -> {args.output}")
    print(out.describe().to_string())


if __name__ == "__main__":
    main()
