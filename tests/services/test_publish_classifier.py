"""Publishing a winning-rule classifier: labels instead of numbers, classifier firing table, scheme in the card."""

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from atlas.contracts import models as m
from atlas.explain import iter_classifier_firing_tables
from atlas.ml.classification import load_scheme
from atlas.paths import REPO_ROOT
from atlas.services import layout
from atlas.services.publish import _class_predictions, classify_observed, publish_run, task_type_of
from atlas.services.synthetic import SCHEME, build_synthetic

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


def period_rows(built):
    table = built.table
    return table[(table["issued_at_utc"] >= pd.Timestamp(START)) & (table["issued_at_utc"] < pd.Timestamp(END))]


def test_task_type_registry_card_and_scheme(built_class, built):
    assert task_type_of(built_class.run) == "classification" and task_type_of(built.run) == "regression"
    entry = layout.read_registry(built_class.published_dir).tasks[built_class.run.manifest.task_id]
    assert entry.task_type == "classification" and entry.synthetic
    assert layout.read_registry(built.published_dir).tasks[built.run.manifest.task_id].task_type == "regression"
    card = m.ModelCard.model_validate_json((built_class.model_dir / layout.CARD_FILE).read_text())
    assert card.target_scheme == built_class.run.rules.target_scheme == SCHEME.to_target_scheme()
    regression_card = m.ModelCard.model_validate_json((built.model_dir / layout.CARD_FILE).read_text())
    assert regression_card.target_scheme is None


def test_predictions_are_labels_and_never_a_class_index(built_class):
    run, rows = built_class.run, period_rows(built_class)
    features = run.config.features
    table = pq.read_table(built_class.model_dir / layout.PREDICTIONS_FILE)
    assert table.column_names == ["entity_id", "issued_at_utc", "valid_at_utc", "prediction", "observed",
                                  "observed_label", "prediction_label", "missing_reason"]
    assert table["prediction"].null_count == table.num_rows  # a class index is never a published number
    got = table.to_pandas()
    merged = rows.merge(got, on=["entity_id", "issued_at_utc"])
    assert len(merged) == len(rows)
    expected = run.model.predict_labels(merged[features])
    assert (merged["prediction_label"].fillna("-").to_numpy() == pd.Series(expected).fillna("-").to_numpy()).all()
    assert set(merged["prediction_label"].dropna()) <= set(SCHEME.labels)
    # observed_label is the run's scheme applied to the observed value, the same classifier A4 trained with
    indexes = SCHEME.classify(merged[run.config.target_column])
    want = pd.Series(np.array([*SCHEME.labels, None], dtype=object)[np.where(indexes < 0, len(SCHEME.labels), indexes)])
    assert (merged["observed_label"].fillna("-").to_numpy() == want.fillna("-").to_numpy()).all()
    finite = np.isfinite(merged[features].to_numpy(dtype=float)).all(axis=1)
    none = merged["prediction_label"].isna()
    assert none.any() and (~finite).any()  # the synthetic table has missing inputs, and some rows fire nothing
    assert (merged.loc[~finite, "missing_reason"] == "missing_input").all()
    assert set(merged.loc[finite & none, "missing_reason"]) <= {"prediction_unavailable"}
    assert merged.loc[~none, "missing_reason"].isna().all()


def test_activations_are_the_classifier_firing_table(built_class):
    run = built_class.run
    rows = period_rows(built_class).sort_values(["issued_at_utc", "entity_id"])
    expected = pd.concat(list(iter_classifier_firing_tables(
        run.model, rows[run.config.features], rows["entity_id"].tolist(), rows["issued_at_utc"])))
    table = pq.read_table(built_class.model_dir / "activations")
    assert table.column_names[:8] == ["entity_id", "issued_at_utc", "rule_id", "firing_strength", "weight",
                                      "association_degree", "is_winner", "missing_reason"]  # then year, month
    assert table.num_rows == len(expected) == built_class.summary.n_activation_records
    got = table.to_pandas().astype({"entity_id": str, "rule_id": str})
    keys = ["issued_at_utc", "entity_id", "rule_id"]
    got = got.sort_values(keys).reset_index(drop=True)
    want = expected.astype({"entity_id": str, "rule_id": str}).sort_values(keys).reset_index(drop=True)
    for column in ("firing_strength", "weight", "association_degree"):
        assert (got[column].isna() == want[column].isna()).all()
        assert (got[column].fillna(-1) == want[column].fillna(-1)).all()
    assert (got["is_winner"] == want["is_winner"]).all()
    # exactly one winner per answered row and none for the rest
    labels = pq.read_table(built_class.model_dir / layout.PREDICTIONS_FILE).to_pandas()
    wins = got.groupby(["entity_id", "issued_at_utc"])["is_winner"].sum().reset_index()
    wins = wins.merge(labels, on=["entity_id", "issued_at_utc"])
    assert (wins["is_winner"] == wins["prediction_label"].notna().astype(int)).all()


def test_classify_observed_follows_the_official_scheme_convention():
    official = load_scheme(REPO_ROOT / "configs/ml/ica_no2_scheme.json")
    target = official.to_target_scheme()
    values = [0, 0.4, 39.9, 40, 40.4, 40.5, 41, 90, 90.6, 120, 121, 340, 1000, 1000.4, 1001, np.nan, 5.5]
    index = official.classify(values)
    want = [None if i < 0 else official.labels[i] for i in index]
    assert classify_observed(target, values) == want
    with pytest.raises(ValueError, match="boundary"):
        classify_observed(target.model_copy(update={"boundary": "lower_inclusive"}), values)



def test_classify_observed_handles_an_open_top_class():
    """The EAQI with its rare upper bands merged ends in an open class ("Poor or worse", 61 and above)."""
    official = load_scheme(REPO_ROOT / "configs/air/eaqi_no2_scheme.json")
    merged = official.merge_rare_upper_tail([100, 100, 100, 10, 2, 1], min_share=0.01)
    target = merged.to_target_scheme()
    assert target.classes[-1].upper is None and target.classes[-1].label == "Poor or worse"
    values = [-3.2, 0, 10, 10.4, 10.5, 25, 26, 60, 60.4, 60.5, 61, 150, 151, 2000, np.nan]
    index = merged.classify(values)
    want = [None if i < 0 else merged.labels[i] for i in index]
    assert classify_observed(target, values) == want
    assert want[0] == "Good" and want[-2] == "Poor or worse" and want[-1] is None

def test_an_unknown_label_is_refused():
    class Stub:
        def predict_labels(self, X):
            return np.array(["low", "bogus"], dtype=object)

    frame = pd.DataFrame({"entity_id": ["a", "b"], "issued_at_utc": pd.date_range("2024-01-01", periods=2, tz="UTC"),
                          "f": [1.0, 2.0]})
    with pytest.raises(ValueError, match="bogus"):
        _class_predictions(Stub(), frame, ["f"], np.array([1.0, 2.0]), SCHEME.to_target_scheme(), pd.Timedelta(hours=6))


def test_regression_and_classification_share_one_registry(built, built_class, tmp_path):
    for b in (built, built_class):
        publish_run(
            b.run.run_dir, b.root / "features.parquet", b.root / "entities.geojson", b.root / "feature_spec.json",
            START, END, published_dir=tmp_path, synthetic=True)
    tasks = layout.read_registry(tmp_path).tasks
    assert {k: v.task_type for k, v in tasks.items()} == {
        built.run.manifest.task_id: "regression", built_class.run.manifest.task_id: "classification"}


def test_default_demo_is_the_regression_one_and_task_is_checked(tmp_path):
    with pytest.raises(ValueError, match="task must be"):
        build_synthetic(tmp_path, task="ordinal")
