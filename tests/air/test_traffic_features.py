"""Leakage, join and null-semantics tests of the madrid_no2_h6_traffic table, on hand-written observations.

A traffic value encodes its own hour: ``value = 10 * hours_since_t0 + point_offset``; the mean over the contributing
points therefore tells which hour it was read from, and the tests compare that hour with the issue time.
"""

import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.observations import OBSERVATION_SCHEMA
from atlas.domains.air import traffic_features as tf
from atlas.services import layout

A, B = "28079004", "28079008"
START, END = "2023-01-01T00:00:00Z", "2023-02-02T00:00:00Z"
T0 = pd.Timestamp("2022-12-30T00:00:00Z")  # the traffic series starts earlier than the first issue hour
LAST_OBS = pd.Timestamp("2023-02-02T00:00:00Z")


def obs_table(rows):
    cols = {name: [] for name in OBSERVATION_SCHEMA.names}
    for point, ts, value in rows:
        cols["domain"].append("air")
        cols["entity_id"].append(str(point))
        cols["timestamp_utc"].append(ts)
        cols["source_timestamp_local"].append(None)
        cols["timezone"].append("Europe/Madrid")
        cols["feature_name"].append("traffic_intensity")
        cols["value"].append(value)
        cols["unit"].append("veh/h")
        cols["validity_flag"].append("valid" if value is not None else "insufficient_valid_records")
        cols["missing_reason"].append(None if value is not None else "invalid_observation")
        cols["censoring"].append(None)
        cols["source_id"].append("madrid-traffic")
        cols["data_version"].append("test")
        cols["aggregation_window_start_utc"].append(ts)
        cols["aggregation_window_end_utc"].append(ts + pd.Timedelta(hours=1))
        cols["n_records"].append(4 if value is not None else 1)
    return pa.table(cols, schema=OBSERVATION_SCHEMA)


def encode(ts, offset):
    return 10.0 * (ts - T0) / pd.Timedelta(hours=1) + offset


def decode(value, offset=1.5):
    return (T0 + pd.Timedelta(hours=(value - offset) / 10.0)).round("s")


class Scenario:
    """Points 1 and 2 are associated with A in January and February; point 3 only in January; point 9 with nobody
    (it reports but is outside every rule); B has no associated point at all."""

    def __init__(self, tmp_path, *, holes=()):
        self.processed = tmp_path / "air"
        self.traffic = self.processed / "traffic"
        (self.processed / "observations").mkdir(parents=True)
        (self.traffic / "observations").mkdir(parents=True)
        no2 = [(e, T0, "no2", 1.0) for e in (A, B)]
        t = obs_table([(e, ts, v) for e, ts, _f, v in no2])
        t = t.set_column(t.schema.get_field_index("feature_name"), "feature_name", pa.array(["no2"] * t.num_rows))
        pq.write_table(t, self.processed / "observations" / "part.parquet")
        hours = pd.date_range(T0, LAST_OBS, freq="h")
        self.holes = {(p, pd.Timestamp(h)) for p, h in holes}
        rows = []
        for ts in hours:
            for point, offset in ((1, 1.0), (2, 2.0), (3, 3.0), (9, 500.0)):
                value = None if (point, ts) in self.holes else encode(ts, offset)
                rows.append((point, ts, value))
        pq.write_table(obs_table(rows), self.traffic / "observations" / "part.parquet")
        assoc = []
        for month in ("2023-01", "2023-02"):
            for point in (1, 2):
                assoc.append((month, A, point, "urban", f"p{point}", 100.0 * point, point, True))
        assoc.append(("2023-01", A, 3, "urban", "p3", 300.0, 3, True))
        assoc.append(("2023-02", A, 3, "urban", "p3", 700.0, 3, False))  # moved away: no longer in the rule
        assoc.append(("2023-01", A, 9, "urban", "p9", 900.0, 4, False))  # inside the study radius, outside the rule
        cols = ["month", "air_entity_id", "traffic_point_id", "kind", "name", "distance_m", "rank", "in_rule"]
        pd.DataFrame(assoc, columns=cols).to_parquet(self.traffic / "association.parquet", index=False)
        (self.processed / "stations.geojson").write_text(json.dumps({"features": []}))
        self.cfg = tf.load_config()
        self.cfg["grid"] = {"start_utc": START, "end_utc": END}

    def build(self, tmp_path):
        tf.run(
            processed=self.processed,
            traffic_dir=self.traffic,
            out_dir=tmp_path / "feat",
            doc_path=None,
            config=self.cfg,
        )
        return pd.read_parquet(tmp_path / "feat" / "table")


@pytest.fixture
def table(tmp_path):
    sc = Scenario(tmp_path)
    return sc.build(tmp_path)


def station(table, e):
    return table[table["entity_id"] == e].set_index("issued_at_utc")


def mean_offset(key):
    """Mean point offset of the association in the local month of ``key``: points 1, 2, 3 in January, 1, 2 after."""
    return 2.0 if key.tz_convert("Europe/Madrid").month == 1 else 1.5


def test_no_feature_reads_an_unfinished_hour(table):
    a = station(table, A)
    for t, row in a.iterrows():
        key = t - pd.Timedelta(hours=1)
        assert decode(row["traffic_intensity_last"], mean_offset(key)) == key  # the latest FINISHED hour
        assert key + pd.Timedelta(hours=1) <= t  # available at issue time
        if pd.notna(row["traffic_intensity_lag24h"]):
            key24 = t - pd.Timedelta(hours=25)
            assert decode(row["traffic_intensity_lag24h"], mean_offset(key24)) == key24
    # December 2022 has no location file in the scenario, so the first 24 issue hours have no lag24h
    assert a["traffic_intensity_lag24h"].isna().sum() == 24
    assert a["traffic_intensity_lag24h"].iloc[24:].notna().all()


def test_association_membership_follows_each_month(table):
    a = station(table, A)
    jan = a.loc[pd.Timestamp("2023-01-10T12:00:00Z")]
    assert jan["traffic_n_points"] == 3 and jan["traffic_n_associated"] == 3  # points 1, 2, 3; not 9
    feb = a.loc[pd.Timestamp("2023-02-01T12:00:00Z")]
    assert feb["traffic_n_points"] == 2 and feb["traffic_n_associated"] == 2  # point 3 left the rule
    # the point outside the rule (value ~ +500) never contributes
    assert a["traffic_intensity_last"].max() < encode(LAST_OBS, 100.0)
    # the first issue hour reads 2022-12-31T23:00Z, which is local January 1st: it uses the January association
    first = a.iloc[0]
    assert first["traffic_n_associated"] == 3 and first["traffic_n_points"] == 3


def test_mean_ignores_points_without_a_valid_value(tmp_path):
    hole = pd.Timestamp("2023-01-10T11:00:00Z")  # the key hour of t = 12:00Z
    sc = Scenario(tmp_path, holes=[(2, hole), (3, hole)])
    a = station(sc.build(tmp_path), A)
    row = a.loc[pd.Timestamp("2023-01-10T12:00:00Z")]
    assert row["traffic_n_points"] == 1 and row["traffic_n_associated"] == 3
    assert row["traffic_intensity_last"] == pytest.approx(encode(hole, 1.0))  # only point 1 is left
    assert row["traffic_intensity_lag24h"] == pytest.approx(encode(hole - pd.Timedelta(hours=24), 2.0))


def test_missing_stays_null_never_zero(tmp_path):
    hole = pd.Timestamp("2023-01-10T11:00:00Z")
    sc = Scenario(tmp_path, holes=[(p, hole) for p in (1, 2, 3)])
    table = sc.build(tmp_path)
    a, b = station(table, A), station(table, B)
    row = a.loc[pd.Timestamp("2023-01-10T12:00:00Z")]
    assert pd.isna(row["traffic_intensity_last"])  # points exist, none valid: null, not 0
    assert row["traffic_n_points"] == 0 and row["traffic_n_associated"] == 3
    assert (a["traffic_intensity_last"].dropna() > 0).all()
    # B has no associated point: every intensity is null, nothing is borrowed from A or from point 9
    assert b["traffic_intensity_last"].isna().all() and b["traffic_intensity_lag24h"].isna().all()
    assert (b["traffic_n_points"] == 0).all() and (b["traffic_n_associated"] == 0).all()


def test_hours_outside_the_traffic_period_are_null(tmp_path):
    sc = Scenario(tmp_path)
    sc.cfg["grid"] = {"start_utc": "2022-12-29T12:00:00Z", "end_utc": "2023-02-03T00:00:00Z"}
    a = station(sc.build(tmp_path), A)
    before = a.loc[pd.Timestamp("2022-12-29T12:00:00Z")]  # key hour before the first observation
    assert pd.isna(before["traffic_intensity_last"]) and pd.isna(before["traffic_n_points"])
    no_files = a.loc[pd.Timestamp("2022-12-30T12:00:00Z")]  # observed hour, but no location file for December 2022
    assert pd.isna(no_files["traffic_intensity_last"]) and no_files["traffic_n_points"] == 0
    after = a.loc[pd.Timestamp("2023-02-03T00:00:00Z")]  # key hour 2023-02-02T23:00Z is after the last observation
    assert pd.isna(after["traffic_intensity_last"]) and pd.isna(after["traffic_n_points"])


def test_join_with_the_base_table_is_one_to_one(tmp_path):
    sc = Scenario(tmp_path)
    table = sc.build(tmp_path)
    hours = pd.date_range(START, END, freq="h")
    assert len(table) == 2 * len(hours)  # stations x issue hours: nothing multiplied or dropped
    assert not table.duplicated(["entity_id", "issued_at_utc"]).any()
    base = pd.DataFrame(
        [(e, h, 1.0) for e in (A, B) for h in hours], columns=["entity_id", "issued_at_utc", "no2_last"]
    )
    joined = base.merge(table, on=["entity_id", "issued_at_utc"], how="left", validate="one_to_one")
    assert len(joined) == len(base)
    assert joined["traffic_intensity_last"].notna().sum() == table["traffic_intensity_last"].notna().sum()
    assert sorted(set(table["entity_id"])) == [A, B]


def test_feature_spec_follows_the_layout_contract_and_the_committed_file():
    config = tf.load_config()
    spec = layout.FeatureSpec.model_validate(tf.feature_spec(config))  # unit, source_id, lag_hours; extras forbidden
    assert spec.features["traffic_intensity_last"].lag_hours == 1
    assert spec.features["traffic_intensity_lag24h"].lag_hours == 25
    assert all(
        f.source_id == "madrid-traffic" and f.lag_hours >= 1 for f in spec.features.values()
    )  # finished hours only
    assert json.loads(tf.SPEC_PATH.read_text()) == tf.feature_spec(config)  # regenerate with --write-spec if this fails
    cards = {c["name"]: c for c in tf.feature_cards(config)}
    assert (
        cards["traffic_intensity_last"]["lag_hours"] == 1
        and "t-1h" not in cards["traffic_intensity_last"]["available_at"]
    )
    assert [n for n, c in cards.items() if c["recommended"]] == ["traffic_intensity_last", "traffic_intensity_lag24h"]
