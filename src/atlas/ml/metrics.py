"""Regression metrics as ``MetricRow``s, overall and per slice (entity, month, hour, ...)."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from atlas.contracts.models import MetricRow


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """MAE, RMSE and R2. R2 is omitted when it is undefined (fewer than 2 rows or a constant target)."""
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    out = {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
    }
    if len(y_true) >= 2 and np.ptp(y_true) > 0:
        out["r2"] = float(r2_score(y_true, y_pred))
    return out


def metric_rows(
    estimator: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    slices: Mapping[str, pd.Series | np.ndarray] | None = None,
) -> list[MetricRow]:
    """Rows for slice ``all`` and, for each ``name -> labels`` in ``slices``, one slice ``name=label``."""
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    rows = [MetricRow(estimator=estimator, metric=k, value=v, n=len(y_true))
            for k, v in regression_metrics(y_true, y_pred).items()]
    for name, labels in (slices or {}).items():
        labels = np.asarray(labels)
        if len(labels) != len(y_true):
            raise ValueError(f"slice {name!r} has {len(labels)} labels for {len(y_true)} rows")
        for label in pd.unique(labels):
            sel = labels == label
            rows += [MetricRow(estimator=estimator, metric=k, value=v, n=int(sel.sum()), slice=f"{name}={label}")
                     for k, v in regression_metrics(y_true[sel], y_pred[sel]).items()]
    return rows
