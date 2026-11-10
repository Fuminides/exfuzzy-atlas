"""Several served tasks in one domain: /entities is per task, never a merge (AT-070: Madrid and Germany are both air).

A regressor (``synthetic_y_h6``) and a classifier (``synthetic_class_h6``) are published into one directory, both in the
``air`` domain; the classifier's copy of the entities has other names and coordinates and an extra unmodelled one.
"""

import json
import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.publish import publish_run
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app
from atlas_api.mock_store import FIXTURES_DIR, FixtureStore

REG, CLS = "synthetic_y_h6", "synthetic_class_h6"


@pytest.fixture(scope="module")
def two_air_tasks(built, built_class, tmp_path_factory):
    published = tmp_path_factory.mktemp("two-air") / "published"
    shutil.copytree(built.published_dir, published)
    entities = m.EntityCollection.model_validate_json((built_class.root / "entities.geojson").read_text())
    moved = []
    for i, feature in enumerate(entities.features):
        feature.geometry = m.PointGeometry(type="Point", coordinates=(10.0 + i, 51.0 + i))
        feature.properties.name = f"German station {feature.id} (not real)"
        moved.append(feature)
    extra = moved[0].model_copy(deep=True)
    extra.id = extra.properties.entity_id = "E9"
    moved.append(extra)
    germany = built_class.root / "entities_de.geojson"
    germany.write_text(entities.model_copy(update={"features": moved}).model_dump_json())
    lo, hi = built_class.table["issued_at_utc"].min(), built_class.table["issued_at_utc"].max()
    publish_run(
        built_class.run.run_dir, built_class.root / "features.parquet", germany, built_class.root / "feature_spec.json",
        lo + pd.Timedelta(days=4), hi, published_dir=published, synthetic=True, include_unmodelled_entities=True,
        title="Germany air quality (EEA)",
    )
    return published


@pytest.fixture(scope="module")
def client(two_air_tasks):
    return TestClient(create_app(ArtifactStore(two_air_tasks)))


def names(response):
    return {f["properties"]["name"] for f in response.json()["features"]}


def test_domains_lists_both_air_tasks(client):
    air = next(d for d in client.get("/api/v1/domains").json()["domains"] if d["domain"] == "air")
    assert sorted(t["task_id"] for t in air["tasks"]) == [CLS, REG]
    # v0.4.1: each task carries its own title; the domain entry falls back to the generic domain title
    assert {t["task_id"]: t["title"] for t in air["tasks"]}[CLS] == "Germany air quality (EEA)"
    assert air["title"] == "Air quality"



def test_the_default_task_of_a_domain_is_listed_first(two_air_tasks, monkeypatch):
    """The web opens a domain on its first task; layout.DEFAULT_TASKS puts the chosen one first, the rest by task_id."""
    def air_tasks():
        domains = TestClient(create_app(ArtifactStore(two_air_tasks))).get("/api/v1/domains").json()["domains"]
        return [t["task_id"] for t in next(d for d in domains if d["domain"] == "air")["tasks"]]

    monkeypatch.setattr(layout, "DEFAULT_TASKS", {})
    assert air_tasks() == [CLS, REG]
    monkeypatch.setattr(layout, "DEFAULT_TASKS", {m.Domain.AIR: REG})
    assert air_tasks() == [REG, CLS]

def test_each_task_serves_exactly_its_own_entities(client):
    reg = client.get("/api/v1/entities", params={"domain": "air", "task_id": REG})
    cls = client.get("/api/v1/entities", params={"domain": "air", "task_id": CLS})
    assert reg.status_code == cls.status_code == 200
    assert all(n.startswith("Synthetic station") for n in names(reg)) and len(reg.json()["features"]) == 3
    assert all(n.startswith("German station") for n in names(cls)) and len(cls.json()["features"]) == 4
    assert reg.json()["data_version"] == "synthetic-entities" and reg.json()["domain"] == "air"


def test_without_task_id_a_multi_task_domain_is_ambiguous_422(client):
    response = client.get("/api/v1/entities", params={"domain": "air"})
    assert response.status_code == 422
    assert REG in response.json()["detail"] and CLS in response.json()["detail"]


def test_task_of_another_domain_is_422_and_unknown_task_is_404(client):
    assert client.get("/api/v1/entities", params={"domain": "water", "task_id": REG}).status_code == 422
    assert client.get("/api/v1/entities", params={"domain": "air", "task_id": "nope"}).status_code == 404


def test_other_domains_and_models_are_unchanged(client, two_air_tasks):
    # no task of `water` is served: the domain 404s as before, with or without ambiguity elsewhere
    assert client.get("/api/v1/entities", params={"domain": "water"}).status_code == 404
    tasks = [t for d in client.get("/api/v1/domains").json()["domains"] for t in d["tasks"]]
    window = {"from": "2024-01-10T00:00:00Z", "to": "2024-01-11T00:00:00Z"}
    for task, info in ((t["task_id"], t) for t in tasks):
        assert client.get(f"/api/v1/models/{info['model_id']}").status_code == 200
        pred = client.get("/api/v1/predictions", params={"task_id": task, **window})
        assert pred.status_code == 200 and pred.json()["task_id"] == task


def test_single_task_domain_does_not_need_task_id(built):
    client = TestClient(create_app(ArtifactStore(built.published_dir)))
    plain = client.get("/api/v1/entities", params={"domain": "air"})
    explicit = client.get("/api/v1/entities", params={"domain": "air", "task_id": REG})
    assert plain.status_code == explicit.status_code == 200 and plain.json() == explicit.json()
    assert client.get("/api/v1/entities", params={"domain": "air", "task_id": CLS}).status_code == 404


@pytest.fixture(scope="module")
def mock_client(tmp_path_factory):
    root = tmp_path_factory.mktemp("fixtures-two-air")
    shutil.copytree(FIXTURES_DIR, root, dirs_exist_ok=True)
    domains = json.loads((root / "domains.json").read_text())
    air = next(d for d in domains["domains"] if d["domain"] == "air")
    air["tasks"].append({**air["tasks"][0], "task_id": "germany_no2_h6", "model_id": "other-model"})
    (root / "domains.json").write_text(json.dumps(domains))
    return TestClient(create_app(FixtureStore(root)))


def test_mock_mode_is_task_aware(mock_client):
    def get(**p):
        return mock_client.get("/api/v1/entities", params={"domain": "air", **p})

    assert get().status_code == 422
    assert get(task_id="madrid_no2_h6").status_code == 200
    assert get(task_id="germany_no2_h6").status_code == 200
    assert get(task_id="nope").status_code == 404
    assert get(domain="water", task_id="madrid_no2_h6").status_code == 422
