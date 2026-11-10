"""Chronological split by issue time with an embargo, and a hard leakage check.

A row is identified by its issue time ``t``; its target is observed at ``t + horizon``. Periods are the
half-open intervals of ``SplitSpec`` and consecutive periods are separated by ``embargo_hours``, which must be
at least the horizon so that no training target is observed after the next period starts. No shuffling.
Fit-time transforms (imputers, scalers, fuzzy partitions, climatology) are fitted on the training rows only.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from atlas.contracts.models import SplitSpec

PERIODS = ("train", "validation", "test")


def chronological_split_spec(
    issued_at_utc: pd.Series | pd.DatetimeIndex,
    *,
    horizon_hours: int,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    embargo_hours: int | None = None,
) -> SplitSpec:
    """Lay train / validation / test one after the other over the span of the issue times.

    The remaining fraction goes to test. Each gap is ``embargo_hours`` (default: ``horizon_hours``) and is
    taken out of the span before the fractions are applied; boundaries are floored to the hour.
    ``validation_fraction=0`` gives a split without validation.
    """
    embargo = horizon_hours if embargo_hours is None else embargo_hours
    if embargo < horizon_hours:
        raise ValueError("embargo_hours must be at least horizon_hours")
    test_fraction = 1.0 - train_fraction - validation_fraction
    if train_fraction <= 0 or validation_fraction < 0 or test_fraction <= 0:
        raise ValueError("fractions must leave positive room for train and test")
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issue times must be timezone-aware (UTC)")
    first, last = stamps.min().tz_convert("UTC"), stamps.max().tz_convert("UTC")
    end = last + pd.Timedelta(seconds=1)  # half-open: the last issue time belongs to the test period
    gaps = 2 if validation_fraction > 0 else 1
    usable = (end - first) - gaps * pd.Timedelta(hours=embargo)
    if usable <= pd.Timedelta(0):
        raise ValueError("the time span is shorter than the embargo gaps")
    train_to = (first + usable * train_fraction).floor("h")
    if validation_fraction > 0:
        validation_from = train_to + pd.Timedelta(hours=embargo)
        validation_to = (validation_from + usable * validation_fraction).floor("h")
        test_from = validation_to + pd.Timedelta(hours=embargo)
    else:
        validation_from = validation_to = None
        test_from = train_to + pd.Timedelta(hours=embargo)
    return SplitSpec(
        train_from_utc=first.to_pydatetime(), train_to_utc=train_to.to_pydatetime(),
        validation_from_utc=None if validation_from is None else validation_from.to_pydatetime(),
        validation_to_utc=None if validation_to is None else validation_to.to_pydatetime(),
        test_from_utc=test_from.to_pydatetime(), test_to_utc=end.to_pydatetime(), embargo_hours=embargo,
    )


def split_masks(issued_at_utc: pd.Series | pd.DatetimeIndex, spec: SplitSpec) -> dict[str, np.ndarray]:
    """Boolean masks per period (``validation`` only if the spec has one). Rows in the gaps belong to none."""
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issue times must be timezone-aware (UTC)")
    bounds = {"train": (spec.train_from_utc, spec.train_to_utc), "test": (spec.test_from_utc, spec.test_to_utc)}
    if spec.validation_from_utc is not None:
        bounds["validation"] = (spec.validation_from_utc, spec.validation_to_utc)
    return {name: np.asarray((stamps >= lo) & (stamps < hi)) for name, (lo, hi) in bounds.items()}


def assert_no_temporal_leakage(
    issued_at_utc: pd.Series | pd.DatetimeIndex, masks: dict[str, np.ndarray], horizon_hours: int
) -> None:
    """Fail if any earlier period has a target observed (``issued + horizon``) after a later period begins."""
    stamps = pd.DatetimeIndex(issued_at_utc)
    horizon = timedelta(hours=horizon_hours)
    ordered = [name for name in PERIODS if name in masks and masks[name].any()]
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        last_target = stamps[masks[earlier]].max() + horizon
        first_issue = stamps[masks[later]].min()
        if last_target > first_issue:
            raise ValueError(
                f"temporal leakage: {earlier} targets are observed up to {last_target}, "
                f"but {later} is issued from {first_issue}"
            )
    for a, b in zip(ordered, ordered[1:], strict=False):
        if (masks[a] & masks[b]).any():
            raise ValueError(f"periods {a} and {b} overlap")
