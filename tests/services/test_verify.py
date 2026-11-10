"""B4 (AT-061): code files verified before unpickling; the full SHA256SUMS by `python -m atlas.services.verify`."""

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from atlas.ml import artifacts
from atlas.services import layout, verify
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app


@pytest.fixture
def copy(built, tmp_path):
    """A private copy of the session's published directory, free to tamper with."""
    shutil.copytree(built.published_dir, tmp_path / "pub")
    return tmp_path / "pub", tmp_path / "pub" / built.run.manifest.model_id


def append(path, data=b"x"):
    with open(path, "ab") as fh:
        fh.write(data)


def first_activations(model_dir):
    return next((model_dir / layout.ACTIVATIONS_DIR).rglob("*.parquet"))


def test_a_clean_model_verifies_in_full_and_by_cli(copy, capsys):
    published, model_dir = copy
    verify.verify_model_dir(model_dir)
    assert verify.main([str(model_dir)]) == 0
    assert "ok" in capsys.readouterr().out
    assert verify.main([str(published)]) == 0  # a published directory: every registered model
    assert str(model_dir) in capsys.readouterr().out


def test_cli_as_a_module_exits_non_zero_on_tampered_data(copy):
    _, model_dir = copy
    command = [sys.executable, "-m", "atlas.services.verify", str(model_dir)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    append(first_activations(model_dir))
    bad = subprocess.run(command, capture_output=True, text=True)
    assert bad.returncode == 1 and "checksum mismatch" in bad.stderr and "part-000000.parquet" in bad.stderr


@pytest.mark.parametrize("name", ["predictions.parquet", "inputs.parquet", "entities.geojson", "metrics.json"])
def test_full_verification_catches_tampered_data_and_run_files(copy, name, capsys):
    _, model_dir = copy
    append(model_dir / name)
    with pytest.raises(ValueError, match=f"checksum mismatch for {name}"):
        verify.verify_model_dir(model_dir)
    assert verify.main([str(model_dir)]) == 1
    assert name in capsys.readouterr().err


def test_full_verification_catches_missing_and_unlisted_files(copy):
    _, model_dir = copy
    (model_dir / "extra.parquet").write_bytes(b"not listed")
    with pytest.raises(ValueError, match="not listed"):
        verify.verify_model_dir(model_dir)
    (model_dir / "extra.parquet").unlink()
    first_activations(model_dir).unlink()
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify.verify_model_dir(model_dir)


def test_not_a_published_model_directory(tmp_path):
    with pytest.raises(ValueError, match="SHA256SUMS"):
        verify.verify_model_dir(tmp_path)


def test_load_hashes_only_the_code_files(built, monkeypatch):
    hashed = []
    real = artifacts.sha256_file
    monkeypatch.setattr(artifacts, "sha256_file", lambda p: hashed.append(p.name) or real(p))
    verify.load_verified_model(built.model_dir)
    assert sorted(hashed) == sorted(verify.CODE_FILES) == ["card.json", "model.pkl", "rules.json"]


@pytest.mark.parametrize("name", ["model.pkl", "rules.json", "card.json"])
def test_a_tampered_code_file_is_refused_before_unpickling(copy, name, monkeypatch):
    _, model_dir = copy
    append(model_dir / name, b" ")
    import pickle

    monkeypatch.setattr(pickle, "load", lambda *_: pytest.fail("unpickled a model whose files do not verify"))
    with pytest.raises(ValueError, match=f"checksum mismatch for {name}"):
        verify.load_verified_model(model_dir)


def test_the_api_refuses_a_tampered_model_but_serves_with_tampered_data(built, copy, monkeypatch):
    published, model_dir = copy
    model_id = built.run.manifest.model_id
    trace = ("/api/v1/entities/E0/rule-trace", {"model_id": model_id, "at": "2024-01-10T00:00:00Z"})

    append(first_activations(model_dir))  # data: not read by the load check, caught by `verify`
    append(model_dir / "predictions.parquet", b"")
    ok = TestClient(create_app(ArtifactStore(published)), raise_server_exceptions=False).get(trace[0], params=trace[1])
    assert ok.status_code == 200
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify.verify_model_dir(model_dir)

    append(model_dir / "model.pkl")  # code: refused at load
    with pytest.raises(ValueError, match="checksum mismatch for model.pkl"):
        TestClient(create_app(ArtifactStore(published))).get(trace[0], params=trace[1])


def test_publishing_checks_the_directory_before_making_it_visible(built, tmp_path, monkeypatch):
    from atlas.services import publish

    def corrupt(tmp):
        append(first_activations(tmp))

    real = layout.write_checksums
    monkeypatch.setattr(publish.layout, "write_checksums", lambda d: (real(d), corrupt(d)))
    with pytest.raises(ValueError, match="checksum mismatch"):
        publish.publish_run(
            built.run.run_dir, built.root / "features.parquet", built.root / "entities.geojson",
            built.root / "feature_spec.json", "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z",
            published_dir=tmp_path / "pub", synthetic=True)
    assert not (tmp_path / "pub" / built.run.manifest.model_id).exists()
    assert not [p for p in (tmp_path / "pub").iterdir() if p.name.startswith(".tmp-")]
