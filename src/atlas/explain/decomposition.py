"""Diagnostic: is ``w_r * c_r`` an exact decomposition of a zero-order TSK prediction?

Not part of any contract and not exposed by the API. See ``docs/ml/exfuzzy_api_notes.md`` for what the
result does and does not mean. ``w_r`` is the effective firing of rule r over the sum of effective firings
(``sufficient`` mode already zeroes every rule but the winner in ``effective``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from atlas.explain.engine import COVERAGE_EPSILON, compute_activations, get_rulebase


@dataclass(frozen=True)
class TSKDecomposition:
    weights: np.ndarray  # (n_rows, n_rules); all zeros where the fallback was used
    contributions: np.ndarray  # weights * consequents
    reconstruction: np.ndarray  # contributions.sum(1) where covered, y_mean where the fallback was used
    prediction: np.ndarray  # RuleBaseT1Regression.inference
    fallback_used: np.ndarray
    max_abs_error: float


def tsk_decomposition(model, X: np.ndarray) -> TSKDecomposition:
    """Weighted-consequent decomposition of ``X`` (finite rows) and its error against ex_fuzzy's output."""
    rulebase = get_rulebase(model)
    act = compute_activations(rulebase, X)
    total = act.effective.sum(axis=1)
    covered = total > COVERAGE_EPSILON
    weights = np.zeros_like(act.effective)
    weights[covered] = act.effective[covered] / total[covered, None]
    contributions = weights * rulebase.scalar_consequents[None, :]
    reconstruction = np.where(covered, contributions.sum(axis=1), float(rulebase.y_mean))
    error = float(np.max(np.abs(reconstruction - act.prediction))) if len(reconstruction) else 0.0
    return TSKDecomposition(weights, contributions, reconstruction, act.prediction, act.fallback_used, error)
