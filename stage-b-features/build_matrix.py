"""Combine all Stage B feature parquets + Stage A label into one matrix.

Output: data/derived/benin_features_<date>.parquet plus a sidecar provenance JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import geopandas as gpd
import pandas as pd


FEATURE_PARQUETS = [
    "benin_distances.parquet",
    "benin_density.parquet",
    "benin_worship.parquet",
    "benin_ghsl_smod.parquet",
    "benin_rwi.parquet",
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent.parent,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--stage-a", required=True)
    p.add_argument("--features-dir", default="data/derived/features")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    stage_a = gpd.read_file(args.stage_a)
    keep = [
        "school_id",
        "name",
        "iso3",
        "adm1",
        "level",
        "ownership_label",
        "ownership_confidence",
        "join_source",
    ]
    base = pd.DataFrame(stage_a[keep])
    base["lon"] = stage_a.geometry.x.round(6)
    base["lat"] = stage_a.geometry.y.round(6)

    fdir = Path(args.features_dir)
    inputs = []
    for fname in FEATURE_PARQUETS:
        fpath = fdir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"missing feature file: {fpath}")
        df = pd.read_parquet(fpath)
        base = base.merge(df, on="school_id", how="left")
        inputs.append({"path": str(fpath), "sha256": sha256_file(fpath)})

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    base.to_parquet(args.output, index=False)
    print(f"wrote {len(base)} rows x {base.shape[1]} cols -> {args.output}")
    print()
    print("columns:", list(base.columns))

    prov_path = Path(args.output).with_suffix(Path(args.output).suffix + ".provenance.json")
    prov = {
        "output": str(args.output),
        "stage_a_input": {"path": args.stage_a, "sha256": sha256_file(Path(args.stage_a))},
        "feature_inputs": inputs,
        "git_commit": git_commit(),
        "runtime_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    prov_path.write_text(json.dumps(prov, indent=2))
    print(f"provenance -> {prov_path}")


if __name__ == "__main__":
    main()
