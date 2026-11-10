"""Exact rule activations of a fitted ex_fuzzy regression rule base.

Everything numeric (memberships, raw firing, the prediction) is computed by ex_fuzzy itself through
``compute_antecedents_memberships``, ``compute_rule_antecedent_memberships`` and ``inference``. The one
private helper used is ``_apply_rule_mode``, which is the only place where ex_fuzzy exposes the firing
that the inference really consumes in ``sufficient`` mode; the golden tests in ``tests/ml`` check that
the weighted average of that firing reproduces ``predict`` bit for bit.
"""

from __future__ import annotations

from dataclasses import dataclass

import ex_fuzzy
import numpy as np
from ex_fuzzy.evolutionary_fit_regression import RuleBaseT1Regression

from atlas.contracts import models as m

try:
    from ex_fuzzy.evolutionary_fit_regression import _apply_rule_mode
except ImportError as exc:  # pragma: no cover - only if a different ex_fuzzy is installed
    raise ImportError(
        f"ex_fuzzy {ex_fuzzy.__version__} has no _apply_rule_mode; atlas.explain is validated against 3.3.1"
    ) from exc

# ex_fuzzy divides by the firing sum only when it exceeds this constant (RuleBaseT1Regression.inference).
COVERAGE_EPSILON = 1e-10


class UnsupportedModelError(ValueError):
    """The rule base uses something the Atlas contracts cannot describe faithfully."""


def get_rulebase(model) -> RuleBaseT1Regression:
    """Return the scalar-consequent rule base of a fitted regressor, wrapper or rule base."""
    if isinstance(model, RuleBaseT1Regression):
        return model
    if hasattr(model, "get_rulebase"):
        rulebase = model.get_rulebase()
        if isinstance(rulebase, RuleBaseT1Regression):
            return rulebase
    raise UnsupportedModelError(
        f"expected a fitted BaseFuzzyRulesRegressor with crisp (zero-order TSK) consequents, got {type(model)!r}"
    )


def feature_names(rulebase: RuleBaseT1Regression) -> list[str]:
    return [str(variable.name) for variable in rulebase.antecedents]


def rule_ids(rulebase: RuleBaseT1Regression) -> list[str]:
    """Stable ids by position in the rule base: R01, R02, ... (width grows past 99 rules)."""
    width = max(2, len(str(len(rulebase.rules))))
    return [f"R{position + 1:0{width}d}" for position in range(len(rulebase.rules))]


def tnorm_of(rulebase: RuleBaseT1Regression) -> m.TNorm:
    """Map the rule base t-norm to the contract enum, failing loudly on anything else."""
    if rulebase.tnorm is np.prod:
        return m.TNorm.PRODUCT
    if rulebase.tnorm in (np.min, np.amin):
        return m.TNorm.MINIMUM
    raise UnsupportedModelError(f"t-norm {rulebase.tnorm!r} has no equivalent in the TNorm contract enum")


def inference_spec(rulebase: RuleBaseT1Regression) -> m.InferenceSpec:
    """Inference description read from the fitted rule base."""
    from atlas.ml.exfuzzy_features import exfuzzy_version  # atlas.ml imports atlas.explain: import at call time

    if rulebase.y_mean is None:
        # ex_fuzzy would then return 0.0, which is not "train_target_mean".
        raise UnsupportedModelError("rule base has no y_mean; the fallback cannot be described")
    return m.InferenceSpec(
        family=m.InferenceFamily.TSK_ZERO_ORDER,
        tnorm=tnorm_of(rulebase),
        rule_mode=m.RuleMode(rulebase.rule_mode),
        tolerance=float(rulebase.tolerance),
        fallback="train_target_mean",
        exfuzzy_version=exfuzzy_version(),
    )


def rule_modifier(rule, feature_index: int) -> float | None:
    """Hedge exponent of an antecedent, or None when ex_fuzzy applies none (None, -1 or 1)."""
    modifiers = getattr(rule, "modifiers", None)
    if modifiers is None or modifiers[feature_index] in (-1, 1):
        return None
    return float(modifiers[feature_index])


def trace_antecedents(rule, variables, names, memberships, k: int, *, hedged: bool = False) -> list[m.AntecedentTrace]:
    """The ``AntecedentTrace`` of every condition of ``rule`` for sample ``k`` (contract v0.8).

    The membership of a condition is the number ex_fuzzy computed for its code in ``memberships`` (the output of
    ``compute_antecedents_memberships``): the term's own membership for ``is``, the bounded sum
    ``min(1, sum of the covered terms)`` for ``at_least`` / ``at_most`` / ``any_of``. It is read, never recomputed.
    ``hedged``: the rule base has hedge exponents (the TSK regressor), applied to the membership.
    """
    from atlas.ml.exfuzzy_features import rule_conditions  # atlas.ml imports atlas.explain: import at call time

    out = []
    for c in rule_conditions(rule, variables):
        membership = float(memberships[c.feature][c.code][k])
        modifier = rule_modifier(rule, c.feature) if hedged else None
        out.append(m.AntecedentTrace(
            feature=names[c.feature], term=c.term, operator=c.operator, terms=list(c.terms), membership=membership,
            modifier=modifier, effective_membership=membership if modifier is None else membership**modifier,
        ))
    return out


def duplicate_groups(rulebase: RuleBaseT1Regression) -> list[list[int]]:
    """Groups (positions, ascending) of rules sharing identical antecedents and modifiers.

    Only groups with two or more rules are returned. The GA does not forbid them: such rules fire with
    exactly the same strength and differ only in their consequent.
    """
    groups: dict[tuple, list[int]] = {}
    for position, rule in enumerate(rulebase.rules):
        modifiers = tuple(rule_modifier(rule, f) for f in range(len(rule.antecedents)))
        groups.setdefault((tuple(int(t) for t in rule.antecedents), modifiers), []).append(position)
    return [positions for positions in groups.values() if len(positions) > 1]


@dataclass(frozen=True)
class RuleActivations:
    """Activations of every rule for finite input rows. Row i of each array is input row i."""

    memberships: list[np.ndarray]  # per feature, shape (n_terms, n_rows)
    raw: np.ndarray  # (n_rows, n_rules): t-norm of the effective memberships
    effective: np.ndarray  # (n_rows, n_rules): after rule_mode, what the inference consumes
    prediction: np.ndarray | None  # (n_rows,) from RuleBaseT1Regression.inference
    fallback_used: np.ndarray  # (n_rows,) bool: no effective firing, ex_fuzzy returned y_mean


def compute_activations(
    rulebase: RuleBaseT1Regression, X: np.ndarray, *, with_prediction: bool = True
) -> RuleActivations:
    """Run ex_fuzzy on ``X`` (finite, columns in antecedent order) and return all firing arrays."""
    X = np.asarray(X, dtype=float)
    memberships = rulebase.compute_antecedents_memberships(X)
    raw = rulebase.compute_rule_antecedent_memberships(X, memberships)
    effective = _apply_rule_mode(raw, rulebase.rule_mode, rulebase.tolerance)
    prediction = rulebase.inference(X, memberships) if with_prediction else None
    return RuleActivations(
        memberships=memberships,
        raw=raw,
        effective=effective,
        prediction=prediction,
        fallback_used=np.sum(effective, axis=1) <= COVERAGE_EPSILON,
    )
