"""Meteorology ingestion on hand-written files: parsing, DST slots, month guard, stations, report."""

import json

import duckdb
import pytest

from atlas.contracts.models import EntityCollection, QualityReport
from atlas.contracts.observations import validate_observations
from atlas.domains.air import meteo
from atlas.domains.air.parse import read_csv_wide, wide_to_long

URL = "https://example.test"
HEADER = "PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;" + ";".join(
    f"H{i:02d};V{i:02d}" for i in range(1, 25)
)


def csv_row(station, magnitude, day, values, flags=None, month="03", year="2019"):
    flags = flags or ["V"] * 24
    cells = ";".join(f"{v};{f}" for v, f in zip(values, flags, strict=True))
    return f"28;079;{station};{magnitude};28079{int(station):03d}_{magnitude}_98;{year};{month};{day};{cells}"


def txt_row(station, magnitude, day, values, flags=None, month="03", year="2019"):
    flags = flags or ["V"] * 24
    cells = ",".join(f"{v},{f}" for v, f in zip(values, flags, strict=True))
    return f"28,079,{int(station):03d},{magnitude},98,02,{year},{month},{day},{cells}"


def temps(base):
    return [f"{base + i / 10:.1f}" for i in range(24)]


# Spring-forward day 2019-03-31: the nonexistent hour is slot H03 (invalid N in the source).
SPRING_FLAGS = ["V"] * 2 + ["N"] + ["V"] * 21
CSV = "\n".join(
    [
        HEADER,
        csv_row(4, 83, "31", temps(10), SPRING_FLAGS),
        csv_row(102, 81, "31", ["1.5"] * 24, SPRING_FLAGS),
        csv_row(102, 81, "30", ["2.5"] * 24, ["V"] * 4 + ["N"] + ["V"] * 19),
        csv_row(102, 86, "31", ["55"] * 23 + ["130"], SPRING_FLAGS),  # 130 % humidity is physically impossible
        csv_row(102, 99, "31", ["1"] * 24, SPRING_FLAGS),  # unknown magnitude: counted, not written
    ]
)
TXT = "\n".join(
    [
        txt_row(4, 83, "31", temps(99), SPRING_FLAGS),  # same key as the CSV row: the CSV wins
        txt_row(103, 89, "31", ["0.0"] * 24, SPRING_FLAGS),  # only in the TXT
    ]
)

STATIONS_HEADER = (
    "CÓDIGO;CÓDIGO_CORTO;ESTACION;DIRECCION;LONGITUD_ETRS89;LATITUD_ETRS89;ALTITUD;"
    "VV (81);DV (82);T (83);HR (86);PB (87);RS (88);P (89);LONGITUD;LATITUD"
)
STATIONS = "\n".join(
    [
        STATIONS_HEADER,
        "28079004;4;Plaza España;Plaza de España;x;y;637;;;X;;;;;-3.7122567;40.4238823",
        "28079102;102;J.M.D. Moratalaz;C/ Fuente Carantona, 8;x;y;686;X;X;X;X;;;;-3,636944;40,398611",
        "28079103;103;J.M.D. Villaverde;C/ Arroyo Bueno, 53;x;y;595;;;;;;;X;-3.711178;40.348902",
        "28079999;999;Sin datos;;x;y;;X;;;;;;;-3.7;40.4",
    ]
)

CONFIG = {
    "data_version": "meteo-test-v1",
    "meteo": {
        "source_id": "madrid-meteo",
        "title": "t",
        "landing_url": URL,
        "license": "CC BY 4.0",
        "attribution": "AM",
        "period_start": "2019-01-01",
        "files": [
            {"path": "interprete.pdf", "url": f"{URL}/pdf", "role": "interpreter"},
            {"path": "meteo-2019-03.csv", "url": f"{URL}/csv", "role": "data", "years": [2019], "month": 3},
            {"path": "meteo-2019-03.txt", "url": f"{URL}/txt", "role": "data", "years": [2019], "month": 3},
        ],
    },
    "stations": {
        "source_id": "madrid-meteo-stations",
        "title": "s",
        "landing_url": f"{URL}/stations",
        "license": "CC BY 4.0",
        "attribution": "AM",
        "files": [{"path": "estaciones-meteorologicas.csv", "url": f"{URL}/st", "role": "geometry"}],
    },
}
PAYLOADS = {
    f"{URL}/pdf": b"%PDF-fake",
    f"{URL}/csv": CSV.encode(),
    f"{URL}/txt": TXT.encode(),
    f"{URL}/st": STATIONS.encode(),
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(CONFIG))
    monkeypatch.setattr(meteo, "CONFIG_PATH", path)
    monkeypatch.setattr(meteo, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("atlas.domains.air.ingest.RAW_DIR", tmp_path / "raw")
    return tmp_path


def run(workspace, payloads=None):
    data = payloads or PAYLOADS
    return meteo.run([2019], out_dir=workspace / "out", doc_path=workspace / "q.md", fetch=lambda url: data[url])


def test_end_to_end(workspace):
    details = run(workspace)
    out = workspace / "out"
    assert validate_observations(out / "observations" / "**" / "*.parquet") == []
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT entity_id, feature_name, unit, source_id, domain, timestamp_utc, value, missing_reason "
        f"FROM read_parquet('{out}/observations/**/*.parquet', hive_partitioning=true)"
    ).fetchall()
    by_feature = {}
    for entity, name, unit, source, domain, ts, value, reason in rows:
        assert (source, domain) == ("madrid-meteo", "air")
        by_feature.setdefault((entity, name), []).append((ts, value, reason, unit))
    # spring-forward day: 23 rows (the nonexistent local hour has no UTC instant) and the CSV beats the TXT
    temperature = sorted(by_feature[("28079004", "temperature")])
    assert len(temperature) == 23 and temperature[0][3] == "degC"
    assert [v for _, v, _, _ in temperature if v is not None][0] == 10.0  # CSV value, not the TXT one (99.0)
    assert all(v is None or v < 20 for _, v, _, _ in temperature)
    # wind: two days (23 + 24 rows), stations keep their 8-digit code, the N slot has a null value and a reason
    wind = by_feature[("28079102", "wind_speed")]
    assert len(wind) == 47
    assert {v for _, v, _, _ in wind} == {1.5, 2.5, None}
    assert [r for _, v, r, _ in wind if v is None] == ["invalid_observation"]
    assert len(by_feature[("28079103", "precipitation")]) == 23  # only in the TXT
    assert details["counters"]["overlap_slots_cross_format"] == 24
    assert details["unknown_magnitude_slots"] == {"99": 24}

    report = QualityReport.model_validate_json((out / "quality_report.json").read_text())
    assert report.source_id == "madrid-meteo"
    assert report.invalid_codes["flag:N"] == 1 and report.invalid_codes["magnitude_excluded:99"] == 24
    assert report.outliers_flagged == 1  # the 130 % humidity, flagged but kept
    assert details["plausibility_flagged"] == {"relative_humidity": 1}
    assert report.value_units["wind_speed"] == "m/s" and report.value_units["pressure"] == "mbar"
    assert details["dst_anomalies"] == {}
    text = (workspace / "q.md").read_text()
    assert "2019-03-31" in text and "28079102" in text and "J.M.D. Moratalaz" in text


def test_stations_use_official_coordinates_and_sensor_flags(workspace):
    details = run(workspace)
    entities = EntityCollection.model_validate_json((workspace / "out" / "stations.geojson").read_text())
    by_id = {f.id: f for f in entities.features}
    assert set(by_id) == {"28079004", "28079102", "28079103", "28079999"}
    assert by_id["28079102"].geometry.coordinates == (-3.636944, 40.398611)  # decimal comma accepted
    assert by_id["28079004"].properties.attributes["official_sensors"] == ["temperature"]
    assert by_id["28079999"].properties.attributes["in_hourly_data"] is False
    assert details["stations"]["official_without_data"] == ["28079999"]
    # 102 declares wind speed, direction, temperature, humidity; the file has wind speed and humidity only
    assert details["stations"]["sensor_mismatch"]["28079102"]["official_only"] == ["temperature", "wind_direction"]


def test_a_file_whose_rows_are_not_in_the_declared_month_is_refused(workspace):
    wrong = {**PAYLOADS, f"{URL}/csv": "\n".join([HEADER, csv_row(4, 83, "01", temps(10), month="04")]).encode()}
    with pytest.raises(SystemExit, match="declared month"):
        run(workspace, wrong)


def test_meteo_reuses_the_air_reader_with_its_own_magnitudes():
    wide = read_csv_wide(CSV)
    table, stats = wide_to_long(wide, data_version="v", magnitudes=meteo.METEO_MAGNITUDES, source_id="madrid-meteo")
    assert set(table.column("source_id").to_pylist()) == {"madrid-meteo"}
    assert "no2" not in set(table.column("feature_name").to_pylist())
    assert stats.unknown_magnitude_slots == {"99": 24}
