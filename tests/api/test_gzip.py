"""Large JSON answers are gzip-compressed when the client accepts it; the body is unchanged once decoded."""

from fastapi.testclient import TestClient

from atlas_api.main import app


def test_large_answers_are_gzipped_and_small_ones_are_not():
    client = TestClient(app)
    big = client.get("/api/v1/domains", headers={"Accept-Encoding": "gzip"})
    model_id = big.json()["domains"][0]["tasks"][0]["model_id"]
    card = client.get(f"/api/v1/models/{model_id}", headers={"Accept-Encoding": "gzip"})
    assert card.status_code == 200 and card.headers.get("content-encoding") == "gzip"
    assert card.json()["manifest"]["model_id"] == model_id  # httpx decodes it: same JSON
    health = client.get("/api/v1/health", headers={"Accept-Encoding": "gzip"})
    assert health.headers.get("content-encoding") is None  # under minimum_size
