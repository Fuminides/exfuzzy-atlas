"""Display names of the named compound terms (contract v0.8), kept in an Atlas config and not in the model.

A compound term ("x IS Long night") is a name the fit gave to a union of terms; the library calls it by an internal
name. ``configs/compound_terms.json`` maps that internal name to the Spanish and English names the interface shows
(``Antecedent.label`` / ``label_en``). They are display only: a name can change without refitting, and a published
model takes the new one with ``python -m atlas.services.enrich --labels-only``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from atlas.contracts import models as m
from atlas.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs" / "compound_terms.json"


class CompoundLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    label_en: str


class CompoundTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    compound_terms: dict[str, CompoundLabel]


def load_labels(path: Path | None = None) -> dict[str, CompoundLabel]:
    """The display names by the compound's internal name (the config; an absent file means no labels)."""
    path = Path(path) if path is not None else CONFIG
    if not path.is_file():
        return {}
    return CompoundTerms.model_validate(json.loads(path.read_text())).compound_terms


def label_antecedent(antecedent: m.Antecedent, labels: dict[str, CompoundLabel]) -> m.Antecedent:
    """``antecedent`` with the labels of its compound; any other condition is returned as it is."""
    entry = labels.get(antecedent.term) if antecedent.operator == "any_of" else None
    if entry is None:
        return antecedent
    return antecedent.model_copy(update={"label": entry.label, "label_en": entry.label_en})


def apply_labels(rules: m.ModelRules, labels: dict[str, CompoundLabel] | None = None) -> m.ModelRules:
    """``rules`` with the names of every compound condition set from the config (``labels``; default: the file)."""
    labels = load_labels() if labels is None else labels
    changed = [
        r.model_copy(update={"antecedents": [label_antecedent(a, labels) for a in r.antecedents]})
        for r in rules.rules
    ]
    return rules.model_copy(update={"rules": changed})
