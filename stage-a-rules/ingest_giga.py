"""Filter a WAFR Giga schools CSV export to one country and write a normalised GeoJSON.

The Giga CSV has these columns:
  School Giga ID, school_ID, School Name, longitude, latitude,
  Education Level, Country ISO3 Code, Country Name, School Data Source

Output GeoDataFrame columns:
  school_id, name_giga, level, iso3, source ("giga"), geometry (Point, EPSG:4326)

The default input path is resolved from the SCHOOL_DATA_DIR environment variable.
See data/README.md for the expected directory layout.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def _default_giga_csv() -> Path | None:
    base = os.environ.get("SCHOOL_DATA_DIR")
    if not base:
        return None
    return Path(base).expanduser() / "1. School locations" / "WAFR_Schools_GIGA_ALL_dated_08122025_203756.csv"


def load_giga(csv_path: Path, iso3: str) -> gpd.GeoDataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"Giga CSV not found: {csv_path}")
    df = pd.read_csv(csv_path)
    df = df[df["Country ISO3 Code"] == iso3].copy()
    if df.empty:
        raise ValueError(f"No rows for iso3={iso3} in {csv_path}")

    df = df.rename(
        columns={
            "School Giga ID": "school_id",
            "School Name": "name_giga",
            "Education Level": "level",
            "Country ISO3 Code": "iso3",
        }
    )
    df["source"] = "giga"
    df["name_giga"] = df["name_giga"].astype(str).str.strip()
    keep = ["school_id", "name_giga", "level", "iso3", "source", "longitude", "latitude"]
    df = df[keep]
    df = df.dropna(subset=["longitude", "latitude"])

    geom = [Point(xy) for xy in zip(df["longitude"].astype(float), df["latitude"].astype(float))]
    gdf = gpd.GeoDataFrame(df.drop(columns=["longitude", "latitude"]), geometry=geom, crs="EPSG:4326")
    return gdf


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest a WAFR Giga schools CSV and filter to one country.")
    p.add_argument("--iso3", required=True, help="ISO3 code, e.g. BEN")
    p.add_argument("--csv", default=None, help="Path to Giga CSV (defaults to $SCHOOL_DATA_DIR layout)")
    p.add_argument("--output", required=True, help="Output GeoJSON path")
    args = p.parse_args()

    csv_path = Path(args.csv) if args.csv else _default_giga_csv()
    if csv_path is None:
        raise SystemExit("No --csv given and SCHOOL_DATA_DIR is unset. See data/README.md.")

    gdf = load_giga(csv_path, args.iso3)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(args.output, driver="GeoJSON")
    print(f"wrote {len(gdf)} {args.iso3} schools -> {args.output}")


if __name__ == "__main__":
    main()
