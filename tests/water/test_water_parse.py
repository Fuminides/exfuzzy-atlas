"""Censoring, missing values, DST conversion, canonical rows and entities (hand-written and recorded API samples)."""

import json
from datetime import datetime, timezone

import pandas as pd
import pytest
from water_helpers import FIXTURES, obs_row

from atlas.contracts.models import EntityFeature, MissingReason
from atlas.contracts.observations import validate_observations
from atlas.domains.water.parse import (
    OUTPUT_SCHEMA,
    Stats,
    build_entities,
    local_to_utc,
    observations_frame,
    parse_result,
    read_csv_pages,
    read_sampling_points,
    to_arrow,
    unit_symbols,
)

FEATURES = {"9924": "dissolved_oxygen", "0111": "ammoniacal_nitrogen", "0180": "orthophosphate_reactive"}
UNITS = {"MILLIGRAM PER LITRE": "mg/l"}


# --- censoring ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "censoring"),
    [
        ("<0.03", 0.03, "left"),
        ("< 0.03", 0.03, "left"),
        (">20", 20.0, "right"),
        ("<1e-3", 0.001, "left"),
        ("0.048", 0.048, None),
        ("13", 13.0, None),
        ("-0.2", -0.2, None),  # instrument noise below zero is a measurement, not censoring
        ("0", 0.0, None),  # a real zero stays a number: 0 is never "missing"
    ],
)
def test_parse_result_numbers_and_detection_limits(text, value, censoring):
    parsed = parse_result(text)
    assert (parsed.value, parsed.censoring, parsed.missing_reason) == (value, censoring, None)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", MissingReason.NO_OBSERVATION.value),
        ("   ", MissingReason.NO_OBSERVATION.value),
        (None, MissingReason.NO_OBSERVATION.value),
        ("NO FLOW", MissingReason.INVALID_OBSERVATION.value),
        ("<", MissingReason.INVALID_OBSERVATION.value),
        ("<0", MissingReason.INVALID_OBSERVATION.value),  # a non-positive limit means nothing
        ("<abc", MissingReason.INVALID_OBSERVATION.value),
        ("nan", MissingReason.INVALID_OBSERVATION.value),
        ("inf", MissingReason.INVALID_OBSERVATION.value),
        ("1,5", MissingReason.INVALID_OBSERVATION.value),
        ("<<1", MissingReason.INVALID_OBSERVATION.value),
    ],
)
def test_parse_result_missing_and_invalid_have_a_reason_and_no_value(text, reason):
    parsed = parse_result(text)
    assert parsed.value is None and parsed.censoring is None and parsed.missing_reason == reason


# --- DST ------------------------------------------------------------------------------------------------------


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("local", "expected_utc", "kind"),
    [
        ("2015-02-03T10:28:00", "2015-02-03T10:28:00", None),  # winter: GMT = UTC
        ("2015-07-01T10:28:00", "2015-07-01T09:28:00", None),  # summer: BST = UTC+1
        ("2019-03-31T00:59:00", "2019-03-31T00:59:00", None),  # last minute before the gap
        ("2019-03-31T01:30:00", "2019-03-31T01:30:00", "nonexistent"),  # inside the spring gap: pre-transition offset
        ("2019-03-31T02:00:00", "2019-03-31T01:00:00", None),  # first valid BST minute
        ("2019-10-27T00:59:00", "2019-10-26T23:59:00", None),  # BST, before the repeated hour
        ("2019-10-27T01:00:00", "2019-10-27T00:00:00", "ambiguous"),  # repeated hour: first occurrence (BST)
        ("2019-10-27T01:59:00", "2019-10-27T00:59:00", "ambiguous"),
        ("2019-10-27T02:00:00", "2019-10-27T02:00:00", None),  # GMT again, unambiguous
    ],
)
def test_local_to_utc_documented_policy(local, expected_utc, kind):
    result, flagged = local_to_utc(datetime.fromisoformat(local))
    assert result == utc(expected_utc) and result.utcoffset().total_seconds() == 0 and flagged == kind


def test_dst_rows_are_counted_and_listed():
    raw = pd.DataFrame(
        [
            obs_row("P1", 1, "9924", "2019-03-31T01:30:00", "9"),
            obs_row("P1", 2, "9924", "2019-10-27T01:30:00", "9"),
            obs_row("P1", 3, "9924", "2019-07-01T09:00:00", "9"),
        ]
    )
    stats = Stats()
    frame = observations_frame(raw, features=FEATURES, unit_symbols=UNITS, data_version="v", stats=stats)
    assert stats.counters["dst_nonexistent_rows"] == 1 and stats.counters["dst_ambiguous_rows"] == 1
    assert stats.dst_examples == {"ambiguous": ["2019-10-27T01:30:00"], "nonexistent": ["2019-03-31T01:30:00"]}
    got = dict(zip(frame["source_timestamp_local"], frame["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M"), strict=True))
    assert got == {
        "2019-03-31T01:30:00": "2019-03-31T01:30",
        "2019-10-27T01:30:00": "2019-10-27T00:30",
        "2019-07-01T09:00:00": "2019-07-01T08:00",
    }
    assert set(frame["timezone"]) == {"Europe/London"}


# --- canonical rows -------------------------------------------------------------------------------------------


def frame_of(rows, stats=None, **kwargs):
    stats = stats or Stats()
    raw = pd.DataFrame(rows)
    return observations_frame(
        raw, features=FEATURES, unit_symbols=UNITS, data_version="v1", stats=stats, **kwargs
    ), stats


def test_rows_carry_contract_semantics_and_identifiers():
    rows = [
        obs_row("NE-1", 7, "9924", "2019-02-03T10:28:00", "13.3"),
        obs_row("NE-1", 7, "0111", "2019-02-03T10:28:00", "<0.03"),
        obs_row("NE-1", 7, "0180", "2019-02-03T10:28:00", ">5"),
        obs_row("NE-1", 8, "9924", "2019-03-03T10:28:00", "NO FLOW"),
        obs_row("NE-1", 9, "9924", "2019-04-03T10:28:00", ""),
    ]
    frame, stats = frame_of(rows)
    by = {(r.sample_id, r.feature_name): r for r in frame.itertuples()}
    do, nh4, po4 = (
        by[("NE-1/7", "dissolved_oxygen")],
        by[("NE-1/7", "ammoniacal_nitrogen")],
        by[("NE-1/7", "orthophosphate_reactive")],
    )
    # pandas 2 keeps None, pandas 3 turns missing strings into NaN: compare with pd.isna
    assert do.value == 13.3 and pd.isna(do.censoring) and pd.isna(do.missing_reason)
    assert (nh4.value, nh4.censoring, nh4.result_raw) == (0.03, "left", "<0.03") and pd.isna(nh4.missing_reason)
    assert (po4.value, po4.censoring) == (5.0, "right")
    invalid = by[("NE-1/8", "dissolved_oxygen")]
    empty = by[("NE-1/9", "dissolved_oxygen")]
    assert (
        pd.isna(invalid.value) and invalid.missing_reason == "invalid_observation" and invalid.result_raw == "NO FLOW"
    )
    assert pd.isna(empty.value) and empty.missing_reason == "no_observation"
    assert (do.domain, do.source_id, do.entity_id, do.unit, do.unit_label) == (
        "water",
        "uk-water-quality",
        "NE-1",
        "mg/l",
        "MILLIGRAM PER LITRE",
    )
    assert do.observation_id == "NE-1/sample/7/observation/9924" and do.determinand_code == "9924"
    assert pd.isna(do.validity_flag)  # the API has no validity code
    assert stats.counters["censored_left"] == 1 and stats.counters["censored_right"] == 1
    assert stats.counters["valid_rows"] == 3 and stats.counters["canonical_rows"] == 5 == stats.counters["raw_rows"]
    assert stats.counters["missing_invalid_observation"] == 1 and stats.counters["missing_no_observation"] == 1
    assert list(frame.columns) == [f.name for f in OUTPUT_SCHEMA]


def test_frame_passes_the_observation_contract(tmp_path):
    rows = [
        obs_row("NE-1", 7, "9924", "2019-02-03T10:28:00", "13.3"),
        obs_row("NE-1", 7, "0111", "2019-02-03T10:28:00", "<0.03"),
        obs_row("NE-2", 8, "9924", "2019-03-03T10:28:00", "NO FLOW"),
    ]
    frame, _ = frame_of(rows)
    assert validate_observations(to_arrow(frame)) == []


def test_unit_label_missing_from_the_codelist_is_kept_verbatim_and_counted():
    frame, stats = frame_of([obs_row("NE-1", 1, "9924", "2019-02-03T10:28:00", "9", unit="STRANGE UNIT")])
    assert frame["unit"].iat[0] == "STRANGE UNIT" and stats.counters["unit_not_in_codelist"] == 1


def test_duplicates_on_the_contract_key_keep_the_smallest_observation_id():
    rows = [
        obs_row("NE-1", 20, "9924", "2019-02-03T10:28:00", "8"),
        obs_row("NE-1", 10, "9924", "2019-02-03T10:28:00", "9"),  # same point, instant and determinand, other sample
        obs_row("NE-1", 11, "0111", "2019-02-03T10:28:00", "1"),
    ]
    frame, stats = frame_of(rows)
    assert len(frame) == 2 and stats.counters["duplicate_key_rows_dropped"] == 1
    kept = frame[frame["feature_name"] == "dissolved_oxygen"].iloc[0]
    assert kept["sample_id"] == "NE-1/10" and kept["value"] == 9.0
    assert stats.dropped_duplicates == ["NE-1/sample/20/observation/9924"]
    assert validate_observations(to_arrow(frame)) == []


def test_outliers_are_counted_not_altered_and_other_materials_are_counted():
    rows = [
        obs_row("NE-1", 1, "9924", "2019-02-03T10:28:00", "35.35"),
        obs_row("NE-1", 2, "9924", "2019-03-03T10:28:00", "9", material="FINAL SEWAGE EFFLUENT"),
    ]
    frame, stats = frame_of(rows, outlier_rules={"dissolved_oxygen": 20.0})
    assert stats.counters["outliers_flagged"] == 1 and stats.counters["non_river_sample_material"] == 1
    assert sorted(frame["value"]) == [9.0, 35.35]


def test_guards_against_schema_drift():
    with pytest.raises(ValueError, match="not in the configuration"):
        frame_of([obs_row("NE-1", 1, "0061", "2019-02-03T10:28:00", "7")])
    bad = obs_row("NE-1", 1, "9924", "2019-02-03T10:28:00", "7")
    bad["id"] = bad["id"].replace("NE-1", "NE-2")  # id says another point than the row
    with pytest.raises(ValueError, match="disagrees"):
        frame_of([bad])
    with pytest.raises(ValueError, match="header"):
        read_csv_pages([b"id,result\nx,1\n"])


def test_recorded_api_rows_are_parsed():
    """Five real rows of POST /data/observation (2015, Fenham Burn and Till): header, ids, '<' results."""
    raw = read_csv_pages([(FIXTURES / "observations_recorded.csv").read_bytes()])
    unit_pages = [(FIXTURES / "unit_recorded.jsonld").read_bytes()]
    stats = Stats()
    frame = observations_frame(
        raw, features=FEATURES, unit_symbols=unit_symbols(unit_pages), data_version="v", stats=stats
    )
    assert len(frame) == 5 and set(frame["unit"]) == {"mg/l"} and set(frame["unit_label"]) == {"MILLIGRAM PER LITRE"}
    assert sorted(frame["censoring"].dropna()) == ["left", "left"]
    assert sorted(frame.loc[frame["censoring"] == "left", "result_raw"]) == ["<0.01", "<0.03"]
    first = frame[(frame["sample_id"] == "NE-41000003/1517549") & (frame["feature_name"] == "dissolved_oxygen")].iloc[0]
    assert first["value"] == 13.3 and first["timestamp_utc"] == pd.Timestamp("2015-02-03T10:28:00Z")
    assert validate_observations(to_arrow(frame)) == []


# --- entities -------------------------------------------------------------------------------------------------


def test_recorded_sampling_points_become_observed_point_entities():
    points = read_sampling_points([(FIXTURES / "sampling_point_recorded.jsonld").read_bytes()])
    assert set(points) == {"NE-41000002", "NE-41000003"} and points["NE-41000002"]["bng"] == (407291.0, 643492.0)
    collection, report = build_entities(points, {}, {}, data_version="v", api_base="https://api.test/wq")
    feature = next(f for f in collection.features if f.id == "NE-41000002")
    assert feature.properties.geometry_support.value == "observed_point"
    assert feature.properties.geometry_source == "https://api.test/wq/sampling-point/NE-41000002"
    assert feature.properties.timezone == "Europe/London" and collection.domain.value == "water"
    assert (
        feature.properties.attributes["sub_area_code"] == "X-H"
        and feature.properties.attributes["bng_easting"] == 407291.0
    )
    assert (
        abs(feature.geometry.coordinates[0] - -1.8856) < 3e-4 and abs(feature.geometry.coordinates[1] - 55.6849) < 3e-4
    )
    assert report["listing_without_coordinates"] == []


def test_missing_coordinates_give_null_geometry_and_are_never_invented():
    from water_helpers import point_member

    page = json.dumps({"member": [point_member("A", 409570, 639530), point_member("B", None, None)]}).encode()
    points = read_sampling_points([page])
    collection, report = build_entities(points, {}, {}, data_version="v", api_base="https://api.test")
    by = {f.id: f for f in collection.features}
    assert by["B"].geometry is None and by["A"].geometry is not None
    assert report["listing_without_coordinates"] == ["B"]
    EntityFeature.model_validate(by["B"].model_dump())  # still a valid entity


def test_point_seen_only_in_observations_takes_the_observation_coordinates_and_mismatches_are_reported():
    from water_helpers import point_member

    points = read_sampling_points([json.dumps({"member": [point_member("A", 409570, 639530)]}).encode()])
    observed = {
        "A": {"n_observations": 3, "n_samples": 1, "first_utc": "x", "last_utc": "y"},
        "Z": {"n_observations": 1},
    }
    xy = {"A": (409570.0, 639535.0), "Z": (407291.0, 643492.0)}
    collection, report = build_entities(points, observed, xy, data_version="v", api_base="https://api.test")
    by = {f.id: f for f in collection.features}
    assert (
        report["observed_not_in_listing"] == ["Z"] and by["Z"].geometry is not None and by["Z"].properties.name is None
    )
    assert by["Z"].properties.attributes["in_listing"] is False
    assert list(report["coordinate_mismatch_listing_vs_observations_m"]) == ["A"]
    assert by["A"].properties.attributes["n_observations"] == 3


def test_placeholder_coordinates_outside_the_dataset_extent_give_null_geometry_but_keep_the_raw_values():
    from water_helpers import point_member

    members = [
        point_member("REAL", 409570, 639530),
        point_member("FAKE", 500000, 3),
    ]  # the real archive has such a point
    points = read_sampling_points([json.dumps({"member": members}).encode()])
    extent = {"lon": [-6.236, 2.072], "lat": [49.943, 55.816]}
    collection, report = build_entities(points, {}, {}, data_version="v", api_base="https://api.test", extent=extent)
    by = {f.id: f for f in collection.features}
    assert by["REAL"].geometry is not None and by["REAL"].properties.attributes["coordinate_flag"] is None
    assert (
        by["FAKE"].geometry is None and by["FAKE"].properties.attributes["coordinate_flag"] == "outside_dataset_extent"
    )
    assert by["FAKE"].properties.attributes["bng_easting"] == 500000.0
    assert list(report["coordinates_outside_extent"]) == ["FAKE"] and report["listing_without_coordinates"] == []
