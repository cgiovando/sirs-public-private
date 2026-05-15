# Stage A - deterministic labels

Per-country YAML rule files plus a single Python applier. The whole point of Stage A is that the labelling logic is **human-editable**, **auditable** (every label carries the rule ID that produced it), and **testable** (every rule needs at least one positive and one negative example).

## Why YAML

A teammate who isn't a programmer should be able to edit the regex and see the impact. Putting country-conditional logic in `.py` files behind `if iso == "BEN":` branches makes it invisible to the people who know West African school naming best.

## File layout

```
stage-a-rules/
├── README.md              (this file)
├── label.py               (single applier, takes --rules and --input, emits canonical Stage A geojson)
├── benin.yaml             (Benin rules - the pilot)
├── niger.yaml             (added later)
├── mali.yaml
├── guinea.yaml
├── ghana.yaml
├── tests/
│   ├── conftest.py
│   └── test_rules.py      (loads each YAML, asserts every rule's positive/negative examples)
└── shared/
    └── francophone-base.yaml   (rules that apply across all 4 francophone countries; included from per-country files)
```

## Rule schema

Every rule must have:

```yaml
- id: unique-snake-case
  countries: [BEN]                           # or [BEN, NER, MLI, GIN] for shared rules
  applies_to_field: name                     # name | name_fr | operator | operator:type | religion | denomination
  match_type: regex                          # regex | exact | tag_value
  pattern: '^EPP\b'                          # the actual rule
  case_insensitive: true
  label: public                              # public | private-secular | private-religious | community | public-mission | government-assisted | unknown
  confidence: high                           # high | medium | low
  notes: |
    EPP = École Primaire Publique. Pan-francophone West Africa.
  examples_positive:
    - "EPP Cotonou Centre"
    - "EPP Adjarra"
  examples_negative:
    - "École privée St Michel"
    - "Lycée Jean-Pierre Tohouet"
```

## Applier behaviour

`label.py` does this on each input feature:

1. Run every rule whose `countries` matches the feature's `iso3` (or has no country restriction).
2. Collect all rules that fire. Each contributes a (label, confidence) vote.
3. Resolve:
   - If all firing high-confidence rules agree on a label -> emit that label, `ownership_confidence=high`.
   - If high-confidence rules disagree -> emit `unknown`, audit lists both.
   - If only medium/low rules fire and they agree -> emit that label, confidence = `medium` or `low` accordingly.
   - If no rules fire -> emit `unknown`, `ownership_confidence=none`. This is the input set for Stage B later.
4. Emit canonical Stage A schema (per `AGENTS.md`) including a one-line audit string and the list of rule IDs that contributed.

## Test requirements

Every rule must have at least one positive and one negative example. Pytest:

- Loads every YAML.
- For each rule, asserts pattern matches every positive example.
- For each rule, asserts pattern does NOT match any negative example.
- For each rule, asserts pattern does not match positive examples of *contradictory* rules.

CI gates Stage A: a rule without tests, or whose tests fail, blocks the build.

## Adding a new country

1. Copy the closest existing country YAML (`benin.yaml` for francophone, `ghana.yaml` for Anglophone once it exists).
2. Read `docs/parent-brief.md` for the country-specific gotchas.
3. Pull a sample of 100 random schools from that country's Giga export, classify them by hand, then back-solve the rule changes needed.
4. Run `pytest stage-a-rules/tests/`. Iterate until green.
5. Run `python label.py --rules stage-a-rules/<country>.yaml --input <sample>` and spot-check the output against your hand classification.

## What this stage does NOT do

- It does not match against EMIS / authoritative registers. That's a separate ingest path that happens *before* Stage A; the EMIS-matched records bypass Stage A and go to the canonical artifact with `source_signal=emis_match` and `confidence=high`.
- It does not look at imagery, footprints, or auxiliary spatial data. That is Stage B.
- It does not produce a binary public/private flag. The 7-class taxonomy + uncertainty is the canonical output. Downstream consumers can collapse for their own use.
