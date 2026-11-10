"""Stratified, reproducible subsample of training rows (AT-041).

ex_fuzzy needs about 2.3 KB of RAM and 0.5 to 0.9 microseconds per row and evaluation, so the Madrid fit cannot use
every training row (``docs/ml/exfuzzy_api_notes.md`` section 7). The subsample is drawn from the *training period
only*, uniformly within blocks (``entity_id`` x calendar month of ``issued_at_utc`` in UTC), with the same sampling
fraction in every block so every station and season keeps its share. Rows are independent once lags are
materialised, so thinning does not break the time structure that the chronological split already protects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

METHOD = "uniform_within_entity_x_month_blocks"


def _allocate(sizes: np.ndarray, n_target: int) -> np.ndarray:
    """Per-block counts proportional to ``sizes`` (largest remainder), each at most the block size."""
    total = int(sizes.sum())
    if n_target >= total:
        return sizes.copy()
    exact = sizes * (n_target / total)
    counts = np.floor(exact).astype(int)
    short = n_target - int(counts.sum())
    # Largest fractional parts first; ties broken by position, so the allocation is deterministic.
    order = np.argsort(-(exact - counts), kind="stable")
    counts[order[:short]] += 1
    return np.minimum(counts, sizes)


def _block_codes(entity_id: np.ndarray, month: np.ndarray) -> tuple[np.ndarray, pd.Index]:
    """Block code per row, equal to ``pd.factorize(entity + "|" + month, sort=True)`` without building a string per row.

    The blocks (entity x month) are few (thousands) next to the rows (millions): the strings are built for the
    distinct pairs only and sorted as before, so the code order (and hence the random draws) does not change.
    """
    ent_codes, ent_uniques = pd.factorize(entity_id)
    if (ent_codes < 0).any():
        raise ValueError("entity_id must not be null")
    months, month_codes = np.unique(month, return_inverse=True)
    pair, pair_codes = np.unique(ent_codes.astype(np.int64) * len(months) + month_codes, return_inverse=True)
    names = pd.Series([f"{ent_uniques[p // len(months)]}|{months[p % len(months)]}" for p in pair])
    ranks, uniques = pd.factorize(names, sort=True)
    return ranks[pair_codes], uniques


def stratified_subsample(
    entity_id: pd.Series | np.ndarray, issued_at_utc: pd.Series | pd.DatetimeIndex, n_target: int, seed: int
) -> np.ndarray:
    """Sorted positional indices of ``n_target`` rows (or all rows if fewer), uniform within entity x month blocks."""
    if n_target <= 0:
        raise ValueError("n_target must be positive")
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issue times must be timezone-aware (UTC)")
    utc = stamps.tz_convert("UTC")
    month = np.asarray(utc.year * 100 + utc.month)
    codes, uniques = _block_codes(entity_id if isinstance(entity_id, pd.Categorical) else np.asarray(entity_id), month)
    sizes = np.bincount(codes, minlength=len(uniques))
    counts = _allocate(sizes, n_target)
    order = np.argsort(codes, kind="stable")  # positions grouped by block, original order inside a block
    starts = np.concatenate([[0], np.cumsum(sizes)])
    rng = np.random.default_rng(seed)
    chosen = []
    for b, take in enumerate(counts):
        if take:
            members = order[starts[b]:starts[b + 1]]
            chosen.append(members if take == len(members) else rng.choice(members, size=take, replace=False))
    return np.sort(np.concatenate(chosen)) if chosen else np.array([], dtype=int)


def subsample_spec(
    entity_id: np.ndarray, issued_at_utc: pd.DatetimeIndex, selected: np.ndarray, *, n_target: int, seed: int,
    train_from_utc: str, train_to_utc: str, excluded_windows: list[list[str]] | None = None,
) -> dict:
    """JSON-serialisable description of a subsample (with the realised block counts), enough to redraw it."""
    sel_entities = np.asarray(entity_id)[selected]
    return {
        "method": METHOD,
        "n_requested": int(n_target),
        "n_selected": int(len(selected)),
        "seed": int(seed),
        "train_from_utc": train_from_utc,
        "train_to_utc": train_to_utc,
        "excluded_windows_utc": excluded_windows or [],
        "n_candidate_rows": int(len(entity_id)),
        "rows_per_entity": {str(k): int(v) for k, v in pd.Series(sel_entities).value_counts().sort_index().items()},
        "first_issue_utc": issued_at_utc[selected].min().isoformat() if len(selected) else None,
        "last_issue_utc": issued_at_utc[selected].max().isoformat() if len(selected) else None,
    }
