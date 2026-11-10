"""ExFuzzy Atlas HTTP API, v1.

Two modes, same endpoints and response models (``ATLAS_API_MODE``):

* ``mock`` (default): every response comes from fixtures/synthetic/ and is flagged ``synthetic: true``.
* ``artifacts``: precomputed views of published models under ``ATLAS_PUBLISHED_DIR`` (see docs/api.md).

Run with ``make api`` and open /docs. The query validation (the 422 rules) lives here, so both modes share it.
"""

from __future__ import annotations

import math
import os
from datetime import timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from atlas.contracts import models as m
from atlas.services.scenarios import ScenarioError
from atlas_api.store import BadRequest, NotFound, Store

MAX_WINDOW = timedelta(days=366)
DEFAULT_TAU = 0.5
MAX_STORIES = 50

Utc = Annotated[m.UtcDatetime, Query(description="ISO 8601 instant in UTC, e.g. 2025-01-15T06:00:00Z")]


def make_store(mode: str | None = None) -> Store:
    """The store selected by ``ATLAS_API_MODE`` (``mock`` or ``artifacts``)."""
    mode = mode or os.environ.get("ATLAS_API_MODE", "mock")
    if mode == "mock":
        from atlas_api.mock_store import FixtureStore

        return FixtureStore()
    if mode == "artifacts":
        from atlas_api.artifact_store import ArtifactStore

        return ArtifactStore.from_env()
    raise ValueError(f"ATLAS_API_MODE must be 'mock' or 'artifacts', got {mode!r}")


def _found(call, *args):
    try:
        return call(*args)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BadRequest, ScenarioError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _check_window(start, end) -> None:
    if end <= start:
        raise HTTPException(422, "`to` must be after `from`")
    if end - start > MAX_WINDOW:
        raise HTTPException(422, f"the window is limited to {MAX_WINDOW.days} days")


def _check_time_or_window(time, start, end) -> None:
    """A single issue time, or a half-open window [from, to) (latest sample per entity); never both nor neither."""
    if time is not None and (start is not None or end is not None):
        raise HTTPException(422, "pass `time` (one issue time) or `from`/`to` (a window), not both")
    if time is None:
        if start is None or end is None:
            raise HTTPException(422, "pass `time` (one issue time) or both `from` and `to` (a window)")
        _check_window(start, end)


def create_app(store: Store) -> FastAPI:
    app = FastAPI(title="ExFuzzy Atlas API", version=m.SCHEMA_VERSION)
    app.add_middleware(
        CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    # Model cards (up to 4.6 MB of JSON for Germany: metrics per station and rule) and rule maps compress about 10x.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc: RequestValidationError):
        """FastAPI's 422, except that a rejected NaN/Infinity is echoed as text (JSON cannot carry it)."""
        errors = [
            {**e, "input": str(e["input"])}
            if isinstance(e.get("input"), float) and not math.isfinite(e["input"]) else e
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @app.get("/api/v1/health", response_model=m.Health)
    def health():
        return m.Health(status="ok", mode=store.mode)

    @app.get("/api/v1/domains", response_model=m.DomainsResponse)
    def domains():
        return store.domains()

    @app.get("/api/v1/entities", response_model=m.EntityCollection)
    def entities(
        domain: m.Domain,
        task_id: Annotated[str | None, Query(description="required when the domain serves several tasks")] = None,
    ):
        """Entities of one task. Without `task_id`: a single-task domain answers as before, several tasks is a 422."""
        return _found(store.entity_collection, domain, task_id)

    @app.get("/api/v1/models/{model_id}", response_model=m.ModelCard)
    def model_card(model_id: str):
        return _found(store.model_card, model_id)

    @app.get("/api/v1/models/{model_id}/rules", response_model=m.ModelRules)
    def model_rules(model_id: str):
        return _found(store.model_rules, model_id)

    @app.get("/api/v1/models/{model_id}/importance", response_model=m.RuleImportanceResponse)
    def model_importance(model_id: str):
        """How much each rule and input weighs in the published predictions (decides and hits); 404 before v0.5."""
        return _found(store.importance, model_id)

    @app.get("/api/v1/models/{model_id}/explanation", response_model=m.ModelExplanation)
    def model_explanation(model_id: str):
        """A short text about the rule base, in Spanish and English, written by an AI from the published files
        (``generated_by``; ``reviewed`` says whether a person has checked it); 404 when the model has none."""
        return _found(store.explanation, model_id)

    @app.get("/api/v1/summary", response_model=m.SummaryResponse)
    def summary(task_id: str):
        """Distribution of the task's observed variable over its whole history, in groups; 404 before v0.5."""
        return _found(store.summary, task_id)

    @app.get("/api/v1/series", response_model=m.SeriesResponse)
    def series(
        task_id: str, entity_id: str,
        from_: Annotated[m.UtcDatetime | None, Query(alias="from")] = None,
        to: Annotated[m.UtcDatetime | None, Query()] = None,
        cursor: Annotated[m.UtcDatetime | None, Query(description="`next_cursor` of the previous page")] = None,
    ):
        """Observed and predicted points by issue time; large windows come in pages (follow `next_cursor`)."""
        if from_ is not None and to is not None and to <= from_:
            raise HTTPException(422, "`to` must be after `from`")
        series = _found(store.series_for, task_id, entity_id, from_, to, cursor)
        # serialised once by pydantic's Rust core: going through response_model would dump, re-validate and re-encode
        # every point (thousands of objects) in Python. `response_model` stays for the OpenAPI schema.
        return Response(series.model_dump_json(), media_type="application/json")

    @app.get("/api/v1/rule-map", response_model=m.RuleMapResponse)
    def rule_map(
        model_id: str, rule_id: str, metric: m.RuleMapMetric,
        time: Annotated[m.UtcDatetime | None, Query(description="issued_at_utc, for metric=firing_strength")] = None,
        from_: Annotated[m.UtcDatetime | None, Query(alias="from", description="window start (inclusive)")] = None,
        to: Annotated[m.UtcDatetime | None, Query(description="window end (exclusive)")] = None,
        tau: Annotated[float | None, Query(gt=0, le=1, description="threshold for activation_frequency")] = None,
    ):
        """GeoJSON of one rule over the model's entities. ``time`` is an issue time, not a valid time."""
        if metric == m.RuleMapMetric.FIRING_STRENGTH:
            if time is None or from_ is not None or to is not None:
                raise HTTPException(422, "firing_strength takes `time` (a single issue time), not from/to")
        else:
            if from_ is None or to is None or time is not None:
                raise HTTPException(422, f"{metric.value} takes a window `from`/`to`, not `time`")
            if to <= from_:
                raise HTTPException(422, "`to` must be after `from`")
            if to - from_ > MAX_WINDOW:
                raise HTTPException(422, f"the window is limited to {MAX_WINDOW.days} days")
        if (metric == m.RuleMapMetric.ACTIVATION_FREQUENCY) != (tau is not None):
            raise HTTPException(422, "`tau` is required for activation_frequency and only for it")
        return _found(store.rule_map, model_id, rule_id, metric, time, from_, to, tau)

    @app.get("/api/v1/entities/{entity_id}/rule-trace", response_model=m.RuleTrace)
    def rule_trace(entity_id: str, model_id: str, at: Utc):
        return _found(store.rule_trace, model_id, entity_id, at)

    @app.get("/api/v1/predictions", response_model=m.PredictionsResponse)
    def predictions(
        task_id: str,
        time: Annotated[m.UtcDatetime | None, Query(description="issued_at_utc of every row")] = None,
        from_: Annotated[m.UtcDatetime | None, Query(alias="from", description="window start (inclusive)")] = None,
        to: Annotated[m.UtcDatetime | None, Query(description="window end (exclusive)")] = None,
    ):
        """All entities at one issue time, or the latest sample per entity in `[from, to)` (irregular tasks)."""
        _check_time_or_window(time, from_, to)
        return _found(store.predictions, task_id, time, from_, to)

    @app.get("/api/v1/observations", response_model=m.ObservationsResponse)
    def observations(
        task_id: str,
        time: Annotated[m.UtcDatetime | None, Query(description="issued_at_utc of every row")] = None,
        from_: Annotated[m.UtcDatetime | None, Query(alias="from", description="window start (inclusive)")] = None,
        to: Annotated[m.UtcDatetime | None, Query(description="window end (exclusive)")] = None,
    ):
        """Observed target and model inputs per entity (data mode). Not a prediction, not an interpolation."""
        _check_time_or_window(time, from_, to)
        return _found(store.observations, task_id, time, from_, to)

    @app.get("/api/v1/rule-territories", response_model=m.RuleTerritoriesResponse)
    def rule_territories(
        model_id: str,
        from_: Annotated[m.UtcDatetime, Query(alias="from", description="window start (inclusive)")],
        to: Annotated[m.UtcDatetime, Query(description="window end (exclusive)")],
        measure: m.TerritoryMeasure = m.TerritoryMeasure.MEAN_ACTIVATION,
        tau: Annotated[float, Query(gt=0, le=1, description="threshold of activation_frequency")] = DEFAULT_TAU,
    ):
        """Empirical territory of every rule over `[from, to)` and the dominant rule under `measure` (argmax only)."""
        _check_window(from_, to)
        return _found(store.rule_territories, model_id, from_, to, measure, tau)

    @app.get("/api/v1/rule-stories", response_model=m.RuleStoriesResponse)
    def rule_stories(
        model_id: str,
        from_: Annotated[m.UtcDatetime, Query(alias="from", description="window start (inclusive)")],
        to: Annotated[m.UtcDatetime, Query(description="window end (exclusive)")],
        tau: Annotated[float, Query(gt=0, le=1)] = DEFAULT_TAU,
        limit: Annotated[int, Query(ge=1, le=MAX_STORIES)] = 10,
    ):
        """Template-built, ranked statements about activations, each with the query that reproduces its numbers."""
        _check_window(from_, to)
        return _found(store.rule_stories, model_id, from_, to, tau, limit)

    @app.post("/api/v1/scenarios", response_model=m.ScenarioResponse)
    def scenarios(request: m.ScenarioRequest):
        """Model response to modified inputs of one published row (real ex_fuzzy inference). Writes nothing."""
        return _found(store.scenario, request)

    return app


app = create_app(make_store())
