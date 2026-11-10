"""Scaling benchmark of the ex_fuzzy GA fit: wall time and peak RSS versus the number of training rows.

Each size runs in a fresh subprocess so that ``ru_maxrss`` is the peak of that fit alone. Sequential, CPU
(``backend="pymoo"``). Usage::

    python -m atlas.ml.benchmark --sizes 10000 50000 200000 --n-gen 20 --pop-size 30 --out bench.json

Data are invented (gamma / normal features, a smooth nonlinear target): only the cost is meaningful.
"""

from __future__ import annotations

import argparse
import json
import pickle
import resource
import subprocess
import sys
import time

import numpy as np
import pandas as pd

N_FEATURES = 10


def _child(n_rows: int, n_gen: int, pop_size: int, n_rules: int, n_ants: int, seed: int) -> dict:
    from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor

    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {f"x{i}": (rng.gamma(2.0 + i, 5.0, n_rows) if i % 2 else rng.normal(i, 3.0, n_rows)) for i in range(N_FEATURES)}
    )
    y = 0.5 * X["x1"] - 2.0 * np.sin(X["x0"]) + 0.1 * X["x2"] * X["x3"] / 10 + rng.normal(0, 1, n_rows)
    baseline_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    model = FuzzyRegressor(FuzzyParams(nRules=n_rules, nAnts=n_ants, n_gen=n_gen, pop_size=pop_size))
    start = time.perf_counter()
    model.fit(X, y.to_numpy(), seed=seed)
    fit_seconds = time.perf_counter() - start
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    start = time.perf_counter()
    pred = model.predict(X)
    predict_seconds = time.perf_counter() - start
    return {
        "n_rows": n_rows, "n_features": N_FEATURES, "nRules": n_rules, "nAnts": n_ants, "n_gen": n_gen,
        "pop_size": pop_size, "fit_seconds": round(fit_seconds, 2),
        "fit_seconds_per_generation": round(fit_seconds / n_gen, 3),
        "predict_seconds": round(predict_seconds, 3), "peak_rss_mb": round(peak_rss, 0),
        "rss_before_fit_mb": round(baseline_rss, 0), "pickle_bytes": len(pickle.dumps(model)),
        "n_rules_fitted": len(model.get_rulebase().rules),
        "train_r2": round(float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 3),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=[10_000, 50_000, 200_000])
    parser.add_argument("--n-gen", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=30)
    parser.add_argument("--n-rules", type=int, default=20)
    parser.add_argument("--n-ants", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", help="write the JSON results here")
    parser.add_argument("--child", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        print(json.dumps(_child(args.child, args.n_gen, args.pop_size, args.n_rules, args.n_ants, args.seed)))
        return
    results = []
    for n in args.sizes:
        cmd = [sys.executable, "-m", "atlas.ml.benchmark", "--child", str(n), "--n-gen", str(args.n_gen),
               "--pop-size", str(args.pop_size), "--n-rules", str(args.n_rules), "--n-ants", str(args.n_ants),
               "--seed", str(args.seed)]
        results.append(json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout))
        print(json.dumps(results[-1]), flush=True)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)


if __name__ == "__main__":
    main()
