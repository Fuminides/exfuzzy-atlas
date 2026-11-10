"""What the routes need from a data backend; the mock and artifacts stores implement it."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from atlas.contracts import models as m


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    """A well-formed request the data cannot answer (e.g. winner_share for a regressor, an invalid scenario): 422."""


def served_task(served: dict[str, m.Domain], domain: m.Domain, task_id: str | None) -> str | None:
    """The task whose entities answer ``/entities?domain=&task_id=``; shared by both stores.

    ``served`` maps every served task_id to its domain. With ``task_id``: unknown -> NotFound (404), of another domain
    -> BadRequest (422). Without it: the domain's only task, or None when it has none; with several the request is
    ambiguous and is rejected (422) instead of merging the entities of different tasks (e.g. two countries) on one map.
    """
    if task_id is not None:
        if task_id not in served:
            raise NotFound(f"unknown task_id {task_id}")
        if served[task_id] != domain:
            raise BadRequest(f"task_id {task_id} belongs to domain {served[task_id].value}, not {domain.value}")
        return task_id
    mine = sorted(t for t, d in served.items() if d == domain)
    if len(mine) > 1:
        raise BadRequest(f"domain {domain.value} has {len(mine)} tasks ({', '.join(mine)}): pass task_id")
    return mine[0] if mine else None


class Store(Protocol):
    mode: Literal["mock", "artifacts"]

    def domains(self) -> m.DomainsResponse: ...

    def entity_collection(self, domain: m.Domain, task_id: str | None = None) -> m.EntityCollection: ...

    def model_card(self, model_id: str) -> m.ModelCard: ...

    def model_rules(self, model_id: str) -> m.ModelRules: ...

    def series_for(
        self, task_id: str, entity_id: str, start: datetime | None, end: datetime | None,
        cursor: datetime | None = None,
    ) -> m.SeriesResponse: ...

    def rule_map(
        self, model_id: str, rule_id: str, metric: m.RuleMapMetric,
        time: datetime | None, start: datetime | None, end: datetime | None, tau: float | None,
    ) -> m.RuleMapResponse: ...

    def rule_trace(self, model_id: str, entity_id: str, at: datetime) -> m.RuleTrace: ...

    # ---- contract v0.4

    def predictions(
        self, task_id: str, time: datetime | None, start: datetime | None, end: datetime | None,
    ) -> m.PredictionsResponse: ...

    def observations(
        self, task_id: str, time: datetime | None, start: datetime | None, end: datetime | None,
    ) -> m.ObservationsResponse: ...

    def rule_territories(
        self, model_id: str, start: datetime, end: datetime, measure: m.TerritoryMeasure, tau: float,
    ) -> m.RuleTerritoriesResponse: ...

    def rule_stories(
        self, model_id: str, start: datetime, end: datetime, tau: float, limit: int,
    ) -> m.RuleStoriesResponse: ...

    def scenario(self, request: m.ScenarioRequest) -> m.ScenarioResponse: ...

    # ---- contract v0.5 (NotFound while the model has no precomputed file)

    def importance(self, model_id: str) -> m.RuleImportanceResponse: ...

    def summary(self, task_id: str) -> m.SummaryResponse: ...

    # ---- contract v0.6.2 (NotFound while the model has no explanation)

    def explanation(self, model_id: str) -> m.ModelExplanation: ...
