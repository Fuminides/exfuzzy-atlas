"""Contract v0.5 endpoints in artifacts mode: importance, summary, territory, the 404 of a model published before."""

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "qa"))
import wording_audit  # noqa: E402


@pytest.fixture(scope="module")
def client(built_class_v04):
    return TestClient(create_app(ArtifactStore(built_class_v04.published_dir)))


@pytest.fixture(scope="module")
def ids(built_class_v04):
    return built_class_v04.run.manifest.model_id, built_class_v04.run.manifest.task_id


def test_importance_is_the_published_file(client, built_class_v04, ids):
    model_id, _ = ids
    response = client.get(f"/api/v1/models/{model_id}/importance")
    assert response.status_code == 200, response.text
    got = m.RuleImportanceResponse.model_validate(response.json())
    published = (built_class_v04.model_dir / layout.IMPORTANCE_FILE).read_text()
    expected = m.RuleImportanceResponse.model_validate_json(published)
    assert got == expected.model_copy(update={"synthetic": True})
    assert got.synthetic and got.measure == m.ImportanceMeasure.WINNING_RULE and got.model_id == model_id
    rules = client.get(f"/api/v1/models/{model_id}/rules").json()
    assert [r["rule_id"] for r in response.json()["rules"]] == [r["rule_id"] for r in rules["rules"]]
    assert [v["feature"] for v in response.json()["variables"]] == [v["feature"] for v in rules["variables"]]


def test_summary_is_the_published_file(client, built_class_v04, ids):
    _, task_id = ids
    response = client.get("/api/v1/summary", params={"task_id": task_id})
    assert response.status_code == 200, response.text
    got = m.SummaryResponse.model_validate(response.json())
    assert got.task_id == task_id and got.classes is not None and got.synthetic
    assert got.label == "Serie y observada (inventada)"
    assert got.groups[m.SummaryGroup.ALL][0].n > 0


def test_unknown_model_and_task_are_404(client):
    assert client.get("/api/v1/models/nope/importance").status_code == 404
    assert client.get("/api/v1/summary", params={"task_id": "nope"}).status_code == 404
    assert client.get("/api/v1/summary").status_code == 422


def test_a_model_published_before_v05_answers_404_with_the_reason(built_class_v04, tmp_path):
    root = tmp_path / "published"
    shutil.copytree(built_class_v04.published_dir, root)
    model_dir = root / built_class_v04.model_dir.name
    for name in (layout.IMPORTANCE_FILE, layout.SUMMARY_FILE):
        (model_dir / name).unlink()
    layout.write_checksums(model_dir)
    old = TestClient(create_app(ArtifactStore(root)))
    model_id, task_id = built_class_v04.run.manifest.model_id, built_class_v04.run.manifest.task_id
    answers = (old.get(f"/api/v1/models/{model_id}/importance"),
               old.get("/api/v1/summary", params={"task_id": task_id}))
    for response in answers:
        assert response.status_code == 404
        assert "before contract v0.5" in response.json()["detail"] and model_id in response.json()["detail"]
    assert old.get(f"/api/v1/models/{model_id}/rules").status_code == 200  # the rest of the model still works


def test_the_files_are_read_once_and_a_republish_is_picked_up(built_class_v04, tmp_path):
    root = tmp_path / "published"
    shutil.copytree(built_class_v04.published_dir, root)
    store = ArtifactStore(root)
    model_id = built_class_v04.run.manifest.model_id
    first = store.importance(model_id)
    assert store.importance(model_id) is first
    model_dir = root / built_class_v04.model_dir.name
    (model_dir / layout.IMPORTANCE_FILE).unlink()
    assert store.importance(model_id) is first  # cached for this version of the model
    layout.write_checksums(model_dir)  # SHA256SUMS changes: the directory was published again
    with pytest.raises(Exception, match="before contract v0.5"):
        store.importance(model_id)


def test_domains_carry_the_territory(client, ids):
    _, task_id = ids
    tasks = {t["task_id"]: t for d in client.get("/api/v1/domains").json()["domains"] for t in d["tasks"]}
    assert (tasks[task_id]["territory"], tasks[task_id]["territory_title"]) == ("synthetic", "Sintético (inventado)")


def test_the_new_payloads_pass_the_wording_audit(client, ids):
    model_id, task_id = ids
    for path, params in ((f"/api/v1/models/{model_id}/importance", {}), ("/api/v1/summary", {"task_id": task_id}),
                         (f"/api/v1/models/{model_id}/rules", {})):
        hits = wording_audit.scan_text(client.get(path, params=params).text, path)
        assert [h for h in hits if h.kind != "other-context"] == [], [str(h) for h in hits]
