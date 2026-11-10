"""Generate the synthetic contract fixtures in fixtures/synthetic/.

Every membership, firing strength and prediction is computed by the pinned ex_fuzzy
engine (``RuleBaseT1Regression``) from a hand-written toy rule base, through the production
export and trace code (``atlas.ml.rules_export``, ``atlas.explain``), so the fixtures double
as golden traces. ``rule_maps.json`` holds the mock API's rule-map responses, for clients
that must not re-aggregate; ``v04_responses.json`` does the same for the v0.4 endpoints
(predictions, observations, territories, stories and a what-if scenario). ``importance.json`` and
``summary.json`` (contract v0.5) hold the rule importance and the data summary of two synthetic models: the toy
regressor above (computed from its own traces by ``atlas.services.importance`` / ``summary``) and a tiny trained
winning-rule classifier (``atlas.services.synthetic``, published and read back); ``model_rules_extra.json`` has the
rules of that classifier so the mock API can serve them next to its importance. ``explanations.json`` (contract
v0.6.2) is a hand-written explanation of the toy regressor, so the web can show the card against the mock API; the real
ones are written by ``scripts/explain_model.py``. Contract v0.7: a tiny trained mixture-of-rules classifier
(``atlas.services.synthetic --task mixture``) is published the same way; its rules and importance join those files, and
``v07_responses.json`` holds the artifacts-mode responses of that model (rules, rule traces with class contributions,
predictions with ``top_rule_id``, a what-if, importance), read back through ``atlas_api.artifact_store``; the mock API
serves its traces. Stations, coordinates
and values are invented: every payload carries ``synthetic: true`` and must never be shown as
real data.

Usage: python scripts/make_fixtures.py [--out DIR]
"""

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.contracts import models as m
from atlas.contracts.observations import OBSERVATION_SCHEMA
from atlas.explain import build_rule_traces, iter_firing_tables
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.rules_export import export_model_rules
from atlas.services import layout
from atlas.services.enrich import apply_feature_labels
from atlas.services.importance import compute_importance
from atlas.services.mock_model import FALLBACK, RULES, VARIABLES, build_rulebase
from atlas.services.publish import ACTIVATION_SCHEMA, PREDICTION_SCHEMA, _table
from atlas.services.summary import compute_summary
from atlas.services.synthetic import build_synthetic
from atlas_api.mock_store import FixtureStore

REPO = Path(__file__).resolve().parents[1]
DATA_VERSION = "synthetic-fixture-v0"
MODEL_ID = "synthetic-no2-h6-v0"
TASK_ID = "madrid_no2_h6"
HORIZON_HOURS = 6
SEED = 20261030
ATTRIBUTION = m.Attribution(text="Synthetic fixtures: invented stations and values, not a real source.")
ISSUE_TIMES = [datetime(2025, 1, 15, 6, tzinfo=timezone.utc) + timedelta(hours=h) for h in range(6)]

# Invented points inside the Madrid bounding box, named so nobody mistakes them for stations.
STATIONS = {
    "SYN_A": ("Synthetic station A (not real)", -3.703, 40.417),
    "SYN_B": ("Synthetic station B (not real)", -3.668, 40.452),
    "SYN_C": ("Synthetic station C (not real)", -3.741, 40.388),
    "SYN_D": ("Synthetic station D (not real)", -3.632, 40.401),
}

# One input is deliberately missing so the fixtures exercise null versus 0.
MISSING = {("SYN_D", ISSUE_TIMES[2], "wind_speed_t")}


def synthetic_inputs(rng):
    """Smooth invented NO2 / wind series per station and issue time."""
    no2_base = {"SYN_A": 72.0, "SYN_B": 45.0, "SYN_C": 30.0, "SYN_D": 85.0}
    wind_base = {"SYN_A": 1.2, "SYN_B": 3.0, "SYN_C": 5.5, "SYN_D": 2.2}
    rows = {}
    for k, entity in enumerate(STATIONS):
        for h, t in enumerate(ISSUE_TIMES):
            no2 = float(np.clip(no2_base[entity] + 12 * np.sin(h / 2 + k) + rng.normal(0, 4), 2, 190))
            wind = float(np.clip(wind_base[entity] + 1.0 * np.cos(h / 3 + k) + rng.normal(0, 0.4), 0, 19))
            rows[(entity, t)] = {"no2_t": round(no2, 1), "wind_speed_t": round(wind, 1)}
    return rows


# contract v0.5 input labels of the toy rule base (invented, like everything here); v0.5.1 adds the term labels
TERMS = {"Low": "baja (inventada)", "Medium": "media (inventada)", "High": "alta (inventada)"}
TERMS_EN = {"Low": "low (made up)", "Medium": "medium (made up)", "High": "high (made up)"}  # contract v0.6
LABELS = {
    "no2_t": layout.FeatureMetadata(
        label="NO₂ en la emisión (inventado)", lag_hours=0,
        description="Concentración inventada de NO₂ (µg/m³) a la hora de emisión; no es una fuente real.",
        terms=TERMS, label_en="NO₂ at the issue time (made up)",
        description_en="Made-up NO₂ concentration (µg/m³) at the issue time; not a real source.", terms_en=TERMS_EN),
    "wind_speed_t": layout.FeatureMetadata(
        label="Viento en la emisión (m/s, inventado)", lag_hours=0,
        description="Velocidad inventada del viento (m/s) a la hora de emisión; no es una fuente real.",
        terms=TERMS, label_en="Wind at the issue time (m/s, made up)",
        description_en="Made-up wind speed (m/s) at the issue time; not a real source.", terms_en=TERMS_EN),
}


def model_rules(rulebase):
    rules = export_model_rules(
        rulebase, model_id=MODEL_ID, task_id=TASK_ID, domain=m.Domain.AIR, target="no2", target_unit="ug/m3",
        horizon_hours=HORIZON_HOURS, data_version=DATA_VERSION, synthetic=True,
    )
    spec = layout.FeatureSpec(features={
        name: layout.FeatureSource(unit=unit, source_id="synthetic", lag_hours=0) for name, unit, _, _ in VARIABLES})
    return apply_feature_labels(rules, LABELS, spec)[0]


def traces(inputs, rulebase):
    """Production trace path (atlas.explain); observation provenance is filled in afterwards."""
    keys = list(inputs)
    X = pd.DataFrame([
        {f: np.nan if (entity, t, f) in MISSING else v for f, v in inputs[(entity, t)].items()}
        for entity, t in keys
    ])
    out = build_rule_traces(
        rulebase, X, [e for e, _ in keys], [t for _, t in keys], model_id=MODEL_ID, task_id=TASK_ID,
        horizon_hours=HORIZON_HOURS, target_unit="ug/m3", data_version=DATA_VERSION, synthetic=True,
    )
    return [
        tr.model_copy(update={"feature_values": [
            fv.model_copy(update={"observed_at_utc": tr.issued_at_utc, "source_id": "synthetic"})
            for fv in tr.feature_values
        ]})
        for tr in out
    ]


def series(trace_list, rng):
    by_entity = {}
    for tr in trace_list:
        observed = float(np.round(rng.uniform(15, 80), 1))
        by_entity.setdefault(tr.entity_id, []).append(m.SeriesPoint(
            issued_at_utc=tr.issued_at_utc, valid_at_utc=tr.valid_at_utc, observed=observed,
            prediction=tr.prediction.value, missing_reason=tr.prediction.missing_reason,
        ))
    return [
        m.SeriesResponse(
            data_version=DATA_VERSION, synthetic=True, task_id=TASK_ID, entity_id=e, model_id=MODEL_ID,
            target="no2", unit="ug/m3", horizon_hours=HORIZON_HOURS, points=points,
        )
        for e, points in by_entity.items()
    ]


def entities():
    return m.EntityCollection(
        type="FeatureCollection", domain=m.Domain.AIR, data_version=DATA_VERSION, synthetic=True,
        attribution=[ATTRIBUTION],
        features=[
            m.EntityFeature(
                type="Feature", id=eid, geometry=m.PointGeometry(type="Point", coordinates=(lon, lat)),
                properties=m.EntityProperties(
                    entity_id=eid, domain=m.Domain.AIR, name=name, geometry_support=m.GeometrySupport.OBSERVED_POINT,
                    geometry_source="synthetic-fixture", timezone="Europe/Madrid", attributes={"synthetic": True},
                    modelled=True,
                ),
            )
            for eid, (name, lon, lat) in STATIONS.items()
        ],
    )


def model_card():
    t0 = datetime(2019, 1, 1, tzinfo=timezone.utc)
    split = m.SplitSpec(
        train_from_utc=t0, train_to_utc=datetime(2023, 1, 1, tzinfo=timezone.utc),
        validation_from_utc=datetime(2023, 1, 2, tzinfo=timezone.utc),
        validation_to_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        test_from_utc=datetime(2024, 1, 2, tzinfo=timezone.utc), test_to_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        embargo_hours=24,
    )
    manifest = m.RunManifest(
        run_id="synthetic-run-0", model_id=MODEL_ID, task_id=TASK_ID, domain=m.Domain.AIR,
        created_at_utc=datetime(2026, 10, 30, tzinfo=timezone.utc), git_commit=None, git_dirty=False,
        exfuzzy_version=exfuzzy_version(), python_version="n/a", seed=SEED, split=split,
        data_version=DATA_VERSION, data_checksums={}, target="no2", horizon_hours=HORIZON_HOURS,
        features=[v[0] for v in VARIABLES], hyperparameters={"hand_written_rules": len(RULES)},
        artifacts={}, warnings=["hand-written toy rule base for UI and contract tests; not trained"],
    )
    coverage = m.TimeCoverage(
        issued_from_utc=ISSUE_TIMES[0], issued_to_utc=ISSUE_TIMES[-1], step_hours=1,
    )
    return m.ModelCard(
        data_version=DATA_VERSION, synthetic=True, manifest=manifest, coverage=coverage, attribution=[ATTRIBUTION],
    )


def domains():
    return m.DomainsResponse(data_version=DATA_VERSION, synthetic=True, domains=[
        m.DomainInfo(domain=m.Domain.AIR, title="Madrid air quality", status="planned", tasks=[
            m.TaskInfo(
                task_id=TASK_ID, target="no2", unit="ug/m3", horizon_hours=HORIZON_HOURS, status="planned",
                model_id=MODEL_ID, territory="madrid", territory_title="Madrid (inventado)",
                territory_title_en="Madrid (made up)",
            ),
        ]),
        m.DomainInfo(domain=m.Domain.WATER, title="England water quality", status="planned", tasks=[]),
        m.DomainInfo(domain=m.Domain.MOBILITY, title="NYC yellow taxi demand", status="planned", tasks=[]),
    ])


def observations(inputs):
    rows = []
    for (entity, t), values in inputs.items():
        for name, unit, _, _ in VARIABLES:
            missing = (entity, t, name) in MISSING
            rows.append({
                "domain": "air", "entity_id": entity, "timestamp_utc": t,
                "source_timestamp_local": None, "timezone": "Europe/Madrid", "feature_name": name,
                "value": None if missing else values[name], "unit": unit, "validity_flag": None,
                "missing_reason": "no_observation" if missing else None, "censoring": None,
                "source_id": "synthetic", "data_version": DATA_VERSION,
                "aggregation_window_start_utc": None, "aggregation_window_end_utc": None, "n_records": None,
            })
    return pa.Table.from_pylist(rows, schema=OBSERVATION_SCHEMA)


def rule_maps(out: Path):
    """Every rule at every issue time, plus the whole window for both aggregates (tau=0.5)."""
    store = FixtureStore(out)
    window = (ISSUE_TIMES[0], ISSUE_TIMES[-1] + timedelta(hours=1))
    queries = []
    for rule_id, _, _ in RULES:
        queries += [dict(rule_id=rule_id, metric=m.RuleMapMetric.FIRING_STRENGTH, time=t) for t in ISSUE_TIMES]
        queries.append(dict(rule_id=rule_id, metric=m.RuleMapMetric.MEAN_ACTIVATION, start=window[0], end=window[1]))
        queries.append(dict(
            rule_id=rule_id, metric=m.RuleMapMetric.ACTIVATION_FREQUENCY, start=window[0], end=window[1], tau=0.5,
        ))
    entries = []
    for q in queries:
        response = store.rule_map(
            MODEL_ID, q["rule_id"], q["metric"], q.get("time"), q.get("start"), q.get("end"), q.get("tau"),
        )
        query = {"model_id": MODEL_ID, "rule_id": q["rule_id"], "metric": q["metric"].value}
        if "time" in q:
            query["time"] = q["time"]
        else:
            query.update({"from": q["start"], "to": q["end"]})
        if "tau" in q:
            query["tau"] = q["tau"]
        iso = {k: v.isoformat().replace("+00:00", "Z") if isinstance(v, datetime) else v for k, v in query.items()}
        entries.append({"query": iso, "response": response.model_dump(mode="json")})
    (out / "rule_maps.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def v04_responses(out: Path):
    """Reference responses of the v0.4 endpoints (predictions, observations, territories, stories, what-if)."""
    store = FixtureStore(out)
    window = (ISSUE_TIMES[0], ISSUE_TIMES[-1] + timedelta(hours=1))

    def iso(value):
        return value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value

    def entry(method, path, query, response):
        return {"method": method, "path": path, "query": {k: iso(v) for k, v in query.items()},
                "response": response.model_dump(mode="json")}

    entries = []
    for t in (ISSUE_TIMES[0], ISSUE_TIMES[2]):
        entries.append(entry("GET", "/api/v1/predictions", {"task_id": TASK_ID, "time": t},
                             store.predictions(TASK_ID, t, None, None)))
    entries.append(entry("GET", "/api/v1/predictions", {"task_id": TASK_ID, "from": window[0], "to": window[1]},
                         store.predictions(TASK_ID, None, *window)))
    entries.append(entry("GET", "/api/v1/observations", {"task_id": TASK_ID, "time": ISSUE_TIMES[2]},
                         store.observations(TASK_ID, ISSUE_TIMES[2], None, None)))
    for measure in (m.TerritoryMeasure.MEAN_ACTIVATION, m.TerritoryMeasure.ACTIVATION_FREQUENCY):
        entries.append(entry(
            "GET", "/api/v1/rule-territories",
            {"model_id": MODEL_ID, "from": window[0], "to": window[1], "measure": measure.value, "tau": 0.5},
            store.rule_territories(MODEL_ID, *window, measure, 0.5)))
    entries.append(entry("GET", "/api/v1/rule-stories", {"model_id": MODEL_ID, "from": window[0], "to": window[1],
                                                         "tau": 0.5, "limit": 10},
                         store.rule_stories(MODEL_ID, *window, 0.5, 10)))
    request = m.ScenarioRequest(model_id=MODEL_ID, entity_id="SYN_A", at=ISSUE_TIMES[1],
                                overrides={"wind_speed_t": 5.0})
    entries.append(entry("POST", "/api/v1/scenarios", {}, store.scenario(request)) | {
        "body": request.model_dump(mode="json")})
    (out / "v04_responses.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def v05_responses(out: Path, inputs, rulebase, rules, trace_list, series_list):
    """Importance and summary of the toy regressor and of a trained synthetic classifier (contract v0.5)."""
    keys = list(inputs)
    X = pd.DataFrame([
        {f: np.nan if (entity, t, f) in MISSING else v for f, v in inputs[(entity, t)].items()} for entity, t in keys
    ])
    points = {(s.entity_id, p.issued_at_utc): p for s in series_list for p in s.points}
    con = duckdb.connect(config={"threads": 1})  # one thread: the summary means are then bit-for-bit reproducible
    con.execute("SET TimeZone='UTC'")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # the files a publish writes, from the toy engine: predictions.parquet and the tidy firing table
        predictions = pd.DataFrame([{
            "entity_id": e, "issued_at_utc": t, "valid_at_utc": points[(e, t)].valid_at_utc,
            "prediction": points[(e, t)].prediction, "observed": points[(e, t)].observed,
            "missing_reason": None if points[(e, t)].prediction is not None else "missing_input",
        } for e, t in keys])
        pq.write_table(_table(predictions, PREDICTION_SCHEMA), tmp / "predictions.parquet")
        part = tmp / "activations" / "year=2025" / "month=01"
        part.mkdir(parents=True)
        firing = pd.concat(iter_firing_tables(
            rulebase, X, [e for e, _ in keys], pd.DatetimeIndex([t for _, t in keys]), chunk_size=1000))
        pq.write_table(_table(firing, ACTIVATION_SCHEMA), part / "part-000000.parquet")
        regression, _ = compute_importance(
            tmp, rules, data_version=DATA_VERSION, synthetic=True, fallback=FALLBACK, con=con)
        table = pd.DataFrame({
            "entity_id": predictions["entity_id"], "issued_at_utc": predictions["issued_at_utc"],
            "valid_at_utc": predictions["valid_at_utc"], "target": predictions["observed"],
        })
        table.to_parquet(tmp / "features.parquet", index=False)
        regression_summary = compute_summary(
            con, source=str(tmp / "features.parquet"), task_id=TASK_ID, domain=m.Domain.AIR, variable="no2",
            label="NO₂ horario observado (inventado)", unit="ug/m3", column="target", time_column="valid_at_utc",
            horizon_hours=HORIZON_HOURS, entity_ids=sorted(STATIONS), timezone="Europe/Madrid", scheme=None,
            data_version=DATA_VERSION, synthetic=True,
        ).model_copy(update={"label_en": "Observed hourly NO₂ (made up)"})
    with tempfile.TemporaryDirectory() as tmp:  # a tiny trained classifier, published and read back
        built = build_synthetic(Path(tmp), task="classification", v04=True)
        classifier_importance = m.RuleImportanceResponse.model_validate_json(
            (built.model_dir / layout.IMPORTANCE_FILE).read_text())
        classifier_summary = m.SummaryResponse.model_validate_json((built.model_dir / layout.SUMMARY_FILE).read_text())
        classifier_rules = m.ModelRules.model_validate_json((built.model_dir / "rules.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:  # contract v0.7: the same, with the mixture of rules
        built = build_synthetic(Path(tmp), task="mixture", v04=True)
        mixture_importance = m.RuleImportanceResponse.model_validate_json(
            (built.model_dir / layout.IMPORTANCE_FILE).read_text())
        mixture_rules = m.ModelRules.model_validate_json((built.model_dir / "rules.json").read_text())
        v07_responses(out, built)
    dump([regression, classifier_importance, mixture_importance], out / "importance.json")
    dump([regression_summary, classifier_summary], out / "summary.json")
    dump([classifier_rules, mixture_rules], out / "model_rules_extra.json")


def v07_responses(out: Path, built):
    """Artifacts-mode responses of the synthetic mixture of rules (contract v0.7), read back through the API store."""
    from atlas_api.artifact_store import ArtifactStore

    store = ArtifactStore(built.published_dir, threads=1)
    rules = store.model_rules(built.run.manifest.model_id)
    model_id, task_id = rules.model_id, rules.task_id
    predictions = pd.read_parquet(built.model_dir / layout.PREDICTIONS_FILE).sort_values(["issued_at_utc", "entity_id"])

    def iso(value):
        return value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value

    def entry(method, path, query, response):
        return {"method": method, "path": path, "query": {k: iso(v) for k, v in query.items()},
                "response": response.model_dump(mode="json")}

    # three rows: a prediction with a top rule, one without a top rule (if any), one with a missing input (if any)
    picks = [predictions[predictions["top_rule_id"].notna()].iloc[0]]
    for mask in (predictions["prediction_label"].notna() & predictions["top_rule_id"].isna(),
                 predictions["missing_reason"] == m.MissingReason.MISSING_INPUT.value):
        if mask.any():
            picks.append(predictions[mask].iloc[0])
    entries = [entry("GET", f"/api/v1/models/{model_id}/rules", {}, rules)]
    for row in picks:
        at = row["issued_at_utc"].to_pydatetime()
        entries.append(entry("GET", f"/api/v1/entities/{row['entity_id']}/rule-trace",
                             {"model_id": model_id, "at": at}, store.rule_trace(model_id, row["entity_id"], at)))
    at = picks[0]["issued_at_utc"].to_pydatetime()
    entries.append(entry("GET", "/api/v1/predictions", {"task_id": task_id, "time": at},
                         store.predictions(task_id, at, None, None)))
    request = m.ScenarioRequest(model_id=model_id, entity_id=picks[0]["entity_id"], at=at, overrides={"y_t": 60.0})
    entries.append(entry("POST", "/api/v1/scenarios", {}, store.scenario(request)) | {
        "body": request.model_dump(mode="json")})
    entries.append(entry("GET", f"/api/v1/models/{model_id}/importance", {}, store.importance(model_id)))
    (out / "v07_responses.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def explanations():
    """A synthetic explanation of the toy regressor (contract v0.6.2), written here by hand and without numbers."""
    es = m.ExplanationText(
        headline="Ejemplo sintético: tres reglas inventadas estiman el NO₂ con el NO₂ y el viento en la emisión",
        summary=[
            "Texto de ejemplo para la API simulada: no describe un modelo real. Las tres reglas miran dos entradas, "
            "NO₂ en la emisión (inventado) y Viento en la emisión (m/s, inventado).",
            "Cada estimación es un promedio ponderado de las reglas que se cumplen. Cuando el viento es alto, se "
            "cumple R03, la regla con el valor más bajo.",
        ],
        points=[
            "R01 es la única regla con dos condiciones: NO₂ alto y viento bajo.",
            "R02 solo mira el NO₂ en la emisión.",
            "Los datos son inventados: no sirven para sacar conclusiones.",
        ],
    )
    en = m.ExplanationText(
        headline="Synthetic example: three made-up rules estimate NO₂ from NO₂ and wind at the issue time",
        summary=[
            "Example text for the mock API: it describes no real model. The three rules look at two inputs, NO₂ at "
            "the issue time (made up) and Wind at the issue time (m/s, made up).",
            "Each estimate is a weighted average of the rules that hold. When the wind is high, R03 holds, the rule "
            "with the lowest value.",
        ],
        points=[
            "R01 is the only rule with two conditions: high NO₂ and low wind.",
            "R02 only looks at NO₂ at the issue time.",
            "The data are made up: no conclusion can be drawn from them.",
        ],
    )
    return [m.ModelExplanation(
        data_version=DATA_VERSION, synthetic=True, model_id=MODEL_ID, template_version="1",
        generated_by=m.ExplanationAuthor(tool="synthetic fixture (scripts/make_fixtures.py)"),
        generated_at_utc=datetime(2026, 11, 9, tzinfo=timezone.utc),
        input_sha256=hashlib.sha256(MODEL_ID.encode()).hexdigest(), reviewed=False, es=es, en=en,
    )]


def dump(obj, path):
    data = [o.model_dump(mode="json") for o in obj] if isinstance(obj, list) else obj.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    inputs = synthetic_inputs(rng)
    rulebase = build_rulebase()
    trace_list = traces(inputs, rulebase)
    series_list = series(trace_list, rng)
    observed = {(p.issued_at_utc, s.entity_id): p.observed for s in series_list for p in s.points}
    trace_list = [t.model_copy(update={"observed": observed[(t.issued_at_utc, t.entity_id)]}) for t in trace_list]
    dump(domains(), out / "domains.json")
    dump(entities(), out / "entities_air.json")
    dump(model_rules(rulebase), out / "model_rules.json")
    dump(model_card(), out / "model_card.json")
    dump(trace_list, out / "rule_traces.json")
    dump(series_list, out / "series.json")
    pq.write_table(observations(inputs), out / "observations_air.parquet")
    v05_responses(out, inputs, rulebase, model_rules(rulebase), trace_list, series_list)
    dump(explanations(), out / "explanations.json")
    rule_maps(out)  # these two read the fixtures written above through the mock store
    v04_responses(out)
    print(f"wrote fixtures to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "fixtures" / "synthetic")
    main(parser.parse_args().out)
