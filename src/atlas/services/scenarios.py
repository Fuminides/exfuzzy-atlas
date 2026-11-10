"""What-if (MAP_EXPERIENCE E5, contract v0.4): the model's answer to one modified input row.

The caller supplies the published trace of the row and a function that runs the real ex_fuzzy inference on a full
set of input values (``atlas.explain``); nothing here computes a membership, a firing or a prediction. The dataset
and the published files are never written. The result is a *response of the model to modified inputs*: it is neither
a causal effect nor a forecast, and ``ScenarioResponse.label`` says so.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from atlas.contracts import models as m

OVERRIDE_SOURCE_ID = "what_if_override"
# Quality warning of a modified trace; the static export ships this template so a client writes the same text.
OVERRIDE_WARNING = "what-if: inputs overridden ({features}); {label}"


class ScenarioError(ValueError):
    """The request is not a valid scenario (unknown feature, non-finite or out-of-domain value): HTTP 422."""


def validate_overrides(rules: m.ModelRules, features: list[str], overrides: Mapping[str, float]) -> None:
    domains = {v.feature: v.domain for v in rules.variables}
    unknown = sorted(set(overrides) - set(features))
    if unknown:
        raise ScenarioError(f"unknown features {unknown}; the model's inputs are {features}")
    for feature, value in overrides.items():
        if not math.isfinite(value):
            raise ScenarioError(f"{feature}: the value must be finite")
        domain = domains.get(feature)
        if domain is not None and not domain[0] <= value <= domain[1]:
            raise ScenarioError(f"{feature}={value:g} is outside the variable's domain [{domain[0]:g}, {domain[1]:g}]")


def build_scenario(
    request: m.ScenarioRequest, rules: m.ModelRules, original: m.RuleTrace,
    rerun: Callable[[dict[str, float | None]], m.RuleTrace],
) -> m.ScenarioResponse:
    """``original`` is the trace of the published row; ``rerun`` runs the engine on all input values (None = missing).

    Features that are not overridden keep the original ``FeatureValue`` untouched (provenance included); an
    overridden one has ``source_id="what_if_override"`` and no ``observed_at_utc``, since nobody observed it. With
    no override the modified trace is the original one. With overrides, ``observed`` is dropped: the observed
    target belongs to the unmodified row.
    """
    originals = {fv.feature: fv for fv in original.feature_values}
    validate_overrides(rules, list(originals), request.overrides)
    domains = {v.feature: v.domain for v in rules.variables}
    values = {name: fv.value for name, fv in originals.items()}
    values.update(request.overrides)
    trace = rerun(values)
    feature_values = []
    for fv in trace.feature_values:
        if fv.feature in request.overrides:
            feature_values.append(fv.model_copy(update={"source_id": OVERRIDE_SOURCE_ID, "observed_at_utc": None}))
        else:
            feature_values.append(originals[fv.feature])
    warnings = list(trace.quality.warnings)
    if request.overrides:
        warnings.append(OVERRIDE_WARNING.format(features=", ".join(sorted(request.overrides)), label=m.WHAT_IF_LABEL))
    modified = m.RuleTrace.model_validate(trace.model_copy(update={
        "feature_values": feature_values,
        "observation_ids": [] if request.overrides else original.observation_ids,
        "observed": None if request.overrides else original.observed,
        "observed_label": None if request.overrides else original.observed_label,
        "quality": m.Quality(
            status=m.QualityStatus.WARNING if warnings else trace.quality.status, warnings=warnings,
        ) if request.overrides else trace.quality,
    }).model_dump())
    inputs = [
        m.ScenarioInput(
            feature=name, unit=originals[name].unit,
            origin="overridden" if name in request.overrides else "observed",
            original_value=originals[name].value,
            scenario_value=request.overrides.get(name, originals[name].value),
            domain=domains.get(name), missing_reason=originals[name].missing_reason,
        )
        for name in originals
    ]
    return m.ScenarioResponse(
        data_version=original.data_version, synthetic=original.synthetic, model_id=request.model_id,
        entity_id=request.entity_id, issued_at_utc=original.issued_at_utc, inputs=inputs, original=original,
        modified=modified, rule_deltas=rule_deltas(original, modified),
        prediction_change=prediction_change(original, modified),
    )


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def rule_deltas(original: m.RuleTrace, modified: m.RuleTrace) -> list[m.RuleDelta]:
    before = {e.rule_id: e for e in original.rules}
    after = {e.rule_id: e for e in modified.rules}
    deltas = []
    for rule_id in [*before, *(r for r in after if r not in before)]:
        a, b = before.get(rule_id), after.get(rule_id)
        fa, fb = (a.firing_strength if a else None), (b.firing_strength if b else None)
        aa, ab = (a.association_degree if a else None), (b.association_degree if b else None)
        deltas.append(m.RuleDelta(
            rule_id=rule_id, firing_original=fa, firing_scenario=fb, firing_delta=_delta(fa, fb),
            association_original=aa, association_scenario=ab, association_delta=_delta(aa, ab),
        ))
    return deltas


def prediction_change(original: m.RuleTrace, modified: m.RuleTrace) -> m.PredictionChange:
    a, b = original.prediction, modified.prediction
    classified = a.label is not None or b.label is not None
    return m.PredictionChange(
        original_value=a.value, scenario_value=b.value, value_delta=_delta(a.value, b.value),
        original_label=a.label, scenario_label=b.label,
        label_changed=(a.label != b.label) if classified else None,
        original_winning_rule_id=a.winning_rule_id, scenario_winning_rule_id=b.winning_rule_id,
        original_top_rule_id=a.top_rule_id, scenario_top_rule_id=b.top_rule_id,
    )
