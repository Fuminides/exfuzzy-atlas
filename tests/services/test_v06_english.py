"""Contract v0.6: English display fields applied by publish and by the backfill (``--labels-only``), display only."""

import json
import shutil
from pathlib import Path

import pytest
from test_v05_enrich import publish_again, read

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import enrich, layout, verify
from atlas.services.publish import main
from atlas.services.synthetic import TERMS_EN, V04_METADATA, V04_SCHEME_METADATA, V04_TERRITORY

REPO = Path(__file__).resolve().parents[2]
DISPLAY_EN = {"low": "low (made up)", "mid": "medium (made up)", "high": "high (made up)"}


def spec_with(**lags):
    return layout.FeatureSpec(features={n: layout.FeatureSource(source_id="s", lag_hours=h) for n, h in lags.items()})


def rules_with(feature):
    term = m.LinguisticTerm(name="Low", membership_type="trapezoidal", params=[0, 0, 1, 2])
    return m.ModelRules.model_validate_json((REPO / "fixtures/synthetic/model_rules.json").read_text()).model_copy(
        update={"variables": [m.LinguisticVariable(feature=feature, terms=[term])], "rules": []})


# ----------------------------------------------------------------------------------------------- publish


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_publish_sets_the_english_input_and_term_labels(fixture, request):
    built = request.getfixturevalue(fixture)
    published = read(built.model_dir, "rules.json", m.ModelRules)
    original = m.ModelRules.model_validate_json((built.run.run_dir / "rules.json").read_text())
    for v in published.variables:
        meta = V04_METADATA.features[v.feature]
        assert (v.label_en, v.description_en) == (meta.label_en, meta.description_en)
        assert all(t.label_en == TERMS_EN[t.name] for t in v.terms)
    assert published.rules == original.rules
    summary = read(built.model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
    assert (summary.label, summary.label_en) == (V04_METADATA.summary.label, V04_METADATA.summary.label_en)
    info = json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert "variables[].label_en" in info["rules_json_patch"]["patched_fields"]
    verify.verify_model_dir(built.model_dir)


def test_publish_sets_the_english_class_and_scheme_names_in_rules_card_and_summary(built_class_v04):
    rules = read(built_class_v04.model_dir, "rules.json", m.ModelRules)
    card = read(built_class_v04.model_dir, layout.CARD_FILE, m.ModelCard)
    summary = read(built_class_v04.model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
    for scheme in (rules.target_scheme, card.target_scheme):
        assert {c.label: c.display_label_en for c in scheme.classes} == DISPLAY_EN
        assert (scheme.name_en, scheme.short_name_en) == (
            V04_SCHEME_METADATA.name_en, V04_SCHEME_METADATA.short_name_en)
        high = next(c for c in scheme.classes if c.label == "high")
        assert high.description_en == "made up: groups two made-up bands"
    assert [(c.label, c.display_label_en) for c in summary.classes] == list(DISPLAY_EN.items())


def test_publish_takes_territory_title_en_and_it_needs_a_territory(built, tmp_path):
    main([
        "--run-dir", str(built.run.run_dir), "--features", str(built.root / "features.parquet"),
        "--entities", str(built.root / "entities.geojson"), "--feature-spec", str(built.root / "feature_spec.json"),
        "--from", "2024-01-05T00:00:00Z", "--to", "2024-02-14T23:00:00Z", "--published-dir",
        str(tmp_path / "published"), "--synthetic", "--territory", "germany", "--territory-title", "Alemania",
        "--territory-title-en", "Germany",
    ])
    entry = layout.read_registry(tmp_path / "published").tasks[built.run.config.task_id]
    assert (entry.territory, entry.territory_title, entry.territory_title_en) == ("germany", "Alemania", "Germany")
    publish_again(built, tmp_path, replace=True)  # a republish without a territory keeps the English title too
    entry = layout.read_registry(tmp_path / "published").tasks[built.run.config.task_id]
    assert entry.territory_title_en == "Germany"
    with pytest.raises(ValueError, match="territory_title_en needs a territory"):
        publish_again(built, tmp_path, replace=True, territory_title_en="x")


# ----------------------------------------------------------------------------------- the guards on label_en


def test_an_english_label_whose_age_contradicts_the_feature_spec_is_refused():
    features = {"no2_lag3h": layout.FeatureMetadata(label="NO₂ hace 4 h", lag_hours=4, label_en="NO₂ 3 h ago")}
    with pytest.raises(ValueError, match="says 3 h ago but the feature_spec says lag_hours=4"):
        enrich.apply_feature_labels(rules_with("no2_lag3h"), features, spec_with(no2_lag3h=4))


def test_an_english_label_that_states_another_age_than_the_spanish_one_is_refused():
    features = {"x": layout.FeatureMetadata(label="Viento (m/s)", lag_hours=1, label_en="Wind 1 h ago (m/s)")}
    with pytest.raises(ValueError, match="state different ages"):
        enrich.apply_feature_labels(rules_with("x"), features, spec_with(x=1))
    features = {"x": layout.FeatureMetadata(label="Viento hace 1 h", lag_hours=1, label_en="Wind (m/s)")}
    with pytest.raises(ValueError, match="state different ages"):
        enrich.apply_feature_labels(rules_with("x"), features, spec_with(x=1))


def test_an_english_label_that_agrees_is_applied():
    features = {"no2_lag3h": layout.FeatureMetadata(label="NO₂ hace 4 h", lag_hours=4, label_en="NO₂ 4 h ago",
                                                    description_en="d", terms_en={"Low": "low"})}
    rules, labelled = enrich.apply_feature_labels(rules_with("no2_lag3h"), features, spec_with(no2_lag3h=4))
    v = rules.variables[0]
    assert labelled == ["no2_lag3h"]
    assert (v.label_en, v.description_en, v.terms[0].label_en) == ("NO₂ 4 h ago", "d", "low")
    assert v.terms[0].label is None  # an English term label does not need a Spanish one


def test_the_lag_guard_on_label_en_refuses_a_publish(built, tmp_path):
    features = dict(V04_METADATA.features)
    features["y_lag3"] = features["y_lag3"].model_copy(update={"label_en": "Series y 2 h ago (made up)"})
    with pytest.raises(ValueError, match="says 2 h ago but the feature_spec says lag_hours=3"):
        publish_again(built, tmp_path, V04_METADATA.model_copy(update={"features": features}))
    assert not (tmp_path / "published").exists() or not any((tmp_path / "published").glob("exfuzzy-*"))


def test_an_english_term_label_for_a_term_the_variable_does_not_have_is_refused(built, tmp_path):
    features = dict(V04_METADATA.features)
    features["y_t"] = features["y_t"].model_copy(update={"terms_en": {"Very high": "x"}})
    with pytest.raises(ValueError, match=r"y_t: term labels name terms .* \['Very high'\]"):
        publish_again(built, tmp_path, V04_METADATA.model_copy(update={"features": features}))


# ------------------------------------------------------------------------------- the --labels-only backfill


def without_english(built, tmp_path):
    """A copy of the published directory as v0.5.2 left it: every English field null, checksums valid."""
    root = tmp_path / "published"
    shutil.copytree(built.published_dir, root)
    model_dir = root / built.model_dir.name
    rules = read(model_dir, "rules.json", m.ModelRules)
    variables = [v.model_copy(update={"label_en": None, "description_en": None,
                                      "terms": [t.model_copy(update={"label_en": None}) for t in v.terms]})
                 for v in rules.variables]
    scheme = rules.target_scheme
    if scheme is not None:
        scheme = scheme.model_copy(update={"name_en": None, "short_name_en": None, "classes": [
            c.model_copy(update={"display_label_en": None, "description_en": None}) for c in scheme.classes]})
        card = read(model_dir, layout.CARD_FILE, m.ModelCard)
        (model_dir / layout.CARD_FILE).write_text(card.model_copy(update={"target_scheme": scheme}).model_dump_json())
    (model_dir / "rules.json").write_text(
        rules.model_copy(update={"variables": variables, "target_scheme": scheme}).model_dump_json(indent=2))
    summary = read(model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
    summary = summary.model_copy(update={"label_en": None, "classes": None if summary.classes is None else [
        c.model_copy(update={"display_label_en": None, "description_en": None}) for c in summary.classes]})
    (model_dir / layout.SUMMARY_FILE).write_text(summary.model_dump_json(indent=2))
    registry = layout.read_registry(root)
    for entry in registry.tasks.values():
        entry.territory_title_en = None
    layout.write_registry(root, registry)
    layout.write_checksums(model_dir)
    verify.verify_model_dir(model_dir)
    return root, model_dir


def numbers(summary: m.SummaryResponse) -> dict:
    return summary.model_dump(mode="json", exclude={"label", "label_en", "classes"})


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_the_labels_only_backfill_adds_the_english_and_changes_no_number(fixture, request, tmp_path):
    built = request.getfixturevalue(fixture)
    root, model_dir = without_english(built, tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(V04_METADATA.model_copy(update={"target_scheme": V04_SCHEME_METADATA}).model_dump_json())
    before = {p.name: artifacts.sha256_file(p) for p in model_dir.iterdir() if p.is_file()}
    summary_before = read(model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
    rules_before = read(model_dir, "rules.json", m.ModelRules)
    enrich.main(["--published-dir", str(root), "--model-id", model_dir.name, "--metadata", str(metadata),
                 "--labels-only", "--territory", V04_TERRITORY[0], "--territory-title", V04_TERRITORY[1],
                 "--territory-title-en", V04_TERRITORY[2], "--features", "/nonexistent/never/read.parquet"])
    verify.verify_model_dir(model_dir)
    # the English is there, as a publish writes it
    for name in ("rules.json", layout.SUMMARY_FILE):
        assert json.loads((model_dir / name).read_text()) == json.loads((built.model_dir / name).read_text()), name
    if built.run.rules.target_scheme is not None:
        assert read(model_dir, layout.CARD_FILE, m.ModelCard).target_scheme == read(
            built.model_dir, layout.CARD_FILE, m.ModelCard).target_scheme
    entry = layout.read_registry(root).tasks[built.run.config.task_id]
    assert (entry.territory, entry.territory_title, entry.territory_title_en) == V04_TERRITORY
    # and no number, rule or prediction changed
    assert numbers(read(model_dir, layout.SUMMARY_FILE, m.SummaryResponse)) == numbers(summary_before)
    assert read(model_dir, "rules.json", m.ModelRules).rules == rules_before.rules
    for name in ("model.pkl", "importance.json", "predictions.parquet", "inputs.parquet", "entities.geojson",
                 "run_manifest.json"):
        assert artifacts.sha256_file(model_dir / name) == before[name], name
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["v06"]["rules_json_patch"]["previous_rules_sha256"] == before["rules.json"]
    assert info["v05"] == json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())["v05"]
    assert not [p for p in root.iterdir() if p.name.startswith(".")]


def test_the_labels_only_backfill_refuses_a_bad_english_label_and_leaves_the_model_as_it_was(built_v04, tmp_path):
    root, model_dir = without_english(built_v04, tmp_path)
    features = dict(V04_METADATA.features)
    features["y_lag3"] = features["y_lag3"].model_copy(update={"label_en": "Series y 4 h ago"})
    metadata = tmp_path / "metadata.json"
    metadata.write_text(V04_METADATA.model_copy(update={"features": features}).model_dump_json())
    before = (model_dir / artifacts.CHECKSUM_FILE).read_text()
    with pytest.raises(ValueError, match="4 h ago"):
        enrich.backfill(root, model_dir.name, metadata_path=metadata, labels_only=True)
    assert (model_dir / artifacts.CHECKSUM_FILE).read_text() == before
    verify.verify_model_dir(model_dir)


# ------------------------------------------------------------------------------------- the shipped configs


CONFIGS = {
    "configs/air/attribution.json": "configs/ml/madrid_no2_h6_feature_spec.json",
    "configs/air/attribution_de.json": "configs/air/de_no2_h6_feature_spec.json",
    "configs/mobility/attribution.json": "configs/mobility/feature_spec.json",
    "configs/water/attribution.json": "configs/water/feature_spec.json",
}


@pytest.mark.parametrize("metadata_path", sorted(CONFIGS))
def test_every_shipped_spanish_label_has_its_english(metadata_path):
    metadata = layout.PublishMetadata.model_validate_json((REPO / metadata_path).read_text())
    spec = layout.FeatureSpec.model_validate_json((REPO / CONFIGS[metadata_path]).read_text())
    for name, meta in metadata.features.items():
        assert meta.label_en and meta.description_en, f"{metadata_path}: {name}"
        assert set(meta.terms) <= set(meta.terms_en), f"{metadata_path}: {name}: a Spanish term label has no English"
        stated = enrich._stated_age(enrich._AGE_EN, meta.label_en)
        assert stated == enrich._stated_age(enrich._AGE_ES, meta.label), f"{metadata_path}: {name}"
        assert stated is None or stated == spec.features[name].lag_hours, f"{metadata_path}: {name}"
        assert "hace" not in meta.label_en.lower() and "ago" not in meta.label.lower()
    assert metadata.summary.label_en, metadata_path
    if metadata.target_scheme is not None:
        assert metadata.target_scheme.name_en and metadata.target_scheme.short_name_en, metadata_path
        for label, c in metadata.target_scheme.classes.items():
            assert c.display_label_en, f"{metadata_path}: {label}"
            assert not c.description or c.description_en, f"{metadata_path}: {label}"
