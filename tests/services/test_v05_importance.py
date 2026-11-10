"""Contract v0.5 rule importance: exact on the synthetic models, recomputed here from the published files with pandas.

The expected numbers do not use ``atlas.services.importance``: they are rebuilt from ``predictions.parquet`` and
``activations/`` (and, for the regressor, the rule consequents of ``rules.json``).
"""

import shutil

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.enrich import regression_fallback
from atlas.services.importance import ImportanceError, compute_importance
from atlas.services.verify import load_verified_model


def read(model_dir):
    importance = m.RuleImportanceResponse.model_validate_json((model_dir / layout.IMPORTANCE_FILE).read_text())
    rules = m.ModelRules.model_validate_json((model_dir / "rules.json").read_text())
    predictions = pq.read_table(model_dir / layout.PREDICTIONS_FILE).to_pandas()
    activations = pq.read_table(model_dir / layout.ACTIVATIONS_DIR).to_pandas()
    return importance, rules, predictions, activations.astype({"entity_id": str, "rule_id": str})


@pytest.fixture(scope="module")
def classifier(built_class):
    return read(built_class.model_dir)


@pytest.fixture(scope="module")
def regressor(built):
    return read(built.model_dir)


KEY = ["entity_id", "issued_at_utc"]


def with_shares(activations):
    """Records of rows with complete inputs and the share of each rule: effective_firing / sum over the row."""
    live = activations.dropna(subset=["effective_firing"]).copy()
    live["share"] = live["effective_firing"] / live.groupby(KEY)["effective_firing"].transform("sum")
    return live


def con():
    connection = duckdb.connect(config={"threads": 1})
    connection.execute("SET TimeZone='UTC'")
    return connection


# ------------------------------------------------------------------ classifier


def test_every_labelled_prediction_has_one_winner_that_decides_it(classifier):
    importance, rules, predictions, activations = classifier
    winners = activations[activations["is_winner"]]
    assert not winners.duplicated(["entity_id", "issued_at_utc"]).any()
    merged = predictions.merge(winners, on=["entity_id", "issued_at_utc"], how="left")
    labelled = merged["prediction_label"].notna()
    assert merged.loc[labelled, "rule_id"].notna().all()
    class_of = {r.rule_id: r.consequent.term for r in rules.rules}
    assert (merged.loc[labelled, "rule_id"].map(class_of) == merged.loc[labelled, "prediction_label"]).all()
    # counts: the rules decide exactly the labelled predictions
    decided = merged[labelled].groupby("rule_id").size()
    assert importance.n_predicted == int(labelled.sum())
    for rule in importance.rules:
        assert rule.n_decided == int(decided.get(rule.rule_id, 0))
        assert rule.decided_share == pytest.approx(rule.n_decided / importance.n_predicted, abs=1e-15)
    assert sum(r.n_decided for r in importance.rules) == importance.n_predicted


def test_accuracy_counts_only_decisions_with_an_observed_class(classifier):
    importance, rules, predictions, activations = classifier
    winners = activations[activations["is_winner"]][["entity_id", "issued_at_utc", "rule_id"]]
    merged = predictions[predictions["prediction_label"].notna()].merge(winners, on=["entity_id", "issued_at_utc"])
    merged = merged.assign(checked=merged["observed_label"].notna(),
                           hit=merged["observed_label"] == merged["prediction_label"])
    assert merged["checked"].any() and (~merged["checked"]).any(), "the fixture must exercise both cases"
    for rule in importance.rules:
        mine = merged[merged["rule_id"] == rule.rule_id]
        assert rule.n_checked == int(mine["checked"].sum())
        expected = None if not rule.n_checked else float(mine["hit"].sum()) / rule.n_checked
        assert rule.accuracy == expected
        assert rule.mean_weight_share is None and rule.mae is None


def test_issue_times_with_complete_inputs_and_no_rule_are_not_attributed(classifier):
    importance, rules, predictions, activations = classifier
    unavailable = predictions["missing_reason"] == "prediction_unavailable"
    assert unavailable.any(), "the fixture must have rows where no rule fired"
    fired = activations[activations["is_winner"]][["entity_id", "issued_at_utc"]]
    assert not predictions[unavailable].merge(fired, on=["entity_id", "issued_at_utc"]).shape[0]
    assert importance.n_no_rule == int(unavailable.sum())
    missing_input = int((predictions["missing_reason"] == "missing_input").sum())
    assert importance.n_predicted + importance.n_no_rule + missing_input == len(predictions)


def test_entities_aggregate_to_the_totals_and_variables_follow_from_the_rules(classifier):
    importance, rules, predictions, _ = classifier
    assert {e.entity_id for e in importance.entities} == set(predictions["entity_id"])
    assert sum(e.n_predicted for e in importance.entities) == importance.n_predicted
    for rule in importance.rules:
        per_entity = sum(e.n_predicted * r.decided_share for e in importance.entities for r in e.rules
                         if r.rule_id == rule.rule_id)
        assert per_entity == pytest.approx(rule.n_decided, abs=1e-9)
    for entity in importance.entities:
        assert [r.rule_id for r in entity.rules] == [r.rule_id for r in importance.rules
                                                     if r.rule_id in {x.rule_id for x in entity.rules}]
        assert sum(r.decided_share for r in entity.rules) == pytest.approx(1.0 if entity.n_predicted else 0.0)
    assert [v.feature for v in importance.variables] == [v.feature for v in rules.variables]
    decided = {r.rule_id: r.n_decided for r in importance.rules}
    for variable in importance.variables:
        users = [r.rule_id for r in rules.rules if variable.feature in {a.feature for a in r.antecedents}]
        assert variable.n_rules == len(users)
        assert variable.decided_share == pytest.approx(sum(decided[u] for u in users) / importance.n_predicted)


def test_the_period_is_the_published_issue_times(classifier):
    importance, _, predictions, _ = classifier
    assert importance.period_from_utc == predictions["issued_at_utc"].min()
    assert importance.period_to_utc == predictions["issued_at_utc"].max()
    assert importance.measure == m.ImportanceMeasure.WINNING_RULE


# ------------------------------------------------------------------ regression


def test_regression_shares_reproduce_the_predictions_and_add_up_to_one(regressor):
    importance, rules, predictions, activations = regressor
    consequent = {r.rule_id: r.consequent.value for r in rules.rules}
    live = with_shares(activations)
    assert live.groupby(KEY)["share"].sum().sub(1).abs().max() < 1e-12
    live["part"] = live["share"] * live["rule_id"].map(consequent)
    rebuilt = live.groupby(KEY)["part"].sum()
    merged = predictions.dropna(subset=["prediction"]).set_index(KEY)
    assert (rebuilt.reindex(merged.index) - merged["prediction"]).abs().max() < 1e-9
    assert importance.n_predicted == len(merged) and importance.n_no_rule == 0
    mean_share = live.groupby("rule_id")["share"].sum() / len(merged)
    for rule in importance.rules:
        assert rule.mean_weight_share == pytest.approx(mean_share.get(rule.rule_id, 0.0), abs=1e-12)
    assert sum(r.mean_weight_share for r in importance.rules) == pytest.approx(1.0)


def test_the_largest_share_decides_with_ties_to_the_lowest_position_and_mae_uses_observations(regressor):
    importance, rules, predictions, activations = regressor
    position = {r.rule_id: r.position for r in rules.rules}
    live = with_shares(activations)
    live["pos"] = live["rule_id"].map(position)
    best = live.sort_values(["share", "pos"], ascending=[False, True]).drop_duplicates(KEY)
    merged = best.merge(predictions, on=KEY)
    merged["error"] = (merged["prediction"] - merged["observed"]).abs()
    for rule in importance.rules:
        mine = merged[merged["rule_id"] == rule.rule_id]
        assert rule.n_decided == len(mine)
        assert rule.n_checked == int(mine["observed"].notna().sum())
        assert rule.accuracy is None
        if rule.n_checked:
            assert rule.mae == pytest.approx(mine["error"].mean(), abs=1e-12)
        else:
            assert rule.mae is None
    for entity in importance.entities:
        mine = merged[merged["entity_id"] == entity.entity_id]
        assert entity.n_predicted == len(mine)
        for r in entity.rules:
            assert r.decided_share == pytest.approx((mine["rule_id"] == r.rule_id).mean())
    # a variable's share is the summed mean share of the rules that use it
    shares = {r.rule_id: r.mean_weight_share for r in importance.rules}
    for variable in importance.variables:
        users = [r.rule_id for r in rules.rules if variable.feature in {a.feature for a in r.antecedents}]
        assert variable.decided_share == pytest.approx(min(1.0, sum(shares[u] for u in users)))


# ------------------------------------------------------- failing loudly


def tampered(built, tmp_path, edit):
    """A copy of the published model directory whose predictions.parquet was changed by ``edit(frame)``."""
    dest = tmp_path / built.model_dir.name
    shutil.copytree(built.model_dir, dest)
    frame = pq.read_table(dest / layout.PREDICTIONS_FILE).to_pandas()
    edit(frame)
    frame.to_parquet(dest / layout.PREDICTIONS_FILE, index=False)
    return dest


def test_a_class_label_that_differs_from_the_winning_rule_fails(built_class, tmp_path):
    def swap(frame):
        row = frame.index[frame["prediction_label"].notna()][0]
        others = [c for c in ("low", "mid", "high") if c != frame.loc[row, "prediction_label"]]
        frame.loc[row, "prediction_label"] = others[0]

    dest = tampered(built_class, tmp_path, swap)
    rules = m.ModelRules.model_validate_json((dest / "rules.json").read_text())
    with pytest.raises(ImportanceError, match="differs from prediction_label"):
        compute_importance(dest, rules, data_version="x", synthetic=True, fallback=None, con=con())


def test_a_regression_prediction_off_by_1e_6_fails(built, tmp_path):
    def nudge(frame):
        row = frame.index[frame["prediction"].notna()][3]
        frame.loc[row, "prediction"] += 1e-6

    dest = tampered(built, tmp_path, nudge)
    rules = m.ModelRules.model_validate_json((dest / "rules.json").read_text())
    fallback = regression_fallback(load_verified_model(built.model_dir), rules)
    with pytest.raises(ImportanceError, match="differs from the published prediction"):
        compute_importance(dest, rules, data_version="x", synthetic=True, fallback=fallback, con=con())


def test_predictions_without_activations_fail(built_class, tmp_path):
    def extra(frame):
        frame.loc[len(frame)] = frame.iloc[0]
        frame.loc[len(frame) - 1, "issued_at_utc"] = pd.Timestamp("2030-01-01", tz="UTC")

    dest = tampered(built_class, tmp_path, extra)
    rules = m.ModelRules.model_validate_json((dest / "rules.json").read_text())
    with pytest.raises(ImportanceError, match="activations for"):
        compute_importance(dest, rules, data_version="x", synthetic=True, fallback=None, con=con())


def test_a_withheld_prediction_is_neither_predicted_nor_without_rule(built_class, tmp_path):
    """NYC rows without a reference level: a rule fired, the class is withheld (no label). Not in n_predicted."""
    def withhold(frame):
        row = frame.index[frame["prediction_label"].notna()][0]
        frame.loc[row, ["prediction_label", "missing_reason"]] = [None, "prediction_unavailable"]

    base, *_ = read(built_class.model_dir)
    dest = tampered(built_class, tmp_path, withhold)
    rules = m.ModelRules.model_validate_json((dest / "rules.json").read_text())
    got, checks = compute_importance(dest, rules, data_version="x", synthetic=True, fallback=None, con=con())
    assert checks["n_withheld_excluded"] == 1
    assert got.n_predicted == base.n_predicted - 1 and got.n_no_rule == base.n_no_rule
    assert np.isclose(sum(r.decided_share for r in got.rules), 1.0)


def test_a_regression_row_where_no_rule_fires_gets_the_fallback_and_counts_as_no_rule(built, tmp_path):
    """Nothing fires: the prediction is the model's train_target_mean, the row is in n_no_rule and in no rule."""
    dest = tmp_path / built.model_dir.name
    shutil.copytree(built.model_dir, dest)
    rules = m.ModelRules.model_validate_json((dest / "rules.json").read_text())
    fallback = regression_fallback(load_verified_model(built.model_dir), rules)
    base, *_ = read(built.model_dir)
    part = next((dest / layout.ACTIVATIONS_DIR).glob("year=*/month=*/*.parquet"))
    activations = pq.read_table(part).to_pandas()
    key = activations.loc[activations["effective_firing"].notna(), ["entity_id", "issued_at_utc"]].iloc[0]
    row = (activations["entity_id"] == key["entity_id"]) & (activations["issued_at_utc"] == key["issued_at_utc"])
    activations.loc[row, ["firing_strength", "effective_firing"]] = 0.0
    schema = pq.read_schema(part)
    pq.write_table(pa.Table.from_pandas(activations, schema=schema, preserve_index=False), part)
    predictions = pq.read_table(dest / layout.PREDICTIONS_FILE).to_pandas()
    hit = (predictions["entity_id"] == key["entity_id"]) & (predictions["issued_at_utc"] == key["issued_at_utc"])
    predictions.loc[hit, "prediction"] = fallback
    pq.write_table(pa.Table.from_pandas(predictions, schema=pq.read_schema(dest / layout.PREDICTIONS_FILE),
                                        preserve_index=False), dest / layout.PREDICTIONS_FILE)
    got, checks = compute_importance(dest, rules, data_version="x", synthetic=True, fallback=fallback, con=con())
    assert (got.n_no_rule, checks["n_fallback_rows"]) == (1, 1)
    assert got.n_predicted == base.n_predicted - 1
    assert sum(r.n_decided for r in got.rules) == got.n_predicted
    assert sum(r.mean_weight_share for r in got.rules) == pytest.approx(1.0)
    with pytest.raises(ImportanceError, match="differs from the published prediction"):
        compute_importance(dest, rules, data_version="x", synthetic=True, fallback=fallback + 1, con=con())


def test_v052_observed_class_shares_are_the_observed_labels_of_the_checked_predictions(classifier):
    importance, rules, predictions, activations = classifier
    shares = importance.observed_class_shares
    assert shares is not None and sum(shares.values()) == pytest.approx(1)
    assert list(shares) == [c.label for c in rules.target_scheme.classes]  # every class, scheme order
    n_checked = sum(r.n_checked for r in importance.rules)
    assert n_checked > 0
    # accuracy x n_checked is the number of hits
    hits = sum(r.accuracy * r.n_checked for r in importance.rules if r.n_checked)
    winners = activations[activations["is_winner"]][["entity_id", "issued_at_utc"]]
    checked = predictions.merge(winners, on=["entity_id", "issued_at_utc"])
    checked = checked[checked["prediction_label"].notna() & checked["observed_label"].notna()]
    assert len(checked) == n_checked
    assert hits == pytest.approx(int((checked["observed_label"] == checked["prediction_label"]).sum()))
    for label, share in shares.items():
        assert share == pytest.approx(int((checked["observed_label"] == label).sum()) / n_checked)


def test_v052_observed_class_shares_are_for_classifiers_only(regressor):
    assert regressor[0].observed_class_shares is None
