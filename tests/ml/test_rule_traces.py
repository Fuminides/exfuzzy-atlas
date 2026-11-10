"""Golden parity tests for atlas.explain: traces and firing tables against ex_fuzzy's own outputs."""

import numpy as np
import pandas as pd
import pytest
from ml_helpers import build_rulebase

from atlas.contracts import models as m
from atlas.explain import (
    UnsupportedModelError,
    build_rule_traces,
    compute_activations,
    duplicate_groups,
    firing_table,
    iter_firing_tables,
    rule_ids,
    tsk_decomposition,
)
from atlas.ml.synthetic import FEATURES

META = dict(model_id="m", task_id="t", horizon_hours=6, target_unit="u", data_version="v", synthetic=True)


def _eval_frame(rows: pd.DataFrame, n: int = 120) -> pd.DataFrame:
    """Rows from the data plus two out-of-domain rows (membership is clipped to the training domain)."""
    frame = rows.iloc[::7][["entity_id", "issued_at_utc", *FEATURES]].head(n).copy()
    extreme = frame.iloc[:2].copy()
    extreme["y_t"] = [1e6, -1e6]
    extreme["exo_t"] = [-50.0, 1e3]
    return pd.concat([frame, extreme], ignore_index=True)


def _traces(model, frame):
    return build_rule_traces(model, frame[FEATURES], frame["entity_id"], frame["issued_at_utc"], **META)


@pytest.mark.parametrize("fixture", ["additive_model", "sufficient_model"])
def test_trace_equals_library_firing_and_prediction(request, complete_rows, fixture):
    model = request.getfixturevalue(fixture)
    frame = _eval_frame(complete_rows)
    traces = _traces(model, frame)
    rulebase = model.get_rulebase()
    X = frame[FEATURES].to_numpy()

    library_firing = rulebase.compute_rule_antecedent_memberships(X)  # independent call of the library
    library_prediction = model.estimator.predict(frame[FEATURES])
    ids = rule_ids(rulebase)
    assert len(traces) == len(frame)
    for i, trace in enumerate(traces):
        assert [e.rule_id for e in trace.rules] == ids  # all rules, in model order
        assert np.array_equal([e.firing_strength for e in trace.rules], library_firing[i])
        assert trace.prediction.value == library_prediction[i]  # bit-exact
        m.RuleTrace.model_validate_json(trace.model_dump_json())  # the contract validator accepts it
        assert trace.inference.rule_mode.value == rulebase.rule_mode
        # memberships in the trace are the library's per-term values
        for entry, rule in zip(trace.rules, rulebase.rules, strict=True):
            used = [f for f, t in enumerate(rule.antecedents) if t >= 0]
            assert len(entry.antecedents) == len(used)


def test_additive_effective_firing_is_raw_and_sufficient_keeps_only_the_winner(
    complete_rows, additive_model, sufficient_model
):
    frame = _eval_frame(complete_rows)
    for entry in (e for t in _traces(additive_model, frame) for e in t.rules):
        assert entry.effective_firing == entry.firing_strength

    tolerance = sufficient_model.get_rulebase().tolerance
    covered = uncovered = 0
    for trace in _traces(sufficient_model, frame):
        raw = np.array([e.firing_strength for e in trace.rules])
        eff = np.array([e.effective_firing for e in trace.rules])
        if raw.max() > tolerance:
            covered += 1
            assert np.count_nonzero(eff) == 1 and eff[raw.argmax()] == raw.max()
        else:
            uncovered += 1
            assert not eff.any() and trace.prediction.fallback_used
        # the prediction is the weighted average of the effective firing of the trace
        c = np.array(sufficient_model.get_rulebase().scalar_consequents)
        if eff.sum() > 1e-10:
            assert abs(eff @ c / eff.sum() - trace.prediction.value) <= 1e-9
    assert covered > 0  # the sufficient fixture does exercise the winner path


def test_zero_firing_is_a_number_and_fallback_is_not_missing():
    # a=Low -> 10, b=High -> 90. The point (a=10, b=0) is High/Low only: both rules fire exactly 0.
    rulebase = build_rulebase([(0, -1), (-1, 1)], [10, 90], y_mean=42.0)
    frame = pd.DataFrame({"a": [10.0], "b": [0.0]})
    trace = build_rule_traces(
        rulebase, frame, ["E"], pd.DatetimeIndex(["2025-01-01T00:00Z"]), **META)[0]
    assert [e.firing_strength for e in trace.rules] == [0.0, 0.0]
    assert trace.prediction.value == 42.0 and trace.prediction.fallback_used is True
    assert trace.prediction.missing_reason is None
    assert rulebase.inference(frame.to_numpy())[0] == 42.0


def test_sufficient_below_tolerance_uses_fallback_although_raw_firing_is_positive():
    rulebase = build_rulebase([(0, -1), (1, -1)], [10, 90], rule_mode="sufficient", tolerance=0.9, y_mean=42.0)
    frame = pd.DataFrame({"a": [3.0, 0.5], "b": [5.0, 5.0]})  # Low(3)=0.5 -> weak, Low(0.5)=1 -> strong
    traces = build_rule_traces(rulebase, frame, ["E", "E"], pd.DatetimeIndex(["2025-01-01T00:00Z"] * 2), **META)
    weak, strong = traces
    assert max(e.firing_strength for e in weak.rules) > 0
    assert all(e.effective_firing == 0 for e in weak.rules)
    assert weak.prediction.fallback_used and weak.prediction.value == 42.0
    assert not strong.prediction.fallback_used and strong.prediction.value == 10.0
    assert [e.effective_firing for e in strong.rules] == [1.0, 0.0]


def test_missing_inputs_give_empty_traces_and_never_reach_the_library(monkeypatch, complete_rows, additive_model):
    frame = _eval_frame(complete_rows).head(6).copy()
    frame.loc[1, "exo_t"] = np.nan
    frame.loc[3, "y_t"] = np.inf
    rulebase = additive_model.get_rulebase()
    seen = []
    original = type(rulebase).compute_antecedents_memberships

    def spy(self, X):
        seen.append(np.asarray(X))
        return original(self, X)

    monkeypatch.setattr(type(rulebase), "compute_antecedents_memberships", spy)
    traces = _traces(additive_model, frame)
    assert all(np.isfinite(x).all() for x in seen) and seen  # the library only saw finite rows
    for i in (1, 3):
        t = traces[i]
        assert t.rules == [] and t.prediction.value is None and not t.prediction.fallback_used
        assert t.prediction.missing_reason == m.MissingReason.MISSING_INPUT
        assert t.quality.status == m.QualityStatus.WARNING
    reasons = {fv.feature: fv.missing_reason for fv in traces[1].feature_values}
    assert reasons["exo_t"] == m.MissingReason.NO_OBSERVATION and reasons["y_t"] is None
    assert traces[3].feature_values[0].missing_reason == m.MissingReason.INVALID_OBSERVATION
    for i in (0, 2, 4, 5):
        assert traces[i].prediction.value is not None and len(traces[i].rules) == len(rulebase.rules)


def test_modifier_and_minimum_tnorm_are_traced_and_validated():
    rulebase = build_rulebase(
        [(0, 1), (1, -1)], [20, 80], tnorm=np.min, modifiers=[np.array([2.0, -1]), None]
    )
    frame = pd.DataFrame({"a": [1.0, 3.0], "b": [7.0, 5.0]})
    traces = build_rule_traces(rulebase, frame, ["E", "E"], pd.DatetimeIndex(["2025-01-01T00:00Z"] * 2), **META)
    library = rulebase.compute_rule_antecedent_memberships(frame.to_numpy())
    for i, trace in enumerate(traces):
        assert trace.inference.tnorm == m.TNorm.MINIMUM
        assert np.array_equal([e.firing_strength for e in trace.rules], library[i])
    first = traces[1].rules[0].antecedents[0]
    assert first.modifier == 2.0 and first.effective_membership == pytest.approx(first.membership**2)
    assert traces[1].rules[0].antecedents[1].modifier is None  # -1 means "no modifier"


def test_unsupported_tnorm_fails_loudly():
    rulebase = build_rulebase([(0, -1)], [1.0], tnorm=np.sum)
    with pytest.raises(UnsupportedModelError, match="t-norm"):
        build_rule_traces(rulebase, pd.DataFrame({"a": [1.0], "b": [1.0]}), ["E"],
                          pd.DatetimeIndex(["2025-01-01T00:00Z"]), **META)


def test_naive_timestamps_and_length_mismatch_are_rejected(complete_rows, additive_model):
    frame = _eval_frame(complete_rows).head(3)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_rule_traces(additive_model, frame[FEATURES], frame["entity_id"],
                          frame["issued_at_utc"].dt.tz_localize(None), **META)
    with pytest.raises(ValueError, match="same length"):
        build_rule_traces(additive_model, frame[FEATURES], ["E"], frame["issued_at_utc"], **META)


@pytest.mark.parametrize("fixture", ["additive_model", "sufficient_model"])
def test_bulk_table_matches_per_row_traces(request, complete_rows, fixture):
    model = request.getfixturevalue(fixture)
    frame = _eval_frame(complete_rows).head(40).copy()
    frame.loc[5, "exo_t"] = np.nan
    traces = _traces(model, frame)
    table = firing_table(model, frame[FEATURES], frame["entity_id"], frame["issued_at_utc"], chunk_size=13)
    n_rules = len(model.get_rulebase().rules)
    assert len(table) == len(frame) * n_rules
    assert list(table.columns) == [
        "entity_id", "issued_at_utc", "rule_id", "firing_strength", "effective_firing", "missing_reason"
    ]
    for i, trace in enumerate(traces):
        block = table.iloc[i * n_rules:(i + 1) * n_rules]
        assert (block["entity_id"] == frame["entity_id"].iloc[i]).all()
        assert (block["issued_at_utc"] == frame["issued_at_utc"].iloc[i]).all()
        assert block["rule_id"].tolist() == rule_ids(model.get_rulebase())
        if trace.rules:
            assert np.array_equal(block["firing_strength"], [e.firing_strength for e in trace.rules])
            assert np.array_equal(block["effective_firing"], [e.effective_firing for e in trace.rules])
            assert block["missing_reason"].isna().all()
        else:  # missing input: NaN, never 0
            assert block["firing_strength"].isna().all() and (block["missing_reason"] == "missing_input").all()
    whole = firing_table(model, frame[FEATURES], frame["entity_id"], frame["issued_at_utc"], chunk_size=10_000)
    pd.testing.assert_frame_equal(table, whole)
    assert sum(len(c) for c in iter_firing_tables(
        model, frame[FEATURES], frame["entity_id"], frame["issued_at_utc"], chunk_size=7)) == len(table)


def test_duplicate_antecedents_are_flagged_not_merged():
    rulebase = build_rulebase([(0, 1), (1, -1), (0, 1), (0, 1)], [10, 20, 30, 40])
    assert duplicate_groups(rulebase) == [[0, 2, 3]]
    # identical antecedents fire identically; additive inference averages their consequents
    act = compute_activations(rulebase, np.array([[1.0, 9.0]]))
    assert act.raw[0, 0] == act.raw[0, 2] == act.raw[0, 3] > 0
    avg = build_rulebase([(0, 1), (0, 1), (0, 1)], [10, 30, 40])
    X = np.array([[1.0, 9.0]])
    assert avg.inference(X)[0] == pytest.approx(np.mean([10, 30, 40]))
    # sufficient mode: argmax ties go to the first rule, the later duplicates can never be the winner
    sufficient = build_rulebase([(0, 1), (0, 1)], [10, 30], rule_mode="sufficient", tolerance=0.0)
    eff = compute_activations(sufficient, X).effective[0]
    assert eff[0] > 0 and eff[1] == 0


@pytest.mark.parametrize("fixture", ["additive_model", "sufficient_model"])
def test_weighted_consequent_decomposition_is_exact(request, complete_rows, fixture):
    model = request.getfixturevalue(fixture)
    frame = _eval_frame(complete_rows)
    result = tsk_decomposition(model, frame[FEATURES].to_numpy())
    assert result.max_abs_error <= 1e-9
    covered = ~result.fallback_used
    assert np.allclose(result.weights[covered].sum(axis=1), 1.0, atol=1e-12)
    assert (result.weights[result.fallback_used] == 0).all()


def test_decomposition_fallback_and_leave_one_out_identity():
    # Fallback: nothing fires, the prediction is y_mean, the contributions sum to 0 (not to the prediction).
    rulebase = build_rulebase([(0, -1), (-1, 1)], [10, 90], y_mean=42.0)
    out = tsk_decomposition(rulebase, np.array([[10.0, 0.0]]))
    assert out.fallback_used[0] and out.contributions.sum() == 0 and out.prediction[0] == 42.0
    assert out.reconstruction[0] == 42.0 and out.max_abs_error == 0.0

    # Removing rule r changes the prediction by w_r * (c_r - yhat_without_r), not by w_r * c_r.
    full = build_rulebase([(0, -1), (-1, 0), (1, 1)], [10, 50, 90])
    X = np.array([[3.0, 3.0]])
    base = tsk_decomposition(full, X)
    for r in range(3):
        keep = [i for i in range(3) if i != r]
        reduced = build_rulebase([[(0, -1), (-1, 0), (1, 1)][i] for i in keep], [[10, 50, 90][i] for i in keep])
        without = reduced.inference(X)[0]
        w, c = base.weights[0, r], full.scalar_consequents[r]
        assert base.prediction[0] - without == pytest.approx(w * (c - without), abs=1e-9)
        if w > 0:  # the share of the weighted average is not the change caused by the rule
            assert abs((base.prediction[0] - without) - base.contributions[0, r]) > 1e-3


@pytest.mark.parametrize("mode,tolerance", [("additive", 0.0), ("sufficient", 0.0), ("sufficient", 0.8)])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_decomposition_holds_across_seeds_modes_and_random_inputs(complete_rows, seed, mode, tolerance):
    from ml_helpers import fit_fuzzy

    model = fit_fuzzy(complete_rows, seed=seed, rule_mode=mode, tolerance=tolerance, nRules=12)
    X = complete_rows[FEATURES].to_numpy()
    rng = np.random.default_rng(seed)
    probes = np.vstack([X[::9], rng.uniform(X.min(axis=0) - 50, X.max(axis=0) + 50, (150, X.shape[1]))])
    result = tsk_decomposition(model, probes)
    assert result.max_abs_error <= 1e-9
