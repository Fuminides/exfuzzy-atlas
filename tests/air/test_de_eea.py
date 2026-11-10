"""EEA Germany NO2 ingestion on hand-written Parquet files shaped like the Air Quality Download Service files (AT-070).

No network and no real data. Each file is one sampling point; ``Start``/``End`` are naive timestamps in UTC+01.
"""

# ruff: noqa: E501  (SQL, URLs and prose templates)

import json
from datetime import datetime
from decimal import Decimal

import duckdb
import pandas as pd
import pytest

from atlas.contracts.models import EntityCollection
from atlas.contracts.observations import validate_observations_partitioned
from atlas.domains.air import eea_download, eea_ingest

CFG = eea_ingest.load_config()
YEARS = [2019]
OFFSET = 1


def write_eea(path, rows, *, agg="hour"):
    """rows: (start 'YYYY-MM-DD HH:MM', value or None, validity, verification[, unit])."""
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for row in rows:
        start, value, validity, verification, *unit = row
        s = pd.Timestamp(start)
        records.append(
            {
                "Samplingpoint": "DE/" + path.stem, "Pollutant": 8, "Start": s, "End": s + pd.Timedelta(hours=1),
                "Value": None if value is None else Decimal(str(value)), "Unit": unit[0] if unit else "ug.m-3",
                "AggType": agg, "Validity": validity, "Verification": verification,
                "ResultTime": pd.Timestamp("2020-01-01"), "DataCapture": None, "FkObservationLog": "x",
            }
        )
    frame = pd.DataFrame(records)
    con = duckdb.connect()
    con.register("f", frame)
    con.execute(
        "COPY (SELECT * REPLACE (CAST(Value AS DECIMAL(38,18)) AS Value, CAST(DataCapture AS DECIMAL(38,18)) AS DataCapture) FROM f) "
        f"TO '{path}.parquet' (FORMAT PARQUET)"
    )


def sp(station, group=1):
    return f"SPO.DE_{station}_NO2_dataGroup{group}"


def run_convert(tmp_path, e1a_files, e2a_files, years=None):
    raw = tmp_path / "raw"
    for key, files in (("e1a", e1a_files), ("e2a", e2a_files)):
        for name, rows in files.items():
            write_eea(raw / key / name, rows)
    out = tmp_path / "obs"
    info = eea_ingest.convert(CFG, years or YEARS, raw, tmp_path / "stg", out, OFFSET)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    df = con.execute(f"SELECT * FROM read_parquet('{out}/**/*.parquet', hive_partitioning=true) ORDER BY entity_id, timestamp_utc").df()
    return info, df, out


# a dummy second dataset file in the years of the test so that the E2a glob is never empty
E2A_FILLER = {sp("DEZZ999"): [("2019-01-01 00:00", 1.0, 1, 3)]}


def test_start_is_utc_plus_one_all_year_so_timestamp_utc_is_start_minus_one_hour(tmp_path):
    rows = [("2019-01-01 00:00", 10.0, 1, 1), ("2019-01-01 01:00", 11.0, 1, 1), ("2019-07-01 12:00", 20.0, 1, 1), ("2019-03-31 03:00", 30.0, 1, 1)]
    _, df, _ = run_convert(tmp_path, {sp("DEBB001"): rows}, E2A_FILLER)
    df = df[df["entity_id"] == "DEBB001"]
    by_local = dict(zip(df["source_timestamp_local"], df["timestamp_utc"], strict=True))
    # winter: 00:00 UTC+01 is 23:00Z of the previous day (the START of the hour, in UTC)
    assert by_local["2019-01-01 00:00 UTC+01"] == pd.Timestamp("2018-12-31T23:00:00Z")
    assert by_local["2019-01-01 01:00 UTC+01"] == pd.Timestamp("2019-01-01T00:00:00Z")
    # summer: the source clock does NOT move with daylight saving time, so 12:00 is 11:00Z (not 10:00Z)
    assert by_local["2019-07-01 12:00 UTC+01"] == pd.Timestamp("2019-07-01T11:00:00Z")
    # the spring-forward day has no hole and no repeated hour: 03:00 is simply 02:00Z
    assert by_local["2019-03-31 03:00 UTC+01"] == pd.Timestamp("2019-03-31T02:00:00Z")
    assert (df["timezone"] == "Europe/Berlin").all()


def test_the_value_belongs_to_the_hour_that_starts_at_start_not_to_end(tmp_path):
    # Start 10:00 End 11:00 (UTC+01): the hour [09:00Z, 10:00Z); timestamp_utc is its start, 09:00Z
    _, df, _ = run_convert(tmp_path, {sp("DEBB001"): [("2019-05-05 10:00", 42.0, 1, 1)]}, E2A_FILLER)
    row = df[df["entity_id"] == "DEBB001"].iloc[0]
    assert row["timestamp_utc"] == pd.Timestamp("2019-05-05T09:00:00Z") and row["value"] == 42.0


def test_validity_and_verification_flags_are_kept_and_invalid_values_are_null_not_the_sentinel(tmp_path):
    rows = [
        ("2019-02-01 00:00", 12.5, 1, 1),
        ("2019-02-01 01:00", -999, -1, 1),  # not valid: the files carry the sentinel -999
        ("2019-02-01 02:00", -999, -99, 1),  # maintenance / calibration
        ("2019-02-01 03:00", -3.2, 2, 1),  # valid, below the detection limit, measured value given (can be negative)
        ("2019-02-01 04:00", 0.5, 3, 2),  # replaced by 0.5 * detection limit
        ("2019-02-01 05:00", None, 1, 1),  # valid without a number
        ("2019-02-01 06:00", 7.0, 1, 3),
    ]
    _, df, out = run_convert(tmp_path, {sp("DEBB001"): rows}, E2A_FILLER)
    d = df[df["entity_id"] == "DEBB001"].set_index("validity_flag")
    assert d.loc["1:1"].iloc[0]["value"] == 12.5 and pd.isna(d.loc["1:1"].iloc[0]["missing_reason"])
    for flag in ("-1:1", "-99:1"):
        assert pd.isna(d.loc[flag]["value"]) and d.loc[flag]["missing_reason"] == "invalid_observation"
    assert (df["value"].dropna() != -999).all()
    assert d.loc["2:1"]["value"] == -3.2 and pd.isna(d.loc["2:1"]["censoring"])  # kept as reported
    assert d.loc["3:2"]["value"] == 0.5 and d.loc["3:2"]["censoring"] == "left"
    n = df[(df["entity_id"] == "DEBB001") & df["value"].isna()]
    assert sorted(n["missing_reason"]) == ["invalid_observation", "invalid_observation", "no_observation"]
    assert d.loc["1:3"]["value"] == 7.0  # verification 3 (not verified) is a flag, not a filter
    assert validate_observations_partitioned(out) == []


def test_units_are_converted_or_the_value_is_refused_never_mixed(tmp_path):
    raw = tmp_path / "raw"
    write_eea(raw / "e1a" / sp("DEBB001"), [("2019-02-01 00:00", 0.025, 1, 1, "mg.m-3"), ("2019-02-01 01:00", 13.0, 1, 1, "ppb")])
    write_eea(raw / "e2a" / sp("DEZZ999"), [("2019-01-01 00:00", 1.0, 1, 3)])
    eea_ingest.convert(CFG, YEARS, raw, tmp_path / "stg", tmp_path / "obs", OFFSET)
    df = duckdb.connect().execute(f"SELECT * FROM read_parquet('{tmp_path / 'obs'}/**/*.parquet', hive_partitioning=true) WHERE entity_id = 'DEBB001' ORDER BY timestamp_utc").df()
    assert df["value"].iloc[0] == pytest.approx(25.0) and df["unit"].iloc[0] == "ug/m3"  # 0.025 mg/m3 = 25 ug/m3
    assert pd.isna(df["value"].iloc[1]) and df["missing_reason"].iloc[1] == "invalid_observation"  # ppb is not converted


def test_e1a_wins_over_e2a_and_e2a_fills_the_rest_with_its_own_source_id(tmp_path):
    e1a = {sp("DEBB001"): [("2019-03-01 00:00", 10.0, 1, 1), ("2019-03-01 01:00", -999, -1, 1)]}
    e2a = {
        sp("DEBB001"): [("2019-03-01 00:00", 99.0, 1, 3), ("2019-03-01 01:00", 98.0, 1, 3), ("2019-03-01 02:00", 20.0, 1, 2)],
        sp("DEBB002"): [("2019-03-01 00:00", 5.0, 1, 2)],  # a station only in E2a
    }
    info, df, out = run_convert(tmp_path, e1a, e2a)
    one = df[df["entity_id"] == "DEBB001"].set_index("source_timestamp_local")
    assert one.loc["2019-03-01 00:00 UTC+01", "value"] == 10.0 and one.loc["2019-03-01 00:00 UTC+01", "source_id"] == "eea-air-de-e1a"
    # E1a says "not valid" for 01:00: the verified dataset is the authority, E2a does not override it
    assert pd.isna(one.loc["2019-03-01 01:00 UTC+01", "value"]) and one.loc["2019-03-01 01:00 UTC+01", "source_id"] == "eea-air-de-e1a"
    assert one.loc["2019-03-01 02:00 UTC+01", "value"] == 20.0 and one.loc["2019-03-01 02:00 UTC+01", "source_id"] == "eea-air-de-e2a"
    assert one.loc["2019-03-01 02:00 UTC+01", "validity_flag"] == "1:2"
    assert df[df["entity_id"] == "DEBB002"]["source_id"].eq("eea-air-de-e2a").all()
    assert info["precedence"]["hours_in_both_datasets"] == 2 and info["precedence"]["hours_in_both_with_different_value"] == 2
    assert not df.duplicated(["entity_id", "timestamp_utc", "feature_name"]).any()  # one row per station and hour
    assert validate_observations_partitioned(out) == []


def test_a_station_with_two_sampling_points_keeps_the_one_with_more_numbers(tmp_path):
    files = {
        sp("DEBB001", 1): [("2019-03-01 00:00", 1.0, 1, 1), ("2019-03-01 01:00", -999, -1, 1)],
        sp("DEBB001", 2): [("2019-03-01 00:00", 2.0, 1, 1), ("2019-03-01 01:00", 3.0, 1, 1)],
    }
    info, df, _ = run_convert(tmp_path, files, E2A_FILLER)
    assert info["inventory"]["e1a"]["stations_with_several_sampling_points"] == ["DEBB001"]
    assert df[df["entity_id"] == "DEBB001"]["value"].tolist() == [2.0, 3.0]


def test_years_are_those_of_the_source_clock_and_other_years_are_left_out(tmp_path):
    rows = [("2018-12-31 23:00", 1.0, 1, 1), ("2019-12-31 23:00", 2.0, 1, 1), ("2020-01-01 00:00", 3.0, 1, 1)]
    _, df, _ = run_convert(tmp_path, {sp("DEBB001"): rows}, E2A_FILLER)
    assert df[df["entity_id"] == "DEBB001"]["value"].tolist() == [2.0]  # 2019-12-31 23:00 UTC+01 = 22:00Z
    assert df[df["entity_id"] == "DEBB001"]["timestamp_utc"].iloc[0] == pd.Timestamp("2019-12-31T22:00:00Z")


@pytest.mark.parametrize("bad", ["agg", "interval"])
def test_unexpected_schema_stops_the_ingestion(tmp_path, bad):
    raw = tmp_path / "raw"
    write_eea(raw / "e1a" / sp("DEBB001"), [("2019-03-01 00:00", 1.0, 1, 1)], agg="day" if bad == "agg" else "hour")
    write_eea(raw / "e2a" / sp("DEZZ999"), [("2019-01-01 00:00", 1.0, 1, 3)])
    if bad == "interval":
        con = duckdb.connect()
        p = raw / "e1a" / (sp("DEBB001") + ".parquet")
        con.execute(f"COPY (SELECT * REPLACE (\"End\" + INTERVAL 1 HOUR AS \"End\") FROM read_parquet('{p}')) TO '{p}.tmp' (FORMAT PARQUET)")
        (raw / "e1a" / (sp("DEBB001") + ".parquet.tmp")).replace(p)
    with pytest.raises(SystemExit, match="violate the expected schema"):
        eea_ingest.convert(CFG, YEARS, raw, tmp_path / "stg", tmp_path / "obs", OFFSET)


def test_utc_offset_notation():
    assert eea_ingest.utc_offset_hours("UTC+01") == 1
    assert eea_ingest.utc_offset_hours("UTC") == 0
    assert eea_ingest.utc_offset_hours("UTC-02") == -2
    assert eea_ingest.offset_label(1) == "UTC+01" and eea_ingest.offset_label(0) == "UTC"
    with pytest.raises(ValueError):
        eea_ingest.utc_offset_hours("Europe/Berlin")


def test_month_ranges_cover_the_source_clock_years_in_utc():
    months = eea_ingest.month_ranges([2019, 2020], OFFSET)
    assert months[0][:2] == (2018, 12) and months[-1][:2] == (2020, 12)
    assert len(months) == 25 and months[0][2] == "2018-12-01T00:00:00+00:00"


def test_expected_hours_and_coverage_fraction():
    assert eea_ingest.expected_hours(2019) == 8760 and eea_ingest.expected_hours(2020) == 8784
    rows = [("DEBB001", 2019, 8760, 4380, None, None, ["eea-air-de-e1a"])]
    assert eea_ingest.coverage_tables(rows, [2019])["DEBB001"][2019]["fraction"] == 0.5


# ---------------------------------------------------------------------------------------------- download


def test_url_list_parser_and_request():
    payload = ("﻿ParquetFileUrl\r\n" + eea_download.BLOB_HOST + "airquality-p-e1a/DE/SPO.DE_DEBB007_NO2_dataGroup1.parquet\r\n").encode()
    urls = eea_download.parse_url_list(payload)
    assert urls == [eea_download.BLOB_HOST + "airquality-p-e1a/DE/SPO.DE_DEBB007_NO2_dataGroup1.parquet"]
    assert eea_download.file_name(urls[0]) == "SPO.DE_DEBB007_NO2_dataGroup1.parquet"
    with pytest.raises(ValueError):
        eea_download.parse_url_list(b"<html>error</html>")
    with pytest.raises(ValueError):
        eea_download.parse_url_list(b"ParquetFileUrl\nhttps://evil.example/x.parquet\n")
    body = eea_download.url_request(CFG, CFG["air"]["datasets"][0], [2019, 2025])
    assert body["dataset"] == 2 and body["aggregationType"] == "hour" and body["pollutants"] == ["NO2"] and body["countries"] == ["DE"]


def test_download_is_resumable_and_idempotent(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["stations"]["files"] = [{"path": "stations/m.csv", "url": "https://example.test/m.csv", "role": "metadata"}]
    answers = {
        "e1a": f"ParquetFileUrl\n{eea_download.BLOB_HOST}airquality-p-e1a/DE/{sp('DEBB001')}.parquet\n{eea_download.BLOB_HOST}airquality-p-e1a/DE/{sp('DEBB002')}.parquet\n",
        "e2a": f"ParquetFileUrl\n{eea_download.BLOB_HOST}airquality-p/DE/{sp('DEBB001')}.parquet\n",
    }
    posts, fetches = [], []

    def post(url, body):
        posts.append(body["dataset"])
        return answers["e1a" if body["dataset"] == 2 else "e2a"].encode()

    def fetch(url):
        fetches.append(url)
        return b"payload " + url.encode()

    kwargs = {"fetch": fetch, "post": post}
    manifest, got = eea_download.download(cfg, YEARS, tmp_path / "raw", **kwargs)
    assert len(got) == 4 and len(fetches) == 4 and posts == [2, 1]  # 3 data files + the metadata file
    assert {f.path for f in manifest.files} >= {"e1a/" + sp("DEBB001") + ".parquet", "e2a/" + sp("DEBB001") + ".parquet", "stations/m.csv"}
    _, again = eea_download.download(cfg, YEARS, tmp_path / "raw", **kwargs)
    assert again == [] and len(fetches) == 4 and posts == [2, 1]  # nothing fetched, the stored URL lists are reused
    # a document added to the config later is fetched alone; the data files stay in the manifest and are not fetched again
    cfg["stations"]["files"].append({"path": "docs/new.pdf", "url": "https://example.test/new.pdf", "role": "interpreter"})
    manifest, added = eea_download.download(cfg, YEARS, tmp_path / "raw", **kwargs)
    assert added == ["docs/new.pdf"] and len(fetches) == 5 and len(manifest.files) == 5


# ----------------------------------------------------------------------------------------------- stations


def metadata_frame(rows):
    cols = ["AirQualityStationEoICode", "Longitude", "Latitude", "Altitude", "AirQualityStationType", "AirQualityStationArea",
            "AirQualityNetwork", "MeasurementType", "Timezone", "ObservationDateBegin", "ObservationDateEnd"]
    return pd.DataFrame([[*r[:4], "traffic", "urban", "NET.DE_X", "automatic", "http://dd.eionet.europa.eu/vocabulary/aq/timezone/UTC+01", "2000", "NULL"] for r in rows], columns=cols)


def test_stations_bbox_fallback_coordinates_colocation_and_missing():
    observed = {c: {"first_utc": "2019-01-01T00:00:00+00:00", "last_utc": "2019-12-31T00:00:00+00:00", "datasets": ["e1a"], "sampling_point": f"SPO.DE_{c}_NO2_dataGroup1"}
                for c in ("DEAA001", "DEAA002", "DEAA003", "DEAA004", "DEAA005", "DEAA006")}
    meta = metadata_frame([
        ("DEAA001", "13.4000", "52.5000", "34"),
        ("DEAA002", "13.4003", "52.5000", "35"),  # 20 m from DEAA001
        ("DEAA003", "2.3500", "48.8600", "35"),   # Paris: inside Europe but outside Germany
    ])
    esri = {"DEAA004": {"name": "Fallback", "lon_lat": (9.17, 48.77)}, "DEAA001": {"name": "Alpha", "lon_lat": (13.4, 52.5)}}
    collection, rep = eea_ingest.build_station_collection(meta, esri, observed, CFG, [])
    assert isinstance(collection, EntityCollection)
    by_id = {f.id: f for f in collection.features}
    assert by_id["DEAA001"].geometry.coordinates == (13.4, 52.5) and by_id["DEAA001"].properties.name == "Alpha"
    assert by_id["DEAA001"].properties.attributes["station_type"] == "traffic"
    assert by_id["DEAA003"].geometry is None and rep["outside_bbox"] == {"DEAA003": [2.35, 48.86]}  # never silently kept
    assert by_id["DEAA003"].properties.attributes["rejected_coordinates_lon_lat"] == [2.35, 48.86]
    assert by_id["DEAA004"].geometry.coordinates == (9.17, 48.77) and "DEAA004" in rep["coordinates_from_stations_layer"]
    assert by_id["DEAA005"].geometry is None and by_id["DEAA006"].geometry is None
    assert rep["without_official_coordinates"] == ["DEAA005", "DEAA006"]
    assert [p[:2] for p in rep["colocated_pairs"]] == [("DEAA001", "DEAA002")] and rep["colocated_pairs"][0][2] < 30
    assert by_id["DEAA001"].properties.attributes["colocated_within_100m"][0]["id"] == "DEAA002"


def test_diurnal_check_finds_the_one_hour_shift_of_a_fixed_utc_plus_one_clock(tmp_path):
    # Synthetic rush hour at 07:00-08:00 local clock; local = UTC+1 (winter) or UTC+2 (summer): UTC hour 6 vs 5.
    rows = []
    for month, local_offset in ((1, 1), (7, 2)):
        for day in range(1, 29):
            if datetime(2019, month, day).isoweekday() not in (2, 3, 4, 5):
                continue
            for hour_utc in range(24):
                local = (hour_utc + local_offset) % 24
                rows.append(("T1", pd.Timestamp(2019, month, day, hour_utc, tz="UTC"), 100.0 if local in (7, 8) else 20.0))
    frame = pd.DataFrame(rows, columns=["entity_id", "timestamp_utc", "value"])
    frame["timestamp_utc"] = frame["timestamp_utc"].astype("datetime64[us, UTC]")
    out = tmp_path / "obs" / "year=2019" / "month=1"
    out.mkdir(parents=True)
    frame.to_parquet(out / "d.parquet")
    f = {"type": "Feature", "id": "T1", "geometry": None, "properties": {
        "entity_id": "T1", "domain": "air", "name": "t", "geometry_support": "observed_point", "geometry_source": "x", "timezone": "Europe/Berlin",
        "attributes": {"station_type": "traffic", "station_area": "urban"}}}
    stations = EntityCollection.model_validate({"type": "FeatureCollection", "domain": "air", "data_version": "t", "features": [f]})
    result = eea_ingest.diurnal_check(tmp_path / "obs", stations, 2019)
    assert result["best_lag_hours"] == 1 and result["summer_cycle_one_hour_earlier"] is True
