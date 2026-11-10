"""Baselines evaluated on the same split and rows as the fuzzy model.

All of them share one tiny interface over a *frame* with ``entity_id``, ``issued_at_utc`` and the feature
columns: ``fit(frame, y)`` (training rows only) and ``predict(frame)``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


class Baseline(Protocol):
    name: str

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> Baseline: ...

    def predict(self, frame: pd.DataFrame) -> np.ndarray: ...


class Persistence:
    """y(t+h) = y(t), read from the feature holding the current value of the target."""

    name = "persistence"

    def __init__(self, feature: str):
        self.feature = feature

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> Persistence:
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame[self.feature].to_numpy(dtype=float)


class Climatology:
    """Mean target by hour-of-day x weekday of the *valid* time, from the training rows.

    By default per entity, falling back to the entity mean and then to the global mean for cells or
    entities the training period never saw. Hours and weekdays are taken in ``timezone`` (local time).
    """

    name = "climatology"

    def __init__(self, horizon_hours: int, timezone: str = "UTC", by_entity: bool = True):
        self.horizon = timedelta(hours=horizon_hours)
        self.timezone = timezone
        self.by_entity = by_entity

    def _keys(self, frame: pd.DataFrame) -> pd.DataFrame:
        valid = (pd.DatetimeIndex(frame["issued_at_utc"]) + self.horizon).tz_convert(self.timezone)
        entity = frame["entity_id"].to_numpy() if self.by_entity else np.zeros(len(frame), dtype=int)
        return pd.DataFrame({"entity": entity, "hour": valid.hour, "weekday": valid.weekday})

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> Climatology:
        keys = self._keys(frame).assign(y=np.asarray(y, dtype=float))
        self.global_mean_ = float(np.mean(y))
        self.cell_ = keys.groupby(["entity", "hour", "weekday"])["y"].mean()
        self.entity_ = keys.groupby("entity")["y"].mean()
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        keys = self._keys(frame)
        cell = pd.MultiIndex.from_frame(keys[["entity", "hour", "weekday"]])
        out = pd.Series(self.cell_.reindex(cell).to_numpy())
        out = out.fillna(pd.Series(self.entity_.reindex(keys["entity"]).to_numpy()))
        return out.fillna(self.global_mean_).to_numpy()


class SklearnBaseline:
    """An sklearn regressor on the model features; every fitted transform sees the training rows only."""

    def __init__(self, name: str, estimator, features: list[str]):
        self.name, self.estimator, self.features = name, estimator, list(features)

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> SklearnBaseline:
        self.estimator.fit(frame[self.features].to_numpy(dtype=float), np.asarray(y, dtype=float))
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict(frame[self.features].to_numpy(dtype=float))


def make_baselines(
    features: list[str],
    *,
    horizon_hours: int,
    seed: int,
    persistence_feature: str | None = None,
    timezone: str = "UTC",
    ridge_alpha: float = 1.0,
    gbm_max_iter: int = 200,
) -> list[Baseline]:
    """Persistence (if a lag-0 feature is named), climatology, Ridge and histogram gradient boosting."""
    baselines: list[Baseline] = []
    if persistence_feature is not None:
        if persistence_feature not in features:
            raise ValueError(f"persistence_feature {persistence_feature!r} is not a model feature")
        baselines.append(Persistence(persistence_feature))
    baselines.append(Climatology(horizon_hours, timezone))
    ridge = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=ridge_alpha))
    baselines.append(SklearnBaseline("ridge", ridge, features))
    # No internal early stopping: it would validate on a random (non-chronological) slice of train.
    gbm = HistGradientBoostingRegressor(max_iter=gbm_max_iter, early_stopping=False, random_state=seed)
    baselines.append(SklearnBaseline("hist_gradient_boosting", gbm, features))
    return baselines
