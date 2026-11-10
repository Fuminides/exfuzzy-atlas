"""Learning curve and full-data fitting of the Madrid ICA classifier (AT-041g).

Protocol: ``docs/ml/madrid_no2_h6_learning_curve.md``.

::

    python -m atlas.ml.learning_curve feasibility --config configs/ml/madrid_no2_h6_learning_curve.json
    python -m atlas.ml.learning_curve fit   --config configs/ml/madrid_no2_h6_learning_curve.json [--arms n30k n60k ...]
    python -m atlas.ml.learning_curve report --config configs/ml/madrid_no2_h6_learning_curve.json

Everything is validation-only: the test period is never indexed. The experiment is the AT-041d fit
(``base_config``: table, split, class merge, ``justified`` partitions) with the fitting rows varied by arm and the GA
backend chosen in the config. Results are resumable JSON files under
``<artifacts>/<task>/experiments/<experiment_id>/``; nothing outside that directory is written.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.ml import eval_timing
from atlas.ml.class_baselines import SklearnClassBaseline, logistic_regression_baseline, random_forest_baseline
from atlas.ml.classification import class_sample, classification_metrics, nested_class_sample
from atlas.ml.evaluation import PeakRss, classifier_rule_sets, current_rss_mb, rule_set_stability
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.experiment import experiment_dir
from atlas.ml.experiment_class import (
    RF_FULL_MAX_SAMPLES,
    Candidate,
    ClassData,
    ClassExperimentConfig,
    _summary,
)
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.partitions import build_variables
from atlas.paths import ARTIFACTS_DIR, REPO_ROOT

SAMPLERS = ("nested", "published", "all")


class Arm(BaseModel):
    """Fitting rows of one arm. ``sampler``: ``nested`` (prefixes of one ordering), ``published`` (the AT-041d draw),
    ``all`` (every complete training row, natural prior; ``n_rows`` is ignored)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    sampler: str = "nested"
    n_rows: int | None = None
    power: float = 0.5
    seeds: list[int] | None = None  # default: the config's seeds
    baselines: bool = True
    batch_size: int | None = None  # minibatch fitness (needs the integration build and the pymoo backend)


class LearningCurveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    base_config: str  # AT-041d experiment config, relative to the repository root
    shape: Candidate  # nRules / nAnts / terms / weighting (sampling_power is per arm)
    n_gen: int
    pop_size: int
    seeds: list[int]
    backend: str = "evox"
    subsample_seed: int = 20260101
    arms: list[Arm]
    timing_rows: list[int] = [30000, 120000, 0]  # 0 = every complete training row


def _log(text: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def load_config(path: Path) -> tuple[LearningCurveConfig, ClassExperimentConfig]:
    config = LearningCurveConfig.model_validate_json(Path(path).read_text())
    base = REPO_ROOT / config.base_config
    return config, ClassExperimentConfig.model_validate_json(base.read_text())


def arm_rows(cd: ClassData, arm: Arm, subsample_seed: int) -> np.ndarray:
    """Positions in ``cd.data.frame`` of the fitting rows of ``arm`` (training period only)."""
    d = cd.data
    if arm.sampler == "all":
        return d.train_pos
    if arm.sampler not in SAMPLERS or not arm.n_rows:
        raise ValueError(f"arm {arm.name}: sampler {arm.sampler!r} needs n_rows")
    draw = nested_class_sample if arm.sampler == "nested" else class_sample
    pos = d.train_pos
    picked = draw(cd.y_class[pos], d.frame["entity_id"].to_numpy()[pos], d.issued[pos], arm.n_rows, subsample_seed,
                  arm.power)
    return pos[picked]


def _params(config: LearningCurveConfig, batch_size: int | None = None) -> FuzzyClassifierParams:
    s = config.shape
    return FuzzyClassifierParams(
        nRules=s.nRules, nAnts=s.nAnts, n_linguistic_variables=s.n_linguistic_variables,
        rule_weighting=s.rule_weighting, n_gen=config.n_gen, pop_size=config.pop_size, patience=None,
        backend=config.backend, batch_size=batch_size)


def _gpu_peak_mb() -> dict:
    import torch

    if not torch.cuda.is_available():
        return {}
    return {"gpu_peak_allocated_mb": torch.cuda.max_memory_allocated() / 2**20,
            "gpu_peak_reserved_mb": torch.cuda.max_memory_reserved() / 2**20}


def _reset_gpu_peak() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()


class _MinibatchClock:
    """Splits the wall time of a minibatch fit: optimiser start, end of the last generation (``finish`` of the batch
    schedule, after which the final population is scored on every row), end of the optimiser."""

    def __enter__(self):
        from ex_fuzzy import _fitness
        from ex_fuzzy.evolutionary_backends import PyMooBackend

        self.marks: dict[str, float] = {}
        self._targets = [(_fitness.MinibatchSchedule, "finish", "generations_end"),
                         (PyMooBackend, "optimize", None)]
        self._originals = [getattr(owner, name) for owner, name, _ in self._targets]
        marks = self.marks

        def wrap_finish(original):
            def finish(obj, *a, **k):
                marks["generations_end"] = time.perf_counter()
                return original(obj, *a, **k)
            return finish

        def wrap_optimize(original):
            def optimize(obj, *a, **k):
                marks["optimizer_start"] = time.perf_counter()
                try:
                    return original(obj, *a, **k)
                finally:
                    marks["optimizer_end"] = time.perf_counter()
            return optimize

        _fitness.MinibatchSchedule.finish = wrap_finish(self._originals[0])
        PyMooBackend.optimize = wrap_optimize(self._originals[1])
        return self

    def __exit__(self, *exc):
        for (owner, name, _), original in zip(self._targets, self._originals, strict=True):
            setattr(owner, name, original)

    def seconds(self, n_gen: int) -> dict:
        m = self.marks
        return {"seconds_per_generation": (m["generations_end"] - m["optimizer_start"]) / n_gen,
                "final_scoring_seconds": m["optimizer_end"] - m["generations_end"]}


def fit_one(config: LearningCurveConfig, cd: ClassData, rows: np.ndarray, seed: int, reference: pd.DataFrame,
            validation: tuple[pd.DataFrame, np.ndarray], batch_size: int | None = None) -> dict:
    """One ExFuzzy fit on ``rows`` and its validation scores, time, CPU RSS and GPU memory."""
    base, d = cd.config.base, cd.data
    X_val, y_val = validation
    _reset_gpu_peak()
    clock = _MinibatchClock() if batch_size else None
    with PeakRss() as rss:
        start = time.perf_counter()
        if clock:
            clock.__enter__()
        try:
            model = FuzzyClassifier(_params(config, batch_size), base.feature_units).fit(
                d.frame.loc[rows, base.features], cd.y_class[rows], cd.labels, seed, partition_reference=reference,
                fixed=cd.fixed)
        finally:
            if clock:
                clock.__exit__()
        seconds = time.perf_counter() - start
    timing = clock.seconds(config.n_gen) if clock else {}
    gpu = _gpu_peak_mb() if config.backend == "evox" else {}
    pred = model.predict(X_val)
    rule_set = classifier_rule_sets(model, cd.labels)
    return {
        "seed": seed, "backend": config.backend, "batch_size": batch_size, "n_fit_rows": int(len(rows)), **timing,
        "fit_class_counts": np.bincount(cd.y_class[rows], minlength=len(cd.labels)).tolist(),
        "fit_seconds": seconds, "peak_rss_mb": rss.peak_mb, **gpu, "fit_info": model.fit_info,
        "n_rules": len(rule_set), "validation": _summary(classification_metrics(y_val, pred, len(cd.labels)),
                                                         cd.labels),
        "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rule_set],
    }


def _baselines(base, arm: Arm, seed: int) -> list[SklearnClassBaseline]:
    cap = RF_FULL_MAX_SAMPLES if arm.sampler == "all" else None
    return [
        random_forest_baseline("random_forest", base.features, seed=seed, max_samples=cap),
        random_forest_baseline("random_forest_balanced", base.features, balanced=True, seed=seed, max_samples=cap),
        logistic_regression_baseline("logistic_regression", base.features, seed=seed),
        logistic_regression_baseline("logistic_regression_balanced", base.features, balanced=True, seed=seed),
    ]


def run_arms(config: LearningCurveConfig, cd: ClassData, out_dir: Path, only: list[str] | None = None) -> None:
    """Fit every arm (resumable): ExFuzzy per seed, then the baselines on the same rows."""
    base, d = cd.config.base, cd.data
    val = d.positions("validation")  # the only held-out period ever indexed here
    validation = (d.frame.loc[val, base.features], cd.y_class[val])
    reference = cd.partition_reference()
    version = exfuzzy_version()  # a checkout (3.3.1+g13f7548) gets its own directory: its numbers are not 3.3.1's
    fits_dir = out_dir / "fits" / (config.backend if version == "3.3.1" else f"{config.backend}@{version}")
    base_dir = out_dir / "baselines"
    fits_dir.mkdir(parents=True, exist_ok=True)
    base_dir.mkdir(parents=True, exist_ok=True)
    for arm in config.arms:
        if only and arm.name not in only:
            continue
        rows = arm_rows(cd, arm, config.subsample_seed)
        _log(f"arm {arm.name}: {len(rows)} rows, classes {np.bincount(cd.y_class[rows], minlength=len(cd.labels))}")
        pd.DataFrame({"entity_id": d.frame["entity_id"].to_numpy()[rows], "issued_at_utc": d.issued[rows]}).to_parquet(
            out_dir / f"rows_{arm.name}.parquet", index=False)
        for seed in arm.seeds if arm.seeds is not None else config.seeds:
            path = fits_dir / f"{arm.name}_seed{seed}.json"
            if path.exists():
                continue
            record = fit_one(config, cd, rows, seed, reference, validation, arm.batch_size)
            record["arm"] = arm.name
            record["exfuzzy_version"] = version
            path.write_text(json.dumps(record, indent=2) + "\n")
            v = record["validation"]
            _log(f"  {arm.name} seed {seed}: val macro-F1 {v['macro_f1']:.4f} bal-acc {v['balanced_accuracy']:.3f} "
                 f"rules {record['n_rules']} fit {record['fit_seconds']:.0f}s rss {record['peak_rss_mb']:.0f} MB "
                 f"gpu {record['fit_info'].get('gpu_accelerated')} {record.get('gpu_peak_reserved_mb', 0):.0f} MB")
        bpath = base_dir / f"{arm.name}.json"
        if arm.baselines and not bpath.exists():
            result = {"arm": arm.name, "n_fit_rows": int(len(rows)), "baselines": {}}
            for baseline in _baselines(base, arm, base.seed):
                start = time.perf_counter()
                baseline.fit(d.frame.loc[rows], cd.y_class[rows])
                secs = time.perf_counter() - start
                pred = baseline.predict(d.frame.loc[val])
                result["baselines"][baseline.name] = {
                    "fit_seconds": secs,
                    "validation": _summary(classification_metrics(validation[1], pred, len(cd.labels)), cd.labels)}
                _log(f"  baseline {baseline.name} on {arm.name}: val macro-F1 "
                     f"{result['baselines'][baseline.name]['validation']['macro_f1']:.4f} ({secs:.0f}s)")
            bpath.write_text(json.dumps(result, indent=2) + "\n")


# ------------------------------------------------------------------------------------------- feasibility


def run_feasibility(config: LearningCurveConfig, cd: ClassData, out_dir: Path) -> dict:
    """Part A of the protocol: A1 (EvoX versus pymoo fit), A2 (torch versus CPU scores), A3 (cost per row)."""
    import ex_fuzzy
    import torch

    from atlas.ml.exfuzzy_features import exfuzzy_version

    base, d = cd.config.base, cd.data
    val = d.positions("validation")
    validation = (d.frame.loc[val, base.features], cd.y_class[val])
    reference = cd.partition_reference()
    out: dict = {"exfuzzy_version": exfuzzy_version(), "exfuzzy_path": ex_fuzzy.__file__, "torch": torch.__version__,
                 "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}
    path = out_dir / "feasibility.json"
    if path.exists():
        out = json.loads(path.read_text())
    published = Arm(name="published30k", sampler="published", n_rows=30000)
    rows30 = arm_rows(cd, published, config.subsample_seed)
    published_dir = experiment_dir(cd.config, ARTIFACTS_DIR)  # the AT-041d experiment (ica2-justified)
    keys = pd.read_parquet(published_dir / "subsample_keys.parquet")
    same = (keys["entity_id"].to_numpy() == d.frame["entity_id"].to_numpy()[rows30]).all() and (
        pd.DatetimeIndex(keys["issued_at_utc"]) == d.issued[rows30]).all()
    out["published_rows_reproduced"] = bool(same)
    _log(f"A0 published 30k rows reproduce ica2-justified/subsample_keys.parquet: {same}")
    out.setdefault("A1", {})
    for backend in ("evox", "pymoo"):
        if backend in out["A1"]:
            continue
        cfg = config.model_copy(update={"backend": backend})
        record = fit_one(cfg, cd, rows30, 0, reference, validation)
        out["A1"][backend] = {k: record[k] for k in ("fit_seconds", "peak_rss_mb", "n_rules", "fit_info", "validation",
                                                      "gpu_peak_reserved_mb", "gpu_peak_allocated_mb")
                              if k in record}
        _log(f"A1 {backend}: val macro-F1 {record['validation']['macro_f1']:.4f} rules {record['n_rules']} "
             f"fit {record['fit_seconds']:.0f}s device {record['fit_info'].get('gpu_accelerated')}")
        path.write_text(json.dumps(out, indent=2) + "\n")

    # A2 + A3 need the problem; an evolved population comes from a short direct EvoX fit on the same rows.
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier

    features = base.features
    variables = build_variables(reference.to_numpy(float), features, cd.fixed, config.shape.n_linguistic_variables,
                                base.feature_units)
    X30, y30 = d.frame.loc[rows30, features].to_numpy(float), cd.y_class[rows30]
    shape = config.shape
    evolver = BaseFuzzyRulesClassifier(
        nRules=shape.nRules, nAnts=shape.nAnts, linguistic_variables=variables, class_names=cd.labels, tolerance=0.0,
        ds_mode=0, allow_unknown=True, backend="evox", n_gen=40, pop_size=config.pop_size, patience=None,
        random_state=0)
    evolver.fit(X30, y30)
    evolved = np.asarray(evolver.optimization_result_["pop"], dtype=int)
    problem30 = eval_timing.build_problem(X30, y30, variables, n_rules=shape.nRules, n_ants=shape.nAnts,
                                          n_classes=len(cd.labels))
    populations = {"evolved": evolved, "random": eval_timing.random_population(problem30, len(evolved), seed=1)}
    from ex_fuzzy._fitness import _fitness_cache_scope

    objective = eval_timing.device_objective(problem30, "cuda")
    a2 = {"device_objective_built": objective is not None}
    if objective is not None:
        for name, genes in populations.items():
            with _fitness_cache_scope(problem30, True, len(genes)):
                cpu = problem30._scalar_scores(genes)
            scores, declined = objective.score(genes)
            device = 1 - scores
            a2[name] = {"n": int(len(genes)), "max_abs_diff": float(np.max(np.abs(device - cpu))),
                        "n_exactly_equal": int(np.sum(device == cpu)), "n_declined": int(declined.sum())}
    out["A2"] = a2
    _log(f"A2 {a2}")
    path.write_text(json.dumps(out, indent=2) + "\n")

    free, total = torch.cuda.mem_get_info() if torch.cuda.is_available() else (0, 0)
    a3 = {"cuda_free_mb_at_start": free / 2**20, "cuda_total_mb": total / 2**20, "sizes": []}
    for n_rows in config.timing_rows:
        rows = d.train_pos if n_rows == 0 else arm_rows(
            cd, Arm(name=f"t{n_rows}", sampler="nested", n_rows=n_rows), config.subsample_seed)
        X, y = d.frame.loc[rows, features].to_numpy(float), cd.y_class[rows]
        problem = eval_timing.build_problem(X, y, variables, n_rules=shape.nRules, n_ants=shape.nAnts,
                                            n_classes=len(cd.labels))
        routes = ["device", "cpu_batched"] + (["cpu_scalar"] if len(rows) <= 30000 else [])
        entry = eval_timing.time_generation(problem, evolved, repeats=3, routes=routes)
        entry["device_row_limit_one_candidate"] = eval_timing.device_row_limit(problem, int(free))
        entry["rss_mb_after_build"] = current_rss_mb()
        a3["sizes"].append(entry)
        _log(f"A3 {entry['n_rows']} rows: " + ", ".join(
            f"{r}={entry[r].get('median', entry[r].get('declined'))}" for r in routes))
        path.write_text(json.dumps({**out, "A3": a3}, indent=2) + "\n")
        del problem, X, y
    # same size with random genes (cost depends on the active rules), 30k only
    problem = eval_timing.build_problem(X30, y30, variables, n_rules=shape.nRules, n_ants=shape.nAnts,
                                        n_classes=len(cd.labels))
    a3["random_population_30k"] = eval_timing.time_generation(problem, populations["random"], repeats=3,
                                                              routes=["device", "cpu_batched"])
    evaluations = eval_timing.n_evaluations(config.n_gen, config.pop_size)
    a3["evaluations_per_fit"] = evaluations
    out["A3"] = a3
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out


def run_costs(config: LearningCurveConfig, cd: ClassData, out_dir: Path) -> dict:
    """Part A, additions made after A1-A3 (section 5 of the protocol): the CPU scalar route on 120k and every
    training row, the device at the largest size it accepts, and how many *fresh* (uncached) candidates an EvoX fit
    on 30,000 rows really scores, which turns the cost per candidate into a cost per fit."""
    import torch
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier, FitRuleBase

    base, d, shape = cd.config.base, cd.data, config.shape
    features = base.features
    reference = cd.partition_reference()
    variables = build_variables(reference.to_numpy(float), features, cd.fixed, shape.n_linguistic_variables,
                                base.feature_units)
    rows30 = arm_rows(cd, Arm(name="p", sampler="published", n_rows=30000), config.subsample_seed)
    X30, y30 = d.frame.loc[rows30, features].to_numpy(float), cd.y_class[rows30]
    path = out_dir / "costs.json"
    out: dict = json.loads(path.read_text()) if path.exists() else {}

    fresh = {"calls": 0, "candidates": 0, "scored_fresh": 0}
    original = FitRuleBase._score_on_best_route

    def counting(self, fresh_genes, population, device=None):
        fresh["calls"] += 1
        fresh["candidates"] += population
        fresh["scored_fresh"] += len(fresh_genes)
        return original(self, fresh_genes, population, device)

    FitRuleBase._score_on_best_route = counting
    try:
        est = BaseFuzzyRulesClassifier(
            nRules=shape.nRules, nAnts=shape.nAnts, linguistic_variables=variables, class_names=cd.labels,
            tolerance=0.0, ds_mode=0, allow_unknown=True, backend="evox", n_gen=config.n_gen,
            pop_size=config.pop_size, patience=None, random_state=0)
        start = time.perf_counter()
        est.fit(X30, y30)
        fresh["fit_seconds"] = time.perf_counter() - start
    finally:
        FitRuleBase._score_on_best_route = original
    out["evox_30k_seed0_fresh_candidates"] = fresh
    evolved = np.asarray(est.optimization_result_["pop"], dtype=int)
    _log(f"A4 EvoX fit scores {fresh['scored_fresh']} fresh candidates of {fresh['candidates']} offered")

    free = torch.cuda.mem_get_info()[0]
    sizes = [("cpu_scalar", 120000), ("cpu_scalar", 0), ("device", None)]
    out["timings"] = []
    for route, n_rows in sizes:
        if route == "device":
            problem0 = eval_timing.build_problem(X30, y30, variables, n_rules=shape.nRules, n_ants=shape.nAnts,
                                                 n_classes=len(cd.labels))
            n_rows = int(eval_timing.device_row_limit(problem0, int(free)) * 0.97)  # a little under the limit
        rows = d.train_pos if n_rows == 0 else arm_rows(
            cd, Arm(name=f"t{n_rows}", sampler="nested", n_rows=n_rows), config.subsample_seed)
        X, y = d.frame.loc[rows, features].to_numpy(float), cd.y_class[rows]
        problem = eval_timing.build_problem(X, y, variables, n_rules=shape.nRules, n_ants=shape.nAnts,
                                            n_classes=len(cd.labels))
        entry = eval_timing.time_generation(problem, evolved, repeats=3, routes=[route])
        out["timings"].append(entry)
        _log(f"A3b {route} {len(rows)} rows: {entry[route].get('median', entry[route].get('declined'))}")
        path.write_text(json.dumps(out, indent=2) + "\n")
        del problem, X, y
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out


# ---------------------------------------------------------------------------------------------- report


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _mean_sd(values: list[float]) -> tuple[float, float]:
    return float(np.mean(values)), float(np.std(values, ddof=1)) if len(values) > 1 else float("nan")


DECISION_THRESHOLD = 0.011  # one seed sd of AT-041d (protocol, section 0)


def decision_lines(backend_dir: Path, small: str = "n30k", large: str = "n120k") -> list[str]:
    """The pre-registered comparison on one backend: mean validation macro-F1 of ``large`` minus ``small``, its
    standard error (independent seeds, n-1 sds) and the verdict of the rule (difference >= 0.011)."""
    def values(arm: str) -> list[float]:
        files = sorted(backend_dir.glob(f"{arm}_seed*.json"))
        return [json.loads(p.read_text())["validation"]["macro_f1"] for p in files]

    a, b = values(small), values(large)
    if len(a) < 2 or len(b) < 2:
        return []
    diff = float(np.mean(b) - np.mean(a))
    se = float(np.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b)))
    verdict = "helps" if diff >= DECISION_THRESHOLD else "no measurable gain"
    return [f"Decision on `{backend_dir.name}`: mean({large}) - mean({small}) = {diff:+.4f} (standard error {se:.4f}, "
            f"threshold {DECISION_THRESHOLD}) -> **{verdict}**", ""]


def report(config: LearningCurveConfig, labels: list[str], out_dir: Path) -> str:
    """Markdown tables of every arm that has results (ExFuzzy per backend, then baselines)."""
    lines: list[str] = []
    for backend_dir in sorted((out_dir / "fits").glob("*")):
        lines += [f"### ExFuzzy, backend `{backend_dir.name}`", "",
                  "| arm | seeds | rows | val macro-F1 | bal-acc | acc | recall " + " / ".join(labels) +
                  " | precision " + " / ".join(labels) + " | F1 " + " / ".join(labels) +
                  " | rules | Jaccard | fit s | s/gen | final scoring s | RSS MB | GPU MB |",
                  "|" + "---|" * (11 + 5)]
        for arm in config.arms:
            fits = [json.loads(p.read_text()) for p in sorted(backend_dir.glob(f"{arm.name}_seed*.json"))]
            if not fits:
                continue
            m = [f["validation"] for f in fits]

            def ms(key, m=m):
                a, s = _mean_sd([x[key] for x in m])
                return f"{a:.3f} +- {s:.3f}"

            rec = " / ".join(f"{np.mean([x['recall'][lab] for x in m]):.2f}" for lab in labels)
            pre = " / ".join(f"{np.mean([x['precision'][lab] for x in m]):.2f}" for lab in labels)
            f1s = " / ".join(
                f"{np.mean([_f1(x['precision'][lab], x['recall'][lab]) for x in m]):.2f}" for lab in labels)
            gen = [f["seconds_per_generation"] for f in fits if "seconds_per_generation" in f]
            fin = [f["final_scoring_seconds"] for f in fits if "final_scoring_seconds" in f]
            sets = [[(tuple(tuple(p) for p in r["antecedents"]), r["class"]) for r in f["rules"]] for f in fits]
            jac = rule_set_stability(sets)["mean_pairwise_jaccard_rule"] if len(fits) > 1 else float("nan")
            gpu = np.mean([f.get("gpu_peak_reserved_mb", np.nan) for f in fits])
            lines.append(
                f"| {arm.name} | {len(fits)} | {fits[0]['n_fit_rows']} | {ms('macro_f1')} | "
                f"{ms('balanced_accuracy')} | {ms('accuracy')} | {rec} | {pre} | {f1s} | "
                f"{np.mean([f['n_rules'] for f in fits]):.1f} | {jac:.3f} | "
                f"{np.mean([f['fit_seconds'] for f in fits]):.0f} | "
                f"{(f'{np.mean(gen):.2f}' if gen else '-')} | {(f'{np.mean(fin):.1f}' if fin else '-')} | "
                f"{np.mean([f['peak_rss_mb'] for f in fits]):.0f} | "
                f"{gpu:.0f} |")
        lines.append("")
        lines += decision_lines(backend_dir)
    rows = []
    for arm in config.arms:
        p = out_dir / "baselines" / f"{arm.name}.json"
        if p.exists():
            for name, b in json.loads(p.read_text())["baselines"].items():
                v = b["validation"]
                rows.append(f"| {arm.name} | {name} | {v['macro_f1']:.4f} | {v['balanced_accuracy']:.3f} | "
                            f"{v['accuracy']:.3f} | {b['fit_seconds']:.0f} |")
    if rows:
        lines += ["### Baselines on the same rows (validation)", "",
                  "| arm | baseline | macro-F1 | bal-acc | acc | fit s |", "|---|---|---|---|---|---|", *rows, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.learning_curve", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["feasibility", "costs", "fit", "report"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--arms", nargs="*", default=None, help="fit: only these arms")
    parser.add_argument("--backend", default=None, help="override the backend of the config (evox | pymoo)")
    args = parser.parse_args(argv)
    config, base_config = load_config(args.config)
    if args.backend:
        config = config.model_copy(update={"backend": args.backend})
    out_dir = experiment_dir(base_config.model_copy(update={"experiment_id": config.experiment_id}),
                             args.artifacts_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cd = ClassData(base_config)
    if args.command == "feasibility":
        run_feasibility(config, cd, out_dir)
    elif args.command == "costs":
        run_costs(config, cd, out_dir)
    elif args.command == "fit":
        run_arms(config, cd, out_dir, args.arms)
    else:
        print(report(config, cd.labels, out_dir))


if __name__ == "__main__":
    main()
