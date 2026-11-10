import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from atlas.contracts import models as m
from atlas.ml.baselines import Climatology, Persistence, make_baselines
from atlas.ml.metrics import metric_rows, regression_metrics
from atlas.ml.split import assert_no_temporal_leakage, chronological_split_spec, split_masks
from atlas.ml.synthetic import FEATURES, TARGET


def test_split_is_chronological_with_embargo_and_disjoint(table):
    spec = chronological_split_spec(table["issued_at_utc"], horizon_hours=6)
    assert spec.embargo_hours >= 6
    masks = split_masks(table["issued_at_utc"], spec)
    assert set(masks) == {"train", "validation", "test"}
    assert sum(mask.astype(int) for mask in masks.values()).max() == 1  # disjoint
    stamps = pd.DatetimeIndex(table["issued_at_utc"])
    assert stamps[masks["train"]].max() < stamps[masks["validation"]].min() < stamps[masks["test"]].min()
    # rows inside an embargo gap belong to no period
    assert (~(masks["train"] | masks["validation"] | masks["test"])).any()
    assert_no_temporal_leakage(table["issued_at_utc"], masks, horizon_hours=6)
    # every row is covered up to the gaps: the last issue time is in test
    assert masks["test"][np.argmax(stamps)]


def test_embargo_shorter_than_horizon_is_rejected(table):
    with pytest.raises(ValueError, match="embargo"):
        chronological_split_spec(table["issued_at_utc"], horizon_hours=6, embargo_hours=3)
    with pytest.raises(ValidationError):  # the contract refuses overlapping periods too
        m.SplitSpec(
            train_from_utc="2024-01-01T00:00:00Z", train_to_utc="2024-01-10T00:00:00Z",
            test_from_utc="2024-01-09T00:00:00Z", test_to_utc="2024-01-20T00:00:00Z", embargo_hours=6,
        )


def test_leakage_check_catches_a_target_observed_after_the_next_period_starts(table):
    stamps = pd.DatetimeIndex(table["issued_at_utc"])
    cut = stamps[len(stamps) // 2]
    masks = {"train": np.asarray(stamps < cut), "test": np.asarray(stamps >= cut + pd.Timedelta(hours=2))}
    with pytest.raises(ValueError, match="leakage"):
        assert_no_temporal_leakage(stamps, masks, horizon_hours=6)
    masks["test"] = np.asarray(stamps >= cut + pd.Timedelta(hours=6))
    assert_no_temporal_leakage(stamps, masks, horizon_hours=6)  # embargo == horizon is enough


def test_no_validation_split(table):
    spec = chronological_split_spec(table["issued_at_utc"], horizon_hours=6, validation_fraction=0.0)
    assert spec.validation_from_utc is None
    assert set(split_masks(table["issued_at_utc"], spec)) == {"train", "test"}


def test_persistence_is_the_current_value(complete_rows):
    baseline = Persistence("y_t").fit(complete_rows, complete_rows[TARGET])
    assert np.array_equal(baseline.predict(complete_rows), complete_rows["y_t"].to_numpy())


def test_climatology_uses_train_cells_and_valid_time_hour():
    issued = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")  # Mon 00:00 .. Tue 23:00
    frame = pd.DataFrame({"entity_id": "A", "issued_at_utc": issued})
    y = np.arange(48, dtype=float)
    clim = Climatology(horizon_hours=6).fit(frame, y)
    # row issued Mon 00:00 has valid time Mon 06:00; the only train row in cell (A, 6h, Monday) has y[0]
    assert clim.predict(frame.iloc[[0]])[0] == 0.0
    unseen = pd.DataFrame({"entity_id": ["B"], "issued_at_utc": issued[:1]})
    assert clim.predict(unseen)[0] == pytest.approx(y.mean())  # unseen entity -> global mean
    wed = pd.DataFrame({"entity_id": ["A"], "issued_at_utc": pd.DatetimeIndex(["2024-01-03T00:00Z"])})
    assert clim.predict(wed)[0] == pytest.approx(clim.entity_["A"])  # Wednesday never seen -> entity mean


def test_fit_time_transforms_use_training_rows_only(complete_rows):
    train, other = complete_rows.iloc[:300], complete_rows.iloc[300:]
    ridge = next(b for b in make_baselines(FEATURES, horizon_hours=6, seed=0) if b.name == "ridge")
    ridge.fit(train, train[TARGET].to_numpy())
    scaler = ridge.estimator.named_steps["standardscaler"]
    assert np.allclose(scaler.mean_, train[FEATURES].mean().to_numpy())
    assert not np.allclose(scaler.mean_, other[FEATURES].mean().to_numpy())


def test_metrics_and_slices():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    pred = np.array([1.0, 2.0, 4.0, 6.0])
    out = regression_metrics(y, pred)
    assert out["mae"] == pytest.approx(0.75)
    assert out["rmse"] == pytest.approx(np.sqrt(5 / 4))
    assert out["r2"] == pytest.approx(1 - 5 / 5)
    rows = metric_rows("est", y, pred, {"entity": np.array(["a", "a", "b", "b"])})
    by = {(r.slice, r.metric): r for r in rows}
    assert by[("entity=a", "mae")].value == 0.0 and by[("entity=a", "mae")].n == 2
    assert by[("entity=b", "mae")].value == pytest.approx(1.5)
    assert ("entity=a", "r2") in by  # y varies inside slice a
    assert regression_metrics(np.ones(3), np.ones(3)).keys() == {"mae", "rmse"}  # constant target: R2 undefined
