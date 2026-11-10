"""Checks used by the FX retrain (docs/ml/fx_retrain_with_fixed_exfuzzy.md); none is needed to serve a model.

* ``classifier_term_usage``: how many antecedents of a fitted winning-rule classifier use each term of each variable
  (the term-index distribution; with ex_fuzzy 3.3.1 the extra terms of a larger variable are never used).
* ``consequent_support``: for a fitted TSK regressor, whether each rule's consequent lies inside the range of the
  observed target on the rows the rule actually covers (a descriptive plausibility check, not a validity test).
* ``decoded_term_table``: which term each term gene decodes to in the installed ex_fuzzy (clip on 3.3.1 / PR 32,
  proportional on PR 35), i.e. the prior of the search before any selection (FX2).
* ``breakpoint_parity``: how close ``ex_fuzzy.utils.construct_breakpoint_partition`` (upstream PR 31) can get to an
  Atlas ``FixedPartition``; needs the integration build (``exfuzzy_features.has_breakpoint_partition``).
"""

from __future__ import annotations

import numpy as np

from atlas.explain import compute_activations
from atlas.explain.classifier import feature_names as classifier_feature_names
from atlas.explain.classifier import get_master_rulebase
from atlas.ml.exfuzzy_features import rule_conditions
from atlas.ml.partitions import FixedPartition, fixed_variable


def classifier_term_usage(model) -> dict[str, dict[str, int]]:
    """``{feature: {term: number of antecedents using it}}`` over the rules of a classifier, terms in index order.

    Every term of every variable appears (count 0 when unused), so a term that the search could not reach is visible.
    An ordinal condition (ex_fuzzy ``ordinal_conditions``) is counted under its own text, ``at least <term>`` or
    ``at most <term>``, which appears only where it is used.
    """
    rb = get_master_rulebase(model)
    names = classifier_feature_names(rb)
    out = {name: dict.fromkeys(map(str, var.linguistic_variable_names()), 0)
           for name, var in zip(names, rb.antecedents, strict=True)}
    for rule in rb.get_rules():
        for c in rule_conditions(rule, rb.antecedents):
            out[names[c.feature]][c.text] = out[names[c.feature]].get(c.text, 0) + 1
    return out


def decoded_term_table(term_counts: list[int]) -> list[list[int]]:
    """Per variable (``term_counts[i]`` terms), the term that each term gene ``0..max(term_counts) - 1`` decodes to.

    Built by decoding one-rule, one-antecedent chromosomes with ``FitRuleBase._construct_ruleBase`` of the installed
    ex_fuzzy, so it is what the fit does: the clip on 3.3.1 and PR 32 (``[0, 1, 2, 2, 2]`` for 3 terms under a maximum
    of 5), the proportional map of PR 35 (``[0, 0, 1, 1, 2]``). Genes are drawn uniformly over ``0..max - 1`` (and
    ``-1`` is "don't care"), so the share of a term in the prior of the search is its number of genes / ``max``.
    """
    import pandas as pd
    from ex_fuzzy import fuzzy_sets as fs
    from ex_fuzzy import utils
    from ex_fuzzy.evolutionary_fit import FitRuleBase

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((60, len(term_counts))), columns=[f"v{i}" for i in range(len(term_counts))])
    variables = [utils.construct_partitions(X[[c]], fs.FUZZY_SETS.t1, n_partitions=k)[0]
                 for c, k in zip(X.columns, term_counts, strict=True)]
    problem = FitRuleBase(X.to_numpy(), (X["v0"] > 0.5).astype(int).to_numpy(), nRules=1, nAnts=1, n_classes=2,
                          linguistic_variables=variables)
    top = int(np.asarray(problem.xu)[1]) + 1  # the bound of the term gene of the only slot
    return [[int(problem._construct_ruleBase(np.array([f, g, 0]), fs.FUZZY_SETS.t1).get_rules()[0].antecedents[f])
             for g in range(top)] for f in range(len(term_counts))]


def consequent_support(rulebase, X: np.ndarray, y: np.ndarray, *, min_firing: float = 0.5,
                       interval: tuple[float, float] = (0.05, 0.95), min_rows: int = 30) -> list[dict]:
    """Per rule (in order): the observed-target interval of the rows it covers and where its consequent falls.

    Covered rows are those with raw firing >= ``min_firing``; the interval is the ``interval`` quantiles of ``y`` on
    them. ``status`` is ``"within"``, ``"outside"`` or ``"no_support"`` (fewer than ``min_rows`` covered rows). In an
    additive TSK a consequent is not the mean of its rows (rules compensate each other), so ``outside`` flags a rule
    that is hard to read on its own, not a wrong model.
    """
    X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
    firing = compute_activations(rulebase, X, with_prediction=False).raw
    out = []
    for r, value in enumerate(np.asarray(rulebase.scalar_consequents, dtype=float)):
        covered = firing[:, r] >= min_firing
        n = int(covered.sum())
        if n < min_rows:
            out.append({"rule": r, "consequent": float(value), "n_covered": n, "lo": None, "hi": None,
                        "mean": None, "status": "no_support"})
            continue
        lo, hi = (float(q) for q in np.quantile(y[covered], interval))
        out.append({"rule": r, "consequent": float(value), "n_covered": n, "lo": lo, "hi": hi,
                    "mean": float(y[covered].mean()), "status": "within" if lo <= value <= hi else "outside"})
    return out


def breakpoint_parity(partition: FixedPartition, scales: np.ndarray | None = None, n_grid: int = 4001) -> dict:
    """Closest ``construct_breakpoint_partition`` to an Atlas ``FixedPartition``, by max membership difference.

    The breakpoint of each boundary is the midpoint between the upper edge of a band's core and the lower edge of the
    next; the ramp width at each boundary is ``scale`` x (the boundary shoulder + the gap between the cores), and
    ``scale`` is searched on ``scales`` (default 0.05..4 in steps of 0.05; a ramp must be
    positive). Returns the best scale, the max absolute membership difference over a dense grid of the domain (overall
    and per term), whether the trapezoid parameters are identical, and the Atlas and library parameters.
    """
    from ex_fuzzy import utils

    names = [b.name for b in partition.bands]
    lo, hi = partition.domain
    gaps = [right.lower - left.upper for left, right in zip(partition.bands, partition.bands[1:], strict=False)]
    breaks = [(left.upper + right.lower) / 2 for left, right in zip(partition.bands, partition.bands[1:], strict=False)]
    base = [w + g for w, g in zip(partition.boundary_shoulders, gaps, strict=True)]
    atlas = fixed_variable(partition)
    grid = np.linspace(lo, hi, n_grid)
    reference = np.asarray(atlas.compute_memberships(grid), dtype=float)
    best = None
    for scale in (np.arange(0.05, 4.0001, 0.05) if scales is None else scales):
        try:
            candidate = utils.construct_breakpoint_partition(
                partition.feature, names, breaks, [lo, hi], [float(scale * b) for b in base])
        except ValueError:  # ramps outside the domain or overlapping
            continue
        diff = np.abs(np.asarray(candidate.compute_memberships(grid), dtype=float) - reference)
        if best is None or diff.max() < best[0]:
            best = (float(diff.max()), float(scale), candidate, diff.max(axis=1))
    if best is None:
        raise ValueError("no valid breakpoint partition in the searched scales")
    err, scale, candidate, per_term = best
    atlas_params = [[float(q) for q in s.membership_parameters] for s in atlas.linguistic_variables]
    library_params = [[float(q) for q in s.membership_parameters] for s in candidate.linguistic_variables]
    return {
        "feature": partition.feature, "best_scale": scale, "max_abs_difference": err,
        "max_abs_difference_by_term": dict(zip(names, map(float, per_term), strict=True)),
        "identical_parameters": bool(np.allclose(atlas_params, library_params)),
        "atlas_parameters": dict(zip(names, atlas_params, strict=True)),
        "library_parameters": dict(zip(names, library_params, strict=True)),
    }
