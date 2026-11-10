"""Wrapper around ``BaseFuzzyRulesClassifier`` (type-1, winning-rule inference) for ordinal class targets (AT-041c).

Decisions, all checked against ex_fuzzy 3.3.1 (see ``docs/ml/madrid_no2_h6_ica.md``):

* Partitions are built here (``detect_categorical=False``) from a reference frame, normally the *whole* training
  period, and passed as ``linguistic_variables``; the GA only chooses rules. Names, units and the fixed quantile
  terms are therefore independent of the class-aware subsample the GA sees.
* The prediction is the rule with the largest ``association = firing x rule weight`` (ex_fuzzy: ``ds_mode`` 0 =
  dominance score computed on the fitting rows, 1 = unweighted, 2 = weight found by the GA). With
  ``allow_unknown=False`` ex_fuzzy silently answers the class of rule 0 when no rule fires, so the wrapper
  defaults to ``allow_unknown=True`` and reports ``-1`` (no prediction).
* The GA fitness is the macro-F1 of the pruned rule base on the fitting rows minus small compactness and coverage
  penalties (ex_fuzzy defaults), i.e. already class-balance aware.
* ``fixed`` (AT-041d) replaces the quantile terms of some inputs by named bands (``atlas.ml.partitions``).
* Rows with a non-finite input are not sent to ex_fuzzy; ``predict`` returns ``-1`` for them.
* ``optimization_result_`` (the whole pymoo problem, i.e. the fitting data) is dropped after fitting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier

from atlas.ml.exfuzzy_features import require
from atlas.ml.partitions import FixedPartition, build_variables

PREDICT_CHUNK = 100_000  # rows per ex_fuzzy call (memberships, rows x rules x antecedents float64): bounds memory
DS_MODES = {"dominance_score": 0, "none": 1, "weight": 2}  # contract rule_weighting -> ex_fuzzy ds_mode


@dataclass(frozen=True)
class FuzzyClassifierParams:
    nRules: int = 30
    nAnts: int = 3
    n_linguistic_variables: int = 3
    rule_weighting: str = "dominance_score"
    allow_unknown: bool = True
    tolerance: float = 0.0
    n_gen: int = 100
    pop_size: int = 50
    patience: int | None = 20
    backend: str = "pymoo"
    batch_size: int | None = None  # minibatch fitness (ex-fuzzy PR 39); None = every row, every generation
    # Mixture of rules (ex_fuzzy ``inference='mixture'``, exfuzzy_features ``rule_mixture``); left out of ``as_dict``
    # with the default winning-rule inference, so manifests of the pinned release keep their hyperparameters.
    inference: str = "winning_rule"
    mixture_C: float = 1.0
    mixture_non_negative: bool = False
    mixture_search: bool = False
    # How mixture_search prunes (exfuzzy_features ``mixture_pruning``): "winning_rule", the pruning of every Atlas
    # mixture fitted before the option existed (so their configs refit the same models), or "mixture", by the rules'
    # role in the fitted mixture, deleting a rule whose largest centred contribution is at most the threshold.
    mixture_pruning: str = "winning_rule"
    mixture_prune_threshold: float = 0.02
    # ex_fuzzy ``ordinal_conditions`` (exfuzzy_features, PR 45): a rule may say ``x IS at least t`` / ``at most t``;
    # True for every input, or the names of the inputs that get it. ``compound_terms``: ``{input: [(name, [terms])]}``,
    # named unions of terms. Both are left out of ``as_dict`` when off, so manifests of the pinned release keep their
    # hyperparameters.
    ordinal_conditions: bool | tuple[str, ...] = False
    compound_terms: dict[str, list[tuple[str, list[str]]]] | None = None

    def as_dict(self) -> dict:
        out = asdict(self)
        if not self.ordinal_conditions:
            del out["ordinal_conditions"]
        if not self.compound_terms:
            del out["compound_terms"]
        if self.inference == "winning_rule" and not self.mixture_search:
            for key in MIXTURE_OPTIONS:
                del out[key]
        if not self.mixture_search:
            del out["mixture_pruning"]
        if not self.mixture_search or self.mixture_pruning != "mixture":
            del out["mixture_prune_threshold"]
        return out

    def estimator_options(self) -> dict:
        """Extra ``BaseFuzzyRulesClassifier`` arguments; refuses a library without them instead of ignoring them."""
        if self.inference == "winning_rule" and not self.mixture_search:
            return self.ordinal_options()
        require("rule_mixture")
        options = {key: getattr(self, key) for key in MIXTURE_OPTIONS} | self.ordinal_options()
        if self.mixture_search:
            require("mixture_pruning")
            options["mixture_pruning"] = self.mixture_pruning
            options["mixture_prune_threshold"] = self.mixture_prune_threshold
        return options

    def ordinal_options(self) -> dict:
        """The ex_fuzzy ``ordinal_conditions`` / ``compound_terms`` arguments that are on (refusing a library without
        them), else nothing."""
        options = {}
        if self.ordinal_conditions:
            require("ordinal_conditions")
            options["ordinal_conditions"] = (self.ordinal_conditions if self.ordinal_conditions is True
                                             else list(self.ordinal_conditions))
        if self.compound_terms:
            require("compound_terms")
            options["compound_terms"] = self.compound_terms
        return options


MIXTURE_OPTIONS = ("inference", "mixture_C", "mixture_non_negative", "mixture_search")


class FuzzyClassifier:
    """A fitted-or-not winning-rule classifier with explicit feature names, units and ordered class labels."""

    def __init__(self, params: FuzzyClassifierParams | None = None, feature_units: dict[str, str] | None = None):
        self.params = params or FuzzyClassifierParams()
        self.feature_units = dict(feature_units or {})
        self.estimator: BaseFuzzyRulesClassifier | None = None
        self.feature_names: list[str] = []
        self.class_labels: list[str] = []
        self.seed: int | None = None
        self.fit_info: dict = {}

    def fit(self, X: pd.DataFrame, y: np.ndarray, class_labels: list[str], seed: int,
            partition_reference: pd.DataFrame | None = None,
            fixed: dict[str, FixedPartition] | None = None) -> FuzzyClassifier:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a DataFrame so that feature names are explicit")
        self.feature_names = [str(c) for c in X.columns]
        self.class_labels = list(class_labels)
        values = X.to_numpy(dtype=float)
        ref = (partition_reference[self.feature_names] if partition_reference is not None else X).to_numpy(float)
        fixed = dict(fixed or {})
        constant = [n for n, col in zip(self.feature_names, ref.T, strict=True)
                    if n not in fixed and np.ptp(col) == 0]
        if constant:
            raise ValueError(f"constant training features cannot be partitioned: {constant}")
        p = self.params
        variables = build_variables(ref, self.feature_names, fixed, p.n_linguistic_variables, self.feature_units)
        y = np.asarray(y, dtype=int)
        absent = sorted(set(range(len(self.class_labels))) - set(np.unique(y).tolist()))
        if absent:
            raise ValueError(f"classes without any fitting row: {[self.class_labels[i] for i in absent]}")
        extra = {} if p.batch_size is None else {"batch_size": p.batch_size}  # 3.3.1 has no such argument
        extra.update(p.estimator_options())
        estimator = BaseFuzzyRulesClassifier(
            nRules=p.nRules, nAnts=p.nAnts, n_linguistic_variables=p.n_linguistic_variables,
            linguistic_variables=variables, class_names=self.class_labels, tolerance=p.tolerance,
            ds_mode=DS_MODES[p.rule_weighting], allow_unknown=p.allow_unknown, backend=p.backend,
            n_gen=p.n_gen, pop_size=p.pop_size, patience=p.patience, random_state=seed, **extra,
        )
        estimator.fit(X[self.feature_names].to_numpy(dtype=float), y)
        self.fit_info = {
            "train_fitness_macro_f1_penalised": float(np.max(estimator.performance)),
            "n_generations_run": int(estimator.n_generations_run_),
            "stopped_early": bool(estimator.stopped_early_),
            "backend": str(estimator.backend.name()),
            "n_train_rows": int(values.shape[0]),
            "train_class_counts": np.bincount(y, minlength=len(self.class_labels)).tolist(),
            "fixed_partitions": {f: [b.name for b in fp.bands] for f, fp in fixed.items()},
        }
        result = estimator.optimization_result_
        if isinstance(result, dict) and "gpu_accelerated" in result:  # EvoX backend: did a device score the fit?
            self.fit_info.update({"device": str(result.get("device")),
                                  "gpu_accelerated": bool(result["gpu_accelerated"])})
        del estimator.optimization_result_
        self.estimator, self.seed = estimator, seed
        return self

    @property
    def rule_base(self):
        """The ex_fuzzy ``MasterRuleBase`` (rules are class-major: all rules of class 0 first, ...)."""
        if self.estimator is None:
            raise RuntimeError("fit first")
        return self.estimator.rule_base

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Class index per row (``-1`` = no rule fired, or a missing input: no inference is run for those)."""
        values = X[self.feature_names].to_numpy(dtype=float)
        finite = np.isfinite(values).all(axis=1)
        out = np.full(values.shape[0], -1, dtype=int)
        rows = np.flatnonzero(finite)
        for start in range(0, len(rows), PREDICT_CHUNK):  # rows are independent: chunking only bounds memory
            part = rows[start:start + PREDICT_CHUNK]
            out[part] = self.estimator.predict(values[part])
        return out

    def predict_labels(self, X: pd.DataFrame) -> np.ndarray:
        """Class label per row as an object array; ``None`` where ``predict`` gives ``-1`` (no prediction)."""
        pred = self.predict(X)
        return np.array([*self.class_labels, None], dtype=object)[np.where(pred < 0, len(self.class_labels), pred)]
