"""Cost of one GA generation of the ExFuzzy classifier, per row, on the CPU and on CUDA (AT-041g).

The helpers are generic (``time_repeated``, ``cost_per_row``, ``extrapolate_fit``). ``build_problem`` and
``time_generation`` rebuild the fitness problem that ``BaseFuzzyRulesClassifier.fit`` builds for fixed partitions
(ex_fuzzy 3.3.1) and time the routes that a fit can use to score one population:

``device``
    ``TorchObjective.score`` (the exact PyTorch objective of the EvoX backend), synchronised;
``cpu_batched``
    ``FitRuleBase._score_fresh_on_cpu``, the batched CPU evaluator inside a fit's cache scope;
``cpu_scalar``
    ``FitRuleBase._scalar_scores``, one candidate at a time.

These are private ex_fuzzy functions: the module is a measurement tool, not part of any served model, and breaks
loudly (``AttributeError``) if the library changes them.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence

import numpy as np


def time_repeated(fn: Callable[[], object], *, repeats: int = 3, warmup: int = 1,
                  sync: Callable[[], None] | None = None) -> dict:
    """Wall seconds of ``fn()``: ``warmup`` untimed calls, then ``repeats`` timed ones (``sync`` after each call)."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    for _ in range(max(0, warmup)):
        fn()
        if sync:
            sync()
    seconds = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        if sync:
            sync()
        seconds.append(time.perf_counter() - start)
    return {"seconds": seconds, "median": statistics.median(seconds), "min": min(seconds), "repeats": repeats}


def cost_per_row(seconds: float, n_rows: int, n_candidates: int) -> float:
    """Seconds per row and per candidate evaluated."""
    if n_rows <= 0 or n_candidates <= 0:
        raise ValueError("n_rows and n_candidates must be positive")
    return seconds / (n_rows * n_candidates)


def n_evaluations(n_gen: int, pop_size: int) -> int:
    """Candidates scored by a GA fit: the initial population plus ``pop_size`` offspring per generation.

    An upper bound for EvoX, which scores each distinct genotype once (a cache), and for pymoo (same population
    size per generation).
    """
    return pop_size * (n_gen + 1)


def extrapolate_fit(cost: float, n_rows: int, evaluations: int) -> float:
    """Seconds of a whole fit if cost is linear in rows: ``cost`` (s per row and candidate) x rows x evaluations."""
    return cost * n_rows * evaluations


def linearity(rows: Sequence[int], seconds: Sequence[float]) -> list[float]:
    """Ratio of each size's cost per row to that of the smallest size (1.0 everywhere = perfectly linear)."""
    per_row = [s / n for s, n in zip(seconds, rows, strict=True)]
    return [p / per_row[0] for p in per_row]


# ------------------------------------------------------------------------------------ the real problem


def build_problem(X: np.ndarray, y: np.ndarray, variables, *, n_rules: int, n_ants: int, n_classes: int,
                  ds_mode: int = 0, allow_unknown: bool = True, tolerance: float = 0.0):
    """The ``FitRuleBase`` that ``BaseFuzzyRulesClassifier.fit`` builds for fixed (precomputed) partitions."""
    from ex_fuzzy import rules
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier, FitRuleBase

    defaults = BaseFuzzyRulesClassifier(nRules=n_rules, nAnts=n_ants, linguistic_variables=variables)
    return FitRuleBase(
        np.asarray(X, dtype=float), np.asarray(y, dtype=int), nRules=n_rules, nAnts=n_ants, n_classes=n_classes,
        linguistic_variables=variables, tolerance=tolerance, alpha=defaults.alpha_, beta=defaults.beta_,
        ds_mode=rules.resolve_ds_mode(ds_mode), allow_unknown=allow_unknown, backend_name="evox",
        var_names=[str(v.name) for v in variables])


def random_population(problem, n: int, seed: int) -> np.ndarray:
    """``n`` chromosomes uniform within the gene bounds of ``problem`` (integers)."""
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(problem.xl, dtype=int), np.asarray(problem.xu, dtype=int)
    return rng.integers(lo, hi + 1, size=(n, len(lo)))


def cuda_sync() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.synchronize()


def device_objective(problem, device: str = "cuda"):
    """The exact torch objective for ``problem`` on ``device``, or ``None`` if the library declines it."""
    from ex_fuzzy import _torch_fitness as torchfit

    return torchfit.TorchObjective.build(problem, device)


def device_row_limit(problem, free_bytes: int, fraction: float = 0.35) -> int:
    """Largest number of rows for which the library's own memory formula allows one candidate per chunk.

    ``per_candidate = 8 * rows * 16 * rules + 2 * rules ** 2 * features`` must fit in ``fraction`` of the free CUDA
    memory (``TorchObjective.build`` returns ``None`` otherwise). Mirrors ``_torch_fitness.py`` of ex_fuzzy 3.3.1.
    """
    budget = int(free_bytes * fraction)
    fixed = 2 * problem.nRules**2 * problem.X.shape[1]
    return max(0, (budget - fixed) // (8 * 16 * problem.nRules))


def time_generation(problem, genes: np.ndarray, *, repeats: int = 3, routes: Sequence[str] = ("device", "cpu_batched"),
                    device: str = "cuda") -> dict:
    """Seconds to score ``genes`` (one generation, nothing cached) on each route.

    The CPU routes run in a fresh fit cache scope per call, so neither the fitness cache nor the firing cache carries
    over between repeats: the figure is the cost of a *cold* generation, an upper bound for a real fit, whose offspring
    share rules with their parents. A route the library cannot run on this problem is reported with its reason.

    Returns ``{route: {"median": s, "seconds": [...], "per_row_candidate": c} | {"declined": reason}}``.
    """
    from ex_fuzzy._fitness import _fitness_cache_scope

    n_rows, n = len(problem.X), len(genes)
    out: dict = {"n_rows": int(n_rows), "n_candidates": int(n)}
    for route in routes:
        sync = None
        if route == "device":
            objective = device_objective(problem, device)
            if objective is None:
                out[route] = {"declined": "TorchObjective.build returned None (one candidate's scratch does not "
                                          "fit in 35 % of the free CUDA memory)"}
                continue

            def fn(objective=objective):
                return objective.score(genes)
            sync = cuda_sync
        elif route in ("cpu_batched", "cpu_scalar"):
            def fn(route=route):
                with _fitness_cache_scope(problem, True, n):
                    if route == "cpu_scalar":
                        return problem._scalar_scores(genes)
                    return problem._batched_scores(genes)
            if route == "cpu_batched":
                with _fitness_cache_scope(problem, True, n):
                    if problem._batched_scores(genes[:2]) is None:
                        out[route] = {"declined": "the batched CPU evaluator declines this problem (chunk < 2)"}
                        continue
        else:
            raise ValueError(f"unknown route {route!r}")
        result = time_repeated(fn, repeats=repeats, warmup=1, sync=sync)
        result["per_row_candidate"] = cost_per_row(result["median"], n_rows, n)
        out[route] = result
    return out
