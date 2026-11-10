"""Wrapper around ``BaseFuzzyRulesRegressor`` (zero-order TSK, crisp consequents, CPU backend).

Decisions, all checked against ex_fuzzy 3.3.1 (see ``docs/ml/exfuzzy_api_notes.md``):

* Partitions are built here with ``detect_categorical=False`` and passed as ``linguistic_variables``. With
  the default detection a low-cardinality whole-number column (e.g. a 0/1 flag) silently becomes a
  ``categoricalFS`` that the rule contract cannot describe. Partitions come from the training rows only.
* ``fit`` takes a DataFrame so feature names reach the linguistic variables; they are checked on ``predict``.
* ``optimization_result_`` is dropped after fitting: it holds the whole pymoo problem, i.e. the training data
  (about 200 bytes per training row: 6.3 MB for 30k rows), and nothing downstream needs it.
* Rows with a non-finite input are not sent to ex_fuzzy (it raises); ``predict`` returns NaN for them.
* Mamdani (``consequent_type="fuzzy"``) is deliberately not exposed: the rule contract has no output-set
  parameters, so ``rules.json`` could not describe it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from ex_fuzzy import utils
from ex_fuzzy.evolutionary_fit_regression import BaseFuzzyRulesRegressor, RuleBaseT1Regression

from atlas.ml.exfuzzy_features import require


@dataclass(frozen=True)
class FuzzyParams:
    """Hyperparameters of the GA fit; ``n_gen`` and ``pop_size`` are the optimisation budget."""

    nRules: int = 20
    nAnts: int = 3
    n_linguistic_variables: int = 3
    rule_mode: str = "additive"
    tolerance: float = 0.0
    n_gen: int = 50
    pop_size: int = 50
    backend: str = "pymoo"
    unique_antecedents: bool = False  # needs ex_fuzzy PR 30 (exfuzzy_features); left out of ``as_dict`` when False
    # ex_fuzzy PR 45: ``x IS at least t`` / ``at most t`` (True, or the inputs that get it) and named compound terms
    # ``{input: [(name, [terms])]}``; both left out of ``as_dict`` when off
    ordinal_conditions: bool | tuple[str, ...] = False
    compound_terms: dict[str, list[tuple[str, list[str]]]] | None = None

    def as_dict(self) -> dict:
        out = asdict(self)
        for key in ("unique_antecedents", "ordinal_conditions", "compound_terms"):
            if not out[key]:
                del out[key]  # manifests of the pinned release keep their old hyperparameters
        return out

    def estimator_options(self) -> dict:
        """Extra ``BaseFuzzyRulesRegressor`` arguments; refuses a library without them instead of ignoring them."""
        options = {}
        if self.unique_antecedents:
            require("unique_antecedents")
            options["unique_antecedents"] = True
        if self.ordinal_conditions:
            require("ordinal_conditions")
            options["ordinal_conditions"] = (self.ordinal_conditions if self.ordinal_conditions is True
                                             else list(self.ordinal_conditions))
        if self.compound_terms:
            require("compound_terms")
            options["compound_terms"] = self.compound_terms
        return options


class FuzzyRegressor:
    """A fitted-or-not crisp TSK regressor with explicit feature names and units."""

    def __init__(self, params: FuzzyParams | None = None, feature_units: dict[str, str] | None = None):
        self.params = params or FuzzyParams()
        self.feature_units = dict(feature_units or {})
        self.estimator: BaseFuzzyRulesRegressor | None = None
        self.feature_names: list[str] = []
        self.seed: int | None = None
        self.fit_info: dict = {}

    def fit(self, X: pd.DataFrame, y, seed: int) -> FuzzyRegressor:
        """Fit on finite rows only; the caller drops incomplete rows and reports how many."""
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a DataFrame so that feature names are explicit")
        self.feature_names = [str(c) for c in X.columns]
        values = X.to_numpy(dtype=float)
        constant = [n for n, col in zip(self.feature_names, values.T, strict=True) if np.ptp(col) == 0]
        if constant:
            raise ValueError(f"constant training features cannot be partitioned: {constant}")
        variables = utils.construct_partitions(
            values, n_partitions=self.params.n_linguistic_variables, detect_categorical=False
        )
        for variable, name in zip(variables, self.feature_names, strict=True):
            variable.name = name
            variable.units = self.feature_units.get(name)
        p = self.params
        estimator = BaseFuzzyRulesRegressor(
            nRules=p.nRules, nAnts=p.nAnts, n_linguistic_variables=p.n_linguistic_variables,
            linguistic_variables=variables, consequent_type="crisp", rule_mode=p.rule_mode,
            tolerance=p.tolerance, backend=p.backend, **p.estimator_options(),
        )
        estimator.fit(X[self.feature_names], y, n_gen=p.n_gen, pop_size=p.pop_size, random_state=seed)
        self.fit_info = {
            "train_fitness": float(estimator.performance_),
            "n_generations_run": int(estimator.n_generations_run_),
            "backend": str(estimator.backend_),
            "n_train_rows": int(values.shape[0]),
        }
        del estimator.optimization_result_
        self.estimator, self.seed = estimator, seed
        return self

    def get_rulebase(self) -> RuleBaseT1Regression:
        if self.estimator is None:
            raise RuntimeError("fit first")
        return self.estimator.get_rulebase()

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Model output per row; NaN where an input is missing or not finite (no inference is run)."""
        values = X[self.feature_names].to_numpy(dtype=float)
        finite = np.isfinite(values).all(axis=1)
        out = np.full(values.shape[0], np.nan)
        if finite.any():
            out[finite] = self.estimator.predict(X.loc[finite, self.feature_names])
        return out
