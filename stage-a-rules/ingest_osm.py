"""Pull `amenity=school` for one country from Overpass and emit a normalised GeoJSON.

Cached to data/cache/overpass_<iso2>.json so that re-runs are free.

Output columns:
  school_id (osm_<type>_<id>), name_osm, name_fr, int_name,
  operator, operator_type, religion, denomination, school_type, isced_level,
  iso3, source ("osm"), geometry (Point, EPSG:4326)

Polygon ways/relations are reduced to their representative point so the join step
can treat all rows uniformly.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Point, Polygon

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

ISO2_FOR_ISO3 = {"BEN": "BJ", "NER": "NE", "MLI": "ML", "GIN": "GN", "GHA": "GH"}

KEEP_TAGS = {
    "name",
    "name:fr",
    "int_name",
    "operator",
    "operator:type",
    "religion",
    "denomination",
    "school:type",
    "isced:level",
}


def overpass_query(iso2: str) -> str:
    return f"""
[out:json][timeout:180];
area["ISO3166-1"="{iso2}"]->.a;
(
  node["amenity"="school"](area.a);
  way["amenity"="school"](area.a);
  relation["amenity"="school"](area.a);
);
out center;
""".strip()


def fetch_overpass(iso2: str, cache_path: Path) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"querying overpass for {iso2}...")
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


def element_to_record(el: dict[str, Any], iso3: str) -> dict[str, Any] | None:
    tags = el.get("tags") or {}
    if "lat" in el and "lon" in el:
        lon, lat = float(el["lon"]), float(el["lat"])
    elif "center" in el:
        lon, lat = float(el["center"]["lon"]), float(el["center"]["lat"])
    else:
        return None
    name = tags.get("name") or tags.get("name:fr") or tags.get("int_name")
    return {
        "school_id": f"osm_{el['type']}_{el['id']}",
        "name_osm": name,
        "name_fr": tags.get("name:fr"),
        "int_name": tags.get("int_name"),
        "operator": tags.get("operator"),
        "operator_type": tags.get("operator:type"),
        "religion": tags.get("religion"),
        "denomination": tags.get("denomination"),
        "school_type": tags.get("school:type"),
        "isced_level": tags.get("isced:level"),
        "iso3": iso3,
        "source": "osm",
        "geometry": Point(lon, lat),
    }


def load_osm(iso3: str, cache_dir: Path) -> gpd.GeoDataFrame:
    if iso3 not in ISO2_FOR_ISO3:
        raise ValueError(f"no ISO2 mapping for iso3={iso3}; add to ISO2_FOR_ISO3")
    iso2 = ISO2_FOR_ISO3[iso3]
    data = fetch_overpass(iso2, cache_dir / f"overpass_{iso2}.json")
    elements = data.get("elements", [])
    records = [r for r in (element_to_record(el, iso3) for el in elements) if r is not None]
    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    return gdf


def main() -> None:
    p = argparse.ArgumentParser(description="Pull amenity=school from Overpass for one country.")
    p.add_argument("--iso3", required=True, help="ISO3 code, e.g. BEN")
    p.add_argument("--cache-dir", default="data/cache", help="Overpass cache dir")
    p.add_argument("--output", required=True, help="Output GeoJSON path")
    args = p.parse_args()

    gdf = load_osm(args.iso3, Path(args.cache_dir))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(args.output, driver="GeoJSON")
    print(f"wrote {len(gdf)} OSM schools for {args.iso3} -> {args.output}")
    n_op_type = gdf["operator_type"].notna().sum()
    n_religion = gdf["religion"].notna().sum()
    print(f"  operator:type set on {n_op_type} ({100*n_op_type/max(len(gdf),1):.1f}%)")
    print(f"  religion set on {n_religion} ({100*n_religion/max(len(gdf),1):.1f}%)")


if __name__ == "__main__":
    main()
