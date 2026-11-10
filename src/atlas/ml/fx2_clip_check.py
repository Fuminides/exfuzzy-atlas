"""Reproduction check of FX2 (``docs/ml/fx2_proportional_remap.md``): run an experiment with the PR 35 remap undone.

The integration build 915b836 maps a term gene ``g`` of a variable with ``n`` terms (largest partition ``M``) to term
``(g * n) // M``; 2ffcfb9 and 3.3.1 clip it to ``min(g, n - 1)``. The two agree only when ``n == M``. This module
replaces the remap, in every decoder that is run on the CPU (``FitRuleBase``, the array and the population decoders),
by the clip, then calls ``atlas.ml.experiment_class`` with the same arguments::

    python -m atlas.ml.fx2_clip_check select --config configs/ml/fx2_madrid_no2_h6_hour4_clip_check_experiment.json

If everything else that 2ffcfb9 and 915b836 differ in (PR 34, the stability diagnostics) leaves a fit unchanged, the
result is bit-for-bit that of 2ffcfb9. It is a check, never a way to fit a model: the manifest would still say 915b836.
The PyTorch objective of ex_fuzzy is not patched and is not used by these experiments.

``digest`` is the second check: a small fit in which every variable has the same number of terms (``n == M``, where the
remap is the identity), printed as a hash of its rule base. Run it on 2ffcfb9 and on 915b836 (``PYTHONPATH``): the two
lines must be identical::

    PYTHONPATH=<ex-fuzzy checkout>:src python -m atlas.ml.fx2_clip_check digest
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np


def clip_term(gene: int, n_terms: int, max_terms: int) -> int:
    """The decoding of 3.3.1 / PR 32: ``-1`` stays, an index above the last term clips to it."""
    return gene if gene < 0 else min(gene, n_terms - 1)


def clip_terms(genes: np.ndarray, n_terms: np.ndarray, max_terms: int) -> np.ndarray:
    """Array form of :func:`clip_term` (``n_terms`` broadcasts against ``genes``)."""
    return np.where(genes < 0, genes, np.minimum(genes, n_terms - 1))


def undo_remap() -> None:
    """Make every ex_fuzzy decoder clip instead of remapping proportionally (idempotent)."""
    from ex_fuzzy import _array_fitness, _fitness, _population_fitness, evolutionary_fit

    for module, name, replacement in ((_fitness, "remap_term", clip_term), (_fitness, "remap_terms", clip_terms),
                                      (_array_fitness, "remap_terms", clip_terms),
                                      (_population_fitness, "remap_terms", clip_terms),
                                      (evolutionary_fit, "remap_term", clip_term)):
        if not hasattr(module, name):
            raise RuntimeError(f"{module.__name__}.{name} not found: this ex_fuzzy build has no PR 35 remap to undo")
        setattr(module, name, replacement)


def digest(n_terms: int = 4, seed: int = 0) -> str:
    """``<ex_fuzzy path> <hash of the fitted rules and weights> <train accuracy>`` of a small equal-count fit."""
    import ex_fuzzy
    import pandas as pd
    from ex_fuzzy import fuzzy_sets as fs
    from ex_fuzzy import utils
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier

    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.random((600, 6)), columns=[f"x{i}" for i in range(6)])
    y = np.digitize(X["x0"] + 0.5 * X["x1"] - 0.3 * X["x4"] + 0.1 * rng.standard_normal(600), [0.3, 0.7, 1.0])
    variables = [utils.construct_partitions(X[[c]], fs.FUZZY_SETS.t1, n_partitions=n_terms)[0] for c in X.columns]
    clf = BaseFuzzyRulesClassifier(nRules=12, nAnts=3, n_linguistic_variables=n_terms, linguistic_variables=variables,
                                   ds_mode=2, backend="numpy", n_gen=25, pop_size=24, random_state=seed)
    clf.fit(X.to_numpy(), y)
    master = clf.rule_base
    rows = [(int(c), tuple(int(a) for a in rule.antecedents), round(float(w), 12))
            for rule, c, w in zip(master.get_rules(), master.get_consequents(), master.get_weights(), strict=True)]
    accuracy = float((clf.predict(X.to_numpy()) == y).mean())
    sha = hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
    return f"{ex_fuzzy.__file__} {sha} {accuracy:.6f} rules={len(rows)}"


def main(argv: list[str] | None = None) -> None:
    from atlas.ml import experiment_class

    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["digest"]:
        print(digest())
        return
    undo_remap()
    experiment_class.main(argv)


if __name__ == "__main__":
    main()
