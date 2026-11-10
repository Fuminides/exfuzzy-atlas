"""AT-041c: ICA scheme, class sampling, classification metrics, the winning-rule classifier and its engine.

Synthetic data only (invented, says nothing about Madrid), except the scheme tests, which read the committed
``configs/ml/ica_no2_scheme.json``.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atlas.explain.classifier import (
    UnsupportedModelError,
    compute_classifier_activations,
    get_master_rulebase,
    rule_classes,
    rule_ids,
    rule_weights,
)
from atlas.ml.class_baselines import ClimatologyMajorityClass, PersistenceClass, RegressionThenBinned
from atlas.ml.classification import (
    ClassScheme,
    class_counts,
    class_sample,
    classification_metric_rows,
    classification_metrics,
    confusion_matrix,
    load_scheme,
)
from atlas.ml.evaluation import classifier_readability_rows, classifier_rule_sets, rule_set_stability
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

SCHEME_PATH = Path(__file__).resolve().parents[2] / "configs" / "ml" / "ica_no2_scheme.json"


@pytest.fixture(scope="module")
def ica() -> ClassScheme:
    return load_scheme(SCHEME_PATH)


# ---------------------------------------------------------------------------------------------- scheme


def test_committed_scheme_is_the_official_no2_table(ica):
    assert ica.unit == "ug/m3" and ica.source_url.startswith("https://www.miteco.gob.es/")
    assert [(c.label, c.lower, c.upper) for c in ica.classes] == [
        ("Buena", 0, 40), ("Razonablemente buena", 41, 90), ("Regular", 91, 120),
        ("Desfavorable", 121, 230), ("Muy desfavorable", 231, 340), ("Extremadamente desfavorable", 341, 1000),
    ]
    assert [c.color for c in ica.classes] == ["#00FFFF", "#00B050", "#FFCC00", "#FF3300", "#990000", "#9900FF"]
    assert set(json.loads(SCHEME_PATH.read_text())) >= {"name", "source_url", "unit", "classes", "accessed"}


def test_classify_uses_inclusive_whole_number_bands(ica):
    values = [0, 40, 41, 90, 91, 120, 121, 230, 231, 340, 341, 1000]
    assert ica.classify(values).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    # non-integers are rounded half up to a whole number first
    assert ica.classify([40.4, 40.5, 90.49, 120.5]).tolist() == [0, 1, 1, 3]
    # outside the scheme or missing: -1, never a class
    assert ica.classify([-1, 1001, np.nan, np.inf]).tolist() == [-1, -1, -1, -1]


def test_merge_rare_upper_tail_keeps_thresholds_and_only_merges_from_the_top(ica):
    merged = ica.merge_rare_upper_tail([683216, 207285, 20750, 7323, 27, 0], 500)
    assert merged.labels == ["Buena", "Razonablemente buena", "Regular", "Desfavorable o peor"]
    last = merged.classes[-1]
    assert (last.lower, last.upper) == (121, 1000)
    assert last.merged_from == ["Desfavorable", "Muy desfavorable", "Extremadamente desfavorable"]
    assert [(c.lower, c.upper) for c in merged.classes[:3]] == [(0, 40), (41, 90), (91, 120)]
    # the merged scheme classifies the same values the official one does, collapsed
    v = np.array([5, 60, 100, 150, 300, 500])
    assert merged.classify(v).tolist() == np.minimum(ica.classify(v), 3).tolist()
    # a rare class in the middle is NOT merged (the rule only looks from the top)
    assert ica.merge_rare_upper_tail([1000, 10, 1000, 1000, 1000, 1000], 500).labels == ica.labels
    assert ica.merge_rare_upper_tail([1000, 1000, 1000, 1000, 1000, 3], 500).labels[-1] == "Muy desfavorable o peor"
    with pytest.raises(ValueError):
        ica.merge_rare_upper_tail([1, 2], 5)


# ---------------------------------------------------------------------------------------------- sampling


def _rows(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.choice(4, n, p=[0.7, 0.2, 0.08, 0.02])
    stamps = pd.DatetimeIndex(pd.Timestamp("2020-01-01", tz="UTC") + pd.to_timedelta(rng.permutation(n), unit="h"))
    return y, rng.choice(["A", "B", "C"], n), stamps


def test_class_sample_follows_the_power_and_is_reproducible():
    y, e, t = _rows()
    nat = class_sample(y, e, t, 1000, seed=1, power=1.0)
    sq = class_sample(y, e, t, 1000, seed=1, power=0.5)
    bal = class_sample(y, e, t, 1000, seed=1, power=0.0)
    assert (class_sample(y, e, t, 1000, seed=1, power=0.5) == sq).all()
    assert all(len(s) == 1000 and len(set(s)) == 1000 for s in (nat, sq, bal))
    cn, cs, cb = (np.bincount(y[s], minlength=4) for s in (nat, sq, bal))
    assert np.abs(cn / 1000 - [0.7, 0.2, 0.08, 0.02]).max() < 0.02
    assert cb[3] == class_counts(y, 4)[3] or cb.min() >= 100  # balanced: rare class strongly up-weighted
    assert cn[3] < cs[3] < cb[3] and cn[0] > cs[0] > cb[0]


def test_class_sample_takes_a_whole_small_class_and_redistributes_the_rest():
    y, e, t = _rows()
    y = np.where(np.arange(len(y)) < 30, 3, np.where(y == 3, 2, y))  # class 3 has exactly 30 rows
    picked = class_sample(y, e, t, 1000, seed=0, power=0.0)
    counts = np.bincount(y[picked], minlength=4)
    assert counts[3] == 30 and len(picked) == 1000
    assert counts[:3].min() > 300


# ---------------------------------------------------------------------------------------------- metrics


def test_classification_metrics_by_hand():
    y = np.array([0, 0, 0, 0, 1, 1, 2, 2, 3])
    p = np.array([0, 0, 1, -1, 1, 3, 2, 0, 3])
    r = classification_metrics(y, p, 4)
    cm = confusion_matrix(y, p, 4)
    assert cm.tolist() == [[2, 1, 0, 0, 1], [0, 1, 0, 1, 0], [1, 0, 1, 0, 0], [0, 0, 0, 1, 0]]
    assert r["accuracy"] == pytest.approx(5 / 9)
    assert r["recall"].tolist() == pytest.approx([0.5, 0.5, 0.5, 1.0])
    assert r["precision"].tolist() == pytest.approx([2 / 3, 0.5, 1.0, 0.5])
    assert r["balanced_accuracy"] == pytest.approx(0.625)
    f1 = [2 * (2 / 3) * 0.5 / (2 / 3 + 0.5), 0.5, 2 * 1.0 * 0.5 / 1.5, 2 * 0.5 * 1.0 / 1.5]
    assert r["macro_f1"] == pytest.approx(np.mean(f1))
    assert r["share_unknown"] == pytest.approx(1 / 9)
    # ordinal metrics ignore the unknown row: gaps 0,0,1,0,2,0,2,0
    assert r["mae_class_index"] == pytest.approx(5 / 8) and r["share_off_by_2plus"] == pytest.approx(2 / 8)


def test_classes_absent_from_the_truth_are_left_out_of_macro_averages():
    r = classification_metrics(np.array([0, 0, 1]), np.array([0, 2, 1]), 3)
    assert r["macro_f1"] == pytest.approx(np.mean([r["f1"][0], r["f1"][1]]))
    assert np.isnan(r["recall"][2]) and r["precision"][2] == 0.0


def test_metric_rows_names_and_slices():
    labels = ["Buena", "Regular"]
    y, p = np.array([0, 0, 1, 1]), np.array([0, 1, 1, 1])
    slices = {"entity": np.array(["a", "a", "b", "b"])}
    rows = classification_metric_rows("est", y, p, labels, slices, prefix="validation/")
    got = {(r.metric, r.slice): r for r in rows}
    assert got[("recall[Regular]", "validation/all")].value == 1.0 and got[("recall[Regular]", "validation/all")].n == 2
    assert got[("confusion[Buena>Regular]", "validation/all")].value == 1.0
    assert ("macro_f1", "validation/entity=b") in got and got[("accuracy", "validation/entity=a")].value == 0.5
    assert ("confusion[Buena>no_prediction]", "validation/all") in got


# ---------------------------------------------------------------------------------------------- baselines


def _frame(n=4000):
    rng = np.random.default_rng(3)
    stamps = pd.Timestamp("2021-03-01", tz="UTC") + pd.to_timedelta(np.arange(n), unit="h")
    return pd.DataFrame({"entity_id": np.where(np.arange(n) % 2, "E0", "E1"), "issued_at_utc": stamps,
                         "x": rng.gamma(2, 20, n)})


def test_persistence_class_classifies_the_current_value(ica):
    f = _frame()
    assert PersistenceClass("x", ica).fit(f, None).predict(f).tolist() == ica.classify(f["x"]).tolist()


def test_climatology_majority_class_uses_the_valid_time_and_falls_back(ica):
    f = _frame()
    valid_hour = (f["issued_at_utc"] + pd.Timedelta(hours=6)).dt.tz_convert("Europe/Madrid").dt.hour
    y = np.where(valid_hour.to_numpy() < 12, 0, 2)
    clim = ClimatologyMajorityClass(6, "Europe/Madrid", 4).fit(f, y)
    assert (clim.predict(f) == y).all()
    unseen = f.iloc[:3].assign(entity_id="NEW")
    assert (clim.predict(unseen) == clim.global_).all()


def test_regression_then_binned_needs_values_and_bins_with_the_scheme(ica):
    from sklearn.linear_model import LinearRegression

    f = _frame()
    base = RegressionThenBinned("r", LinearRegression(), ["x"], ica)
    with pytest.raises(ValueError):
        base.fit(f, None)
    base.values = f["x"].to_numpy() * 1.0
    pred = base.fit(f, None).predict(f)
    assert (pred == ica.classify(f["x"])).all()


def _separable(n=600, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 2))
    y = np.digitize(x[:, 0] * 3 + rng.normal(0, 0.3, n), [-1, 1])  # 3 ordered classes
    return pd.DataFrame({"a": x[:, 0] * 50 + 100, "b": x[:, 1]}), y  # very different input scales


def test_logistic_regression_baseline_standardises_and_balanced_weights_the_rare_class():
    from atlas.ml.class_baselines import logistic_regression_baseline

    f, y = _separable()
    plain = logistic_regression_baseline("lr", ["a", "b"]).fit(f, y)
    assert (plain.predict(f) == y).mean() > 0.9 and plain.predict(f).dtype.kind == "i"
    scaler = plain.estimator[0]
    assert np.allclose(scaler.mean_, f.mean().to_numpy()) and np.allclose(scaler.scale_, f.std(ddof=0).to_numpy())
    # a rare class: balanced weights predict it more often than the plain fit
    y_rare = np.where(np.arange(len(y)) % 40 == 0, 2, np.minimum(y, 1))
    f_rare = f.copy()
    f_rare.loc[y_rare == 2, "b"] += 1.0
    plain = logistic_regression_baseline("lr", ["a", "b"]).fit(f_rare, y_rare)
    balanced = logistic_regression_baseline("lrb", ["a", "b"], balanced=True).fit(f_rare, y_rare)
    assert (balanced.predict(f_rare) == 2).sum() > (plain.predict(f_rare) == 2).sum()


def test_random_forest_baseline_is_reproducible_and_respects_its_settings():
    from atlas.ml.class_baselines import random_forest_baseline

    f, y = _separable()
    kw = {"n_estimators": 20, "min_samples_leaf": 5, "n_jobs": 1}
    a = random_forest_baseline("rf", ["a", "b"], seed=3, max_samples=300, **kw).fit(f, y)
    b = random_forest_baseline("rf", ["a", "b"], seed=3, max_samples=300, **kw).fit(f, y)
    assert (a.predict(f) == b.predict(f)).all() and (a.predict(f) == y).mean() > 0.9
    forest = a.estimator
    assert forest.n_estimators == 20 and forest.min_samples_leaf == 5 and forest.max_samples == 300
    assert forest.class_weight is None
    assert random_forest_baseline("rfb", ["a", "b"], balanced=True).estimator.class_weight == "balanced_subsample"
    default = random_forest_baseline("rf", ["a", "b"]).estimator
    assert (default.n_estimators, default.min_samples_leaf, default.n_jobs) == (300, 20, 4)


# ---------------------------------------------------------------------------------------------- classifier


@pytest.fixture(scope="module")
def classifier_data(complete_rows):
    rows = complete_rows.reset_index(drop=True)
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))  # 3 ordered classes
    return rows, y


@pytest.fixture(scope="module")
def clf(classifier_data) -> FuzzyClassifier:
    rows, y = classifier_data
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=12, pop_size=20)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=0)


def test_classifier_predicts_class_indexes_and_minus_one_for_missing_inputs(clf, classifier_data):
    rows, _ = classifier_data
    X = rows[FEATURES].head(50).copy()
    pred = clf.predict(X)
    assert pred.dtype.kind == "i" and set(pred.tolist()) <= {-1, 0, 1, 2}
    X.iloc[3, 0] = np.nan
    assert clf.predict(X)[3] == -1 and (clf.predict(X)[[0, 1, 2]] == pred[[0, 1, 2]]).all()
    assert clf.fit_info["train_class_counts"] and clf.estimator.rule_base.ds_mode == 0
    labels = clf.predict_labels(X)
    names = ["lo", "mid", "hi"]
    assert labels[3] is None and list(labels[[0, 1, 2]]) == [names[p] if p >= 0 else None for p in pred[:3]]


def test_classifier_is_deterministic_and_rejects_empty_classes(classifier_data):
    rows, y = classifier_data
    params = FuzzyClassifierParams(nRules=6, nAnts=2, n_gen=6, pop_size=12)
    a = FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=4)
    b = FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=4)
    assert (a.predict(rows[FEATURES]) == b.predict(rows[FEATURES])).all()
    with pytest.raises(ValueError, match="without any fitting row"):
        FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], np.minimum(y, 1), ["lo", "mid", "hi"], seed=0)


@pytest.mark.parametrize("weighting", ["dominance_score", "none", "weight"])
def test_engine_matches_the_library(classifier_data, weighting):
    """Firing, association and winner come from ex_fuzzy; the prediction equals ``predict``."""
    rows, y = classifier_data
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=10, pop_size=20, rule_weighting=weighting)
    model = FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=1)
    X = rows[FEATURES].to_numpy(dtype=float)
    act = compute_classifier_activations(model, X)
    rb = get_master_rulebase(model)
    assert np.array_equal(act.firing, rb.compute_firing_strengths(X))
    assert np.array_equal(act.association, rb.compute_association_degrees(X))
    assert np.allclose(act.association, act.firing * act.weights)
    assert np.array_equal(act.prediction, model.predict(rows[FEATURES]))
    classes = np.array(rule_classes(rb))
    ok = act.winner >= 0
    assert (classes[act.winner[ok]] == act.prediction[ok]).all()
    assert (act.winner == np.where(act.association.max(axis=1) > 0, act.association.argmax(axis=1), -1)).all()
    assert len(rule_weights(rb)) == len(rule_ids(rb)) == act.firing.shape[1]


def test_engine_rejects_a_regression_rule_base(additive_model):
    with pytest.raises(UnsupportedModelError):
        get_master_rulebase(additive_model.get_rulebase())


def test_readability_rows_are_consistent(clf, classifier_data):
    rows, y = classifier_data
    X = rows[FEATURES].to_numpy(dtype=float)
    out = classifier_readability_rows("c", clf, X, ["lo", "mid", "hi"], y)
    by = {(r.metric, r.slice): r for r in out}
    n_rules = by[("n_rules", "all")].value
    assert n_rules == len(classifier_rule_sets(clf, ["lo", "mid", "hi"]))
    assert sum(by[(f"n_rules[{c}]", "all")].value for c in ("lo", "mid", "hi")) == n_rules
    wins = [r.value for r in out if r.metric == "rule_win_share"]
    unknown = by[("share_no_rule_fires", "all")].value
    assert sum(wins) + unknown == pytest.approx(1.0)
    assert by[("n_rules_winning", "all")].value == sum(w > 0 for w in wins)
    assert 0 <= by[("n_duplicate_rules", "all")].value <= n_rules
    assert all(0 <= r.value <= 1 for r in out if r.metric == "rule_win_precision")


def test_rule_set_stability_jaccard():
    a = [((("f", "Low"),), "lo"), ((("g", "High"),), "hi")]
    b = [((("f", "Low"),), "lo"), ((("g", "High"),), "mid")]
    out = rule_set_stability([a, b, a])
    assert out["pairwise_jaccard_rule"] == pytest.approx([1 / 3, 1.0, 1 / 3])
    assert out["pairwise_jaccard_antecedents"] == pytest.approx([1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def class_experiment(table, tmp_path_factory):
    from atlas.contracts import models as m
    from atlas.ml import pipeline
    from atlas.ml.experiment_class import ClassExperimentConfig
    from atlas.ml.split import chronological_split_spec

    table = table.copy()
    table["complete"] = True
    table.loc[table.index[::97], "complete"] = False
    cuts = [int(round(c)) for c in np.nanquantile(table[TARGET], [0.4, 0.8, 0.995])]
    bounds = [(0, cuts[0]), (cuts[0] + 1, cuts[1]), (cuts[1] + 1, cuts[2]), (cuts[2] + 1, 1000)]
    scheme = {"name": "toy", "source_url": "https://example.org/toy", "unit": "u", "classes": [
        {"label": f"C{i}", "lower": lo, "upper": hi, "color": "#00FF00", "description": "d"}
        for i, (lo, hi) in enumerate(bounds)]}
    path = tmp_path_factory.mktemp("scheme") / "scheme.json"
    path.write_text(json.dumps(scheme))
    split = chronological_split_spec(table["issued_at_utc"], horizon_hours=6, embargo_hours=24)
    base = pipeline.RunConfig(
        task_id="synthetic_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u", horizon_hours=6,
        features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t", split=split, seed=3,
        data_version="synthetic-test", synthetic=True, gbm_max_iter=10,
    )
    config = ClassExperimentConfig(
        experiment_id="ica-test", table="unused", base=base, scheme=str(path), merge_min_train_rows=60,
        subsample={"n_rows": 600, "seed": 5},
        selection={"candidates": [{"nRules": 6, "nAnts": 2, "sampling_power": 0.5},
                                  {"nRules": 6, "nAnts": 2, "sampling_power": 1.0, "rule_weighting": "none"}],
                   "n_gen": 4, "pop_size": 12},
        final={"n_gen": 4, "pop_size": 12, "seeds": [0, 1]},
    )
    return config, table


def test_class_experiment_select_final_and_run_directories(class_experiment, tmp_path):
    from atlas.contracts import models as m
    from atlas.ml import artifacts
    from atlas.ml.experiment_class import ClassData, run_final, run_selection, write_class_runs

    config, table = class_experiment
    cd = ClassData(config, frame=table)
    dist = cd.distribution()
    assert sum(dist["periods"]["train"]["official"].values()) == dist["periods"]["train"]["n"]
    # the train count of C3 is below 60: the top class is merged
    assert cd.labels[-1].endswith("o peor") and dist["merged"][0]["merged_from"] == ["C2", "C3"]
    out = tmp_path / "exp"
    selection = run_selection(config, cd, out)
    assert len(selection["fits"]) == 2 and (out / "class_distribution.json").exists()
    assert selection["chosen"] in [f["candidate"] for f in selection["fits"]]
    assert run_selection(config, cd, out)["fits"] == selection["fits"]  # resumable
    summary = run_final(config, cd, out)
    assert [r["seed"] for r in summary["runs"]] == [0, 1]
    assert len(summary["rule_stability"]["pairwise_jaccard_rule"]) == 1
    assert set(summary["baselines"]) == {
        "persistence", "climatology_majority_class", "hist_gradient_boosting", "hist_gradient_boosting_balanced",
        "hist_gradient_boosting_regression_binned", "hist_gradient_boosting_subsample", "logistic_regression",
        "logistic_regression_balanced", "logistic_regression_subsample", "logistic_regression_balanced_subsample",
        "random_forest", "random_forest_balanced", "random_forest_subsample", "random_forest_balanced_subsample"}
    n_test = summary["n_complete_rows"]["test"]
    assert sum(sum(row) for row in summary["baselines"]["persistence"]["test"]["confusion"]) == n_test
    assert summary["published_seed"] == max(summary["runs"], key=lambda r: r["validation"]["macro_f1"])["seed"]
    dirs = write_class_runs(config, cd, out, tmp_path / "art")
    assert [d.name for d in dirs] == ["ica-test-seed0", "ica-test-seed1"]
    run = dirs[0]
    artifacts.verify_checksums(run)
    rules = m.ModelRules.model_validate_json((run / "rules.json").read_text())
    assert rules.inference.family == m.InferenceFamily.WINNING_RULE_CLASSIFIER and rules.target_scheme is not None
    assert [c.label for c in rules.target_scheme.classes] == cd.labels
    metrics = m.MetricsReport.model_validate_json((run / "metrics.json").read_text())
    estimators = {r.estimator for r in metrics.rows}
    assert estimators == {"exfuzzy_classifier", *summary["baselines"]}
    names = {r.metric for r in metrics.rows if r.estimator == "exfuzzy_classifier"}
    assert {"macro_f1", "balanced_accuracy", "accuracy", "mae_class_index", "share_off_by_2plus", "n_rules",
            "rule_win_share", "n_rules_winning", "share_unknown", f"recall[{cd.labels[0]}]"} <= names
    preds = pd.read_parquet(run / "predictions.parquet")
    ok = preds["prediction_label"].notna()
    assert set(preds.loc[ok, "prediction_label"]) <= set(cd.labels) and preds["prediction"].isna().all()
    assert (preds.loc[~ok, "missing_reason"].notna()).all() and preds.loc[ok, "missing_reason"].isna().all()
    manifest = m.RunManifest.model_validate_json((run / "run_manifest.json").read_text())
    assert manifest.model_id == "exfuzzy-synthetic_y_h6-ica-test-seed0"


def test_class_report_prints_every_section(class_experiment, tmp_path, capsys):
    from atlas.ml import report_class
    from atlas.ml.experiment_class import ClassData, run_final, run_selection, write_class_runs

    config, table = class_experiment
    cd = ClassData(config, frame=table)
    out = tmp_path / "exp"
    run_selection(config, cd, out)
    run_final(config, cd, out)
    run = write_class_runs(config, cd, out, tmp_path / "art")[0]
    report_class.main(["--experiment", str(out), "--run-dir", str(run)])
    text = capsys.readouterr().out
    for title in ("## Class distribution", "## Selection", "## Test overall", "## Test confusion matrix, ExFuzzy",
                  "## Seeds", "## Readability", "## Rules of the published model", "## Linguistic terms"):
        assert title in text
    assert "| exfuzzy_classifier |" in text and "| persistence |" in text and "THEN ICA = **" in text
