# Data licensing and attribution

The **code** in this repository is licensed under the Apache License 2.0 (see [`LICENSE`](LICENSE)). The **data** distributed with this repository (under `docs/webmap/data/` and any future `data/` outputs that get checked in) is a derived dataset combining multiple upstream sources, each with its own license. To stay compliant with the most restrictive upstream (OpenStreetMap, ODbL 1.0), the published derived dataset is released under **ODbL 1.0**.

## Upstream sources and attributions

### School locations and tags

- **OpenStreetMap contributors** - `amenity=school`, `amenity=kindergarten`, `amenity=place_of_worship` features and their associated tags (`name`, `name:fr`, `operator`, `operator:type`, `religion`, `denomination`, `school:type`).
  - License: **Open Database License (ODbL) 1.0**, https://opendatacommons.org/licenses/odbl/1-0/
  - Attribution: "© OpenStreetMap contributors"
- **Giga / Project Connect** - school registry points (Giga school IDs, locations, names, ISO country, education level).
  - License: per Giga's data terms, https://giga.global/data
  - Attribution: "School locations courtesy of Giga (https://giga.global)"

### Administrative boundaries

- **geoBoundaries** - Benin ADM1 boundaries.
  - License: **CC BY 4.0**, https://www.geoboundaries.org
  - Attribution: "Boundaries © geoBoundaries (Runfola et al.)"

### Statistical priors

- **INFRE - Institut National pour la Formation et la Recherche en Éducation** - Benin annuaires statistiques 2021-22 (department-level public/private primary-school counts).
  - License: public Benin government data
  - Attribution: "INFRE annuaires statistiques 2021-22, Ministère des Enseignements Maternel et Primaire, République du Bénin"

### Spatial covariates

- **GHSL Settlement Model (SMOD), R2023A V2** - 1 km settlement classification.
  - License: **CC BY 4.0**, EC Copernicus / JRC
  - Attribution: "GHSL Settlement Model © European Commission, JRC"
- **Meta Relative Wealth Index** - DHS-validated wealth proxy (~2.4 km cells).
  - License: **CC BY 4.0**, Data for Good at Meta
  - Attribution: "Relative Wealth Index © Data for Good at Meta"

## Derived components

The following fields in `docs/webmap/data/schools.geojson` are produced by this pipeline and are licensed under **ODbL 1.0** as a derived OSM-substantial dataset:

- `ownership_label`, `ownership_confidence`, `source_signal`, `rule_ids`, `audit` (Stage A outputs)
- `stage_c_p_private`, `stage_c_p_private_adj`, `stage_c_band`, `stage_c_band_adj`, `model_agreement` (Stage C outputs)
- `ownership_final`, `ownership_final_adj` (final combined labels)
- `join_source`, `dept_prior_private` (intermediate fields)

The labels are not authoritative. They are model estimates with calibrated uncertainty and should be used together with the `stage_c_band` / `ownership_confidence` fields and the `unknown` category. See [`methodology.md`](methodology.md).

## Reuse

If you redistribute the data in `docs/webmap/data/` or any derivative of it:

1. Keep the ODbL 1.0 share-alike notice.
2. Reproduce the attribution block above.
3. Indicate that the dataset has been modified from its original OSM/Giga/etc. sources.

If you only use the code (not the data), Apache 2.0 applies. You do not need to reproduce the data attributions if you regenerate the dataset from scratch against your own data sources.
