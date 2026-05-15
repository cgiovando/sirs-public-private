# sirs-public-private

Per-school public-vs-private ownership classifier for the SIRS (School Infrastructure Risk Screening) workstream. Pilot country is Benin; the architecture is designed to extend to Niger, Mali, Guinea, and Ghana with per-country rule files.

## Why this exists

The Bank funds public infrastructure. Vulnerability rollups against the "public school stock" need to know which schools are actually public; misclassifying a private school as public inflates the public-stock denominator. Existing school-location datasets (Giga, OpenStreetMap, national EMIS exports) carry public/private signal inconsistently - some have explicit tags, most don't. This project derives a calibrated `ownership_label` per school with an explicit `unknown` band, optimised for high precision on the `private` flag.

## How it works

Four-stage pipeline:

1. **Stage A - deterministic labels.** Per-country YAML rules (regex on school names + OSM tag mining) produce a label with an audit trail (`source_signal`, `rule_id`, `confidence`). High precision, modest recall. See [`stage-a-rules/README.md`](stage-a-rules/README.md).
2. **Stage B - probabilistic features.** Distance to urban centers, population density (GHSL SMOD), Relative Wealth Index, religious-POI proximity, INFRE department-level priors. See [`stage-b-features/`](stage-b-features/).
3. **Stage C - calibrated classifier.** Logistic model trained on Stage A labels with ADM1-grouped cross-validation. Output is a probability with a three-band discretization (`public`, `private`, `unknown`). See [`stage-c-model/`](stage-c-model/).
4. **Stage D - manual evaluation.** Sampled review against authoritative ministry / EMIS data per country.

The full method, model choices, calibration logic, and pilot results are in **[`methodology.md`](methodology.md)**.

## Repository layout

```
sirs-public-private/
├── README.md
├── methodology.md              # method + Benin pilot results
├── requirements.txt
├── stage-a-rules/              # per-country YAML + Python applier
│   ├── benin.yaml
│   ├── label.py
│   └── tests/
├── stage-b-features/           # feature extraction
├── stage-c-model/              # training + inference
├── scripts/                    # one-shot utilities, sanity checks, figure generation
├── data/
│   ├── README.md               # data inventory + access notes
│   ├── inputs/                 # (gitignored) per-country joined Giga+OSM
│   └── derived/                # (gitignored) Stage A labels, Stage C predictions
└── docs/
    ├── figures/                # pipeline output figures
    └── webmap/                 # MapLibre dashboard, served via GitHub Pages
```

## Quick start

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Point at your data (see data/README.md for expected layout)
export SCHOOL_DATA_DIR=/path/to/wafr-schools-export

# Run the Benin pilot end-to-end
python -m stage_a_rules.ingest_giga --iso3 BEN --output data/inputs/benin_giga.geojson
python -m stage_a_rules.ingest_osm --iso3 BEN --output data/inputs/benin_osm.geojson
python -m stage_a_rules.join --iso3 BEN --output data/inputs/benin_joined.geojson
python -m stage_a_rules.label --rules stage-a-rules/benin.yaml \
  --input data/inputs/benin_joined.geojson \
  --output data/derived/stage_a_labels_BEN.geojson
```

Stage B and Stage C entry points are in `stage-b-features/build_matrix.py` and `stage-c-model/train.py` respectively.

## Dashboard

A MapLibre dashboard lives in [`docs/webmap/`](docs/webmap/) and is published via GitHub Pages. It lets you click any school to see its label, model probability, audit trail, and the rule(s) that fired. Three view modes: rules-only, rules+model, population-aware. The Benin dataset (~9,200 schools) is bundled directly into the page as GeoJSON.

## Data sources

Listed in [`data/README.md`](data/README.md) with license and access notes.

## Status

Stage A pilot for Benin is shipped. Stage B/C features and a calibrated model are running; the dashboard reflects the latest pilot outputs. Niger, Mali, Guinea, Ghana are next.

## AI-assisted development

> This project was developed with significant assistance from AI coding tools.

- **[Claude Code](https://claude.ai/claude-code)** (Anthropic) - code generation, architecture, debugging, and documentation
- All functionality has been tested and verified to work as intended
- Features and infrastructure choices have been reviewed and approved by the maintainer

This disclosure follows emerging best practices for transparency in AI-assisted software development.

## License

- **Code**: Apache License 2.0 — see [`LICENSE`](LICENSE).
- **Data** in `docs/webmap/data/` (and any data outputs of this pipeline that get redistributed): **ODbL 1.0**, inherited from the substantial OpenStreetMap input. Full attribution stack and reuse terms in [`DATA_LICENSE.md`](DATA_LICENSE.md).
