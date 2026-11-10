"""Longer forecast horizons of the Madrid and Germany NO2 tasks (AT-080): only the horizon (and the grid end) change."""

# ruff: noqa: E501  (long assertions)

import json
from pathlib import Path

import pandas as pd
import pytest
from test_features import SPRING, Scenario

from atlas.domains.air import de_features, features
from atlas.services import layout

REPO = Path(__file__).resolve().parents[2]
HORIZONS = (1, 3, 12, 24)
YDAY = "no2_yday_valid"  # AT-041h: only in the tasks that publish it (Madrid +3/+6/+12 h, Germany +6 h)
LAST_NO2_HOUR = pd.Timestamp("2025-12-31T22:00:00Z")


def cfg(territory: str, h: int) -> dict:
    return features.load_config(REPO / "configs" / "air" / f"{territory}_no2_h{h}.json")


@pytest.mark.parametrize("territory", ["madrid", "de"])
@pytest.mark.parametrize("h", HORIZONS)
def test_a_horizon_config_equals_the_h6_one_except_task_horizon_and_grid_end(territory, h):
    base, new = cfg(territory, 6), cfg(territory, h)
    assert set(base) == set(new)
    for key in set(base) - {"task_id", "data_version", "horizon_hours", "description", "grid", "features"}:
        assert new[key] == base[key], key  # same association cap, split boundaries, embargo and scheme
    # same features, except the AT-041h input "yesterday at the valid hour", whose key follows the horizon
    assert [f for f in new["features"] if f["name"] != YDAY] == [f for f in base["features"] if f["name"] != YDAY]
    for f in new["features"]:
        if f["name"] == YDAY:
            assert f["key_offset_hours"] == h - 24 <= -1 and not f["recommended"]
    assert new["task_id"] == f"{territory}_no2_h{h}" and new["horizon_hours"] == h
    assert new["grid"]["start_utc"] == base["grid"]["start_utc"]
    assert pd.Timestamp(new["grid"]["end_utc"]) + pd.Timedelta(hours=h) == LAST_NO2_HOUR  # the last t whose target exists


@pytest.mark.parametrize("territory, source, meteo", [("madrid", "madrid-air", "madrid-meteo"), ("de", "eea-air-de", "dwd-meteo-de")])
@pytest.mark.parametrize("h", HORIZONS)
def test_the_feature_specs_of_every_horizon_have_the_h6_columns_units_and_lags(territory, source, meteo, h):
    path = REPO / ("configs/ml" if territory == "madrid" else "configs/air") / f"{territory}_no2_h{h}_feature_spec.json"
    old = REPO / ("configs/ml" if territory == "madrid" else "configs/air") / f"{territory}_no2_h6_feature_spec.json"
    spec, ref = json.loads(path.read_text()), json.loads(old.read_text())
    assert layout.FeatureSpec.model_validate(spec)
    assert {k: (v["unit"], v["source_id"], v["lag_hours"]) for k, v in spec["features"].items() if k != YDAY} == {
        k: (v["unit"], v["source_id"], v["lag_hours"]) for k, v in ref["features"].items() if k != YDAY}
    if YDAY in spec["features"]:  # observed 24 h before the valid hour: lag = 24 - h
        assert spec["features"][YDAY] == {"unit": "ug/m3", "source_id": source, "lag_hours": 24.0 - h}
    assert {e["source_id"] for e in spec["features"].values()} == {source, meteo, "calendar"}


@pytest.mark.parametrize("h", [1, 24])
def test_target_valid_time_and_calendar_follow_the_horizon_across_dst(tmp_path, h):
    start, end, missing = SPRING
    sc = Scenario(tmp_path, start, end, missing_utc=missing)
    sc.cfg["horizon_hours"] = h
    df = sc.build(tmp_path)
    assert ((df["valid_at_utc"] - df["issued_at_utc"]) == pd.Timedelta(hours=h)).all()
    local = df["valid_at_utc"].dt.tz_convert("Europe/Madrid")
    assert (df["valid_hour_local"] == local.dt.hour).all() and (df["valid_weekday"] == local.dt.dayofweek).all()
    known = df[df["target"].notna()]
    assert len(known) > 0
    for row in known.itertuples():
        assert sc.decode(row.target) == row.valid_at_utc  # the observation at t + h, never a neighbour's
    for row in df.itertuples():  # inputs stay on hours that ended by the issue time, whatever the horizon
        if not pd.isna(row.no2_last):
            assert sc.decode(row.no2_last) == row.issued_at_utc - pd.Timedelta(hours=1)


@pytest.mark.parametrize("h", [1, 24])
def test_the_feature_card_states_the_horizon_not_six_hours(tmp_path, h):
    start, end, _ = SPRING
    sc = Scenario(tmp_path, start, end)
    sc.cfg["horizon_hours"] = h
    sc.build(tmp_path)
    card = json.loads((tmp_path / "feat" / "feature_card.json").read_text())
    assert f"t+{h}h" in card["time_convention"] and card["other_columns"]["valid_at_utc"] == f"issued_at_utc + {h}h"


def test_the_germany_builder_takes_another_horizon_without_touching_the_h6_files(monkeypatch):
    seen = {}
    monkeypatch.setattr(de_features, "run", lambda **kw: seen.update(kw) or {"card": {"rows": {"total": 1}}, "summary": {"per_year": [{"complete": 1}]}})
    de_features.main(["--config", str(REPO / "configs/air/de_no2_h3.json")])
    assert seen["spec_path"] == REPO / "configs/air/de_no2_h3_feature_spec.json" and seen["doc_path"] is None
    de_features.main([])
    assert seen["spec_path"] == de_features.SPEC_PATH and seen["doc_path"] == de_features.DOC_PATH and seen["config_path"] is None
