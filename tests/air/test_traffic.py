"""Hourly aggregation of the 15-minute traffic records (AT-012) on hand-written CSVs shaped like the portal's."""

import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.models import QualityReport
from atlas.contracts.observations import OBSERVATION_SCHEMA, validate_observations
from atlas.domains.air import ingest, traffic

HEADER = '"id";"fecha";"tipo_elem";"intensidad";"ocupacion";"carga";"vmed";"error";"periodo_integracion"'


def write_csv(path, rows, header=HEADER):
    """rows: (id, 'YYYY-MM-DD HH:MM:SS' local, intensity or 'NaN', error flag)."""
    lines = [header]
    for pid, fecha, intensity, error in rows:
        lines.append(f'{pid};"{fecha}";"URB";"{intensity}";"1";"2";"0";"{error}";15')
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def quarters(pid, day, hour, values, errors=None):
    """Four 15-minute records of local hour ``hour``; ``values[i]`` may be 'NaN'."""
    errors = errors or ["N"] * 4
    return [(pid, f"{day} {hour:02d}:{15 * i:02d}:00", values[i], errors[i]) for i in range(4)]


def agg(tmp_path, rows, month, ids=(1,), **kw):
    csv_path = write_csv(tmp_path / "t.csv", rows)
    table, stats = traffic.aggregate_month(csv_path, set(ids), month, data_version="test", **kw)
    out = {}
    for r in table.to_pylist():
        out[(r["entity_id"], r["timestamp_utc"])] = r
    return table, stats, out


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_dst_local_hours():
    march = traffic.dst_local_hours("2023-03")
    assert march["nonexistent"] == [datetime(2023, 3, 26, 2)]
    assert march["first_slot_after_gap"] == [datetime(2023, 3, 26, 3)]
    assert march["ambiguous"] == []
    october = traffic.dst_local_hours("2023-10")
    assert october["nonexistent"] == []
    assert october["ambiguous"] == [
        (datetime(2023, 10, 29, 2), utc(2023, 10, 29, 0)),
        (datetime(2023, 10, 29, 2), utc(2023, 10, 29, 1)),
    ]
    assert traffic.dst_local_hours("2023-07") == {"nonexistent": [], "first_slot_after_gap": [], "ambiguous": []}


def test_hourly_mean_and_utc_conversion(tmp_path):
    rows = quarters(1, "2023-01-05", 10, [100, 200, 300, 400])
    table, stats, out = agg(tmp_path, rows, "2023-01")
    row = out[("1", utc(2023, 1, 5, 9))]  # January: local = UTC+1
    assert row["value"] == pytest.approx(250.0)
    assert row["n_records"] == 4
    assert row["validity_flag"] == "valid" and row["missing_reason"] is None
    assert row["unit"] == "veh/h" and row["source_id"] == "madrid-traffic" and row["domain"] == "air"
    assert row["aggregation_window_end_utc"] - row["aggregation_window_start_utc"] == utc(2023, 1, 5, 10) - utc(
        2023, 1, 5, 9
    )
    assert row["source_timestamp_local"] == "2023-01-05 10:00:00"
    assert validate_observations(table) == []


def test_summer_offset_is_two_hours(tmp_path):
    _, _, out = agg(tmp_path, quarters(1, "2023-07-05", 10, [10, 10, 10, 10]), "2023-07")
    assert ("1", utc(2023, 7, 5, 8)) in out


def test_invalid_records_and_three_of_four_rule(tmp_path):
    rows = (
        quarters(1, "2023-01-05", 11, [100, 200, 300, 9999], ["N", "N", "N", "E"])  # 3 valid, E excluded
        + quarters(1, "2023-01-05", 12, [100, 200, "NaN", 400], ["N", "N", "N", ""])  # only 2 valid
        + quarters(1, "2023-01-05", 13, [0, 0, 0, 0])  # genuine zeros stay 0
        + quarters(1, "2023-01-05", 14, [100, 30000, 100, 100])  # implausible record is invalid, 3 valid remain
        + quarters(1, "2023-01-05", 15, [100, 100, 100, 100], ["S", "S", "S", "S"])  # all error-flagged
        + [(1, "2023-01-05 16:00:00", 500, "N")]  # a single record
        + quarters(1, "2023-01-05", 17, [-1, -1, 100, 100])  # negative = absent data
    )
    _, stats, out = agg(tmp_path, rows, "2023-01")
    h = lambda hour: out[("1", utc(2023, 1, 5, hour - 1))]  # noqa: E731
    assert h(11)["value"] == pytest.approx(200.0) and h(11)["n_records"] == 3
    assert h(12)["value"] is None and h(12)["missing_reason"] == "invalid_observation"
    assert h(12)["validity_flag"] == "insufficient_valid_records" and h(12)["n_records"] == 2
    assert h(13)["value"] == 0.0 and h(13)["validity_flag"] == "valid"
    assert h(14)["value"] == pytest.approx(100.0) and h(14)["n_records"] == 3
    assert h(15)["value"] is None and h(15)["n_records"] == 0
    assert h(16)["value"] is None and h(16)["n_records"] == 1
    assert h(17)["value"] is None
    assert ("1", utc(2023, 1, 5, 18)) not in out  # hour with no record: no row
    s = stats["selected_status"]
    assert s["error_flag_E"] == 1 and s["error_flag_S"] == 4 and s["error_flag_blank"] == 1
    assert s["intensity_missing"] == 1 and s["intensity_implausible"] == 1 and s["intensity_negative"] == 2


def test_only_selected_ids_and_declared_month(tmp_path):
    rows = (
        quarters(1, "2023-01-05", 10, [1, 1, 1, 1])
        + quarters(2, "2023-01-05", 10, [9, 9, 9, 9])
        + quarters(1, "2023-02-01", 10, [5, 5, 5, 5])  # outside the declared month
    )
    _, stats, out = agg(tmp_path, rows, "2023-01")
    assert {k[0] for k in out} == {"1"}
    assert stats["selected_status"]["outside_declared_month"] == 4
    assert all(k[1].month == 1 for k in out)


def test_duplicate_slots_are_invalid(tmp_path):
    rows = quarters(1, "2023-01-05", 10, [100, 100, 100, 100]) + [(1, "2023-01-05 10:00:00", 100, "N")]
    _, stats, out = agg(tmp_path, rows, "2023-01")
    assert stats["selected_status"]["duplicate_slot"] == 2
    row = out[("1", utc(2023, 1, 5, 9))]
    assert row["n_records"] == 3  # the duplicated slot (2 records) is excluded


def test_spring_forward_gap(tmp_path):
    day = "2023-03-26"
    rows = (
        quarters(1, day, 1, [100, 100, 100, 100])
        + [(1, f"{day} 02:00:00", 777, "N")]  # a local time that does not exist
        + quarters(1, day, 3, [10, 20, 30, 40])  # the 03:00 slot follows the gap
        + quarters(1, day, 4, [50, 50, 50, 50])
    )
    _, stats, out = agg(tmp_path, rows, "2023-03")
    assert stats["selected_status"]["dst_nonexistent_local_time"] == 1
    assert stats["selected_status"]["dst_transition_slot"] == 1
    assert out[("1", utc(2023, 3, 26, 0))]["value"] == pytest.approx(100.0)  # 01:xx CET
    after = out[("1", utc(2023, 3, 26, 1))]  # 03:xx CEST, the hour right after the gap
    assert after["n_records"] == 3 and after["value"] == pytest.approx(30.0)  # 03:00 slot dropped
    assert out[("1", utc(2023, 3, 26, 2))]["value"] == pytest.approx(50.0)
    assert not any(k[1] == utc(2023, 3, 26, 1, 30) for k in out)
    assert len([k for k in out if k[1].day == 26]) == 3  # no row for the nonexistent hour


def test_fall_back_ambiguous_hour_is_null_for_both_utc_hours(tmp_path):
    day = "2023-10-29"
    rows = (
        quarters(1, day, 1, [100, 100, 100, 100])
        + quarters(1, day, 2, [200, 200, 200, 200])  # appears once, but happens twice
        + quarters(1, day, 3, [300, 300, 300, 300])
    )
    table, _, out = agg(tmp_path, rows, "2023-10")
    assert out[("1", utc(2023, 10, 28, 23))]["value"] == pytest.approx(100.0)  # 01:xx CEST
    for hour in (0, 1):
        row = out[("1", utc(2023, 10, 29, hour))]
        assert row["value"] is None
        assert row["validity_flag"] == "ambiguous_local_hour" and row["missing_reason"] == "invalid_observation"
    assert out[("1", utc(2023, 10, 29, 2))]["value"] == pytest.approx(300.0)  # 03:xx CET
    assert validate_observations(table) == []


def test_alternative_timestamp_format_and_header_check(tmp_path):
    rows = [
        (1, "05/01/2023 10:00:00", 100, "N"),
        (1, "05/01/2023 10:15:00", 100, "N"),
        (1, "05/01/2023 10:30:00", 100, "N"),
    ]
    _, _, out = agg(tmp_path, rows, "2023-01")
    assert out[("1", utc(2023, 1, 5, 9))]["value"] == pytest.approx(100.0)
    bad = write_csv(tmp_path / "bad.csv", [], header='"id";"fecha";"tipo"')
    with pytest.raises(SystemExit, match="header"):
        traffic.aggregate_month(bad, {1}, "2023-01", data_version="test")


def test_months_range():
    assert traffic.parse_months("2022-11:2023-02") == ["2022-11", "2022-12", "2023-01", "2023-02"]
    assert traffic.parse_months("2023-03,2023-01") == ["2023-01", "2023-03"]


def test_wait_for_memory_polls_then_proceeds():
    slept = []
    traffic.wait_for_memory(1500, poll_s=1, sleep=slept.append, read=lambda: 500.0 if len(slept) < 2 else 2000.0)
    assert slept == [1, 1]
    with pytest.raises(SystemExit):
        traffic.wait_for_memory(1500, poll_s=1, max_wait_s=2, sleep=lambda s: None, read=lambda: 100.0)


def test_pipeline_end_to_end_on_a_tiny_month(tmp_path, monkeypatch):
    """Download (injected fetch) -> association -> unzip -> hourly canonical parquet -> quality report and doc."""
    raw = tmp_path / "data" / "raw"
    monkeypatch.setattr(traffic, "RAW_DIR", raw)
    monkeypatch.setattr(ingest, "RAW_DIR", raw)

    lon, lat = -3.70, 40.42
    processed = tmp_path / "air"
    (processed / "observations").mkdir(parents=True)
    cols = {n: [] for n in OBSERVATION_SCHEMA.names}
    ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
    for name, value in (("domain", "air"), ("entity_id", "S1"), ("timestamp_utc", ts), ("timezone", "Europe/Madrid"),
                        ("feature_name", "no2"), ("value", 30.0), ("unit", "ug/m3"), ("source_id", "madrid-air"),
                        ("data_version", "t")):  # fmt: skip
        cols[name].append(value)
    for name in OBSERVATION_SCHEMA.names:
        if not cols[name]:
            cols[name].append(None)
    pq.write_table(pa.table(cols, schema=OBSERVATION_SCHEMA), processed / "observations" / "part.parquet")
    feature = {"id": "S1", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"name": "Station"}}
    (processed / "stations.geojson").write_text(json.dumps({"features": [feature]}))

    north = lambda m: lat + m / 111_195.0  # noqa: E731
    points_csv = (
        '"tipo_elem";"distrito";"id";"cod_cent";"nombre";"utm_x";"utm_y";"longitud";"latitud"\r\n'
        f'"URB";1;1;"a";"near";0;0;{lon};{north(200)}\r\n'
        f'"URB";1;2;"b";"mid";0;0;{lon};{north(700)}\r\n'
        f'"URB";1;3;"c";"far";0;0;{lon};{north(5000)}\r\n'
    ).encode()
    rows = quarters(1, "2023-01-05", 10, [100, 100, 100, 100]) + quarters(2, "2023-01-05", 10, [900] * 4)
    rows += quarters(3, "2023-01-05", 10, [5] * 4) + quarters(1, "2023-01-05", 11, [100, 100, "NaN", "NaN"])
    csv_path = write_csv(tmp_path / "src.csv", rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.write(csv_path, "01-2023.csv")
    meta = {"title": "t", "landing_url": "https://example.test/", "license": "CC BY 4.0", "attribution": "a"}
    spec = {"role": "data", "month": "2023-01"}
    config = {
        "data_version": "test-v1",
        "aggregation": {"min_valid_quarters": 3, "intensity_max_veh_h": 20000},
        "association": {"study_radii_m": [250, 500, 1000], "radius_m": 500, "kinds": ["urban", "m30", "other"]},
        "traffic": meta | {"files": [{**spec, "path": "traffic-2023-01.zip", "url": "https://example.test/t.zip"}]},
        "points": meta | {"files": [{**spec, "path": "points-2023-01.csv", "url": "https://example.test/p.csv"}]},
    }  # fmt: skip
    payloads = {"https://example.test/t.zip": buffer.getvalue(), "https://example.test/p.csv": points_csv}
    out = tmp_path / "out"
    doc = tmp_path / "doc.md"
    result = traffic.run(
        ["2023-01"],
        processed=processed,
        out_dir=out,
        config=config,
        fetch=payloads.__getitem__,
        min_available_mb=0,
        doc_path=doc,
    )

    assoc = pd.read_parquet(out / "association.parquet")
    assert sorted(assoc["traffic_point_id"]) == [1, 2]  # point 3 is 5 km away: not even a study candidate
    assert dict(zip(assoc["traffic_point_id"], assoc["in_rule"], strict=True)) == {1: True, 2: False}
    obs = pq.read_table(out / "observations").to_pylist()
    assert {r["entity_id"] for r in obs} == {"1"}  # only the points of the association are aggregated
    by_hour = {r["timestamp_utc"]: r for r in obs}
    assert by_hour[utc(2023, 1, 5, 9)]["value"] == pytest.approx(100.0)
    assert by_hour[utc(2023, 1, 5, 10)]["value"] is None  # 2 of 4 NaN records: not enough valid quarters
    report = QualityReport.model_validate_json((out / "quality_report.json").read_text())
    assert report.raw_rows == 8 and report.valid_rows == 6 and report.value_units == {"traffic_intensity": "veh/h"}
    assert (
        json.loads((out / "association_summary.json").read_text())["per_station_last_month"][0][
            "rule_points_last_month"
        ]
        == 1
    )
    assert "madrid-traffic" in doc.read_text() and result["details"]["hourly_rows"] == 2
    assert (raw / "madrid-traffic" / "source_manifest.json").exists()
    assert (raw / "madrid-traffic-points" / "source_manifest.json").exists()
