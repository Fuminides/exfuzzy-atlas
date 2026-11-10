"""Synthetic multi-entity hourly series for tests, the demo and benchmarks. Invented data, never real.

``y(t+h)`` depends on the current and lagged ``y`` and on an exogenous driver, plus a daily cycle:
an AR(1) process whose innovations are pushed by ``exo``. Entities differ in level only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["y_t", "y_lag3", "exo_t", "hour"]
FEATURE_UNITS = {"y_t": "u", "y_lag3": "u", "exo_t": "m/s", "hour": "h"}
TARGET = "y_target"


def make_synthetic_table(
    n_entities: int = 3,
    n_hours: int = 24 * 60,
    horizon_hours: int = 6,
    seed: int = 0,
    exo_missing_fraction: float = 0.0,
    start: str = "2024-01-01T00:00:00Z",
) -> pd.DataFrame:
    """Rows keyed by ``entity_id`` and ``issued_at_utc``; ``y_target`` is y at issue time + horizon."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range(start, periods=n_hours, freq="h", tz="UTC")
    hod = hours.hour.to_numpy()
    frames = []
    for e in range(n_entities):
        exo = np.clip(3 + 2 * np.sin(np.arange(n_hours) / 31 + e) + rng.normal(0, 1, n_hours), 0, None)
        y = np.empty(n_hours)
        y[0] = 30 + 10 * e
        daily = 6 * np.sin(2 * np.pi * (hod - 7) / 24)
        for t in range(1, n_hours):
            y[t] = 0.85 * y[t - 1] + 0.15 * (30 + 10 * e) + daily[t] * 0.3 - 1.5 * (exo[t] - 3) + rng.normal(0, 1.5)
        series = pd.DataFrame({"entity_id": f"E{e}", "issued_at_utc": hours, "y_t": y, "exo_t": exo, "hour": hod})
        series["y_lag3"] = series["y_t"].shift(3)
        series[TARGET] = series["y_t"].shift(-horizon_hours)
        frames.append(series)
    table = pd.concat(frames, ignore_index=True)
    if exo_missing_fraction > 0:
        table.loc[rng.random(len(table)) < exo_missing_fraction, "exo_t"] = np.nan
    table["hour"] = table["hour"].astype(float)
    return table[["entity_id", "issued_at_utc", *FEATURES, TARGET]]
