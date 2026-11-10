"""Ordinal decomposition of an ordered class target (Frank and Hall 2001), with winning-rule classifiers (AT-041e).

K ordered classes give K-1 binary problems "the class is above class k" (for the ICA NO2 task: NO2 > 40, > 90, > 120).
Each one is an ordinary two-class winning-rule classifier. The K-1 decisions are combined without probabilities:

* ``highest`` (primary): the class is the highest threshold decided as *exceeded* (class 0 if none is); a decision
  pattern is *inconsistent* when some threshold is exceeded while a lower one is not (e.g. > 90 yes, > 40 no).
* ``count`` (variant): the class is the number of thresholds decided as exceeded.

A binary classifier with no firing rule (``-1``) gives no decision: it counts as *not exceeded* in the combination and
is reported (``share_any_unknown``). The class is unknown (``-1``) only when all K-1 binary classifiers have no rule
firing. The two combinations coincide on consistent patterns.

Publishing this needs a new inference family in the contract: see ``docs/ml/madrid_no2_h6_ica_v3.md``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from atlas.ml.calibration import coordinate_ascent
from atlas.ml.classification import classification_metrics


def threshold_targets(y_class: np.ndarray, n_classes: int) -> np.ndarray:
    """``(n, K-1)`` int array: column k is 1 where the class index is above ``k`` (``-1`` classes stay 0)."""
    y = np.asarray(y_class, dtype=int)
    return (y[:, None] > np.arange(n_classes - 1)[None, :]).astype(int)


def combine(decisions: np.ndarray, how: str = "highest") -> np.ndarray:
    """Class index per row from ``(n, K-1)`` binary decisions (1 = exceeded; -1 = no decision, counted as 0)."""
    d = np.asarray(decisions) == 1
    if how == "count":
        pred = d.sum(axis=1)
    elif how == "highest":
        k = d.shape[1]
        pred = np.where(d.any(axis=1), k - np.argmax(d[:, ::-1], axis=1), 0)
    else:
        raise ValueError(f"unknown combination {how!r}")
    return np.where((np.asarray(decisions) < 0).all(axis=1), -1, pred).astype(int)


def inconsistency_rate(decisions: np.ndarray) -> float:
    """Share of rows where some threshold is exceeded and a lower one is not (a ``-1`` counts as not exceeded)."""
    d = np.asarray(decisions) == 1
    return float(np.mean((d[:, 1:] & ~d[:, :-1]).any(axis=1)))


def decisions_with_factors(assoc: Sequence[np.ndarray], factors: Sequence[float]) -> np.ndarray:
    """Binary decisions from per-threshold ``(n, 2)`` class-association matrices (columns: not exceeded, exceeded).

    Exceeded when ``factor x association(exceeded)`` is above the association of *not exceeded*; ``-1`` when neither
    side has a rule firing. ``factors`` are the multipliers of the "exceeded" side.
    """
    cols = []
    for a, f in zip(assoc, factors, strict=True):
        pos, neg = a[:, 1] * f, a[:, 0]
        cols.append(np.where((pos <= 0) & (neg <= 0), -1, (pos > neg).astype(int)))
    return np.stack(cols, axis=1)


def tune_threshold_factors(assoc: Sequence[np.ndarray], y_class: np.ndarray, n_classes: int, *, how: str = "highest",
                           **kwargs) -> np.ndarray:
    """Factors of the "exceeded" side of each threshold maximising the 4-class macro-F1 of the combined prediction.

    Same coordinate ascent as the per-class calibration (``calibration.coordinate_ascent``), no anchor.
    """
    y = np.asarray(y_class, dtype=int)

    def score(f: np.ndarray) -> float:
        return classification_metrics(y, combine(decisions_with_factors(assoc, f), how), n_classes)["macro_f1"]

    return coordinate_ascent(score, len(assoc), anchor=None, **kwargs)
