"""One adapter over the three ex_fuzzy families: firing, memberships and the outputs the pred shards carry.

Everything numeric comes from ``atlas.explain`` (the engine the API's rule-trace runs), in batches of ``BATCH`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from atlas.contracts import models as m
from atlas.explain import (
    compute_activations,
    compute_classifier_activations,
    compute_mixture_activations,
    get_master_rulebase,
    get_rulebase,
)
from atlas.explain import feature_names as tsk_feature_names
from atlas.explain.classifier import feature_names as class_feature_names

BATCH = 100_000  # rows per engine call; the task allows at most 200k with ~1 GB of peak memory


@dataclass
class Activations:
    fire: np.ndarray  # (n, R)
    mem: list  # per feature (antecedent order): (terms, n)
    out: dict[str, np.ndarray]  # the output columns of a pred shard, per row: pred, plabel, decided, top, tshare


def antecedent_features(model, family: m.InferenceFamily) -> list[str]:
    """Feature names in the order the engine wants its columns (and the order of ``Activations.mem``)."""
    if family == m.InferenceFamily.TSK_ZERO_ORDER:
        return tsk_feature_names(get_rulebase(model))
    return class_feature_names(get_master_rulebase(model))


def term_names(model, family: m.InferenceFamily) -> list[list[str]]:
    rb = get_rulebase(model) if family == m.InferenceFamily.TSK_ZERO_ORDER else get_master_rulebase(model)
    return [list(v.linguistic_variable_names()) for v in rb.antecedents]


def activate(model, family: m.InferenceFamily, X: np.ndarray) -> Activations:
    """Engine outputs for finite rows ``X`` (columns in ``antecedent_features`` order)."""
    X = np.asarray(X, dtype=float)
    if family == m.InferenceFamily.TSK_ZERO_ORDER:
        act = compute_activations(get_rulebase(model), X, with_prediction=True)
        if not np.array_equal(act.raw, act.effective):
            raise ValueError("only additive TSK models are exported (effective_firing == firing_strength)")
        return Activations(act.raw, act.memberships, {"pred": np.asarray(act.prediction, dtype=float)})
    if family == m.InferenceFamily.WINNING_RULE_CLASSIFIER:
        act = compute_classifier_activations(model, X)
        winner = np.asarray(act.winner, dtype=int)
        plabel = np.where(winner >= 0, np.asarray(act.prediction, dtype=int), -1)
        return Activations(act.firing, act.memberships, {"plabel": plabel, "decided": winner})
    if family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER:
        act = compute_mixture_activations(model, X, with_decisive=False)
        return Activations(
            act.firing, act.memberships,
            {"plabel": np.asarray(act.prediction, dtype=int), "top": np.asarray(act.top, dtype=int),
             "tshare": np.asarray(act.top_share, dtype=float)},
        )
    raise ValueError(f"unsupported inference family {family}")


def activate_batches(model, family, X: np.ndarray, pairs: list[tuple[int, int]], need_out: bool = False):
    """Memberships of ``pairs`` ``[(feature position, term position)]`` for finite rows, in batches.

    Returns ``(mem, fire, out)``: ``mem`` is (len(pairs), n); ``fire`` (n, R); ``out`` the output columns.
    """
    n = X.shape[0]
    mem = np.full((len(pairs), n), np.nan)
    fire = None
    out: dict[str, np.ndarray] = {}
    for lo in range(0, n, BATCH):
        part = slice(lo, min(lo + BATCH, n))
        act = activate(model, family, X[part])
        for p, (f, t) in enumerate(pairs):
            mem[p, part] = act.mem[f][t]
        if fire is None:
            fire = np.full((n, act.fire.shape[1]), np.nan)
        fire[part] = act.fire
        for key, col in act.out.items():
            out.setdefault(key, np.full(n, np.nan if col.dtype.kind == "f" else -1, dtype=col.dtype))[part] = col
    return mem, fire, out
