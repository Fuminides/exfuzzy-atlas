"""GET /api/v1/models/{model_id}/explanation (contract v0.6.2) in both modes; 404 when the model has none."""

import json

import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import app, create_app

mock = TestClient(app)


def test_mock_serves_the_synthetic_explanation():
    response = mock.get("/api/v1/models/synthetic-no2-h6-v0/explanation")
    assert response.status_code == 200, response.text
    e = m.ModelExplanation.model_validate(response.json())
    assert e.synthetic and e.model_id == "synthetic-no2-h6-v0" and e.es.headline and e.en.headline


def test_mock_404_for_a_model_without_one():
    assert mock.get("/api/v1/models/exfuzzy-synthetic_class_h6-synthetic-class-seed3/explanation").status_code == 404


@pytest.fixture(scope="module")
def published(built_class_v04, tmp_path_factory):
    explanations = tmp_path_factory.mktemp("explanations")
    model_id = built_class_v04.run.manifest.model_id
    client = TestClient(create_app(ArtifactStore(built_class_v04.published_dir, explanations_dir=explanations)))
    return client, explanations, model_id


def test_artifacts_404_until_the_file_exists_then_serves_it(published):
    client, explanations, model_id = published
    missing = client.get(f"/api/v1/models/{model_id}/explanation")
    assert missing.status_code == 404 and "make explain" in missing.json()["detail"]
    text = {"headline": "h", "summary": ["a", "b"], "points": ["x", "y", "z"]}
    payload = {"data_version": "v", "model_id": model_id, "template_version": "1",
               "generated_by": {"tool": "Claude Code", "tool_version": "2.1.319", "model": "claude-opus-5-5"},
               "generated_at_utc": "2026-11-09T10:00:00Z", "input_sha256": "a" * 64, "reviewed": False,
               "es": text, "en": text}
    (explanations / f"{model_id}.json").write_text(json.dumps(payload))
    got = client.get(f"/api/v1/models/{model_id}/explanation")
    assert got.status_code == 200, got.text
    e = m.ModelExplanation.model_validate(got.json())
    assert e.synthetic  # the published model is synthetic, so its explanation is served as synthetic too
    assert e.model_id == model_id and e.reviewed is False


def test_artifacts_404_for_an_unknown_model(published):
    client, _, _ = published
    assert client.get("/api/v1/models/no-such-model/explanation").status_code == 404


def test_the_explanations_dir_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_PUBLISHED_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_EXPLANATIONS_DIR", str(tmp_path / "expl"))
    assert ArtifactStore.from_env().explanations_dir == tmp_path / "expl"
