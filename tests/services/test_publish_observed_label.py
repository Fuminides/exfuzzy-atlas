"""Publishing a classifier whose observed class comes from a table column (NYC: percentile labels of a count)."""

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.publish import _class_predictions, publish_run
from atlas.services.synthetic import SCHEME

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


@pytest.fixture(scope="module")
def labelled(built_class, tmp_path_factory):
    """The synthetic table with a precomputed label column that disagrees with the scheme bounds on purpose and has
    a null label on some rows that do have an observed value ('no reference level')."""
    table = built_class.table.copy()
    labels = np.array(SCHEME.labels, dtype=object)
    table["lvl"] = labels[(np.arange(len(table)) // 7) % 3]
    table.loc[table.index[::11], "lvl"] = None
    path = tmp_path_factory.mktemp("labelled") / "features.parquet"
    table.to_parquet(path, index=False)
    out = tmp_path_factory.mktemp("published-labelled")
    publish_run(
        built_class.run.run_dir, path, built_class.root / "entities.geojson", built_class.root / "feature_spec.json",
        START, END, published_dir=out, synthetic=True, observed_label_column="lvl")
    return table, out / built_class.run.manifest.model_id


def test_observed_label_comes_from_the_column_and_unlabelled_rows_withhold_the_prediction(built_class, labelled):
    table, model_dir = labelled
    run = built_class.run
    got = pq.read_table(model_dir / layout.PREDICTIONS_FILE).to_pandas()
    merged = got.merge(table, on=["entity_id", "issued_at_utc"])
    assert len(merged) == len(got) > 0
    assert (merged["observed_label"].fillna("-") == merged["lvl"].fillna("-")).all()
    scheme_labels = SCHEME.classify(merged[run.config.target_column])
    assert (merged["observed_label"].fillna("-").to_numpy()
            != np.array([*SCHEME.labels, "-"], dtype=object)[np.where(scheme_labels < 0, 3, scheme_labels)]).any()
    no_reference = merged["lvl"].isna() & merged["observed"].notna()
    assert no_reference.any()
    assert merged.loc[no_reference, "prediction_label"].isna().all()
    finite = np.isfinite(merged[run.config.features].to_numpy(dtype=float)).all(axis=1)
    assert (merged.loc[no_reference & finite, "missing_reason"] == "prediction_unavailable").all()
    assert (merged.loc[no_reference & ~finite, "missing_reason"] == "missing_input").all()
    expected = run.model.predict_labels(merged[run.config.features])
    answered = merged["prediction_label"].notna()
    assert answered.any()
    assert (merged.loc[answered, "prediction_label"].to_numpy() == pd.Series(expected)[answered].to_numpy()).all()
    assert merged.loc[answered, "missing_reason"].isna().all()
    # an unobserved target is not 'no reference': its prediction stays
    unobserved = merged["observed"].isna() & merged["lvl"].isna() & np.isfinite(
        merged[run.config.features].to_numpy(dtype=float)).all(axis=1)
    assert not unobserved.any() or (merged.loc[unobserved, "prediction_label"].notna() | (
        pd.Series(expected)[unobserved].isna())).all()


def test_withheld_rows_and_unknown_labels_in_class_predictions():
    class Stub:
        def predict_labels(self, X):
            return np.array(["low", "mid", "high", "low"], dtype=object)

    frame = pd.DataFrame({"entity_id": list("abcd"), "issued_at_utc": pd.date_range("2024-01-01", periods=4, tz="UTC"),
                          "f": [1.0, 2.0, 3.0, np.nan]})
    scheme = SCHEME.to_target_scheme()
    observed = np.array([5.0, 5.0, np.nan, 5.0])
    out = _class_predictions(Stub(), frame, ["f"], observed, scheme, pd.Timedelta(hours=1),
                             np.array(["low", None, None, "mid"], dtype=object))
    def nulls(column):  # pandas 3 stores missing strings as NaN
        return [None if pd.isna(v) else v for v in out[column]]

    assert nulls("observed_label") == ["low", None, None, "mid"]
    # row b: observed value, no label -> withheld; row c: nothing observed -> kept; row d: input missing
    assert nulls("prediction_label") == ["low", None, "high", "low"]
    assert nulls("missing_reason") == [None, "prediction_unavailable", None, None]
    assert (out["valid_at_utc"] - out["issued_at_utc"] == pd.Timedelta(hours=1)).all()
    with pytest.raises(ValueError, match="observed labels outside"):
        _class_predictions(Stub(), frame, ["f"], observed, scheme, pd.Timedelta(hours=1),
                           np.array(["low", "bogus", None, None], dtype=object))


def test_option_is_checked(built, built_class, tmp_path):
    with pytest.raises(ValueError, match="only applies to classifier"):
        publish_run(built.run.run_dir, built.root / "features.parquet", built.root / "entities.geojson",
                    built.root / "feature_spec.json", START, END, published_dir=tmp_path, synthetic=True,
                    observed_label_column="y")
    with pytest.raises(KeyError, match="observed label column"):
        publish_run(built_class.run.run_dir, built_class.root / "features.parquet",
                    built_class.root / "entities.geojson", built_class.root / "feature_spec.json", START, END,
                    published_dir=tmp_path, synthetic=True, observed_label_column="nope")
    assert not list(tmp_path.glob("exfuzzy-*"))  # refused before publishing anything


def test_irregular_sample_times_need_the_flag_and_get_a_card_warning(built, tmp_path):
    """Water issue times are sample times at minute resolution (horizon 0 in the real task)."""
    table = built.table.copy()
    shift = pd.to_timedelta((np.arange(len(table)) % 7) * 7, unit="min")  # gaps are no longer whole hours
    table["issued_at_utc"] = table["issued_at_utc"] + shift
    path = tmp_path / "irregular.parquet"
    table.to_parquet(path, index=False)
    args = (built.run.run_dir, path, built.root / "entities.geojson", built.root / "feature_spec.json",
            "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z")
    with pytest.raises(ValueError, match="irregular_times"):
        publish_run(*args, published_dir=tmp_path / "strict", synthetic=True)
    assert not (tmp_path / "strict").exists() or not list((tmp_path / "strict").glob("exfuzzy-*"))
    summary = publish_run(*args, published_dir=tmp_path / "loose", synthetic=True, irregular_times=True)
    assert summary.coverage.step_hours == 1
    card = m.ModelCard.model_validate_json((summary.model_dir / layout.CARD_FILE).read_text())
    assert any("irregular sample times" in w for w in card.manifest.warnings)


def test_an_entity_without_geometry_is_left_out(built, tmp_path):
    """An entity that cannot be drawn is never published (AT-062), even with rows; publish.json lists it."""
    collection = m.EntityCollection.model_validate_json((built.root / "entities.geojson").read_text())
    gone = collection.features[0].properties.entity_id
    collection.features[0] = collection.features[0].model_copy(update={"geometry": None})
    entities = tmp_path / "entities.geojson"
    entities.write_text(collection.model_dump_json())
    publish_run(built.run.run_dir, built.root / "features.parquet", entities, built.root / "feature_spec.json",
                START, END, published_dir=tmp_path / "published", synthetic=True)
    model_dir = next((tmp_path / "published").glob("exfuzzy-*"))
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    assert info["entities_left_out_without_geometry"] == [gone] and gone not in info["entities"]
    published = m.EntityCollection.model_validate_json((model_dir / layout.ENTITIES_FILE).read_text())
    assert all(f.geometry is not None for f in published.features)
    for name in (layout.PREDICTIONS_FILE, layout.INPUTS_FILE):
        assert gone not in set(pq.read_table(model_dir / name, columns=["entity_id"]).column(0).to_pylist())
