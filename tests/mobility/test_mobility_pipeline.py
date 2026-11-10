"""End to end on tiny inputs: download (fake), zones, aggregate, validate, reports (needs the geometry stack)."""

import io
import json
import zipfile
from datetime import date

import pytest

pytest.importorskip("shapely", minversion="2.2")
pytest.importorskip("pyproj")
pytest.importorskip("shapefile")

import duckdb  # noqa: E402
from mobility_helpers import LOOKUP_CSV, trip, write_trips, zones_zip  # noqa: E402

from atlas.contracts.models import EntityCollection, QualityReport, SourceManifest  # noqa: E402
from atlas.contracts.observations import validate_observations  # noqa: E402
from atlas.domains.mobility import ingest  # noqa: E402

URL = "https://example.test"


MONTHS = ["2025-02", "2025-03"]


def make_config(months):
    files = [
        {"path": f"yellow_tripdata_{m}.parquet", "url": f"{URL}/{m}.parquet", "role": "data", "month": m}
        for m in months
    ] + [
        {"path": "taxi_zone_lookup.csv", "url": f"{URL}/lookup.csv", "role": "lookup"},
        {"path": "taxi_zones.zip", "url": f"{URL}/zones.zip", "role": "geometry"},
    ]
    return {
        "data_version": "test-v1",
        "max_trip_hours": 6,
        "tlc": {
            "source_id": "nyc-tlc",
            "title": "t",
            "landing_url": URL,
            "license": "test licence",
            "attribution": "test",
            "geometry_source": f"{URL}/zones.zip",
            "files": files,
        },
    }


@pytest.fixture()
def served(tmp_path):
    """URL -> bytes for two months (Feb, Mar 2025) with a spring-forward day, filtered trips and special zones."""
    feb = [trip("2025-02-03 09:00", zone=1), trip("2025-02-03 09:30", zone=2), trip("2025-03-01 00:00", zone=1)]
    mar = [
        trip("2025-03-09 01:30", zone=1),
        trip("2025-03-09 02:30", zone=1),  # nonexistent local hour
        trip("2025-03-09 03:30", zone=1),
        trip("2025-03-10 08:00", zone=3),
        trip("2025-03-10 08:00", zone=264),
        trip("2025-03-10 08:00", minutes=0, zone=3),
        trip("2025-02-28 23:00", zone=3),  # belongs to the previous month's file
    ]
    zones = zones_zip(tmp_path / "z.zip")
    served = {
        f"{URL}/2025-02.parquet": write_trips(tmp_path / "feb.parquet", feb).read_bytes(),
        f"{URL}/2025-03.parquet": write_trips(tmp_path / "mar.parquet", mar).read_bytes(),
        f"{URL}/lookup.csv": LOOKUP_CSV.encode(),
        f"{URL}/zones.zip": zones.read_bytes(),
    }
    assert zipfile.ZipFile(io.BytesIO(served[f"{URL}/zones.zip"])).testzip() is None
    return served


def test_pipeline_end_to_end(tmp_path, monkeypatch, served):
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path / "raw")
    out, doc = tmp_path / "processed", tmp_path / "card.md"
    details = ingest.run(
        MONTHS, out_dir=out, doc_path=doc, fetch=lambda url: served[url], config=make_config(MONTHS)
    )
    c = details["counters"]
    assert c["raw_rows"] == 10
    assert c["filtered"]["pickup_outside_file_month"] == 2 and c["filtered"]["pickup_nonexistent_local_hour"] == 1
    assert c["filtered"]["pickup_zone_unknown_or_outside"] == 1 and c["filtered"]["zero_duration"] == 1
    assert c["raw_rows"] - c["filtered_total"] == c["valid_rows"] == 5
    assert details["summary"]["total_pickups"] == 5

    # raw layer: immutable files with a valid manifest
    manifest = SourceManifest.model_validate_json((tmp_path / "raw" / "nyc-tlc" / "source_manifest.json").read_text())
    assert {f.path for f in manifest.files} >= {"taxi_zones.zip", "yellow_tripdata_2025-03.parquet"}

    # processed layer: contract-valid, dense in the covered period (3 polygons x (28 + 31) days, one 23-hour day)
    assert validate_observations(out / "observations" / "**" / "*.parquet") == []
    hours = 28 * 24 + 31 * 24 - 1
    n_rows, n_zero, n_null = duckdb.connect().execute(
        "SELECT count(*), count(*) FILTER (WHERE value = 0), count(*) FILTER (WHERE value IS NULL) "
        f"FROM read_parquet('{out}/observations/**/*.parquet')"
    ).fetchall()[0]
    # 5 counted trips fall in 5 distinct zone-hours, every other zone-hour is a genuine zero
    assert n_rows == 3 * hours and n_null == 0 and n_zero == n_rows - 5

    report = QualityReport.model_validate_json((out / "quality_report.json").read_text())
    assert report.raw_rows == 10 and report.valid_rows == 5 and report.period_start == date(2025, 2, 1)
    assert report.period_end == date(2025, 3, 31) and report.input_sha256
    assert report.invalid_codes["filtered:zero_duration"] == 1

    for name in ("taxi_zones.geojson", "taxi_zones_simplified.geojson"):
        collection = EntityCollection.model_validate(json.loads((out / name).read_text(encoding="utf-8")))
        assert {f.id for f in collection.features if f.geometry is None} == {"4", "5", "264", "265"}
    assert "Tarjeta de datos" in doc.read_text(encoding="utf-8")

    # idempotent: a second run reproduces the same counts and does not need the network
    again = ingest.run(MONTHS, skip_download=True, out_dir=out, doc_path=None, config=make_config(MONTHS))
    assert again["counters"] == details["counters"]


def test_parse_months():
    assert ingest.parse_months("2025-01..2025-03") == ["2025-01", "2025-02", "2025-03"]
    assert ingest.parse_months("2024-12..2025-01,2025-03") == ["2024-12", "2025-01", "2025-03"]
    assert ingest.parse_months("2025-05") == ["2025-05"]
