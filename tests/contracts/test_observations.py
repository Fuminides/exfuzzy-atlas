from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas.contracts.observations import validate_observations, validate_observations_partitioned

PARQUET = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "observations_air.parquet"


def table():
    return pq.read_table(PARQUET)


def test_fixture_conforms_from_path_and_table():
    assert validate_observations(PARQUET) == []
    assert validate_observations(table()) == []


def test_detects_duplicates():
    t = table()
    assert any("duplicate rows" in e for e in validate_observations(pa.concat_tables([t, t.slice(0, 3)])))


def test_detects_null_value_without_reason():
    t = table()
    reasons = pc.if_else(pc.is_null(t["value"]), pa.scalar(None, pa.string()), t["missing_reason"])
    t = t.set_column(t.schema.get_field_index("missing_reason"), "missing_reason", reasons)
    assert any("null value without missing_reason" in e for e in validate_observations(t))


def test_detects_wrong_types_and_missing_columns():
    t = table()
    t = t.set_column(t.schema.get_field_index("value"), "value", pc.cast(t["value"], pa.string()))
    assert sorted(validate_observations(t.drop_columns(["unit"]))) == [
        "column value is VARCHAR, expected DOUBLE", "missing column unit",
    ]


# ------------------------------------------------------------------ memory limit and per-partition validation (B6)


def write_partitions(root, t, key):
    """Split ``t`` into ``root/<key(row)>/part.parquet`` directories."""
    keys = [key(ts) for ts in t["timestamp_utc"].to_pylist()]
    for k in sorted(set(keys)):
        d = root / k
        d.mkdir(parents=True, exist_ok=True)
        mask = pa.array([x == k for x in keys])
        pq.write_table(t.filter(mask), d / "part.parquet")
    return root


def by_hour(ts):
    """The fixture spans six hours of one day, so an hour partition stands in for a month in a real dataset."""
    return f"year={ts.year}/month={ts.month:02d}/hour={ts.hour:02d}"


def test_memory_limit_and_temp_directory_are_applied(tmp_path, monkeypatch):
    seen = []
    real = duckdb.connect
    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: seen.append(k) or real(*a, **k))
    assert validate_observations(table()) == []
    assert seen[-1]["config"] == {"memory_limit": "1GB"}  # the default
    spill = tmp_path / "spill"
    assert validate_observations(table(), memory_limit="256MB", temp_directory=spill) == []
    assert seen[-1]["config"] == {"memory_limit": "256MB"}


def test_a_small_memory_limit_still_finds_the_duplicates(tmp_path):
    t = table()
    big = pa.concat_tables([t] * 300)  # ~ 300 x the fixture, duplicated on purpose
    errors = validate_observations(big, memory_limit="64MB", temp_directory=tmp_path / "spill")
    assert any(e.startswith("duplicate rows") for e in errors)


def test_a_list_of_paths_is_one_dataset(tmp_path):
    t = table()
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pq.write_table(t, a)
    pq.write_table(t, b)
    assert validate_observations([a]) == []
    assert any("duplicate rows" in e for e in validate_observations([a, b]))


def test_partitioned_validation_matches_the_whole_on_clean_data(tmp_path):
    root = write_partitions(tmp_path / "obs", table(), by_hour)
    assert len(list(root.rglob("*.parquet"))) > 1
    assert validate_observations(str(root / "**" / "*.parquet")) == []
    assert validate_observations_partitioned(root, memory_limit="256MB", temp_directory=tmp_path / "spill") == []


def test_partitioned_validation_reports_the_partition_of_a_violation(tmp_path):
    t = table()
    bad = t.slice(0, 1)
    reasons = pa.array(["not-a-reason"], pa.string())
    bad = bad.set_column(bad.schema.get_field_index("missing_reason"), "missing_reason", reasons)
    root = write_partitions(tmp_path / "obs", pa.concat_tables([t.slice(1), bad]), by_hour)
    errors = validate_observations_partitioned(root)
    assert errors and all(e.startswith("[year=") for e in errors)
    assert any("unknown missing_reason" in e for e in errors)


def test_duplicates_are_exact_when_the_partition_is_a_function_of_the_timestamp(tmp_path):
    t = table()
    dup = pa.concat_tables([t, t.slice(0, 5)])  # the same key twice: same timestamp, so the same partition
    root = write_partitions(tmp_path / "obs", dup, by_hour)
    whole = [e for e in validate_observations(str(root / "**" / "*.parquet")) if e.startswith("duplicate rows")]
    per_partition = [e for e in validate_observations_partitioned(root) if "duplicate rows" in e]
    assert len(whole) == 1 and whole[0].endswith(": 5")
    assert sum(int(e.rsplit(": ", 1)[1]) for e in per_partition) == 5


def test_partitions_that_overlap_in_time_are_validated_together_so_duplicates_are_never_missed(tmp_path):
    """A partition that is not a function of the timestamp (here: alternating batches) must not hide duplicates."""
    t = table()
    dup = pa.concat_tables([t, t.slice(0, 5)])
    parity = iter(range(10**6))
    root = tmp_path / "obs"
    for batch in range(2):
        mask = pa.array([next(parity) % 2 == batch for _ in range(dup.num_rows)])
        (root / f"batch={batch}").mkdir(parents=True)
        pq.write_table(dup.filter(mask), root / f"batch={batch}" / "part.parquet")
    whole = validate_observations(str(root / "**" / "*.parquet"))
    per_partition = validate_observations_partitioned(root)
    assert [e.rsplit(": ", 1)[1] for e in whole if e.startswith("duplicate rows")] == [
        e.rsplit(": ", 1)[1] for e in per_partition if "duplicate rows" in e]


def test_disjoint_partitions_are_validated_separately(tmp_path, monkeypatch):
    root = write_partitions(tmp_path / "obs", table(), by_hour)
    calls = []
    import atlas.contracts.observations as obs

    real = obs.validate_observations
    monkeypatch.setattr(obs, "validate_observations", lambda source, **k: calls.append(source) or real(source, **k))
    assert validate_observations_partitioned(root) == []
    assert len(calls) == len(list(root.rglob("*.parquet"))) and all(len(c) == 1 for c in calls)


def test_an_empty_dataset_is_an_error(tmp_path):
    assert validate_observations_partitioned(tmp_path) == [f"no Parquet files under {tmp_path}"]
