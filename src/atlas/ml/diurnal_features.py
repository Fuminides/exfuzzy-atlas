"""Diurnal inputs for the Madrid NO2 ICA classifier (AT-041h): what the station usually reads at the valid hour,
today's departure from it carried forward, and the station's own recent values at the valid hour.

Time convention of the feature table (``feature_card.md``): a row is an issue time ``t``; an hour with key ``s`` (start
of the hour, UTC) is known at ``s + 1h``, so an input may only read keys ``<= t - 1h``. The table holds one row per
station and issue hour on a regular hourly grid, and ``no2_last`` of the row issued at ``u`` is the NO2 of the key
``u - 1h``; so the NO2 of any key ``t - k`` (``k >= 1``) is ``no2_last`` of the row issued at ``t - k + 1h`` of the same
station. Nothing else is read.

Inputs (all in ug/m3, all NaN where a value they need is missing; nothing is imputed):

* ``no2_clim_valid``: training-period **median** NO2 of the station at the local hour and day type (Laborable / Sabado
  / Domingo) of the target hour. "What this station usually reads at that hour on that kind of day."
* ``no2_expected_valid`` = ``no2_clim_valid + (no2_last - clim(hour and day type of no2_last))``, clipped to the
  domain [0, 1000] of the NO2 terms:
  today's departure from the usual value, carried forward unchanged to the valid hour.
* ``no2_expected_valid_ratio`` = ``no2_clim_valid * (no2_last + k) / (clim_last + k)``, ``k = 6 ug/m3``: the same
  idea with the departure as a ratio (the diurnal cycle scales the level); ``k`` keeps a near-zero usual value from
  blowing the ratio up (6 ug/m3 = the measurement-uncertainty scale of the NO2 terms, 15 % of 40); clipped likewise.
* ``no2_expected_valid_damped`` = ``no2_clim_valid + rho * (no2_last - clim_last)``, clipped like the above, with
  ``rho`` the least-squares slope (no intercept) of the target's departure on ``no2_last``'s departure over the complete
  **training** rows: the share of today's departure still present at the valid hour in the training years.
* ``no2_yday_valid``: NO2 of the key ``t + h - 24h`` (yesterday at the valid hour); needs ``h <= 23``.
* ``no2_week_valid``: NO2 of the key ``t + h - 168h`` (same hour and weekday, last week).
* ``no2_mean_24h`` / ``no2_max_24h``: mean / maximum of the keys ``t - 24h ... t - 1h`` with at least 18 of the 24
  hours valid (75 %, the data-capture rule of Directive 2008/50/EC Annex VII for daily aggregates); else NaN.

The climatology and ``rho`` are computed from rows of ``train_mask`` only (the training split); they are returned in
the audit so that a served model can ship them as a data file.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

CLIM_VALID = "no2_clim_valid"
EXPECTED = "no2_expected_valid"
EXPECTED_RATIO = "no2_expected_valid_ratio"
EXPECTED_DAMPED = "no2_expected_valid_damped"
YDAY_VALID = "no2_yday_valid"
WEEK_VALID = "no2_week_valid"
MEAN_24H = "no2_mean_24h"
MAX_24H = "no2_max_24h"
DIURNAL_FEATURES = (CLIM_VALID, EXPECTED, EXPECTED_RATIO, EXPECTED_DAMPED, YDAY_VALID, WEEK_VALID, MEAN_24H, MAX_24H)
UNITS = dict.fromkeys(DIURNAL_FEATURES, "ug/m3")
RATIO_OFFSET = 6.0  # ug/m3
NO2_DOMAIN_MAX = 1000.0  # ug/m3: end of the domain of the NO2 terms; a projection is clipped to [0, 1000]
WINDOW_HOURS, WINDOW_MIN_VALID = 24, 18
DAY_TYPES = {0: "Laborable", 1: "Sábado", 2: "Domingo"}


def day_type(weekday: np.ndarray) -> np.ndarray:
    """0 Laborable (Mon-Fri), 1 Sabado, 2 Domingo; ``weekday`` 0 = Monday. Public holidays are not encoded."""
    w = np.asarray(weekday)
    return np.where(w <= 4, 0, np.where(w == 5, 1, 2))


def _grid(frame: pd.DataFrame) -> tuple[np.ndarray, int]:
    """Positions that sort ``frame`` by (station, issue time), and the number of hours per station.

    Raises unless every station has the same, gap-free hourly grid of issue times.
    """
    order = np.lexsort((frame["issued_at_utc"].to_numpy(), frame["entity_id"].astype(str).to_numpy()))
    entity = frame["entity_id"].astype(str).to_numpy()[order]
    issued = pd.DatetimeIndex(frame["issued_at_utc"].to_numpy()[order])
    counts = pd.Series(entity).value_counts()
    if counts.nunique() != 1:
        raise ValueError("stations have different numbers of issue hours")
    per = int(counts.iloc[0])
    hours = ((issued - issued[0]) / pd.Timedelta(hours=1)).to_numpy().reshape(-1, per)
    if not np.all(np.diff(hours, axis=1) == 1) or not np.all(hours == hours[:1]):
        raise ValueError("issue times are not the same gap-free hourly grid for every station")
    return order, per


def no2_at_key_offset(frame: pd.DataFrame, offset_hours: int) -> np.ndarray:
    """NO2 of the key ``t + offset_hours`` for every row (``offset_hours <= -1``: only finished hours), NaN off-grid."""
    if offset_hours > -1:
        raise ValueError(f"key offset {offset_hours} h is not a finished hour at the issue time (needs <= -1)")
    order, per = _grid(frame)
    values = frame["no2_last"].to_numpy(dtype=float)[order].reshape(-1, per)
    shift = -offset_hours - 1  # rows back: no2_last of the row issued at t + offset + 1h
    out = np.full_like(values, np.nan)
    out[:, shift:] = values[:, :per - shift] if shift else values
    result = np.empty(len(frame))
    result[order] = out.ravel()
    return result


def window_stat(frame: pd.DataFrame, how: str) -> np.ndarray:
    """Mean or max of the keys ``t - 24h ... t - 1h`` (``no2_last`` of the rows issued ``t - 23h ... t``)."""
    order, per = _grid(frame)
    values = frame["no2_last"].to_numpy(dtype=float)[order].reshape(-1, per)
    rolling = pd.DataFrame(values.T).rolling(WINDOW_HOURS, min_periods=WINDOW_MIN_VALID)
    stat = (rolling.mean() if how == "mean" else rolling.max()).to_numpy().T
    result = np.empty(len(frame))
    result[order] = stat.ravel()
    return result


def observed_hour_and_day_type(issued_at_utc, timezone: str) -> tuple[np.ndarray, np.ndarray]:
    """Local hour and day type of the hour ``no2_last`` measures (key ``t - 1h``)."""
    local = (pd.DatetimeIndex(issued_at_utc) - timedelta(hours=1)).tz_convert(timezone)
    return np.asarray(local.hour), day_type(np.asarray(local.weekday))


def climatology(frame: pd.DataFrame, train_mask: np.ndarray, timezone: str) -> pd.Series:
    """Median NO2 per (station, local hour, day type) of the measured hours ``no2_last`` of the training rows only."""
    rows = np.asarray(train_mask, dtype=bool)
    sub = frame.loc[rows, ["entity_id", "issued_at_utc", "no2_last"]]
    hour, dtype = observed_hour_and_day_type(sub["issued_at_utc"], timezone)
    keys = pd.DataFrame({"entity_id": sub["entity_id"].astype(str).to_numpy(), "hour": hour, "day_type": dtype,
                         "no2": sub["no2_last"].to_numpy(dtype=float)})
    return keys.dropna(subset=["no2"]).groupby(["entity_id", "hour", "day_type"])["no2"].median()


def _lookup(table: pd.Series, entity, hour, dtype) -> np.ndarray:
    index = pd.MultiIndex.from_arrays([np.asarray(entity).astype(str), np.asarray(hour), np.asarray(dtype)])
    return table.reindex(index).to_numpy(dtype=float)


def damping_slope(departure_last: np.ndarray, departure_target: np.ndarray) -> float:
    """Least-squares slope without intercept of the target's departure on ``no2_last``'s (finite pairs only)."""
    ok = np.isfinite(departure_last) & np.isfinite(departure_target)
    x, y = departure_last[ok], departure_target[ok]
    return float((x * y).sum() / (x * x).sum())


def add_diurnal_features(frame: pd.DataFrame, train_mask: np.ndarray, *, timezone: str, horizon_hours: int,
                         target_column: str = "target", complete_column: str | None = "complete",
                         features: tuple[str, ...] = DIURNAL_FEATURES) -> tuple[pd.DataFrame, dict]:
    """A copy of ``frame`` with the diurnal inputs, and an audit (climatology, ``rho``, rows without a value).

    ``train_mask`` (aligned with ``frame``) selects the only rows allowed to define the climatology and ``rho``;
    ``rho`` also needs the target, so it uses the complete training rows (``complete_column``) only.
    """
    out = frame.copy()
    train = np.asarray(train_mask, dtype=bool)
    clim = climatology(frame, train, timezone)
    entity = out["entity_id"].astype(str).to_numpy()
    clim_valid = _lookup(clim, entity, out["valid_hour_local"].to_numpy(), day_type(out["valid_weekday"].to_numpy()))
    hour_last, dtype_last = observed_hour_and_day_type(out["issued_at_utc"], timezone)
    clim_last = _lookup(clim, entity, hour_last, dtype_last)
    last = out["no2_last"].to_numpy(dtype=float)
    departure = last - clim_last
    fit_rows = train & (out[complete_column].to_numpy(dtype=bool) if complete_column else True)
    rho = damping_slope(departure[fit_rows], (out[target_column].to_numpy(dtype=float) - clim_valid)[fit_rows])
    computed = {
        CLIM_VALID: lambda: clim_valid,
        EXPECTED: lambda: np.clip(clim_valid + departure, 0.0, NO2_DOMAIN_MAX),
        EXPECTED_RATIO: lambda: np.clip(clim_valid * (last + RATIO_OFFSET) / (clim_last + RATIO_OFFSET), 0.0,
                                         NO2_DOMAIN_MAX),
        EXPECTED_DAMPED: lambda: np.clip(clim_valid + rho * departure, 0.0, NO2_DOMAIN_MAX),
        YDAY_VALID: lambda: no2_at_key_offset(out, horizon_hours - 24),
        WEEK_VALID: lambda: no2_at_key_offset(out, horizon_hours - 168),
        MEAN_24H: lambda: window_stat(out, "mean"),
        MAX_24H: lambda: window_stat(out, "max"),
    }
    for name in features:
        out[name] = computed[name]()
    audit = {
        "climatology_cells": int(len(clim)), "climatology_rows": int(train.sum()),
        "climatology_min_median": float(clim.min()), "climatology_max_median": float(clim.max()),
        "rho": rho, "rho_rows": int(fit_rows.sum()), "ratio_offset_ug_m3": RATIO_OFFSET,
        "share_floored_at_zero": float(np.mean((clim_valid + departure)[np.isfinite(departure)] < 0)),
        "share_ratio_capped": float(np.mean((clim_valid * (last + RATIO_OFFSET) / (clim_last + RATIO_OFFSET))
                                            [np.isfinite(departure)] > NO2_DOMAIN_MAX)),
        "share_nan": {name: float(np.mean(~np.isfinite(out[name].to_numpy(dtype=float)))) for name in features},
    }
    return out, audit


def climatology_table(frame: pd.DataFrame, train_mask: np.ndarray, timezone: str) -> pd.DataFrame:
    """The climatology as a flat table (``entity_id``, ``hour``, ``day_type``, ``day_type_name``, ``median``)."""
    clim = climatology(frame, train_mask, timezone).rename("median_ug_m3").reset_index()
    clim["day_type_name"] = clim["day_type"].map(DAY_TYPES)
    return clim
