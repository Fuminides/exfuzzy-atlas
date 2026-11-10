"""Helpers shared by the ML tests (importable because pytest puts this directory on sys.path)."""

import numpy as np
import pandas as pd
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import rules as exf_rules
from ex_fuzzy.evolutionary_fit_regression import RuleBaseT1Regression

from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

SMALL = FuzzyParams(nRules=8, nAnts=3, n_gen=8, pop_size=16)


def fit_fuzzy(rows: pd.DataFrame, seed: int = 0, **overrides) -> FuzzyRegressor:
    params = FuzzyParams(**{**SMALL.as_dict(), **overrides})
    return FuzzyRegressor(params, FEATURE_UNITS).fit(rows[FEATURES], rows[TARGET], seed=seed)


def build_rulebase(rule_terms, consequents, *, rule_mode="additive", tolerance=0.0, tnorm=np.prod, modifiers=None,
                   y_mean=50.0) -> RuleBaseT1Regression:
    """Hand-written two-variable rule base (a, b in [0, 10], terms Low/High) for deterministic edge cases."""
    low, high = [0, 0, 2, 6], [4, 8, 10, 10]
    variables = [
        fs.fuzzyVariable(name, [fs.FS("Low", low, [0, 10]), fs.FS("High", high, [0, 10])], units="u")
        for name in ("a", "b")
    ]
    modifiers = modifiers or [None] * len(rule_terms)
    rule_list = [
        exf_rules.RuleSimple(list(t), consequent=0, modifiers=mod) for t, mod in zip(rule_terms, modifiers, strict=True)
    ]
    return RuleBaseT1Regression(
        variables, rule_list, np.array(consequents, dtype=float), y_mean=y_mean, rule_mode=rule_mode,
        tolerance=tolerance, tnorm=tnorm,
    )
