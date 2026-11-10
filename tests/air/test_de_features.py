"""The Germany table ``de_no2_h6`` keeps the Madrid protocol: same columns, time semantics and leakage guarantees (AT-070).

It reuses the hand-written scenario of ``test_features`` (every observation value encodes its own hour) but builds the
table with the Germany config: Europe/Berlin calendar, 25 km meteorological cap, month-by-month writing.
"""

# ruff: noqa: E501  (long assertions)

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from test_features import FALL, M_NEAR, M_SAME, SPRING, A, B, Scenario

from atlas.domains.air import de_features, features
from atlas.services import layout

REPO = Path(__file__).resolve().parents[2]
DE_CONFIG = REPO / "configs" / "air" / "de_no2_h6.json"


def de_scenario(tmp_path, start, end, *, chunk=True, **kwargs):
    sc = Scenario(tmp_path, start, end, **kwargs)
    sc.cfg = features.load_config(DE_CONFIG)
    sc.cfg["grid"] = {"start_utc": start, "end_utc": end}
    sc.cfg["chunk_by_month"] = chunk
    return sc


def test_the_germany_config_has_the_same_features_as_madrid_with_only_the_territory_changed():
    de, es = features.load_config(DE_CONFIG), features.load_config()
    assert de["features"] == es["features"]  # same names, kinds, key offsets and recommended flags
    assert (de["horizon_hours"], de["grid"]["start_utc"], de["grid"]["end_utc"]) == (6, es["grid"]["start_utc"], es["grid"]["end_utc"])
    assert de["association"]["variables"] == es["association"]["variables"]
    assert de["timezone"] == "Europe/Berlin" and de["task_id"] == "de_no2_h6"
    assert de["association"]["max_distance_m"] == 25000 and es["association"]["max_distance_m"] == 5000


def test_the_feature_spec_has_the_madrid_columns_units_and_lags(tmp_path):
    de_spec = de_features.feature_spec(features.load_config(DE_CONFIG))
    madrid = json.loads((REPO / "configs/ml/madrid_no2_h6_feature_spec.json").read_text())
    assert list(de_spec["features"]) == list(madrid["features"])
    for name, entry in madrid["features"].items():
        assert de_spec["features"][name]["unit"] == entry["unit"] and de_spec["features"][name]["lag_hours"] == entry["lag_hours"]
    assert {e["source_id"] for e in de_spec["features"].values()} == {"eea-air-de", "dwd-meteo-de", "calendar"}
    assert de_spec["schema_version"] == layout.m.SCHEMA_VERSION  # the Madrid file predates 0.4.0; the format is the same
    assert layout.FeatureSpec.model_validate(de_spec)  # the publish step accepts it
    shipped = json.loads((REPO / "configs/air/de_no2_h6_feature_spec.json").read_text()) if (REPO / "configs/air/de_no2_h6_feature_spec.json").exists() else de_spec
    assert shipped == de_spec


@pytest.fixture(params=[FALL, SPRING], ids=["fall-back", "spring-forward"])
def built(request, tmp_path):
    start, end, missing = request.param
    sc = de_scenario(
        tmp_path, start, end, missing_utc=missing,
        skip=[(M_SAME, "temperature", "2024-10-26T23:00:00Z"), (M_NEAR, "wind_speed", "2025-03-30T05:00:00Z")],
    )
    return sc, sc.build(tmp_path), request.param


def test_same_columns_as_the_madrid_table(built, tmp_path):
    _, df, (start, end, missing) = built
    madrid = Scenario(tmp_path / "m", start, end, missing_utc=missing)
    assert list(df.columns) == list(madrid.build(tmp_path / "m").columns)


def test_rows_equal_stations_times_hours_and_valid_at_is_six_elapsed_hours(built):
    _, df, (start, end, _) = built
    hours = len(pd.date_range(start, end, freq="h"))
    assert len(df) == 2 * hours and not df.duplicated(["entity_id", "issued_at_utc"]).any()
    assert ((df["valid_at_utc"] - df["issued_at_utc"]) == pd.Timedelta(hours=6)).all()


def test_calendar_features_follow_the_europe_berlin_wall_clock(built):
    _, df, _ = built
    local = df["valid_at_utc"].dt.tz_convert("Europe/Berlin")
    assert (df["valid_hour_local"] == local.dt.hour).all() and (df["valid_weekday"] == local.dt.dayofweek).all()
    assert df["valid_hour_sin"].notna().all()


def test_inputs_never_read_an_hour_that_had_not_ended_and_the_target_is_never_shifted(built):
    sc, df, (_, _, missing) = built
    one_hour = pd.Timedelta(hours=1)
    gaps = {pd.Timestamp(m) for m in missing}
    for row in df.itertuples():
        for name, back in {"no2_last": 1, "no2_lag1h": 2, "no2_lag3h": 4, "no2_lag24h": 25}.items():
            value = getattr(row, name)
            if not pd.isna(value):
                key = sc.decode(value)
                assert key == row.issued_at_utc - back * one_hour and key + one_hour <= row.issued_at_utc
        if row.valid_at_utc in gaps:
            assert pd.isna(row.target)  # a missing hour is NULL, not a neighbour's value, not 0
        else:
            assert sc.decode(row.target) == row.valid_at_utc
        for name, base in (("wind_speed", 0.0), ("relative_humidity", 0.0), ("pressure", 900.0)):
            value = getattr(row, name)
            if not pd.isna(value):
                assert sc.decode(value, base) + one_hour <= row.issued_at_utc
    assert not (df[["no2_last", "target", "temperature"]] == 0).any().any()


def test_meteo_uses_the_25_km_cap_and_is_null_beyond_it(tmp_path):
    start, end = "2025-03-29T20:00:00Z", "2025-03-30T12:00:00Z"
    sc = de_scenario(tmp_path, start, end, skip=[(M_NEAR, "wind_speed", "2025-03-30T05:00:00Z")])
    df = sc.build(tmp_path)
    a, b = df[df["entity_id"] == A], df[df["entity_id"] == B]
    assert b[["wind_speed", "temperature", "relative_humidity", "pressure"]].isna().all().all()  # B is 44 km from every station
    row = a[a["issued_at_utc"] == pd.Timestamp("2025-03-30T06:00:00Z")].iloc[0]  # reads the 05:00Z hour
    assert sc.decode(row["wind_speed"]) == pd.Timestamp("2025-03-30T05:00:00Z")  # M_FAR (11 km) takes over: within 25 km, beyond Madrid's 5 km
    assert row["meteo_fallback_n"] >= 1
    assoc = json.loads((tmp_path / "feat" / "association.json").read_text())
    assert assoc["max_distance_m"] == 25000 and assoc["candidates"][B]["wind_speed"] is None
    frame = pd.read_parquet(tmp_path / "feat" / "association.parquet")
    assert (frame["distance_m"] <= 25000).all() and set(frame["air_entity_id"]) == {A}


def test_stations_without_a_meteorological_station_within_the_cap_are_listed_with_a_missing_reason():
    association = {
        "max_distance_m": 25000,
        "candidates": {
            "S1": {"wind_speed": [{"rank": 1}], "temperature": [{"rank": 1}]},
            "S2": {"wind_speed": None, "temperature": [{"rank": 1}]},
        },
    }
    out = de_features.annotate_unassociated(association)
    assert out["unassociated"] == {
        "S2": {"wind_speed": {"missing_reason": "no_observation", "detail": "no DWD station that measures wind_speed within 25 km: the input is NULL at every hour"}}
    }


def test_writing_month_by_month_gives_exactly_the_rows_of_a_single_pass(tmp_path):
    start, end = "2025-03-30T20:00:00Z", "2025-04-01T04:00:00Z"  # crosses a month boundary
    kwargs = {"missing_utc": ["2025-03-31T23:00:00Z"], "skip": [(M_NEAR, "wind_speed", "2025-03-31T21:00:00Z")]}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    chunked = de_scenario(tmp_path / "a", start, end, chunk=True, **kwargs).build(tmp_path / "a")
    single = de_scenario(tmp_path / "b", start, end, chunk=False, **kwargs).build(tmp_path / "b")
    pd.testing.assert_frame_equal(chunked.reset_index(drop=True), single.reset_index(drop=True))
    parts = sorted(p.relative_to(tmp_path / "a" / "feat" / "table").as_posix() for p in (tmp_path / "a" / "feat" / "table").rglob("*.parquet"))
    assert parts == ["year=2025/month=3/data_0.parquet", "year=2025/month=4/data_0.parquet"]


def test_plausibility_ranges_come_from_the_config():
    de, es = features.load_config(DE_CONFIG), features.load_config()
    assert "BETWEEN 500 AND 1100" in features.build_table_sql(de, [], []) and "BETWEEN -40 AND 50" in features.build_table_sql(de, [], [])
    assert "BETWEEN 880.0 AND 1000.0" in features.build_table_sql(es, [], []) and "BETWEEN 500" not in features.build_table_sql(es, [], [])


def test_card_texts_name_the_german_sources(tmp_path):
    specs = features.feature_specs(features.load_config(DE_CONFIG))
    by_name = {s["name"]: s for s in specs}
    assert by_name["no2_last"]["source"].startswith("eea-air-de / no2") and by_name["wind_speed"]["source"].startswith("dwd-meteo-de /")
    assert by_name["pressure"]["unit"] == "hPa" and by_name["valid_hour_local"]["source"].endswith("Europe/Berlin")
    assert "Europe/Berlin" in by_name["valid_hour_local"]["definition"] and "Madrid" not in json.dumps(specs)
    assert "Madrid" not in json.dumps(features.feature_specs(features.load_config(DE_CONFIG)))


def test_madrid_cards_are_unchanged_by_the_generalisation():
    specs = features.feature_specs(features.load_config())
    by_name = {s["name"]: s for s in specs}
    assert by_name["no2_last"]["source"] == "madrid-air / no2 (observations, own station)"
    assert by_name["wind_speed"]["source"] == "madrid-meteo / wind_speed (hourly)" and by_name["pressure"]["unit"] == "mbar"
    assert by_name["valid_hour_local"]["source"] == "calendar of valid_at_utc in Europe/Madrid"
    assert "(Europe/Madrid)" in by_name["valid_hour_local"]["definition"]


# ---------------------------------------------------------------------------------------- EAQI and splits


def classify(scheme_path, values):
    scheme = json.loads(scheme_path.read_text())
    con = duckdb.connect()
    con.execute("CREATE TABLE t(target DOUBLE)")
    for v in values:
        con.execute("INSERT INTO t VALUES (?)", [v])
    return [r[0] for r in con.execute(f"SELECT {de_features.band_sql(scheme)} FROM t").fetchall()]


def test_eaqi_bands_for_no2():
    path = REPO / "configs/air/eaqi_no2_scheme.json"
    values = [0, 10, 10.4, 10.5, 11, 25, 25.4, 25.5, 60, 61, 100, 101, 150, 150.4, 150.5, 800, -3.2, None]
    assert classify(path, values) == [
        "Good", "Good", "Good", "Fair", "Fair", "Fair", "Fair", "Moderate", "Moderate", "Poor", "Poor", "Very poor",
        "Very poor", "Very poor", "Extremely poor", "Extremely poor", "Good", None,
    ]


def test_eaqi_thresholds_are_not_those_of_the_spanish_ica():
    eaqi = json.loads((REPO / "configs/air/eaqi_no2_scheme.json").read_text())
    ica = json.loads((REPO / "configs/ml/ica_no2_scheme.json").read_text())
    assert [c["upper"] for c in eaqi["classes"]] == [10, 25, 60, 100, 150, None]
    assert [c["upper"] for c in ica["classes"]] == [40, 90, 120, 230, 340, 1000]
    assert eaqi["equals_ica_no2_madrid"] is False and eaqi["source_url"] == "https://airindex.eea.europa.eu/AQI/index.html"
    assert classify(REPO / "configs/ml/ica_no2_scheme.json", [40, 41, 120, 121]) == ["Buena", "Razonablemente buena", "Regular", "Desfavorable"]
    # 30 ug/m3 is 'Moderate' for the EAQI but 'Buena' for the ICA: class results are not comparable between the two tasks
    assert classify(REPO / "configs/air/eaqi_no2_scheme.json", [30]) == ["Moderate"]
    assert classify(REPO / "configs/ml/ica_no2_scheme.json", [30]) == ["Buena"]


def test_split_windows_follow_the_madrid_protocol():
    config = features.load_config(DE_CONFIG)
    windows = de_features.split_windows(config)
    madrid = json.loads((REPO / "configs/ml/madrid_no2_h6_ica2_justified_experiment.json").read_text())["base"]["split"]
    assert windows == {
        "train": (madrid["train_from_utc"], madrid["train_to_utc"]),
        "validation": (madrid["validation_from_utc"], madrid["validation_to_utc"]),
        "test": (madrid["test_from_utc"], madrid["test_to_utc"]),
    }
    assert config["split"]["embargo_hours"] == madrid["embargo_hours"] == 24
    for earlier, later in (("train", "validation"), ("validation", "test")):
        gap = pd.Timestamp(windows[later][0]) - pd.Timestamp(windows[earlier][1])
        assert gap == pd.Timedelta(hours=24)  # the embargo sits between consecutive periods


def test_attribution_file_is_valid_publish_metadata_with_explicit_licences():
    meta = layout.PublishMetadata.model_validate_json((REPO / "configs/air/attribution_de.json").read_text())
    assert [a.url for a in meta.attribution][:3] == [
        "https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d",
        "https://discomap.eea.europa.eu/map/fme/metadata/PanEuropean_metadata.csv",
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/",
    ]
    assert all(a.license == "CC BY 4.0" for a in meta.attribution) and meta.target_scheme.short_name == "EAQI"
