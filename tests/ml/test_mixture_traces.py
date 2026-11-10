"""Contract v0.7: traces, firing tables and rules of a mixture-of-rules classifier equal ex_fuzzy's own numbers.

Parity: the served class scores and per-rule contributions are ex_fuzzy ``mixture_scores`` / ``mixture_contributions``
on the same rows, bit for bit; the top rule and the decisive flags follow their definitions (``atlas.explain.mixture``).
Needs an ex_fuzzy with ``inference='mixture'`` (the pinned commit; locally EXFUZZY_SRC, docs/reproduce.md).
"""

from __future__ import annotations

import copy
import os

import numpy as np
import pandas as pd
import pytest

from atlas.contracts import models as m
from atlas.ml.exfuzzy_features import has_rule_mixture

pytestmark = pytest.mark.skipif(not has_rule_mixture() and not os.environ.get("CI"),
                                reason="needs ex_fuzzy with inference='mixture' (EXFUZZY_SRC, docs/reproduce.md)")


@pytest.fixture(scope="module", params=[True, False], ids=["non_negative", "unconstrained"])
def fitted(request):
    from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
    from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET, make_synthetic_table
    from atlas.services.synthetic import SCHEME

    table = make_synthetic_table(n_entities=3, n_hours=24 * 12, seed=1, exo_missing_fraction=0.03)
    complete = table[np.isfinite(table[[*FEATURES, TARGET]].to_numpy(float)).all(axis=1)].reset_index(drop=True)
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=4, pop_size=10, patience=None, inference="mixture",
                                   mixture_non_negative=request.param, mixture_search=True)
    model = FuzzyClassifier(params, FEATURE_UNITS).fit(complete[FEATURES], SCHEME.classify(complete[TARGET]),
                                                       SCHEME.labels, 3)
    return model, table, SCHEME


def test_traces_equal_mixture_scores_and_contributions(fitted):
    from atlas.explain import build_mixture_traces

    model, table, scheme = fitted
    X = table[model.feature_names].head(400)
    traces = build_mixture_traces(model, X, table["entity_id"].head(400).tolist(), table["issued_at_utc"].head(400),
                                  class_labels=scheme.labels, model_id="m", task_id="t", horizon_hours=6,
                                  target_unit="u", data_version="v")
    finite = np.isfinite(X.to_numpy(float)).all(axis=1)
    assert (~finite).any() and finite.any()
    est = model.estimator
    scores, contributions = est.mixture_scores(X[finite].to_numpy()), est.mixture_contributions(X[finite].to_numpy())
    labels = model.predict_labels(X)
    k = 0
    for row, trace in enumerate(traces):
        if not finite[row]:
            assert trace.rules == [] and trace.prediction.missing_reason == m.MissingReason.MISSING_INPUT
            continue
        p = trace.prediction
        assert list(p.class_scores.values()) == [float(v) for v in scores[k]]
        for r, entry in enumerate(trace.rules):
            assert list(entry.class_contributions.values()) == [float(v) for v in contributions[k, r]]
            assert entry.weight is None and entry.association_degree is None
        assert p.label == labels[row] and p.winning_rule_id is None
        k += 1


def test_top_rule_is_the_largest_centred_support_of_the_predicted_class(fitted):
    from atlas.explain.mixture import centred_weights, compute_mixture_activations

    model, table, _ = fitted
    X = table[model.feature_names].dropna().to_numpy(float)[:300]
    act = compute_mixture_activations(model, X)
    coef = model.estimator.mixture_.coef_
    centred = centred_weights(coef)
    assert np.allclose(centred.mean(axis=1), 0) and np.allclose(centred - coef, (centred - coef)[:, :1])
    for i in range(len(X)):
        c = act.prediction[i]
        support = act.firing[i] * centred[:, c]
        top = m.top_contributor(support.tolist())
        assert act.top[i] == (-1 if top is None else top)
        if top is not None:
            assert act.top_share[i] == pytest.approx(support[top] / support[support > 0].sum())
    # the centred form changes no prediction: argmax of bias + firing @ centred is ex_fuzzy's class
    assert np.array_equal(np.argmax(act.firing @ centred + act.bias, axis=1), act.prediction)


def test_decisive_means_zeroing_the_rule_changes_the_class(fitted):
    from atlas.explain.mixture import compute_mixture_activations

    model, table, _ = fitted
    X = table[model.feature_names].dropna().to_numpy(float)[:300]
    act = compute_mixture_activations(model, X)
    for r in range(act.weights.shape[0]):
        other = copy.deepcopy(model)
        other.estimator.mixture_.coef_[r] = 0.0
        assert np.array_equal(act.decisive[:, r], other.estimator.predict(X) != act.prediction)
    assert act.decisive.any()


def test_firing_table_matches_the_activations_and_the_winning_rule_engine_refuses(fitted):
    from atlas.explain import compute_classifier_activations, iter_mixture_firing_tables
    from atlas.explain.engine import UnsupportedModelError
    from atlas.explain.mixture import compute_mixture_activations

    model, table, _ = fitted
    X = table[model.feature_names].head(120)
    frame = pd.concat(iter_mixture_firing_tables(model, X, table["entity_id"].head(120).tolist(),
                                                 table["issued_at_utc"].head(120), chunk_size=50))
    n_rules = len(model.rule_base.get_rules())
    assert len(frame) == 120 * n_rules
    values = X.to_numpy(float)
    finite = np.isfinite(values).all(axis=1)
    act = compute_mixture_activations(model, values[finite])
    got = frame["firing_strength"].to_numpy().reshape(120, n_rules)
    assert np.array_equal(got[finite], act.firing) and np.isnan(got[~finite]).all()
    assert np.array_equal(frame["is_decisive"].to_numpy().reshape(120, n_rules)[finite], act.decisive)
    with pytest.raises(UnsupportedModelError, match="mixture"):
        compute_classifier_activations(model, values[finite])


def test_exported_rules_carry_the_fitted_weights(fitted):
    from atlas.ml.rules_export import export_classifier_rules

    model, table, scheme = fitted
    rules = export_classifier_rules(model, model_id="m", task_id="t", domain=m.Domain.AIR, target_label="Y",
                                    target_scheme=scheme.to_target_scheme(), horizon_hours=6, data_version="v",
                                    X_reference=table[model.feature_names])
    mixture = model.estimator.mixture_
    assert rules.inference.family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER
    assert rules.inference.mixture_weights == ("non_negative" if mixture.non_negative else "unconstrained")
    assert list(rules.class_bias.values()) == [float(b) for b in mixture.intercept_]
    for k, rule in enumerate(rules.rules):
        assert list(rule.class_weights.values()) == [float(w) for w in mixture.coef_[k]]
        assert rule.weight is None and "suppresses" in rule.text and "THEN" not in rule.text
        assert rule.metrics["weight_spread"] == pytest.approx(np.ptp(mixture.coef_[k]))
