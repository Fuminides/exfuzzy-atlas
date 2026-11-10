"""AT-041e: trend, anomaly and station type, with the leakage checks (train-only reference, finished hours only)."""

import json

import numpy as np
import pandas as pd
import pytest

from atlas.ml import extra_features as xf

TZ = "Europe/Madrid"


def _frame(n_days=40, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    issued = pd.date_range("2023-12-01", periods=24 * n_days, freq="h", tz="UTC")
    parts = []
    for entity in ("E1", "E2"):
        parts.append(pd.DataFrame({
            "entity_id": entity, "issued_at_utc": issued, "no2_last": rng.uniform(10, 80, len(issued)).round(),
            "no2_lag3h": rng.uniform(10, 80, len(issued)).round(), "no2_lag1h": rng.uniform(10, 80, len(issued)),
            "target": rng.uniform(10, 80, len(issued))}))
    return pd.concat(parts, ignore_index=True)


def _stations(tmp_path, codes) -> str:
    path = tmp_path / "stations.geojson"
    path.write_text(json.dumps({"features": [
        {"properties": {"entity_id": e, "attributes": ({"station_type_code": c} if c else {})}}
        for e, c in codes.items()]}))
    return path


def test_trend_is_the_difference_of_two_finished_hours():
    f = pd.DataFrame({"no2_last": [50.0, np.nan, 10.0], "no2_lag3h": [40.0, 5.0, 30.0]})
    out = xf.trend(f)
    assert out[0] == 10.0 and np.isnan(out[1]) and out[2] == -20.0


def test_trend_ignores_everything_but_its_two_inputs():
    f = _frame()
    other = f.copy()
    other["target"] = -999.0
    other["no2_lag1h"] = -999.0
    assert np.array_equal(xf.trend(f), xf.trend(other))


def test_observed_hour_is_the_hour_before_the_issue_time_in_local_time():
    # issued 01:00 UTC on a winter day: the observed hour started at 00:00 UTC = 01:00 Madrid
    assert xf.observed_local_hour(pd.DatetimeIndex(["2024-01-10T01:00:00Z"]), TZ).tolist() == [1]
    # summer: 01:00 UTC -> hour started 00:00 UTC = 02:00 Madrid (CEST)
    assert xf.observed_local_hour(pd.DatetimeIndex(["2024-07-10T01:00:00Z"]), TZ).tolist() == [2]


def test_reference_uses_only_the_rows_it_is_given():
    f = _frame()
    train = (f["issued_at_utc"] < "2023-12-20").to_numpy()
    ref = xf.station_hour_medians(f, train, TZ)
    perturbed = f.copy()
    perturbed.loc[~train, "no2_last"] = 1e6  # validation / test values must not move the reference
    pd.testing.assert_series_equal(ref, xf.station_hour_medians(perturbed, train, TZ))
    a, b = xf.anomaly(f, ref, TZ), xf.anomaly(perturbed, ref, TZ)
    assert np.array_equal(a[train], b[train])


def test_reference_is_the_median_of_the_cell():
    f = pd.DataFrame({
        "entity_id": ["E1"] * 3, "no2_last": [10.0, 20.0, 60.0],
        "issued_at_utc": pd.DatetimeIndex(["2023-12-01T05:00Z", "2023-12-02T05:00Z", "2023-12-03T05:00Z"])})
    ref = xf.station_hour_medians(f, np.ones(3, dtype=bool), TZ)
    assert ref.loc[("E1", 5)] == 20.0  # observed hour 04:00 UTC = 05:00 Madrid
    assert xf.anomaly(f, ref, TZ).tolist() == [-10.0, 0.0, 40.0]


def test_station_without_reference_gets_a_nan_anomaly_not_a_guess():
    f = _frame()
    train = (f["entity_id"] == "E1").to_numpy()
    ref = xf.station_hour_medians(f, train, TZ)
    out = xf.anomaly(f, ref, TZ)
    assert np.isnan(out[(f["entity_id"] == "E2").to_numpy()]).all() and np.isfinite(out[train]).all()


def test_station_types_come_from_the_official_code(tmp_path):
    path = _stations(tmp_path, {"E1": "UT", "E2": "S"})
    assert xf.station_types(path) == {"E1": 0, "E2": 2}


@pytest.mark.parametrize("codes", [{"E1": "UT", "E2": None}, {"E1": "UT", "E2": "XX"}])
def test_station_type_is_never_inferred(tmp_path, codes):
    with pytest.raises(ValueError, match="station_type_code"):
        xf.station_types(_stations(tmp_path, codes))


def test_add_extra_features_refuses_a_station_that_is_not_in_the_metadata(tmp_path):
    f = _frame()
    train = (f["issued_at_utc"] < "2023-12-20").to_numpy()
    with pytest.raises(ValueError, match="without an official type"):
        xf.add_extra_features(f, train, timezone=TZ, stations_geojson=_stations(tmp_path, {"E1": "UF"}))


def test_add_extra_features_adds_the_three_columns_and_leaves_the_input_alone(tmp_path):
    f = _frame()
    before = f.copy()
    train = (f["issued_at_utc"] < "2023-12-20").to_numpy()
    out, audit = xf.add_extra_features(f, train, timezone=TZ,
                                       stations_geojson=_stations(tmp_path, {"E1": "UF", "E2": "UT"}))
    pd.testing.assert_frame_equal(f, before)
    assert {xf.TREND, xf.ANOMALY, xf.STATION_TYPE} <= set(out.columns)
    assert out.loc[out["entity_id"] == "E2", xf.STATION_TYPE].eq(0).all()
    assert audit["reference_cells"] == 48 and audit["reference_rows"] == int(train.sum())
