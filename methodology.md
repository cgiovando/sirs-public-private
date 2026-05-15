# Methodology

This document describes how `sirs-public-private` assigns a public/private ownership label to each school in the input dataset, with calibrated confidence. It is intended to be read alongside the dashboard and to give the SIRS team enough detail to leave informed feedback on rules, features, and modelling choices.

The pipeline runs in four stages: A (deterministic labels from text + tags), B (probabilistic spatial features), C (calibrated classifier), D (manual evaluation). The pilot covers Benin; the architecture is per-country.

---

## Design principles

- **High precision over high recall on the `private` flag.** A private school misclassified as public, then included in a public-stock vulnerability rollup, is the costlier error. Default to `unknown` rather than guessing.
- **`unknown` is a first-class label.** Every school carries a label, a calibrated probability, and a three-band discretization that exposes uncertainty downstream.
- **Auditability.** Every Stage A label records which rule(s) fired and on which field, so reviewers can trace any classification back to a specific regex or OSM tag.
- **Country-conditional rules.** Naming and ownership conventions differ across West Africa (e.g. Mali medersas are private, Niger medersas mix public+private, Ghana mission schools are publicly-assisted). Rules live in per-country YAML, not Python branches, so a domain expert can edit them without touching code.

---

## Inputs

| Source | License | Use |
|---|---|---|
| Giga school registry (WAFR export) | Internal WB/GFDRR; per-school data not redistributed | School locations and canonical names (`name_giga`) |
| OpenStreetMap `amenity=school`, `amenity=kindergarten` | ODbL 1.0 | School locations, names (`name_osm`), and operator/religion tags |
| OpenStreetMap `amenity=place_of_worship` | ODbL 1.0 | Distance-to-worship features |
| INFRE annuaires statistiques 2021-22 (Benin) | Public (gov.bj) | Per-department public/private primary-school counts; used as prior-shift target |
| GHSL Settlement Model (SMOD) R2023A | CC BY 4.0 | 1 km urban / peri-urban / rural classification |
| Meta Relative Wealth Index (RWI) | CC BY 4.0 | DHS-validated wealth proxy (~2.4 km cells) |

Giga and OSM are joined on a 100 m spatial buffer plus a fuzzy name match. The joined table carries both `name_giga` and `name_osm`; `join_source` records which input(s) contributed each row.

---

## Stage A - deterministic labels

### Rule schema

Each rule is a YAML entry with these fields:

```yaml
- id: name_complexe_scolaire
  countries: [BEN]
  applies_to_field: name           # name | name_osm | operator:type | religion | ...
  match_type: regex                # exact | regex | contains
  pattern: '\bComplexe\s+scolaire'
  case_insensitive: true
  label: private-secular           # public | private-secular | private-religious | community | public-mission | government-assisted | unknown
  confidence: high                 # high | medium | low
  notes: >
    Common Benin private-secular marker. Often appears as a Giga record with a
    public-prefix name (EPP X) but tagged "Complexe scolaire" in OSM - see
    join_conflict handling in label.py.
  examples_positive: ["Complexe scolaire Les Lauriers"]
  examples_negative: ["EPP Cocotomey"]
```

Valid labels: `public`, `private-secular`, `private-religious`, `community`, `public-mission`, `government-assisted`, `unknown`. The downstream binary target collapses everything non-public into `private` for Stage C; the multi-class label is preserved on the row for audit.

### Conflict resolution

Rules are evaluated in priority order: all high-tier rules first, then medium, then low.

- **All firing rules in a tier agree on the label** → that label is assigned with the tier's confidence; `rule_ids` lists every rule that fired.
- **Rules in the same tier disagree** → label is `unknown`, `audit` records the disagreement, `rule_ids` lists the conflicting rules.
- **Join conflict** (Giga public-prefix name like `EPP X` joined to an OSM record tagged `Complexe scolaire`) → resolved as `unknown` with a dedicated `join_conflict` audit code. These rows are the highest-value manual review targets.

Output columns: `school_id`, `name`, `iso3`, `adm1`, `adm2`, `level`, `ownership_label`, `ownership_confidence` (high / medium / low / none), `source_signal`, `rule_ids`, `audit`, `geometry`, plus ancillary join metadata.

### Benin rule set (`stage-a-rules/benin.yaml`)

33 rules. Coverage:

| Category | # rules | Example IDs |
|---|---|---|
| OSM operator/religion tags | 6 | `osm_op_type_public`, `osm_op_type_religious`, `osm_religion_set` |
| Public name patterns | 4 | `name_epp` (matches 4,676 of 7,697 Giga names), `name_ceg_cem`, `name_ecole_primaire_publique`, `name_lycee_public` |
| Private-secular name patterns | 7 | `name_complexe_scolaire`, `name_groupe_scolaire`, `name_ecole_privee`, `name_institut`, `name_cours_prive`, `name_maternelle` |
| Private-religious name patterns | 7 | `name_saint` (case-sensitive, beaten by CEG at high tier), `name_ecole_catholique`, `name_medersa` (Benin: private; do NOT reuse for Niger), `name_franco_arabe`, `name_islamique`, `name_evangelical` |

Every rule must declare at least one positive and one negative example string; the test suite (`stage-a-rules/tests/test_rules.py`) loads each YAML and asserts the regex fires on positives and not on negatives.

---

## Stage B - probabilistic features

Six feature extractors, one per file in `stage-b-features/`. All emit a parquet keyed on `school_id`; `build_matrix.py` joins them into the model matrix.

| Module | Features | Units |
|---|---|---|
| `distances.py` | `dist_to_cotonou_km`, `dist_to_porto_novo_km`, `dist_to_parakou_km`, `dist_to_nearest_major_city_km`, `nearest_major_city` | km / categorical |
| `density.py` | `schools_within_1km`, `schools_within_5km`, `dist_to_nearest_school_m` | count / m |
| `ghsl_smod.py` | `smod_code` (10-30), `smod_class` ∈ {rural, peri_urban, urban, other} | categorical |
| `rwi.py` | `rwi` (z-scored, ~[-2, +2]), `rwi_error`, `rwi_cell_dist_m` | numeric |
| `religious_poi.py` | `dist_to_mosque_m`, `dist_to_church_m`, `dist_to_any_worship_m`, `worship_within_500m` | m / count |
| `infre_priors.py` | `dept_prior_private` (per ADM1), `national_prior_private` | share ∈ [0, 1] |

### INFRE recalibration

`infre_priors.py` parses INFRE 2021-22 Excel annuaires (`01DATA_GL` sheet) and computes a per-department private-school share for primary education. The 12 Benin departments each get a `dept_prior_private`; a national fallback (0.17 from the 2022-23 figure) is used when ADM1 is unknown.

These priors enter Stage C via the Saerens-Latinne-Decaestecker prior-shift formula, applied per row:

```
p_new = (p_old * π_new / π_old) /
        [p_old * π_new / π_old + (1 - p_old) * (1 - π_new) / (1 - π_old)]
```

where `p_old` is the model's calibrated probability, `π_old` is the training private rate, and `π_new` is the school's ADM1 prior. This produces a parallel set of probabilities (`stage_c_p_private_adj`) and bands (`stage_c_band_adj`) tuned to match department-level INFRE totals; the unadjusted Stage C output is preserved alongside it so reviewers can see what the model says before and after recalibration.

---

## Stage C - calibrated classifier

### Model

```python
LogisticRegression(class_weight='balanced', max_iter=1000,
                   solver='liblinear', random_state=0)
```

wrapped in:

```python
CalibratedClassifierCV(method='isotonic', cv=5)
```

Preprocessing is a `ColumnTransformer`: `StandardScaler` on numeric features, `OneHotEncoder` on `smod_class` and `nearest_major_city`. We chose logistic regression with isotonic calibration over tree ensembles because:

1. The training set is small (a few thousand rows per country) and skewed toward public; logistic regression generalizes more conservatively.
2. Linear coefficients are inspectable and the team can argue with them directly.
3. Isotonic calibration produces probabilities that pass the reliability-diagram check and are usable in the prior-shift formula without further transformation.

### Features used (12 total)

Numeric (10): `dist_to_cotonou_km`, `dist_to_nearest_major_city_km`, `schools_within_1km`, `schools_within_5km`, `dist_to_nearest_school_m`, `dist_to_mosque_m`, `dist_to_church_m`, `dist_to_any_worship_m`, `worship_within_500m`, `rwi`.

Categorical one-hot (2): `smod_class`, `nearest_major_city`.

`dept_prior_private` is **not** included as a feature; it enters only via the prior-shift step. Including it as a feature would let the model trivially overfit to the training-region departments.

### Training set

Only Stage A `high`-confidence rows are used for training. Stage A `medium`-confidence rows are held out as a semi-validation set; the `model_agreement` column flags rows where Stage C disagrees with Stage A by ≥0.30 probability gap, surfacing candidates for manual review.

Binary target: `0 = public`, `1 = private` (private-secular ∪ private-religious ∪ community).

### Cross-validation

Two complementary CV schemes, both 5-fold:

| Scheme | What it estimates |
|---|---|
| **StratifiedKFold (shuffled, random_state=0)** | Standard ML generalization on i.i.d. data - upper bound, useful for sanity-checking. |
| **GroupKFold by ADM1 (12 Benin departments → 5 folds)** | Honest spatial generalization. Schools in the same department often share name patterns and infrastructure; shuffled CV leaks this signal. Report the grouped score as the headline number. |

### Probability bands

`stage_c_p_private` ∈ [0, 1] → three-way `stage_c_band`:

| p_private | band |
|---|---|
| < 0.30 | `likely-public` |
| 0.30 - 0.70 | `uncertain` |
| > 0.70 | `likely-private` |

The same thresholds apply to `stage_c_p_private_adj` → `stage_c_band_adj`.

### Final labels

- `ownership_final`: trusts Stage A's high/medium labels; uses `stage_c_band` for Stage A unknowns. Conservative; matches what an auditable rule-based system would say.
- `ownership_final_adj`: same, but uses `stage_c_band_adj` (prior-shifted) for unknowns. Recommended for population-level rollups where the goal is to match department INFRE totals.

Both are emitted so downstream consumers can choose.

---

## Benin pilot results (2026-04-30)

### Stage A

9,269 schools after Giga ∪ OSM with conflict-aware join.

| Label | Count | Share |
|---|---:|---:|
| public | 6,180 | 66.7% |
| unknown | 2,731 | 29.5% |
| private-secular | 315 | 3.4% |
| private-religious | 42 | 0.5% |
| community | 1 | <0.1% |

Among labelled (high-confidence) rows: **94.4% public / 5.6% private**, vs. the INFRE 2021-22 national reference of **83% public / 17% private**. The gap is overwhelmingly a *data coverage* problem, not a *modelling* problem: the underlying Giga export carries virtually no private signal in school names (~22 of 7,697 names match any private prefix). OSM is where private schools become visible (`Complexe scolaire`, `Saint *`, `Catholique` and `Médersa` names), and OSM coverage is partial. Stage B/C plus prior-shift partially close the gap by reassigning some `unknown` rows to private bands in proportion to department-level INFRE shares; this is what `ownership_final_adj` is for.

### Stage C

Trained on 6,429 high-confidence Stage A rows (6,180 public + 249 private).

| CV scheme | ROC-AUC | Brier |
|---|---:|---:|
| Shuffled stratified 5-fold | 0.916 | 0.034 |
| **ADM1-grouped 5-fold** | **0.887** | **0.041** |

Report the grouped number as the headline. The ~0.03 AUC gap is the spatial-leakage component; without it, we'd be overstating geographic transfer.

---

## Known limitations

- **Coverage, not skill, is the binding constraint for now.** The model is well-calibrated on the rows it sees; we just don't see enough private schools because Giga is public-prefix-dominant and OSM coverage of private schools is uneven.
- **Rule set is Benin-only.** Reusing `name_medersa: private-religious` for Niger or Mali without country review would be wrong (Niger medersas mix public+private; Mali medersas are private but with a different naming distribution).
- **No labelled holdout from an authoritative source yet.** All CV is internal to Stage A labels, so it estimates Stage C's ability to reproduce Stage A, not its ability to predict ground truth. Stage D (manual evaluation against ministry EMIS data, ideally for a French-speaking African country with known public/private classification) is the missing leg.
- **`unknown` is a confession, not a feature.** Roughly 30% of Benin schools end up `unknown` after Stage A. Stage C + prior-shift reassigns most of these probabilistically, but a 30% unknown rate is high and points back at the coverage problem.

---

## Provenance and reproducibility

Every artifact written by the pipeline (`data/derived/*.geojson`, `data/inputs/*.parquet`, etc.) is accompanied by a `*.provenance.json` sidecar pinning: input file paths and SHA256 hashes, code git commit, runtime, and rule-set version. The rule set itself is versioned by file (`benin.yaml`) and dated in commit history.

---

## Feedback

The team's explicit ask was to make this readable enough that reviewers can comment on individual variables and rules. The rule set is in [`stage-a-rules/benin.yaml`](stage-a-rules/benin.yaml) - it's the most useful place to leave inline review comments. Feature definitions are in [`stage-b-features/`](stage-b-features/). The model is one short file: [`stage-c-model/train.py`](stage-c-model/train.py).
