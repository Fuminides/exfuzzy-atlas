"""Data access over published models (``atlas.services.publish``): the API's artifacts mode.

Everything is read from ``<published_dir>/<model_id>/`` with DuckDB (bounded memory, filters pushed down to
Parquet), never loaded whole. Rule maps are aggregated here, in the backend, from the precomputed firing table;
a rule trace reruns the verified ex_fuzzy engine on the single published input row. Same semantics as the mock
store: ``[from, to)`` windows, ``n_valid`` = non-missing records, ``missing_input`` when every record of an
entity is missing and ``no_observation`` when it has none.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.paths import ARTIFACTS_DIR, REPO_ROOT
from atlas.services import importance, layout, scenarios, stories, territories, unmodelled, verify
from atlas_api.cache import DEFAULT_CACHE_BYTES, ByteLRU, approx_bytes
from atlas_api.store import BadRequest, NotFound, served_task

# v0.6.2: the explanations live in git, next to the template they are written from (scripts/explain_model.py)
EXPLANATIONS_DIR = REPO_ROOT / "configs" / "explanations"
SERIES_MAX_POINTS = 2_000  # points per /series page; `next_cursor` continues (docs/api.md)
_NO_ISSUES = m.Quality()
_MICROSECOND = timedelta(microseconds=1)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


class _Published:
    """One published model directory, read lazily. Rebuilt when its ``SHA256SUMS`` changes (a re-publish)."""

    def __init__(self, path: Path):
        self.path = path
        sums = path / artifacts.CHECKSUM_FILE
        self.stamp = (sums.stat().st_mtime_ns, sums.stat().st_size)
        self.token = artifacts.sha256_file(sums)[:12]
        self.card = m.ModelCard.model_validate_json((path / layout.CARD_FILE).read_text())
        self.synthetic = self.card.synthetic
        rules = m.ModelRules.model_validate_json((path / "rules.json").read_text())
        self.rules = rules.model_copy(update={"synthetic": self.synthetic or rules.synthetic})
        entities = m.EntityCollection.model_validate_json((path / layout.ENTITIES_FILE).read_text())
        self.entities = entities.model_copy(update={"synthetic": self.synthetic or entities.synthetic})
        self.spec = layout.FeatureSpec.model_validate_json((path / layout.FEATURE_SPEC_FILE).read_text())
        manifest = self.card.manifest
        self.model_id, self.task_id = manifest.model_id, manifest.task_id
        self.data_version, self.horizon = manifest.data_version, timedelta(hours=manifest.horizon_hours)
        self.target_unit = manifest.hyperparameters["run_config"]["unit"]
        self.features = manifest.features
        self.entity_ids = {f.properties.entity_id for f in self.entities.features}
        self.unmodelled_ids = {f.properties.entity_id for f in self.entities.features if f.properties.modelled is False}
        self.rule_ids = {r.rule_id for r in self.rules.rules}
        self.rule_order = [r.rule_id for r in self.rules.rules]
        family = self.rules.inference.family
        self.classifier = family in m.CLASSIFIER_FAMILIES
        self.winning_rule = family == m.InferenceFamily.WINNING_RULE_CLASSIFIER
        self.mixture = family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER  # v0.7: no rule decides alone
        self.class_labels = [c.label for c in self.rules.target_scheme.classes] if self.classifier else []
        self.position = {r.rule_id: r.position for r in self.rules.rules}
        # decided_by_rule_id is defined where /importance is: winning-rule classifiers and additive zero-order TSK
        self.decides = self.winning_rule or (
            family == m.InferenceFamily.TSK_ZERO_ORDER and self.rules.inference.rule_mode == m.RuleMode.ADDITIVE)
        self._model = None
        self._lock = threading.Lock()
        self._v05: dict[str, object] = {}

    def v05(self, name: str, model_cls):
        """A v0.5 file (``importance.json``, ``summary.json``), validated and read once for this version of the model.

        ``NotFound`` when the file is absent: the model was published before contract v0.5 (backfill it with
        ``python -m atlas.services.enrich``)."""
        with self._lock:
            if name not in self._v05:
                path = self.path / name
                if not path.is_file():
                    raise NotFound(f"{self.model_id} has no {name}: it was published before contract v0.5 "
                                   "(republish it, or run python -m atlas.services.enrich)")
                loaded = model_cls.model_validate_json(path.read_text())
                self._v05[name] = loaded.model_copy(update={"synthetic": self.synthetic or loaded.synthetic})
            return self._v05[name]

    @property
    def model(self):
        """The fitted model, unpickled once after its code files are checked against ``SHA256SUMS`` (trusted artifacts
        only). Only ``model.pkl``, ``rules.json`` and ``card.json`` are hashed here; the rest is data, checked by
        ``atlas.services.verify`` and at publish time."""
        with self._lock:
            if self._model is None:
                self._model = verify.load_verified_model(self.path)
            return self._model


class ArtifactStore:
    mode = "artifacts"

    def __init__(
        self, root: Path, *, memory_limit: str = "512MB", threads: int = 2, cache_bytes: int = DEFAULT_CACHE_BYTES,
        explanations_dir: Path = EXPLANATIONS_DIR,
    ):
        self.root = Path(root)
        self.explanations_dir = Path(explanations_dir)
        self._db = duckdb.connect(config={"memory_limit": memory_limit, "threads": threads})
        self._db.execute("SET TimeZone='UTC'")
        self._cache = ByteLRU(cache_bytes)  # rule maps, territories and stories, bounded by approximate bytes
        self._lock = threading.Lock()
        self._models: dict[str, _Published] = {}

    @classmethod
    def from_env(cls) -> ArtifactStore:
        cache_mb = os.environ.get("ATLAS_CACHE_MB")
        return cls(
            Path(os.environ.get("ATLAS_PUBLISHED_DIR", ARTIFACTS_DIR / "published")),
            explanations_dir=Path(os.environ.get("ATLAS_EXPLANATIONS_DIR", EXPLANATIONS_DIR)),
            **({} if cache_mb is None else {"cache_bytes": int(float(cache_mb) * 2**20)}),
        )

    # ------------------------------------------------------------------ plumbing

    def _query(self, sql: str, params: list):
        with self._db.cursor() as cur:  # one cursor per call: DuckDB connections are not thread-safe
            return cur.execute(sql, params).fetchall()

    def _model(self, model_id: str) -> _Published:
        path = self.root / model_id
        sums = path / artifacts.CHECKSUM_FILE
        if "/" in model_id or model_id.startswith(".") or not sums.is_file():
            raise NotFound(f"unknown model_id {model_id}")
        stamp = (sums.stat().st_mtime_ns, sums.stat().st_size)
        with self._lock:
            cached = self._models.get(model_id)
            if cached is None or cached.stamp != stamp:
                cached = self._models[model_id] = _Published(path)
            return cached

    def _entry(self, task_id: str) -> layout.RegistryEntry:
        entry = layout.read_registry(self.root).tasks.get(task_id)
        if entry is None:
            raise NotFound(f"unknown task_id {task_id}")
        return entry

    def _files(self, h: _Published, name: str, lo: datetime, hi: datetime) -> list[str]:
        """Firing-table files of the months touched by ``[lo, hi)`` (partition pruning by directory)."""
        last = hi - _MICROSECOND
        files: list[str] = []
        for index in range(lo.year * 12 + lo.month - 1, last.year * 12 + last.month):
            year, month = divmod(index, 12)
            part_dir = h.path / name / f"year={year}" / f"month={month + 1:02d}"
            files += sorted(str(p) for p in part_dir.glob("*.parquet"))
        return files

    # --------------------------------------------------------------- simple views

    def domains(self) -> m.DomainsResponse:
        tasks = sorted(layout.read_registry(self.root).tasks.items())
        infos = []
        for domain in m.Domain:
            mine = [(task_id, e) for task_id, e in tasks if e.domain == domain]
            mine.sort(key=lambda item: item[0] != layout.DEFAULT_TASKS.get(domain))  # stable: the rest by task_id
            infos.append(m.DomainInfo(
                # one task: its title names the domain entry, as before; several: the generic domain title
                domain=domain, title=mine[0][1].title if len(mine) == 1 else layout.DOMAIN_TITLES[domain],
                status="available" if mine else "planned",
                tasks=[
                    m.TaskInfo(task_id=task_id, task_type=e.task_type, target=e.target, unit=e.unit,
                               horizon_hours=e.horizon_hours, status="available", model_id=e.model_id,
                               title=e.title, territory=e.territory, territory_title=e.territory_title,
                               territory_title_en=e.territory_title_en)
                    for task_id, e in mine
                ],
            ))
        versions = sorted({e.data_version for _, e in tasks})
        return m.DomainsResponse(
            data_version=",".join(versions) or "unpublished", synthetic=any(e.synthetic for _, e in tasks),
            domains=infos,
        )

    def entity_collection(self, domain: m.Domain, task_id: str | None = None) -> m.EntityCollection:
        tasks = layout.read_registry(self.root).tasks
        chosen = served_task({t: e.domain for t, e in tasks.items()}, domain, task_id)
        served = [] if chosen is None else [tasks[chosen]]
        features: dict[str, m.EntityFeature] = {}
        versions: set[str] = set()
        credits: dict[str, m.Attribution] = {}
        synthetic = False
        for entry in served:
            h = self._model(entry.model_id)
            versions.add(h.entities.data_version)
            synthetic = synthetic or h.entities.synthetic
            for credit in h.entities.attribution:
                credits.setdefault(credit.text, credit)
            for feature in h.entities.features:
                features.setdefault(feature.id, feature)
        if not served:
            raise NotFound(f"no entities for domain {domain.value}")
        return m.EntityCollection(
            data_version=",".join(sorted(versions)), synthetic=synthetic, type="FeatureCollection", domain=domain,
            attribution=list(credits.values()), features=list(features.values()),
        )

    def model_card(self, model_id: str) -> m.ModelCard:
        return self._model(model_id).card

    def model_rules(self, model_id: str) -> m.ModelRules:
        return self._model(model_id).rules

    # ------------------------------------------------------------ contract v0.5

    def importance(self, model_id: str) -> m.RuleImportanceResponse:
        return self._model(model_id).v05(layout.IMPORTANCE_FILE, m.RuleImportanceResponse)

    def summary(self, task_id: str) -> m.SummaryResponse:
        return self._model(self._entry(task_id).model_id).v05(layout.SUMMARY_FILE, m.SummaryResponse)

    # ---------------------------------------------------------- contract v0.6.2

    def explanation(self, model_id: str) -> m.ModelExplanation:
        h = self._model(model_id)  # an unknown model is a 404 before any file is looked for
        path = self.explanations_dir / f"{model_id}.json"
        if not path.is_file():
            raise NotFound(f"{model_id} has no explanation (write it with: make explain MODEL_ID={model_id})")
        loaded = m.ModelExplanation.model_validate_json(path.read_text(encoding="utf-8"))
        return loaded.model_copy(update={"synthetic": h.synthetic or loaded.synthetic})

    # -------------------------------------------------------------------- series

    def series_for(
        self, task_id: str, entity_id: str, start: datetime | None, end: datetime | None,
        cursor: datetime | None = None,
    ) -> m.SeriesResponse:
        entry = self._entry(task_id)
        h = self._model(entry.model_id)
        if entity_id not in h.entity_ids:
            raise NotFound(f"no series for {task_id}/{entity_id}")
        if entity_id in h.unmodelled_ids:
            raise NotFound(f"{entity_id} has no model for {task_id} (not_modelled): there is no series")
        where, params = ["entity_id = ?"], [str(h.path / layout.PREDICTIONS_FILE), entity_id]
        lower = max([t for t in (start, cursor) if t is not None], default=None)
        if lower is not None:
            where.append("issued_at_utc >= ?")
            params.append(lower)
        if end is not None:
            where.append("issued_at_utc < ?")
            params.append(end)
        labels = ", observed_label, prediction_label" if h.classifier else ""
        rows = self._query(
            f"SELECT issued_at_utc, valid_at_utc, observed, prediction, missing_reason{labels} FROM read_parquet(?) "
            f"WHERE {' AND '.join(where)} ORDER BY issued_at_utc LIMIT {SERIES_MAX_POINTS + 1}",
            params,
        )
        next_cursor = None
        if len(rows) > SERIES_MAX_POINTS:
            next_cursor = _utc(rows[-1][0]).isoformat().replace("+00:00", "Z")
            rows = rows[:SERIES_MAX_POINTS]
        # Fast path: one validated object per point is what made a full range cost ~0.5 s. The rows come from our own
        # predictions.parquet (typed, checked when it was published), so the points are built without per-point
        # validation, but the two invariants SeriesPoint/SeriesResponse enforce are checked here: valid - issued ==
        # horizon, and a prediction (or label) xor a missing_reason. tests/api compares this with the validated model.
        horizon = timedelta(hours=entry.horizon_hours)
        no_prediction = m.MissingReason.PREDICTION_UNAVAILABLE
        points = []
        for issued, valid, observed, prediction, reason, *classes in rows:
            observed_label, predicted_label = classes or (None, None)
            # a class index is never a number here: classifiers publish a null prediction and a label
            answered = prediction is not None or predicted_label is not None
            if valid - issued != horizon:
                raise ValueError(f"{task_id}/{entity_id}: valid_at - issued_at differs from horizon_hours")
            points.append(m.SeriesPoint.model_construct(
                issued_at_utc=_utc(issued), valid_at_utc=_utc(valid), observed=observed, prediction=prediction,
                observed_label=observed_label, predicted_label=predicted_label,
                missing_reason=None if answered else (m.MissingReason(reason) if reason else no_prediction),
                quality=_NO_ISSUES,
            ))
        return m.SeriesResponse.model_construct(
            schema_version=m.SCHEMA_VERSION, data_version=h.data_version, synthetic=h.synthetic, task_id=task_id,
            entity_id=entity_id, model_id=h.model_id, target=entry.target, unit=entry.unit,
            horizon_hours=entry.horizon_hours, points=points, next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------ rule map

    def rule_map(
        self, model_id: str, rule_id: str, metric: m.RuleMapMetric,
        time: datetime | None, start: datetime | None, end: datetime | None, tau: float | None,
    ) -> m.RuleMapResponse:
        h = self._model(model_id)
        if rule_id not in h.rule_ids:
            raise NotFound(f"unknown rule_id {rule_id} for {model_id}")
        instant = metric == m.RuleMapMetric.FIRING_STRENGTH
        lo, hi = (time, time + _MICROSECOND) if instant else (start, end)  # [t, t+1us) is the instant t
        key = (h.model_id, h.data_version, h.token, rule_id, metric.value, time, start, end, tau)
        return self._cached(key, lambda: self._compute_rule_map(h, rule_id, metric, instant, lo, hi, tau))

    def _compute_rule_map(self, h, rule_id, metric, instant, lo, hi, tau) -> m.RuleMapResponse:
        files = self._files(h, layout.ACTIVATIONS_DIR, lo, hi)
        stats = {}
        if files:
            rows = self._query(
                "WITH r AS (SELECT entity_id, firing_strength AS f, "
                "(firing_strength IS NOT NULL AND NOT isnan(firing_strength)) AS ok FROM read_parquet(?) "
                "WHERE rule_id = ? AND issued_at_utc >= ? AND issued_at_utc < ?) "
                "SELECT entity_id, count(*), count(*) FILTER (WHERE ok), avg(f) FILTER (WHERE ok), "
                "count(*) FILTER (WHERE ok AND f >= ?) FROM r GROUP BY entity_id",
                [files, rule_id, lo, hi, tau if tau is not None else 0.0],
            )
            stats = {r[0]: r[1:] for r in rows}
        features = []
        for entity in h.entities.features:
            eid = entity.properties.entity_id
            n_records, n_valid, mean, n_over = stats.get(eid, (0, 0, None, 0))
            quality = m.Quality()
            if entity.properties.modelled is False:
                value, reason = None, m.MissingReason.NOT_MODELLED
            elif n_valid:
                value = n_over / n_valid if metric == m.RuleMapMetric.ACTIVATION_FREQUENCY else mean
                value, reason = min(1.0, max(0.0, float(value))), None
            elif n_records:
                value, reason = None, m.MissingReason.MISSING_INPUT
                quality = m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input"])
            else:
                value, reason = None, m.MissingReason.NO_OBSERVATION
            features.append(m.RuleMapFeature(
                type="Feature", id=eid, geometry=entity.geometry,
                properties=m.RuleMapProperties(
                    entity_id=eid, rule_id=rule_id, metric=metric, value=value, n_valid=n_valid,
                    time_from_utc=lo, time_to_utc=lo if instant else hi,
                    issued_at_utc=lo if instant else None,
                    valid_at_utc=lo + h.horizon if instant and n_records else None,
                    tau=tau, model_id=h.model_id, data_version=h.data_version,
                    geometry_support=entity.properties.geometry_support, missing_reason=reason, quality=quality,
                ),
            ))
        return m.RuleMapResponse(
            type="FeatureCollection", data_version=h.data_version, synthetic=h.synthetic, model_id=h.model_id,
            rule_id=rule_id, metric=metric, tau=tau, time_from_utc=lo, time_to_utc=lo if instant else hi,
            features=features,
        )

    # ---------------------------------------------------------------- rule trace

    def _published_row(self, h: _Published, entity_id: str, at: datetime) -> dict | None:
        """The row of ``predictions.parquet`` at (entity, issue time): its observed target and published label."""
        labels = ", observed_label, prediction_label" if h.classifier else ""
        rows = self._query(
            f"SELECT observed, missing_reason{labels} FROM read_parquet(?) WHERE entity_id = ? AND issued_at_utc = ?",
            [str(h.path / layout.PREDICTIONS_FILE), entity_id, at],
        )
        if not rows:
            return None
        observed, reason, *classes = rows[0]
        observed_label, prediction_label = classes or (None, None)
        return {"observed": observed, "observed_label": observed_label, "prediction_label": prediction_label,
                "missing_reason": reason}

    def rule_trace(self, model_id: str, entity_id: str, at: datetime) -> m.RuleTrace:
        h = self._model(model_id)
        if entity_id not in h.entity_ids:
            raise NotFound(f"unknown entity {entity_id} for {model_id}")
        if entity_id in h.unmodelled_ids:
            return unmodelled.not_modelled_trace(
                inference=h.rules.inference, model_id=h.model_id, task_id=h.task_id, entity_id=entity_id, at=_utc(at),
                horizon_hours=h.card.manifest.horizon_hours, target_unit=h.target_unit,
                data_version=h.data_version, synthetic=h.synthetic,
            )
        with self._db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM read_parquet(?) WHERE entity_id = ? AND issued_at_utc = ?",
                [str(h.path / layout.INPUTS_FILE), entity_id, at],
            ).df()
        if row.empty:
            raise NotFound(f"no trace for {entity_id} at {at.isoformat()}")
        return self._trace(h, entity_id, at, row[h.features], self._published_row(h, entity_id, at))

    def _trace(self, h: _Published, entity_id: str, at: datetime, X: pd.DataFrame, published: dict | None):
        """The engine's trace of one input row, with the provenance of the published row."""
        from atlas.explain import build_classifier_traces, build_mixture_traces, build_rule_traces

        build = build_mixture_traces if h.mixture else build_classifier_traces if h.classifier else build_rule_traces
        extra = {"class_labels": h.class_labels} if h.classifier else {}
        trace = build(
            h.model, X, [entity_id], [at], model_id=h.model_id, task_id=h.task_id,
            horizon_hours=h.card.manifest.horizon_hours, target_unit=h.target_unit, data_version=h.data_version,
            synthetic=h.synthetic, feature_units={f: s.unit for f, s in h.spec.features.items() if s.unit}, **extra,
        )[0]
        if h.classifier and trace.prediction.label is not None and self._no_reference(published):
            trace = self._without_reference(trace)
        values = []
        for fv in trace.feature_values:
            source = h.spec.features[fv.feature]
            observed_at = None if fv.value is None else _utc(at) - timedelta(hours=source.lag_hours)
            values.append(fv.model_copy(update={"source_id": source.source_id, "observed_at_utc": observed_at}))
        update = {"feature_values": values}
        if published is not None:
            update.update(observed=published["observed"], observed_label=published["observed_label"])
        # re-validate: the contract rejects an observed_at_utc after issued_at_utc
        return m.RuleTrace.model_validate(trace.model_copy(update=update).model_dump())

    @staticmethod
    def _no_reference(published: dict | None) -> bool:
        """True when the published row withholds its label: the target has no reference level ("sin referencia").

        The engine still returns a class for such a row (its inputs are fine), but the series publishes none, so the
        trace must agree with the series.
        """
        return (published is not None and published["prediction_label"] is None
                and published["missing_reason"] == m.MissingReason.PREDICTION_UNAVAILABLE.value)

    @staticmethod
    def _without_reference(trace: m.RuleTrace) -> m.RuleTrace:
        """Same engine rule firings and associations (or, for a mixture, contributions and scores), but no class: the
        label goes with its winning rule or top rule."""
        prediction = trace.prediction.model_copy(update={
            "label": None, "winning_rule_id": None, "top_rule_id": None, "top_rule_share": None,
            "missing_reason": m.MissingReason.PREDICTION_UNAVAILABLE})
        quality = m.Quality(status=m.QualityStatus.WARNING, warnings=[
            *trace.quality.warnings,
            "no reference level for this row: no class is published; the rule firings and "
            + ("class scores" if trace.prediction.class_scores is not None else "associations")
            + " below are the engine's own outputs",
        ])
        return trace.model_copy(update={"prediction": prediction, "quality": quality})

    # ------------------------------------------------- v0.4: predictions and observations

    def _rows_at(self, h: _Published, sql_from: str, columns: str, params: list, time, start, end) -> dict[str, tuple]:
        """Per entity, the row at ``time`` or the latest in ``[start, end)``; ``sql_from`` aliases the table ``t``."""
        if time is not None:
            where, extra = "t.issued_at_utc = ?", [time]
        else:
            where, extra = "t.issued_at_utc >= ? AND t.issued_at_utc < ?", [start, end]
        rows = self._query(
            f"SELECT t.entity_id, t.issued_at_utc, {columns} FROM {sql_from} WHERE {where} "
            "QUALIFY row_number() OVER (PARTITION BY t.entity_id ORDER BY t.issued_at_utc DESC) = 1",
            [*params, *extra],
        )
        return {row[0]: row[1:] for row in rows}

    @staticmethod
    def _query_bounds(time, start, end) -> dict:
        if time is not None:
            return {"issued_at_utc": time}
        return {"time_from_utc": start, "time_to_utc": end}

    def _deciding_rules(self, h: _Published, answered: dict[str, datetime]) -> dict[str, str]:
        """``decided_by_rule_id`` by entity, for the answered predictions ``{entity_id: issued_at_utc}``.

        The measure of ``/importance``: the winning rule of a classifier (the ``is_winner`` firing record), or for
        the additive TSK the rule with the largest ``effective_firing / sum`` (``importance.deciding_rows``). An entity
        whose (entity, issue time) has no deciding record (no rule fired) is left out. Reads only the firing records of
        the answered (entity, issue time) pairs.
        """
        if not h.decides or not answered:
            return {}
        lo, hi = min(answered.values()), max(answered.values()) + _MICROSECOND
        files = self._files(h, layout.ACTIVATIONS_DIR, lo, hi)
        if not files:
            return {}
        want = pd.DataFrame({"entity_id": list(answered), "issued_at_utc": pd.DatetimeIndex(list(answered.values()))})
        columns, where = ("a.rule_id", "AND a.is_winner") if h.classifier else ("a.rule_id, a.effective_firing", "")
        with self._db.cursor() as cur:
            cur.register("want", want)
            frame = cur.execute(
                f"SELECT a.entity_id, a.issued_at_utc, {columns} FROM read_parquet(?) a "
                "JOIN want w ON w.entity_id = a.entity_id AND w.issued_at_utc = a.issued_at_utc "
                f"WHERE a.issued_at_utc >= ? AND a.issued_at_utc < ? {where}"
                + ("" if h.classifier else " AND a.effective_firing IS NOT NULL"),
                [files, lo, hi],
            ).df()
        if frame.empty:
            return {}
        if h.classifier:  # one winner per answered prediction (checked when importance.json was computed)
            return dict(zip(frame["entity_id"], frame["rule_id"], strict=True))
        covered = importance.weight_shares(frame, h.position)
        decided = importance.deciding_rows(frame[covered])
        return dict(zip(decided["entity_id"], decided["rule_id"], strict=True))

    def predictions(
        self, task_id: str, time: datetime | None, start: datetime | None, end: datetime | None,
    ) -> m.PredictionsResponse:
        entry = self._entry(task_id)
        h = self._model(entry.model_id)
        labels = ", t.observed_label, t.prediction_label" if h.classifier else ""
        top = ", t.top_rule_id, t.top_rule_share" if h.mixture else ""  # v0.7: the rule that supports it the most
        rows = self._rows_at(
            h, "read_parquet(?) t", f"t.valid_at_utc, t.prediction, t.observed, t.missing_reason{labels}{top}",
            [str(h.path / layout.PREDICTIONS_FILE)], time, start, end,
        )
        tops = {eid: row[-2:] for eid, row in rows.items()} if h.mixture else {}
        if h.mixture:
            rows = {eid: row[:-2] for eid, row in rows.items()}
        # rows[eid] = (issued, valid, prediction, observed, reason[, observed_label, prediction_label])
        answered_at = {eid: row[0] for eid, row in rows.items()
                       if row[2] is not None or (h.classifier and row[-1] is not None)}
        decided = self._deciding_rules(h, answered_at)
        features = []
        for entity in h.entities.features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=h.model_id, data_version=h.data_version, unit=entry.unit,
                          geometry_support=props.geometry_support)
            if props.modelled is False:
                body = dict(issued_at_utc=None, valid_at_utc=None, prediction=None,
                            missing_reason=m.MissingReason.NOT_MODELLED)
            elif eid not in rows:
                body = dict(issued_at_utc=None, valid_at_utc=None, prediction=None,
                            missing_reason=m.MissingReason.NO_OBSERVATION)
            else:
                issued, valid, prediction, observed, reason, *classes = rows[eid]
                observed_label, predicted_label = classes or (None, None)
                answered_row = prediction is not None or predicted_label is not None
                body = dict(
                    issued_at_utc=_utc(issued), valid_at_utc=_utc(valid), prediction=prediction,
                    prediction_label=predicted_label, observed=observed, observed_label=observed_label,
                    missing_reason=None if answered_row else (
                        m.MissingReason(reason) if reason else m.MissingReason.PREDICTION_UNAVAILABLE),
                    decided_by_rule_id=decided.get(eid),
                )
                if h.mixture and predicted_label is not None and tops[eid][0] is not None:
                    body.update(top_rule_id=tops[eid][0], top_rule_share=float(tops[eid][1]))
            features.append(m.PredictionFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.PredictionProperties(**common, **body),
            ))
        return m.PredictionsResponse(
            type="FeatureCollection", data_version=h.data_version, synthetic=h.synthetic, task_id=task_id,
            model_id=h.model_id, task_type=entry.task_type, target=entry.target, unit=entry.unit,
            horizon_hours=entry.horizon_hours, features=features, **self._query_bounds(time, start, end),
        )

    def observations(
        self, task_id: str, time: datetime | None, start: datetime | None, end: datetime | None,
    ) -> m.ObservationsResponse:
        entry = self._entry(task_id)
        h = self._model(entry.model_id)
        names = list(h.features)
        label = ", p.observed_label" if h.classifier else ""
        columns = "p.valid_at_utc, p.observed" + label + "".join(f', t."{n}"' for n in names)
        sql_from = ("read_parquet(?) t JOIN read_parquet(?) p "
                    "ON p.entity_id = t.entity_id AND p.issued_at_utc = t.issued_at_utc")
        rows = self._rows_at(
            h, sql_from, columns, [str(h.path / layout.INPUTS_FILE), str(h.path / layout.PREDICTIONS_FILE)],
            time, start, end,
        )
        features = []
        for entity in h.entities.features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=h.model_id, data_version=h.data_version,
                          geometry_support=props.geometry_support)
            if props.modelled is False:
                body = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[],
                            missing_reason=m.MissingReason.NOT_MODELLED)
            elif eid not in rows:
                body = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[],
                            missing_reason=m.MissingReason.NO_OBSERVATION)
            else:
                issued, valid, observed, *rest = rows[eid]
                observed_label, values = (rest[0], rest[1:]) if h.classifier else (None, rest)
                issued, valid = _utc(issued), _utc(valid)
                inputs = []
                for name, value in zip(names, values, strict=True):
                    source = h.spec.features[name]
                    inputs.append(m.FeatureValue(
                        feature=name, value=value, unit=source.unit, source_id=source.source_id,
                        observed_at_utc=None if value is None else issued - timedelta(hours=source.lag_hours),
                        missing_reason=m.MissingReason.NO_OBSERVATION if value is None else None,
                    ))
                missing = [fv.feature for fv in inputs if fv.value is None]
                body = dict(
                    issued_at_utc=issued, valid_at_utc=valid, target_label=observed_label, inputs=inputs,
                    target=m.FeatureValue(
                        feature=entry.target, value=observed, unit=entry.unit, observed_at_utc=valid,
                        missing_reason=None if observed is not None else m.MissingReason.NO_OBSERVATION),
                    quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)])
                    if missing else m.Quality(),
                )
            features.append(m.ObservationFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.ObservationProperties(**common, **body),
            ))
        return m.ObservationsResponse(
            type="FeatureCollection", data_version=h.data_version, synthetic=h.synthetic, task_id=task_id,
            model_id=h.model_id, target=entry.target, unit=entry.unit, horizon_hours=entry.horizon_hours,
            features=features, **self._query_bounds(time, start, end),
        )

    # --------------------------------------------------- v0.4: territories and stories

    def _cached(self, key: tuple, compute):
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        value = compute()
        size = approx_bytes(value)  # outside the lock: serialising a 0.5 MiB map takes a few ms
        with self._lock:
            self._cache.put(key, value, size)
        return value

    def rule_territories(
        self, model_id: str, start: datetime, end: datetime, measure: m.TerritoryMeasure, tau: float,
    ) -> m.RuleTerritoriesResponse:
        h = self._model(model_id)
        if measure == m.TerritoryMeasure.WINNER_SHARE and not h.winning_rule:
            raise BadRequest("winner_share only exists for winning-rule classifiers (in a mixture of rules no rule "
                             "decides alone); use mean_activation or activation_frequency")
        key = ("territories", h.model_id, h.data_version, h.token, measure.value, tau, start, end)
        return self._cached(key, lambda: territories.build_territories(
            model_id=h.model_id, data_version=h.data_version, synthetic=h.synthetic, family=h.rules.inference.family,
            rule_ids=h.rule_order, entities=h.entities.features, stats=self._territory_stats(h, start, end, tau),
            measure=measure, tau=tau, start=start, end=end,
        ))

    def _territory_stats(self, h: _Published, lo: datetime, hi: datetime, tau: float) -> pd.DataFrame:
        files = self._files(h, layout.ACTIVATIONS_DIR, lo, hi)
        if not files:
            return territories.empty_stats()
        wins = "count(*) FILTER (WHERE ok AND is_winner)" if h.winning_rule else "0"
        extra = ", is_winner" if h.winning_rule else ""
        rows = self._query(
            "WITH r AS (SELECT entity_id, rule_id, firing_strength AS f, "
            f"(firing_strength IS NOT NULL AND NOT isnan(firing_strength)) AS ok{extra} FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ?) "
            "SELECT entity_id, rule_id, count(*), count(*) FILTER (WHERE ok), coalesce(sum(f) FILTER (WHERE ok), 0), "
            f"count(*) FILTER (WHERE ok AND f >= ?), {wins} FROM r GROUP BY entity_id, rule_id",
            [files, lo, hi, tau],
        )
        return pd.DataFrame(rows, columns=territories.STATS_COLUMNS)

    def _step_stats(self, h: _Published, lo: datetime, hi: datetime, tau: float) -> pd.DataFrame:
        files = self._files(h, layout.ACTIVATIONS_DIR, lo, hi)
        if not files:
            return pd.DataFrame(columns=stories.STEP_COLUMNS)
        rows = self._query(
            "WITH r AS (SELECT rule_id, issued_at_utc, firing_strength AS f, "
            "(firing_strength IS NOT NULL AND NOT isnan(firing_strength)) AS ok FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ?) "
            "SELECT rule_id, issued_at_utc, count(*) FILTER (WHERE ok), count(*) FILTER (WHERE ok AND f >= ?) "
            "FROM r GROUP BY rule_id, issued_at_utc",
            [files, lo, hi, tau],
        )
        frame = pd.DataFrame(rows, columns=stories.STEP_COLUMNS)
        frame["issued_at_utc"] = pd.to_datetime(frame["issued_at_utc"], utc=True)
        return frame

    def rule_stories(self, model_id: str, start: datetime, end: datetime, tau: float, limit: int):
        h = self._model(model_id)
        coverage = h.card.coverage
        regular = coverage is None or coverage.regular
        key = ("stories", h.model_id, h.data_version, h.token, tau, limit, start, end)

        def compute():
            return stories.build_stories(
                model_id=h.model_id, data_version=h.data_version, synthetic=h.synthetic, domain=h.rules.domain,
                rule_ids=h.rule_order,
                territories=self.rule_territories(model_id, start, end, m.TerritoryMeasure.MEAN_ACTIVATION, tau),
                step_stats=self._step_stats(h, start, end, tau) if regular else None,
                step_hours=coverage.step_hours if coverage else 1,
                entity_names={f.properties.entity_id: f.properties.name or f.properties.entity_id
                              for f in h.entities.features},
                start=start, end=end, tau=tau, limit=limit,
            )

        return self._cached(key, compute)

    # --------------------------------------------------------------- v0.4: what-if

    def scenario(self, request: m.ScenarioRequest) -> m.ScenarioResponse:
        h = self._model(request.model_id)
        if request.entity_id not in h.entity_ids:
            raise NotFound(f"unknown entity {request.entity_id} for {request.model_id}")
        if request.entity_id in h.unmodelled_ids:
            raise BadRequest(f"{request.entity_id} has no model (not_modelled): there is no row to modify")
        at = _utc(request.at)
        original = self.rule_trace(request.model_id, request.entity_id, at)
        published = self._published_row(h, request.entity_id, at)

        def rerun(values: dict[str, float | None]) -> m.RuleTrace:
            X = pd.DataFrame([{name: float("nan") if v is None else v for name, v in values.items()}])
            return self._trace(h, request.entity_id, at, X[h.features], published)

        try:
            return scenarios.build_scenario(request, h.rules, original, rerun)
        except scenarios.ScenarioError as exc:
            raise BadRequest(str(exc)) from exc
