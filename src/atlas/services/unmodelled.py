"""Entities that exist in the geometry file but have no model (contract v0.4, ``EntityProperties.modelled = false``)."""

from __future__ import annotations

from datetime import datetime, timedelta

from atlas.contracts import models as m


def not_modelled_trace(
    *, inference: m.InferenceSpec, model_id: str, task_id: str, entity_id: str, at: datetime, horizon_hours: int,
    target_unit: str, data_version: str, synthetic: bool,
) -> m.RuleTrace:
    """A trace with no inputs, no rules and no prediction (``missing_reason = not_modelled``), whatever the time."""
    return m.RuleTrace(
        data_version=data_version, synthetic=synthetic, model_id=model_id, task_id=task_id, entity_id=entity_id,
        issued_at_utc=at, valid_at_utc=at + timedelta(hours=horizon_hours), inference=inference, feature_values=[],
        rules=[],
        prediction=m.TracePrediction(
            value=None, unit=target_unit, fallback_used=False, missing_reason=m.MissingReason.NOT_MODELLED),
        quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["entity without a model (not_modelled)"]),
    )
