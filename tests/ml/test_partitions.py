"""AT-041d: fixed linguistic variables (named bands with exact shoulders), the classifier that uses them, and the
experiment plumbing (joined tables, required columns, validation-only final).

Synthetic data only, except the scheme tests, which read the committed ``configs/ml/ica_no2_scheme.json``.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from atlas.contracts import models as m
from atlas.ml.classification import ClassScheme, load_scheme
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.partitions import (
    Band,
    FixedPartition,
    PartitionConfig,
    build_variables,
    fixed_variable,
    load_partition_file,
    scheme_partition,
    trapezoids,
)
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

SCHEME_PATH = Path(__file__).resolve().parents[2] / "configs" / "ml" / "ica_no2_scheme.json"
HOUR = FixedPartition(
    feature="hour", shoulder=1.0, domain=(0, 23),
    bands=[Band(name="Night", lower=0, upper=5), Band(name="Morning", lower=6, upper=11),
           Band(name="Afternoon", lower=12, upper=17), Band(name="Evening", lower=18, upper=23)])


@pytest.fixture(scope="module")
def ica() -> ClassScheme:
    return load_scheme(SCHEME_PATH).merge_rare_upper_tail([683216, 207285, 20750, 7323, 27, 0], 500)


def memberships(partition: FixedPartition, x) -> np.ndarray:
    """(n, n_terms) memberships computed by the ex_fuzzy variable itself."""
    x = np.asarray(x, dtype=float)
    return np.column_stack([term.membership(x) for term in fixed_variable(partition).get_linguistic_variables()])


# ------------------------------------------------------------------------------------------ the shoulders


def test_ica_terms_have_the_official_bands_as_cores_and_exact_shoulders(ica):
    partition = scheme_partition("no2_last", ica, relative_shoulder=0.15)
    assert [n for n, _ in trapezoids(partition)] == ["Buena", "Razonablemente buena", "Regular", "Desfavorable o peor"]
    assert partition.boundary_shoulders == [6.0, 13.5, 18.0]  # 15 % of 40, 90, 120
    assert [p for _, p in trapezoids(partition)] == [
        [0, 0, 40, 46], [35, 41, 90, 103.5], [77.5, 91, 120, 138], [103, 121, 1000, 1000]]
    x = np.array([0, 5, 40, 41, 90, 91, 120, 121, 500, 1000])
    mu = memberships(partition, x)
    core = [(0, 40), (41, 90), (91, 120), (121, 1000)]
    for k, (lo, hi) in enumerate(core):
        inside = (x >= lo) & (x <= hi)
        assert np.all(mu[inside, k] == 1.0), f"core of {k}"
    # linear shoulders around the 40 | 41 boundary (width 6): 0 at the foot, 1 at the core, linear in between
    ramp = np.array([35, 38, 40, 41, 43, 46, 47])
    assert np.allclose(memberships(partition, ramp)[:, 0], [1, 1, 1, 5 / 6, 0.5, 0.0, 0.0])
    assert np.allclose(memberships(partition, ramp)[:, 1], [0, 0.5, 5 / 6, 1, 1, 1, 1])
    # the 90 | 91 and 120 | 121 boundaries have their own widths (13.5 and 18)
    assert np.isclose(memberships(partition, [96.75])[0, 1], 0.5)
    assert np.isclose(memberships(partition, [129])[0, 2], 0.5)
    assert np.all(memberships(partition, [1001, 5000]) == 0)  # above the source's last bound: no term


def test_the_class_labels_are_the_term_names_and_a_value_is_in_its_bands_core(ica):
    partition = scheme_partition("no2_last", ica, relative_shoulder=0.15)
    values = np.array([0, 17, 40, 41, 66, 90, 91, 120, 121, 250])
    winner = memberships(partition, values).argmax(axis=1)
    # inside the shoulders the next term can be as large or larger (ties go to the better class); in cores they agree
    assert [ica.labels[k] for k in winner] == [ica.labels[int(c)] for c in ica.classify(values)]
    assert partition.follows_target_scheme


def test_zero_shoulder_is_crisp_on_whole_numbers(ica):
    partition = scheme_partition("no2_last", ica, shoulder=0.0)
    x = np.arange(0, 200)
    mu = memberships(partition, x)
    assert set(np.unique(mu)) == {0.0, 1.0} and np.all(mu.sum(axis=1) == 1)
    assert np.array_equal(mu.argmax(axis=1), ica.classify(x))


def test_hour_terms_cover_the_day_and_are_crisp_on_whole_hours():
    mu = memberships(HOUR, np.arange(24))
    assert np.all(mu.sum(axis=1) == 1) and set(np.unique(mu)) == {0.0, 1.0}
    assert mu.argmax(axis=1).tolist() == [0] * 6 + [1] * 6 + [2] * 6 + [3] * 6
    half = memberships(HOUR, [5.5, 11.5])
    assert np.allclose(half, [[0.5, 0.5, 0, 0], [0, 0.5, 0.5, 0]])


def test_invalid_partitions_are_refused(ica):
    base = dict(feature="f", shoulder=1.0, domain=(0, 10))
    with pytest.raises(ValidationError, match="at least two"):
        FixedPartition(**base, bands=[Band(name="a", lower=0, upper=10)])
    with pytest.raises(ValidationError, match="unique"):
        FixedPartition(**base, bands=[Band(name="a", lower=0, upper=4), Band(name="a", lower=5, upper=10)])
    with pytest.raises(ValidationError, match="overlap"):
        FixedPartition(**base, bands=[Band(name="a", lower=0, upper=5), Band(name="b", lower=5, upper=10)])
    with pytest.raises(ValidationError, match="domain minimum"):
        FixedPartition(**base, bands=[Band(name="a", lower=1, upper=4), Band(name="b", lower=5, upper=10)])
    with pytest.raises(ValidationError):
        FixedPartition(**{**base, "shoulder": -1}, bands=[Band(name="a", lower=0, upper=4),
                                                         Band(name="b", lower=5, upper=10)])
    with pytest.raises(ValidationError, match="one shoulder width per boundary"):
        FixedPartition(**{**base, "shoulder": [1.0, 2.0]}, bands=[Band(name="a", lower=0, upper=4),
                                                                  Band(name="b", lower=5, upper=10)])
    with pytest.raises(ValueError, match="defined twice"):
        PartitionConfig(fixed=[HOUR, HOUR]).resolve()
    with pytest.raises(ValueError, match="exactly one"):
        scheme_partition("f", ica)


# ------------------------------------------------------------------------- the committed partitions file

PARTITIONS_FILE = Path(__file__).resolve().parents[2] / "configs" / "ml" / "madrid_partitions.json"


def test_committed_partitions_match_their_cores_and_shoulders_and_the_ica_scheme(ica):
    loaded = load_partition_file(PARTITIONS_FILE)  # raises if a written parameter is not the computed one
    assert set(loaded) == {"no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "valid_hour_local",
                           "valid_weekday"}
    assert loaded["no2_last"].model_dump() == scheme_partition("no2_last", ica, relative_shoulder=0.15).model_dump()
    # every hour and weekday belongs to exactly one term (crisp) and the day types are Mon-Fri / Sat / Sun
    hour = memberships(loaded["valid_hour_local"], np.arange(24))
    assert np.all(hour.sum(axis=1) == 1) and np.all(np.isin(hour, [0.0, 1.0]))
    assert [b.name for b in loaded["valid_hour_local"].bands] == ["Noche", "Punta de mañana", "Mediodía", "Tarde-noche"]
    day = memberships(loaded["valid_weekday"], np.arange(7))
    assert day.argmax(axis=1).tolist() == [0, 0, 0, 0, 0, 1, 2] and np.all(day.sum(axis=1) == 1)
    wind = loaded["wind_speed"]  # WMO-No. 8 Table 5.1: force 0-1 up to 1.5, force 2 up to 3.3, force 3-4 up to 7.9 m/s
    assert [(b.lower, b.upper) for b in wind.bands] == [(0, 1.5), (1.6, 3.3), (3.4, 7.9), (8.0, 40)]
    assert wind.boundary_shoulders == pytest.approx([0.5, 0.5, 0.79])
    document = json.loads(PARTITIONS_FILE.read_text())
    for entry in document["variables"]:  # every variable carries its rationale and says what was checked
        assert entry["rationale"] and "source_status" in entry
        if entry["kind"] == "fixed" and entry["features"][0] not in ("valid_hour_local", "valid_weekday"):
            assert entry["source_url"].startswith("https://")
    assert [e["features"] for e in document["variables"] if e["kind"] == "quantile"][0] == [
        "temperature", "relative_humidity"]


def test_a_partitions_file_with_an_edited_parameter_is_refused(tmp_path):
    document = json.loads(PARTITIONS_FILE.read_text())
    document["variables"][0]["terms"][1]["params"][0] = 34.0
    path = tmp_path / "p.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="written params"):
        load_partition_file(path)


def test_partition_config_resolves_a_file_and_a_subset():
    all_fixed = PartitionConfig(file=str(PARTITIONS_FILE)).resolve()
    only_no2 = PartitionConfig(file=str(PARTITIONS_FILE), use_features=["no2_last", "no2_lag1h"]).resolve()
    assert set(only_no2) == {"no2_last", "no2_lag1h"} and set(all_fixed) > set(only_no2)
    with pytest.raises(ValueError, match="no fixed partition"):
        PartitionConfig(file=str(PARTITIONS_FILE), use_features=["temperature"]).resolve()


# ---------------------------------------------------------------------------- variables and the classifier


def test_build_variables_mixes_fixed_and_quantile_terms_in_input_order():
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.normal(size=500), np.full(500, 7.0), rng.integers(0, 24, 500)])  # 2nd: constant
    variables = build_variables(X, ["a", "const", "hour"], {"const": scheme_like("const"), "hour": HOUR}, 3,
                                {"a": "u", "hour": "h"})
    assert [v.name for v in variables] == ["a", "const", "hour"]
    assert [v.units for v in variables] == ["u", None, "h"]
    assert [v.linguistic_variable_names() for v in variables] == [
        ["Low", "Medium", "High"], ["Low", "High"], ["Night", "Morning", "Afternoon", "Evening"]]
    with pytest.raises(ValueError, match="not inputs"):
        build_variables(X, ["a", "const", "hour"], {"zzz": HOUR}, 3)


def scheme_like(name: str) -> FixedPartition:
    return FixedPartition(feature=name, shoulder=0.5, domain=(0, 10),
                          bands=[Band(name="Low", lower=0, upper=4), Band(name="High", lower=5, upper=10)])


@pytest.fixture(scope="module")
def fixed_clf(complete_rows):
    rows = complete_rows.reset_index(drop=True)
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    lo, hi = float(rows["y_t"].min()), float(rows["y_t"].max())
    cut = float(np.quantile(rows["y_t"], 0.6))
    y_t = FixedPartition(feature="y_t", shoulder=3.0, domain=(lo, hi), bands=[
        Band(name="Under", lower=lo, upper=cut), Band(name="Over", lower=cut + 1, upper=hi)])
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=12, pop_size=20)
    model = FuzzyClassifier(params, FEATURE_UNITS).fit(
        rows[FEATURES], y, ["lo", "mid", "hi"], seed=0, fixed={"y_t": y_t, "hour": HOUR})
    return model, rows, y_t


def test_exfuzzy_accepts_the_fixed_variables_and_keeps_them_exactly(fixed_clf):
    model, rows, y_t = fixed_clf
    rb = model.rule_base
    by_name = {v.name: v for v in rb.antecedents}
    assert by_name["y_t"].linguistic_variable_names() == ["Under", "Over"]
    assert by_name["hour"].linguistic_variable_names() == ["Night", "Morning", "Afternoon", "Evening"]
    assert by_name["y_lag3"].linguistic_variable_names() == ["Low", "Medium", "High"]  # the rest stays quantile
    for name, params in trapezoids(y_t):
        term = next(s for s in by_name["y_t"].linguistic_variables if s.name == name)
        assert list(term.membership_parameters) == params
    assert model.fit_info["fixed_partitions"] == {
        "y_t": ["Under", "Over"], "hour": ["Night", "Morning", "Afternoon", "Evening"]}
    pred = model.predict(rows[FEATURES].head(200))
    assert set(pred.tolist()) <= {-1, 0, 1, 2}


def test_rules_json_reads_with_the_band_names(fixed_clf):
    model, rows, _ = fixed_clf
    labels = ["lo", "mid", "hi"]
    target = m.TargetScheme(name="toy", source_url="https://example.org", unit="u", boundary="upper_inclusive",
                            classes=[m.TargetClass(label=lab, lower=None if i == 0 else float(i), upper=float(i + 1))
                                     for i, lab in enumerate(labels)])
    rules = export_classifier_rules(
        model, model_id="toy", task_id="toy", domain=m.Domain.AIR, target_label="T", target_scheme=target,
        horizon_hours=6, data_version="toy", synthetic=True, feature_units=FEATURE_UNITS,
        X_reference=rows[FEATURES])
    terms = {v.feature: [t.name for t in v.terms] for v in rules.variables}
    assert terms["hour"] == ["Night", "Morning", "Afternoon", "Evening"] and terms["y_t"] == ["Under", "Over"]
    used = {a.term for r in rules.rules for a in r.antecedents if a.feature == "hour"}
    assert used <= set(terms["hour"])
    assert all(t.membership_type == "trapezoidal" for v in rules.variables for t in v.terms)


def test_a_fixed_column_may_be_constant_but_a_quantile_one_may_not(complete_rows):
    rows = complete_rows.reset_index(drop=True).copy()
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=6, nAnts=2, n_gen=4, pop_size=12)
    rows["hour"] = 3.0
    FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=0, fixed={"hour": HOUR})
    with pytest.raises(ValueError, match="constant training features"):
        FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=0)


# --------------------------------------------------------------------------------------- the experiment


@pytest.fixture(scope="module")
def joined_experiment(table, tmp_path_factory):
    from atlas.ml import pipeline
    from atlas.ml.experiment_class import ClassExperimentConfig
    from atlas.ml.split import chronological_split_spec

    root = tmp_path_factory.mktemp("joined")
    table = table.copy()
    table["complete"] = True
    extra = table[["entity_id", "issued_at_utc"]].iloc[:-100].copy()  # the extra table covers fewer rows
    rng = np.random.default_rng(1)
    extra["traffic"] = rng.uniform(0, 100, len(extra))
    extra.loc[extra["entity_id"] == "E2", "traffic"] = np.nan  # one entity has no traffic at all
    extra.to_parquet(root / "extra.parquet", index=False)
    table.to_parquet(root / "main.parquet", index=False)
    cuts = [int(round(c)) for c in np.nanquantile(table[TARGET], [0.4, 0.8, 0.995])]
    bounds = [(0, cuts[0]), (cuts[0] + 1, cuts[1]), (cuts[1] + 1, cuts[2]), (cuts[2] + 1, 1000)]
    scheme = {"name": "toy", "source_url": "https://example.org/toy", "unit": "u", "classes": [
        {"label": f"C{i}", "lower": lo, "upper": hi, "color": "#00FF00", "description": "d"}
        for i, (lo, hi) in enumerate(bounds)]}
    (root / "scheme.json").write_text(json.dumps(scheme))
    split = chronological_split_spec(table["issued_at_utc"], horizon_hours=6, embargo_hours=24)

    def config(features, **kw):
        base = pipeline.RunConfig(
            task_id="synthetic_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u", horizon_hours=6,
            features=features, feature_units={**FEATURE_UNITS, "traffic": "veh/h"}, persistence_feature="y_t",
            split=split, seed=3, data_version="synthetic-test", synthetic=True, gbm_max_iter=10)
        return ClassExperimentConfig(
            experiment_id="join-test", table=str(root / "main.parquet"), base=base, scheme=str(root / "scheme.json"),
            merge_min_train_rows=60, subsample={"n_rows": 600, "seed": 5},
            extra_tables=[{"table": str(root / "extra.parquet"), "columns": ["traffic"]}],
            selection={"candidates": [{"nRules": 6, "nAnts": 2, "sampling_power": 0.5}], "n_gen": 4, "pop_size": 12},
            final={"n_gen": 4, "pop_size": 12, "seeds": [0, 1]}, **kw)

    return config


def test_extra_tables_are_inner_joined_and_missing_values_leave_the_rows_incomplete(joined_experiment):
    from atlas.ml.experiment_class import ClassData

    without = ClassData(joined_experiment(FEATURES, require_columns=["traffic"]))
    with_traffic = ClassData(joined_experiment([*FEATURES, "traffic"]))
    frame = without.data.frame
    assert len(frame) == len(with_traffic.data.frame) < 3 * 24 * 20 * 3  # inner join: the last 100 keys are gone
    assert "traffic" in frame and not frame.loc[frame["entity_id"] == "E2", "traffic"].notna().any()
    # identical rows with and without the traffic features, and none of E2 (no traffic) nor of the incomplete rows
    for period in ("train", "validation", "test"):
        a = without.data.train_pos if period == "train" else without.data.positions(period)
        b = with_traffic.data.train_pos if period == "train" else with_traffic.data.positions(period)
        assert np.array_equal(a, b)
        assert "E2" not in set(frame.loc[a, "entity_id"])
    assert without.labels == with_traffic.labels


def test_extra_table_keys_must_exist_in_the_main_table(joined_experiment, tmp_path):
    from atlas.ml.experiment_class import ClassExperimentConfig, load_class_frame

    config = joined_experiment(FEATURES)
    extra = pd.read_parquet(config.extra_tables[0].table).head(5).copy()
    extra["entity_id"] = "ghost"
    extra.to_parquet(tmp_path / "ghost.parquet", index=False)
    bad = ClassExperimentConfig.model_validate(
        {**json.loads(config.model_dump_json()), "extra_tables": [{"table": str(tmp_path / "ghost.parquet"),
                                                                   "columns": ["traffic"]}]})
    with pytest.raises(ValueError, match="not in"):
        load_class_frame(bad)


def test_validation_only_final_never_reads_test_and_fixed_terms_reach_the_summary(joined_experiment, tmp_path):
    from atlas.ml.experiment_class import ClassData, run_final, run_selection

    config = joined_experiment(
        [*FEATURES], partitions={"fixed": [json.loads(p.model_dump_json()) for p in (HOUR, scheme_like("y_t"))]})
    cd = ClassData(config)
    assert set(cd.fixed) == {"y_t", "hour"}
    out = tmp_path / "exp"
    run_selection(config, cd, out)
    summary = run_final(config, cd, out, test=False, baselines=False)
    assert (out / "summary_validation.json").exists() and not (out / "summary.json").exists()
    assert all("test" not in run for run in summary["runs"]) and "test" not in summary["n_complete_rows"]
    assert summary["baselines"] == {}
    assert summary["fixed_partitions"]["hour"]["bands"][0]["name"] == "Night"
    assert summary["runs"][0]["fit_info"]["fixed_partitions"]["y_t"] == ["Low", "High"]
    rows = json.loads((out / "models" / "rows_seed0.json").read_text())
    assert any(r["metric"] == "n_rules" for r in rows)  # static readability rows are kept when only validation runs
    assert not any(r["slice"] == "all" and r["metric"] == "macro_f1" for r in rows)  # validation rows are prefixed


def test_a_term_set_that_claims_to_follow_the_target_scheme_must_match_it(joined_experiment):
    from atlas.ml.experiment_class import ClassData

    claim = scheme_like("y_t").model_copy(update={"follows_target_scheme": True})
    config = joined_experiment([*FEATURES], partitions={"fixed": [json.loads(claim.model_dump_json())]})
    with pytest.raises(ValueError, match="not the classes of the target scheme"):
        ClassData(config)


def test_report_v2_prints_the_partition_and_traffic_tables(joined_experiment, tmp_path, capsys):
    from atlas.ml import report_v2
    from atlas.ml.experiment_class import ClassData, run_final, run_selection

    dirs = {}
    for name, features, extra in (("without", FEATURES, {"require_columns": ["traffic"]}),
                                  ("with", [*FEATURES, "traffic"], {})):
        config = joined_experiment(features, **extra)
        cd = ClassData(config)
        out = tmp_path / name
        run_selection(config, cd, out)
        run_final(config, cd, out)  # test=True: the traffic report needs summary.json
        dirs[name] = out
    report_v2.main(["partitions", "--scheme", f"a={dirs['without']}", "--scheme", f"b={dirs['with']}"])
    text = capsys.readouterr().out
    assert "| a | 6 / 2 |" in text and "| b | 6 / 2 |" in text and "chosen" in text
    report_v2.main(["traffic", "--without", str(dirs["without"]), "--with", str(dirs["with"])])
    text = capsys.readouterr().out
    assert "Rows (identical in both arms)" in text and "| exfuzzy_classifier | without traffic |" in text
    assert "| random_forest_subsample | without traffic |" in text and "difference (with - without)" in text
    assert "| logistic_regression_balanced |" in text
