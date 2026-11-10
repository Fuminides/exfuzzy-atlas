"""Layout of ``artifacts/published/`` and the small JSON documents that describe it.

::

    artifacts/published/
      registry.json                    task_id -> served model_id (+ domain, title, target, unit, horizon)
      <model_id>/
        model.pkl run_manifest.json metrics.json rules.json      copied from the run, checksum-verified
        entities.geojson                an EntityCollection, restricted to the published entities
        inputs.parquet                  entity_id, issued_at_utc, feature columns
        activations/year=YYYY/month=MM/part-NNNNNN.parquet       tidy firing table (one record per rule)
        predictions.parquet             entity_id, issued_at_utc, valid_at_utc, prediction, observed, missing_reason
        importance.json summary.json    v0.5, precomputed: RuleImportanceResponse, SummaryResponse
        feature_spec.json card.json publish.json
        SHA256SUMS                      every file above, relative paths (publish.json included)

A model directory is written under a hidden temp name and renamed into place, so readers never see a
half-written model. ``SHA256SUMS`` is checked before ``model.pkl`` is unpickled.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from atlas.contracts import models as m
from atlas.ml.artifacts import CHECKSUM_FILE, sha256_file

REGISTRY_FILE = "registry.json"
MODEL_FILE = "model.pkl"
RUN_FILES = (MODEL_FILE, "run_manifest.json", "metrics.json", "rules.json")
ENTITIES_FILE = "entities.geojson"
INPUTS_FILE = "inputs.parquet"
PREDICTIONS_FILE = "predictions.parquet"
FEATURE_SPEC_FILE = "feature_spec.json"
CARD_FILE = "card.json"
PUBLISH_INFO_FILE = "publish.json"
ACTIVATIONS_DIR = "activations"
IMPORTANCE_FILE = "importance.json"
SUMMARY_FILE = "summary.json"
DOMAIN_TITLES = {m.Domain.AIR: "Air quality", m.Domain.WATER: "Water quality", m.Domain.MOBILITY: "Urban mobility"}
# The task a domain with several opens on: /domains lists it first (the web shows the first task). The others follow
# by task_id. Air keeps Madrid, its first task, as the default next to Germany (author's choice, 2026-11-02).
DEFAULT_TASKS = {m.Domain.AIR: "madrid_no2_h6"}


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureSource(_Doc):
    """Where a model input comes from. ``lag_hours`` is how far before the issue time it was observed."""

    unit: str | None = None
    source_id: str
    lag_hours: float = Field(ge=0, description="observed_at = issued_at - lag_hours; never after issued_at.")


class FeatureSpec(_Doc):
    schema_version: str = m.SCHEMA_VERSION
    features: dict[str, FeatureSource]


class ClassMetadata(_Doc):
    """Extra documentation of one scheme class, applied at publish time (contract v0.4)."""

    merged_from: list[str] = []
    description: str | None = Field(None, description="Replaces the class description when given.")
    display_label: str | None = Field(None, description="v0.5.1: sets TargetClass.display_label.")
    display_label_en: str | None = Field(None, description="v0.6: sets TargetClass.display_label_en.")
    description_en: str | None = Field(None, description="v0.6: sets TargetClass.description_en.")


class SchemeMetadata(_Doc):
    kind: m.SchemeKind
    short_name: str
    name_en: str | None = Field(None, description="v0.6: sets TargetScheme.name_en.")
    short_name_en: str | None = Field(None, description="v0.6: sets TargetScheme.short_name_en.")
    classes: dict[str, ClassMetadata] = Field({}, description="By class label; labels must exist in the scheme.")


class FeatureMetadata(_Doc):
    """Display name and explanation of one model input, applied at publish time (contract v0.5)."""

    label: str
    description: str | None = None
    lag_hours: float | None = Field(
        None, description="The age at the issue time that the label states ('hace 2 h'); publish refuses the label "
        "when the feature_spec says otherwise, so a label cannot drift from the timing it describes.",
    )
    terms: dict[str, str] = Field({}, description="v0.5.1: display label by term name; sets LinguisticTerm.label.")
    label_en: str | None = Field(
        None, description="v0.6: sets LinguisticVariable.label_en. An age it states ('4 h ago') must be the "
        "feature_spec's lag_hours and the one the Spanish label states ('hace 4 h'); publish refuses it otherwise.",
    )
    description_en: str | None = Field(None, description="v0.6: sets LinguisticVariable.description_en.")
    terms_en: dict[str, str] = Field(
        {}, description="v0.6: English display label by term name (any term, labelled or not); sets "
        "LinguisticTerm.label_en.",
    )


class SummaryMetadata(_Doc):
    """What the data summary (``summary.json``, contract v0.5) describes and how, per task."""

    label: str = Field(description="Display name of the observed variable, e.g. 'NO₂ horario observado'.")
    label_en: str | None = Field(None, description="v0.6: sets SummaryResponse.label_en, e.g. 'Observed hourly NO₂'.")
    column: str | None = Field(
        None, description="Observed column of the feature table; default: the run's target column.")
    time_column: Literal["valid_at_utc", "issued_at_utc"] = Field(
        "valid_at_utc", description="Time of the observed value: the table's valid_at_utc, or issued_at_utc when the "
        "value is keyed by the start of the hour it covers (NYC pickups of [T, T+1)).",
    )
    notes: list[str] = Field([], description="Sentences added to the summary notes (why this variable).")


class PublishMetadata(_Doc):
    """Per-task v0.4 metadata (``configs/<domain>/attribution.json``): credits, and scheme kind and merged classes.

    The scheme block patches the *published copy* of ``rules.json`` (see ``publish.apply_scheme_metadata``), so a
    model can get it without retraining.
    """

    attribution: list[m.Attribution] = []
    target_scheme: SchemeMetadata | None = None
    features: dict[str, FeatureMetadata] = Field(
        {}, description="v0.5: by input name; sets LinguisticVariable.label/description in the published rules."
    )
    summary: SummaryMetadata | None = Field(None, description="v0.5: the observed variable of summary.json.")


class RegistryEntry(_Doc):
    model_id: str
    domain: m.Domain
    title: str = Field(description="Display title of the domain this task belongs to.")
    task_type: Literal["regression", "classification"] = "regression"
    target: str
    unit: str
    horizon_hours: int = Field(ge=0)
    data_version: str
    synthetic: bool = False
    territory: str | None = Field(
        None, description="v0.5: tasks that differ only in horizon share a territory (publish --territory)."
    )
    territory_title: str | None = None
    territory_title_en: str | None = Field(
        None, description="v0.6: English display name of the territory (publish/enrich --territory-title-en)."
    )


class Registry(_Doc):
    schema_version: str = m.SCHEMA_VERSION
    tasks: dict[str, RegistryEntry] = {}


def read_registry(published_dir: Path) -> Registry:
    path = Path(published_dir) / REGISTRY_FILE
    if not path.exists():
        return Registry()
    return Registry.model_validate_json(path.read_text())


def write_registry(published_dir: Path, registry: Registry) -> None:
    """Atomic replace, so a reader sees the old or the new registry, never a partial file."""
    published_dir = Path(published_dir)
    fd, tmp = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=published_dir)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(registry.model_dump(mode="json"), indent=2) + "\n")
        os.replace(tmp, published_dir / REGISTRY_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_checksums(model_dir: Path) -> None:
    """``SHA256SUMS`` over every file under ``model_dir`` (relative POSIX paths), in the format of ``ml.artifacts``."""
    names = sorted(p.relative_to(model_dir).as_posix() for p in Path(model_dir).rglob("*") if p.is_file())
    names = [n for n in names if n != CHECKSUM_FILE]
    (Path(model_dir) / CHECKSUM_FILE).write_text("".join(f"{sha256_file(Path(model_dir) / n)}  {n}\n" for n in names))
