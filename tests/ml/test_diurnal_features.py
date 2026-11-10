"""AT-041h: diurnal inputs and their leakage checks (finished hours only; climatology and rho from training rows)."""

import numpy as np
import pandas as pd
import pytest

from atlas.ml import diurnal_features as dfe

TZ = "Europe/Madrid"
H = 6


def _frame(n_days=30, seed=0) -> pd.DataFrame:
    """A table like the feature table: regular hourly grid, no2_last = NO2 of key t-1h, target = NO2 of key t+h."""
    rng = np.random.default_rng(seed)
    issued = pd.date_range("2023-11-20", periods=24 * n_days, freq="h", tz="UTC")
    parts = []
    for entity in ("E1", "E2"):
        series = rng.uniform(5, 130, len(issued) + H + 1).round()  # NO2 of keys issued[0]-1h ... issued[-1]+h
        local = (issued + pd.Timedelta(hours=H)).tz_convert(TZ)
        parts.append(pd.DataFrame({
            "entity_id": entity, "issued_at_utc": issued, "no2_last": series[:len(issued)],
            "target": series[H + 1:], "valid_hour_local": local.hour, "valid_weekday": local.weekday,
            "complete": True}))
    return pd.concat(parts, ignore_index=True)


def _train(f):
    return (f["issued_at_utc"] < "2023-12-05").to_numpy()


def _all(f, train=None):
    return dfe.add_diurnal_features(f, _train(f) if train is None else train, timezone=TZ, horizon_hours=H)


def test_key_offset_reads_the_right_hour_and_refuses_unfinished_hours():
    f = _frame()
    out = dfe.no2_at_key_offset(f, -18)
    e1 = f[f["entity_id"] == "E1"].reset_index(drop=True)
    i = 100  # key t-18h = no2_last of the row issued at t-17h
    assert out[i] == e1.loc[i - 17, "no2_last"]
    assert np.isnan(out[:17]).all()  # before the start of the grid: NaN, not a guess
    with pytest.raises(ValueError, match="finished hour"):
        dfe.no2_at_key_offset(f, 0)


def test_key_offset_does_not_mix_stations_and_ignores_row_order():
    f = _frame()
    shuffled = f.sample(frac=1.0, random_state=1)
    a = pd.Series(dfe.no2_at_key_offset(f, -18), index=f.index)
    b = pd.Series(dfe.no2_at_key_offset(shuffled, -18), index=shuffled.index)
    pd.testing.assert_series_equal(a, b.loc[a.index])
    e2_first = f.index[f["entity_id"] == "E2"][:17]
    assert np.isnan(a.loc[e2_first]).all()  # E2's first hours do not borrow E1's last values


def test_inputs_do_not_change_when_the_future_changes():
    """Every input at issue t is unchanged if every NO2 hour with key >= t (and the target) is perturbed."""
    f = _frame()
    t = pd.Timestamp("2023-12-10T12:00Z")
    perturbed = f.copy()
    future = perturbed["issued_at_utc"] > t  # no2_last of rows issued after t is a key >= t
    perturbed.loc[future, "no2_last"] = 999.0
    perturbed["target"] = perturbed["target"] + 500.0  # the target is never an input (only rho reads it, on train)
    a, _ = _all(f)
    b, _ = _all(perturbed)
    upto = (f["issued_at_utc"] <= t).to_numpy()
    for name in dfe.DIURNAL_FEATURES:
        if name == dfe.EXPECTED_DAMPED:  # rho reads training targets: see the next test
            continue
        np.testing.assert_array_equal(a.loc[upto, name].to_numpy(), b.loc[upto, name].to_numpy(), err_msg=name)


def test_climatology_and_rho_use_training_rows_only():
    f = _frame()
    train = _train(f)
    perturbed = f.copy()
    perturbed.loc[~train, ["no2_last", "target"]] = 1e5  # validation / test values must not move anything fitted
    a, audit_a = _all(f, train)
    b, audit_b = _all(perturbed, train)
    pd.testing.assert_series_equal(dfe.climatology(f, train, TZ), dfe.climatology(perturbed, train, TZ))
    assert audit_a["rho"] == audit_b["rho"]
    for name in (dfe.CLIM_VALID,):
        np.testing.assert_array_equal(a[name].to_numpy(), b[name].to_numpy())


def test_climatology_is_the_median_per_station_hour_and_day_type():
    issued = pd.DatetimeIndex(["2024-01-08T05:00Z", "2024-01-09T05:00Z", "2024-01-10T05:00Z", "2024-01-13T05:00Z"])
    f = pd.DataFrame({"entity_id": "E1", "issued_at_utc": issued, "no2_last": [10.0, 20.0, 60.0, 99.0]})
    clim = dfe.climatology(f, np.ones(4, dtype=bool), TZ)
    # key 04:00 UTC = 05:00 Madrid; Mon-Wed are Laborable (0), 2024-01-13 is a Saturday (1)
    assert clim.loc[("E1", 5, 0)] == 20.0 and clim.loc[("E1", 5, 1)] == 99.0


def test_expected_value_is_usual_valid_plus_departure_and_is_floored():
    f = _frame()
    out, audit = _all(f)
    clim = dfe.climatology(f, _train(f), TZ)
    hour, dtype = dfe.observed_hour_and_day_type(f["issued_at_utc"], TZ)
    clim_last = clim.reindex(pd.MultiIndex.from_arrays([f["entity_id"], hour, dtype])).to_numpy()
    raw = out[dfe.CLIM_VALID].to_numpy() + f["no2_last"].to_numpy() - clim_last
    np.testing.assert_allclose(out[dfe.EXPECTED].to_numpy(), np.clip(raw, 0.0, 1000.0))
    assert (out[dfe.EXPECTED] >= 0).all() and (out[dfe.EXPECTED_DAMPED] >= 0).all()
    ratio = out[dfe.CLIM_VALID] * (f["no2_last"] + 6.0) / (clim_last + 6.0)
    np.testing.assert_allclose(out[dfe.EXPECTED_RATIO].to_numpy(), ratio.clip(0, 1000).to_numpy())
    assert 0.0 <= audit["share_floored_at_zero"] <= 1.0


def test_window_needs_18_valid_hours_and_reads_only_finished_hours():
    f = _frame()
    e1 = (f["entity_id"] == "E1").to_numpy()
    out = dfe.window_stat(f, "mean")
    assert np.isnan(out[np.flatnonzero(e1)[:17]]).all() and np.isfinite(out[np.flatnonzero(e1)[17]])
    i = np.flatnonzero(e1)[200]
    np.testing.assert_allclose(out[i], f.loc[i - 23:i, "no2_last"].mean())  # keys t-24h ... t-1h
    holes = f.copy()
    holes.loc[i - 23:i - 17, "no2_last"] = np.nan  # 7 of 24 hours missing -> 17 valid -> NaN
    assert np.isnan(dfe.window_stat(holes, "max")[i])


def test_station_without_climatology_gets_nan_not_a_guess():
    f = _frame()
    train = _train(f) & (f["entity_id"] == "E1").to_numpy()
    out, _ = _all(f, train)
    e2 = (f["entity_id"] == "E2").to_numpy()
    for name in (dfe.CLIM_VALID, dfe.EXPECTED, dfe.EXPECTED_RATIO, dfe.EXPECTED_DAMPED):
        assert out.loc[e2, name].isna().all() and out.loc[~e2, name].notna().all()


def test_irregular_grid_is_refused():
    f = _frame().drop(index=5)
    with pytest.raises(ValueError):
        dfe.no2_at_key_offset(f, -18)
