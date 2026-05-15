"""Spatial-plus-name join between a Giga GeoJSON and an OSM GeoJSON.

Strategy
- Project both layers to a metric CRS suitable for the country (UTM auto-pick).
- For each Giga point, find OSM candidates within `--buffer-m` (default 100 m).
- Among candidates, pick the best name match (token_set_ratio on Unicode-folded
  uppercase strings); accept if score >= `--name-threshold` (default 70).
  If no candidate clears the threshold, accept the spatially nearest OSM record
  ONLY when there is exactly one candidate (avoid arbitrary picks in clusters).
- Output one feature per Giga record (matched or unmatched), plus all OSM
  records that did not match any Giga record.

Output schema (every feature):
  school_id           : str   (Giga UUID, OSM osm_id, or composite)
  source              : "giga_osm" | "giga_only" | "osm_only"
  name_giga, name_osm, name_fr, int_name
  level                                              (Giga, when present)
  operator, operator_type, religion, denomination, school_type, isced_level (OSM)
  iso3
  match_dist_m        : float | null
  match_name_score    : int | null
  geometry            : Point (Giga point if matched, else source point)
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz
from shapely.geometry import Point
from unidecode import unidecode


def utm_epsg_for_lon_lat(lon: float, lat: float) -> int:
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    return (32600 if lat >= 0 else 32700) + zone


def normalise_name(name: str | None) -> str:
    if not isinstance(name, str):
        return ""
    return unidecode(name).upper().strip()


def best_name_match(giga_name: str, osm_names: list[str]) -> tuple[int, int]:
    g = normalise_name(giga_name)
    best_idx, best_score = -1, -1
    for i, n in enumerate(osm_names):
        nn = normalise_name(n)
        if not nn:
            continue
        score = fuzz.token_set_ratio(g, nn)
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx, best_score


OUTPUT_COLS = [
    "school_id",
    "source",
    "name_giga",
    "name_osm",
    "name_fr",
    "int_name",
    "level",
    "operator",
    "operator_type",
    "religion",
    "denomination",
    "school_type",
    "isced_level",
    "iso3",
    "match_dist_m",
    "match_name_score",
    "geometry",
]


def join(giga: gpd.GeoDataFrame, osm: gpd.GeoDataFrame, buffer_m: float, name_threshold: int) -> gpd.GeoDataFrame:
    if giga.crs is None or osm.crs is None:
        raise ValueError("inputs must have a CRS")

    centroid = giga.geometry.union_all().centroid
    epsg = utm_epsg_for_lon_lat(centroid.x, centroid.y)
    giga_m = giga.to_crs(epsg=epsg).copy()
    osm_m = osm.to_crs(epsg=epsg).copy()
    giga_m["_gix"] = range(len(giga_m))
    osm_m["_oix"] = range(len(osm_m))

    giga_buf = giga_m[["_gix", "geometry"]].copy()
    giga_buf["geometry"] = giga_buf.geometry.buffer(buffer_m)

    candidates = gpd.sjoin(
        giga_buf,
        osm_m[["_oix", "geometry"]],
        how="left",
        predicate="intersects",
    )

    matched_oix: set[int] = set()
    rows: list[dict] = []

    for gix, group in candidates.groupby("_gix", sort=False):
        giga_row = giga_m.iloc[gix]
        cand_oix = [int(o) for o in group["_oix"].dropna().tolist()]

        chosen_oix: int | None = None
        score: int | None = None

        if cand_oix:
            osm_names = [osm_m.iloc[o]["name_osm"] for o in cand_oix]
            best_local_idx, best_score = best_name_match(giga_row["name_giga"], osm_names)
            if best_local_idx >= 0 and best_score >= name_threshold:
                chosen_oix = cand_oix[best_local_idx]
                score = int(best_score)
            elif len(cand_oix) == 1:
                # only one candidate in 100m, accept geometry alone but flag low name score
                chosen_oix = cand_oix[0]
                score = int(best_score) if best_score >= 0 else None

        if chosen_oix is not None:
            matched_oix.add(chosen_oix)
            osm_row = osm_m.iloc[chosen_oix]
            dist = giga_row.geometry.distance(osm_row.geometry)
            rows.append(
                {
                    "school_id": giga_row["school_id"],
                    "source": "giga_osm",
                    "name_giga": giga_row["name_giga"],
                    "name_osm": osm_row["name_osm"],
                    "name_fr": osm_row["name_fr"],
                    "int_name": osm_row["int_name"],
                    "level": giga_row["level"],
                    "operator": osm_row["operator"],
                    "operator_type": osm_row["operator_type"],
                    "religion": osm_row["religion"],
                    "denomination": osm_row["denomination"],
                    "school_type": osm_row["school_type"],
                    "isced_level": osm_row["isced_level"],
                    "iso3": giga_row["iso3"],
                    "match_dist_m": float(round(dist, 1)),
                    "match_name_score": score,
                    "geometry": giga_row.geometry,  # Giga point wins
                }
            )
        else:
            rows.append(
                {
                    "school_id": giga_row["school_id"],
                    "source": "giga_only",
                    "name_giga": giga_row["name_giga"],
                    "name_osm": None,
                    "name_fr": None,
                    "int_name": None,
                    "level": giga_row["level"],
                    "operator": None,
                    "operator_type": None,
                    "religion": None,
                    "denomination": None,
                    "school_type": None,
                    "isced_level": None,
                    "iso3": giga_row["iso3"],
                    "match_dist_m": None,
                    "match_name_score": None,
                    "geometry": giga_row.geometry,
                }
            )

    # Append OSM-only records.
    for oix in range(len(osm_m)):
        if oix in matched_oix:
            continue
        osm_row = osm_m.iloc[oix]
        rows.append(
            {
                "school_id": osm_row["school_id"],
                "source": "osm_only",
                "name_giga": None,
                "name_osm": osm_row["name_osm"],
                "name_fr": osm_row["name_fr"],
                "int_name": osm_row["int_name"],
                "level": None,
                "operator": osm_row["operator"],
                "operator_type": osm_row["operator_type"],
                "religion": osm_row["religion"],
                "denomination": osm_row["denomination"],
                "school_type": osm_row["school_type"],
                "isced_level": osm_row["isced_level"],
                "iso3": osm_row["iso3"],
                "match_dist_m": None,
                "match_name_score": None,
                "geometry": osm_row.geometry,
            }
        )

    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=epsg)
    out = out.to_crs("EPSG:4326")
    return out[OUTPUT_COLS]


def main() -> None:
    p = argparse.ArgumentParser(description="Spatial+name join Giga to OSM.")
    p.add_argument("--giga", required=True)
    p.add_argument("--osm", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--buffer-m", type=float, default=100.0)
    p.add_argument("--name-threshold", type=int, default=70)
    args = p.parse_args()

    giga = gpd.read_file(args.giga)
    osm = gpd.read_file(args.osm)
    out = join(giga, osm, args.buffer_m, args.name_threshold)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_file(args.output, driver="GeoJSON")
    counts = out["source"].value_counts()
    print(f"wrote {len(out)} features -> {args.output}")
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
