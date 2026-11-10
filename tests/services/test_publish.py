"""AT-045 publish step: layout, checksums, atomicity, refusals. Synthetic data only."""

import json
import shutil

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from atlas.contracts import models as m
from atlas.explain import firing_table
from atlas.ml import artifacts
from atlas.services import layout
from atlas.services.publish import main, publish_run

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


def publish_again(built, published_dir, **overrides):
    """Publish the session's run again into ``published_dir`` (cheap: a fraction of a second)."""
    args = dict(
        run_dir=built.run.run_dir, features=built.root / "features.parquet",
        entities_path=built.root / "entities.geojson", feature_spec_path=built.root / "feature_spec.json",
        period_from=START, period_to=END, published_dir=published_dir,
    )
    args.update(overrides)
    return publish_run(**args)


def period_rows(built):
    table = built.table
    return table[(table["issued_at_utc"] >= pd.Timestamp(START)) & (table["issued_at_utc"] < pd.Timestamp(END))]


def test_layout_checksums_registry_and_card(built):
    model_dir, manifest = built.model_dir, built.run.manifest
    for name in [*layout.RUN_FILES, layout.ENTITIES_FILE, layout.INPUTS_FILE, layout.PREDICTIONS_FILE,
                 layout.FEATURE_SPEC_FILE, layout.CARD_FILE, layout.PUBLISH_INFO_FILE, artifacts.CHECKSUM_FILE]:
        assert (model_dir / name).is_file(), name
    parts = sorted(p.relative_to(model_dir).as_posix() for p in (model_dir / "activations").rglob("*.parquet"))
    assert parts == ["activations/year=2024/month=01/part-000000.parquet",
                     "activations/year=2024/month=02/part-000000.parquet"]
    artifacts.verify_checksums(model_dir)
    listed = {line.split("  ", 1)[1] for line in (model_dir / artifacts.CHECKSUM_FILE).read_text().splitlines()}
    assert set(parts) <= listed and "model.pkl" in listed
    # the copies are the run's files, byte for byte
    for name in layout.RUN_FILES:
        assert (model_dir / name).read_bytes() == (built.run.run_dir / name).read_bytes()

    registry = layout.read_registry(built.published_dir)
    entry = registry.tasks[manifest.task_id]
    assert (entry.model_id, entry.domain, entry.target, entry.unit, entry.horizon_hours, entry.synthetic) == (
        manifest.model_id, m.Domain.AIR, "y", "u", 6, True)

    card = m.ModelCard.model_validate_json((model_dir / layout.CARD_FILE).read_text())
    assert card.synthetic and card.manifest.model_id == manifest.model_id and card.metrics is not None
    assert card.coverage == m.TimeCoverage(
        issued_from_utc="2024-01-05T00:00:00Z", issued_to_utc="2024-02-14T22:00:00Z", step_hours=1)
    assert any("in-sample" in w for w in card.manifest.warnings)  # the period overlaps the training period


def test_inputs_and_predictions_reproduce_the_model(built):
    rows = period_rows(built)
    features = built.run.config.features
    inputs = pq.read_table(built.model_dir / layout.INPUTS_FILE).to_pandas()
    assert list(inputs.columns) == ["entity_id", "issued_at_utc", *features]
    assert len(inputs) == len(rows) == built.summary.n_input_rows
    merged = rows.merge(inputs, on=["entity_id", "issued_at_utc"], suffixes=("", "_pub"))
    assert len(merged) == len(rows)
    for f in features:  # missing stays missing (null), present values are bit-identical
        assert (merged[f].isna() == merged[f + "_pub"].isna()).all()
        assert (merged[f].fillna(-1) == merged[f + "_pub"].fillna(-1)).all()

    predictions = pq.read_table(built.model_dir / layout.PREDICTIONS_FILE).to_pandas()
    merged = rows.merge(predictions, on=["entity_id", "issued_at_utc"])
    expected = built.run.model.predict(merged[features])
    assert len(merged) == len(rows)
    assert (merged["prediction"].isna() == pd.isna(expected)).all()
    assert (merged["prediction"].fillna(-1) == pd.Series(expected).fillna(-1)).all()
    assert (merged["valid_at_utc"] - merged["issued_at_utc"] == pd.Timedelta(hours=6)).all()
    assert (merged["observed"].isna() == merged[built.run.config.target_column].isna()).all()
    missing = merged["prediction"].isna()
    assert missing.any()  # the synthetic table has missing exogenous inputs
    assert set(merged.loc[missing, "missing_reason"]) == {"missing_input"}
    assert merged.loc[~missing, "missing_reason"].isna().all()


def test_activations_are_the_exact_firing_table_with_null_for_missing(built):
    rows = period_rows(built).sort_values(["issued_at_utc", "entity_id"])
    features = built.run.config.features
    expected = firing_table(built.run.model, rows[features], rows["entity_id"].tolist(), rows["issued_at_utc"])
    table = pq.read_table(built.model_dir / "activations")
    assert table.num_rows == len(expected) == built.summary.n_activation_records
    assert pc.sum(pc.is_nan(table["firing_strength"])).as_py() in (0, None)  # NaN never reaches a file as a number
    assert table["firing_strength"].null_count == int(expected["firing_strength"].isna().sum()) > 0
    got = table.to_pandas()[["entity_id", "issued_at_utc", "rule_id", "firing_strength", "effective_firing",
                             "missing_reason"]]
    got = got.astype({"entity_id": str, "rule_id": str}).sort_values(["issued_at_utc", "entity_id", "rule_id"])
    want = expected.astype({"entity_id": str, "rule_id": str}).sort_values(["issued_at_utc", "entity_id", "rule_id"])
    for column in ("firing_strength", "effective_firing"):
        a, b = got[column].reset_index(drop=True), want[column].reset_index(drop=True)
        assert (a.isna() == b.isna()).all() and (a.fillna(-1) == b.fillna(-1)).all()
    assert (got["missing_reason"].reset_index(drop=True).fillna("-")
            == want["missing_reason"].astype(object).reset_index(drop=True).fillna("-")).all()


def test_entities_are_restricted_and_complete(built, tmp_path):
    kept = m.EntityCollection.model_validate_json((built.model_dir / layout.ENTITIES_FILE).read_text())
    assert {f.id for f in kept.features} == {"E0", "E1", "E2"} and kept.synthetic

    one = tmp_path / "e1.parquet"  # a feature table with only E1: the other entities are dropped
    table = period_rows(built)
    table[table["entity_id"] == "E1"].to_parquet(one, index=False)
    publish_again(built, tmp_path / "pub", features=one)
    only = m.EntityCollection.model_validate_json(
        (tmp_path / "pub" / built.run.manifest.model_id / layout.ENTITIES_FILE).read_text())
    assert [f.id for f in only.features] == ["E1"]

    partial = m.EntityCollection.model_validate_json((built.root / "entities.geojson").read_text())
    partial = partial.model_copy(update={"features": [f for f in partial.features if f.id != "E2"]})
    (tmp_path / "partial.geojson").write_text(partial.model_dump_json())
    with pytest.raises(ValueError, match="E2"):
        publish_again(built, tmp_path / "pub2", entities_path=tmp_path / "partial.geojson")
    assert not (tmp_path / "pub2" / built.run.manifest.model_id).exists()


def test_tampered_run_is_refused_and_nothing_is_left_behind(built, tmp_path):
    run_copy = tmp_path / "run"
    shutil.copytree(built.run.run_dir, run_copy)
    with open(run_copy / "model.pkl", "ab") as fh:
        fh.write(b"x")
    with pytest.raises(ValueError, match="checksum mismatch"):
        publish_again(built, tmp_path / "pub", run_dir=run_copy)
    assert not (tmp_path / "pub").exists() or list((tmp_path / "pub").iterdir()) == []


def test_failure_midway_leaves_no_model_dir_and_keeps_registry(built, tmp_path):
    pub = tmp_path / "pub"
    publish_again(built, pub)
    before = (pub / layout.REGISTRY_FILE).read_text()
    bad = tmp_path / "bad.parquet"  # duplicate (entity, issue time) rows are a producer bug
    rows = period_rows(built)
    pd.concat([rows, rows.head(3)]).to_parquet(bad, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        publish_again(built, pub, features=bad, replace=True)
    assert sorted(p.name for p in pub.iterdir()) == [built.run.manifest.model_id, layout.REGISTRY_FILE]
    artifacts.verify_checksums(pub / built.run.manifest.model_id)  # the previous publication is intact
    assert (pub / layout.REGISTRY_FILE).read_text() == before


def test_refusals(built, tmp_path):
    pub = tmp_path / "pub"
    publish_again(built, pub)
    with pytest.raises(FileExistsError):
        publish_again(built, pub)
    publish_again(built, pub, replace=True)
    with pytest.raises(ValueError, match="does not match"):
        publish_again(built, tmp_path / "p2", task_id="other_task")
    with pytest.raises(ValueError, match="UTC"):
        publish_again(built, tmp_path / "p2", period_from="2024-01-05T00:00:00")
    with pytest.raises(ValueError, match="after"):
        publish_again(built, tmp_path / "p2", period_to=START)
    with pytest.raises(ValueError, match="no rows"):
        publish_again(built, tmp_path / "p2", period_from="2030-01-01T00:00:00Z", period_to="2030-02-01T00:00:00Z")
    spec = json.loads((built.root / "feature_spec.json").read_text())
    del spec["features"]["exo_t"]
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="exo_t"):
        publish_again(built, tmp_path / "p2", feature_spec_path=tmp_path / "spec.json")
    negative = json.loads((built.root / "feature_spec.json").read_text())
    negative["features"]["exo_t"]["lag_hours"] = -1  # an input from the future
    (tmp_path / "neg.json").write_text(json.dumps(negative))
    with pytest.raises(ValueError):
        publish_again(built, tmp_path / "p2", feature_spec_path=tmp_path / "neg.json")
    assert not (tmp_path / "p2").exists() or not any(p.is_dir() for p in (tmp_path / "p2").iterdir())


def test_a_synthetic_run_cannot_be_published_as_real(built, tmp_path):
    publish_again(built, tmp_path / "pub", synthetic=False)
    registry = layout.read_registry(tmp_path / "pub")
    assert registry.tasks[built.run.manifest.task_id].synthetic is True


def test_partial_month_period_and_cli(built, tmp_path, capsys):
    argv = [
        "--run-dir", str(built.run.run_dir), "--features", str(built.root / "features.parquet"),
        "--entities", str(built.root / "entities.geojson"), "--feature-spec", str(built.root / "feature_spec.json"),
        "--from", "2024-01-31T12:00:00Z", "--to", "2024-02-01T12:00:00Z", "--published-dir", str(tmp_path / "pub"),
        "--synthetic", "--chunk-size", "7",
    ]
    main(argv)
    out = json.loads(capsys.readouterr().out)
    assert out["input_rows"] == 3 * 24 and out["activation_records"] == 3 * 24 * len(built.run.rules.rules)
    assert out["coverage"]["issued_from_utc"] == "2024-01-31T12:00:00Z"
    assert out["coverage"]["issued_to_utc"] == "2024-02-01T11:00:00Z"
    model_dir = tmp_path / "pub" / built.run.manifest.model_id
    # chunked while it is built, one file per month once sorted (AT-061 B3); the chunks are not left behind
    assert len(list((model_dir / "activations" / "year=2024" / "month=01").glob("*.parquet"))) == 1
    assert not [p for p in (tmp_path / "pub").iterdir() if p.name.startswith(".tmp-")]
    assert pq.read_table(model_dir / "activations").num_rows == out["activation_records"]
