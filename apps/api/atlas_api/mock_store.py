"""Fixture-backed data access for the mock API.

Serves fixtures/synthetic/ so the web client can be built before real artifacts exist.
Rule-map aggregates are computed here, in the backend, from the traces that ex_fuzzy
produced; the client never recomputes firing.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from atlas.contracts import models as m
from atlas.services import importance, scenarios, stories, territories, unmodelled
from atlas.services.mock_model import build_rulebase
from atlas_api.store import BadRequest, NotFound, served_task

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic"


class FixtureStore:
    mode = "mock"

    def __init__(self, root: Path = FIXTURES_DIR):
        def load(name):
            return json.loads((root / name).read_text())

        self._domains = m.DomainsResponse.model_validate(load("domains.json"))
        self.entities = {m.Domain.AIR: m.EntityCollection.model_validate(load("entities_air.json"))}
        rules = m.ModelRules.model_validate(load("model_rules.json"))
        self.rules = {rules.model_id: rules}
        card = m.ModelCard.model_validate(load("model_card.json"))
        self.cards = {card.manifest.model_id: card}
        self.traces = {
            (t.model_id, t.entity_id, t.issued_at_utc): t
            for t in (m.RuleTrace.model_validate(x) for x in load("rule_traces.json"))
        }
        self.series = {
            (s.task_id, s.entity_id): s for s in (m.SeriesResponse.model_validate(x) for x in load("series.json"))
        }
        self._rulebase = None  # the toy rule base, built on the first what-if
        # contract v0.5: precomputed by scripts/make_fixtures.py with the production code (services.importance/summary)
        self.importances = {x.model_id: x for x in (
            m.RuleImportanceResponse.model_validate(y) for y in load("importance.json"))}
        self.summaries = {x.task_id: x for x in (m.SummaryResponse.model_validate(y) for y in load("summary.json"))}
        # contract v0.6.2: a synthetic explanation of the toy model (written by scripts/make_fixtures.py, not by an AI)
        self.explanations = {x.model_id: x for x in (
            m.ModelExplanation.model_validate(y) for y in load("explanations.json"))}
        for extra in load("model_rules_extra.json"):  # the synthetic classifiers that the fixtures above refer to
            classifier = m.ModelRules.model_validate(extra)
            self.rules[classifier.model_id] = classifier
        # contract v0.7: the rule traces of the synthetic mixture of rules (artifacts-mode responses in v07_responses)
        for item in load("v07_responses.json"):
            if item["path"].endswith("/rule-trace"):
                trace = m.RuleTrace.model_validate(item["response"])
                self.traces[(trace.model_id, trace.entity_id, trace.issued_at_utc)] = trace

    def domains(self) -> m.DomainsResponse:
        return self._domains

    def model_rules(self, model_id: str) -> m.ModelRules:
        if model_id not in self.rules:
            raise NotFound(f"unknown model_id {model_id}")
        return self.rules[model_id]

    def importance(self, model_id: str) -> m.RuleImportanceResponse:
        if model_id not in self.importances:
            raise NotFound(f"{model_id} has no importance fixture")
        return self.importances[model_id]

    def explanation(self, model_id: str) -> m.ModelExplanation:
        if model_id not in self.explanations:
            raise NotFound(f"{model_id} has no explanation fixture")
        return self.explanations[model_id]

    def summary(self, task_id: str) -> m.SummaryResponse:
        if task_id not in self.summaries:
            raise NotFound(f"{task_id} has no summary fixture")
        return self.summaries[task_id]

    def model_card(self, model_id: str) -> m.ModelCard:
        if model_id not in self.cards:
            raise NotFound(f"unknown model_id {model_id}")
        return self.cards[model_id]

    def entity_collection(self, domain: m.Domain, task_id: str | None = None) -> m.EntityCollection:
        served = {t.task_id: d.domain for d in self._domains.domains for t in d.tasks}
        served_task(served, domain, task_id)
        if domain not in self.entities:
            raise NotFound(f"no entities for domain {domain.value}")
        return self.entities[domain]

    def rule_trace(self, model_id: str, entity_id: str, at: datetime) -> m.RuleTrace:
        rules = self.model_rules(model_id)
        for entity in self.entity_collection(rules.domain).features:
            if entity.properties.entity_id == entity_id and entity.properties.modelled is False:
                task = self._task(rules.task_id)
                return unmodelled.not_modelled_trace(
                    inference=rules.inference, model_id=model_id, task_id=rules.task_id, entity_id=entity_id, at=at,
                    horizon_hours=task.horizon_hours, target_unit=task.unit, data_version=rules.data_version,
                    synthetic=rules.synthetic,
                )
        key = (model_id, entity_id, at)
        if key not in self.traces:
            raise NotFound(f"no trace for {entity_id} at {at.isoformat()}")
        return self.traces[key]

    def series_for(
        self, task_id: str, entity_id: str, start: datetime | None, end: datetime | None,
        cursor: datetime | None = None,
    ):
        """The fixture series are tiny, so ``cursor`` (pagination) is accepted and ignored."""
        if (task_id, entity_id) not in self.series:
            raise NotFound(f"no series for {task_id}/{entity_id}")
        s = self.series[(task_id, entity_id)]
        points = [
            p for p in s.points
            if (start is None or p.issued_at_utc >= start) and (end is None or p.issued_at_utc < end)
        ]
        return s.model_copy(update={"points": points})

    def rule_map(
        self, model_id: str, rule_id: str, metric: m.RuleMapMetric,
        time: datetime | None, start: datetime | None, end: datetime | None, tau: float | None,
    ) -> m.RuleMapResponse:
        rules = self.model_rules(model_id)
        if rule_id not in {r.rule_id for r in rules.rules}:
            raise NotFound(f"unknown rule_id {rule_id} for {model_id}")
        collection = self.entity_collection(rules.domain)
        instant = metric == m.RuleMapMetric.FIRING_STRENGTH
        if instant:
            start = end = time

        def selected(issued: datetime) -> bool:  # one instant, or the half-open window [start, end)
            return issued == time if instant else start <= issued < end

        features = []
        for entity in collection.features:
            eid = entity.properties.entity_id
            in_window = [
                t for (mid, e, issued), t in self.traces.items() if mid == model_id and e == eid and selected(issued)
            ]
            firings = [
                entry.firing_strength for t in in_window for entry in t.rules if entry.rule_id == rule_id
            ]
            if firings:
                if metric == m.RuleMapMetric.ACTIVATION_FREQUENCY:
                    value = sum(f >= tau for f in firings) / len(firings)
                else:
                    value = sum(firings) / len(firings)
                reason = None
            else:
                value = None
                reason = m.MissingReason.MISSING_INPUT if in_window else m.MissingReason.NO_OBSERVATION
            single = in_window[0] if instant and in_window else None
            if entity.properties.modelled is False:
                reason = m.MissingReason.NOT_MODELLED
            features.append(m.RuleMapFeature(
                type="Feature", id=eid, geometry=entity.geometry,
                properties=m.RuleMapProperties(
                    entity_id=eid, rule_id=rule_id, metric=metric, value=value, n_valid=len(firings),
                    time_from_utc=start, time_to_utc=end,
                    issued_at_utc=time if instant else None,
                    valid_at_utc=single.valid_at_utc if single else None,
                    tau=tau, model_id=model_id, data_version=rules.data_version,
                    geometry_support=entity.properties.geometry_support, missing_reason=reason,
                    quality=single.quality if single else m.Quality(),
                ),
            ))
        return m.RuleMapResponse(
            type="FeatureCollection", data_version=rules.data_version, synthetic=rules.synthetic,
            model_id=model_id, rule_id=rule_id, metric=metric, tau=tau,
            time_from_utc=start, time_to_utc=end, features=features,
        )

    # ------------------------------------------------------- contract v0.4 views

    def _task(self, task_id: str) -> m.TaskInfo:
        for domain in self._domains.domains:
            for task in domain.tasks:
                if task.task_id == task_id and task.model_id:
                    return task
        raise NotFound(f"unknown task_id {task_id}")

    def _latest(self, model_id: str, entity_id: str, time, start, end) -> m.RuleTrace | None:
        """The trace at ``time`` or the latest one issued in ``[start, end)``."""
        if time is not None:
            return self.traces.get((model_id, entity_id, time))
        inside = [t for (mid, e, issued), t in self.traces.items()
                  if mid == model_id and e == entity_id and start <= issued < end]
        return max(inside, key=lambda t: t.issued_at_utc, default=None)

    def _query_bounds(self, time, start, end) -> dict:
        return {"issued_at_utc": time} if time is not None else {"time_from_utc": start, "time_to_utc": end}

    @staticmethod
    def _decided_by(trace: m.RuleTrace, rules: m.ModelRules) -> str | None:
        """``decided_by_rule_id`` of a trace, the measure of /importance: the winning rule, or the largest f_r/Σf."""
        if trace.prediction.winning_rule_id is not None:
            return trace.prediction.winning_rule_id
        if trace.prediction.value is None:
            return None
        frame = pd.DataFrame({"entity_id": trace.entity_id, "issued_at_utc": trace.issued_at_utc,
                              "rule_id": [r.rule_id for r in trace.rules],
                              "effective_firing": [r.effective_firing for r in trace.rules]})
        covered = importance.weight_shares(frame, {r.rule_id: r.position for r in rules.rules})
        return None if not covered.any() else str(importance.deciding_rows(frame[covered])["rule_id"].iloc[0])

    def predictions(self, task_id, time, start, end) -> m.PredictionsResponse:
        task = self._task(task_id)
        rules = self.model_rules(task.model_id)
        features = []
        for entity in self.entity_collection(rules.domain).features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=task.model_id, data_version=rules.data_version, unit=task.unit,
                          geometry_support=props.geometry_support)
            trace = None if props.modelled is False else self._latest(task.model_id, eid, time, start, end)
            if trace is None:
                reason = m.MissingReason.NOT_MODELLED if props.modelled is False else m.MissingReason.NO_OBSERVATION
                body = dict(issued_at_utc=None, valid_at_utc=None, prediction=None, missing_reason=reason)
            else:
                point = next(p for p in self.series[(task_id, eid)].points if p.issued_at_utc == trace.issued_at_utc)
                body = dict(
                    issued_at_utc=point.issued_at_utc, valid_at_utc=point.valid_at_utc, prediction=point.prediction,
                    prediction_label=point.predicted_label, observed=point.observed,
                    observed_label=point.observed_label, missing_reason=point.missing_reason,
                    decided_by_rule_id=self._decided_by(trace, rules),
                )
            features.append(m.PredictionFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.PredictionProperties(**common, **body),
            ))
        return m.PredictionsResponse(
            type="FeatureCollection", data_version=rules.data_version, synthetic=rules.synthetic, task_id=task_id,
            model_id=task.model_id, task_type=task.task_type, target=task.target, unit=task.unit,
            horizon_hours=task.horizon_hours, features=features, **self._query_bounds(time, start, end),
        )

    def observations(self, task_id, time, start, end) -> m.ObservationsResponse:
        task = self._task(task_id)
        rules = self.model_rules(task.model_id)
        features = []
        for entity in self.entity_collection(rules.domain).features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=task.model_id, data_version=rules.data_version,
                          geometry_support=props.geometry_support)
            trace = None if props.modelled is False else self._latest(task.model_id, eid, time, start, end)
            if trace is None:
                reason = m.MissingReason.NOT_MODELLED if props.modelled is False else m.MissingReason.NO_OBSERVATION
                body = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[], missing_reason=reason)
            else:
                point = next(p for p in self.series[(task_id, eid)].points if p.issued_at_utc == trace.issued_at_utc)
                missing = [fv.feature for fv in trace.feature_values if fv.value is None]
                body = dict(
                    issued_at_utc=trace.issued_at_utc, valid_at_utc=trace.valid_at_utc, inputs=trace.feature_values,
                    target=m.FeatureValue(
                        feature=task.target, value=point.observed, unit=task.unit, observed_at_utc=trace.valid_at_utc,
                        missing_reason=None if point.observed is not None else m.MissingReason.NO_OBSERVATION),
                    target_label=point.observed_label,
                    quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)])
                    if missing else m.Quality(),
                )
            features.append(m.ObservationFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.ObservationProperties(**common, **body),
            ))
        return m.ObservationsResponse(
            type="FeatureCollection", data_version=rules.data_version, synthetic=rules.synthetic, task_id=task_id,
            model_id=task.model_id, target=task.target, unit=task.unit, horizon_hours=task.horizon_hours,
            features=features, **self._query_bounds(time, start, end),
        )

    def _in_window(self, model_id: str, start: datetime, end: datetime) -> list[m.RuleTrace]:
        return [t for (mid, _, issued), t in self.traces.items() if mid == model_id and start <= issued < end]

    def rule_territories(self, model_id, start, end, measure, tau) -> m.RuleTerritoriesResponse:
        rules = self.model_rules(model_id)
        if measure == m.TerritoryMeasure.WINNER_SHARE:
            raise BadRequest("winner_share only exists for classifiers; use mean_activation or activation_frequency")
        rule_ids = [r.rule_id for r in rules.rules]
        acc: dict[str, dict] = {}
        for trace in self._in_window(model_id, start, end):
            entity = acc.setdefault(trace.entity_id, {"n_records": 0, "n_valid": 0, "sum": dict.fromkeys(rule_ids, 0.0),
                                                     "over": dict.fromkeys(rule_ids, 0)})
            entity["n_records"] += 1
            if trace.rules:
                entity["n_valid"] += 1
                for entry in trace.rules:
                    entity["sum"][entry.rule_id] += entry.firing_strength
                    entity["over"][entry.rule_id] += entry.firing_strength >= tau
        rows = [
            [eid, rule_id, a["n_records"], a["n_valid"], a["sum"][rule_id], a["over"][rule_id], 0]
            for eid, a in acc.items() for rule_id in rule_ids
        ]
        return territories.build_territories(
            model_id=model_id, data_version=rules.data_version, synthetic=rules.synthetic,
            family=rules.inference.family, rule_ids=rule_ids,
            entities=self.entity_collection(rules.domain).features,
            stats=pd.DataFrame(rows, columns=territories.STATS_COLUMNS) if rows else territories.empty_stats(),
            measure=measure, tau=tau, start=start, end=end,
        )

    def rule_stories(self, model_id, start, end, tau, limit) -> m.RuleStoriesResponse:
        rules = self.model_rules(model_id)
        rule_ids = [r.rule_id for r in rules.rules]
        steps: dict[tuple, list[int]] = {}
        for trace in self._in_window(model_id, start, end):
            if trace.rules:
                for entry in trace.rules:
                    counts = steps.setdefault((entry.rule_id, trace.issued_at_utc), [0, 0])
                    counts[0] += 1
                    counts[1] += entry.firing_strength >= tau
        frame = pd.DataFrame([[r, pd.Timestamp(t), *c] for (r, t), c in steps.items()], columns=stories.STEP_COLUMNS)
        collection = self.entity_collection(rules.domain)
        return stories.build_stories(
            model_id=model_id, data_version=rules.data_version, synthetic=rules.synthetic, domain=rules.domain,
            rule_ids=rule_ids,
            territories=self.rule_territories(model_id, start, end, m.TerritoryMeasure.MEAN_ACTIVATION, tau),
            step_stats=frame, step_hours=1,
            entity_names={f.properties.entity_id: f.properties.name or f.properties.entity_id
                          for f in collection.features},
            start=start, end=end, tau=tau, limit=limit,
        )

    def scenario(self, request: m.ScenarioRequest) -> m.ScenarioResponse:
        """Reruns the real ex_fuzzy engine on the toy rule base behind the fixtures (not a stored answer)."""
        from atlas.explain import build_rule_traces

        rules = self.model_rules(request.model_id)
        flags = {f.properties.entity_id: f.properties.modelled for f in self.entity_collection(rules.domain).features}
        if flags.get(request.entity_id) is False:
            raise BadRequest(f"{request.entity_id} has no model (not_modelled): there is no row to modify")
        original = self.rule_trace(request.model_id, request.entity_id, request.at)
        if self._rulebase is None:
            self._rulebase = build_rulebase()

        horizon_hours = int((original.valid_at_utc - original.issued_at_utc).total_seconds() // 3600)

        def rerun(values: dict[str, float | None]) -> m.RuleTrace:
            X = pd.DataFrame([{name: float("nan") if v is None else v for name, v in values.items()}])
            return build_rule_traces(
                self._rulebase, X, [request.entity_id], [request.at], model_id=request.model_id,
                task_id=original.task_id, horizon_hours=horizon_hours, target_unit=original.prediction.unit,
                data_version=original.data_version, synthetic=original.synthetic,
            )[0]

        try:
            return scenarios.build_scenario(request, rules, original, rerun)
        except scenarios.ScenarioError as exc:
            raise BadRequest(str(exc)) from exc
