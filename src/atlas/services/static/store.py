"""Reference builder: the API's ``Store`` answered from an export directory (docs/static_export.md section 10).

This is the executable form of the spec and what the exporter's self-check compares with ``ArtifactStore``. It reads
only the exported ``*.json.gz`` files, runs no ex_fuzzy and no Parquet query; it reshapes, selects, sums and multiplies.
The web's TypeScript builder is a port of it.
"""

from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from atlas.contracts import models as m
from atlas.services import layout, scenarios, territories, unmodelled
from atlas.services.static import fmt
from atlas_api.artifact_store import ArtifactStore
from atlas_api.store import BadRequest, NotFound, served_task

_NO_ISSUES = m.Quality()
_MICROSECOND = timedelta(microseconds=1)
_NO_V05 = ("{model_id} has no {name}: it was published before contract v0.5 "
           "(republish it, or run python -m atlas.services.enrich)")
COVERAGE_EPSILON = 1e-10  # ex_fuzzy sums firings above this to avoid dividing by ~0 (TSK fallback)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


class Reader:
    """Decoded JSON files with a small LRU (the browser's loader keeps ~50 MB the same way)."""

    def __init__(self, root: Path, capacity: int = 48):
        self.root, self.capacity = Path(root), capacity
        self._cache: OrderedDict[str, object] = OrderedDict()

    def get(self, rel: str):
        """The decoded file, or ``None`` when it does not exist."""
        if rel in self._cache:
            self._cache.move_to_end(rel)
            return self._cache[rel]
        path = self.root / rel
        value = json.loads(fmt.unzip(path.read_bytes())) if path.is_file() else None
        self._cache[rel] = value
        while len(self._cache) > self.capacity:
            self._cache.popitem(last=False)
        return value


class _Shard:
    """A pred shard with its row lookups."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.ti, self.ei = doc["ti"], doc["ei"]
        self.by_time: dict[int, list[int]] = defaultdict(list)
        self.row_of: dict[tuple[int, int], int] = {}
        for i, (t, e) in enumerate(zip(self.ti, self.ei, strict=True)):
            self.by_time[t].append(i)
            self.row_of[(t, e)] = i
        self.t_index = {t: k for k, t in enumerate(doc["t"])}

    def col(self, name: str, i: int):
        column = self.doc.get(name)
        return None if column is None else column[i]


class _Model:
    def __init__(self, store: StaticStore, model_id: str):
        r = store.reader
        meta = r.get(f"models/{model_id}/meta.json.gz")
        if meta is None:
            raise NotFound(f"unknown model_id {model_id}")
        self.meta, self.model_id = meta, model_id
        self.rules = m.ModelRules.model_validate(r.get(f"models/{model_id}/rules.json.gz"))
        self.task_id = meta["task_id"]
        self.entities = m.EntityCollection.model_validate(r.get(f"tasks/{self.task_id}/entities.json.gz"))
        self.e_index = {e: i for i, e in enumerate(meta["entities"])}
        self.entity_ids = {f.properties.entity_id for f in self.entities.features}
        self.unmodelled_ids = {f.properties.entity_id for f in self.entities.features if f.properties.modelled is False}
        self.data_version, self.synthetic = meta["data_version"], meta["synthetic"]
        self.horizon = timedelta(hours=meta["horizon_hours"])
        self.classes, self.rule_order = meta["classes"], meta["rules"]
        self.classifier = meta["task_type"] == "classification"
        self.winning = meta["family"] == m.InferenceFamily.WINNING_RULE_CLASSIFIER.value
        self.mixture = meta["mixture"]
        self.decides = meta["decides"]
        self.regular = meta["regular"]
        self.pair_index = {tuple(p): i for i, p in enumerate(meta["mem_pairs"])}
        self.feature_meta = {f["name"]: f for f in meta["features"]}
        self.rule_defs = {r.rule_id: r for r in self.rules.rules}
        self.taus = meta["taus"]
        self.trace_features = meta["antecedent_order"]
        self.inference = m.InferenceSpec.model_validate(meta["inference"])  # as a trace reports it (engine version)


class StaticStore:
    """``atlas_api.store.Store`` over an export directory (``<out>/data/<export_id>``)."""

    mode = "static"

    def __init__(self, data_dir: Path, *, cache: int = 48):
        self.reader = Reader(data_dir, cache)
        self._models: dict[str, _Model] = {}
        domains = self.reader.get("domains.json.gz")
        if domains is None:
            raise FileNotFoundError(f"{data_dir} is not a static export (no domains.json.gz)")
        self._domains = m.DomainsResponse.model_validate(domains)
        self._tasks = {t.task_id: (d.domain, t) for d in self._domains.domains for t in d.tasks}

    # ------------------------------------------------------------------ plumbing
    def _model(self, model_id: str) -> _Model:
        if "/" in model_id or model_id.startswith("."):
            raise NotFound(f"unknown model_id {model_id}")
        if model_id not in self._models:
            self._models[model_id] = _Model(self, model_id)
        return self._models[model_id]

    def _task(self, task_id: str) -> m.TaskInfo:
        if task_id not in self._tasks:
            raise NotFound(f"unknown task_id {task_id}")
        return self._tasks[task_id][1]

    def _exact(self, rel: str, cls, what: str):
        body = self.reader.get(rel)
        if body is None:
            raise NotFound(what)
        return cls.model_validate(body)

    # ------------------------------------------------------------------ exact bodies
    def domains(self) -> m.DomainsResponse:
        return self._domains

    def entity_collection(self, domain: m.Domain, task_id: str | None = None) -> m.EntityCollection:
        chosen = served_task({t: d for t, (d, _) in self._tasks.items()}, domain, task_id)
        if chosen is None:
            raise NotFound(f"no entities for domain {domain.value}")
        return self._exact(f"tasks/{chosen}/entities.json.gz", m.EntityCollection,
                           f"no entities for domain {domain.value}")

    def model_card(self, model_id: str) -> m.ModelCard:
        self._model(model_id)
        return self._exact(f"models/{model_id}/card.json.gz", m.ModelCard, f"unknown model_id {model_id}")

    def model_rules(self, model_id: str) -> m.ModelRules:
        return self._model(model_id).rules

    def importance(self, model_id: str) -> m.RuleImportanceResponse:
        self._model(model_id)
        return self._exact(f"models/{model_id}/importance.json.gz", m.RuleImportanceResponse, _NO_V05.format(
            model_id=model_id, name=layout.IMPORTANCE_FILE))

    def summary(self, task_id: str) -> m.SummaryResponse:
        model_id = self._task(task_id).model_id
        return self._exact(f"tasks/{task_id}/summary.json.gz", m.SummaryResponse, _NO_V05.format(
            model_id=model_id, name=layout.SUMMARY_FILE))

    def explanation(self, model_id: str) -> m.ModelExplanation:
        self._model(model_id)
        return self._exact(f"models/{model_id}/explanation.json.gz", m.ModelExplanation,
                           f"{model_id} has no explanation (write it with: make explain MODEL_ID={model_id})")

    # ------------------------------------------------------------------ shards
    def _keys_between(self, M: _Model, lo: datetime, hi: datetime) -> list[str]:
        """Shard keys that can hold issue times in ``[lo, hi)``."""
        if not M.regular:
            return ["all"]
        first = fmt.utc_midnight(fmt.day_key(lo))
        last = fmt.utc_midnight(fmt.day_key(hi - _MICROSECOND))
        keys, d = [], first
        while d <= last:
            keys.append(fmt.day_key(d))
            d += fmt.DAY
        return [k for k in keys if k in set(M.meta["keys"])]

    def _shard(self, M: _Model, key: str) -> _Shard | None:
        doc = self.reader.get(f"models/{M.model_id}/{key}/pred.json.gz")
        if doc is None:
            return None
        cached = self.reader._cache.get(f"shard::{M.model_id}/{key}")
        if cached is None:
            cached = _Shard(doc)
            self.reader._cache[f"shard::{M.model_id}/{key}"] = cached
        return cached

    def _key_of(self, M: _Model, at: datetime) -> str:
        return fmt.day_key(at) if M.regular else "all"

    def _rows_at(self, M: _Model, time, start, end) -> dict[str, tuple[_Shard, int, datetime]]:
        """Per entity, the row at ``time`` or the latest in ``[start, end)``: (shard, row, issue time)."""
        found: dict[str, tuple[_Shard, int, datetime]] = {}
        ids = M.meta["entities"]
        if time is not None:
            shard = self._shard(M, self._key_of(M, time))
            k = shard.t_index.get(fmt.iso(time)) if shard else None
            if k is not None:
                for i in shard.by_time[k]:
                    found[ids[shard.ei[i]]] = (shard, i, time)
            return found
        for key in self._keys_between(M, start, end):
            shard = self._shard(M, key)
            if shard is None:
                continue
            for k, t_iso in enumerate(shard.doc["t"]):
                t = fmt.parse_iso(t_iso)
                if not start <= t < end:
                    continue
                for i in shard.by_time[k]:
                    eid = ids[shard.ei[i]]
                    if eid not in found or found[eid][2] <= t:
                        found[eid] = (shard, i, t)
        return found

    @staticmethod
    def _bounds(time, start, end) -> dict:
        return {"issued_at_utc": time} if time is not None else {"time_from_utc": start, "time_to_utc": end}

    def _reason(self, shard: _Shard, i: int):
        code = shard.col("reason", i)
        return None if code is None else m.MissingReason(fmt.MISSING_REASONS[code])

    # ------------------------------------------------------------------ predictions / observations
    def predictions(self, task_id, time, start, end) -> m.PredictionsResponse:
        entry = self._task(task_id)
        M = self._model(entry.model_id)
        rows = self._rows_at(M, time, start, end)
        features = []
        for entity in M.entities.features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=M.model_id, data_version=M.data_version, unit=entry.unit,
                          geometry_support=props.geometry_support)
            if props.modelled is False:
                body = dict(issued_at_utc=None, valid_at_utc=None, prediction=None,
                            missing_reason=m.MissingReason.NOT_MODELLED)
            elif eid not in rows:
                body = dict(issued_at_utc=None, valid_at_utc=None, prediction=None,
                            missing_reason=m.MissingReason.NO_OBSERVATION)
            else:
                shard, i, t = rows[eid]
                plabel, olabel = shard.col("plabel", i), shard.col("olabel", i)
                decided, top = shard.col("decided", i), shard.col("top", i)
                body = dict(
                    issued_at_utc=t, valid_at_utc=t + M.horizon, prediction=shard.col("pred", i),
                    prediction_label=None if plabel is None else M.classes[plabel], observed=shard.col("obs", i),
                    observed_label=None if olabel is None else M.classes[olabel], missing_reason=self._reason(shard, i),
                    decided_by_rule_id=None if decided is None else M.rule_order[decided])
                if M.mixture and plabel is not None and top is not None:
                    body.update(top_rule_id=M.rule_order[top], top_rule_share=float(shard.col("tshare", i)))
            features.append(m.PredictionFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.PredictionProperties(**common, **body)))
        return m.PredictionsResponse(
            type="FeatureCollection", data_version=M.data_version, synthetic=M.synthetic, task_id=task_id,
            model_id=M.model_id, task_type=entry.task_type, target=entry.target, unit=entry.unit,
            horizon_hours=entry.horizon_hours, features=features, **self._bounds(time, start, end))

    def _input(self, M: _Model, feature: str, shard: _Shard, i: int, t: datetime):
        base = M.feature_meta[feature]["input"]
        if M.regular:
            doc = self.reader.get(f"{base}/{fmt.day_key(t)}.json.gz")
            if doc is None:
                return None
            return doc["values"][_utc(t).hour * len(M.meta["entities"]) + shard.ei[i]]
        doc = self.reader.get(f"{base}/all.json.gz")
        return None if doc is None else doc["values"][i]

    def observations(self, task_id, time, start, end) -> m.ObservationsResponse:
        entry = self._task(task_id)
        M = self._model(entry.model_id)
        rows = self._rows_at(M, time, start, end)
        features = []
        for entity in M.entities.features:
            props = entity.properties
            eid = props.entity_id
            common = dict(entity_id=eid, model_id=M.model_id, data_version=M.data_version,
                          geometry_support=props.geometry_support)
            if props.modelled is False:
                body = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[],
                            missing_reason=m.MissingReason.NOT_MODELLED)
            elif eid not in rows:
                body = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[],
                            missing_reason=m.MissingReason.NO_OBSERVATION)
            else:
                shard, i, t = rows[eid]
                olabel, observed = shard.col("olabel", i), shard.col("obs", i)
                inputs = []
                for f in M.meta["features"]:
                    value = self._input(M, f["name"], shard, i, t)
                    inputs.append(m.FeatureValue(
                        feature=f["name"], value=value, unit=f["obs_unit"], source_id=f["source_id"],
                        observed_at_utc=None if value is None else t - timedelta(hours=f["lag_hours"]),
                        missing_reason=m.MissingReason.NO_OBSERVATION if value is None else None))
                missing = [fv.feature for fv in inputs if fv.value is None]
                body = dict(
                    issued_at_utc=t, valid_at_utc=t + M.horizon, inputs=inputs,
                    target_label=None if olabel is None else M.classes[olabel],
                    target=m.FeatureValue(
                        feature=entry.target, value=observed, unit=entry.unit, observed_at_utc=t + M.horizon,
                        missing_reason=None if observed is not None else m.MissingReason.NO_OBSERVATION),
                    quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)])
                    if missing else m.Quality())
            features.append(m.ObservationFeature(
                type="Feature", id=eid, geometry=entity.geometry, properties=m.ObservationProperties(**common, **body)))
        return m.ObservationsResponse(
            type="FeatureCollection", data_version=M.data_version, synthetic=M.synthetic, task_id=task_id,
            model_id=M.model_id, target=entry.target, unit=entry.unit, horizon_hours=entry.horizon_hours,
            features=features, **self._bounds(time, start, end))

    # ------------------------------------------------------------------ series
    def series_for(self, task_id, entity_id, start, end, cursor=None) -> m.SeriesResponse:
        entry = self._task(task_id)
        M = self._model(entry.model_id)
        if entity_id not in M.entity_ids:
            raise NotFound(f"no series for {task_id}/{entity_id}")
        if entity_id in M.unmodelled_ids:
            raise NotFound(f"{entity_id} has no model for {task_id} (not_modelled): there is no series")
        e = M.e_index[entity_id]
        lower = max([t for t in (start, cursor) if t is not None], default=None)
        cov_lo, cov_hi = fmt.parse_iso(M.meta["coverage"]["from"]), fmt.parse_iso(M.meta["coverage"]["to"])
        keys = self._keys_between(M, lower or cov_lo, end or cov_hi + fmt.DAY)
        points = []
        for key in keys:
            shard = self._shard(M, key)
            if shard is None:
                continue
            for i in range(len(shard.ti)):
                if shard.ei[i] != e:
                    continue
                t = fmt.parse_iso(shard.doc["t"][shard.ti[i]])
                if (lower is not None and t < lower) or (end is not None and t >= end):
                    continue
                points.append((t, shard, i))
        points.sort(key=lambda p: p[0])
        next_cursor = None
        if len(points) > fmt.SERIES_MAX_POINTS:
            next_cursor = fmt.iso(points[fmt.SERIES_MAX_POINTS][0])
            points = points[:fmt.SERIES_MAX_POINTS]
        out = []
        for t, shard, i in points:
            plabel, olabel = shard.col("plabel", i), shard.col("olabel", i)
            prediction = shard.col("pred", i)
            out.append(m.SeriesPoint.model_construct(
                issued_at_utc=t, valid_at_utc=t + M.horizon, observed=shard.col("obs", i), prediction=prediction,
                observed_label=None if olabel is None else M.classes[olabel],
                predicted_label=None if plabel is None else M.classes[plabel],
                missing_reason=self._reason(shard, i), quality=_NO_ISSUES))
        return m.SeriesResponse.model_construct(
            schema_version=m.SCHEMA_VERSION, data_version=M.data_version, synthetic=M.synthetic, task_id=task_id,
            entity_id=entity_id, model_id=M.model_id, target=entry.target, unit=entry.unit,
            horizon_hours=entry.horizon_hours, points=out, next_cursor=next_cursor)

    # ------------------------------------------------------------------ windows
    def _window_file(self, M: _Model, start: datetime, end: datetime) -> str:
        """The agg file of ``[start, end)`` or a 422: only the windows of docs section 8 are precomputed."""
        period = M.meta.get("period")
        c_lo, c_hi = None, None
        if period:  # inside a period the windows are the standard ones clipped to it (docs section 8)
            c_lo = fmt.parse_iso(M.meta["coverage"]["from"])
            c_hi = fmt.parse_iso(M.meta["coverage"]["to"]) + timedelta(hours=M.meta["step_hours"])
        for kind in fmt.WINDOW_KINDS:
            std = fmt.window_of(kind, start)
            if period:
                std_clipped = (max(std[0], c_lo), min(std[1], c_hi))
                if std_clipped == (start, end):
                    return f"models/{M.model_id}/agg/{kind}/{fmt.day_key(std[0])}.json.gz"
            elif std == (start, end):
                return f"models/{M.model_id}/agg/{kind}/{fmt.day_key(start)}.json.gz"
        if M.meta["windows"]["coverage"]:
            c = M.meta["coverage"]
            cov = fmt.coverage_window(fmt.parse_iso(c["from"]), fmt.parse_iso(c["to"]), M.meta["step_hours"])
            if cov == (start, end):
                return f"models/{M.model_id}/agg/coverage/all.json.gz"
        raise BadRequest("window not precomputed: use a UTC day, ISO week, month or year, or the whole coverage")

    def _tau_index(self, M: _Model, tau: float) -> int:
        for k, t in enumerate(M.taus):
            if fmt.close(t, tau):
                return k
        raise BadRequest(f"tau {tau:g} is not precomputed: use one of 0.05, 0.10, ..., 1.00")

    def _agg(self, M: _Model, start, end) -> dict | None:
        return self.reader.get(self._window_file(M, start, end))

    # ------------------------------------------------------------------ rule map
    def rule_map(self, model_id, rule_id, metric, time, start, end, tau) -> m.RuleMapResponse:
        M = self._model(model_id)
        if rule_id not in M.rule_defs:
            raise NotFound(f"unknown rule_id {rule_id} for {model_id}")
        r = M.rule_order.index(rule_id)
        instant = metric == m.RuleMapMetric.FIRING_STRENGTH
        lo, hi = (time, time + _MICROSECOND) if instant else (start, end)
        stats: dict[str, tuple] = {}
        ids = M.meta["entities"]
        if instant:
            shard = self._shard(M, self._key_of(M, time))
            k = shard.t_index.get(fmt.iso(time)) if shard else None
            if k is not None:
                fire = self.reader.get(f"models/{model_id}/{self._key_of(M, time)}/fire.json.gz")["f"][r]
                for i in shard.by_time[k]:
                    f = fire[i]
                    stats[ids[shard.ei[i]]] = (1, 0 if f is None else 1, f, 1 if f is not None and f >= 0 else 0)
        else:
            kk = self._tau_index(M, tau) if metric == m.RuleMapMetric.ACTIVATION_FREQUENCY else None
            agg = self._agg(M, start, end)
            if agg is not None:
                n_e = len(ids)
                for e, eid in enumerate(ids):
                    n_rec, n_val = agg["n_records"][e], agg["n_valid"][e]
                    if not n_rec:
                        continue
                    mean = agg["sum"][r * n_e + e] / n_val if n_val else None
                    over = agg["over"][kk][r * n_e + e] if kk is not None else 0
                    stats[eid] = (n_rec, n_val, mean, over)
        features = []
        for entity in M.entities.features:
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
                    time_from_utc=lo, time_to_utc=lo if instant else hi, issued_at_utc=lo if instant else None,
                    valid_at_utc=lo + M.horizon if instant and n_records else None, tau=tau, model_id=M.model_id,
                    data_version=M.data_version, geometry_support=entity.properties.geometry_support,
                    missing_reason=reason, quality=quality)))
        return m.RuleMapResponse(
            type="FeatureCollection", data_version=M.data_version, synthetic=M.synthetic, model_id=M.model_id,
            rule_id=rule_id, metric=metric, tau=tau, time_from_utc=lo, time_to_utc=lo if instant else hi,
            features=features)

    # ------------------------------------------------------------------ territories / stories
    def rule_territories(self, model_id, start, end, measure, tau) -> m.RuleTerritoriesResponse:
        M = self._model(model_id)
        if measure == m.TerritoryMeasure.WINNER_SHARE and not M.winning:
            raise BadRequest("winner_share only exists for winning-rule classifiers (in a mixture of rules no rule "
                             "decides alone); use mean_activation or activation_frequency")
        kk = self._tau_index(M, tau)
        agg = self._agg(M, start, end)
        rows = []
        if agg is not None:
            ids, n_e = M.meta["entities"], len(M.meta["entities"])
            for e, eid in enumerate(ids):
                if not agg["n_records"][e]:
                    continue
                for r, rule_id in enumerate(M.rule_order):
                    rows.append((eid, rule_id, agg["n_records"][e], agg["n_valid"][e], agg["sum"][r * n_e + e],
                                 agg["over"][kk][r * n_e + e], agg["win"][r * n_e + e] if "win" in agg else 0))
        stats = pd.DataFrame(rows, columns=territories.STATS_COLUMNS) if rows else territories.empty_stats()
        return territories.build_territories(
            model_id=M.model_id, data_version=M.data_version, synthetic=M.synthetic, family=M.rules.inference.family,
            rule_ids=M.rule_order, entities=M.entities.features, stats=stats, measure=measure, tau=tau,
            start=start, end=end)

    def rule_stories(self, model_id, start, end, tau, limit) -> m.RuleStoriesResponse:
        M = self._model(model_id)
        if not fmt.close(tau, fmt.STORIES_TAU) or limit != fmt.STORIES_LIMIT:
            raise BadRequest(f"stories are precomputed for tau={fmt.STORIES_TAU:g} and limit={fmt.STORIES_LIMIT} only")
        rel = self._window_file(M, start, end).replace("/agg/", "/stories/")
        return self._exact(rel, m.RuleStoriesResponse, f"no stories for {model_id} in this window")

    # ------------------------------------------------------------------ rule trace
    def _locate(self, M: _Model, entity_id: str, at: datetime):
        shard = self._shard(M, self._key_of(M, at))
        if shard is None:
            return None
        k = shard.t_index.get(fmt.iso(at))
        i = None if k is None else shard.row_of.get((k, M.e_index[entity_id]))
        return None if i is None else (shard, i)

    def _base(self, M: _Model, entity_id: str, at: datetime):
        """Everything a trace needs about a located row: inputs, memberships, firing, pred columns."""
        found = self._locate(M, entity_id, at)
        if found is None:
            return None
        shard, i = found
        key = self._key_of(M, at)
        fire = self.reader.get(f"models/{M.model_id}/{key}/fire.json.gz")["f"]
        mem = self.reader.get(f"models/{M.model_id}/{key}/mem.json.gz")["m"]
        return {
            "shard": shard, "i": i,
            "vals": {f["name"]: self._input(M, f["name"], shard, i, at) for f in M.meta["features"]},
            "mem": [col[i] for col in mem], "fire": [col[i] for col in fire],
            "out": {c: shard.col(c, i) for c in ("pred", "plabel", "decided", "top", "tshare")},
            "obs": shard.col("obs", i), "olabel": shard.col("olabel", i),
            "noref": bool(shard.col("noref", i)),
        }

    def rule_trace(self, model_id, entity_id, at) -> m.RuleTrace:
        M = self._model(model_id)
        if entity_id not in M.entity_ids:
            raise NotFound(f"unknown entity {entity_id} for {model_id}")
        at = _utc(at)
        if entity_id in M.unmodelled_ids:
            return unmodelled.not_modelled_trace(
                inference=M.rules.inference, model_id=M.model_id, task_id=M.task_id, entity_id=entity_id, at=at,
                horizon_hours=M.meta["horizon_hours"], target_unit=M.meta["target_unit"],
                data_version=M.data_version, synthetic=M.synthetic)
        base = self._base(M, entity_id, at)
        if base is None:
            raise NotFound(f"no trace for {entity_id} at {at.isoformat()}")
        return self._trace(M, entity_id, at, base["vals"], base["mem"], base["fire"], base["out"], base["obs"],
                           base["olabel"], base["noref"])

    def _trace(self, M, entity_id, at, vals, mem, fire, out, obs, olabel, noref) -> m.RuleTrace:
        meta = M.meta
        values = []
        for name in M.trace_features:
            f, v = M.feature_meta[name], vals[name]
            values.append(m.FeatureValue(
                feature=name, value=v, unit=f["trace_unit"], source_id=f["source_id"],
                observed_at_utc=None if v is None else at - timedelta(hours=f["lag_hours"]),
                missing_reason=m.MissingReason.NO_OBSERVATION if v is None else None))
        common = dict(
            data_version=M.data_version, synthetic=M.synthetic, model_id=M.model_id, task_id=M.task_id,
            entity_id=entity_id, issued_at_utc=at, valid_at_utc=at + M.horizon, inference=M.inference,
            feature_values=values, observed=obs, observed_label=None if olabel is None else M.classes[olabel])
        unit = meta["target_unit"]
        if any(fv.value is None for fv in values):
            missing = [fv.feature for fv in values if fv.value is None]
            return m.RuleTrace(
                **common, rules=[],
                prediction=m.TracePrediction(value=None, unit=unit, fallback_used=False,
                                             missing_reason=m.MissingReason.MISSING_INPUT),
                quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)]))
        classes = M.classes
        entries = []
        for r, rule_id in enumerate(M.rule_order):
            d = M.rule_defs[rule_id]
            ants = self._antecedent_traces(M, d, mem)
            extra: dict = {}
            if M.winning:
                weight = 1.0 if M.rules.inference.rule_weighting == "none" else d.weight
                extra = dict(weight=d.weight, association_degree=fire[r] * weight)
            elif M.mixture:
                extra = dict(
                    class_weights=d.class_weights,
                    class_contributions={c: d.class_weights[c] * fire[r] for c in classes},
                    class_contributions_centred={c: d.class_weights_centred[c] * fire[r] for c in classes})
            entries.append(m.RuleTraceEntry(rule_id=rule_id, antecedents=ants, firing_strength=fire[r],
                                            effective_firing=fire[r], **extra))
        fired = False
        plabel = out.get("plabel")
        label = None if plabel is None else classes[plabel]
        if M.mixture:
            bias = M.rules.class_bias
            scores = {c: bias[c] + sum(e.class_contributions[c] for e in entries) for c in classes}
            fired = any(f > 0 for f in fire)
            top = out.get("top")
            scores_kw = dict(class_scores=scores, class_bias=dict(bias))
            if label is None:
                prediction = m.TracePrediction(value=None, unit=unit, fallback_used=not fired,
                                               missing_reason=m.MissingReason.PREDICTION_UNAVAILABLE, **scores_kw)
            else:
                prediction = m.TracePrediction(
                    value=None, label=label, unit=unit, fallback_used=not fired,
                    top_rule_id=None if top is None else M.rule_order[top],
                    top_rule_share=None if top is None else out.get("tshare"), **scores_kw)
        elif M.winning:
            fired = any(e.association_degree > 0 for e in entries)
            winner = out.get("decided")
            if label is None:
                prediction = m.TracePrediction(value=None, unit=unit, fallback_used=not fired,
                                               missing_reason=m.MissingReason.PREDICTION_UNAVAILABLE)
            else:
                prediction = m.TracePrediction(value=None, label=label, winning_rule_id=M.rule_order[winner],
                                               unit=unit, fallback_used=False)
        else:
            prediction = m.TracePrediction(value=out.get("pred"), unit=unit,
                                           fallback_used=sum(fire) <= COVERAGE_EPSILON)
        trace = m.RuleTrace(**common, rules=entries, prediction=prediction)
        if noref and M.classifier and fired:  # the engine had a class, the published row withholds it
            trace = ArtifactStore._without_reference(trace)
        return trace

    @staticmethod
    def _antecedent_traces(M: _Model, rule: m.RuleDefinition, mem) -> list[m.AntecedentTrace]:
        """The antecedent entries of a rule's trace. With ``extract.antecedent_pairs``, the only reader of the
        antecedent shape (feature, term, modifier); a richer antecedent (contract v0.8) is refused at export time."""
        ants = []
        for a in rule.antecedents:
            membership = mem[M.pair_index[(a.feature, a.term)]]
            ants.append(m.AntecedentTrace(
                feature=a.feature, term=a.term, membership=membership, modifier=a.modifier,
                effective_membership=membership if a.modifier is None else membership ** a.modifier))
        return ants

    # ------------------------------------------------------------------ scenario
    def scenario(self, request: m.ScenarioRequest) -> m.ScenarioResponse:
        M = self._model(request.model_id)
        if request.entity_id not in M.entity_ids:
            raise NotFound(f"unknown entity {request.entity_id} for {request.model_id}")
        if request.entity_id in M.unmodelled_ids:
            raise BadRequest(f"{request.entity_id} has no model (not_modelled): there is no row to modify")
        at = _utc(request.at)
        original = self.rule_trace(request.model_id, request.entity_id, at)
        base = self._base(M, request.entity_id, at)

        def rerun(values: dict[str, float | None]) -> m.RuleTrace:
            changed = {f: v for f, v in values.items() if base["vals"][f] != v}
            if not changed:
                return original
            if len(changed) > 1:
                raise BadRequest("the static demo changes one input at a time")
            (feature,) = changed
            doc = self.reader.get(f"models/{M.model_id}/whatif/{request.entity_id}.json.gz")
            at_iso = fmt.iso(at)
            if doc is None or at_iso not in doc["variants"]:
                near = self._nearest_instant(doc, at)
                raise BadRequest("no precomputed scenarios for this row"
                                 + (f"; nearest featured instant: {near}" if near else ""))
            grid = doc["grid"][feature]
            value = request.overrides[feature]
            k = next((j for j, g in enumerate(grid) if fmt.close(g, value)), None)
            if k is None:
                lower = max((g for g in grid if g <= value), default=None)
                upper = min((g for g in grid if g >= value), default=None)
                raise BadRequest(f"value not precomputed for {feature}; nearest: {lower}, {upper}")
            v = doc["variants"][at_iso][feature]
            fire = [col[k] for col in v["f"]]
            mem = list(base["mem"])
            for p, col in zip(self._pairs_of(M, feature), v["m"], strict=True):
                mem[p] = col[k]
            out = {c: v[c][k] for c in ("pred", "plabel", "decided", "top", "tshare") if c in v}
            return self._trace(M, request.entity_id, at, values, mem, fire, out, base["obs"], base["olabel"],
                               base["noref"])

        try:
            return scenarios.build_scenario(request, M.rules, original, rerun)
        except scenarios.ScenarioError as exc:
            raise BadRequest(str(exc)) from exc

    @staticmethod
    def _pairs_of(M: _Model, feature: str) -> list[int]:
        return [p for p, (f, _) in enumerate(M.meta["mem_pairs"]) if f == feature]

    @staticmethod
    def _nearest_instant(doc, at: datetime):
        if not doc or not doc["at"]:
            return None
        return min(doc["at"], key=lambda s: abs((fmt.parse_iso(s) - at).total_seconds()))
