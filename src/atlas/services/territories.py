"""Rule Territories (MAP_EXPERIENCE E2): the empirical territory of every rule over a window ``[from, to)``.

The data stores compute one row per (entity, rule) of firing statistics (``STATS_COLUMNS``); this module turns them
into the contract response, so the mock and artifacts stores share every rule of the semantics:

* ``n_valid`` = records of the entity in the window whose inputs are all present (the denominator of every value);
* ``mean_activation`` = mean firing over them, ``activation_frequency`` = share with firing >= ``tau``;
* ``winner_share`` (classifiers) = share in which the rule decided the class; it sums to at most 1 over the rules
  because a record nothing fires on has no winner;
* the dominant rule is the argmax of the chosen measure and nothing else (never a "contribution"); values within
  ``TIE_TOLERANCE`` tie and the lowest rule position wins (``atlas.contracts.models.dominant_index``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from atlas.contracts import models as m

STATS_COLUMNS = ["entity_id", "rule_id", "n_records", "n_valid", "sum_firing", "n_over", "n_win"]
DEFAULT_TAU = 0.5
TIE_BREAK = (
    f"Dominant rule = argmax of the measure over the rules of the entity; values within {m.TIE_TOLERANCE:g} tie "
    "and the rule with the lowest position (R01 before R02, ...) wins; null if the measure is 0 for every rule."
)
DENOMINATORS = (
    "n_valid = records of the entity with issue time in [from, to) whose inputs are all present. mean_activation, "
    "activation_frequency and winner_share are computed over those n_valid records (a missing input is never a 0)."
)
NOTES = [
    "Territories overlap: several rules are active in the same entity and record. They are not a partition.",
    "A rule's activation is a degree of match with the inputs. It is not a probability, a risk nor a contribution to "
    "the prediction, and the dominant rule is not the rule that explains the prediction.",
]


def empty_stats() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object" if c in ("entity_id", "rule_id") else "float64")
                         for c in STATS_COLUMNS})


def build_territories(
    *, model_id: str, data_version: str, synthetic: bool, family: m.InferenceFamily, rule_ids: Sequence[str],
    entities: Sequence[m.EntityFeature], stats: pd.DataFrame, measure: m.TerritoryMeasure, tau: float,
    start: datetime, end: datetime,
) -> m.RuleTerritoriesResponse:
    """The response for ``stats`` (one row per entity and rule that has records) over the model's entities."""
    classifier = family == m.InferenceFamily.WINNING_RULE_CLASSIFIER
    if measure == m.TerritoryMeasure.WINNER_SHARE and not classifier:
        raise ValueError("winner_share only exists for winning-rule classifiers")
    by_entity = {eid: frame.set_index("rule_id") for eid, frame in stats.groupby("entity_id", sort=False)}
    features = []
    for entity in entities:
        props = entity.properties
        eid = props.entity_id
        common = dict(entity_id=eid, model_id=model_id, data_version=data_version,
                      geometry_support=props.geometry_support)
        frame = by_entity.get(eid)
        if props.modelled is False:
            body = dict(n_records=0, n_valid=0, missing_reason=m.MissingReason.NOT_MODELLED)
        elif frame is None:
            body = dict(n_records=0, n_valid=0, missing_reason=m.MissingReason.NO_OBSERVATION)
        elif int(frame["n_valid"].iloc[0]) == 0:
            body = dict(
                n_records=int(frame["n_records"].iloc[0]), n_valid=0, missing_reason=m.MissingReason.MISSING_INPUT,
                quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input"]),
            )
        else:
            body = _entity_body(frame, rule_ids, classifier, measure)
        features.append(m.TerritoryFeature(
            type="Feature", id=eid, geometry=entity.geometry, properties=m.TerritoryProperties(**common, **body),
        ))
    return m.RuleTerritoriesResponse(
        type="FeatureCollection", data_version=data_version, synthetic=synthetic, model_id=model_id,
        inference_family=family, measure=measure, tau=tau, time_from_utc=start, time_to_utc=end,
        n_rules=len(rule_ids), tie_break=TIE_BREAK, denominators=DENOMINATORS, notes=NOTES, features=features,
    )


def _entity_body(frame: pd.DataFrame, rule_ids: Sequence[str], classifier: bool, measure: m.TerritoryMeasure) -> dict:
    n_valid = int(frame["n_valid"].iloc[0])
    stats = []
    for rule_id in rule_ids:
        row = frame.loc[rule_id]
        stats.append(m.TerritoryRuleStats(
            rule_id=rule_id,
            mean_activation=_unit(float(row["sum_firing"]) / n_valid),
            activation_frequency=_unit(float(row["n_over"]) / n_valid),
            winner_share=_unit(float(row["n_win"]) / n_valid) if classifier else None,
        ))
    chosen = m.dominant_index([getattr(s, measure.value) for s in stats])
    body = dict(n_records=int(frame["n_records"].iloc[0]), n_valid=n_valid, rules=stats)
    if chosen is None:
        body["quality"] = m.Quality(
            status=m.QualityStatus.WARNING, warnings=[f"{measure.value} is 0 for every rule: no dominant rule"])
    else:
        body.update(dominant_rule_id=stats[chosen].rule_id, dominant_value=getattr(stats[chosen], measure.value))
    return body


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))
