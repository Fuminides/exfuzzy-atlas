"""Wrapper, rules.json export, atomic run directories and the CLI, on tiny synthetic data."""

import json
import pickle

import ex_fuzzy
import numpy as np
import pandas as pd
import pytest
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import utils
from ml_helpers import SMALL, build_rulebase, fit_fuzzy

from atlas.contracts import models as m
from atlas.explain import UnsupportedModelError, rule_ids
from atlas.ml import artifacts, pipeline
from atlas.ml.__main__ import main
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.rules_export import export_model_rules
from atlas.ml.synthetic import FEATURES, TARGET

EXPORT = dict(
    model_id="m", task_id="t", domain=m.Domain.AIR, target="y", target_unit="u", horizon_hours=6,
    data_version="v", synthetic=True,
)


# ----------------------------------------------------------------------------- wrapper


def test_same_seed_same_rules_and_predictions(complete_rows, additive_model):
    again = fit_fuzzy(complete_rows)
    a, b = additive_model.get_rulebase(), again.get_rulebase()
    assert [r.antecedents for r in a.rules] == [r.antecedents for r in b.rules]
    assert np.array_equal(a.scalar_consequents, b.scalar_consequents)
    assert np.array_equal(additive_model.predict(complete_rows[FEATURES]), again.predict(complete_rows[FEATURES]))


def test_feature_names_units_and_train_only_partitions(complete_rows, additive_model):
    rulebase = additive_model.get_rulebase()
    assert [v.name for v in rulebase.antecedents] == FEATURES
    assert [v.units for v in rulebase.antecedents] == ["u", "u", "m/s", "h"]
    reference = utils.construct_partitions(
        complete_rows[FEATURES].to_numpy(), n_partitions=3, detect_categorical=False
    )
    for fitted, expected in zip(rulebase.antecedents, reference, strict=True):
        for a, b in zip(fitted.linguistic_variables, expected.linguistic_variables, strict=True):
            assert np.array_equal(a.membership_parameters, b.membership_parameters)


def test_binary_flag_stays_numeric_and_bad_inputs_are_rejected(complete_rows):
    from atlas.ml.fuzzy import FuzzyRegressor

    flagged = complete_rows[FEATURES].assign(flag=(np.arange(len(complete_rows)) % 2).astype(float))
    model = FuzzyRegressor(SMALL).fit(flagged, complete_rows[TARGET], seed=0)
    assert all(type(s) is fs.FS for v in model.get_rulebase().antecedents for s in v.linguistic_variables)
    with pytest.raises(ValueError, match="constant"):
        FuzzyRegressor(SMALL).fit(flagged.assign(flag=1.0), complete_rows[TARGET], seed=0)
    with pytest.raises(TypeError):
        FuzzyRegressor(SMALL).fit(flagged.to_numpy(), complete_rows[TARGET], seed=0)


def test_predict_returns_nan_instead_of_raising_on_missing_inputs(complete_rows, additive_model):
    X = complete_rows[FEATURES].head(4).copy()
    X.loc[X.index[1], "exo_t"] = np.nan
    out = additive_model.predict(X)
    assert np.isnan(out[1]) and np.isfinite(out[[0, 2, 3]]).all()


def test_fit_drops_the_optimizer_result_that_embeds_the_training_data(additive_model):
    assert not hasattr(additive_model.estimator, "optimization_result_")
    assert len(pickle.dumps(additive_model)) < 20_000
    assert additive_model.fit_info["n_generations_run"] == SMALL.n_gen


# ------------------------------------------------------------------------ rules export


def test_rules_json_reads_the_real_partitions(complete_rows, additive_model):
    rules = export_model_rules(additive_model, X_reference=complete_rows[FEATURES], **EXPORT)
    m.ModelRules.model_validate_json(rules.model_dump_json())
    rulebase = additive_model.get_rulebase()
    assert [r.rule_id for r in rules.rules] == rule_ids(rulebase)
    assert len({r.rule_id for r in rules.rules}) == len(rulebase.rules)
    for var, lib in zip(rules.variables, rulebase.antecedents, strict=True):
        assert var.feature == lib.name and var.unit == lib.units
        for term, fuzzy_set in zip(var.terms, lib.linguistic_variables, strict=True):
            assert term.name == fuzzy_set.name and term.membership_type == "trapezoidal"
            assert term.params == [float(p) for p in fuzzy_set.membership_parameters]
    for rule, lib_rule, c in zip(rules.rules, rulebase.rules, rulebase.scalar_consequents, strict=True):
        assert rule.consequent.value == float(c) and rule.text.startswith("IF ")
        assert len(rule.antecedents) == sum(t >= 0 for t in lib_rule.antecedents)
        assert 0 <= rule.metrics["mean_activation"] <= 1
    assert rules.inference.tnorm == m.TNorm.PRODUCT and rules.inference.fallback == "train_target_mean"
    assert rules.inference.family == m.InferenceFamily.TSK_ZERO_ORDER


def test_sufficient_mode_is_exported(complete_rows, sufficient_model):
    inf = export_model_rules(sufficient_model, **EXPORT).inference
    assert inf.rule_mode == m.RuleMode.SUFFICIENT and inf.tolerance == 0.3


def test_duplicate_rules_keep_positional_ids_and_are_flagged():
    rulebase = build_rulebase([(0, 1), (1, -1), (0, 1)], [10, 20, 30])
    rules = export_model_rules(rulebase, **EXPORT).rules
    assert [r.rule_id for r in rules] == ["R01", "R02", "R03"]
    assert rules[0].duplicate_of is None
    assert rules[2].duplicate_of == rules[0].rule_id
    assert rules[2].text.endswith("[same antecedents as R01]")
    assert [r.consequent.value for r in rules] == [10, 20, 30]  # nothing merged, nothing dropped


def test_unknown_membership_class_fails_loudly():
    variables = [
        fs.fuzzyVariable("a", [fs.categoricalFS("0.0", 0.0), fs.categoricalFS("1.0", 1.0)]),
        fs.fuzzyVariable("b", [fs.FS("Low", [0, 0, 1, 2], [0, 2]), fs.FS("High", [1, 2, 3, 3], [0, 3])]),
    ]
    from ex_fuzzy import rules as exf_rules
    from ex_fuzzy.evolutionary_fit_regression import RuleBaseT1Regression

    rulebase = RuleBaseT1Regression(variables, [exf_rules.RuleSimple([0, 1])], np.array([1.0]), y_mean=0.0)
    with pytest.raises(UnsupportedModelError, match="categoricalFS"):
        export_model_rules(rulebase, **EXPORT)


def test_gaussian_and_triangular_are_mapped_and_wrong_arity_is_rejected():
    from ex_fuzzy import rules as exf_rules
    from ex_fuzzy.evolutionary_fit_regression import RuleBaseT1Regression

    variables = [
        fs.fuzzyVariable("a", [fs.gaussianFS("Low", [0.0, 1.0], [0, 5]), fs.gaussianFS("High", [5.0, 1.0], [0, 5])]),
        fs.fuzzyVariable(
            "b", [fs.triangularFS("Low", [0, 0, 1, 2], [0, 2]), fs.triangularFS("High", [1, 2, 2, 2], [0, 2])]
        ),
    ]
    rulebase = RuleBaseT1Regression(variables, [exf_rules.RuleSimple([0, 1])], np.array([1.0]), y_mean=0.0)
    kinds = [t.membership_type for v in export_model_rules(rulebase, **EXPORT).variables for t in v.terms]
    assert kinds == ["gaussian", "gaussian", "triangular", "triangular"]
    variables[0].linguistic_variables[0].membership_parameters = [0.0, 1.0, 2.0]
    with pytest.raises(UnsupportedModelError, match="parameters"):
        export_model_rules(rulebase, **EXPORT)


# ------------------------------------------------------------------------ run directory


@pytest.fixture(scope="module")
def trained(table, run_config, tmp_path_factory):
    root = tmp_path_factory.mktemp("artifacts")
    return pipeline.train_run(table, run_config, artifacts_dir=root), root


def test_run_directory_contents_and_metrics_share_one_split(trained, run_config):
    result, root = trained
    assert result.run_dir == root / run_config.task_id / result.manifest.run_id
    assert sorted(p.name for p in result.run_dir.iterdir()) == [
        "SHA256SUMS", "metrics.json", "model.pkl", "predictions.parquet", "rules.json", "run_manifest.json",
    ]
    assert not [p for p in result.run_dir.parent.iterdir() if p.name.startswith(".tmp-")]
    manifest = m.RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    assert manifest.split.embargo_hours >= manifest.horizon_hours and manifest.seed == run_config.seed
    # "3.4.0" on the pinned PyPI library, "3.4.0+g<commit>[.dirty]" on a git checkout of ex_fuzzy
    assert manifest.exfuzzy_version == exfuzzy_version() and manifest.exfuzzy_version.startswith(ex_fuzzy.__version__)
    assert manifest.git_commit and isinstance(manifest.git_dirty, bool)
    assert manifest.features == FEATURES and set(manifest.artifacts) >= {"model", "metrics", "rules"}
    assert any("rows dropped" in w for w in manifest.warnings)  # incomplete rows are reported, not hidden
    report = m.MetricsReport.model_validate_json((result.run_dir / "metrics.json").read_text())
    assert report.split == manifest.split
    n_all = {r.estimator: r.n for r in report.rows if r.metric == "mae" and r.slice == "all"}
    assert set(n_all) == {"exfuzzy", "persistence", "climatology", "ridge", "hist_gradient_boosting"}
    assert len(set(n_all.values())) == 1  # every estimator scored on exactly the same rows
    assert {r.slice for r in report.rows if r.slice != "all"} == {"entity=E0", "entity=E1", "entity=E2"}
    assert {"n_rules", "mean_rule_length", "fraction_fallback", "fit_seconds"} <= {r.metric for r in report.rows}


def test_training_period_is_not_contaminated_by_later_data(table, run_config, tmp_path):
    """Changing only test-period features must not change anything learned (partitions, rules, consequents)."""
    masks = pipeline.split_masks(table["issued_at_utc"], run_config.split)
    tampered = table.copy()
    tampered.loc[masks["test"], FEATURES[:3]] *= 50
    base = pipeline.train_run(table, run_config.model_copy(update={"run_id": "a"}), artifacts_dir=tmp_path)
    other = pipeline.train_run(tampered, run_config.model_copy(update={"run_id": "b"}), artifacts_dir=tmp_path)
    strip = lambda r: {k: v for k, v in r.rules.model_dump().items() if k != "model_id"}  # noqa: E731
    assert strip(base) == strip(other)


def test_leaky_split_is_refused(table, run_config, tmp_path):
    spec = run_config.split
    leaky = spec.model_copy(update={"embargo_hours": 0, "test_from_utc": spec.validation_to_utc,
                                    "validation_from_utc": spec.train_to_utc})
    with pytest.raises(ValueError, match="leakage"):
        pipeline.train_run(table, run_config.model_copy(update={"split": leaky}), artifacts_dir=tmp_path)


def test_reload_predictions_metrics_and_traces_reproduce(trained, table):
    result, _ = trained
    run = pipeline.load_run(result.run_dir)
    stored = pd.read_parquet(result.run_dir / "predictions.parquet")
    test = table[pipeline.split_masks(table["issued_at_utc"], run.manifest.split)["test"]]
    assert len(stored) == len(test)
    again = pipeline.predict_table(run, test)
    assert np.array_equal(stored["prediction"].to_numpy(), again["prediction"].to_numpy(), equal_nan=True)
    assert stored.loc[stored["prediction"].isna(), "missing_reason"].eq("missing_input").all()
    rows, gap = pipeline.evaluate_run(run, table)
    assert gap == 0.0 and rows
    row = test.dropna().iloc[3]
    (trace,) = pipeline.explain_rows(run, table, row["entity_id"], row["issued_at_utc"])
    assert trace.prediction.value == stored.set_index(["entity_id", "issued_at_utc"]).loc[
        (row["entity_id"], row["issued_at_utc"]), "prediction"
    ]
    assert trace.model_id == run.manifest.model_id and trace.synthetic is True


def test_existing_run_is_never_overwritten_and_failures_leave_nothing(trained, table, run_config, monkeypatch):
    result, root = trained
    with pytest.raises(FileExistsError):
        pipeline.train_run(table, run_config.model_copy(update={"run_id": result.manifest.run_id}),
                           artifacts_dir=root)

    def boom(*args, **kwargs):
        raise RuntimeError("parity failed")

    monkeypatch.setattr(artifacts, "assert_pickle_parity", boom)
    with pytest.raises(RuntimeError, match="parity"):
        pipeline.train_run(table, run_config.model_copy(update={"run_id": "failing"}), artifacts_dir=root)
    siblings = sorted(p.name for p in (root / run_config.task_id).iterdir())
    assert "failing" not in siblings and not [s for s in siblings if s.startswith(".tmp-")]


def test_tampered_model_is_refused_before_unpickling(trained, tmp_path):
    result, _ = trained
    copy = tmp_path / "run"
    copy.mkdir()
    for p in result.run_dir.iterdir():
        (copy / p.name).write_bytes(p.read_bytes())
    pipeline.load_run(copy)
    (copy / "model.pkl").write_bytes((copy / "model.pkl").read_bytes() + b"x")
    with pytest.raises(ValueError, match="checksum"):
        pipeline.load_run(copy)


def test_cli_demo_predict_evaluate_explain(tmp_path, capsys):
    main(["demo", "--n-gen", "5", "--pop-size", "10", "--artifacts-dir", str(tmp_path)])
    (run_dir,) = list((tmp_path / "synthetic_y_h6").iterdir())
    assert "exfuzzy" in capsys.readouterr().out
    from atlas.ml.synthetic import make_synthetic_table

    table_path = tmp_path / "table.parquet"
    table = make_synthetic_table(seed=0)
    table.to_parquet(table_path)
    main(["evaluate", "--run", str(run_dir), "--table", str(table_path)])
    assert json.loads(capsys.readouterr().out)["max_gap_vs_stored"] == 0.0
    out = tmp_path / "pred.parquet"
    main(["predict", "--run", str(run_dir), "--table", str(table_path), "--out", str(out)])
    capsys.readouterr()
    assert len(pd.read_parquet(out)) == len(table)
    row = table.dropna().iloc[-100]
    main(["explain", "--run", str(run_dir), "--table", str(table_path), "--entity", row["entity_id"],
          "--at", row["issued_at_utc"].isoformat()])
    trace = m.RuleTrace.model_validate_json(capsys.readouterr().out)
    assert trace.entity_id == row["entity_id"] and len(trace.rules) == 20


@pytest.mark.parametrize("fixture", ["additive_model", "sufficient_model"])
def test_ga_fitness_is_the_r2_of_the_final_rule_base(request, complete_rows, fixture):
    from sklearn.metrics import r2_score

    model = request.getfixturevalue(fixture)
    r2 = r2_score(complete_rows[TARGET], model.predict(complete_rows[FEATURES]))
    assert model.fit_info["train_fitness"] == pytest.approx(r2, abs=1e-12)


def test_rule_text_has_no_plus_zero_horizon():
    rulebase = build_rulebase([(0, 1)], [10])
    same_time = export_model_rules(rulebase, **{**EXPORT, "horizon_hours": 0}).rules[0].text
    forecast = export_model_rules(rulebase, **EXPORT).rules[0].text
    assert "y(t) =" in same_time and "+0h" not in same_time
    assert "y(t+6h) =" in forecast
