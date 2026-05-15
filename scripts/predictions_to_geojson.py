"""Convert Stage C parquet predictions to a slim GeoJSON for the webmap."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

KEEP = [
    "school_id",
    "name",
    "level",
    "adm1",
    "ownership_label",
    "ownership_confidence",
    "ownership_final",
    "ownership_final_adj",
    "stage_c_p_private",
    "stage_c_p_private_adj",
    "stage_c_band",
    "stage_c_band_adj",
    "model_agreement",
    "join_source",
    "audit",
    "dept_prior_private",
]


def main() -> None:
    df = pd.read_parquet("data/derived/stage_c_predictions_BEN_2026-04-30.parquet")
    cols = [c for c in KEEP if c in df.columns]
    features = []
    for _, row in df.iterrows():
        props = {c: (None if pd.isna(row[c]) else row[c]) for c in cols}
        # numpy / pandas types are not JSON-serialisable
        for k, v in list(props.items()):
            if hasattr(v, "item"):
                try:
                    props[k] = v.item()
                except Exception:
                    props[k] = str(v)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row["lon"]), 6), round(float(row["lat"]), 6)],
                },
                "properties": props,
            }
        )
    fc = {"type": "FeatureCollection", "features": features}
    out = Path("docs/webmap/data/schools.geojson")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"wrote {len(features)} features -> {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
