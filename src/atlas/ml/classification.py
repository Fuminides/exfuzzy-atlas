"""Ordinal class targets and their metrics (AT-041c).

* ``ClassScheme``: the official band scheme of a target (the ICA NO2 bands of
  ``configs/ml/ica_no2_scheme.json``), ``classify`` for values and ``merge_rare_upper_tail`` for the one allowed
  adaptation: classes at the top with too few *training* rows are merged into their lower neighbour. Thresholds are
  never changed; a merged class keeps the lower bound of its lowest member and the upper bound of its highest.
* ``class_sample``: class-aware stratified subsample of the training rows (tempered by a power of the class counts).
* ``classification_metrics`` / ``classification_metric_rows``: macro-F1, balanced accuracy, accuracy, per-class
  precision / recall / F1, the confusion matrix, ordinal errors and per-slice values as ``MetricRow``s.

Predictions are integer class indexes in ``0..K-1`` ordered from best to worst band; ``-1`` means *no
prediction* (no rule fired, or an input was missing). Unknown is always counted as a wrong answer, never as a class.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from atlas.contracts.models import MetricRow, TargetClass, TargetScheme
from atlas.ml.subsample import stratified_subsample

UNKNOWN = -1
CLASSIFY_CHUNK = 2_000_000


class ClassBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    lower: float
    upper: float | None = None  # None: open-ended (the EAQI "Extremely poor", ">150")
    color: str | None = None  # None: no verified colour
    description: str | None = None
    note: str | None = None  # free text of the scheme file (e.g. "'>150' in the source: open-ended")
    merged_from: list[str] = Field(default_factory=list, description="Official labels merged into this class.")


class ClassScheme(BaseModel):
    """Ordered classes over a numeric target; both bounds are inclusive over whole-number values."""

    model_config = ConfigDict(extra="allow")

    name: str
    source_url: str
    unit: str
    classes: list[ClassBand]
    merged_label_suffix: str = " o peor"  # label of a merged tail: "<best member><suffix>" (EAQI: " or worse")
    below_first_as_first: bool = False  # values below the first lower bound (noise under 0) go to the first class

    @property
    def labels(self) -> list[str]:
        return [c.label for c in self.classes]

    def classify(self, values) -> np.ndarray:
        """Class index per value; ``-1`` for NaN, values below the first lower bound or above the last upper bound.

        Values are rounded half up to whole numbers first (the official table lists whole numbers); integer data
        are unaffected.
        """
        values = np.asarray(values)
        if values.ndim == 1 and len(values) > CLASSIFY_CHUNK:  # same result, without whole-array float64 temporaries
            return np.concatenate([self.classify(values[i:i + CLASSIFY_CHUNK])
                                   for i in range(0, len(values), CLASSIFY_CHUNK)])
        v = np.floor(np.asarray(values, dtype=float) + 0.5)
        uppers = np.array([np.inf if c.upper is None else c.upper for c in self.classes])
        idx = np.searchsorted(uppers, v, side="left")  # first class whose upper bound >= v
        bad = ~np.isfinite(v) | (idx >= len(self.classes))
        if not self.below_first_as_first:
            bad |= v < self.classes[0].lower
        return np.where(bad, UNKNOWN, np.minimum(idx, len(self.classes) - 1)).astype(int)

    def to_target_scheme(self) -> TargetScheme:
        """The contract ``TargetScheme``: contiguous ``(lower, upper]`` classes.

        The official table lists whole numbers with both ends inclusive (41-90), which for whole-number data is
        exactly ``(40, 90]``; so each lower bound is the previous class's upper bound, ``boundary`` is
        ``upper_inclusive`` and the first class is unbounded below. For non-integer values the model's own
        ``classify`` rounds first, as the official table implies.
        """
        classes = [
            TargetClass(label=c.label, lower=None if i == 0 else self.classes[i - 1].upper, upper=c.upper,
                        color=c.color, description=c.description)
            for i, c in enumerate(self.classes)
        ]
        return TargetScheme(name=self.name, source_url=self.source_url, unit=self.unit, boundary="upper_inclusive",
                            classes=classes)

    def merge_rare_upper_tail(self, counts: Sequence[int], min_count: int | None = None, *,
                              min_share: float | None = None) -> ClassScheme:
        """Merge, from the top, every class with too few rows into the class below it.

        "Too few" is fewer than ``min_count`` rows, or (``min_share``, exclusive with it) a share of the total
        ``counts`` below ``min_share``. The rule only looks at ``counts`` (training rows per class, fixed before any
        fit): walking down from the worst class, every rare class is merged with the next better one, and the walk
        stops at the first class that has enough. The merged class is labelled
        ``"<best member><merged_label_suffix>"`` (Madrid: ``"... o peor"``).
        """
        if len(counts) != len(self.classes):
            raise ValueError("one count per class is required")
        if (min_count is None) == (min_share is None):
            raise ValueError("give exactly one of min_count and min_share")
        if min_share is not None:
            if not 0 < min_share < 1:
                raise ValueError("min_share must be in (0, 1)")
            min_count = min_share * float(np.sum(counts))
        keep = len(self.classes)  # classes[keep:] are merged into classes[keep - 1]
        while keep > 1 and counts[keep - 1] < min_count:
            keep -= 1
        if keep == len(self.classes):
            return self.model_copy(deep=True)
        tail = self.classes[keep - 1:]
        base = tail[0]
        merged = ClassBand(
            label=f"{base.label}{self.merged_label_suffix}", lower=base.lower, upper=tail[-1].upper, color=base.color,
            description=base.description, merged_from=[c.label for c in tail],
        )
        out = self.model_copy(deep=True)
        out.classes = [c.model_copy(deep=True) for c in self.classes[:keep - 1]] + [merged]
        return out


def load_scheme(path: str | Path) -> ClassScheme:
    return ClassScheme.model_validate(json.loads(Path(path).read_text()))


def class_counts(y_class: np.ndarray, n_classes: int) -> np.ndarray:
    y_class = np.asarray(y_class)
    return np.bincount(y_class[y_class >= 0], minlength=n_classes)


def class_quotas(counts: np.ndarray, n_rows: int, power: float) -> np.ndarray:
    """Rows to take per class: proportional to ``count ** power``, a class never above its size (water-filling)."""
    counts = np.asarray(counts, dtype=float)
    n_classes = len(counts)
    quota = np.zeros(n_classes)
    free = counts > 0
    remaining = float(n_rows)
    while True:  # water-filling: cap classes at their size, share the rest by weight
        weights = np.where(free, counts**power, 0.0)
        share = remaining * weights / weights.sum()
        over = free & (share >= counts)
        if not over.any():
            quota[free] = share[free]
            break
        quota[over] = counts[over]
        free &= ~over
        remaining = n_rows - quota[~free].sum()
        if not free.any():
            break
    take = np.floor(quota).astype(int)
    take[np.argsort(-(quota - take), kind="stable")[: n_rows - int(take.sum())]] += 1  # largest remainders
    return np.minimum(take, counts.astype(int))


def class_sample(
    y_class: np.ndarray, entity_id: np.ndarray, issued_at_utc: pd.DatetimeIndex, n_rows: int, seed: int,
    power: float,
) -> np.ndarray:
    """Positions of a training subsample whose class sizes are proportional to ``count ** power``.

    ``power = 1`` keeps the natural class proportions (the entity x month block sampling of AT-041 inside every
    class); ``power = 0`` is fully balanced; ``0.5`` is the square-root compromise. A class with fewer rows than
    its quota is taken whole and the remainder is redistributed to the other classes in proportion to their
    quotas. Within a class the draw is uniform over entity x month blocks (``stratified_subsample``).
    """
    y_class = np.asarray(y_class)
    n_classes = int(y_class.max()) + 1
    take = class_quotas(np.bincount(y_class, minlength=n_classes), n_rows, power)
    picked = []
    for k in range(n_classes):
        members = np.flatnonzero(y_class == k)
        if take[k] and len(members):
            sub = stratified_subsample(entity_id[members], issued_at_utc[members], int(take[k]), seed + k)
            picked.append(members[sub])
    return np.sort(np.concatenate(picked))


def nested_class_sample(
    y_class: np.ndarray, entity_id: np.ndarray, issued_at_utc: pd.DatetimeIndex, n_rows: int, seed: int,
    power: float,
) -> np.ndarray:
    """Like ``class_sample`` (same class quotas), but samples of different sizes are nested (AT-041g).

    Within a class every row gets the key ``(rank_in_block + u_block) / block_size``: the rank comes from a seeded
    random permutation inside its entity x month block and ``u_block`` is one seeded uniform offset per block. A
    sample is the first ``quota`` rows of the class by key, so a smaller sample is a prefix of a larger one
    (same ``seed``, same ``power``) and every block contributes its proportional share to within one row.
    """
    y_class = np.asarray(y_class)
    n_classes = int(y_class.max()) + 1
    take = class_quotas(np.bincount(y_class, minlength=n_classes), n_rows, power)
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issue times must be timezone-aware (UTC)")
    utc = stamps.tz_convert("UTC")
    month = np.asarray(utc.year * 100 + utc.month)
    block_label = pd.Series(np.asarray(entity_id).astype(str)) + "|" + pd.Series(month.astype(str))
    picked = []
    for k in range(n_classes):
        members = np.flatnonzero(y_class == k)
        if not (take[k] and len(members)):
            continue
        codes, uniques = pd.factorize(block_label.iloc[members], sort=True)
        sizes = np.bincount(codes, minlength=len(uniques))
        rng = np.random.default_rng(seed + k)
        offset = rng.random(len(uniques))
        shuffle = rng.permutation(len(members))  # one random order of the class; rank inside a block follows it
        order = np.lexsort((shuffle, codes))  # grouped by block, random order inside
        starts = np.concatenate([[0], np.cumsum(sizes)])[:-1]
        rank = np.empty(len(members))
        rank[order] = np.arange(len(members)) - np.repeat(starts, sizes)
        key = (rank + offset[codes]) / sizes[codes]
        picked.append(members[np.argsort(key, kind="stable")[: int(take[k])]])
    return np.sort(np.concatenate(picked))


# ------------------------------------------------------------------------------------------------- metrics


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> np.ndarray:
    """(n_classes, n_classes + 1): rows true class, columns predicted class plus a final ``no prediction`` column."""
    y_true, y_pred = np.asarray(y_true, dtype=int), np.asarray(y_pred, dtype=int)
    cols = np.where(y_pred < 0, n_classes, y_pred)
    out = np.zeros((n_classes, n_classes + 1), dtype=np.int64)
    np.add.at(out, (y_true, cols), 1)
    return out


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> dict:
    """Scalar and per-class metrics. Classes absent from ``y_true`` are left out of the macro / balanced averages
    (their recall is undefined); a class never predicted has precision 0 when it exists in ``y_true``.
    """
    y_true, y_pred = np.asarray(y_true, dtype=int), np.asarray(y_pred, dtype=int)
    cm = confusion_matrix(y_true, y_pred, n_classes)
    support = cm.sum(axis=1)
    predicted = cm[:, :n_classes].sum(axis=0)
    tp = np.diag(cm[:, :n_classes])
    with np.errstate(divide="ignore", invalid="ignore"):
        recall = np.where(support > 0, tp / support, np.nan)
        precision = np.where(predicted > 0, tp / predicted, 0.0)
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), 0.0)
    present = support > 0
    known = y_pred >= 0
    gap = np.abs(y_pred[known] - y_true[known])
    return {
        "n": int(len(y_true)),
        "confusion": cm,
        "support": support,
        "precision": precision,
        "recall": recall,
        "f1": np.where(present, f1, np.nan),
        "macro_f1": float(np.mean(f1[present])),
        "balanced_accuracy": float(np.mean(recall[present])),
        "accuracy": float(np.mean(y_pred == y_true)),
        "mae_class_index": float(gap.mean()) if known.any() else float("nan"),
        "share_off_by_2plus": float(np.mean(gap >= 2)) if known.any() else float("nan"),
        "share_unknown": float(np.mean(~known)),
    }


def classification_metric_rows(
    estimator: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: Sequence[str],
    slices: Mapping[str, np.ndarray] | None = None,
    prefix: str = "",
    per_slice_scalar: Sequence[str] = ("macro_f1", "accuracy"),
) -> list[MetricRow]:
    """Rows for slice ``all`` (everything) and, per ``slices`` label, ``macro_f1`` and ``accuracy`` only.

    Per-class rows use names like ``recall[Regular]``; the confusion matrix is ``confusion[true>predicted]`` with
    ``n`` = the number of rows of the true class and ``no_prediction`` as the last predicted column.
    """
    k = len(labels)
    res = classification_metrics(y_true, y_pred, k)
    sl = prefix + "all"
    rows = [MetricRow(estimator=estimator, metric=name, value=float(res[name]), n=res["n"], slice=sl)
            for name in ("macro_f1", "balanced_accuracy", "accuracy", "mae_class_index", "share_off_by_2plus",
                         "share_unknown") if np.isfinite(res[name])]
    for i, label in enumerate(labels):
        if res["support"][i]:
            rows.append(MetricRow(estimator=estimator, metric=f"recall[{label}]", value=float(res["recall"][i]),
                                  n=int(res["support"][i]), slice=sl))
            rows.append(MetricRow(estimator=estimator, metric=f"f1[{label}]", value=float(res["f1"][i]),
                                  n=int(res["support"][i]), slice=sl))
        n_pred = int(res["confusion"][:, i].sum())
        rows.append(MetricRow(estimator=estimator, metric=f"precision[{label}]", value=float(res["precision"][i]),
                              n=n_pred, slice=sl))
        for j, other in enumerate([*labels, "no_prediction"]):
            rows.append(MetricRow(estimator=estimator, metric=f"confusion[{label}>{other}]",
                                  value=float(res["confusion"][i, j]), n=int(res["support"][i]), slice=sl))
    for name, values in (slices or {}).items():
        values = values if isinstance(values, pd.Categorical) else np.asarray(values)  # categorical: fast compare
        for value in pd.unique(values):
            sel = values == value
            sub = classification_metrics(np.asarray(y_true)[sel], np.asarray(y_pred)[sel], k)
            rows += [MetricRow(estimator=estimator, metric=m, value=float(sub[m]), n=int(sel.sum()),
                               slice=f"{prefix}{name}={value}") for m in per_slice_scalar if np.isfinite(sub[m])]
    return rows
