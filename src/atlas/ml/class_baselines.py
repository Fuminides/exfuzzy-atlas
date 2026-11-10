"""Baselines for the ordinal-class task (AT-041c), on the same rows and split as the fuzzy classifier.

Same tiny interface as ``atlas.ml.baselines``, but ``fit(frame, y_class)`` receives class indexes and ``predict``
returns class indexes. ``y`` is the observed class of the target; the scheme classifies raw values elsewhere.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from atlas.ml.classification import ClassScheme

FIT_CHUNK = 2_000_000  # rows per groupby in ClimatologyMajorityClass.fit


class PersistenceClass:
    """Class of the current value: ``scheme.classify(frame[feature])`` (``-1`` where the feature is missing)."""

    name = "persistence"

    def __init__(self, feature: str, scheme: ClassScheme, name: str | None = None):
        self.feature, self.scheme = feature, scheme
        if name is not None:  # e.g. "persistence_24h": the class of the value 24 h before the target hour (AT-041h)
            self.name = name

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> PersistenceClass:
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.scheme.classify(frame[self.feature].to_numpy(dtype=float))


class ClimatologyMajorityClass:
    """Majority class of the training rows per station x local hour x weekday of the *valid* time.

    Ties go to the lower (better) class; cells never seen in training fall back to the station majority and then
    to the global majority.
    """

    name = "climatology_majority_class"

    def __init__(self, horizon_hours: int, timezone: str, n_classes: int):
        self.horizon, self.timezone, self.n_classes = timedelta(hours=horizon_hours), timezone, n_classes

    def _keys(self, frame: pd.DataFrame) -> pd.DataFrame:
        valid = (pd.DatetimeIndex(frame["issued_at_utc"]) + self.horizon).tz_convert(self.timezone)
        return pd.DataFrame({"entity": frame["entity_id"].to_numpy(), "hour": valid.hour, "weekday": valid.weekday})

    def _counts(self, keys: pd.DataFrame, y: np.ndarray, by: list[str]) -> pd.DataFrame:
        counts = keys[by].assign(y=y).groupby([*by, "y"]).size().unstack("y", fill_value=0)
        return counts.reindex(columns=range(self.n_classes), fill_value=0)

    @staticmethod
    def _majority(counts: pd.DataFrame) -> pd.Series:
        return pd.Series(counts.to_numpy().argmax(axis=1), index=counts.index)  # argmax: first = lower class on ties

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> ClimatologyMajorityClass:
        """Counts are added up chunk by chunk, so a 15-million-row training period needs no whole-period groupby."""
        y = np.asarray(y, dtype=int)
        self.global_ = int(np.bincount(y, minlength=self.n_classes).argmax())
        cell = entity = None
        for start in range(0, max(len(frame), 1), FIT_CHUNK):
            keys, part = self._keys(frame.iloc[start:start + FIT_CHUNK]), y[start:start + FIT_CHUNK]
            c, e = self._counts(keys, part, ["entity", "hour", "weekday"]), self._counts(keys, part, ["entity"])
            cell = c if cell is None else cell.add(c, fill_value=0)
            entity = e if entity is None else entity.add(e, fill_value=0)
        self.cell_, self.entity_ = self._majority(cell), self._majority(entity)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        keys = self._keys(frame)
        cell = pd.MultiIndex.from_frame(keys[["entity", "hour", "weekday"]])
        out = pd.Series(self.cell_.reindex(cell).to_numpy())
        out = out.fillna(pd.Series(self.entity_.reindex(keys["entity"]).to_numpy()))
        return out.fillna(self.global_).to_numpy().astype(int)


class SklearnClassBaseline:
    """An sklearn classifier on the model features, trained on class indexes."""

    def __init__(self, name: str, estimator, features: list[str]):
        self.name, self.estimator, self.features = name, estimator, list(features)

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> SklearnClassBaseline:
        self.estimator.fit(frame[self.features].to_numpy(dtype=float), np.asarray(y, dtype=int))
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict(frame[self.features].to_numpy(dtype=float)).astype(int)


def logistic_regression_baseline(name: str, features: list[str], *, balanced: bool = False,
                                 seed: int = 0) -> SklearnClassBaseline:
    """Multinomial logistic regression on standardised inputs (scaler fitted on the fitting rows, which is the
    training period or the training subsample, never validation or test); L2 penalty C=1, lbfgs.

    The inputs are the raw model features, so ``valid_hour_local`` and ``valid_weekday`` enter linearly as numbers:
    a weak encoding of a cyclic variable, the same raw inputs the other baselines get.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    estimator = make_pipeline(StandardScaler(), LogisticRegression(
        max_iter=2000, class_weight="balanced" if balanced else None, random_state=seed))
    return SklearnClassBaseline(name, estimator, features)


def random_forest_baseline(name: str, features: list[str], *, balanced: bool = False, seed: int = 0,
                           n_estimators: int = 300, min_samples_leaf: int = 20, max_samples: int | None = None,
                           n_jobs: int = 4) -> SklearnClassBaseline:
    """Random forest (``n_estimators`` trees, ``min_samples_leaf`` rows per leaf, bootstrap).

    ``max_samples`` caps the bootstrap draw of each tree: on the 918k-row training period an unlimited draw with 20-row
    leaves would hold roughly 2 GB of trees, so the full-period variant uses a smaller draw per tree (documented in the
    experiment config). ``balanced`` uses ``class_weight="balanced_subsample"`` (weights from each tree's bootstrap).
    """
    from sklearn.ensemble import RandomForestClassifier

    return SklearnClassBaseline(name, RandomForestClassifier(
        n_estimators=n_estimators, min_samples_leaf=min_samples_leaf, max_samples=max_samples,
        class_weight="balanced_subsample" if balanced else None, n_jobs=n_jobs, random_state=seed), features)


class RegressionThenBinned:
    """A regressor fitted on the raw target (µg/m3) whose output is classified with the scheme.

    ``fit`` takes the raw target in ``fit_values`` because the interface passes class indexes; callers set
    ``values`` before ``fit`` (see ``experiment_class``).
    """

    def __init__(self, name: str, estimator, features: list[str], scheme: ClassScheme):
        self.name, self.estimator, self.features, self.scheme = name, estimator, list(features), scheme
        self.values: np.ndarray | None = None

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> RegressionThenBinned:
        if self.values is None or len(self.values) != len(frame):
            raise ValueError("set .values (raw target of the fitting rows) before fit")
        self.estimator.fit(frame[self.features].to_numpy(dtype=float), np.asarray(self.values, dtype=float))
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.scheme.classify(self.estimator.predict(frame[self.features].to_numpy(dtype=float)))
