"""Contract v0.5.1: term and class display labels are applied by publish and by the backfill, and are display only."""

import json
import os
import shutil
from pathlib import Path

import pytest
from test_v05_enrich import as_published_before_v05, publish_again, read

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import enrich, layout, verify
from atlas.services.synthetic import TERMS, V04_METADATA, V04_SCHEME_METADATA

DISPLAY = {"low": "baja (inventada)", "mid": "media (inventada)", "high": "alta (inventada)"}


def term_labels(rules):
    return {(v.feature, t.name): t.label for v in rules.variables for t in v.terms}


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_publish_sets_the_term_labels_and_changes_no_key_rule_or_prediction(fixture, request):
    built = request.getfixturevalue(fixture)
    published = read(built.model_dir, "rules.json", m.ModelRules)
    original = m.ModelRules.model_validate_json((built.run.run_dir / "rules.json").read_text())
    labels = term_labels(published)
    assert labels and all(label == TERMS[name] for (_, name), label in labels.items())
    assert all(t.label is None for v in original.variables for t in v.terms)
    # display only: the same rules and the same terms (name, shape)
    assert published.rules == original.rules
    assert [(v.feature, [(t.name, t.membership_type, t.params) for t in v.terms]) for v in published.variables] == [
        (v.feature, [(t.name, t.membership_type, t.params) for t in v.terms]) for v in original.variables]
    info = json.loads((built.model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert "variables[].terms[].label" in info["rules_json_patch"]["patched_fields"]
    verify.verify_model_dir(built.model_dir)


def test_publish_sets_the_class_display_labels_in_rules_card_and_summary(built_class_v04):
    rules = read(built_class_v04.model_dir, "rules.json", m.ModelRules)
    card = read(built_class_v04.model_dir, layout.CARD_FILE, m.ModelCard)
    summary = read(built_class_v04.model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
    for scheme in (rules.target_scheme, card.target_scheme):
        assert {c.label: c.display_label for c in scheme.classes} == DISPLAY
    assert [(c.label, c.display_label) for c in summary.classes] == list(DISPLAY.items())
    original = m.ModelRules.model_validate_json((built_class_v04.run.run_dir / "rules.json").read_text())
    assert all(c.display_label is None for c in original.target_scheme.classes)
    assert [c.label for c in rules.target_scheme.classes] == [c.label for c in original.target_scheme.classes]
    assert rules.rules == original.rules


def test_a_term_label_for_a_term_the_variable_does_not_have_is_refused_at_publish(built, tmp_path):
    features = dict(V04_METADATA.features)
    features["y_t"] = features["y_t"].model_copy(update={"terms": {"Low": "baja", "Muy alta": "x"}})
    with pytest.raises(ValueError, match=r"y_t: term labels name terms .* \['Muy alta'\]"):
        publish_again(built, tmp_path, V04_METADATA.model_copy(update={"features": features}))
    assert not (tmp_path / "published").exists() or not any((tmp_path / "published").glob("exfuzzy-*"))


def test_a_class_display_label_for_an_unknown_class_is_refused_at_publish(built_class, tmp_path):
    scheme = V04_SCHEME_METADATA.model_copy(update={"classes": {"nope": layout.ClassMetadata(display_label="x")}})
    with pytest.raises(ValueError, match="nope"):
        publish_again(built_class, tmp_path, V04_METADATA.model_copy(update={"target_scheme": scheme}))


# ------------------------------------------------------------------------------------------- the backfill


@pytest.mark.parametrize("fixture", ["built_v04", "built_class_v04"])
def test_the_backfill_applies_term_and_class_labels_and_never_writes_through_a_hard_link(fixture, request, tmp_path):
    built = request.getfixturevalue(fixture)
    source, source_dir = as_published_before_v05(built, tmp_path / "a")
    root = tmp_path / "linked"
    shutil.copytree(source, root, copy_function=os.link)  # what `cp -al` does: every file is a second name
    model_dir = root / source_dir.name
    before = {p.name: artifacts.sha256_file(p) for p in source_dir.iterdir() if p.is_file()}
    metadata = tmp_path / "metadata.json"
    metadata.write_text(V04_METADATA.model_copy(update={"target_scheme": V04_SCHEME_METADATA}).model_dump_json())

    record = enrich.backfill(root, model_dir.name, metadata_path=metadata)

    verify.verify_model_dir(model_dir)
    rules = read(model_dir, "rules.json", m.ModelRules)
    assert all(label == TERMS[name] for (_, name), label in term_labels(rules).items()) and term_labels(rules)
    assert record["rules_json_patch_v05"]["n_term_labels"] == len(term_labels(rules))
    if rules.target_scheme is not None:
        assert {c.label: c.display_label for c in rules.target_scheme.classes} == DISPLAY
        card = read(model_dir, layout.CARD_FILE, m.ModelCard)
        assert {c.label: c.display_label for c in card.target_scheme.classes} == DISPLAY
        summary = read(model_dir, layout.SUMMARY_FILE, m.SummaryResponse)
        assert [(c.label, c.display_label) for c in summary.classes] == list(DISPLAY.items())
        assert record["rules_json_patch_v05"]["class_display_labels"] == list(DISPLAY)
    # display only: rules, predictions and activations are what they were
    assert rules.rules == read(source_dir, "rules.json", m.ModelRules).rules
    for name in ("model.pkl", "predictions.parquet", "inputs.parquet"):
        assert artifacts.sha256_file(model_dir / name) == before[name], name
    # the original names of the hard-linked source were not written through
    assert {p.name: artifacts.sha256_file(p) for p in source_dir.iterdir() if p.is_file()} == before
    verify.verify_model_dir(source_dir)


def test_the_backfill_is_idempotent(built_class_v04, tmp_path):
    root, model_dir = as_published_before_v05(built_class_v04, tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(V04_METADATA.model_copy(update={"target_scheme": V04_SCHEME_METADATA}).model_dump_json())
    enrich.backfill(root, model_dir.name, metadata_path=metadata)
    first = (model_dir / "rules.json").read_text(), (model_dir / layout.CARD_FILE).read_text()
    enrich.backfill(root, model_dir.name, metadata_path=metadata)
    assert ((model_dir / "rules.json").read_text(), (model_dir / layout.CARD_FILE).read_text()) == first
    verify.verify_model_dir(model_dir)


def test_the_backfill_refuses_an_unknown_term_or_class_and_leaves_the_model_as_it_was(built_class_v04, tmp_path):
    root, model_dir = as_published_before_v05(built_class_v04, tmp_path)
    before = (model_dir / artifacts.CHECKSUM_FILE).read_text()
    features = dict(V04_METADATA.features)
    features["hour"] = features["hour"].model_copy(update={"terms": {"Noon": "mediodía"}})
    bad_term = V04_METADATA.model_copy(update={"features": features})
    scheme = V04_SCHEME_METADATA.model_copy(update={"classes": {"nope": layout.ClassMetadata(display_label="x")}})
    bad_class = V04_METADATA.model_copy(update={"target_scheme": scheme})
    for name, metadata, pattern in (("term", bad_term, "Noon"), ("class", bad_class, "nope")):
        path = tmp_path / f"{name}.json"
        path.write_text(metadata.model_dump_json())
        with pytest.raises(ValueError, match=pattern):
            enrich.backfill(root, model_dir.name, metadata_path=path)
        assert (model_dir / artifacts.CHECKSUM_FILE).read_text() == before
        assert not (model_dir / layout.IMPORTANCE_FILE).exists()
        verify.verify_model_dir(model_dir)
        assert not [p for p in root.iterdir() if p.name.startswith(".")]


# --------------------------------------------------------------------------------------- shipped metadata


CONFIGS = Path(__file__).resolve().parents[2] / "configs"


def load(name):
    return layout.PublishMetadata.model_validate_json((CONFIGS / name).read_text())


def test_germany_ships_spanish_class_names_that_are_not_the_ica_ones():
    de, ica = load("air/attribution_de.json"), load("air/attribution.json")
    assert {k: v.display_label for k, v in de.target_scheme.classes.items()} == {
        "Good": "Buena", "Fair": "Aceptable", "Moderate": "Moderada", "Poor or worse": "Mala o peor"}
    # the same four labels name the NO2 input terms, which are the EAQI classes
    for feature in ("no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h"):
        assert de.features[feature].terms == {
            "Good": "Buena", "Fair": "Aceptable", "Moderate": "Moderada", "Poor or worse": "Mala o peor"}
    assert all(c.display_label is None for c in ica.target_scheme.classes.values())  # already Spanish: keys are shown


def test_water_ships_a_label_for_every_cryptic_term():
    water = load("water/attribution.json")
    for feature in ("ammoniacal_nitrogen", "orthophosphate_reactive"):
        assert water.features[feature].terms == {
            "<=L": "≤ límite de detección", "Bajo>L": "baja (sobre el límite)",
            "Medio>L": "media (sobre el límite)", "Alto>L": "alta (sobre el límite)"}
    for feature in ("water_temperature", "ph", "local_hour"):
        assert set(water.features[feature].terms) == {"Low", "Medium", "High"}


def test_no_shipped_term_label_repeats_its_term_name_or_is_empty():
    for name in ("air/attribution.json", "air/attribution_de.json", "water/attribution.json",
                 "mobility/attribution.json"):
        for feature, meta in load(name).features.items():
            for term, label in meta.terms.items():
                assert label.strip() and label != term, f"{name}: {feature}: {term}"
