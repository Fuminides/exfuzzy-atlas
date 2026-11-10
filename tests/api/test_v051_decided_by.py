"""Contract v0.5.1: ``decided_by_rule_id`` in ``GET /predictions`` is the ``/importance`` measure, rule by rule."""

import shutil
from collections import Counter

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.publish import publish_run
from atlas.services.synthetic import SCHEME
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


@pytest.fixture(scope="module")
def withheld(built_class, tmp_path_factory):
    """The synthetic classifier republished with an observed-label column that is null on some rows (no reference)."""
    table = built_class.table.copy()
    labels = np.array(SCHEME.labels, dtype=object)
    table["lvl"] = labels[(np.arange(len(table)) // 7) % 3]
    table.loc[table.index[::11], "lvl"] = None
    path = tmp_path_factory.mktemp("decided-features") / "features.parquet"
    table.to_parquet(path, index=False)
    out = tmp_path_factory.mktemp("decided-published")
    built = publish_run(
        built_class.run.run_dir, path, built_class.root / "entities.geojson", built_class.root / "feature_spec.json",
        START, END, published_dir=out, synthetic=True, observed_label_column="lvl")
    return built.model_dir, out


def serve(published_dir):
    return TestClient(create_app(ArtifactStore(published_dir)))


def all_predictions(client, model_dir, task_id):
    """The ``properties`` of every entity at every published issue time, through the endpoint."""
    table = pq.read_table(model_dir / layout.PREDICTIONS_FILE, columns=["issued_at_utc"]).to_pandas()
    out = []
    for issued in sorted(table["issued_at_utc"].unique()):
        at = pd.Timestamp(issued).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = client.get("/api/v1/predictions", params={"task_id": task_id, "time": at})
        assert response.status_code == 200, response.text
        out += [f["properties"] for f in m.PredictionsResponse.model_validate(response.json()).model_dump(
            mode="json")["features"]]
    return out


@pytest.mark.parametrize("fixture", ["built", "built_class", "built_v04", "built_class_v04", "withheld"])
def test_counting_decided_by_rule_id_reproduces_n_decided_of_the_importance(fixture, request):
    world = request.getfixturevalue(fixture)
    if fixture == "withheld":
        model_dir, published = world
        task_id = m.RuleImportanceResponse.model_validate_json((model_dir / layout.IMPORTANCE_FILE).read_text()).task_id
    else:
        model_dir, published, task_id = world.model_dir, world.published_dir, world.run.manifest.task_id
    importance = m.RuleImportanceResponse.model_validate_json((model_dir / layout.IMPORTANCE_FILE).read_text())
    props = all_predictions(serve(published), model_dir, task_id)
    counted = Counter(p["decided_by_rule_id"] for p in props if p["decided_by_rule_id"] is not None)
    assert counted == {r.rule_id: r.n_decided for r in importance.rules if r.n_decided}
    assert sum(counted.values()) == importance.n_predicted > 0
    # null exactly when: no prediction, no rule fired, or the prediction is withheld
    answered = [p for p in props if p["prediction"] is not None or p["prediction_label"] is not None]
    assert all(p["decided_by_rule_id"] is None for p in props if p not in answered)
    without = [p for p in answered if p["decided_by_rule_id"] is None]
    regression = importance.measure == m.ImportanceMeasure.WEIGHTED_AVERAGE
    assert len(without) == (importance.n_no_rule if regression else 0)  # a classifier's no-rule rows are unanswered
    if fixture == "withheld":
        assert importance.n_withheld > 0
        unavailable = [p for p in props if p["missing_reason"] == "prediction_unavailable"]
        assert len(unavailable) >= importance.n_withheld
        assert all(p["decided_by_rule_id"] is None for p in unavailable)


def test_the_decider_of_a_classifier_is_the_winner_of_its_trace_and_of_the_class(built_class_v04):
    client = serve(built_class_v04.published_dir)
    model_id, task_id = built_class_v04.run.manifest.model_id, built_class_v04.run.manifest.task_id
    rules = {r.rule_id: r for r in m.ModelRules.model_validate_json(
        (built_class_v04.model_dir / "rules.json").read_text()).rules}
    issued = pq.read_table(built_class_v04.model_dir / layout.PREDICTIONS_FILE).to_pandas()["issued_at_utc"].iloc[40]
    at = pd.Timestamp(issued).strftime("%Y-%m-%dT%H:%M:%SZ")
    features = client.get("/api/v1/predictions", params={"task_id": task_id, "time": at}).json()["features"]
    checked = 0
    for f in features:
        p = f["properties"]
        if p["decided_by_rule_id"] is None:
            continue
        trace = client.get(f"/api/v1/entities/{p['entity_id']}/rule-trace", params={"model_id": model_id, "at": at})
        assert trace.json()["prediction"]["winning_rule_id"] == p["decided_by_rule_id"]
        assert rules[p["decided_by_rule_id"]].consequent.term == p["prediction_label"]
        checked += 1
    assert checked > 0


def test_the_decider_of_a_regression_is_the_largest_weight_share_of_its_trace(built_v04):
    client = serve(built_v04.published_dir)
    model_id, task_id = built_v04.run.manifest.model_id, built_v04.run.manifest.task_id
    issued = pq.read_table(built_v04.model_dir / layout.PREDICTIONS_FILE).to_pandas()["issued_at_utc"].iloc[40]
    at = pd.Timestamp(issued).strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = 0
    for f in client.get("/api/v1/predictions", params={"task_id": task_id, "time": at}).json()["features"]:
        p = f["properties"]
        if p["decided_by_rule_id"] is None:
            continue
        trace = client.get(f"/api/v1/entities/{p['entity_id']}/rule-trace", params={"model_id": model_id, "at": at})
        fired = {r["rule_id"]: r["effective_firing"] for r in trace.json()["rules"]}
        assert max(fired, key=lambda k: (fired[k], -list(fired).index(k))) == p["decided_by_rule_id"]
        checked += 1
    assert checked > 0


def test_a_window_gives_each_entity_the_decider_of_its_own_latest_row(built_class_v04, built_v04):
    for world in (built_class_v04, built_v04):
        client = serve(world.published_dir)
        task_id = world.run.manifest.task_id
        times = sorted(pq.read_table(world.model_dir / layout.PREDICTIONS_FILE, columns=["issued_at_utc"])
                       .to_pandas()["issued_at_utc"].unique())
        lo, hi = times[10], times[30]
        stamp = lambda t: pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        window = client.get("/api/v1/predictions", params={"task_id": task_id, "from": stamp(lo), "to": stamp(hi)})
        assert window.status_code == 200, window.text
        for f in window.json()["features"]:
            p = f["properties"]
            if p["issued_at_utc"] is None:
                assert p["decided_by_rule_id"] is None
                continue
            instant = client.get("/api/v1/predictions", params={"task_id": task_id, "time": p["issued_at_utc"]})
            same = next(x for x in instant.json()["features"] if x["id"] == f["id"])
            assert same["properties"]["decided_by_rule_id"] == p["decided_by_rule_id"]


def test_the_mock_api_carries_decided_by_rule_id_and_null_without_a_rule():
    from atlas_api.mock_store import FixtureStore

    store = FixtureStore()
    seen = []
    for t in sorted({tr.issued_at_utc for tr in store.traces.values()}):
        response = store.predictions("madrid_no2_h6", t, None, None)
        for f in response.features:
            p = f.properties
            seen.append(p.decided_by_rule_id)
            assert (p.decided_by_rule_id is None) or p.prediction is not None
    assert {"R01", "R02"} <= set(seen) and None in seen


def test_a_regression_row_where_no_rule_fired_has_no_decider(built, tmp_path):
    """Zero every firing record of one (entity, time) in a copy: a prediction (the fallback) and no decider."""
    root = tmp_path / "published"
    shutil.copytree(built.published_dir, root)
    model_dir = root / built.model_dir.name
    files = sorted((model_dir / layout.ACTIVATIONS_DIR).rglob("*.parquet"))
    frame = pq.read_table(files[0]).to_pandas()
    entity, issued = frame.iloc[0]["entity_id"], frame.iloc[0]["issued_at_utc"]
    row = (frame["entity_id"] == entity) & (frame["issued_at_utc"] == issued)
    frame.loc[row, "effective_firing"] = 0.0
    frame.loc[row, "firing_strength"] = 0.0
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), files[0])
    at = pd.Timestamp(issued).strftime("%Y-%m-%dT%H:%M:%SZ")
    features = serve(root).get("/api/v1/predictions", params={"task_id": built.run.manifest.task_id, "time": at}
                               ).json()["features"]
    by_entity = {f["properties"]["entity_id"]: f["properties"] for f in features}
    assert by_entity[entity]["prediction"] is not None and by_entity[entity]["decided_by_rule_id"] is None
    others = [p for e, p in by_entity.items() if e != entity and p["prediction"] is not None]
    assert others and all(p["decided_by_rule_id"] is not None for p in others)


def test_winning_rule_parity_leaves_out_the_withheld_rows(withheld):
    """v0.7: rows published without a label although a rule won (no reference level) are not compared with native."""
    from atlas.ml.publish_parity import check

    model_dir, _ = withheld
    result = check(model_dir)
    assert result["ok"] and result["rows_withheld"] > 0 and result["label_equal_native"] == 1.0
