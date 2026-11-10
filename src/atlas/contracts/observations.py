"""Arrow form of the canonical observation record and a DuckDB validator for it.

Pipelines may keep wide tables internally, but whatever they publish as canonical
observations (Parquet) must pass :func:`validate_observations`. The checks run in DuckDB,
so a partitioned Parquet dataset is validated without loading it into RAM.

The duplicate check groups by the 5-column key and needs memory in proportion to the rows it sees (about 117 bytes per
row measured on 8.3 M rows: docs/qa/volume.md). ``validate_observations`` therefore runs under a DuckDB ``memory_limit``
(spilling to ``temp_directory`` beyond it), and :func:`validate_observations_partitioned` validates a hive-partitioned
dataset one partition at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
import pyarrow as pa

from atlas.contracts.models import Censoring, Domain, MissingReason

_TS = pa.timestamp("us", tz="UTC")

OBSERVATION_SCHEMA = pa.schema(
    [
        ("domain", pa.string()),
        ("entity_id", pa.string()),
        ("timestamp_utc", _TS),
        ("source_timestamp_local", pa.string()),
        ("timezone", pa.string()),
        ("feature_name", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("validity_flag", pa.string()),
        ("missing_reason", pa.string()),
        ("censoring", pa.string()),
        ("source_id", pa.string()),
        ("data_version", pa.string()),
        ("aggregation_window_start_utc", _TS),
        ("aggregation_window_end_utc", _TS),
        ("n_records", pa.int64()),
    ]
)

REQUIRED_COLUMNS = (
    "domain", "entity_id", "timestamp_utc", "timezone", "feature_name", "unit", "source_id", "data_version",
)
UNIQUE_KEY = ("domain", "entity_id", "timestamp_utc", "feature_name", "source_id")
DEFAULT_MEMORY_LIMIT = "1GB"

_DUCKDB_TYPES = {
    pa.string(): "VARCHAR",
    _TS: "TIMESTAMP WITH TIME ZONE",
    pa.float64(): "DOUBLE",
    pa.int64(): "BIGINT",
}


def _quoted(values) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


def _sql_string(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def validate_observations(
    source: pa.Table | str | Path | Sequence[str | Path], *, memory_limit: str = DEFAULT_MEMORY_LIMIT,
    temp_directory: str | Path | None = None,
) -> list[str]:
    """Check a table or Parquet path/glob against the canonical observation contract.

    Args:
        source: an Arrow table, or a Parquet file, directory glob or hive-partitioned path (or a list of them).
        memory_limit: DuckDB ``memory_limit`` of the validating connection (``"1GB"`` by default; DuckDB's own default
            is 80 % of the RAM). Beyond it the duplicate check spills to ``temp_directory`` instead of growing.
        temp_directory: where DuckDB spills (default: DuckDB's own, ``.tmp`` in the working directory).

    Returns:
        Human-readable violations; an empty list means the data conforms.
    """
    con = duckdb.connect(config={"memory_limit": memory_limit})
    con.execute("SET TimeZone = 'UTC'")
    if temp_directory is not None:
        con.execute(f"SET temp_directory = {_sql_string(temp_directory)}")
    if isinstance(source, pa.Table):
        con.register("obs", source)
    else:
        paths = [source] if isinstance(source, str | Path) else list(source)
        listed = "[" + ", ".join(_sql_string(p) for p in paths) + "]"
        con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet({listed}, hive_partitioning = true)")

    found = {row[0]: row[1] for row in con.execute("DESCRIBE obs").fetchall()}
    errors = []
    for field in OBSERVATION_SCHEMA:
        expected = _DUCKDB_TYPES[field.type]
        if field.name not in found:
            errors.append(f"missing column {field.name}")
        elif found[field.name] != expected:
            errors.append(f"column {field.name} is {found[field.name]}, expected {expected}")
    if errors:
        return errors  # the row checks below assume the schema

    checks = {
        "required column is null": " OR ".join(f"{c} IS NULL" for c in REQUIRED_COLUMNS),
        "unknown domain": f"domain NOT IN ({_quoted(Domain)})",
        "unknown missing_reason": f"missing_reason NOT IN ({_quoted(MissingReason)})",
        "unknown censoring": f"censoring NOT IN ({_quoted(Censoring)})",
        "null value without missing_reason": "value IS NULL AND missing_reason IS NULL",
        "value present with missing_reason": "value IS NOT NULL AND missing_reason IS NOT NULL",
        "non-finite value": "value IS NOT NULL AND NOT isfinite(value)",
        "half-open aggregation window": (
            "(aggregation_window_start_utc IS NULL) <> (aggregation_window_end_utc IS NULL)"
        ),
        "aggregation window end <= start": "aggregation_window_end_utc <= aggregation_window_start_utc",
    }
    for label, condition in checks.items():
        n = con.execute(f"SELECT count(*) FROM obs WHERE {condition}").fetchone()[0]
        if n:
            errors.append(f"{label}: {n} rows")

    key = ", ".join(UNIQUE_KEY)
    dupes = con.execute(
        f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) AS n FROM obs GROUP BY {key} HAVING n > 1)"
    ).fetchone()[0]
    if dupes:
        errors.append(f"duplicate rows on ({key}): {dupes}")
    return errors


def _time_ranges(directories: list[Path]) -> list[tuple[object, object]]:
    con = duckdb.connect()
    return [
        con.execute(
            f"SELECT min(timestamp_utc), max(timestamp_utc) FROM read_parquet({_sql_string(d / '*.parquet')})"
        ).fetchone()
        for d in directories
    ]


def validate_observations_partitioned(
    root: str | Path, *, memory_limit: str = DEFAULT_MEMORY_LIMIT, temp_directory: str | Path | None = None,
) -> list[str]:
    """Validate a hive-partitioned dataset (``root/year=Y/month=M/*.parquet``) one partition at a time.

    Memory is bounded by the largest partition instead of the dataset (8.3 M rows: 1.1 GB at once, 160 MB per month).
    A partition is every directory under ``root`` that holds Parquet files. Errors are prefixed with the partition.

    **Duplicates stay exact** as long as the partition is a function of ``timestamp_utc`` (calendar month in UTC, or in
    a local zone): ``timestamp_utc`` is part of the unique key, so two rows with the same key have the same timestamp
    and are always in the same partition. This is checked, not assumed: partitions whose ``[min, max]`` timestamp
    ranges overlap are validated together, in one call, so that the result is exact for any layout; only the memory
    saving is lost for them.
    """
    root = Path(root)
    directories = sorted({p.parent for p in root.rglob("*.parquet")})
    if not directories:
        return [f"no Parquet files under {root}"]
    ranges = _time_ranges(directories)
    order = sorted(range(len(directories)), key=lambda i: (ranges[i][0] is None, ranges[i][0]))
    groups: list[list[int]] = []  # runs of partitions whose time ranges chain together
    reach = None
    for i in order:
        low, high = ranges[i]
        if groups and low is not None and reach is not None and low <= reach:
            groups[-1].append(i)
            reach = max(reach, high)
        else:
            groups.append([i])
            reach = high
    errors: list[str] = []
    for group in groups:
        names = [directories[i].relative_to(root).as_posix() for i in sorted(group)]
        found = validate_observations(
            [directories[i] / "*.parquet" for i in sorted(group)], memory_limit=memory_limit,
            temp_directory=temp_directory,
        )
        errors += [f"[{', '.join(names)}] {e}" for e in found]
    return errors
