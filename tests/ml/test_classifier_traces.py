"""AT-041c golden parity: classifier traces, firing table and ``rules.json`` against ex_fuzzy itself."""

import numpy as np
import pandas as pd
import pytest
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import rules as exf_rules

from atlas.contracts import models as m
from atlas.explain import build_classifier_traces, iter_classifier_firing_tables
from atlas.explain.classifier import UnsupportedModelError, inference_spec
from atlas.ml.classification import ClassScheme
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

LABELS = ["lo", "mid", "hi"]
SCHEME = ClassScheme.model_validate({
    "name": "toy", "source_url": "https://example.org/toy", "unit": "u",
    "classes": [{"label": "lo", "lower": 0, "upper": 10, "color": "#00FFFF", "description": "d"},
                {"label": "mid", "lower": 11, "upper": 20, "color": "#FFCC00", "description": "d"},
                {"label": "hi", "lower": 21, "upper": 30, "color": "#FF3300", "description": "d"}]})
KW = dict(model_id="toy-model", task_id="toy", horizon_hours=6, target_unit="u", data_version="synthetic-test",
          synthetic=True, feature_units=FEATURE_UNITS)


@pytest.fixture(scope="module")
def rows(complete_rows):
    return complete_rows.reset_index(drop=True)


@pytest.fixture(scope="module", params=["dominance_score", "none", "weight"])
def model(request, rows) -> FuzzyClassifier:
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=10, pop_size=20, rule_weighting=request.param)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=2)


def _traces(model, rows, n=60):
    X = rows[FEATURES].head(n)
    return X, build_classifier_traces(
        model, X, rows["entity_id"].head(n).tolist(), rows["issued_at_utc"].head(n), class_labels=LABELS, **KW)


def test_traces_equal_the_library(model, rows):
    X, traces = _traces(model, rows)
    rb = model.rule_base
    values = X.to_numpy(dtype=float)
    firing = rb.compute_firing_strengths(values)
    assoc = rb.compute_association_degrees(values)
    expected = model.estimator.predict(values)
    expl = rb.explainable_predict(values)
    for k, trace in enumerate(traces):
        assert [e.firing_strength for e in trace.rules] == firing[k].tolist()
        assert [e.association_degree for e in trace.rules] == assoc[k].tolist()
        assert [e.weight for e in trace.rules] == [e.weight for e in traces[0].rules]
        if expected[k] >= 0:
            assert trace.prediction.label == LABELS[expected[k]]
            assert trace.prediction.winning_rule_id == f"R{int(expl.winning_rule[k]) + 1:02d}"
            assert trace.prediction.value is None and not trace.prediction.fallback_used
        else:
            assert trace.prediction.label is None and trace.prediction.winning_rule_id is None
            assert trace.prediction.missing_reason == m.MissingReason.PREDICTION_UNAVAILABLE
    assert traces[0].inference.family == m.InferenceFamily.WINNING_RULE_CLASSIFIER
    assert traces[0].inference.rule_weighting == model.params.rule_weighting
    assert traces[0].inference.fallback == "unknown" and traces[0].inference.allow_unknown is True


def test_trace_memberships_multiply_to_the_firing(model, rows):
    """Product t-norm of the membership values ex_fuzzy returned (the trace never recomputes a membership)."""
    _, traces = _traces(model, rows, 30)
    for trace in traces:
        for entry in trace.rules:
            assert np.prod([a.membership for a in entry.antecedents]) == pytest.approx(entry.firing_strength, abs=1e-12)


def test_missing_input_row_has_no_rules_and_is_not_a_prediction(model, rows):
    X = rows[FEATURES].head(3).copy()
    X.iloc[1, 0] = np.nan
    stamps = rows["issued_at_utc"].head(3)
    traces = build_classifier_traces(model, X, ["a", "b", "c"], stamps, class_labels=LABELS, **KW)
    assert traces[1].rules == [] and traces[1].prediction.label is None
    assert traces[1].prediction.missing_reason == m.MissingReason.MISSING_INPUT
    assert traces[0].prediction.label is not None or traces[0].prediction.missing_reason is not None


def test_firing_table_equals_traces_and_the_library(model, rows):
    X = rows[FEATURES].head(40).copy()
    X.iloc[5, 1] = np.nan
    ents, stamps = rows["entity_id"].head(40).tolist(), rows["issued_at_utc"].head(40)
    table = pd.concat(list(iter_classifier_firing_tables(model, X, ents, stamps, chunk_size=13)), ignore_index=True)
    n_rules = len(model.rule_base.get_rules())
    assert len(table) == 40 * n_rules
    traces = build_classifier_traces(model, X, ents, stamps, class_labels=LABELS, **KW)
    ok = [k for k in range(40) if k != 5]
    good = table.iloc[[k * n_rules + r for k in ok for r in range(n_rules)]]
    assert good["firing_strength"].tolist() == [e.firing_strength for k in ok for e in traces[k].rules]
    assert good["association_degree"].tolist() == [e.association_degree for k in ok for e in traces[k].rules]
    key = good["entity_id"].astype(str) + good["issued_at_utc"].astype(str)
    wins = good.groupby(key, sort=False)["is_winner"].sum()
    labels = [traces[k].prediction.label for k in ok]
    assert (wins.to_numpy() == np.array([lab is not None for lab in labels])).all()
    bad = table.iloc[5 * n_rules:6 * n_rules]
    assert bad["firing_strength"].isna().all() and (bad["missing_reason"] == "missing_input").all()
    assert not bad["is_winner"].any()


def test_rules_json_is_valid_and_consistent_with_the_model(model, rows):
    rules = export_classifier_rules(
        model, model_id="toy-model", task_id="toy", domain=m.Domain.AIR, target_label="ICA", horizon_hours=6,
        data_version="synthetic-test", synthetic=True, feature_units=FEATURE_UNITS,
        target_scheme=SCHEME.to_target_scheme(), X_reference=rows[FEATURES])
    again = m.ModelRules.model_validate_json(rules.model_dump_json())
    assert again == rules
    rb = model.rule_base
    assert [r.consequent.term for r in rules.rules] == [LABELS[c] for c in rb.get_consequents()]
    assert all(r.consequent.type == "class" for r in rules.rules)
    weights = [1.0] * len(rules.rules) if model.params.rule_weighting == "none" else rb.get_scores() \
        if model.params.rule_weighting == "dominance_score" else rb.get_weights()
    assert [r.weight for r in rules.rules] == pytest.approx(list(weights))
    assert rules.inference == inference_spec(rb)
    if model.params.rule_weighting != "none":
        assert all("(peso" in r.text and "THEN ICA = " in r.text for r in rules.rules)


def test_target_scheme_is_contiguous_upper_inclusive():
    scheme = SCHEME.to_target_scheme()
    assert scheme.boundary == "upper_inclusive"
    assert [(c.lower, c.upper) for c in scheme.classes] == [(None, 10), (10, 20), (20, 30)]
    assert [c.color for c in scheme.classes] == ["#00FFFF", "#FFCC00", "#FF3300"]


# ------------------------------------------------------------------------- hand-built: nothing fires


def _hand_built(allow_unknown=True, ds_mode=0):
    low, high = [0, 0, 2, 6], [4, 8, 10, 10]
    variables = [fs.fuzzyVariable(n, [fs.FS("Low", low, [0, 10]), fs.FS("High", high, [0, 10])], units="u")
                 for n in ("a", "b")]
    rb0 = exf_rules.RuleBaseT1(variables, [exf_rules.RuleSimple([0, 0], consequent=0)])
    rb1 = exf_rules.RuleBaseT1(variables, [exf_rules.RuleSimple([1, 1], consequent=1)])
    rb0.rules[0].score, rb1.rules[0].score = 0.5, 0.25
    return exf_rules.MasterRuleBase([rb0, rb1], ["lo", "hi"], ds_mode=ds_mode, allow_unknown=allow_unknown)


def test_unknown_when_nothing_fires():
    master = _hand_built()
    X = pd.DataFrame({"a": [0.0, 10.0, 0.0], "b": [0.0, 10.0, 10.0]})
    traces = build_classifier_traces(
        master, X, ["e"] * 3, pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"), class_labels=["lo", "hi"],
        **KW)
    assert [t.prediction.label for t in traces] == ["lo", "hi", None]
    assert [t.prediction.winning_rule_id for t in traces] == ["R01", "R02", None]
    last = traces[2]
    assert last.prediction.missing_reason == m.MissingReason.PREDICTION_UNAVAILABLE and last.prediction.fallback_used
    assert all(e.firing_strength == 0 and e.association_degree == 0 for e in last.rules)
    assert [e.weight for e in traces[0].rules] == [0.5, 0.25]
    assert traces[0].rules[0].association_degree == pytest.approx(0.5 * traces[0].rules[0].firing_strength)


def test_classifier_that_cannot_say_unknown_is_not_exportable():
    master = _hand_built(allow_unknown=False)
    X = pd.DataFrame({"a": [0.0], "b": [10.0]})
    with pytest.raises(UnsupportedModelError, match="allow_unknown"):
        build_classifier_traces(master, X, ["e"], pd.date_range("2024-01-01", periods=1, tz="UTC"),
                                class_labels=["lo", "hi"], **KW)
