"""Pytest suite for stage-a-rules YAML files.

Every rule in every per-country YAML must:
  - have at least one positive and one negative example
  - match all positive examples
  - reject all negative examples

In addition, a positive example for a public-confidence-high rule must not be
matched by any private-confidence-high rule from the same country (and v.v.),
to catch authoring errors where two rules silently agree on the wrong thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))

from importlib import import_module  # noqa: E402

label_mod = import_module("stage-a-rules.label".replace("-", "_")) if False else None  # placeholder to avoid linter

# We import label.py directly via path because the directory name has a hyphen.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("label", ROOT / "label.py")
label = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(label)  # type: ignore[union-attr]

YAML_PATHS = sorted(ROOT.glob("*.yaml"))


def _all_rules():
    out = []
    for p in YAML_PATHS:
        rules = label.load_rules(p)
        for r in rules:
            out.append((p.name, r))
    return out


@pytest.fixture(scope="session")
def yaml_paths():
    assert YAML_PATHS, f"no rule YAMLs found under {ROOT}"
    return YAML_PATHS


@pytest.mark.parametrize("path,rule", _all_rules(), ids=[f"{p}::{r.id}" for p, r in _all_rules()])
def test_rule_has_examples(path, rule):
    assert rule.examples_positive, f"{path}::{rule.id} has no positive examples"
    assert rule.examples_negative, f"{path}::{rule.id} has no negative examples"


@pytest.mark.parametrize("path,rule", _all_rules(), ids=[f"{p}::{r.id}" for p, r in _all_rules()])
def test_rule_positive_examples_match(path, rule):
    for ex in rule.examples_positive:
        assert rule.matches(ex), f"{path}::{rule.id} should match positive example {ex!r}"


@pytest.mark.parametrize("path,rule", _all_rules(), ids=[f"{p}::{r.id}" for p, r in _all_rules()])
def test_rule_negative_examples_reject(path, rule):
    for ex in rule.examples_negative:
        assert not rule.matches(ex), f"{path}::{rule.id} should NOT match negative example {ex!r}"


def _high_confidence_pairs():
    """Yield (rule_a, rule_b) where both are high-confidence and produce contradictory labels."""
    by_country: dict[str, list] = {}
    for path, rule in _all_rules():
        if rule.confidence != "high":
            continue
        for c in rule.countries:
            by_country.setdefault(c, []).append((path, rule))
    pairs = []
    for country, items in by_country.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if _contradicts(a[1].label, b[1].label):
                    pairs.append((country, a, b))
    return pairs


def _contradicts(label_a: str, label_b: str) -> bool:
    """Public vs anything-private (or community) is contradictory at high confidence."""
    publicy = {"public", "public-mission", "government-assisted"}
    privatey = {"private-secular", "private-religious", "community"}
    return (label_a in publicy and label_b in privatey) or (label_a in privatey and label_b in publicy)


@pytest.mark.parametrize(
    "country,pair_a,pair_b", _high_confidence_pairs(),
    ids=[f"{c}::{a[1].id}__vs__{b[1].id}" for c, a, b in _high_confidence_pairs()] or ["no-pairs"],
)
def test_high_conf_rules_dont_collide(country, pair_a, pair_b):
    """A high-confidence positive example from rule A must not also fire rule B
    when A and B carry contradictory labels."""
    _, a = pair_a
    _, b = pair_b
    for ex in a.examples_positive:
        assert not b.matches(ex), (
            f"high-conf collision in {country}: '{ex}' is positive for {a.id} ({a.label}) "
            f"but also matches {b.id} ({b.label})"
        )
    for ex in b.examples_positive:
        assert not a.matches(ex), (
            f"high-conf collision in {country}: '{ex}' is positive for {b.id} ({b.label}) "
            f"but also matches {a.id} ({a.label})"
        )
