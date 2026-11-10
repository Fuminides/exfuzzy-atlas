"""Memory-bounded loading of a large feature table (AT-070: Germany, 27 M rows).

``pd.read_parquet`` of the whole Germany table plus the ``np.isfinite(frame[...].to_numpy(float))`` of
``experiment.Data`` needs more than 6 GB. ``load_complete_compact`` reads the table batch by batch and keeps only the
**complete** rows (the table's ``complete`` flag and finite target and features, exactly the rows that
``Data.complete`` marks), in a compact frame:

* ``entity_id`` as a categorical (a few hundred distinct stations), ``issued_at_utc`` as UTC timestamps;
* the target and the persistence feature in float64 (the class of the target and of the persistence baseline must be
  the one of the table), every other feature in float32 (relative error below 6e-8; the published model is scored on
  the float64 table);
* ``complete`` is all True when the config has a ``complete_column``.

Because only complete rows are kept, every position-based result of ``Data`` (``train_pos``, ``positions(period)``)
and every count, merge and subsample are those of the full frame restricted to its complete rows, in the same row
order (``pd.read_parquet`` order: the dataset's fragments in path order). Rows that are not complete are never used by
any arm, so they are not needed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds


def load_complete_compact(path: Path, *, target_column: str, features: list[str], complete_column: str | None,
                          float64_columns: list[str] | tuple[str, ...] = ()) -> pd.DataFrame:
    """Complete rows of the parquet file or hive directory ``path`` (see the module docstring)."""
    wide = {target_column, *float64_columns}
    columns = ["entity_id", "issued_at_utc", target_column, *[f for f in features if f != target_column]]
    if complete_column:
        columns.append(complete_column)
    dataset = ds.dataset(str(path), format="parquet", partitioning="hive")
    flag = ds.field(complete_column) == True if complete_column else None  # noqa: E712 - arrow expression
    capacity = dataset.count_rows(filter=flag)
    numeric = [c for c in columns if c not in ("entity_id", "issued_at_utc", complete_column)]
    out = {c: np.empty(capacity, dtype=np.float64 if c in wide else np.float32) for c in numeric}
    issued = np.empty(capacity, dtype="datetime64[us]")
    codes = np.empty(capacity, dtype=np.int32)
    categories: dict[str, int] = {}
    n, tz = 0, None
    for batch in dataset.scanner(columns=columns, filter=flag, batch_size=1 << 18,
                           fragment_readahead=1, batch_readahead=1, use_threads=False).to_batches():
        if not batch.num_rows:
            continue
        keep = np.ones(batch.num_rows, dtype=bool)
        arrays = {}
        for c in numeric:
            values = batch.column(c).to_numpy(zero_copy_only=False).astype(np.float64, copy=False)
            keep &= np.isfinite(values)
            arrays[c] = values
        encoded = batch.column("entity_id").dictionary_encode()
        remap = np.array([categories.setdefault(str(s), len(categories)) for s in encoded.dictionary.to_pylist()],
                         dtype=np.int32)
        stamp = batch.column("issued_at_utc")
        if stamp.type.tz is None:
            raise ValueError("issued_at_utc must be timezone-aware UTC")
        tz = stamp.type.tz
        k = int(keep.sum())
        for c in numeric:
            out[c][n:n + k] = arrays[c][keep]
        issued[n:n + k] = stamp.to_numpy(zero_copy_only=False).astype("datetime64[us]")[keep]
        codes[n:n + k] = remap[encoded.indices.to_numpy(zero_copy_only=False)][keep]
        n += k
    frame = pd.DataFrame({
        "entity_id": pd.Categorical.from_codes(codes[:n], categories=list(categories)),
        "issued_at_utc": pd.DatetimeIndex(issued[:n]).tz_localize("UTC").tz_convert(tz),
        **{c: out[c][:n] for c in columns if c in out},
    }, copy=False)  # the columns are views of the preallocated arrays: no second copy of the table
    pa.default_memory_pool().release_unused()
    if complete_column:
        frame[complete_column] = np.ones(n, dtype=bool)
    return frame
