"""Contract v0.4 at publish time: attribution, regular flag, scheme kind and merged classes, unmodelled entities."""

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import layout
from atlas.services.publish import apply_scheme_metadata, main, publish_run
from atlas.services.synthetic import V04_METADATA, V04_SCHEME_METADATA

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


def read(model_dir, name, model):
    return model.model_validate_json((model_dir / name).read_text())


def publish_again(built, tmp_path, **overrides):
    args = dict(
        run_dir=built.run.run_dir, features=built.root / "features.parquet",
        entities_path=built.root / "entities.geojson", feature_spec_path=built.root / "feature_spec.json",
        period_from=START, period_to=END, published_dir=tmp_path / "published",
    )
    args.update(overrides)
    return publish_run(**args)


def test_a_default_publish_marks_entities_modelled_and_has_no_credits(built):
    entities = read(built.model_dir, layout.ENTITIES_FILE, m.EntityCollection)
    assert {f.properties.modelled for f in entities.features} == {True}
    assert entities.attribution == [] and read(built.model_dir, layout.CARD_FILE, m.ModelCard).attribution == []
    assert read(built.model_dir, layout.CARD_FILE, m.ModelCard).coverage.regular is True
    assert json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())["rules_json_patch"] is None


def test_unmodelled_entities_are_published_with_the_flag_and_no_data(built_v04):
    entities = read(built_v04.model_dir, layout.ENTITIES_FILE, m.EntityCollection)
    flags = {f.properties.entity_id: f.properties.modelled for f in entities.features}
    assert flags == {"E0": True, "E1": True, "E2": True, "E9": False}
    for name in (layout.INPUTS_FILE, layout.PREDICTIONS_FILE):
        assert set(pq.read_table(built_v04.model_dir / name, columns=["entity_id"]).column(0).to_pylist()) == {
            "E0", "E1", "E2"}
    activations = pq.read_table(built_v04.model_dir / layout.ACTIVATIONS_DIR, columns=["entity_id"])
    assert "E9" not in set(activations.column(0).to_pylist())
    info = json.loads((built_v04.model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["entities"] == ["E0", "E1", "E2"]  # the entities with data, not the unmodelled one


def test_without_the_option_an_entity_without_data_is_not_published(built, tmp_path):
    extra = m.EntityCollection.model_validate_json((built.model_dir / layout.ENTITIES_FILE).read_text())
    feature = extra.features[0].model_copy(update={
        "id": "E9", "properties": extra.features[0].properties.model_copy(update={"entity_id": "E9"})})
    path = tmp_path / "entities.geojson"
    path.write_text(extra.model_copy(update={"features": [*extra.features, feature]}).model_dump_json())
    summary = publish_again(built, tmp_path, entities_path=path)
    ids = {f.properties.entity_id for f in read(summary.model_dir, layout.ENTITIES_FILE, m.EntityCollection).features}
    assert ids == {"E0", "E1", "E2"}


def test_an_unmodelled_entity_without_geometry_is_not_published(built, tmp_path):
    base = m.EntityCollection.model_validate_json((built.model_dir / layout.ENTITIES_FILE).read_text())
    first = base.features[0]
    nowhere = first.model_copy(update={
        "id": "E8", "geometry": None, "properties": first.properties.model_copy(update={"entity_id": "E8"})})
    path = tmp_path / "entities.geojson"
    path.write_text(base.model_copy(update={"features": [*base.features, nowhere]}).model_dump_json())
    summary = publish_again(built, tmp_path, entities_path=path, include_unmodelled_entities=True)
    ids = {f.properties.entity_id for f in read(summary.model_dir, layout.ENTITIES_FILE, m.EntityCollection).features}
    assert ids == {"E0", "E1", "E2"}


def test_attribution_goes_to_the_entities_and_the_card(built_v04):
    expected = V04_METADATA.attribution
    assert read(built_v04.model_dir, layout.ENTITIES_FILE, m.EntityCollection).attribution == expected
    assert read(built_v04.model_dir, layout.CARD_FILE, m.ModelCard).attribution == expected
    artifacts.verify_checksums(built_v04.model_dir)


def test_irregular_times_set_regular_false(built, tmp_path):
    summary = publish_again(built, tmp_path, irregular_times=True)
    assert summary.coverage.regular is False and summary.coverage.step_hours == 1
    card = read(summary.model_dir, layout.CARD_FILE, m.ModelCard)
    assert card.coverage.regular is False and any("irregular" in w for w in card.manifest.warnings)


def test_scheme_metadata_patches_only_the_published_copy_of_rules(built_class_v04):
    model_dir, run_dir = built_class_v04.model_dir, built_class_v04.run.run_dir
    run_rules = m.ModelRules.model_validate_json((run_dir / "rules.json").read_text())
    published = read(model_dir, "rules.json", m.ModelRules)
    scheme, original = published.target_scheme, run_rules.target_scheme
    assert (scheme.kind, scheme.short_name) == (m.SchemeKind.ANALYTICAL, "synthetic")
    assert (original.kind, original.short_name) == (None, None)  # the run is untouched: nothing was retrained
    high = {c.label: c for c in scheme.classes}["high"]
    assert high.merged_from == ["very high (invented)", "extreme (invented)"] and "groups two" in high.description
    # labels, bounds and colours are the run's own
    assert [(c.label, c.lower, c.upper, c.color) for c in scheme.classes] == [
        (c.label, c.lower, c.upper, c.color) for c in original.classes]
    assert [r.model_dump() for r in published.rules] == [r.model_dump() for r in run_rules.rules]
    assert read(model_dir, layout.CARD_FILE, m.ModelCard).target_scheme == scheme
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["rules_json_patch"]["run_rules_sha256"] == artifacts.sha256_file(run_dir / "rules.json")
    artifacts.verify_checksums(model_dir)  # the published directory is self-consistent
    artifacts.verify_checksums(run_dir)  # and the run still verifies


def test_apply_scheme_metadata_rejects_unknown_classes(built_class):
    scheme = built_class.run.rules.target_scheme
    bad = layout.SchemeMetadata(kind="analytical", short_name="x", classes={"nope": layout.ClassMetadata()})
    with pytest.raises(ValueError, match="not in the target_scheme"):
        apply_scheme_metadata(scheme, bad)
    patched = apply_scheme_metadata(scheme, V04_SCHEME_METADATA)
    assert patched.kind == m.SchemeKind.ANALYTICAL and scheme.kind is None  # the input is not mutated


def test_a_scheme_block_for_a_regressor_is_refused_before_writing_anything(built, tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(layout.PublishMetadata(target_scheme=V04_SCHEME_METADATA).model_dump_json())
    with pytest.raises(ValueError, match="not a classifier"):
        publish_again(built, tmp_path, metadata_path=path)
    assert not (tmp_path / "published").exists()


def test_unknown_metadata_keys_are_refused(built, tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"attribution": [], "licence": "typo"}))
    with pytest.raises(ValueError):
        publish_again(built, tmp_path, metadata_path=path)


def test_cli_options(built_class, tmp_path, capsys):
    path = tmp_path / "metadata.json"
    path.write_text(layout.PublishMetadata(attribution=V04_METADATA.attribution,
                                           target_scheme=V04_SCHEME_METADATA).model_dump_json())
    main([
        "--run-dir", str(built_class.run.run_dir), "--features", str(built_class.root / "features.parquet"),
        "--entities", str(built_class.root / "entities.geojson"),
        "--feature-spec", str(built_class.root / "feature_spec.json"), "--from", START, "--to", END,
        "--published-dir", str(tmp_path / "published"), "--metadata", str(path), "--include-unmodelled-entities",
    ])
    out = json.loads(capsys.readouterr().out)
    card = read(tmp_path / "published" / built_class.run.manifest.model_id, layout.CARD_FILE, m.ModelCard)
    assert card.target_scheme.kind == m.SchemeKind.ANALYTICAL and card.attribution and out["entities"] == 3


REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("domain", ["air", "mobility", "water"])
def test_shipped_attribution_configs_are_valid_publish_metadata(domain):
    meta = layout.PublishMetadata.model_validate_json((REPO / "configs" / domain / "attribution.json").read_text())
    assert meta.attribution and all(a.text for a in meta.attribution)
    # a source without an explicit licence says so in words, not with a made-up licence
    assert all(a.license or "licencia" in a.text.lower() or "licence" in a.text.lower() for a in meta.attribution)
    assert (meta.target_scheme is None) == (domain == "water")


def test_the_ica_merged_class_names_exactly_the_official_bands_it_groups():
    meta = layout.PublishMetadata.model_validate_json((REPO / "configs/air/attribution.json").read_text())
    official = json.loads((REPO / "configs/ml/ica_no2_scheme.json").read_text())["classes"]
    bands = {c["label"]: (c["lower"], c["upper"]) for c in official}
    merged = meta.target_scheme.classes["Desfavorable o peor"].merged_from
    assert merged == ["Desfavorable", "Muy desfavorable", "Extremadamente desfavorable"]
    assert [bands[label] for label in merged] == [(121, 230), (231, 340), (341, 1000)]  # the 121-1000 of the class
    description = meta.target_scheme.classes["Desfavorable o peor"].description
    assert all(f"«{label}»" in description for label in merged)
    assert meta.target_scheme.kind == m.SchemeKind.OFFICIAL_INDEX and meta.target_scheme.short_name == "ICA"
    nyc = layout.PublishMetadata.model_validate_json((REPO / "configs/mobility/attribution.json").read_text())
    assert nyc.target_scheme.kind == m.SchemeKind.PERCENTILE_REFERENCE
    assert any(a.license is None and "licencia" in a.text for a in nyc.attribution)  # the TLC has no explicit licence
