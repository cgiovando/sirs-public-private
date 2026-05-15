"""Parse INFRE annuaires-statistiques Excel files into a per-department prior.

INFRE publishes per-year .xls files at
<https://www.infre-benin.org/annuaires-statistiques.html>. We use the 2021-22
versions:

  901_PUBLIC&PRIVE_VERS_PROV 2021-2022.xls -> public + private primary
  902_PUBLIC_VERS_PROV 2021-2022.xls       -> public-only primary

Both have a sheet `01DATA_GL` (Données générales par département) where the
'Masculin' row of each department block carries the school count in column 5.
By subtracting public-only from total, we get private counts per department.

Output: data/cache/infre/benin_dept_priors_2021_2022.parquet
  columns: department, n_schools_total, n_schools_public, n_schools_private,
           private_share
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

# 12 Benin ADM1 names (in INFRE all-caps spelling, with Atlantique misspelling
# observed in the file as "ATLANIQUE" or "ATLANTIQUE" depending on year).
BENIN_DEPARTMENTS = [
    "ATACORA",
    "DONGA",
    "ATLANTIQUE",
    "LITTORAL",
    "BORGOU",
    "ALIBORI",
    "OUEME",
    "PLATEAU",
    "MONO",
    "COUFFO",
    "ZOU",
    "COLLINES",
]


def read_n_schools_per_department(xls_path: Path) -> dict[str, int]:
    """Walk the 01DATA_GL sheet, picking the first block of department-level
    rows. After the 12 departments are seen, stop - subsequent rows are
    commune-level (ADM2) data we don't want."""
    df = pd.read_excel(xls_path, sheet_name="01DATA_GL", header=None)

    out: dict[str, int] = {}
    cur_dept: str | None = None

    for i in range(len(df)):
        v0 = df.iloc[i, 0]
        if isinstance(v0, str):
            v0_clean = v0.strip().upper()
            if v0_clean in BENIN_DEPARTMENTS and v0_clean not in out:
                cur_dept = v0_clean
                continue
            if v0_clean == "MASCULIN" and cur_dept is not None:
                v_schools = df.iloc[i, 5]
                if pd.notna(v_schools):
                    out[cur_dept] = int(v_schools)
                cur_dept = None  # consumed
        if len(out) == len(BENIN_DEPARTMENTS):
            break

    missing = [d for d in BENIN_DEPARTMENTS if d not in out]
    if missing:
        raise ValueError(f"INFRE parse missed departments {missing} in {xls_path}")
    return out


# ADM1 names in geoBoundaries spelling (Atlanique misspelling preserved).
INFRE_TO_GEOB = {
    "ATACORA": "Atakora",
    "DONGA": "Donga",
    "ATLANTIQUE": "Atlanique",
    "LITTORAL": "Littoral",
    "BORGOU": "Borgou",
    "ALIBORI": "Alibori",
    "OUEME": "Oueme",
    "PLATEAU": "Plateau",
    "MONO": "Mono",
    "COUFFO": "Kouffo",
    "ZOU": "Zou",
    "COLLINES": "Collines",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pp", default="data/cache/infre/ben_901_PubPrive_2021_2022.xls")
    p.add_argument("--pu", default="data/cache/infre/ben_902_Public_2021_2022.xls")
    p.add_argument("--output", default="data/cache/infre/benin_dept_priors_2021_2022.parquet")
    args = p.parse_args()

    pp_counts = read_n_schools_per_department(Path(args.pp))
    pu_counts = read_n_schools_per_department(Path(args.pu))

    rows = []
    for d in BENIN_DEPARTMENTS:
        n_total = pp_counts[d]
        n_pub = pu_counts[d]
        n_priv = n_total - n_pub
        rows.append(
            {
                "department_infre": d,
                "department": INFRE_TO_GEOB[d],
                "n_schools_total": n_total,
                "n_schools_public": n_pub,
                "n_schools_private": n_priv,
                "private_share": n_priv / n_total if n_total else None,
            }
        )

    df = pd.DataFrame(rows).sort_values("private_share", ascending=False)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)

    print(f"wrote {len(df)} rows -> {args.output}")
    print()
    print(df.to_string(index=False))
    print()
    total = df["n_schools_total"].sum()
    pub = df["n_schools_public"].sum()
    priv = df["n_schools_private"].sum()
    print(f"NATIONAL: {total:,} primary schools = {pub:,} public + {priv:,} private "
          f"({priv/total*100:.1f}% private)")


if __name__ == "__main__":
    main()
