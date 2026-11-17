"""fNIRS end to end on synthetic trials: real ex_fuzzy fit -> publish -> API -> static export -> StaticStore parity."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.domains.fnirs import synthetic
from atlas.ml.experiment_fnirs import CLASS_LABELS, feature_columns
from atlas.paths import REPO_ROOT
from atlas.services.static import export
from atlas.services.static.store import StaticStore
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

MONTAGE = json.loads((REPO_ROOT / "configs/fnirs/montage.json").read_text())
SUBJECTS, TEST = list(range(1, 7)), [3, 4]


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    root = tmp_path_factory.mktemp("fnirs")
    out, model, data = synthetic.build(root)
    return root, out, model, data


def test_publish_writes_valid_documents_and_a_montage_registry_entry(published):
    root, out, model, data = published
    entry = json.loads((root / "published/registry.json").read_text())["tasks"]["fnirs_nback"]
    assert entry["view"] == "montage" and entry["domain"] == "fnirs"
    montage = m.MontageResponse.model_validate_json((out / "montage.json").read_text())
    assert len(montage.channels) == 36 and montage.region_approximate
    assert {i.signal for c in montage.channels for i in c.inputs} == {m.HaemoglobinSignal.HBO, m.HaemoglobinSignal.HBR}
    trials = m.TrialsResponse.model_validate_json((out / "trials.json").read_text()).trials
    assert len(trials) == len(data) and trials[0].split == "test"  # test subjects first
    predicted = model.predict(data[feature_columns(data)])
    by_key = {(t.subject, t.trial): t for t in trials}
    for (subject, trial), p in zip(zip(data["subject"], data["trial"], strict=True), predicted, strict=True):
        label = by_key[(subject, trial)].predicted_label
        assert label == (None if p < 0 else CLASS_LABELS[p])


def test_api_serves_montage_bodies_and_refuses_map_endpoints(published):
    root, out, _, _ = published
    client = TestClient(create_app(ArtifactStore(root / "published")))
    mid = out.name
    assert client.get("/api/v1/fnirs/montage", params={"task_id": "fnirs_nback"}).status_code == 200
    card = client.get("/api/v1/fnirs/card", params={"model_id": mid}).json()
    assert card["split"]["test_subjects"] == TEST
    assert {r["slice"].split("/")[0] for r in card["metrics"]} == {"validation", "test", "train", "nested"}
    assert {r["slice"] for r in card["metrics"] if r["estimator"] == "svm_rbf" and "/" in r["slice"]} == {
        "test/seed=0", "test/seed=1", "test/seed=2", "validation/fold=0", "validation/fold=1", "nested/fold=0",
        "nested/fold=1", "nested/fold=2"}
    trace = client.get("/api/v1/fnirs/trace", params={"model_id": mid, "sample_id": "s03-t01"})
    assert trace.status_code == 200 and trace.json()["split"] == "test"
    assert client.get("/api/v1/fnirs/trace", params={"model_id": mid, "sample_id": "s99-t01"}).status_code == 404
    assert client.get(f"/api/v1/models/{mid}/rules").status_code == 200
    assert client.get(f"/api/v1/models/{mid}").status_code == 422
    assert client.get("/api/v1/entities", params={"domain": "fnirs"}).status_code == 422
    tasks = [t for d in client.get("/api/v1/domains").json()["domains"] for t in d["tasks"]]
    assert [t["view"] for t in tasks] == ["montage"]


def test_committed_web_fixture_is_valid_and_synthetic():
    """The web fixture (python -m atlas.domains.fnirs.synthetic) validates under the current contract, all synthetic."""
    fx = json.loads(synthetic.WEB_FIXTURE.read_text())
    rules = m.ModelRules.model_validate(fx["rules"])
    m.MontageResponse.model_validate(fx["montage"])
    m.FnirsModelCard.model_validate(fx["card"])
    trials = m.TrialsResponse.model_validate(fx["trials"])
    traces = [m.TrialTrace.model_validate(t) for t in fx["traces"].values()]
    assert rules.synthetic and trials.synthetic and all(t.synthetic for t in traces)
    assert set(fx["traces"]) == set(synthetic.WEB_TRACES)


def test_static_export_matches_the_api(published, tmp_path):
    root, out, _, _ = published
    export.main(["--published-dir", str(root / "published"), "--out", str(tmp_path), "--check-n", "2"])
    data = next((tmp_path / "data").iterdir())
    manifest = json.loads((data / "manifest.json").read_text())
    golden = manifest["golden"]
    assert golden["n_passed"] == golden["n_checked"] > 0 and golden["by_kind"]["trialTrace"]["ok"] > 0
    assert manifest["tasks"]["fnirs_nback"]["view"] == "montage" and manifest["privacy"]["violations"] == 0
    assert not any(p.suffix in (".pkl", ".parquet") for p in data.rglob("*"))
    static = StaticStore(data)
    assert static.fnirs_trace(out.name, "s05-t09").sample_id == "s05-t09"
    assert static.fnirs_montage("fnirs_nback").channels[0].xy == m.head_projection(static.fnirs_montage(
        "fnirs_nback").channels[0].xyz)
