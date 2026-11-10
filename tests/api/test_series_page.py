"""B1 (AT-061): /series pages of 2 000 points, built without a validated object per point, still contract-valid."""

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas_api import artifact_store
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app


@pytest.fixture(scope="module", params=["regression", "classification"])
def world(request, built, built_class):
    b = built if request.param == "regression" else built_class
    store = ArtifactStore(b.published_dir)
    return b, store, TestClient(create_app(store))


def test_the_default_page_is_2000_points():
    assert artifact_store.SERIES_MAX_POINTS == 2_000


def test_payload_validates_and_equals_the_validated_construction(world):
    b, store, client = world
    task = b.run.manifest.task_id
    response = client.get("/api/v1/series", params={"task_id": task, "entity_id": "E0"})
    assert response.status_code == 200 and response.headers["content-type"] == "application/json"
    parsed = m.SeriesResponse.model_validate_json(response.content)  # the contract validators run on every point
    fast = store.series_for(task, "E0", None, None)
    # the same data through full validation (model_validate re-runs every validator) is the same object
    assert m.SeriesResponse.model_validate(fast.model_dump()) == parsed
    # and it is what is in the file
    published = pq.read_table(b.model_dir / "predictions.parquet", filters=[("entity_id", "=", "E0")]).to_pandas()
    assert [p.issued_at_utc for p in parsed.points] == published["issued_at_utc"].sort_values().tolist()
    assert (parsed.horizon_hours, parsed.next_cursor, parsed.entity_id, parsed.task_id) == (
        b.run.manifest.horizon_hours, None, "E0", task)
    answered = [p for p in parsed.points if p.prediction is not None or p.predicted_label is not None]
    assert answered
    assert all(p.missing_reason is None for p in answered)
    assert all(p.missing_reason is not None for p in parsed.points if p not in answered)


def test_pages_follow_next_cursor_and_concatenate_to_the_whole_range(world, monkeypatch):
    b, _, client = world
    task = b.run.manifest.task_id
    whole = m.SeriesResponse.model_validate_json(
        client.get("/api/v1/series", params={"task_id": task, "entity_id": "E1"}).content)
    monkeypatch.setattr(artifact_store, "SERIES_MAX_POINTS", 250)
    points, cursor, pages = [], None, 0
    while True:
        page = m.SeriesResponse.model_validate_json(client.get("/api/v1/series", params={
            "task_id": task, "entity_id": "E1", **({"cursor": cursor} if cursor else {})}).content)
        assert len(page.points) <= 250
        points += page.points
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break
    assert pages > 2 and points == whole.points


def test_openapi_still_describes_the_series_response(world):
    _, _, client = world
    schema = client.get("/openapi.json").json()["paths"]["/api/v1/series"]["get"]["responses"]["200"]
    assert schema["content"]["application/json"]["schema"]["$ref"].endswith("SeriesResponse")


def test_a_row_that_breaks_the_horizon_is_refused(world, monkeypatch):
    b, store, _ = world
    real = store._query

    def shifted(sql, params):
        return [(r[0], r[1].replace(year=r[1].year + 1), *r[2:]) for r in real(sql, params)]

    monkeypatch.setattr(store, "_query", shifted)
    with pytest.raises(ValueError, match="horizon"):
        store.series_for(b.run.manifest.task_id, "E0", None, None)
