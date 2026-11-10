"""AT-041 helpers and the experiment driver, on tiny synthetic data (invented, says nothing about Madrid)."""

import json

import numpy as np
import pandas as pd
import pytest
from ml_helpers import build_rulebase

from atlas.contracts import models as m
from atlas.ml import pipeline
from atlas.ml.evaluation import (
    PeakRss,
    evaluation_slices,
    extreme_rows,
    interpretability_rows,
    period_metric_rows,
    rule_signatures,
    rule_stability,
)
from atlas.ml.experiment import ExperimentConfig, load_data, run_final, run_selection, run_sensitivity
from atlas.ml.feature_spec import feature_spec_from_card
from atlas.ml.split import chronological_split_spec
from atlas.ml.subsample import stratified_subsample
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET


# ------------------------------------------------------------------------------------------ subsample
def _grid(n_entities=3, months=3, per_block=100):
    rows = []
    for e in range(n_entities):
        for mo in range(months):
            start = pd.Timestamp(2020, 1 + mo, 1, tz="UTC")
            n = per_block + 50 * e  # unequal blocks
            stamps = start + pd.to_timedelta(range(n), unit="h")
            rows.append(pd.DataFrame({"entity_id": f"E{e}", "issued_at_utc": stamps}))
    return pd.concat(rows, ignore_index=True)


def test_subsample_is_reproducible_exact_size_and_proportional_per_block():
    t = _grid()
    a = stratified_subsample(t["entity_id"], t["issued_at_utc"], 300, seed=1)
    b = stratified_subsample(t["entity_id"], t["issued_at_utc"], 300, seed=1)
    c = stratified_subsample(t["entity_id"], t["issued_at_utc"], 300, seed=2)
    assert len(a) == 300 and len(set(a)) == 300 and (a == np.sort(a)).all()
    assert (a == b).all() and not (a == c).all()
    month = t["issued_at_utc"].dt.month
    full = t.groupby(["entity_id", month]).size()
    got = t.iloc[a].groupby(["entity_id", month.iloc[a]]).size().reindex(full.index, fill_value=0)
    # same sampling fraction everywhere, up to rounding to whole rows
    assert (got - full * (300 / len(t))).abs().max() < 1.0
    assert (got > 0).all()


def test_subsample_returns_everything_when_asked_for_more_rows_than_exist():
    t = _grid(1, 1, 20)
    assert list(stratified_subsample(t["entity_id"], t["issued_at_utc"], 1000, seed=0)) == list(range(20))
    with pytest.raises(ValueError):
        stratified_subsample(t["entity_id"], t["issued_at_utc"], 0, seed=0)
    with pytest.raises(ValueError, match="timezone"):
        stratified_subsample(t["entity_id"], t["issued_at_utc"].dt.tz_localize(None), 5, seed=0)


# ----------------------------------------------------------------------------------------- evaluation
def test_extreme_rows_count_error_and_event_detection():
    y = np.array([10.0, 50.0, 120.0, 130.0, 20.0])
    p = np.array([12.0, 110.0, 100.0, 90.0, 20.0])
    rows = {r.metric: r for r in extreme_rows("e", y, p, {"ge_100": 100.0}, prefix="validation/")}
    assert {r.slice for r in rows.values()} == {"validation/extreme=ge_100"}
    assert rows["mae"].n == 2 and rows["mae"].value == pytest.approx((20 + 40) / 2)
    assert rows["bias"].value == pytest.approx(-30.0)
    assert rows["event_recall"].value == pytest.approx(0.5)  # 120 -> 100 counts, 130 -> 90 does not
    assert rows["event_precision"].value == pytest.approx(0.5)  # predicted >= 100: rows 1 and 2; only row 2 is an event
    assert extreme_rows("e", y, p, {"ge_500": 500.0}) == []  # no event, no alarm: no rows rather than zeros


def test_period_metric_rows_slices_and_prefix():
    frame = pd.DataFrame({
        "entity_id": ["a", "a", "b", "b"],
        "issued_at_utc": pd.to_datetime(
            ["2025-01-01T00:00Z", "2025-01-01T01:00Z", "2025-02-01T12:00Z", "2025-02-01T13:00Z"]),
    })
    y, p = np.array([1.0, 2.0, 3.0, 5.0]), np.array([1.0, 3.0, 3.0, 4.0])
    rows = period_metric_rows("e", frame, y, p, horizon_hours=6, timezone="Europe/Madrid", thresholds={"hi": 4.0})
    slices = {r.slice for r in rows}
    assert {"all", "entity=a", "entity=b", "month=1", "month=2", "hour=7", "hour=8", "extreme=hi"} <= slices
    assert {r.metric for r in rows if r.slice == "all"} == {"mae", "rmse", "r2", "bias"}
    pref = period_metric_rows("e", frame, y, p, horizon_hours=6, timezone="UTC", thresholds={}, prefix="validation/")
    assert all(r.slice.startswith("validation/") for r in pref)
    # local hour of the *target*: 00:00Z + 6 h = 07:00 in Madrid (CET)
    assert evaluation_slices(frame, 6, "Europe/Madrid")["hour"].tolist() == [7, 8, 19, 20]


def test_interpretability_rows_and_rule_signatures_on_a_hand_built_rulebase():
    rb = build_rulebase([[0, -1], [0, -1], [1, 0]], [10.0, 20.0, 30.0])  # R01 and R02 share their antecedents
    assert rule_signatures(rb) == [(("a", "Low"),), (("a", "Low"),), (("a", "High"), ("b", "Low"))]
    X = np.array([[1.0, 1.0], [9.0, 1.0]])
    rows = interpretability_rows("e", rb, X)
    by = {(r.metric, r.slice): r.value for r in rows}
    assert by[("n_rules", "all")] == 3 and by[("n_duplicate_rules", "all")] == 1
    assert by[("n_distinct_antecedent_sets", "all")] == 2
    assert by[("mean_rule_length", "all")] == pytest.approx(4 / 3)
    assert by[("fraction_fallback", "all")] == 0.0
    assert by[("rule_mean_activation", "rule=R01")] == pytest.approx(0.5)  # Low(a) is 1 at 1, 0 at 9
    assert by[("rule_activation_frequency_tau0.5", "rule=R01")] == 0.5
    assert all(0.0 <= r.value <= 1.0 for r in rows if r.metric.startswith("rule_"))


def test_rule_stability_jaccard_and_found_in_others():
    a, b, c = ("x", "L"), ("y", "H"), ("z", "M")
    out = rule_stability([[(a,), (a, b)], [(a,), (c,)], [(a,)]])
    assert out["pairwise_jaccard"] == pytest.approx([1 / 3, 1 / 2, 1 / 2])
    assert out["reference_found_in_others"] == pytest.approx([0.5, 0.5, 1.0])
    assert out["feature_usage"][0] == {"x": 1.0, "y": 0.5}
    assert rule_stability([[(a,)]])["mean_pairwise_jaccard"] is None


def test_peak_rss_reports_a_positive_size():
    with PeakRss() as rss:
        _ = np.ones(2_000_000)
    assert rss.peak_mb > 0


# ------------------------------------------------------------------------------------- feature spec
def test_feature_spec_from_card_uses_offsets_and_marks_calendar_features():
    card = {"features": [
        {"name": "no2_last", "kind": "no2", "unit": "ug/m3", "source_key_offset_hours": -1},
        {"name": "no2_lag24h", "kind": "no2", "unit": "ug/m3", "source_key_offset_hours": -25},
        {"name": "wind_speed", "kind": "meteo", "unit": "m/s", "source_key_offset_hours": -1},
        {"name": "valid_hour_local", "kind": "calendar", "unit": "h", "source_key_offset_hours": 6},
    ]}
    sources = {"no2": "madrid-air", "meteo": "madrid-meteo"}
    spec = feature_spec_from_card(card, ["no2_lag24h", "wind_speed", "valid_hour_local"], sources)
    f = spec.features
    assert (f["no2_lag24h"].lag_hours, f["no2_lag24h"].source_id) == (25.0, "madrid-air")
    assert (f["wind_speed"].lag_hours, f["wind_speed"].source_id, f["wind_speed"].unit) == (1.0, "madrid-meteo", "m/s")
    assert (f["valid_hour_local"].lag_hours, f["valid_hour_local"].source_id) == (0.0, "calendar")
    with pytest.raises(KeyError):
        feature_spec_from_card(card, ["nope"], {})
    with pytest.raises(KeyError):
        feature_spec_from_card(card, ["wind_speed"], {"no2": "madrid-air"})
    bad = {"features": [{"name": "f", "kind": "no2", "source_key_offset_hours": 2}]}
    with pytest.raises(ValueError, match="<= 0"):
        feature_spec_from_card(bad, ["f"], {"no2": "x"})


# ------------------------------------------------------------------------------------ end to end
@pytest.fixture(scope="module")
def experiment(table):
    table = table.copy()
    table["complete"] = True
    table.loc[table.index[::97], "complete"] = False  # the table's own flag must be honoured
    split = chronological_split_spec(table["issued_at_utc"], horizon_hours=6, embargo_hours=24)
    base = pipeline.RunConfig(
        task_id="synthetic_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u", horizon_hours=6,
        features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t", split=split, seed=3,
        data_version="synthetic-test", synthetic=True, gbm_max_iter=10,
    )
    t0 = table["issued_at_utc"].min()
    config = ExperimentConfig(
        experiment_id="exp-test", table="unused", base=base,
        subsample={"n_rows": 400, "seed": 5},
        selection={"nRules": [4, 6], "nAnts": [2], "n_gen": 3, "pop_size": 10},
        final={"n_gen": 3, "pop_size": 10, "seeds": [0, 1]},
        extremes={"train_quantiles": [0.9], "absolute": [60.0]},
        covid_window_utc=[(t0 + pd.Timedelta(days=2)).isoformat(), (t0 + pd.Timedelta(days=4)).isoformat()],
    )
    return config, table


def test_selection_final_and_sensitivity_on_synthetic_data(experiment, tmp_path, capsys):
    config, table = experiment
    data = load_data(config, frame=table)
    assert not data.complete[~table["complete"].to_numpy()].any()
    out = tmp_path / "exp"
    # --- select: validation only
    selection = run_selection(config, data, out)
    assert len(selection["fits"]) == 2 and selection["chosen"]["nAnts"] == 2
    best = min(selection["fits"], key=lambda f: f["validation"]["rmse"])
    assert selection["chosen"]["nRules"] == best["nRules"]
    assert run_selection(config, data, out)["fits"] == selection["fits"]  # resumable: nothing is refitted
    # --- final
    summary = run_final(config, data, out, tmp_path / "art")
    assert [r["seed"] for r in summary["runs"]] == [0, 1]
    pub = summary["published_run"]
    assert pub["seed"] == min(summary["validation_rmse_by_seed"], key=summary["validation_rmse_by_seed"].get)
    # subsample keys: training period only, complete rows only, the spec's size
    keys = pd.read_parquet(out / "subsample_keys.parquet")
    spec = json.loads((out / "subsample_spec.json").read_text())
    assert len(keys) == spec["n_selected"] == 400
    assert keys["issued_at_utc"].max() < pd.Timestamp(config.base.split.train_to_utc)
    merged = keys.merge(table, on=["entity_id", "issued_at_utc"])
    assert len(merged) == 400 and merged["complete"].all()
    # the published run loads, validates, and reproduces its stored test metrics
    run = pipeline.load_run(pub["run_dir"])
    finite_only = table.assign(**{TARGET: table[TARGET].where(table["complete"])})  # evaluate_run knows no flag
    rows, gap = pipeline.evaluate_run(run, finite_only)
    assert gap is not None and gap < 1e-9
    estimators = {r.estimator for r in run.metrics.rows}
    assert estimators == {"persistence", "climatology", "climatology_global", "ridge", "hist_gradient_boosting",
                          "hist_gradient_boosting_subsample", "exfuzzy"}
    for est in estimators:  # the same split: every estimator scored on the same rows in both periods
        n = {r.slice.startswith("validation/"): r.n for r in run.metrics.rows
             if r.estimator == est and r.metric == "mae" and r.slice in ("all", "validation/all")}
        assert n[False] == summary["n_complete_rows"]["test"] and n[True] == summary["n_complete_rows"]["validation"]
    metric_names = {r.metric for r in run.metrics.rows if r.estimator == "exfuzzy"}
    assert {"n_rules", "mean_rule_length", "n_duplicate_rules", "fraction_fallback", "rule_mean_activation",
            "fit_seconds", "predict_seconds", "predict_ms_single_row", "fit_peak_rss_mb", "model_pkl_bytes",
            "bias"} <= metric_names
    assert run.manifest.hyperparameters["train_subsample"]["n_selected"] == 400
    assert len(summary["rule_stability"]["pairwise_jaccard"]) == 1
    # --- the markdown report comes out of the artifacts
    from atlas.ml import report

    report.main(["--experiment", str(out)])
    text = capsys.readouterr().out
    assert "## Test overall" in text and "## Rules" in text and "| persistence |" in text
    # --- sensitivity
    sens = run_sensitivity(config, data, out)
    assert sens["n_removed"] > 0 and set(sens["estimators"]) == {"hist_gradient_boosting", "exfuzzy"}
    assert sens["estimators"]["exfuzzy"]["test"]["rmse"] > 0
