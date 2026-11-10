"""Cleaning + zone-hour aggregation on tiny hand-written trips (DuckDB, no network, no real data)."""

from datetime import datetime, timezone

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest
from mobility_helpers import LOOKUP_IDS, ZONE_IDS, trip, write_trips

from atlas.contracts.observations import OBSERVATION_SCHEMA, validate_observations
from atlas.domains.mobility.aggregate import REASONS, aggregate_month, connect

UTC = timezone.utc


def run_month(tmp_path, month, trips, **kwargs):
    con = connect("500MB", 2)
    out = tmp_path / f"{month}.parquet"
    result = aggregate_month(
        con, write_trips(tmp_path / f"in-{month}.parquet", trips), month, ZONE_IDS, LOOKUP_IDS, out,
        data_version="test-v1", **kwargs,
    )  # fmt: skip
    rows = duckdb.connect().execute("SELECT * FROM read_parquet(?)", [str(out)]).fetchdf()
    return result, rows, out


def value_at(rows, zone, utc_iso):
    stamp = datetime.fromisoformat(utc_iso).replace(tzinfo=UTC)
    hit = rows[(rows.entity_id == str(zone)) & (rows.timestamp_utc == stamp)]
    assert len(hit) == 1, f"expected one row for zone {zone} at {utc_iso}"
    return hit.iloc[0]


def test_counts_equal_raw_minus_filtered_and_every_filter_is_counted(tmp_path):
    trips = [
        trip("2025-01-10 08:05", zone=1),
        trip("2025-01-10 08:55", zone=1),
        trip("2025-01-10 09:00", zone=2),
        trip("2024-12-31 23:50", zone=1),  # before the file month
        trip("2025-02-01 00:00", zone=1),  # first instant of the next month: outside (half-open)
        trip("2025-01-10 10:00", dropoff="2025-01-10 09:00", zone=1),  # dropoff before pickup
        trip("2025-01-10 10:00", minutes=0, zone=1),  # zero duration
        trip("2025-01-10 10:00", minutes=6 * 60 + 1 / 60, zone=1),  # one minute over 6 h
        trip("2025-01-10 11:00", minutes=6 * 60, zone=2),  # exactly 6 h is kept
        trip("2025-01-10 12:00", zone=264),  # Unknown
        trip("2025-01-10 12:00", zone=265),  # Outside of NYC
        trip("2025-01-10 12:00", zone=999),  # not in the lookup
        trip("2025-01-10 12:00", zone=None),  # null zone
        trip("2025-01-10 12:00", minutes=None, zone=1),  # null dropoff
    ]
    result, rows, out = run_month(tmp_path, "2025-01", trips)
    assert result.raw_rows == len(trips)
    assert result.filtered == {
        "null_timestamp": 1,
        "pickup_outside_file_month": 2,
        "dropoff_before_pickup": 1,
        "zero_duration": 1,
        "duration_over_max": 1,
        "pickup_zone_invalid": 2,
        "pickup_zone_unknown_or_outside": 2,
        "pickup_nonexistent_local_hour": 0,
        "pickup_ambiguous_local_hour": 0,
    }
    assert set(result.filtered) == set(REASONS)
    assert result.kept_rows == 4 and result.raw_rows - sum(result.filtered.values()) == result.kept_rows
    assert rows["value"].sum() == result.kept_rows  # nothing kept is lost, nothing filtered leaks in
    assert result.special_zone_counts == {264: 1, 265: 1}
    # 08:05 and 08:55 local (EST) both land in the 13:00Z hour of zone 1
    first = value_at(rows, 1, "2025-01-10T13:00:00")
    assert first["value"] == 2 and first["n_records"] == 2
    assert value_at(rows, 2, "2025-01-10T14:00:00")["value"] == 1


def test_hour_boundaries_and_utc_conversion(tmp_path):
    trips = [trip("2025-01-01 00:59:59", zone=3), trip("2025-01-01 01:00:00", zone=3)]
    _, rows, _ = run_month(tmp_path, "2025-01", trips)
    midnight = value_at(rows, 3, "2025-01-01T05:00:00")  # local midnight in January is 05:00Z
    assert midnight["value"] == 1 and midnight["source_timestamp_local"] == "2025-01-01 00:00-0500"
    assert value_at(rows, 3, "2025-01-01T06:00:00")["value"] == 1


def test_zero_filled_inside_the_period_and_no_rows_outside(tmp_path):
    result, rows, _ = run_month(tmp_path, "2025-01", [trip("2025-01-15 12:00", zone=1)])
    hours = 31 * 24
    assert len(rows) == len(ZONE_IDS) * hours == result.output_rows
    assert rows.groupby("entity_id").size().eq(hours).all()  # every zone has every hour
    assert rows["value"].notna().all() and (rows["value"] >= 0).all()
    assert result.zero_rows == len(rows) - 1 and result.null_rows == 0
    zero = value_at(rows, 5, "2025-01-20T00:00:00")
    assert zero["value"] == 0 and zero["n_records"] == 0 and pd.isna(zero["missing_reason"])
    # nothing before local midnight of the 1st (05:00Z) nor from local midnight of the 1st of the next month (05:00Z)
    assert rows.timestamp_utc.min() == datetime(2025, 1, 1, 5, tzinfo=UTC)
    assert rows.timestamp_utc.max() == datetime(2025, 2, 1, 4, tzinfo=UTC)


def test_spring_forward_nonexistent_hour_is_dropped_and_counted(tmp_path):
    trips = [
        trip("2025-03-09 01:30", zone=1),
        trip("2025-03-09 02:15", zone=1),  # does not exist on that day
        trip("2025-03-09 02:45", zone=2),
        trip("2025-03-09 03:10", zone=1),
    ]
    result, rows, _ = run_month(tmp_path, "2025-03", trips)
    assert result.filtered["pickup_nonexistent_local_hour"] == 2
    assert result.nonexistent_trips_by_hour == {"2025-03-09 02:00:00": 2}
    assert result.kept_rows == 2
    assert value_at(rows, 1, "2025-03-09T06:00:00")["value"] == 1  # 01:30 EST
    assert value_at(rows, 1, "2025-03-09T07:00:00")["value"] == 1  # 03:10 EDT, the very next UTC hour
    assert rows["value"].notna().all()  # no hole on the UTC axis
    assert len(rows) == len(ZONE_IDS) * (31 * 24 - 1)


def test_fall_back_ambiguous_hour_becomes_null_in_both_utc_hours(tmp_path):
    trips = [
        trip("2025-11-02 00:30", zone=1),
        trip("2025-11-02 01:10", zone=1),  # EDT or EST: cannot tell
        trip("2025-11-02 01:50", zone=2),
        trip("2025-11-02 02:20", zone=1),
    ]
    result, rows, out = run_month(tmp_path, "2025-11", trips)
    assert result.filtered["pickup_ambiguous_local_hour"] == 2
    assert result.ambiguous_trips_by_hour == {"2025-11-02 01:00:00": 2}
    assert result.null_rows == 2 * len(ZONE_IDS)
    for stamp in ("2025-11-02T05:00:00", "2025-11-02T06:00:00"):
        for zone in ZONE_IDS:
            row = value_at(rows, zone, stamp)
            assert pd.isna(row["value"])  # null, never 0
            assert row["missing_reason"] == "invalid_observation" and row["validity_flag"] == "ambiguous_local_hour"
            assert pd.isna(row["n_records"])
    assert value_at(rows, 1, "2025-11-02T04:00:00")["value"] == 1  # 00:30 EDT
    assert value_at(rows, 1, "2025-11-02T07:00:00")["value"] == 1  # 02:20 EST
    assert validate_observations(out) == []


def test_output_passes_the_contract_validator_and_carries_no_trip_fields(tmp_path):
    result, rows, out = run_month(tmp_path, "2025-01", [trip("2025-01-02 09:00", zone=4)], count_duplicates=True)
    assert validate_observations(out) == []
    assert list(pq.read_schema(out).names) == OBSERVATION_SCHEMA.names  # no fare / dropoff / distance column survives
    assert set(rows.domain) == {"mobility"} and set(rows.feature_name) == {"pickups"} and set(rows.unit) == {"trips"}
    assert set(rows.timezone) == {"America/New_York"} and set(rows.source_id) == {"nyc-tlc-yellow"}
    start, end = rows.aggregation_window_start_utc, rows.aggregation_window_end_utc
    assert (rows.timestamp_utc == start).all() and ((end - start).dt.total_seconds() == 3600).all()
    assert result.duplicate_rows == 0


def test_exact_duplicate_rows_are_reported_not_removed(tmp_path):
    same = trip("2025-01-02 09:00", zone=4)
    result, rows, _ = run_month(tmp_path, "2025-01", [same, same, trip("2025-01-02 09:30", zone=4)])
    assert result.duplicate_rows == 1 and result.kept_rows == 3
    assert value_at(rows, 4, "2025-01-02T14:00:00")["value"] == 3


def test_missing_required_column_fails_loudly(tmp_path):
    import pyarrow as pa

    bad = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"tpep_pickup_datetime": pa.array([datetime(2025, 1, 1)], pa.timestamp("us"))}), bad)
    with pytest.raises(ValueError, match="lacks required columns"):
        aggregate_month(
            connect("500MB", 1), bad, "2025-01", ZONE_IDS, LOOKUP_IDS, tmp_path / "o.parquet", data_version="v"
        )
