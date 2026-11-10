"""DWD hourly meteorology for the Germany air task on hand-written station zips (AT-070). No network, no real data."""

# ruff: noqa: E501  (SQL, URLs and prose templates)

import io
import json
import zipfile
from datetime import date

import duckdb
import pandas as pd
import pytest

from atlas.contracts.observations import validate_observations_partitioned
from atlas.domains.air import dwd_download, dwd_ingest

CFG = dwd_ingest.load_config()
PERIOD = (date(2019, 1, 1), date(2025, 12, 31))

PARAM_HEADER = "Stations_ID;Von_Datum;Bis_Datum;Stationsname;Parameter;Parameterbeschreibung;Einheit;Datenquelle (Strukturversion=SV);Zusatz-Info;Besonderheiten;Literaturhinweis;eor;\n"
PARAM_UTC = PARAM_HEADER + (
    "44;19500101;19991231;Gro\xdfenkneten;TT_TU;Lufttemperatur;\xb0C;alte Daten;Stundenwerte in MEZ;;;eor;\n"
    "44;20000101;20260418;Gro\xdfenkneten;TT_TU;Lufttemperatur;\xb0C;SYNOP;Stundenwerte in UTC;;;eor;\n"
    "44;20000101;20260418;Gro\xdfenkneten;RF_TU;relative Feuchte;%;SYNOP;Stundenwerte in UTC;;;eor;\n"
)
PARAM_MEZ = PARAM_HEADER + "44;20000101;20260418;Gro\xdfenkneten;TT_TU;Lufttemperatur;\xb0C;SYNOP;Stundenwerte in MEZ;;;eor;\n"
GEO = (
    "Stations_id;Stationshoehe;Geogr.Breite;Geogr.Laenge;von_datum;bis_datum;Stationsname\n"
    "    44;   45.00; 52.8900;  8.2300;19450801;19481231;Gro\xdfenkneten\n"
    "    44;   42.00; 52.9164;  8.2211;19930701;20070331;Gro\xdfenkneten\n"
    "    44;   44.00; 52.9336;  8.2370;20070401;20991231;Gro\xdfenkneten\n"
)


def tu_file(rows):
    lines = ["STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor"]
    lines += [f"{44:10d};{stamp};{qn:5d};{t:6.1f};{rh:6.1f};eor" for stamp, qn, t, rh in rows]
    return "\n".join(lines) + "\n"


def make_zip(product_name, product_text, parameter=PARAM_UTC, geography=GEO):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Metadaten_Parameter_tu_stunde_00044.html", "<html>not the text file</html>")
        archive.writestr("Metadaten_Parameter_tu_stunde_00044.txt", parameter.encode("latin-1"))
        archive.writestr("Metadaten_Geographie_00044.txt", geography.encode("latin-1"))
        archive.writestr(product_name, product_text.encode("latin-1"))
    return buffer.getvalue()


def test_label_is_taken_as_the_start_of_the_hour_and_missing_values_are_null():
    text = tu_file([("2019010100", 3, 7.3, 78.0), ("2019010101", 3, -999.0, -999.0), ("2019062812", 10, 25.0, 40.0)])
    frame = dwd_ingest.parse_product(text, CFG["meteo"]["products"][0]["columns"])
    assert set(frame["feature_name"]) == {"temperature", "relative_humidity"}
    t = frame[frame["feature_name"] == "temperature"].reset_index(drop=True)
    assert t["ts_utc"].tolist()[0] == pd.Timestamp("2019-01-01T00:00:00Z")  # label = start; usable from label + 1 h
    assert t["ts_utc"].tolist()[2] == pd.Timestamp("2019-06-28T12:00:00Z")  # UTC all year: no daylight saving shift
    assert pd.isna(t["value"][1]) and t["value"][0] == 7.3 and t["qn"].tolist() == [3, 3, 10]
    t, *_ = dwd_ingest.apply_time_reference(t, {"TT_TU": [("20190101", "20191231", "UTC")]}, {"TT_TU": "temperature"})
    table = dwd_ingest.to_observation_table(t, "DWD00044", CFG["meteo"]["units"], "v", "dwd-meteo-de", "Europe/Berlin").to_pandas()
    assert table["missing_reason"].isna().tolist() == [True, False, True]  # None (pandas 2) or NaN (pandas 3)
    assert table["missing_reason"][1] == "no_observation"  # -999 -> NULL, never 0 and never -999
    assert table["value"].isna().tolist() == [False, True, False] and table["unit"].eq("degC").all()
    assert table["source_timestamp_local"][0] == "2019010100 UTC" and table["validity_flag"].tolist() == ["3", "3", "10"]


def test_the_quality_column_may_have_any_qn_name_and_a_missing_column_is_an_error():
    text = "STATIONS_ID;MESS_DATUM;QN_8;P;P0;eor\n 96;2025043000;3;1025.0;1018.7;eor\n"
    frame = dwd_ingest.parse_product(text, {"P0": "pressure"})
    assert frame["value"].tolist() == [1018.7] and frame["feature_name"].tolist() == ["pressure"]
    with pytest.raises(ValueError, match="not in the file"):
        dwd_ingest.parse_product(text, {"TT_TU": "temperature"})


def test_the_time_reference_of_each_used_column_is_read_and_a_mez_label_is_converted_to_utc():
    segments = dwd_ingest.time_reference_segments(PARAM_UTC, ["TT_TU", "RF_TU"], *PERIOD)
    assert segments == {"TT_TU": [("20000101", "20260418", "UTC")], "RF_TU": [("20000101", "20260418", "UTC")]}  # the MEZ row ends in 1999
    mez = dwd_ingest.time_reference_segments(PARAM_MEZ, ["TT_TU"], *PERIOD)
    assert mez == {"TT_TU": [("20000101", "20260418", "MEZ")]}
    frame = dwd_ingest.parse_product(tu_file([("2019070112", 3, 20.0, 50.0)]), {"TT_TU": "temperature"})
    out, dropped, refused = dwd_ingest.apply_time_reference(frame, mez, {"TT_TU": "temperature"})
    assert dropped == 0 and refused == 0
    # MEZ is the fixed UTC+1 (no daylight saving): 12:00 MEZ is 11:00Z even in July
    assert out["ts_utc"].iloc[0] == pd.Timestamp("2019-07-01T11:00:00Z") and out["ref"].iloc[0] == "MEZ"
    utc, *_ = dwd_ingest.apply_time_reference(frame, segments, {"TT_TU": "temperature"})
    assert utc["ts_utc"].iloc[0] == pd.Timestamp("2019-07-01T12:00:00Z")
    table = dwd_ingest.to_observation_table(out, "DWD00044", CFG["meteo"]["units"], "v", "dwd-meteo-de", "Europe/Berlin").to_pandas()
    assert table["source_timestamp_local"].iloc[0] == "2019070112 MEZ"  # the original clock is kept


def test_an_unknown_or_missing_time_reference_stops_the_ingestion_instead_of_guessing():
    legal = PARAM_UTC.replace("Stundenwerte in UTC", "Stundenwerte in GZ")
    with pytest.raises(ValueError, match="not UTC or MEZ"):
        dwd_ingest.time_reference_segments(legal, ["TT_TU"], *PERIOD)
    frame = dwd_ingest.parse_product(tu_file([("2019070112", 3, 20.0, 50.0)]), {"TT_TU": "temperature"})
    kept, dropped, _ = dwd_ingest.apply_time_reference(frame, {"TT_TU": [("20200101", "20201231", "UTC")]}, {"TT_TU": "temperature"})
    assert kept.empty and dropped == 1  # outside every stated segment: dropped and counted, not guessed
    # a reference the configuration does not accept is refused (Germany accepts UTC only): the series is left out, not converted
    kept, dropped, refused = dwd_ingest.apply_time_reference(
        frame, {"TT_TU": [("20190101", "20191231", "MEZ")]}, {"TT_TU": "temperature"}, accepted=("UTC",)
    )
    assert kept.empty and dropped == 0 and refused == 1
    assert dwd_ingest.load_config()["meteo"]["accepted_time_references"] == ["UTC"]


def test_station_list_rows_are_parsed_with_names_that_contain_spaces():
    text = (
        "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname                             Bundesland Abgabe\n"
        "----------- --------- --------- ------------- --------- --------- ----------------------------------------- ---------- ------\n"
        "00011 19800901 20261031            680     47.9736    8.5205 Donaueschingen (Landeplatz)              Baden-W\xfcrttemberg Frei\n"
        "00005 19790102 19950630            190     50.8167    6.1833 Aachen-Merzbr\xfcck                      Nordrhein-Westfalen\n"
    )
    frame = dwd_ingest.parse_station_list(text)
    assert frame.iloc[0]["Stations_id"] == "00011" and frame.iloc[0]["Stationsname"] == "Donaueschingen (Landeplatz)"
    assert frame.iloc[0]["Bundesland"] == "Baden-W\xfcrttemberg" and frame.iloc[0]["geoBreite"] == 47.9736
    assert frame.iloc[1]["Stationsname"] == "Aachen-Merzbr\xfcck" and frame.iloc[1]["Bundesland"] == "Nordrhein-Westfalen"
    assert dwd_ingest.entity_id("00011") == "DWD00011"


def test_station_position_is_the_last_one_in_the_period_and_relocations_are_measured():
    geo = dwd_ingest.parse_geography(GEO)
    pos = dwd_ingest.station_position(geo, *PERIOD)
    assert (pos["lon"], pos["lat"], pos["height_m"], pos["positions_in_period"]) == (8.2370, 52.9336, 44.0, 1)
    moved = dwd_ingest.parse_geography(GEO.replace("20070331;", "20190630;").replace("20070401;20991231", "20190701;20991231"))
    pos = dwd_ingest.station_position(moved, *PERIOD)
    assert pos["positions_in_period"] == 2 and 2000 < pos["max_displacement_m"] < 2500 and pos["lat"] == 52.9336


def test_file_selection_takes_recent_files_only_where_historical_does_not_reach_the_end():
    hist = [
        ("stundenwerte_TU_00001_20000101_20251231_hist.zip", "00001", "20000101", "20251231"),
        ("stundenwerte_TU_00002_20000101_20241231_hist.zip", "00002", "20000101", "20241231"),
        ("stundenwerte_TU_00003_19500101_19991231_hist.zip", "00003", "19500101", "19991231"),
    ]
    recent = [("stundenwerte_TU_00001_akt.zip", "00001"), ("stundenwerte_TU_00002_akt.zip", "00002"), ("stundenwerte_TU_00004_akt.zip", "00004")]
    chosen = dwd_download.select_files(hist, recent, *PERIOD)
    assert chosen == [
        ("historical", "stundenwerte_TU_00001_20000101_20251231_hist.zip"),
        ("historical", "stundenwerte_TU_00002_20000101_20241231_hist.zip"),
        ("recent", "stundenwerte_TU_00002_akt.zip"),
        ("recent", "stundenwerte_TU_00004_akt.zip"),
    ]  # 00003 ended in 1999; 00001's recent file is redundant
    html = '<a href="stundenwerte_TU_00001_20000101_20251231_hist.zip">x</a> <a href="stundenwerte_TU_00004_akt.zip">y</a>'
    h, r = dwd_download.parse_listing(html, "TU")
    assert [x[1] for x in h] == ["00001"] and r == [("stundenwerte_TU_00004_akt.zip", "00004")]


def test_download_and_convert_historical_wins_over_recent_and_output_is_valid(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["meteo"]["products"] = [p for p in cfg["meteo"]["products"] if p["key"] == "tu"]
    cfg["meteo"]["documents"] = []
    base = cfg["meteo"]["base_url"]
    hist_name, recent_name = "stundenwerte_TU_00044_20070401_20241231_hist.zip", "stundenwerte_TU_00044_akt.zip"
    zips = {
        f"{base}/air_temperature/historical/{hist_name}": make_zip(
            "produkt_tu_stunde_20070401_20241231_00044.txt",
            tu_file([("2024123122", 10, 5.0, 90.0), ("2024123123", 10, 4.0, 91.0)]),
        ),
        f"{base}/air_temperature/recent/{recent_name}": make_zip(
            "produkt_tu_stunde_20250101_20261031_00044.txt",
            tu_file([("2024123123", 3, 99.0, 99.0), ("2025010100", 3, 3.0, 92.0), ("2025010101", 3, -999.0, 80.0)]),
        ),
    }
    pages = {
        f"{base}/air_temperature/historical/": f'<a href="{hist_name}">z</a>',
        f"{base}/air_temperature/recent/": f'<a href="{recent_name}">z</a>',
    }

    def fetch(url):
        if url in zips:
            return zips[url]
        if url in pages:
            return pages[url].encode()
        if url.endswith("Beschreibung_Stationen.txt"):
            return b"Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland Abgabe\n"
        raise AssertionError(url)

    raw = tmp_path / "raw"
    manifest, _ = dwd_download.download(cfg, raw, fetch=fetch)
    assert {f.path for f in manifest.files} >= {f"historical/{hist_name}", f"recent/{recent_name}"}
    inventory = dwd_ingest.convert(cfg, raw, tmp_path / "stg")
    assert inventory["zips"] == 2 and inventory["duplicate_rows_dropped"] == 2 and inventory["time_reference_rows_checked"] == 4 and inventory["time_references"] == {"UTC": {"DWD00044:TT_TU", "DWD00044:RF_TU"}}
    dwd_ingest.write_partitions(tmp_path / "stg", tmp_path / "obs")
    assert validate_observations_partitioned(tmp_path / "obs") == []
    df = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{tmp_path / 'obs'}/**/*.parquet', hive_partitioning=true) WHERE feature_name = 'temperature' ORDER BY timestamp_utc"
    ).df()
    by_ts = {t: v for t, v in zip(df["timestamp_utc"], df["value"], strict=True)}
    assert by_ts[pd.Timestamp("2024-12-31T23:00:00Z")] == 4.0  # the historical (quality-controlled) value, not the recent 99.0
    assert by_ts[pd.Timestamp("2025-01-01T00:00:00Z")] == 3.0
    assert pd.isna(by_ts[pd.Timestamp("2025-01-01T01:00:00Z")])
    assert inventory["positions"]["DWD00044"]["lat"] == 52.9336
    _, again = dwd_download.download(cfg, raw, fetch=fetch)
    assert again == []  # idempotent
    # a document added to the config later is fetched alone and the zips stay in the manifest
    cfg["meteo"]["documents"] = [{"path": "docs/terms.pdf", "url": "https://example.test/terms.pdf", "role": "license"}]
    manifest, added = dwd_download.download(cfg, raw, fetch=lambda url: b"terms" if url.endswith("terms.pdf") else fetch(url))
    assert added == ["docs/terms.pdf"] and {f"historical/{hist_name}", f"recent/{recent_name}"} <= {f.path for f in manifest.files}


def test_a_station_whose_clock_is_not_accepted_leaves_no_observations(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["meteo"]["products"] = [p for p in cfg["meteo"]["products"] if p["key"] == "tu"]
    cfg["meteo"]["documents"] = []
    base = cfg["meteo"]["base_url"]
    name = "stundenwerte_TU_00044_20070401_20251231_hist.zip"
    mez = PARAM_HEADER + "".join(
        f"44;20000101;20260418;Gro\xdfenkneten;{col};x;u;SYNOP;Stundenwerte in MEZ;;;eor;\n" for col in ("TT_TU", "RF_TU")
    )
    payload = make_zip("produkt_tu_stunde_20070401_20251231_00044.txt", tu_file([("2019070112", 3, 20.0, 50.0)]), parameter=mez)
    pages = {f"{base}/air_temperature/historical/": f'<a href="{name}">z</a>', f"{base}/air_temperature/recent/": ""}

    def fetch(url):
        if url.endswith(name):
            return payload
        return pages[url].encode() if url in pages else b"Stations_id von_datum\n"

    raw = tmp_path / "raw"
    dwd_download.download(cfg, raw, fetch=fetch)
    inventory = dwd_ingest.convert(cfg, raw, tmp_path / "stg")
    assert inventory["rows_with_refused_time_reference"] == 2 and inventory["rows_kept"] == 0
    assert inventory["time_references"] == {"MEZ": {"DWD00044:TT_TU", "DWD00044:RF_TU"}}
    assert not list((tmp_path / "stg").glob("part-*.parquet"))
