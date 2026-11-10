"""End-to-end run on the tiny fixtures: download (fake), convert, partition, validate, stations, report."""

import io
import json
import zipfile
from pathlib import Path

import duckdb
import pytest

from atlas.contracts.models import EntityCollection, QualityReport, SourceManifest
from atlas.contracts.observations import validate_observations
from atlas.domains.air import ingest

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.test"

GEOPORTAL = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.7122567, 40.4238823]},
            "properties": {
                "CODIGO_TX": "28079004",
                "CODIGO_CORTO": 4,
                "ESTACION": "Pza. de España",
                "DIRECCION": "Plaza de España",
                "COD_TIPO": "UT",
                "NOM_TIPO": "Urbana tráfico",
                "NO2": "X",
                "SO2": None,
                "CO": None,
                "PM10": None,
                "PM2_5": None,
                "O3": None,
                "BTX": None,
                "COORDENADA_X_ETRS89": 439579.3291,
                "COORDENADA_Y_ETRS89": 4475049.263,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.6823158, 40.4215533]},
            "properties": {
                "CODIGO_TX": "28079008",
                "CODIGO_CORTO": 8,
                "ESTACION": "Escuelas Aguirre",
                "DIRECCION": "C/ Alcalá",
                "COD_TIPO": "UT",
                "NOM_TIPO": "Urbana tráfico",
                "NO2": "X",
                "SO2": None,
                "CO": None,
                "PM10": None,
                "PM2_5": None,
                "O3": None,
                "BTX": None,
                "COORDENADA_X_ETRS89": 442117.2366,
                "COORDENADA_Y_ETRS89": 4474770.696,
            },
        },
        {  # official station that has no rows in the sample data
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.7746101, 40.5180701]},
            "properties": {
                "CODIGO_TX": "28079058",
                "CODIGO_CORTO": 58,
                "ESTACION": "El Pardo",
                "DIRECCION": "Avda. La Guardia",
                "COD_TIPO": "S",
                "NOM_TIPO": "Suburbana",
                "NO2": "X",
                "SO2": None,
                "CO": None,
                "PM10": None,
                "PM2_5": None,
                "O3": "X",
                "BTX": None,
                "COORDENADA_X_ETRS89": 434381.6,
                "COORDENADA_Y_ETRS89": 4485548.7,
            },
        },
    ],
}
CROSSCHECK = (
    "CODIGO;CODIGO_CORTO;ESTACION;ALTITUD;Fecha alta;LONGITUD;LATITUD\n"
    "28079004;4;Plaza de España;637;01/12/1998;-3.7122567;40.4238823\n"
    "28079008;8;Escuelas Aguirre;672;01/12/1998;-3.6700000;40.4215533\n"  # ~1 km away from the Geoportal point
    "28079058;58;El Pardo;611;01/12/2009;-3.7746101;40.5180701\n"
)


def make_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Anio19/", "")
        archive.writestr("Anio19/ene_mo19.csv", (FIXTURES / "sample_hourly.csv").read_bytes())
        archive.writestr("Anio19/ene_mo19.txt", (FIXTURES / "sample_hourly.txt").read_bytes())
        archive.writestr("Anio19/ene_mo19.xml", "<Datos/>")
    return buffer.getvalue()


PAYLOADS = {
    f"{URL}/air-2019.zip": make_zip(),
    f"{URL}/pdf": b"%PDF-fake",
    f"{URL}/geo": json.dumps(GEOPORTAL).encode(),
    f"{URL}/meta": b"{}",
    f"{URL}/cross": CROSSCHECK.encode(),
}
CONFIG = {
    "data_version": "test-v1",
    "air": {
        "source_id": "madrid-air",
        "title": "t",
        "landing_url": URL,
        "license": "CC BY 4.0",
        "attribution": "AM",
        "period_start": "2019-01-01",
        "files": [
            {"path": "interprete.pdf", "url": f"{URL}/pdf", "role": "interpreter"},
            {"path": "air-2019.zip", "url": f"{URL}/air-2019.zip", "role": "data", "years": [2019]},
        ],
    },
    "stations": {
        "source_id": "madrid-air-stations",
        "title": "s",
        "landing_url": URL,
        "geometry_source": f"{URL}/layer/5",
        "license": "CC BY 4.0",
        "attribution": "AM",
        "files": [
            {"path": "geoportal_layer5_estaciones.geojson", "url": f"{URL}/geo", "role": "geometry"},
            {"path": "geoportal_layer5_metadata.json", "url": f"{URL}/meta", "role": "metadata"},
            {"path": "estaciones-control-aire.csv", "url": f"{URL}/cross", "role": "crosscheck"},
        ],
    },
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG))
    monkeypatch.setattr(ingest, "CONFIG_PATH", config_path)
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path / "raw")
    return tmp_path


def fake_fetch(url):
    return PAYLOADS[url]


def run(workspace, **kwargs):
    return ingest.run([2019], out_dir=workspace / "out", doc_path=workspace / "quality.md", fetch=fake_fetch, **kwargs)


def test_end_to_end_on_the_sample(workspace):
    details = run(workspace)
    out = workspace / "out"

    # 1. canonical Parquet: hive-partitioned by UTC year/month, contract-clean
    assert validate_observations(out / "observations" / "**" / "*.parquet") == []
    partitions = sorted(p.relative_to(out / "observations").as_posix() for p in (out / "observations").glob("*/*"))
    assert partitions == ["year=2019/month=1", "year=2019/month=10", "year=2019/month=3"]
    con = duckdb.connect()
    n, valid = con.execute(
        f"SELECT count(*), count(value) FROM read_parquet('{out}/observations/**/*.parquet', hive_partitioning=true)"
    ).fetchone()
    # 23 (spring) + 24 (fall) + 24 (mixed day) NO2 rows + 24 TXT-only PM2.5 rows; Feb 30 and magnitude 83 excluded
    assert (n, valid) == (23 + 24 + 24 + 24, 23 + 24 + 21 + 24)
    assert details["counters"]["canonical_rows"] == n and details["counters"]["valid_rows"] == valid

    # 2. quality report
    report = QualityReport.model_validate_json((out / "quality_report.json").read_text())
    assert report.raw_rows == n + 1 and report.valid_rows == valid and report.duplicate_rows == 0
    assert report.invalid_codes["flag:N"] == 1 and report.invalid_codes["flag:M"] == 1
    assert report.invalid_codes["magnitude_excluded:83"] == 24
    assert report.value_units["no2"] == "ug/m3" and report.value_units["co"] == "mg/m3"
    assert report.missing_by_column["value"] == n - valid
    assert set(report.input_sha256) == {
        "madrid-air/air-2019.zip",
        "madrid-air/interprete.pdf",
        "madrid-air-stations/estaciones-control-aire.csv",
        "madrid-air-stations/geoportal_layer5_estaciones.geojson",
        "madrid-air-stations/geoportal_layer5_metadata.json",
    }

    # 3. stations: official point where it exists, null geometry (never invented) where it does not
    entities = EntityCollection.model_validate_json((out / "stations.geojson").read_text())
    by_id = {f.id: f for f in entities.features}
    assert set(by_id) == {"28079004", "28079008", "28079058", "28079056"}
    assert by_id["28079056"].geometry is None and by_id["28079056"].properties.name is None
    assert by_id["28079056"].properties.attributes["has_official_coordinates"] is False
    assert by_id["28079004"].geometry.coordinates == (-3.7122567, 40.4238823)
    assert by_id["28079004"].properties.geometry_support.value == "observed_point"
    assert by_id["28079004"].properties.geometry_source == f"{URL}/layer/5"
    assert by_id["28079058"].properties.attributes["in_hourly_data"] is False
    stations = details["stations"]
    assert stations["in_data_without_official_coordinates"] == ["28079056"]
    assert stations["official_without_hourly_data"] == ["28079058"]
    assert list(stations["coordinate_discrepancies_over_5m"]) == ["28079008"]

    # 4. raw manifests were written and the markdown mentions the DST evidence
    assert SourceManifest.model_validate_json((workspace / "raw/madrid-air/source_manifest.json").read_text())
    text = (workspace / "quality.md").read_text()
    assert "2019-03-31" in text and "H03" in text and "28079056" in text


def test_rerun_without_download_is_deterministic(workspace):
    run(workspace)
    first = {p.name: p.read_bytes() for p in (workspace / "out").glob("*.json*")}
    ingest.run([2019], skip_download=True, out_dir=workspace / "out", doc_path=None)
    second = {p.name: p.read_bytes() for p in (workspace / "out").glob("*.json*")}
    assert first == second


def test_parse_years():
    assert ingest.parse_years("2019-2021") == [2019, 2020, 2021]
    assert ingest.parse_years("2019,2022") == [2019, 2022]
    assert ingest.parse_years("2025") == [2025]
