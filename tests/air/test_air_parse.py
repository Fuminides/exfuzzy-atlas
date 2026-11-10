"""Parsing and conversion of the official Madrid hourly format (tiny hand-written samples, no network)."""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from atlas.contracts.observations import validate_observations
from atlas.domains.air.parse import SchemaError, Stats, read_csv_wide, read_txt_wide, wide_to_long

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def csv_wide():
    return read_csv_wide((FIXTURES / "sample_hourly.csv").read_bytes())


@pytest.fixture(scope="module")
def txt_wide():
    return read_txt_wide((FIXTURES / "sample_hourly.txt").read_bytes())


def convert(*frames, seen=None):
    return wide_to_long(pd.concat(frames, ignore_index=True), data_version="test-v1", seen=seen)


def rows_of(table: pa.Table, entity: str, feature: str, day: str) -> pd.DataFrame:
    df = table.to_pandas()
    mask = (df.entity_id == entity) & (df.feature_name == feature) & df.source_timestamp_local.str.startswith(day)
    return df[mask].sort_values("timestamp_utc").reset_index(drop=True)


def test_csv_and_txt_parse_to_the_same_wide_layout(csv_wide, txt_wide):
    assert len(csv_wide) == 5 and len(txt_wide) == 2
    assert csv_wide.loc[0, ["province", "municipality", "station", "magnitude", "technique"]].tolist() == [
        "28",
        "079",
        "4",
        "8",
        "8",
    ]
    assert txt_wide.loc[1, ["station", "magnitude", "technique"]].tolist() == ["056", "09", "47"]
    assert set(csv_wide.columns) == set(txt_wide.columns)
    assert csv_wide.loc[2, "H03"] == "" and txt_wide.loc[0, "H03"] == ""  # empty slot survives as empty text


def test_unexpected_csv_header_is_rejected():
    with pytest.raises(SchemaError):
        read_csv_wide("PROVINCIA;MUNICIPIO\n28;079\n")


def test_hour_is_converted_as_hour_ending_to_utc_start(csv_wide):
    table, _ = convert(csv_wide)
    winter = rows_of(table, "28079008", "no2", "2019-01-15")
    # H01 = 00:00-01:00 local = 23:00Z of the previous day (CET, UTC+1); H24 starts at 23:00 local = 22:00Z.
    assert winter.timestamp_utc.iloc[0] == pd.Timestamp("2019-01-14 23:00", tz="UTC")
    assert winter.timestamp_utc.iloc[-1] == pd.Timestamp("2019-01-15 22:00", tz="UTC")
    assert winter.source_timestamp_local.iloc[0] == "2019-01-15 H01"
    assert (winter.timezone == "Europe/Madrid").all() and (winter.unit == "ug/m3").all()
    assert (winter.source_id == "madrid-air").all() and (winter.data_version == "test-v1").all()


def test_spring_forward_drops_the_nonexistent_hour(csv_wide):
    table, stats = convert(csv_wide)
    day = rows_of(table, "28079004", "no2", "2019-03-31")
    assert len(day) == 23 and "2019-03-31 H03" not in set(day.source_timestamp_local)
    # Consecutive UTC hours: no gap and no overlap even though local wall time jumps from 02:00 to 03:00.
    assert day.timestamp_utc.diff().dropna().eq(pd.Timedelta(hours=1)).all()
    assert day.timestamp_utc.iloc[0] == pd.Timestamp("2019-03-30 23:00", tz="UTC")
    assert day.set_index("source_timestamp_local").loc["2019-03-31 H04", "timestamp_utc"] == pd.Timestamp(
        "2019-03-31 01:00", tz="UTC"
    )
    assert stats.counters["slots_dst_nonexistent"] == 1
    assert stats.counters["slots_dst_nonexistent_not_flagged_invalid"] == 0
    assert stats.dst_days["2019-03-31"]["invalid_per_slot"][2] == 1  # the evidence table records H03


def test_fall_back_assigns_the_first_occurrence_and_leaves_the_repeat_empty(csv_wide):
    table, _ = convert(csv_wide)
    day = rows_of(table, "28079004", "no2", "2019-10-27")
    assert len(day) == 24 and day.timestamp_utc.is_unique
    by_slot = day.set_index("source_timestamp_local").timestamp_utc
    assert by_slot["2019-10-27 H03"] == pd.Timestamp("2019-10-27 00:00", tz="UTC")  # 02:00 CEST, first occurrence
    assert by_slot["2019-10-27 H04"] == pd.Timestamp("2019-10-27 02:00", tz="UTC")  # 03:00 CET
    assert pd.Timestamp("2019-10-27 01:00", tz="UTC") not in set(day.timestamp_utc)  # repeated hour: no slot


def test_validity_flags_become_null_values_with_a_reason(csv_wide):
    table, stats = convert(csv_wide)
    day = rows_of(table, "28079008", "no2", "2019-01-15").set_index("source_timestamp_local")
    assert day.loc["2019-01-15 H01", "value"] == 12 and pd.isna(day.loc["2019-01-15 H01", "missing_reason"])
    # N: the file holds a placeholder 0 that must not leak into the value
    assert pd.isna(day.loc["2019-01-15 H02", "value"])
    assert day.loc["2019-01-15 H02", ["validity_flag", "missing_reason"]].tolist() == ["N", "invalid_observation"]
    # empty text -> no_observation, flag kept as published
    assert (
        pd.isna(day.loc["2019-01-15 H03", "value"]) and day.loc["2019-01-15 H03", "missing_reason"] == "no_observation"
    )
    # a valid zero stays zero and has no reason
    assert day.loc["2019-01-15 H04", "value"] == 0 and pd.isna(day.loc["2019-01-15 H04", "missing_reason"])
    # undocumented code M is not valid either
    assert day.loc["2019-01-15 H05", ["validity_flag", "missing_reason"]].tolist() == ["M", "invalid_observation"]
    assert day["value"].notna().sum() == 21 and stats.by_flag["N"] >= 1 and stats.by_flag["M"] == 1


def test_impossible_dates_and_unknown_magnitudes_are_counted_not_written(csv_wide):
    table, stats = convert(csv_wide)
    assert stats.counters["rows_impossible_date"] == 1 and stats.counters["slots_impossible_date"] == 24
    assert not table.to_pandas().source_timestamp_local.str.startswith("2019-02-30").any()
    assert stats.unknown_magnitude_slots == {"83": 24}
    assert set(table.column("feature_name").to_pylist()) == {"no2"}


def test_csv_has_precedence_over_txt_and_txt_only_rows_are_kept(csv_wide, txt_wide):
    table, stats = convert(csv_wide, txt_wide)
    assert stats.counters["overlap_slots_cross_format"] == 24 and stats.counters["duplicate_slots_same_format"] == 0
    day = rows_of(table, "28079008", "no2", "2019-01-15")
    assert day.value.iloc[0] == 12  # CSV says 12, TXT says 13
    pm = rows_of(table, "28079056", "pm25", "2019-01-15")
    assert len(pm) == 24 and pm.value.tolist() == list(range(1, 25)) and (pm.unit == "ug/m3").all()
    assert stats.txt_only_slots == {"2019/pm25": 24}


def test_same_format_duplicates_are_reported_and_output_has_no_duplicate_keys(csv_wide):
    table, stats = convert(csv_wide, csv_wide)
    assert stats.counters["duplicate_slots_same_format"] == 3 * 24  # the three convertible rows, repeated
    assert validate_observations(table) == []  # includes the uniqueness check on the contract key
    df = table.to_pandas()
    assert not df.duplicated(["entity_id", "timestamp_utc", "feature_name"]).any()


def test_canonical_output_passes_the_contract_validator(csv_wide, txt_wide):
    table, _ = convert(csv_wide, txt_wide)
    assert validate_observations(table) == []
    df = table.to_pandas()
    assert ((df.value.isna()) == df.missing_reason.notna()).all()  # null value <=> reason, 0 is never 'missing'
    assert str(table.schema.field("timestamp_utc").type) == "timestamp[us, tz=UTC]"


def test_stats_merge_adds_counters():
    a, b = Stats(), Stats()
    a.counters["x"] += 1
    b.counters["x"] += 2
    b.dst_days["2019-03-31"] = {"rows": 2, "invalid_per_slot": [0, 0, 2] + [0] * 21}
    a.merge(b)
    assert a.counters["x"] == 3 and a.dst_days["2019-03-31"]["rows"] == 2
