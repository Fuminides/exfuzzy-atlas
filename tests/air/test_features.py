"""Leakage and alignment tests for the madrid_no2_h6 feature table, on hand-written observations.

Every observation value encodes its own hour (``value = 0.25 * hours_since_t0`` plus a per-source offset), so a
feature value tells which timestamp it was read from and the tests can check that source against the issue time.
"""

import json
import math

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.observations import OBSERVATION_SCHEMA
from atlas.domains.air import features
from atlas.domains.air.association import Point, build_association

A, B = "28079004", "28079008"
P0 = (-3.7122567, 40.4238823)
M_SAME, M_NEAR, M_FAR = "28079004", "28079102", "28079106"
# ~1.1 km north of P0; ~44 km east of P0 (B); ~11 km north of P0
COORDS_AIR = {A: P0, B: (P0[0] + 0.5, P0[1])}
COORDS_METEO = {M_SAME: P0, M_NEAR: (P0[0], P0[1] + 0.01), M_FAR: (P0[0], P0[1] + 0.1)}
OFFSET = {"temperature@" + M_SAME: 0.0, "temperature@" + M_NEAR: 10.0, "pressure": 900.0}


def table(rows):
    cols = {name: [] for name in OBSERVATION_SCHEMA.names}
    for entity, ts, feature, value, source in rows:
        cols["domain"].append("air")
        cols["entity_id"].append(entity)
        cols["timestamp_utc"].append(ts)
        cols["source_timestamp_local"].append(None)
        cols["timezone"].append("Europe/Madrid")
        cols["feature_name"].append(feature)
        cols["value"].append(value)
        cols["unit"].append("u")
        cols["validity_flag"].append("V" if value is not None else "N")
        cols["missing_reason"].append(None if value is not None else "invalid_observation")
        cols["censoring"].append(None)
        cols["source_id"].append(source)
        cols["data_version"].append("test")
        cols["aggregation_window_start_utc"].append(None)
        cols["aggregation_window_end_utc"].append(None)
        cols["n_records"].append(None)
    return pa.table(cols, schema=OBSERVATION_SCHEMA)


def stations_geojson(path, coords, names=None):
    path.write_text(
        json.dumps(
            {
                "features": [
                    {"id": e, "geometry": {"type": "Point", "coordinates": list(c)}, "properties": {"name": e}}
                    for e, c in coords.items()
                ]
            }
        )
    )


class Scenario:
    """Observations on a regular UTC grid with chosen holes; encodes ``value`` from the hour index."""

    def __init__(self, tmp_path, start, end, *, missing_utc=(), skip=(), extra_excluded=(), anomalies=None):
        self.t0 = pd.Timestamp(start, tz="UTC") - pd.Timedelta(hours=48)
        hours = pd.date_range(self.t0, pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=10), freq="h")
        self.processed = tmp_path / "air"
        (self.processed / "meteo" / "observations").mkdir(parents=True)
        (self.processed / "observations").mkdir()
        missing = {pd.Timestamp(m, tz="UTC") for m in missing_utc}
        self.missing_for = {(e, f, pd.Timestamp(t, tz="UTC")) for e, f, t in skip}
        air, met = [], []
        for e in (A, B):
            for ts in hours:
                if ts in missing:
                    continue
                air.append((e, ts, "no2", self.encode(ts), "madrid-air"))
        for m in (M_SAME, M_NEAR, M_FAR):
            for name in ("temperature", "relative_humidity", "wind_speed", "pressure"):
                if (name == "temperature" and m == M_FAR) or (m == M_FAR and name != "wind_speed"):
                    continue
                if m == M_SAME and name not in ("temperature", "relative_humidity"):
                    continue
                if m == M_NEAR and name == "relative_humidity":
                    continue
                for ts in hours:
                    if ts in missing or (m, name, ts) in self.missing_for:
                        continue
                    met.append((m, ts, name, self.meteo_value(m, name, ts), "madrid-meteo"))
        pq.write_table(table(air), self.processed / "observations" / "part.parquet")
        pq.write_table(table(met), self.processed / "meteo" / "observations" / "part.parquet")
        stations_geojson(self.processed / "stations.geojson", COORDS_AIR)
        stations_geojson(self.processed / "meteo" / "stations.geojson", COORDS_METEO)
        details = {"data_version": "t", "sha256": {}, "dst_anomalies": anomalies or {}}
        (self.processed / "ingest_details.json").write_text(json.dumps(details))
        (self.processed / "meteo" / "ingest_details.json").write_text(json.dumps({**details, "dst_anomalies": {}}))
        self.cfg = features.load_config()
        self.cfg["grid"] = {"start_utc": start, "end_utc": end}
        self.extra_excluded = list(extra_excluded)

    def encode(self, ts):
        return 0.25 * (ts - self.t0) / pd.Timedelta(hours=1)

    def meteo_value(self, m, name, ts):
        return self.encode(ts) + OFFSET.get(f"{name}@{m}", OFFSET.get(name, 0.0))

    def decode(self, value, base=0.0):
        return self.t0 + pd.Timedelta(hours=(value - base) / 0.25)

    def build(self, tmp_path):
        features.run(
            processed=self.processed,
            out_dir=tmp_path / "feat",
            doc_path=None,
            config=self.cfg,
            extra_excluded=self.extra_excluded,
        )
        con = duckdb.connect()
        con.execute("SET TimeZone='UTC'")
        df = (
            con.execute(
                f"SELECT * FROM read_parquet('{tmp_path / 'feat'}/table/**/*.parquet', hive_partitioning=true) "
                "ORDER BY entity_id, issued_at_utc"
            )
            .to_arrow_table()
            .to_pandas()
        )
        return df


# 2024-10-27: clocks go back at 01:00Z (03:00 CEST -> 02:00 CET). The repeated hour has no source slot, so 01:00Z is
# absent in every series.  2025-03-30: clocks go forward at 01:00Z (02:00 CET -> 03:00 CEST).
FALL = ("2024-10-26T20:00:00Z", "2024-10-27T12:00:00Z", ["2024-10-27T01:00:00Z"])
SPRING = ("2025-03-29T20:00:00Z", "2025-03-30T12:00:00Z", [])


@pytest.fixture(params=[FALL, SPRING], ids=["fall-back", "spring-forward"])
def built(request, tmp_path):
    start, end, missing = request.param
    sc = Scenario(
        tmp_path,
        start,
        end,
        missing_utc=missing,
        skip=[(M_SAME, "temperature", "2024-10-26T23:00:00Z"), (M_NEAR, "wind_speed", "2025-03-30T05:00:00Z")],
    )
    return sc, sc.build(tmp_path), request.param


def test_rows_equal_stations_times_hours(built):
    sc, df, (start, end, _) = built
    hours = len(pd.date_range(start, end, freq="h"))
    assert len(df) == 2 * hours  # no join multiplied or dropped rows
    assert not df.duplicated(["entity_id", "issued_at_utc"]).any()
    assert df.groupby("entity_id").size().eq(hours).all()
    assert str(df["issued_at_utc"].dt.tz) == "UTC"


def test_valid_at_is_exactly_six_elapsed_hours_across_dst(built):
    _, df, _ = built
    assert ((df["valid_at_utc"] - df["issued_at_utc"]) == pd.Timedelta(hours=6)).all()
    # the local hour of the target follows the wall clock, not a naive +6
    local = df["valid_at_utc"].dt.tz_convert("Europe/Madrid")
    assert (df["valid_hour_local"] == local.dt.hour).all()
    assert (df["valid_weekday"] == local.dt.dayofweek).all()


def test_target_is_the_observation_at_plus_six_hours_and_never_shifted(built):
    sc, df, (_, _, missing) = built
    gaps = {pd.Timestamp(m) for m in missing}
    for row in df.itertuples():
        if row.valid_at_utc in gaps:
            assert pd.isna(row.target), "a missing target hour must stay null, not take a neighbour's value"
        else:
            assert sc.decode(row.target) == row.valid_at_utc


def test_inputs_come_from_hours_that_ended_at_or_before_the_issue_time(built):
    sc, df, _ = built
    one_hour = pd.Timedelta(hours=1)
    expected_no2 = {"no2_last": 1, "no2_lag1h": 2, "no2_lag3h": 4, "no2_lag24h": 25}
    for row in df.itertuples():
        for name, back in expected_no2.items():
            value = getattr(row, name)
            if pd.isna(value):
                continue
            key = sc.decode(value)
            assert key == row.issued_at_utc - back * one_hour
            assert key + one_hour <= row.issued_at_utc  # the hour was complete when the forecast was issued
        for name, base in (("wind_speed", 0.0), ("relative_humidity", 0.0), ("pressure", 900.0)):
            value = getattr(row, name)
            if not pd.isna(value):
                assert sc.decode(value, base) + one_hour <= row.issued_at_utc


def test_yesterday_at_the_valid_hour_is_the_hour_24h_before_the_target_and_finished_at_issue(built):
    """AT-041h: ``no2_yday_valid`` reads the key ``valid_at - 24h`` (= ``t - 18h`` at h6), never a later hour."""
    sc, df, _ = built
    one_hour = pd.Timedelta(hours=1)
    seen = 0
    for row in df.itertuples():
        if pd.isna(row.no2_yday_valid):
            continue
        key = sc.decode(row.no2_yday_valid)
        assert key == row.valid_at_utc - 24 * one_hour == row.issued_at_utc - 18 * one_hour
        assert key + one_hour <= row.issued_at_utc
        seen += 1
    assert seen > 0


def test_yesterday_at_the_valid_hour_does_not_enter_complete(tmp_path):
    """It is an extra input of some models (in the spec), not a recommended feature: ``complete`` ignores it."""
    start, end, _ = SPRING
    hole = pd.Timestamp(start) - pd.Timedelta(hours=4)  # only rows issued at hole + 18 h lack it among their inputs
    sc = Scenario(tmp_path, start, end, missing_utc=[hole.isoformat()])
    df = sc.build(tmp_path).set_index("issued_at_utc")
    row = df[df["entity_id"] == A].loc[hole + pd.Timedelta(hours=18)]
    assert pd.isna(row["no2_yday_valid"]) and pd.notna(row["no2_last"]) and bool(row["complete"])
    card = json.loads((tmp_path / "feat" / "feature_card.json").read_text())
    assert "no2_yday_valid" not in card["recommended_features"]
    entry = next(f for f in card["features"] if f["name"] == "no2_yday_valid")
    assert entry["source_key_offset_hours"] == -18 and "valid_at_utc - 24h" in entry["definition"]


@pytest.mark.parametrize("h", [3, 12])
def test_yesterday_at_the_valid_hour_follows_the_horizon(tmp_path, h):
    start, end, _ = SPRING
    sc = Scenario(tmp_path, start, end)
    sc.cfg = {**features.load_config(features.REPO_ROOT / "configs" / "air" / f"madrid_no2_h{h}.json"),
              "grid": sc.cfg["grid"]}
    df = sc.build(tmp_path)
    known = df[df["no2_yday_valid"].notna()]
    assert len(known) > 0
    for row in known.itertuples():
        key = sc.decode(row.no2_yday_valid)
        assert key == row.valid_at_utc - pd.Timedelta(hours=24) and key + pd.Timedelta(hours=1) <= row.issued_at_utc


def test_missing_hours_give_null_never_zero(built):
    sc, df, (_, _, missing) = built
    for m in missing:
        t = pd.Timestamp(m)
        late = df[df["issued_at_utc"] == t + pd.Timedelta(hours=1)]  # its latest complete hour is the hole
        assert late["no2_last"].isna().all()
        assert late["no2_lag1h"].notna().all()
    numeric = df[["target", "no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "temperature"]]
    assert (numeric.fillna(1) > 0).all().all()  # 0 would mean a missing value was filled


def test_meteo_association_distance_limit_fallback_and_provenance(built):
    sc, df, _ = built
    a = df[df["entity_id"] == A]
    b = df[df["entity_id"] == B]
    assert b[["wind_speed", "temperature", "relative_humidity", "pressure"]].isna().all().all()  # 44 km from everything
    # wind: only M_NEAR is within 5 km of A; M_FAR (11 km) exists but must never fill the hole
    hole = a[a["issued_at_utc"] == pd.Timestamp("2025-03-30T06:00:00Z")]
    if len(hole):
        assert hole["wind_speed"].isna().all()
    assert a["wind_speed"].dropna().between(0, 50).all()
    # temperature: primary is the station with the same code (value = idx/4), M_NEAR (value + 10) is the fallback
    t_fall = a[a["issued_at_utc"] == pd.Timestamp("2024-10-27T00:00:00Z")]
    if len(t_fall):
        assert sc.decode(t_fall["temperature"].iloc[0], 10.0) == pd.Timestamp("2024-10-26T23:00:00Z")
        assert t_fall["meteo_fallback_n"].iloc[0] == 1
    normal = a[a["issued_at_utc"] == a["issued_at_utc"].iloc[8]]
    if normal["meteo_fallback_n"].iloc[0] == 0:
        assert sc.decode(normal["temperature"].iloc[0]) == normal["issued_at_utc"].iloc[0] - pd.Timedelta(hours=1)
    assoc = pd.read_parquet(sc.processed / ".." / "feat" / "association.parquet")
    assert (assoc["distance_m"] <= 5000).all()
    wind = assoc[(assoc["air_entity_id"] == A) & (assoc["variable"] == "wind_speed")]
    assert wind["meteo_entity_id"].tolist() == [M_NEAR]
    same = assoc[(assoc["air_entity_id"] == A) & (assoc["variable"] == "temperature")]
    assert same["meteo_entity_id"].tolist() == [M_SAME, M_NEAR] and bool(same["same_station_code"].iloc[0])
    assert same["distance_m"].iloc[0] == 0.0 and not bool(same["same_station_code"].iloc[1])
    assert B not in set(assoc["air_entity_id"])


def test_excluded_local_day_is_nulled_and_flagged(tmp_path):
    sc = Scenario(tmp_path, "2025-03-29T20:00:00Z", "2025-04-01T06:00:00Z", extra_excluded=["2025-03-30"])
    df = sc.build(tmp_path)
    day = df[(df["entity_id"] == A)].set_index("issued_at_utc")
    # 2025-03-30 local day = [2025-03-29T23:00Z, 2025-03-30T22:00Z)
    inside = pd.Timestamp("2025-03-30T10:00:00Z")
    assert pd.isna(day.loc[inside, "no2_last"]) and pd.isna(day.loc[inside, "target"])
    assert bool(day.loc[inside, "excluded_day_window"]) and not bool(day.loc[inside, "complete"])
    far = pd.Timestamp("2025-04-01T00:00:00Z")  # window [t-25h, t+7h) starts after the excluded day ended
    assert not bool(day.loc[far, "excluded_day_window"])
    # the day after: lag24h would read the excluded day, and is null; the rest of the row is intact
    next_day = pd.Timestamp("2025-03-31T10:00:00Z")
    assert bool(day.loc[next_day, "excluded_day_window"]) and pd.isna(day.loc[next_day, "no2_lag24h"])
    assert not pd.isna(day.loc[next_day, "no2_last"])


def test_complete_requires_every_recommended_feature_and_the_target(tmp_path):
    sc = Scenario(tmp_path, "2025-03-29T20:00:00Z", "2025-03-30T20:00:00Z")
    df = sc.build(tmp_path)
    required = sc.cfg["features"]
    names = [f["name"] for f in required if f["recommended"]]
    manual = df[names + ["target"]].notna().all(axis=1) & ~df["excluded_day_window"]
    assert (df["complete"] == manual).all()
    # station A has everything after the first 25 hours; B never has meteo, so never complete
    assert df[df["entity_id"] == A]["complete"].sum() > 0 and not df[df["entity_id"] == B]["complete"].any()


def test_build_association_never_returns_a_station_beyond_the_limit():
    air = [Point("a", 0.0, 40.0)]
    meteo = [Point("near", 0.0, 40.01), Point("edge", 0.0, 40.04), Point("far", 0.0, 40.2)]  # 1.1, 4.4, 22 km
    hours = {(m.entity_id, "temperature"): 10 for m in meteo}
    rows = build_association(air, meteo, hours, ["temperature", "wind_speed"], max_distance_m=5000)
    assert [(r["meteo_entity_id"], r["rank"]) for r in rows] == [("near", 1), ("edge", 2)]
    assert all(r["distance_m"] <= 5000 for r in rows)
    assert build_association(air, meteo, hours, ["temperature"], max_distance_m=1500)[0]["meteo_entity_id"] == "near"
    assert build_association(air, meteo, hours, ["temperature"], max_distance_m=500) == []  # honest: no candidate
    # a station that does not measure the variable is never a candidate, however close
    only_far = {("far", "temperature"): 5}
    assert build_association(air, meteo, only_far, ["temperature"], max_distance_m=5000) == []


def test_real_config_is_small_and_reads_only_complete_hours():
    cfg = features.load_config()
    specs = features.feature_specs(cfg)
    recommended = [s for s in specs if s["recommended"]]
    assert 6 <= len(recommended) <= 10
    assert cfg["horizon_hours"] == 6
    for feat in cfg["features"]:
        if feat["kind"] in ("no2", "meteo"):
            assert feat["key_offset_hours"] <= -1  # key + 1h <= issued_at
    last_no2 = pd.Timestamp("2025-12-31T22:00:00Z")  # last hour of the ingested NO2 series
    assert pd.Timestamp(cfg["grid"]["end_utc"]) + pd.Timedelta(hours=cfg["horizon_hours"]) <= last_no2
    # binary flags and constant-ish columns are not recommended to the rule learner
    assert not any(s["name"] == "valid_is_weekend" for s in recommended)
    assert math.isfinite(cfg["association"]["max_distance_m"])
