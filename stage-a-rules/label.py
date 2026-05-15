"""Apply a per-country YAML rules file to a joined Giga+OSM GeoJSON and emit the
canonical Stage A artifact.

Usage:
  python label.py --rules stage-a-rules/benin.yaml \
                  --input data/inputs/benin_joined.geojson \
                  --output data/derived/stage_a_labels_BEN_$(date +%Y-%m-%d).geojson

Output schema (per AGENTS.md):
  school_id, name, iso3, adm2, level,
  ownership_label, ownership_confidence,
  source_signal, rule_ids, audit, geometry

Adjacent file:
  <output>.provenance.json   - input file path + sha256, code commit, params, runtime.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml

VALID_LABELS = {
    "public",
    "private-secular",
    "private-religious",
    "community",
    "public-mission",
    "government-assisted",
    "unknown",
}
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


class Rule:
    __slots__ = (
        "id",
        "countries",
        "applies_to_field",
        "match_type",
        "pattern",
        "case_insensitive",
        "label",
        "confidence",
        "notes",
        "examples_positive",
        "examples_negative",
        "_compiled",
    )

    def __init__(self, raw: dict[str, Any], default_countries: list[str]):
        self.id: str = raw["id"]
        self.countries: list[str] = raw.get("countries") or default_countries
        self.applies_to_field: str = raw["applies_to_field"]
        self.match_type: str = raw["match_type"]
        self.pattern: str = raw["pattern"]
        self.case_insensitive: bool = bool(raw.get("case_insensitive", True))
        self.label: str = raw["label"]
        if self.label not in VALID_LABELS:
            raise ValueError(f"rule {self.id}: invalid label {self.label}")
        self.confidence: str = raw["confidence"]
        if self.confidence not in CONFIDENCE_RANK:
            raise ValueError(f"rule {self.id}: invalid confidence {self.confidence}")
        self.notes: str = raw.get("notes", "")
        self.examples_positive: list[str] = list(raw.get("examples_positive") or [])
        self.examples_negative: list[str] = list(raw.get("examples_negative") or [])

        if self.match_type == "regex":
            flags = re.IGNORECASE if self.case_insensitive else 0
            self._compiled = re.compile(self.pattern, flags)
        else:
            self._compiled = None

    def applies_to_iso3(self, iso3: str) -> bool:
        return iso3 in self.countries

    def matches(self, value) -> bool:
        if not isinstance(value, str) or not value:
            return False
        if self.match_type == "regex":
            return self._compiled.search(value) is not None
        if self.match_type == "exact":
            target = self.pattern
            if self.case_insensitive:
                return value.strip().lower() == target.lower()
            return value.strip() == target
        if self.match_type == "tag_value":
            target = self.pattern
            if self.case_insensitive:
                return target.lower() in value.lower().split(";")
            return target in value.split(";")
        raise ValueError(f"rule {self.id}: unknown match_type {self.match_type}")


def load_rules(path: Path) -> list[Rule]:
    raw = yaml.safe_load(path.read_text())
    default_countries = raw.get("countries", [])
    rules = [Rule(r, default_countries) for r in raw["rules"]]
    seen = set()
    for r in rules:
        if r.id in seen:
            raise ValueError(f"duplicate rule id: {r.id}")
        seen.add(r.id)
    return rules


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def field_value(feature: dict[str, Any], applies_to_field: str) -> str | None:
    """`name_any` checks all known name fields. Other fields look up directly."""
    if applies_to_field == "name_any":
        for f in ("name_giga", "name_osm", "name_fr", "int_name"):
            v = feature.get(f)
            if isinstance(v, str) and v.strip():
                # Return first non-empty; the matcher will be called per field
                # via the loop in `apply_rules`.
                pass
        # Caller iterates over fields itself (see apply_rules).
        return None
    return feature.get(applies_to_field)


NAME_FIELDS = ("name_giga", "name_osm", "name_fr", "int_name")


def rule_fires(rule: Rule, feature: dict[str, Any]) -> bool:
    if rule.applies_to_field == "name_any":
        for f in NAME_FIELDS:
            if rule.matches(feature.get(f)):
                return True
        return False
    return rule.matches(feature.get(rule.applies_to_field))


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------


def resolve(firings: list[Rule]) -> tuple[str, str, list[str], str]:
    """Given the list of rules that fired, decide label, confidence, rule_ids, audit."""
    if not firings:
        return "unknown", "none", [], "no rule fired"

    by_conf: dict[str, list[Rule]] = defaultdict(list)
    for r in firings:
        by_conf[r.confidence].append(r)

    for tier in ("high", "medium", "low"):
        if tier not in by_conf:
            continue
        labels = {r.label for r in by_conf[tier]}
        if len(labels) == 1:
            label = labels.pop()
            ids = [r.id for r in by_conf[tier]]
            audit = f"{tier} rules agreed on {label}: {', '.join(ids)}"
            # also include lower-tier firings in the rule_ids list for traceability
            all_ids = [r.id for r in firings]
            return label, tier, all_ids, audit
        # Disagreement at this tier -> unknown, surface in audit
        ids = [f"{r.id}->{r.label}" for r in by_conf[tier]]
        audit = f"{tier} rules disagreed: {'; '.join(ids)}"
        all_ids = [r.id for r in firings]
        return "unknown", tier, all_ids, audit

    return "unknown", "none", [r.id for r in firings], "no decisive tier"


# ---------------------------------------------------------------------------
# Join-conflict detection
# ---------------------------------------------------------------------------


def join_conflict(feature: dict[str, Any]) -> bool:
    """Return True if Giga and OSM disagree on the school-type prefix.

    Concretely: Giga name has a public prefix (EPP/CEG/EEP/EP) AND OSM name has a
    private secular prefix (Complexe / Groupe scolaire / Ecole privee /
    Maternelle). These cases are real-world false-positive joins where the
    100m buffer caught the public school's neighbour. Stage A reports them as
    `unknown` with a join_conflict audit.
    """
    if feature.get("source") != "giga_osm":
        return False
    g_raw = feature.get("name_giga")
    o_raw = feature.get("name_osm")
    g = g_raw.upper() if isinstance(g_raw, str) else ""
    o = o_raw.upper() if isinstance(o_raw, str) else ""
    g_pub = bool(re.search(r"^\s*(EPP|EEP|CEG|CEM|EP|E\.?P\.?P\.?)\b", g))
    o_priv = bool(
        re.search(
            r"\b(COMPLEXE\s+SCOLAIRE|GROUPE\s+SCOLAIRE|MATERNELLE|ÉCOLE\s+PRIV|ECOLE\s+PRIV)\b",
            o,
        )
    )
    return g_pub and o_priv


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def compose_audit(rule_audit: str, feature: dict[str, Any]) -> str:
    src = feature.get("source") or "unknown"
    return f"[{src}] {rule_audit}"


def apply_rules(rules: list[Rule], gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out_rows: list[dict[str, Any]] = []

    for _, row in gdf.iterrows():
        feature = row.to_dict()
        iso3 = feature.get("iso3")

        # Detect join conflicts before running rules; emit unknown directly.
        if join_conflict(feature):
            label, conf = "unknown", "none"
            rule_ids: list[str] = []
            audit = compose_audit(
                f"join_conflict: giga='{feature.get('name_giga')}' vs osm='{feature.get('name_osm')}'",
                feature,
            )
            source_signal = "join_conflict"
        else:
            firings = [r for r in rules if r.applies_to_iso3(iso3) and rule_fires(r, feature)]
            label, conf, rule_ids, rule_audit = resolve(firings)
            audit = compose_audit(rule_audit, feature)
            source_signal = ",".join(rule_ids) if rule_ids else "no_rule"

        name = next(
            (
                feature[f]
                for f in ("name_giga", "name_osm", "name_fr", "int_name")
                if isinstance(feature.get(f), str) and feature[f].strip()
            ),
            None,
        )

        out_rows.append(
            {
                "school_id": feature["school_id"],
                "name": name,
                "iso3": iso3,
                "adm2": None,  # populated by a follow-up join later
                "level": feature.get("level"),
                "ownership_label": label,
                "ownership_confidence": conf,
                "source_signal": source_signal,
                "rule_ids": ";".join(rule_ids),
                "audit": audit,
                "name_giga": feature.get("name_giga"),
                "name_osm": feature.get("name_osm"),
                "operator_type": feature.get("operator_type"),
                "religion": feature.get("religion"),
                "join_source": feature.get("source"),
                "match_dist_m": feature.get("match_dist_m"),
                "match_name_score": feature.get("match_name_score"),
                "geometry": feature["geometry"],
            }
        )

    out = gpd.GeoDataFrame(out_rows, geometry="geometry", crs=gdf.crs)
    return out


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


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


def write_provenance(out_path: Path, rules_path: Path, input_path: Path, params: dict[str, Any]) -> Path:
    prov_path = out_path.with_suffix(out_path.suffix + ".provenance.json")
    prov = {
        "output": str(out_path),
        "input": {"path": str(input_path), "sha256": sha256_file(input_path)},
        "rules": {"path": str(rules_path), "sha256": sha256_file(rules_path)},
        "params": params,
        "git_commit": git_commit(),
        "runtime_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    prov_path.write_text(json.dumps(prov, indent=2))
    return prov_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Stage A rules to joined GeoJSON.")
    p.add_argument("--rules", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    rules_path = Path(args.rules)
    input_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rules = load_rules(rules_path)
    gdf = gpd.read_file(input_path)
    out = apply_rules(rules, gdf)
    out.to_file(out_path, driver="GeoJSON")

    prov_path = write_provenance(out_path, rules_path, input_path, params={"rules_count": len(rules)})

    print(f"wrote {len(out)} features -> {out_path}")
    print(f"provenance -> {prov_path}")
    print()
    print("=== ownership_label ===")
    print(out["ownership_label"].value_counts().to_string())
    print()
    print("=== ownership_confidence ===")
    print(out["ownership_confidence"].value_counts().to_string())
    print()
    print("=== by source x label ===")
    print(out.groupby("join_source")["ownership_label"].value_counts().to_string())


if __name__ == "__main__":
    main()
