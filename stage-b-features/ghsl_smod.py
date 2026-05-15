"""GHSL Settlement Model (SMOD) class per school point.

Class codes (R2023A V2):
  10  water
  11  very low density rural
  12  low density rural
  13  rural cluster
  21  suburban / peri-urban
  22  semi-dense urban
  23  dense urban cluster
  30  urban centre
  -200 / NoData

We collapse to a coarse class for the model:
  rural        : 11, 12, 13
  peri_urban   : 21, 22
  urban        : 23, 30
  water/nodata : <11
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as rio_transform


SMOD_TIF = Path("data/cache/ghsl/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif")


def coarse_class(code: int) -> str:
    if code in (30, 23):
        return "urban"
    if code in (21, 22):
        return "peri_urban"
    if code in (11, 12, 13):
        return "rural"
    return "other"


def add_smod(schools: gpd.GeoDataFrame, tif: Path = SMOD_TIF) -> pd.DataFrame:
    if not tif.exists():
        raise FileNotFoundError(f"GHSL SMOD raster not found: {tif}")
    with rasterio.open(tif) as src:
        # Project schools to the raster CRS (Mollweide).
        xs = schools.geometry.x.values
        ys = schools.geometry.y.values
        rx, ry = rio_transform("EPSG:4326", src.crs, xs.tolist(), ys.tolist())
        coords = list(zip(rx, ry))
        # rasterio.sample is the canonical efficient lookup.
        vals = np.fromiter((v[0] for v in src.sample(coords)), dtype=np.int32, count=len(coords))

    out = pd.DataFrame(
        {
            "school_id": schools["school_id"].values,
            "smod_code": vals,
            "smod_class": [coarse_class(int(v)) for v in vals],
        }
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--tif", default=str(SMOD_TIF))
    args = p.parse_args()

    schools = gpd.read_file(args.input)
    out = add_smod(schools, Path(args.tif))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"wrote {len(out)} rows -> {args.output}")
    print(out["smod_class"].value_counts().to_string())
    print()
    print("smod_code raw:")
    print(out["smod_code"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
