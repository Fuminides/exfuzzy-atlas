"""Contract v0.5 at publish time: input labels, territories, the new files in SHA256SUMS, and the backfill."""

import json
import shutil
from pathlib import Path

import pytest

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import enrich, layout, verify
from atlas.services.publish import main, publish_run
from atlas.services.synthetic import V04_METADATA, V04_SCHEME_METADATA, V04_TERRITORY

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


def read(model_dir, name, model):
    return model.model_validate_json((model_dir / name).read_text())


def publish_again(built, tmp_path, metadata=None, **overrides):
    args = dict(
        run_dir=built.run.run_dir, features=built.root / "features.parquet",
        entities_path=built.root / "entities.geojson", feature_spec_path=built.root / "feature_spec.json",
        period_from=START, period_to=END, published_dir=tmp_path / "published", synthetic=True,
    )
    if metadata is not None:
        path = tmp_path / "metadata.json"
        path.write_text(metadata.model_dump_json())
        args["metadata_path"] = path
    return publish_run(**{**args, **overrides})


# ---------------------------------------------------------------------------------------------- labels


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_labels_are_applied_to_the_published_rules_and_the_run_is_untouched(fixture, request):
    built = request.getfixturevalue(fixture)
    published = read(built.model_dir, "rules.json", m.ModelRules)
    shown = {v.feature: v for v in published.variables}
    assert set(shown) == set(V04_METADATA.features)
    for name, variable in shown.items():
        meta = V04_METADATA.features[name]
        assert (variable.label, variable.description) == (meta.label, meta.description)
    original = m.ModelRules.model_validate_json((built.run.run_dir / "rules.json").read_text())
    assert all(v.label is None and v.description is None for v in original.variables)
    info = json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert "variables[].label" in info["rules_json_patch"]["patched_fields"]
    assert info["rules_json_patch"]["run_rules_sha256"] == artifacts.sha256_file(built.run.run_dir / "rules.json")
    verify.verify_model_dir(built.model_dir)


def test_without_a_features_block_the_labels_stay_empty(built):
    assert all(v.label is None for v in read(built.model_dir, "rules.json", m.ModelRules).variables)


def test_a_label_for_an_input_that_is_not_in_the_feature_spec_is_refused(built, tmp_path):
    metadata = layout.PublishMetadata(features={"no_such_input": layout.FeatureMetadata(label="Nada")})
    with pytest.raises(ValueError, match="no_such_input"):
        publish_again(built, tmp_path, metadata)
    assert not (tmp_path / "published").exists() or not any((tmp_path / "published").glob("exfuzzy-*"))


def test_a_shared_metadata_file_can_skip_labels_of_inputs_this_model_lacks(built, tmp_path):
    """v0.7: opt-in (``--skip-labels-not-in-spec``) for a metadata file shared by tasks with other inputs."""
    metadata = layout.PublishMetadata(features={
        "no_such_input": layout.FeatureMetadata(label="Nada"),
        "y_lag3": layout.FeatureMetadata(label="Serie y hace 3 h", lag_hours=3)})
    summary = publish_again(built, tmp_path, metadata, skip_labels_not_in_spec=True)
    info = json.loads((summary.model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["rules_json_patch"]["labels_not_in_feature_spec"] == ["no_such_input"]
    rules = m.ModelRules.model_validate_json((summary.model_dir / "rules.json").read_text())
    assert {v.feature: v.label for v in rules.variables}["y_lag3"] == "Serie y hace 3 h"


def test_a_label_whose_stated_lag_contradicts_the_feature_spec_is_refused(built, tmp_path):
    metadata = layout.PublishMetadata(features={
        "y_lag3": layout.FeatureMetadata(label="Serie y hace 2 h", lag_hours=2)})  # the spec says 3
    with pytest.raises(ValueError, match="lag_hours=2 but the feature_spec says 3"):
        publish_again(built, tmp_path, metadata)


def test_every_shipped_label_states_the_lag_of_its_feature_spec():
    """The labels of configs/*/attribution*.json must say 'hace N h' for the lag_hours of the published spec."""
    root = Path(__file__).resolve().parents[2]
    pairs = {
        "configs/air/attribution.json": "configs/ml/madrid_no2_h6_feature_spec.json",
        "configs/air/attribution_de.json": "configs/air/de_no2_h6_feature_spec.json",
        "configs/mobility/attribution.json": "configs/mobility/feature_spec.json",
        "configs/water/attribution.json": "configs/water/feature_spec.json",
    }
    # AT-041h: "yesterday at the valid hour" has a lag of 24 - h hours; one attribution file serves every horizon, so
    # its label states no lag (the spec of each horizon does) and must not say "hace N h".
    horizon_dependent = {"no2_yday_valid"}
    for metadata_path, spec_path in pairs.items():
        metadata = layout.PublishMetadata.model_validate_json((root / metadata_path).read_text())
        spec = layout.FeatureSpec.model_validate_json((root / spec_path).read_text())
        assert metadata.features and metadata.summary is not None, metadata_path
        for name, meta in metadata.features.items():
            lag = spec.features[name].lag_hours
            if name in horizon_dependent:
                assert meta.lag_hours is None and "hace" not in meta.label and meta.description, name
                continue
            assert meta.lag_hours == lag, f"{metadata_path}: {name}"
            assert meta.description and meta.label, f"{metadata_path}: {name}"
            if "hace" in meta.label:  # the label states an age: it must be the spec's
                assert f"hace {lag:g} h" in meta.label, f"{metadata_path}: {name}: {meta.label!r}"


# ------------------------------------------------------------------------------------------- territory


def test_the_territory_is_in_the_registry_and_in_domains(built_class_v04):
    entry = layout.read_registry(built_class_v04.published_dir).tasks["synthetic_class_h6"]
    assert (entry.territory, entry.territory_title, entry.territory_title_en) == V04_TERRITORY
    from atlas_api.artifact_store import ArtifactStore

    domains = ArtifactStore(built_class_v04.published_dir).domains()
    task = next(t for d in domains.domains for t in d.tasks if t.task_id == "synthetic_class_h6")
    assert (task.territory, task.territory_title, task.territory_title_en) == V04_TERRITORY


def test_a_republish_without_a_territory_keeps_the_previous_one_and_a_title_needs_a_territory(built, tmp_path):
    publish_again(built, tmp_path, territory="synthetic", territory_title="Sintético")
    again = publish_again(built, tmp_path, replace=True)
    entry = layout.read_registry(tmp_path / "published").tasks[built.run.config.task_id]
    assert (entry.territory, entry.territory_title) == ("synthetic", "Sintético")
    assert again.model_dir.is_dir()
    with pytest.raises(ValueError, match="territory_title needs a territory"):
        publish_again(built, tmp_path, replace=True, territory_title="x")


def test_the_publish_command_takes_territory_flags(built, tmp_path):
    main([
        "--run-dir", str(built.run.run_dir), "--features", str(built.root / "features.parquet"),
        "--entities", str(built.root / "entities.geojson"), "--feature-spec", str(built.root / "feature_spec.json"),
        "--from", START, "--to", END, "--published-dir", str(tmp_path / "published"), "--synthetic",
        "--territory", "madrid", "--territory-title", "Madrid",
    ])
    entry = layout.read_registry(tmp_path / "published").tasks[built.run.config.task_id]
    assert (entry.territory, entry.territory_title) == ("madrid", "Madrid")


# --------------------------------------------------------------------------- the new files in SHA256SUMS


@pytest.mark.parametrize("fixture", ["built", "built_class"])
def test_importance_and_summary_are_published_checksummed_and_verified(fixture, request):
    built = request.getfixturevalue(fixture)
    listed = (built.model_dir / artifacts.CHECKSUM_FILE).read_text()
    for name in (layout.IMPORTANCE_FILE, layout.SUMMARY_FILE):
        assert f"  {name}\n" in listed
    verify.verify_model_dir(built.model_dir)
    record = json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())["v05"]
    assert record["importance"]["n_predicted"] > 0 and record["summary"]["n"] > 0


def test_verify_catches_a_modified_importance_file(built_class, tmp_path):
    copy = tmp_path / built_class.model_dir.name
    shutil.copytree(built_class.model_dir, copy)
    (copy / layout.IMPORTANCE_FILE).write_text((copy / layout.IMPORTANCE_FILE).read_text().replace('"R01"', '"R99"', 1))
    with pytest.raises(ValueError, match="checksum mismatch for importance.json"):
        verify.verify_model_dir(copy)


# ------------------------------------------------------------------------------------------- the backfill


def rounded(value):
    """``value`` (parsed JSON) with every float rounded to 9 digits."""
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, list):
        return [rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    return value


def as_published_before_v05(built, tmp_path):
    """A published directory the way v0.4 left it: no importance, no summary, no labels, no territory."""
    root = tmp_path / "published"
    shutil.copytree(built.published_dir, root)
    model_dir = root / built.model_dir.name
    for name in (layout.IMPORTANCE_FILE, layout.SUMMARY_FILE):
        (model_dir / name).unlink()
    rules = read(model_dir, "rules.json", m.ModelRules)
    unlabelled = [v.model_copy(update={"label": None, "description": None}) for v in rules.variables]
    stripped = rules.model_copy(update={"variables": unlabelled})
    (model_dir / "rules.json").write_text(stripped.model_dump_json(indent=2) + "\n")
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    info.pop("v05")
    (model_dir / layout.PUBLISH_INFO_FILE).write_text(json.dumps(info))
    registry = layout.read_registry(root)
    for entry in registry.tasks.values():
        entry.territory = entry.territory_title = None
    layout.write_registry(root, registry)
    layout.write_checksums(model_dir)
    verify.verify_model_dir(model_dir)
    return root, model_dir


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_the_backfill_adds_the_v05_files_labels_and_territory_and_keeps_verify_ok(fixture, request, tmp_path):
    built = request.getfixturevalue(fixture)
    root, model_dir = as_published_before_v05(built, tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(layout.PublishMetadata(
        features=V04_METADATA.features, summary=V04_METADATA.summary, target_scheme=V04_SCHEME_METADATA,
    ).model_dump_json())
    before = {p.name: artifacts.sha256_file(p) for p in model_dir.iterdir() if p.is_file()}
    before_info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    record = enrich.backfill(root, model_dir.name, metadata_path=metadata, territory="synthetic",
                             territory_title="Sintético")
    verify.verify_model_dir(model_dir)
    # the same numbers as a publish computes (a mean may differ in its last bit: DuckDB sums in parallel)
    for name in (layout.IMPORTANCE_FILE, layout.SUMMARY_FILE):
        assert rounded(json.loads((model_dir / name).read_text())) == rounded(
            json.loads((built.model_dir / name).read_text()))
    rules = read(model_dir, "rules.json", m.ModelRules)
    assert {v.feature: v.label for v in rules.variables} == {
        v.feature: V04_METADATA.features[v.feature].label for v in rules.variables}
    assert record["rules_json_patch_v05"]["previous_rules_sha256"] == before["rules.json"]
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["v05"]["backfilled_at_utc"] and info["v05"]["importance"] == record["importance"]
    assert info["rules_json_patch"] == before_info["rules_json_patch"]  # the v0.4 record is kept as it was
    entry = layout.read_registry(root).tasks[built.run.config.task_id]
    assert (entry.territory, entry.territory_title) == ("synthetic", "Sintético")
    # nothing else changed: model, predictions, activations, inputs
    for name in ("model.pkl", "run_manifest.json", "card.json", "predictions.parquet", "inputs.parquet",
                 "entities.geojson"):
        assert artifacts.sha256_file(model_dir / name) == before[name], name
    assert not [p for p in root.iterdir() if p.name.startswith(".")]  # no staging left behind


def test_the_backfill_refuses_an_unknown_label_and_leaves_the_model_as_it_was(built_class_v04, tmp_path):
    root, model_dir = as_published_before_v05(built_class_v04, tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(layout.PublishMetadata(features={"nope": layout.FeatureMetadata(label="x")}).model_dump_json())
    before = (model_dir / artifacts.CHECKSUM_FILE).read_text()
    with pytest.raises(ValueError, match="nope"):
        enrich.backfill(root, model_dir.name, metadata_path=metadata)
    assert (model_dir / artifacts.CHECKSUM_FILE).read_text() == before
    assert not (model_dir / layout.IMPORTANCE_FILE).exists()
    verify.verify_model_dir(model_dir)
    assert not [p for p in root.iterdir() if p.name.startswith(".")]


def test_the_backfill_refuses_a_directory_that_does_not_verify(built_class_v04, tmp_path):
    root, model_dir = as_published_before_v05(built_class_v04, tmp_path)
    (model_dir / "card.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum mismatch"):
        enrich.backfill(root, model_dir.name)


def test_the_backfill_command_runs_on_a_published_directory(built_class_v04, tmp_path, capsys):
    root, model_dir = as_published_before_v05(built_class_v04, tmp_path)
    enrich.main(["--published-dir", str(root), "--territory", "synthetic", "--territory-title", "Sintético"])
    assert json.loads(capsys.readouterr().out)["model_id"] == model_dir.name
    verify.verify_model_dir(model_dir)
    assert (model_dir / layout.IMPORTANCE_FILE).is_file()
