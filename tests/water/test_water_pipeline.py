"""End to end on a tiny in-memory API: download, normalise, partition, validate, entities, report, idempotence."""

import json

import duckdb
import pytest
from water_helpers import FakeApi, Response, make_client, obs_row, point_member

from atlas.contracts.models import EntityCollection, QualityReport, SourceManifest
from atlas.contracts.observations import validate_observations
from atlas.domains.water import fetch, ingest

CONFIG = {
    "source_id": "uk-water-quality",
    "title": "test slice",
    "landing_url": "https://example.test/landing",
    "api_base": "https://api.test/water-quality",
    "license": "Open Government Licence v3.0",
    "attribution": "Environment Agency (test)",
    "manifest_notes": ["note"],
    "slice": {
        "id": "t",
        "description": "Test slice.",
        "filters": {"samplingPointType": "F6", "area": "X", "subArea": "H"},
        "year_from": 2019,
        "year_to": 2020,
    },
    "determinands": [
        {"code": "9924", "feature_name": "dissolved_oxygen", "label": "DO"},
        {"code": "0111", "feature_name": "ammoniacal_nitrogen", "label": "NH4"},
        {"code": "0180", "feature_name": "orthophosphate_reactive", "label": "PO4"},
    ],
    "candidate_determinands": [{"code": "0061", "label": "pH"}],
    "dataset_extent_wgs84": {"lon": [-6.236, 2.072], "lat": [49.943, 55.816]},
    "timezone": "Europe/London",
}

# (point, sample, local time, {determinand: result}); NE-2 has no coordinates in the listing, NE-9 is not listed at all
SAMPLES = [
    ("NE-1", 100, "2019-02-03T10:28:00", {"9924": "13.3", "0111": "<0.03", "0180": "0.05"}),
    ("NE-1", 101, "2019-03-31T01:30:00", {"0111": "0.1"}),  # inside the spring gap
    ("NE-1", 102, "2019-07-01T09:00:00", {"9924": "35.35", "0111": ">5", "0180": "NO FLOW"}),
    ("NE-2", 103, "2019-10-27T01:30:00", {"9924": "9.1", "0180": "<0.01"}),  # the repeated autumn hour
    ("NE-2", 104, "2019-12-31T23:30:00", {"9924": "8.0"}),  # last day of the year: dateTo is exclusive, so it needs H2
    ("NE-1", 106, "2019-06-30T23:30:00", {"9924": "7.0"}),  # last half hour of H1 (BST: 22:30 UTC)
    ("NE-9", 105, "2020-01-15T11:00:00", {"9924": "10.0", "0111": "0.2", "0180": "0.02"}),
]
XY = {"NE-1": (409570, 639530), "NE-2": (None, None), "NE-9": (407291, 643492)}
POINTS = [
    point_member("NE-1", 409570, 639530),
    point_member("NE-2", None, None),
    point_member("NE-3", 407291, 643492),
    point_member("NE-4", 500000, 3),  # placeholder, as in the real archive
]


def observations():
    return [
        obs_row(p, s, det, when, res, easting=XY[p][0], northing=XY[p][1])
        for p, s, when, results in SAMPLES
        for det, res in results.items()
    ]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG))
    monkeypatch.setattr(fetch, "CONFIG_PATH", config_path)
    monkeypatch.setattr(fetch, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(fetch, "CSV_PAGE_LIMIT", 4)  # several pages per year
    monkeypatch.setattr(fetch, "JSONLD_PAGE_LIMIT", 2)
    return tmp_path


def run(workspace, api=None, **kwargs):
    client, _ = make_client(api or FakeApi(POINTS, observations()))
    return ingest.run(
        datasets_root=str(workspace / "datasets"),
        out_dir=workspace / "out",
        client=client,
        log=lambda _: None,
        **kwargs,
    )


def test_end_to_end(workspace):
    api = FakeApi(POINTS, observations())
    details = run(workspace, api)
    out = workspace / "out"
    n_rows = sum(len(r) for *_, r in SAMPLES)  # 3 + 1 + 3 + 2 + 1 + 1 + 3

    # 1. counts reconcile: samples x determinands = rows, no duplicates, API totals = CSV rows = canonical rows
    assert n_rows == 14 and details["counters"]["canonical_rows"] == 14 == details["counters"]["raw_rows"]
    assert details["api_total_items_all_years"] == 14 and details["distinct_samples"] == 7
    for year in details["per_year"].values():
        assert (
            year["api_total_items"] == year["csv_rows"] == year["canonical_rows"] == year["distinct_sample_determinand"]
        )
    assert details["per_year"][2019]["pages"] == 4 and details["per_year"][2020]["pages"] == 1  # 4 rows per page, H1+H2

    # 2. contract-clean, hive-partitioned by UTC year/month; the Madrid-style 'no duplicate key' holds
    assert validate_observations(out / "observations" / "**" / "*.parquet") == []
    partitions = sorted(p.relative_to(out / "observations").as_posix() for p in (out / "observations").glob("*/*"))
    assert partitions == [
        "year=2019/month=10",
        "year=2019/month=12",
        "year=2019/month=2",
        "year=2019/month=3",
        "year=2019/month=6",
        "year=2019/month=7",
        "year=2020/month=1",
    ]
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    rows = con.execute(
        "SELECT sample_id, feature_name, value, censoring, missing_reason, "
        f"strftime(timestamp_utc, '%Y-%m-%dT%H:%M'), unit "
        f"FROM read_parquet('{out}/observations/**/*.parquet', hive_partitioning=true)"
    ).fetchall()
    by = {(r[0], r[1]): r for r in rows}
    assert by[("NE-1/100", "ammoniacal_nitrogen")][2:4] == (0.03, "left")
    assert by[("NE-1/102", "ammoniacal_nitrogen")][2:4] == (5.0, "right")
    assert by[("NE-1/102", "orthophosphate_reactive")][2:5] == (None, None, "invalid_observation")
    assert (
        by[("NE-1/100", "dissolved_oxygen")][5] == "2019-02-03T10:28"
        and by[("NE-1/102", "dissolved_oxygen")][5] == "2019-07-01T08:00"
    )
    assert by[("NE-1/101", "ammoniacal_nitrogen")][5] == "2019-03-31T01:30"  # spring gap: read with the GMT offset
    assert by[("NE-2/103", "dissolved_oxygen")][5] == "2019-10-27T00:30"  # autumn repeated hour: first occurrence
    assert (
        by[("NE-2/104", "dissolved_oxygen")][5] == "2019-12-31T23:30"
        and by[("NE-9/105", "dissolved_oxygen")][5] == "2020-01-15T11:00"
    )
    assert (
        details["counters"]["dst_nonexistent_rows"] == 1 and details["counters"]["dst_ambiguous_rows"] == 2
    )  # NE-2/103 has two determinands
    assert {r[6] for r in rows} == {"mg/l"}

    # 3. quality report
    report = QualityReport.model_validate_json((out / "quality_report.json").read_text())
    assert (
        report.raw_rows == 14
        and report.valid_rows == 13
        and report.duplicate_rows == 0
        and report.outliers_flagged == 1
    )
    assert report.invalid_codes["censoring:<"] == 2 and report.invalid_codes["missing_reason:invalid_observation"] == 1
    assert report.value_units == {
        "ammoniacal_nitrogen": "mg/l",
        "dissolved_oxygen": "mg/l",
        "orthophosphate_reactive": "mg/l",
    }
    assert report.missing_by_column["value"] == 1 and report.missing_by_column["validity_flag"] == 14
    assert (
        report.geographic_coverage["sampling_points_in_listing"] == 4
        and report.geographic_coverage["sampling_points_with_observations"] == 3
    )
    assert report.period_start.isoformat() == "2019-02-03" and report.period_end.isoformat() == "2020-01-15"
    assert any("Europe/London" in note for note in report.known_limitations)

    # 4. entities: observed points, official coordinates converted, null where the source has none
    entities = EntityCollection.model_validate_json((out / "entities.geojson").read_text())
    point = {f.id: f for f in entities.features}
    assert set(point) == {"NE-1", "NE-2", "NE-3", "NE-4", "NE-9"}
    assert (
        point["NE-4"].geometry is None
        and point["NE-4"].properties.attributes["coordinate_flag"] == "outside_dataset_extent"
    )
    assert list(report.geographic_coverage["points_with_placeholder_coordinates"]) == ["NE-4"]
    assert point["NE-2"].geometry is None and point["NE-2"].properties.attributes["n_observations"] == 3
    assert point["NE-3"].properties.attributes["n_observations"] == 0 and point["NE-3"].geometry is not None
    assert point["NE-9"].properties.attributes["in_listing"] is False and point["NE-9"].geometry is not None
    assert point["NE-1"].properties.geometry_support.value == "observed_point"
    assert point["NE-1"].properties.geometry_source == "https://api.test/water-quality/sampling-point/NE-1"
    lon, lat = point["NE-1"].geometry.coordinates
    assert 55.6 < lat < 55.7 and -1.9 < lon < -1.8
    assert details["entities"]["listing_without_coordinates"] == ["NE-2"] and details["entities"][
        "observed_not_in_listing"
    ] == ["NE-9"]

    # 4b. regression: dateTo is exclusive, so a year ends on 01-01 of the next one and never on 12-31
    obs_urls = [u for m, u in api.calls if m == "POST"]
    assert any("dateFrom=2019-07-01&dateTo=2020-01-01" in u for u in obs_urls)
    assert not any("-12-31" in u for u in obs_urls)

    # 5. the raw cache has a valid manifest whose checksums are quoted by the report
    manifest = SourceManifest.model_validate_json((workspace / "raw/uk-water-quality/source_manifest.json").read_text())
    assert {f"uk-water-quality/{f.path}": f.sha256 for f in manifest.files} == report.input_sha256
    assert manifest.period_start.isoformat() == "2019-01-01" and manifest.period_end.isoformat() == "2020-12-31"


def test_rerun_is_idempotent_no_requests_and_identical_output(workspace):
    api = FakeApi(POINTS, observations())
    run(workspace, api)
    out = workspace / "out"
    manifest = (workspace / "raw/uk-water-quality/source_manifest.json").read_bytes()
    first = {p.name: p.read_bytes() for p in out.glob("*.json*")}
    n_calls = len(api.calls)

    run(workspace, api)  # normal run again: the cache satisfies everything
    assert len(api.calls) == n_calls
    assert (workspace / "raw/uk-water-quality/source_manifest.json").read_bytes() == manifest
    assert {p.name: p.read_bytes() for p in out.glob("*.json*") if p.name != "ingest_details.json"} == {
        k: v for k, v in first.items() if k != "ingest_details.json"
    }
    ingest.run(
        datasets_root=str(workspace / "datasets"), out_dir=workspace / "out", skip_download=True, log=lambda _: None
    )
    assert len(api.calls) == n_calls


def test_skip_download_refuses_to_touch_the_network_when_the_cache_is_empty(workspace):
    with pytest.raises(SystemExit, match="cache is incomplete"):
        ingest.run(
            datasets_root=str(workspace / "datasets"), out_dir=workspace / "out", skip_download=True, log=lambda _: None
        )


def test_tampered_raw_file_is_caught_before_anything_is_written(workspace):
    run(workspace)
    page = next((workspace / "raw/uk-water-quality/observations").rglob("page-0000.csv"))
    page.chmod(0o644)
    page.write_bytes(page.read_bytes() + b"x")
    with pytest.raises(SystemExit, match="do not match|cache is incomplete"):
        ingest.run(
            datasets_root=str(workspace / "datasets"),
            out_dir=workspace / "out2",
            skip_download=True,
            log=lambda _: None,
        )


def test_api_that_always_fails_aborts_the_run(workspace):
    client, _ = make_client(lambda *args: Response(503, {}, b"down"), max_attempts=2)
    with pytest.raises(Exception, match="after 2 attempts"):
        ingest.run(
            datasets_root=str(workspace / "datasets"), out_dir=workspace / "out", client=client, log=lambda _: None
        )
