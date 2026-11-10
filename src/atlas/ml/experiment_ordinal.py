"""AT-041k: ex_fuzzy ordinal conditions ("x IS at least Fair" / "at most Fair") against the ten published tasks.

::

    python -u -m atlas.ml.experiment_ordinal arms [--workers 16] [--smoke]   # every (task, arm, seed) fit; validation
    python -m atlas.ml.experiment_ordinal decide                             # decisions.json, validation only
    python -m atlas.ml.experiment_ordinal test                               # once; needs decisions.json for all tasks
    python -m atlas.ml.experiment_ordinal report                             # markdown tables

Protocol, arms and decision rule: ``docs/ml/ordinal_conditions.md`` section 0 (pre-registered, committed before any
fit). Arm A is the task's published configuration with ``ordinal_conditions`` off, arm B the same with it on, seeds 0-2
in both. Mixture tasks reuse the fits of ``atlas.ml.experiment_mixture`` (``mix_search_nonneg``, pruning
``winning_rule``); NYC +6 h (winning rule) and Water (TSK regressor) also re-run the shape selection of their published
procedure in each arm. Everything is written under ``<artifacts>/experiments/ordinal_conditions/`` (resumable).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing as mp
import pickle
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from atlas.explain import feature_names
from atlas.explain.classifier import feature_names as classifier_feature_names
from atlas.explain.classifier import get_master_rulebase, rule_classes, rule_weights
from atlas.ml.evaluation import PeakRss, classifier_rule_sets, rule_signatures
from atlas.ml.exfuzzy_features import exfuzzy_version, require, rule_conditions
from atlas.ml.experiment_class import _log, _params
from atlas.ml.experiment_mixture import Context, MixtureConfig, _json, _metrics, mixture_stats, partitions_signature
from atlas.ml.experiment_water import WaterConfig, WaterData, _fit_fuzzy
from atlas.ml.fuzzy import FuzzyParams
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.metrics import regression_metrics
from atlas.paths import ARTIFACTS_DIR, REPO_ROOT

CONFIG = "configs/ml/ordinal_conditions_experiment.json"
ARMS = ("A", "B")  # A: the published configuration, the option off; B: the same with ordinal_conditions=True
ACTIVE_SPREAD = 0.25  # mixture rules with weight spread below this are "negligible" (rule_mixture.md 0.5)


class CompoundTerm(BaseModel):
    """A named union of contiguous terms of a clock or calendar input (Amendment 1); the bounded sum is its membership.

    ``name`` is what the fitted model calls it (in the language of the input's own terms); ``name_es`` / ``name_en`` are
    the provisional display names. Names never enter the fit."""

    model_config = ConfigDict(extra="forbid")

    terms: list[str]  # the unified terms, in the order of the variable (hour: the last-and-first pair wraps)
    name: str
    name_es: str
    name_en: str


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    kind: Literal["mixture", "winning", "water"]
    # mixture / winning: the task's mixture-serve config (rows, split, served fitting sample); water: its experiment
    config: str
    # Amendment 1, arm B: ``at least`` / ``at most`` on the quantity inputs only; the clock and calendar inputs
    # listed here get the compound terms below instead (Amendment 1 of docs/ml/ordinal_conditions.md)
    clock_variables: list[str] = []
    # clock inputs whose domain spans the whole cycle (hour 0-23, weekday 0-6): only there may a union wrap
    cyclic_variables: list[str] = []
    compound_terms: dict[str, list[CompoundTerm]] = {}


class OrdinalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = "ordinal-conditions"
    seeds: list[int] = [0, 1, 2]
    tau_macro_f1: float = 0.01  # the web's tie tolerance for a macro-F1 (apps/web/src/lib/performance.ts)
    tau_mae_share: float = 0.01  # ... and for an error: 1 % of the reference error
    tasks: list[TaskSpec]  # in decreasing order of expected cost: the pool starts the slowest fits first


def quantity_variables(spec: TaskSpec, features: list[str]) -> list[str]:
    """The inputs that get ``at least`` / ``at most`` in arm B: every input that is not a clock or calendar one."""
    unknown = [v for v in [*spec.clock_variables, *spec.compound_terms] if v not in features]
    if unknown:
        raise ValueError(f"{spec.task_id}: clock inputs {unknown} are not inputs of the model")
    if set(spec.compound_terms) - set(spec.clock_variables) or set(spec.cyclic_variables) - set(spec.clock_variables):
        raise ValueError(f"{spec.task_id}: compound terms on inputs that are not clock inputs")
    return [f for f in features if f not in spec.clock_variables]


def check_compound_terms(spec: TaskSpec, terms: dict[str, list[str]]) -> None:
    """``terms``: the base terms of each clock input, in order. Every member exists and each union is contiguous; it may
    wrap (the last term next to the first) only for an input of ``spec.cyclic_variables``: wrap only if the domain
    spans the whole cycle."""
    for variable, unions in spec.compound_terms.items():
        base = terms[variable]
        names = [u.name for u in unions]
        if len(set(names)) != len(names) or set(names) & set(base):
            raise ValueError(f"{spec.task_id}.{variable}: compound names must be unique and differ from the base terms")
        for union in unions:
            at = sorted(base.index(t) for t in union.terms)  # KeyError-like ValueError if a member is missing
            gaps = {(b - a) % len(base) for a, b in zip(at, at[1:], strict=False)}
            wraps = len(at) == 2 and (at[0] - at[1]) % len(base) == 1
            if len(at) < 2 or not (gaps == {1} or (wraps and variable in spec.cyclic_variables)):
                raise ValueError(f"{spec.task_id}.{variable}: {union.terms} is not a run of adjacent terms")


def load_config(path: Path | None = None) -> OrdinalConfig:
    return OrdinalConfig.model_validate_json((path or REPO_ROOT / CONFIG).read_text())


def out_dir(artifacts: Path, smoke: bool = False) -> Path:
    return Path(artifacts) / "experiments" / ("ordinal_conditions-smoke" if smoke else "ordinal_conditions")


# ------------------------------------------------------------------------------------------------ contexts


class WaterContext:
    """The table, split and complete-row masks of Water, and the published shape grid."""

    def __init__(self, config: WaterConfig):
        self.config, self.wd = config, WaterData(config)

    @property
    def shapes(self) -> list[tuple[int, int]]:
        sel = self.config.selection
        return [(r, a) for r in sel.nRules for a in sel.nAnts]


def shapes_of(ctx) -> list[tuple[int, int]]:
    """The shape grid of the published selection procedure (water, winning-rule NYC +6 h)."""
    if isinstance(ctx, WaterContext):
        return ctx.shapes
    return [(c.nRules, c.nAnts) for c in ctx.task.selection.candidates]


def load_context(spec: TaskSpec, artifacts: Path):
    path = REPO_ROOT / spec.config
    if spec.kind == "water":
        return WaterContext(WaterConfig.model_validate_json(path.read_text()))
    config = MixtureConfig.model_validate_json(path.read_text())
    config = config.model_copy(update={"experiment_id": "ordinal-conditions"})
    ctx = Context(config, artifacts)
    if spec.kind == "winning":
        cands = ctx.task.selection.candidates
        if len({(c.n_linguistic_variables, c.rule_weighting, c.sampling_power) for c in cands}) != 1:
            raise ValueError("the candidates of the shape selection differ in more than the shape")
        keys = {(c.sampling_power) for c in cands}
        rows = ctx.cd.train_sample(ctx.task.subsample.n_rows, ctx.task.subsample.seed, keys.pop())
        if set(rows.tolist()) != set(ctx.sub_rows.tolist()):  # the served fitting sample is the selection's sample
            raise AssertionError(f"{spec.task_id}: the served fitting sample is not the shape selection's sample")
    return ctx


# ------------------------------------------------------------------------------------------------ jobs


@dataclass(frozen=True)
class Job:
    task: str
    arm: str
    stage: Literal["select", "final"]
    seed: int
    shape: tuple[int, int] | None = None  # (nRules, nAnts); None: the published shape of a mixture task

    @property
    def name(self) -> str:
        if self.stage == "final":
            return f"{self.arm}-seed{self.seed}"
        return f"{self.arm}-select-{self.shape[0]}x{self.shape[1]}"


def fit_path(out: Path, job: Job) -> Path:
    return out / job.task / "fits" / f"{job.name}.json"


def read_fits(out: Path, task: str, pattern: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((out / task / "fits").glob(pattern))]


def chosen_shape(spec: TaskSpec, ctx, out: Path, arm: str) -> tuple[int, int] | None:
    """The shape the published selection procedure picks in this arm (None for a task with a fixed shape)."""
    if spec.kind == "mixture":
        return None
    fits = read_fits(out, spec.task_id, f"{arm}-select-*.json")
    if len(fits) != len(shapes_of(ctx)):
        raise SystemExit(f"{spec.task_id} arm {arm}: {len(fits)} of {len(shapes_of(ctx))} selection fits on disk")
    if spec.kind == "water":  # lowest validation RMSE (ties: fewer rules, then fewer antecedents)
        best = min(fits, key=lambda f: (f["validation"]["rmse"], f["shape"][0], f["shape"][1]))
    else:  # highest validation macro-F1 (ties: fewer rules)
        best = max(fits, key=lambda f: (f["validation"]["macro_f1"], -f["n_rules"]))
    return tuple(best["shape"])


def plan_selection(cfg: OrdinalConfig, ctxs: dict) -> list[Job]:
    """Fits that do not depend on a selection: the final fits of the fixed-shape tasks and every selection fit."""
    jobs = []
    for spec in cfg.tasks:
        for arm in ARMS:
            if spec.kind == "mixture":
                jobs += [Job(spec.task_id, arm, "final", s) for s in cfg.seeds]
            else:
                jobs += [Job(spec.task_id, arm, "select", 0, shape) for shape in shapes_of(ctxs[spec.task_id])]
    return jobs


def plan_final(cfg: OrdinalConfig, ctxs: dict, out: Path) -> list[Job]:
    return [Job(spec.task_id, arm, "final", s, chosen_shape(spec, ctxs[spec.task_id], out, arm))
            for spec in cfg.tasks if spec.kind != "mixture" for arm in ARMS for s in cfg.seeds]


# ------------------------------------------------------------------------------------------------ fitting


def arm_b_library_options(spec: TaskSpec, features: list[str]) -> dict:
    """The per-variable options of arm B (Amendment 1), as ``FuzzyClassifierParams`` / ``FuzzyParams`` fields:
    ``at least`` / ``at most`` on the quantity inputs only, and the named compound terms of the clock inputs."""
    return {
        "ordinal_conditions": tuple(quantity_variables(spec, features)),
        "compound_terms": {variable: [(u.name, list(u.terms)) for u in unions]
                           for variable, unions in spec.compound_terms.items()},
    }


def classifier_params(ctx: Context, spec: TaskSpec, job: Job, smoke: bool) -> FuzzyClassifierParams:
    """``fit_arm`` of ``experiment_mixture`` for ``mix_search_nonneg`` (mixture tasks), or the published
    ``experiment_class`` parameters of the shape (winning rule); the option is the only difference between A and B."""
    b_options = arm_b_library_options(spec, ctx.features) if job.arm == "B" else {}
    if spec.kind == "mixture":
        served = ctx.served_model(ctx.cfg.served_seed).params
        params = dataclasses.replace(
            served, batch_size=getattr(served, "batch_size", None), inference="mixture", mixture_C=ctx.cfg.mixture_C,
            mixture_non_negative=True, mixture_search=True, mixture_pruning="winning_rule",
            mixture_prune_threshold=ctx.cfg.mixture_prune_threshold, **b_options)
    else:
        sel = ctx.task.selection
        cand = next(c for c in sel.candidates if (c.nRules, c.nAnts) == job.shape)
        params = dataclasses.replace(_params(cand, sel.n_gen, sel.pop_size, sel.patience), **b_options)
    return dataclasses.replace(params, n_gen=2, pop_size=8) if smoke else params


def condition_stats(rules, antecedents, names: list[str], clock: Sequence[str] = ()) -> dict:
    """Rules and conditions of a rule base through ``rule.conditions()``: single terms (``is``), ordinal
    (``at_least`` / ``at_most``) and compound (``any_of``). ``clock``: inputs that must carry no ordinal condition."""
    by_input: dict[str, dict[str, int]] = {}
    lengths, rules_ordinal, rules_compound = [], 0, 0
    for rule in rules:
        conditions = rule_conditions(rule, antecedents)
        lengths.append(len(conditions))
        rules_ordinal += any(c.operator in ("at_least", "at_most") for c in conditions)
        rules_compound += any(c.operator == "any_of" for c in conditions)
        for c in conditions:
            by_input.setdefault(names[c.feature], {"is": 0, "at_least": 0, "at_most": 0, "any_of": 0})[c.operator] += 1
    total = sum(lengths)
    return {"n_rules": len(lengths), "total_conditions": total,
            "mean_conditions": total / len(lengths) if lengths else 0.0,
            "n_rules_ordinal": rules_ordinal, "n_rules_compound": rules_compound,
            "n_conditions_ordinal": sum(d["at_least"] + d["at_most"] for d in by_input.values()),
            "n_conditions_compound": sum(d["any_of"] for d in by_input.values()),
            "n_ordinal_on_clock_inputs": sum(d["at_least"] + d["at_most"] for n, d in by_input.items() if n in clock),
            "conditions_by_input": by_input}


def check_flags(arm: str, antecedents, spec: TaskSpec) -> int:
    """Arm A: no variable offers an ordinal or compound condition. Arm B (Amendment 1): exactly the quantity inputs
    offer ``at least`` / ``at most``, none of the clock inputs does, and every compound term of the config is there.
    Anything else is a code or library bug. Returns the number of ordinal variables."""
    ordinal = {str(v.name) for v in antecedents if getattr(v, "ordinal", False)}
    compound = {str(v.name): [name for name, _ in getattr(v, "compound", ())] for v in antecedents
                if getattr(v, "compound", ())}
    if arm == "A":
        if ordinal or compound:
            raise AssertionError(f"arm A: ordinal {sorted(ordinal)} / compound {sorted(compound)} variables")
        return 0
    features = [str(v.name) for v in antecedents]
    expected = set(quantity_variables(spec, features))
    if ordinal != expected:
        raise AssertionError(f"arm B: ordinal variables {sorted(ordinal)}, expected {sorted(expected)}")
    want = {v: [u.name for u in unions] for v, unions in spec.compound_terms.items()}
    if {v: sorted(n) for v, n in compound.items()} != {v: sorted(n) for v, n in want.items()}:
        raise AssertionError(f"arm B: compound terms {compound}, expected {want}")
    return len(ordinal)


def fit_classifier(ctx: Context, spec: TaskSpec, job: Job, smoke: bool):
    cd = ctx.cd
    params = classifier_params(ctx, spec, job, smoke)
    X_sub, y_sub = cd.data.frame.loc[ctx.sub_rows, ctx.features], cd.y_class[ctx.sub_rows]
    model = FuzzyClassifier(params, {f: ctx.task.base.feature_units[f] for f in ctx.features}).fit(
        X_sub, y_sub, cd.labels, job.seed, partition_reference=cd.partition_reference()[ctx.features],
        fixed={f: p for f, p in cd.fixed.items() if f in ctx.features})
    served = ctx.served_model(ctx.cfg.served_seed)
    if partitions_signature(model.estimator) != partitions_signature(served.estimator):
        raise AssertionError(f"{job.name}: the terms differ from the published model's")
    return model


def classifier_record(ctx: Context, spec: TaskSpec, job: Job, model, secs: float, rss: float, smoke: bool) -> dict:
    cd = ctx.cd
    pos = ctx.sub_rows if smoke else cd.data.positions("validation")  # smoke: no validation row is read
    rb = get_master_rulebase(model)
    stats = condition_stats(rb.get_rules(), rb.antecedents, classifier_feature_names(rb), spec.clock_variables)
    rules = classifier_rule_sets(model, cd.labels)
    X_sub = cd.data.frame.loc[ctx.sub_rows, ctx.features]
    record = {
        **stats, "task": job.task, "arm": job.arm, "stage": job.stage, "seed": job.seed, "shape": list(job.shape or (
            model.params.nRules, model.params.nAnts)), "scored_on": "fitting sample (smoke)" if smoke else "validation",
        "validation": _metrics(cd, pos, model.predict(cd.data.frame.loc[pos, ctx.features])),
        "fit_sample": _metrics(cd, ctx.sub_rows, model.predict(X_sub)),
        "n_ordinal_variables": check_flags(job.arm, rb.antecedents, spec),
        "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rules],
        "partitions": partitions_signature(model.estimator), "params": model.params.as_dict(),
        "fit_seconds": secs, "peak_rss_mb": rss, "exfuzzy_version": exfuzzy_version(), "fit_info": model.fit_info,
    }
    if spec.kind == "mixture":
        record["mixture"] = mixture_stats(model, X_sub.to_numpy(dtype=float), ACTIVE_SPREAD)
    return record


def water_params(ctx: WaterContext, spec: TaskSpec, job: Job, smoke: bool) -> FuzzyParams:
    cfg = ctx.config
    sel, fin = cfg.selection, cfg.final
    n_gen, pop = (sel.n_gen, sel.pop_size) if job.stage == "select" else (fin.n_gen, fin.pop_size)
    if smoke:
        n_gen, pop = 2, 8
    return FuzzyParams(nRules=job.shape[0], nAnts=job.shape[1], n_linguistic_variables=sel.n_linguistic_variables,
                       n_gen=n_gen, pop_size=pop, rule_mode=cfg.rule_mode, unique_antecedents=cfg.unique_antecedents,
                       **(arm_b_library_options(spec, ctx.config.base.features) if job.arm == "B" else {}))


def water_record(ctx: WaterContext, spec: TaskSpec, job: Job, model, secs: float, rss: float, smoke: bool) -> dict:
    wd, base = ctx.wd, ctx.config.base
    pos = wd.train_pos[:2000] if smoke else wd.positions("validation")  # smoke: no validation row is read
    rulebase = model.get_rulebase()
    names = feature_names(rulebase)
    signatures = rule_signatures(rulebase)
    metrics = regression_metrics(wd.y[pos], model.predict(wd.frame.loc[pos, base.features]))
    return {
        **condition_stats(rulebase.rules, rulebase.antecedents, names, spec.clock_variables), "task": job.task,
        "arm": job.arm, "stage": job.stage, "seed": job.seed, "shape": list(job.shape),
        "scored_on": "training rows (smoke)" if smoke else "validation", "validation": {**metrics, "n": int(len(pos))},
        "n_ordinal_variables": check_flags(job.arm, rulebase.antecedents, spec),
        "rules": [[list(p) for p in sig] for sig in signatures],
        "consequents": [float(v) for v in np.ravel(rulebase.scalar_consequents)],
        "partitions": model.variables_summary, "params": water_params(ctx, spec, job, smoke).as_dict(),
        "fit_seconds": secs, "peak_rss_mb": rss, "exfuzzy_version": exfuzzy_version(), "fit_info": model.fit_info,
    }


_STATE: dict = {}  # set in the parent before forking: contexts (tables), specs, output directory, smoke flag


def run_job(job: Job) -> dict:
    from threadpoolctl import threadpool_limits

    spec, ctx, out, smoke = _STATE["specs"][job.task], _STATE["ctxs"][job.task], _STATE["out"], _STATE["smoke"]
    with threadpool_limits(1):  # BLAS threads only slow the small products of the mixture fits
        if spec.kind == "water":
            model, secs, rss = _fit_fuzzy(ctx.wd, water_params(ctx, spec, job, smoke), job.seed)
            record = water_record(ctx, spec, job, model, secs, rss, smoke)
        else:
            start = time.perf_counter()
            with PeakRss() as peak:
                model = fit_classifier(ctx, spec, job, smoke)
            secs, rss = time.perf_counter() - start, peak.peak_mb
            record = classifier_record(ctx, spec, job, model, secs, rss, smoke)
    if job.stage == "final":
        with open(out / job.task / "models" / f"{job.name}.pkl", "wb") as fh:
            pickle.dump(model, fh)
    fit_path(out, job).write_text(json.dumps(record, default=_json) + "\n")
    score = record["validation"].get("macro_f1", record["validation"].get("mae"))
    return {"job": job, "score": score, "rules": record["n_rules"], "conditions": record["total_conditions"],
            "ordinal": record["n_conditions_ordinal"], "compound": record["n_conditions_compound"], "secs": secs}


def run_pool(jobs: list[Job], workers: int, done: int, total: int) -> int:
    """Run the fits not on disk yet, longest first; one ``[k/N]`` line per finished fit. Returns the new count."""
    out = _STATE["out"]
    pending = [j for j in jobs if not fit_path(out, j).exists()]
    done += len(jobs) - len(pending)
    if not pending:
        return done
    with mp.get_context("fork").Pool(min(workers, len(pending)), maxtasksperchild=1) as pool:
        for r in pool.imap_unordered(run_job, pending):
            done += 1
            j = r["job"]
            shape = "" if j.shape is None else f" shape={j.shape[0]}x{j.shape[1]}"
            print(f"[{done}/{total}] task={j.task} arm={j.arm} {j.stage}{shape} seed={j.seed} score={r['score']:.4f} "
                  f"rules={r['rules']} conditions={r['conditions']} ordinal={r['ordinal']} compound={r['compound']} "
                  f"fit={r['secs']:.0f}s",
                  flush=True)
    return done


def arms(cfg: OrdinalConfig, artifacts: Path, workers: int, smoke: bool, only: list[str] | None) -> None:
    if smoke:
        cfg = cfg.model_copy(update={"seeds": cfg.seeds[:1]})
    if only:
        cfg = cfg.model_copy(update={"tasks": [t for t in cfg.tasks if t.task_id in only]})
    require("ordinal_conditions")
    out = out_dir(artifacts, smoke)
    for spec in cfg.tasks:
        for sub in ("fits", "models"):
            (out / spec.task_id / sub).mkdir(parents=True, exist_ok=True)
    _log(f"loading {len(cfg.tasks)} tasks; ex_fuzzy {exfuzzy_version()}")
    ctxs = {spec.task_id: load_context(spec, Path(artifacts)) for spec in cfg.tasks}
    _STATE.update(specs={s.task_id: s for s in cfg.tasks}, ctxs=ctxs, out=out, smoke=smoke)
    first = plan_selection(cfg, ctxs)
    selected = [s for s in cfg.tasks if s.kind != "mixture"]
    total = len(first) + len(ARMS) * len(cfg.seeds) * len(selected)
    _log(f"{total} fits ({len(first)} before the shape selections are known), {workers} workers")
    done = run_pool(first, workers, 0, total)
    shapes = {}
    for spec in selected:
        shapes[spec.task_id] = {arm: chosen_shape(spec, ctxs[spec.task_id], out, arm) for arm in ARMS}
    (out / "selected_shapes.json").write_text(json.dumps(shapes, indent=2) + "\n")
    _log(f"selected shapes: {shapes}")
    done = run_pool(plan_final(cfg, ctxs, out), workers, done, total)
    _log(f"done: {done} fits")


# ------------------------------------------------------------------------------------------------ decision


def arm_summary(records: list[dict], water: bool) -> dict:
    """The selected fit (the published seed rule) of an arm and the aggregates over its seeds."""
    metric = "mae" if water else "macro_f1"
    records = sorted(records, key=lambda r: r["seed"])
    # published seed: lowest validation RMSE (water) / highest validation macro-F1; ties to the lowest seed
    pick = min(records, key=lambda r: r["validation"]["rmse"]) if water else max(
        records, key=lambda r: r["validation"][metric])
    values = [r["validation"][metric] for r in records]
    return {
        "metric": metric, "seeds": {r["seed"]: r["validation"][metric] for r in records},
        "selected_seed": pick["seed"], "M": pick["validation"][metric], "C": pick["total_conditions"],
        "median_M": statistics.median(values), "median_C": statistics.median(r["total_conditions"] for r in records),
        "mean_M": float(np.mean(values)), "sd_M": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "n_rules": pick["n_rules"], "mean_conditions": pick["mean_conditions"],
        "n_rules_ordinal": pick["n_rules_ordinal"], "n_conditions_ordinal": pick["n_conditions_ordinal"],
        "n_rules_compound": pick["n_rules_compound"], "n_conditions_compound": pick["n_conditions_compound"],
        "shape": pick["shape"], "rmse": pick["validation"].get("rmse"),
        "mean_fit_seconds": float(np.mean([r["fit_seconds"] for r in records])),
    }


def outcome(gain: float, tau: float, c_a: float, c_b: float) -> str:
    """``B`` if the gain beats the tolerance, or is within it with strictly fewer total conditions; else ``A``."""
    if gain > tau:
        return "B"
    return "B" if abs(gain) <= tau and c_b < c_a else "A"


def decide_task(a: dict, b: dict, water: bool, tau_f1: float, tau_share: float) -> dict:
    """Section 0.4: gain ``D`` and tolerance ``tau`` on the selected fits, and the same on the medians (robustness)."""
    def gain(m_a, m_b):
        return (m_a - m_b) if water else (m_b - m_a)  # positive: B is better (water: lower error)

    def tau(m_a):
        return tau_share * m_a if water else tau_f1

    primary = {"D": gain(a["M"], b["M"]), "tau": tau(a["M"])}
    primary["outcome"] = outcome(primary["D"], primary["tau"], a["C"], b["C"])
    median = {"D": gain(a["median_M"], b["median_M"]), "tau": tau(a["median_M"])}
    median["outcome"] = outcome(median["D"], median["tau"], a["median_C"], b["median_C"])
    return {"A": a, "B": b, "primary": primary, "median_check": median,
            "winner": primary["outcome"], "robust": primary["outcome"] == median["outcome"],
            "rule": "B wins if D > tau, or |D| <= tau and C_B < C_A (docs/ml/ordinal_conditions.md 0.4)"}


def decide(cfg: OrdinalConfig, artifacts: Path) -> dict:
    out = out_dir(artifacts)
    decisions = {}
    for spec in cfg.tasks:
        water = spec.kind == "water"
        recs = {arm: read_fits(out, spec.task_id, f"{arm}-seed*.json") for arm in ARMS}
        if any(len(r) != len(cfg.seeds) for r in recs.values()):
            raise SystemExit(f"{spec.task_id}: fits missing ({ {a: len(r) for a, r in recs.items()} })")
        if recs["A"][0]["partitions"] != recs["B"][0]["partitions"]:  # section 0.6: identical terms in both arms
            raise SystemExit(f"{spec.task_id}: the terms of A and B differ")
        decisions[spec.task_id] = decide_task(arm_summary(recs["A"], water), arm_summary(recs["B"], water), water,
                                              cfg.tau_macro_f1, cfg.tau_mae_share) | {"kind": spec.kind}
    doc = {"decided_at": datetime.now().isoformat(), "exfuzzy_version": exfuzzy_version(), "tasks": decisions,
           "checks": reproduction_checks(cfg, artifacts)}
    (out / "decisions.json").write_text(json.dumps(doc, indent=2, default=_json) + "\n")
    for task, d in decisions.items():
        print(f"{task}: D={d['primary']['D']:+.4f} tau={d['primary']['tau']:.4f} C_A={d['A']['C']} C_B={d['B']['C']} "
              f"-> {d['winner']} (median check: {d['median_check']['outcome']}, robust={d['robust']})")
    return doc


def reproduction_checks(cfg: OrdinalConfig, artifacts: Path) -> dict:
    """Section 0.6: A re-run against the mixture-serve fits on disk (rules, weights, validation macro-F1)."""
    out, checks = out_dir(artifacts), {}
    for spec in cfg.tasks:
        if spec.kind != "mixture":
            continue
        base = Path(artifacts) / spec.task_id / "experiments" / "mixture-serve" / "fits"
        rows = []
        for r in read_fits(out, spec.task_id, "A-seed*.json"):
            path = base / f"mix_search_nonneg-seed{r['seed']}.json"
            if not path.exists():
                continue
            old = json.loads(path.read_text())
            rows.append({"seed": r["seed"], "same_rules": old["rules"] == r["rules"],
                         "macro_f1_new": r["validation"]["macro_f1"], "macro_f1_old": old["validation"]["macro_f1"],
                         "same_weights": bool(np.array_equal(np.asarray(old["mixture"]["coef"]),
                                                             np.asarray(r["mixture"]["coef"])))})
        checks[spec.task_id] = rows
    return checks


# ------------------------------------------------------------------------------------------------ test


def test_task(spec: TaskSpec, cfg: OrdinalConfig, artifacts: Path) -> dict:
    """All seeds of both arms on the task's test rows (information only)."""
    out, ctx = out_dir(artifacts), load_context(spec, Path(artifacts))
    result = {}
    for arm in ARMS:
        rows = []
        for seed in cfg.seeds:
            with open(out / spec.task_id / "models" / f"{arm}-seed{seed}.pkl", "rb") as fh:
                model = pickle.load(fh)  # noqa: S301 - written by this module
            if spec.kind == "water":
                wd, feats = ctx.wd, ctx.config.base.features
                pos = wd.positions("test")
                pred = model.predict(wd.frame.loc[pos, feats])
                rows.append({"seed": seed, "test": {**regression_metrics(wd.y[pos], pred), "n": int(len(pos))}})
            else:
                pos = ctx.cd.data.positions("test")
                pred = model.predict(ctx.cd.data.frame.loc[pos, ctx.features])
                rows.append({"seed": seed, "test": _metrics(ctx.cd, pos, pred)})
        result[arm] = rows
    return result


def _test_one(args) -> tuple[str, dict]:
    spec, cfg, artifacts = args
    return spec.task_id, test_task(spec, cfg, artifacts)


def test(cfg: OrdinalConfig, artifacts: Path, workers: int) -> None:
    out = out_dir(artifacts)
    path = out / "decisions.json"
    if not path.exists() or set(json.loads(path.read_text())["tasks"]) != {t.task_id for t in cfg.tasks}:
        raise SystemExit("the test rows are read only after the decision of every task is recorded (decisions.json)")
    marker = out / "TEST_READ"
    if marker.exists():
        raise SystemExit(f"the test rows were already read ({marker.read_text().strip()}); refusing a second read")
    marker.write_text(f"{datetime.now().isoformat()}\n")
    (out / "test").mkdir(exist_ok=True)
    with mp.get_context("fork").Pool(min(workers, len(cfg.tasks)), maxtasksperchild=1) as pool:
        for k, (task, result) in enumerate(pool.imap_unordered(_test_one, [(t, cfg, artifacts) for t in cfg.tasks]), 1):
            (out / "test" / f"{task}.json").write_text(json.dumps(result, indent=2, default=_json) + "\n")
            print(f"[{k}/{len(cfg.tasks)}] task={task} test read", flush=True)


# ------------------------------------------------------------------------------------------------ report


def rule_lines(model, kind: str, labels: list[str], limit: int = 3) -> list[str]:
    """The ``limit`` rules with an ``at least`` / ``at most`` condition that have the largest effect, as text."""
    if kind == "water":
        rb = model.get_rulebase()
        rules, antecedents, names = rb.rules, rb.antecedents, feature_names(rb)
        effect = [abs(float(v)) for v in np.ravel(rb.scalar_consequents)]
        tail = [f"THEN dissolved oxygen += {float(v):+.3g}" for v in np.ravel(rb.scalar_consequents)]
    else:
        rb = get_master_rulebase(model)
        rules, antecedents, names = rb.get_rules(), rb.antecedents, classifier_feature_names(rb)
        if kind == "mixture":
            coef = np.asarray(model.estimator.mixture_.coef_)
            centred = coef - coef.mean(axis=1, keepdims=True)
            effect = (coef.max(axis=1) - coef.min(axis=1)).tolist()
            tail = ["centred weights " + " | ".join(f"{c} {w:+.2f}" for c, w in zip(labels, row, strict=True))
                    for row in centred]
        else:
            weights, classes = rule_weights(rb), rule_classes(rb)
            effect = [float(w) for w in weights]
            tail = [f"THEN {labels[c]} (weight {w:.2g})" for c, w in zip(classes, weights, strict=True)]
    used = [r for r, rule in enumerate(rules) if any(c.operator != "is" for c in rule_conditions(rule, antecedents))]
    lines = []
    for r in sorted(used, key=lambda r: -effect[r])[:limit]:
        text = " AND ".join(f"{names[c.feature]} IS {c.text}" for c in rule_conditions(rules[r], antecedents))
        lines.append(f"IF {text}: {tail[r]}")
    return lines


def report(cfg: OrdinalConfig, artifacts: Path) -> str:
    out = out_dir(artifacts)
    doc = json.loads((out / "decisions.json").read_text())
    md = ["| task | arm | selected seed (shape) | seeds | M | rules | total conditions | cond/rule | ordinal rules "
          "| ordinal conditions | compound conditions | fit s |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for task, d in doc["tasks"].items():
        water = d["kind"] == "water"
        for arm in ARMS:
            s = d[arm]
            seeds = " / ".join(f"{v:.4f}" for v in s["seeds"].values())
            md.append(f"| {task} | {arm} | {s['selected_seed']} ({s['shape'][0]}x{s['shape'][1]}) | {seeds} | "
                      f"{s['M']:.4f}{' MAE' if water else ''} | {s['n_rules']} | {s['C']} | "
                      f"{s['mean_conditions']:.2f} | "
                      f"{s['n_rules_ordinal']} | {s['n_conditions_ordinal']} | {s['n_conditions_compound']} | "
                      f"{s['mean_fit_seconds']:.0f} |")
    md += ["", "| task | D | tau | C_A | C_B | decision | median D | median check | robust |",
           "|---|---|---|---|---|---|---|---|---|"]
    for task, d in doc["tasks"].items():
        md.append(f"| {task} | {d['primary']['D']:+.4f} | {d['primary']['tau']:.4f} | {d['A']['C']} | {d['B']['C']} | "
                  f"{d['winner']} | {d['median_check']['D']:+.4f} | {d['median_check']['outcome']} | {d['robust']} |")
    if (out / "test").exists():
        md += ["", "| task | arm | test per seed | selected seed |", "|---|---|---|---|"]
        for task, d in doc["tasks"].items():
            t = json.loads((out / "test" / f"{task}.json").read_text())
            key = "mae" if d["kind"] == "water" else "macro_f1"
            for arm in ARMS:
                vals = {r["seed"]: r["test"][key] for r in t[arm]}
                md.append(f"| {task} | {arm} | {' / '.join(f'{v:.4f}' for v in vals.values())} | "
                          f"{vals[d[arm]['selected_seed']]:.4f} |")
    wins = [(t, d) for t, d in doc["tasks"].items() if d["winner"] == "B"]
    task, d = max(wins or doc["tasks"].items(), key=lambda kv: kv[1]["primary"]["D"] / kv[1]["primary"]["tau"])
    spec = next(s for s in cfg.tasks if s.task_id == task)
    with open(out / task / "models" / f"B-seed{d['B']['selected_seed']}.pkl", "rb") as fh:
        model = pickle.load(fh)  # noqa: S301 - written by this module
    labels = list(getattr(model, "class_labels", []))
    verdict = "a winning task" if wins else "no task won"
    md += ["", f"Example rules, {task} B seed {d['B']['selected_seed']} ({verdict}):"]
    md += [f"    {line}" for line in rule_lines(model, spec.kind, labels)]
    text = "\n".join(md) + "\n"
    (out / "report.md").write_text(text)
    return text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_ordinal", description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=["arms", "decide", "test", "report"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--smoke", action="store_true", help="arms: 2 generations x 8 individuals, seed 0, scored on "
                        "the fitting sample (no validation row), into ordinal_conditions-smoke")
    parser.add_argument("--tasks", nargs="*", help="arms: only these task ids (smoke runs)")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.stage == "arms":
        arms(cfg, args.artifacts_dir, args.workers, args.smoke, args.tasks)
    elif args.stage == "decide":
        decide(cfg, args.artifacts_dir)
    elif args.stage == "test":
        test(cfg, args.artifacts_dir, args.workers)
    else:
        print(report(cfg, args.artifacts_dir))


if __name__ == "__main__":
    main()
