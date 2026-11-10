"""Fuzzy regressor with detection-limit terms for the water dissolved-oxygen task (AT-041f).

Kept out of ``atlas.ml.experiment_water`` on purpose: a model pickled from a module run as ``__main__`` cannot be
unpickled by ``atlas.services.publish``; the class has to live in an importable module.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import utils
from ex_fuzzy.evolutionary_fit_regression import BaseFuzzyRulesRegressor

from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor
from atlas.ml.partitions import build_variables


def censored_variable(name: str, reference: np.ndarray, limit: float, n_above: int, unit: str | None
                      ) -> fs.fuzzyVariable:
    """A term exactly for "at or below the limit" plus ``n_above`` data-driven terms for the measured values above it.

    The table harmonises every censored or sub-limit result to ``limit`` (``docs/water/water_feasibility.md`` section
    3), so the first term is 1 at ``limit`` and falls to 0 at the smallest measured value above it (the reporting
    resolution): a crisp step on the data. The terms above are the ex_fuzzy quantile terms (20/40/60/80 %) of the
    reference values strictly above ``limit`` only; the first one starts at the smallest of those values.
    """
    ref = np.asarray(reference, dtype=float)
    ref = ref[np.isfinite(ref)]
    above = ref[ref > limit * (1 + 1e-9)]
    if len(above) < 10 * n_above:
        raise ValueError(f"{name}: only {len(above)} reference values above the limit {limit}")
    domain = [float(limit), float(above.max())]
    step = float(above.min() - limit)
    sets = [fs.FS("<=L", [limit, limit, limit, limit + step], domain)]
    var = utils.construct_partitions(above.reshape(-1, 1), n_partitions=n_above, detect_categorical=False)[0]
    first = float(above.min())
    for i, (label, term) in enumerate(zip(("Bajo>L", "Medio>L", "Alto>L"), var.linguistic_variables, strict=False)):
        params = [float(p) for p in term.membership_parameters]
        if i == 0:  # starts exactly at the smallest measured value above L, so it is 0 at L (no overlap with <=L)
            params[0] = params[1] = first
        sets.append(fs.FS(label, params, domain))
    return fs.fuzzyVariable(name, sets, unit)


def load_censored(path: Path) -> dict[str, dict]:
    """``censored`` entries of a partitions file, by feature: ``limit``, ``n_above``."""
    document = json.loads(Path(path).read_text())
    return {f: entry for entry in document.get("censored", []) for f in entry["features"]}


class WaterFuzzyRegressor(FuzzyRegressor):
    """``FuzzyRegressor`` with fixed terms and detection-limit terms (partitions from the fitting split's train)."""

    def __init__(self, params: FuzzyParams | None = None, feature_units: dict[str, str] | None = None,
                 censored: dict[str, dict] | None = None):
        super().__init__(params, feature_units)
        self.censored = dict(censored or {})

    def fit(self, X: pd.DataFrame, y, seed: int, partition_reference: pd.DataFrame | None = None,
            fixed: dict | None = None) -> WaterFuzzyRegressor:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a DataFrame so that feature names are explicit")
        self.feature_names = [str(c) for c in X.columns]
        p = self.params
        ref = (partition_reference[self.feature_names] if partition_reference is not None else X).to_numpy(float)
        keep = [n for n in self.feature_names if n not in self.censored]
        by_name = dict(zip(keep, build_variables(
            ref[:, [self.feature_names.index(n) for n in keep]], keep,
            {n: fp for n, fp in (fixed or {}).items() if n in keep}, p.n_linguistic_variables, self.feature_units),
            strict=True))
        for name, spec in self.censored.items():
            if name in self.feature_names:
                by_name[name] = censored_variable(name, ref[:, self.feature_names.index(name)], spec["limit"],
                                                  spec["n_above"], self.feature_units.get(name))
        variables = [by_name[n] for n in self.feature_names]
        self.variables_summary = {
            v.name: {s.name: [float(q) for q in s.membership_parameters] for s in v.linguistic_variables}
            for v in variables}
        estimator = BaseFuzzyRulesRegressor(
            nRules=p.nRules, nAnts=p.nAnts, n_linguistic_variables=p.n_linguistic_variables,
            linguistic_variables=variables, consequent_type="crisp", rule_mode=p.rule_mode,
            tolerance=p.tolerance, backend=p.backend, **p.estimator_options(),
        )
        estimator.fit(X[self.feature_names], y, n_gen=p.n_gen, pop_size=p.pop_size, random_state=seed)
        self.fit_info = {
            "train_fitness": float(estimator.performance_), "n_generations_run": int(estimator.n_generations_run_),
            "backend": str(estimator.backend_), "n_train_rows": int(len(X)),
            "terms_per_variable": {v.name: len(v.linguistic_variables) for v in variables},
        }
        del estimator.optimization_result_
        self.estimator, self.seed = estimator, seed
        return self


