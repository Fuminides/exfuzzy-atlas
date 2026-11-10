"""AT-041i: mixture-of-rules inference (ex_fuzzy PR 44) against the served winning-rule classifiers.

::

    python -m atlas.ml.experiment_mixture <stage> --config configs/ml/<task>_mixture_experiment.json [--workers 4]

Protocol, arms and decision rule: ``docs/ml/rule_mixture.md`` section 0 (pre-registered). Stages (resumable; everything
is written under ``<artifacts>/<task>/experiments/<experiment_id>/``):

* ``arms``: every (arm, seed) of ``ARMS`` not on disk yet, scored on the validation rows; one ``[k/N]`` log line per
  finished fit. ``--smoke`` runs a tiny search on seed 0 into ``<experiment_id>-smoke`` and scores the fitting sample
  instead (no validation or test row is read).
* ``decide``: the pre-registered rule (``decide_arms``), written to ``decision.json``.
* ``final --test``: the test rows, read once (a ``TEST_READ`` marker refuses a second read), for the served arm and the
  selected arm, with persistence, the served model's other reference baselines and a logistic regression refitted on
  the same rows, inputs and fitting sample.
* ``report``: the markdown tables of the report.

AT-041j (``serve`` block of the config, ``docs/ml/rule_mixture_serve.md``): the mixture is published for every task.
``arms`` fits the served reference and ``serve.arms``; ``decide`` takes the arm of highest mean validation macro-F1
(ties within ``serve.tie`` to non-negative weights) and its best validation seed, with no margin over the served
model; ``final --test`` also refits a random forest on the fitting sample with the model's inputs; ``runs`` writes the
run directory of the chosen fit (``artifacts/<task>/<run_prefix>-<nonneg|free>-seed<k>``) with the mixture rules
(contract v0.7), the test-period predictions and a ``metrics.json`` whose baseline rows are those of the served run
(same rows, split and fitting sample).

Rows, split, fitting sample (the served model's ``subsample_keys.parquet``) and partitions are those of the served
model, whose seeds are the ``served`` arm. Mixture weights are fitted on the fitting sample only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing as mp
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.ml.class_baselines import logistic_regression_baseline, random_forest_baseline
from atlas.ml.classification import classification_metrics
from atlas.ml.evaluation import PeakRss, classifier_rule_sets
from atlas.ml.exfuzzy_features import exfuzzy_version, require
from atlas.ml.experiment_class import ClassData, ClassExperimentConfig, _log, _summary
from atlas.ml.fuzzy_classifier import FuzzyClassifier
from atlas.paths import ARTIFACTS_DIR, REPO_ROOT

DECISIVE_SHARE = 0.001  # a rule is "decisive" if zeroing its weights changes >= 0.1 % of the fitting-sample predictions


class Arm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["served", "search"]  # the served seed's rules, or a new genetic search on the same sample
    mixture: bool = False  # inference = "mixture" (weights fitted on the fitting sample) instead of the winning rule
    non_negative: bool = False
    # how a re-search under the mixture prunes its candidates and final model (FuzzyClassifierParams.mixture_pruning)
    pruning: Literal["winning_rule", "mixture"] = "winning_rule"
    selectable: bool = False  # only mixture arms can be chosen; the others are reference and control
    description: str = ""


ARMS: dict[str, Arm] = {
    "served": Arm(source="served", description="the served winning-rule classifier (its arm's three seeds)"),
    "mix_served_nonneg": Arm(source="served", mixture=True, non_negative=True, selectable=True,
                             description="mixture on the served seed's own rules, weights >= 0"),
    "mix_served_free": Arm(source="served", mixture=True, selectable=True,
                           description="mixture on the served seed's own rules, unconstrained weights"),
    "mix_search_nonneg": Arm(source="search", mixture=True, non_negative=True, selectable=True,
                             description="rules re-searched with the GA scoring each candidate as its mixture, >= 0"),
    "mix_search_free": Arm(source="search", mixture=True, selectable=True,
                           description="rules re-searched with the GA scoring each candidate as its mixture, free"),
    "mix_search_nonneg_mp": Arm(source="search", mixture=True, non_negative=True, pruning="mixture", selectable=True,
                                description="re-searched under the mixture, pruned by the rules' role in it, >= 0"),
    "mix_search_free_mp": Arm(source="search", mixture=True, pruning="mixture", selectable=True,
                              description="re-searched under the mixture, pruned by the rules' role in it, free"),
    "search_winning": Arm(source="search", description="control: the winning-rule GA re-run on this ex_fuzzy build"),
}


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_gain: float = 0.02  # the margin is max(min_gain, 2 x the standard error of the difference of the 3-seed means)
    tie: float = 0.005
    max_mean_active_rules: float = 22.0  # mean number of rules with non-negligible weight (readability, as ica4)
    active_spread: float = 0.25  # "non-negligible weight": max_c W[r, c] - min_c W[r, c] >= 0.25 (log-odds)


class ServeConfig(BaseModel):
    """AT-041j: the mixture is published for every task (user decision, 2026-11-09), so the rule is a plain choice.

    The arm with the highest mean validation macro-F1 among ``arms``; arms within ``tie`` of it are tied and the tie
    goes to non-negative weights. The published seed is the chosen arm's best validation seed. There is no margin over
    the served model: the comparison is reported, not used to decide.
    """

    model_config = ConfigDict(extra="forbid")

    arms: list[str] = ["mix_search_nonneg", "mix_search_free"]
    tie: float = 0.005
    run_prefix: str = "mixture"  # run ids: <run_prefix>-nonneg-seed<k> / <run_prefix>-free-seed<k>
    # re-searched arms: FuzzyClassifierParams fields replacing the served model's (e.g. nRules / nAnts of other tasks)
    params: dict[str, int] = {}
    # pre-registered gate: the chosen arm is served only if its mean validation macro-F1 reaches this; else the served
    # winning-rule model stays (None: always served, the rule of the first nine tasks)
    serve_if_validation_mean_at_least: float | None = None
    # the run published for the task when the gate is set, which stays if the gate is not met (default: served_run)
    current_run: str | None = None


class MixtureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = "rule-mixture"
    kind: Literal["class", "nyc"] = "class"  # ClassData (air ICA / EAQI) or NycData (taxi demand level)
    task_config: str  # the served model's experiment config (rows, split, partitions), relative to the repository
    served_experiment: str  # <task>/experiments/<id> under artifacts: models/seed<k>.pkl, subsample_keys.parquet
    served_run: str  # <task>/<run id> under artifacts: the served model's run directory (metrics.json)
    served_seed: int
    seeds: list[int] = [0, 1, 2]
    mixture_C: float = 1.0
    mixture_prune_threshold: float = 0.02  # arms with pruning="mixture" (ex_fuzzy mixture_prune_threshold, log-odds)
    reference_baselines: list[str]  # estimators of the served metrics.json quoted in the test table
    decision: DecisionConfig = DecisionConfig()
    serve: ServeConfig | None = None  # AT-041j: publication protocol (arms, choice, run directories), no decision

    @property
    def arms(self) -> list[str]:
        """The arms this experiment fits: every arm, or (``serve``) the served reference and the publication arms."""
        return ["served", *self.serve.arms] if self.serve else list(ARMS)


# ------------------------------------------------------------------------------------------------ context


class Context:
    def __init__(self, config: MixtureConfig, artifacts_dir: Path, smoke: bool = False):
        self.cfg, self.smoke, self.artifacts = config, smoke, Path(artifacts_dir)
        text = (REPO_ROOT / config.task_config).read_text()
        if config.kind == "nyc":
            from atlas.ml.experiment_nyc import NycExperimentConfig

            self.task = NycExperimentConfig.model_validate_json(text)
        else:
            self.task = ClassExperimentConfig.model_validate_json(text)
        name = config.experiment_id + ("-smoke" if smoke else "")
        self.out = self.artifacts / self.task.base.task_id / "experiments" / name
        self.served_dir = self.artifacts / config.served_experiment
        self.served_run = self.artifacts / config.served_run
        for sub in ("val", "models", "fits"):
            (self.out / sub).mkdir(parents=True, exist_ok=True)
        self._cd = None
        self._sub: np.ndarray | None = None

    @property
    def features(self) -> list[str]:
        return list(self.task.base.features)

    @property
    def seeds(self) -> list[int]:
        return [self.cfg.seeds[0]] if self.smoke else list(self.cfg.seeds)

    @property
    def cd(self) -> ClassData:
        if self._cd is None:
            if self.cfg.kind == "nyc":
                from atlas.ml.experiment_nyc import NycData

                self._cd = NycData(self.task)
            else:
                self._cd = ClassData(self.task)
        return self._cd

    @property
    def sub_rows(self) -> np.ndarray:
        """The served model's fitting sample, as positions of the frame (in the order the served fit saw)."""
        if self._sub is None:
            frame = self.cd.data.frame
            keys = pd.read_parquet(self.served_dir / "subsample_keys.parquet")
            keys["entity_id"] = keys["entity_id"].astype(frame["entity_id"].dtype)
            index = frame[["entity_id", "issued_at_utc"]].reset_index().rename(columns={"index": "pos"})
            found = keys.merge(index, on=["entity_id", "issued_at_utc"], how="left")["pos"]
            if found.isna().any() or not np.isin(found.to_numpy(), self.cd.data.train_pos).all():
                raise AssertionError("the served fitting sample is not inside this task's complete training rows")
            self._sub = found.to_numpy(dtype=int)
        return self._sub

    def served_model(self, seed: int) -> FuzzyClassifier:
        with open(self.served_dir / "models" / f"seed{seed}.pkl", "rb") as fh:
            return pickle.load(fh)  # noqa: S301 - a run directory of this repository

    def arm_seeds(self, name: str) -> list[int]:
        """The seeds of an arm: every seed, except that an arm on the served rules only has the served seeds."""
        if ARMS[name].source != "served":
            return self.seeds
        return [s for s in self.seeds if (self.served_dir / "models" / f"seed{s}.pkl").exists()]

    def score_positions(self) -> np.ndarray:
        """Validation rows, or (smoke) the fitting sample, so that a smoke run reads no validation row."""
        return self.sub_rows if self.smoke else self.cd.data.positions("validation")

    def save_json(self, name: str, document: dict) -> None:
        (self.out / "val" / f"{name}.json").write_text(json.dumps(document, indent=2, default=_json) + "\n")

    def load_json(self, name: str) -> dict:
        return json.loads((self.out / "val" / f"{name}.json").read_text())


def _json(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def partitions_signature(estimator) -> list:
    """Names, terms and membership parameters of every input: two fits use the same terms iff these are equal."""
    return [(str(v.name), [(str(s.name), np.asarray(s.membership_parameters, dtype=float).tolist())
                           for s in v.linguistic_variables]) for v in estimator.lvs]


# ------------------------------------------------------------------------------------------------ fitting


def fit_arm(ctx: Context, name: str, seed: int) -> FuzzyClassifier:
    """The fitted classifier of ``name`` for ``seed``, on the served fitting sample."""
    arm, cd = ARMS[name], ctx.cd
    X_sub = cd.data.frame.loc[ctx.sub_rows, ctx.features]
    y_sub = cd.y_class[ctx.sub_rows]
    # a re-search takes the served model's hyperparameters (identical for every seed of its arm) from the same seed, or
    # from the served seed beyond the served arm's seeds
    own = arm.source == "served" or seed in ctx.arm_seeds("served")
    served = ctx.served_model(seed if own else ctx.cfg.served_seed)
    if arm.source == "served":
        if arm.mixture:
            require("rule_mixture")
            est = served.estimator  # pickled by the pinned release: set the options directly (set_params needs all)
            est.inference, est.mixture_C = "mixture", ctx.cfg.mixture_C
            est.mixture_non_negative, est.mixture_search = arm.non_negative, False
            est.fit_mixture(X_sub.to_numpy(dtype=float), y_sub)
        return served
    params = dataclasses.replace(
        served.params, batch_size=getattr(served.params, "batch_size", None),
        inference="mixture" if arm.mixture else "winning_rule", mixture_C=ctx.cfg.mixture_C,
        mixture_non_negative=arm.non_negative, mixture_search=arm.mixture, mixture_pruning=arm.pruning,
        mixture_prune_threshold=ctx.cfg.mixture_prune_threshold, **(ctx.cfg.serve.params if ctx.cfg.serve else {}))
    if ctx.smoke:
        params = dataclasses.replace(params, n_gen=2, pop_size=8)
    model = FuzzyClassifier(params, {f: ctx.task.base.feature_units[f] for f in ctx.features}).fit(
        X_sub, y_sub, cd.labels, seed, partition_reference=cd.partition_reference()[ctx.features],
        fixed={f: p for f, p in cd.fixed.items() if f in ctx.features})
    if partitions_signature(model.estimator) != partitions_signature(served.estimator):
        raise AssertionError(f"{name} seed {seed}: the terms differ from the served model's")
    return model


def mixture_stats(model: FuzzyClassifier, X: np.ndarray, active_spread: float) -> dict:
    """Weights, their spread, and how many rules matter, measured on the fitting sample ``X`` (training rows)."""
    from ex_fuzzy import rule_mixture as rm

    est = model.estimator
    mix = est.mixture_
    firing = rm.rule_firing(est.rule_base, X)
    base = mix.predict(firing, allow_unknown=est.rule_base.allow_unknown)
    changed = []
    for r in range(mix.coef_.shape[0]):
        coef = mix.coef_.copy()
        coef[r] = 0.0
        pred = np.argmax(firing @ coef + mix.intercept_, axis=1)
        if est.rule_base.allow_unknown:
            pred[~np.any(firing > 0, axis=1)] = -1
        changed.append(float(np.mean(pred != base)))
    spread = mix.weight_spread()
    return {
        "coef": mix.coef_, "intercept": mix.intercept_, "spread": spread, "share_changed_without_rule": changed,
        "n_active": int(np.sum(spread >= active_spread)),
        "n_decisive": int(np.sum(np.asarray(changed) >= DECISIVE_SHARE)),
        "duplicate_of": mix.duplicate_of_, "converged": bool(mix.converged_), "n_iter": int(mix.n_iter_),
        "text": est.print_mixture(return_text=True),
    }


def _metrics(cd: ClassData, pos: np.ndarray, pred: np.ndarray) -> dict:
    return _summary(classification_metrics(cd.y_class[pos], pred, len(cd.labels)), cd.labels)


def score(ctx: Context, name: str, seed: int, model: FuzzyClassifier, secs: float, rss: float) -> dict:
    cd, arm = ctx.cd, ARMS[name]
    pos = ctx.score_positions()
    pred = model.predict(cd.data.frame.loc[pos, ctx.features])
    rules = classifier_rule_sets(model, cd.labels)
    X_sub = cd.data.frame.loc[ctx.sub_rows, ctx.features]
    record = {
        "arm": name, "seed": seed, "scored_on": "fitting sample (smoke)" if ctx.smoke else "validation",
        "validation": _metrics(cd, pos, pred), "fit_sample": _metrics(cd, ctx.sub_rows, model.predict(X_sub)),
        "n_rules": len(rules), "mean_rule_length": float(np.mean([len(a) for a, _ in rules])) if rules else 0.0,
        "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rules],
        "fit_seconds": secs, "peak_rss_mb": rss, "n_fit_rows": int(len(ctx.sub_rows)),
        "exfuzzy_version": exfuzzy_version(), "fit_info": model.fit_info if arm.source == "search" else None,
    }
    if arm.mixture:
        record["mixture"] = mixture_stats(model, X_sub.to_numpy(dtype=float), ctx.cfg.decision.active_spread)
    return record


_CTX: Context | None = None  # set in the parent before forking; the workers read the shared table


def _fit_one(job: tuple[str, int]) -> dict:
    from threadpoolctl import threadpool_limits

    name, seed = job
    ctx = _CTX
    with threadpool_limits(1):  # BLAS threads only slow the small products of the mixture fits
        start = time.perf_counter()
        with PeakRss() as rss:
            model = fit_arm(ctx, name, seed)
        secs = time.perf_counter() - start
        record = score(ctx, name, seed, model, secs, rss.peak_mb)
    with open(ctx.out / "models" / f"{name}-seed{seed}.pkl", "wb") as fh:
        pickle.dump(model, fh)
    (ctx.out / "fits" / f"{name}-seed{seed}.json").write_text(json.dumps(record, default=_json) + "\n")
    return {"arm": name, "seed": seed, "macro_f1": record["validation"]["macro_f1"], "rules": record["n_rules"],
            "active": (record.get("mixture") or {}).get("n_active"), "secs": secs}


def pending_jobs(ctx: Context, arms: list[str]) -> list[tuple[str, int]]:
    """The (arm, seed) fits not on disk yet; searches (the slowest) first, so the pool does not end on one of them."""
    order = sorted(arms, key=lambda a: (ARMS[a].source != "search", not ARMS[a].mixture))
    return [(a, s) for a in order for s in ctx.arm_seeds(a) if not (ctx.out / "fits" / f"{a}-seed{s}.json").exists()]


def run_fits(ctx: Context, arms: list[str], workers: int, progress: tuple[int, int] | None = None) -> int:
    """Fit and score the pending jobs; one ``[k/N]`` line per finished fit. ``progress = (done, total)`` numbers the
    lines across several tasks of one command (``arms --config a.json b.json``). Returns the number of fits run."""
    global _CTX
    seeds = ctx.seeds
    jobs = pending_jobs(ctx, arms)
    done, total = progress or (0, len(jobs))
    _CTX = ctx
    if jobs:
        _ = ctx.cd, ctx.sub_rows  # loaded once in the parent, inherited by the forked workers
        _log(f"{ctx.task.base.task_id}: {len(jobs)} fits to run ({len(arms)} arms x {len(seeds)} seeds, the rest on "
             f"disk), {workers} workers; ex_fuzzy {exfuzzy_version()}; fitting sample {len(ctx.sub_rows)} rows")
        with mp.get_context("fork").Pool(min(workers, len(jobs)), maxtasksperchild=1) as pool:
            for k, r in enumerate(pool.imap_unordered(_fit_one, jobs), start=1):
                active = "" if r["active"] is None else f" active={r['active']}"
                print(f"[{done + k}/{total}] task={ctx.task.base.task_id} arm={r['arm']} seed={r['seed']} "
                      f"macroF1={r['macro_f1']:.3f} rules={r['rules']}{active} fit={r['secs']:.0f}s", flush=True)
    for name in arms:
        aggregate(ctx, name, ctx.arm_seeds(name))
    return len(jobs)


def aggregate(ctx: Context, name: str, seeds: list[int]) -> dict | None:
    paths = [ctx.out / "fits" / f"{name}-seed{s}.json" for s in seeds]
    if not all(p.exists() for p in paths):
        return None
    records = [json.loads(p.read_text()) for p in paths]
    f1 = [r["validation"]["macro_f1"] for r in records]
    doc = {"arm": name, "spec": ARMS[name].model_dump(), "seeds": records, "mean": float(np.mean(f1)),
           "sd": float(np.std(f1, ddof=1)) if len(f1) > 1 else 0.0, "min": float(np.min(f1)),
           "mean_rules": float(np.mean([r["n_rules"] for r in records]))}
    if ARMS[name].mixture:
        doc["mean_active"] = float(np.mean([r["mixture"]["n_active"] for r in records]))
        doc["mean_decisive"] = float(np.mean([r["mixture"]["n_decisive"] for r in records]))
    ctx.save_json(name, doc)
    return doc


# ------------------------------------------------------------------------------------------------ decision


def decide_arms(docs: dict[str, dict], dec: DecisionConfig, n_seeds: int) -> dict:
    """The pre-registered rule (``docs/ml/rule_mixture.md`` section 0.5), on the aggregated validation documents.

    Reference = the mean of ``served``. A selectable arm wins if its mean gain over the reference is at least
    ``max(min_gain, 2 * sqrt((sd_arm**2 + sd_served**2) / n_seeds))``, its worst seed is above the reference mean
    and its mean number of rules with non-negligible weight is at most ``max_mean_active_rules``. Among winners the
    highest mean is taken; arms within ``tie`` of it are tied, and the tie goes to non-negative weights, then to
    fewer rules with non-negligible weight, then to the served rules over re-searched ones. The proposed seed is the
    chosen arm's best validation seed. Without a winner the served model stays, and the selectable arm with the
    highest mean is named for an information-only test read.
    """
    ref = docs["served"]
    out = {"reference": "served", "reference_mean": ref["mean"], "reference_sd": ref["sd"], "arms": {}}
    winners = []
    for name, doc in docs.items():
        if not ARMS[name].selectable:
            continue
        margin = max(dec.min_gain, 2 * float(np.sqrt((doc["sd"] ** 2 + ref["sd"] ** 2) / n_seeds)))
        gain = doc["mean"] - ref["mean"]
        readable = doc["mean_active"] <= dec.max_mean_active_rules
        wins = gain >= margin and doc["min"] > ref["mean"] and readable
        out["arms"][name] = {"mean": doc["mean"], "sd": doc["sd"], "min": doc["min"], "gain": gain, "margin": margin,
                             "mean_active": doc["mean_active"], "readable": readable, "wins": wins}
        if wins:
            winners.append(name)
    chosen = None
    if winners:
        top = max(docs[n]["mean"] for n in winners)
        tied = [n for n in winners if top - docs[n]["mean"] <= dec.tie]
        chosen = min(tied, key=lambda n: (not ARMS[n].non_negative, docs[n]["mean_active"], ARMS[n].source != "served"))
    out["chosen"] = chosen
    out["proposed_seed"] = None if chosen is None else max(
        docs[chosen]["seeds"], key=lambda r: r["validation"]["macro_f1"])["seed"]
    selectable = [n for n in docs if ARMS[n].selectable]
    out["information_arm"] = None if chosen or not selectable else max(selectable, key=lambda n: docs[n]["mean"])
    return out


SUPPRESSION_THRESHOLD = 0.25  # a centred weight <= -0.25: a fully firing rule lowers that class by >= 0.25 (log-odds)


def suppression_stats(coef, labels: list[str], rules: list) -> dict:
    """Support and suppression of the rules in the centred form ``W - mean_c W`` (same predictions as ``W``).

    ``n_rules_suppressing``: rules with at least one centred weight <= -``SUPPRESSION_THRESHOLD``;
    ``mostly_suppressing``: those of them whose largest centred effect is negative (|min| > max), each with its
    weights; duplicates (all-zero weights) are left out."""
    from atlas.explain.mixture import centred_weights

    coef = np.asarray(coef, dtype=float)
    centred = centred_weights(coef)
    live = [r for r in range(len(coef)) if coef[r].max() != coef[r].min()]
    suppressing = [r for r in live if centred[r].min() <= -SUPPRESSION_THRESHOLD]
    mostly = sorted((r for r in suppressing if -centred[r].min() > centred[r].max()),
                    key=lambda r: centred[r].min())
    return {
        "threshold": SUPPRESSION_THRESHOLD, "n_rules": len(live), "n_rules_suppressing": len(suppressing),
        "share_rules_suppressing": len(suppressing) / len(live) if live else 0.0,
        "n_rules_mostly_suppressing": len(mostly),
        "mostly_suppressing": [{"position": r, "antecedents": rules[r]["antecedents"],
                                "search_class": rules[r]["class"],
                                "weights": dict(zip(labels, coef[r].tolist(), strict=True)),
                                "centred": dict(zip(labels, centred[r].round(4).tolist(), strict=True))}
                               for r in mostly],
    }


def decide_serve(ctx: Context) -> dict:
    """AT-041j: the arm of highest mean validation macro-F1 among ``serve.arms`` (ties within ``serve.tie`` go to
    non-negative weights) and its best validation seed. The served model is the reference of the report, not a bar."""
    serve = ctx.cfg.serve
    docs = {n: ctx.load_json(n) for n in ["served", *serve.arms] if (ctx.out / "val" / f"{n}.json").exists()}
    if missing := [n for n in ["served", *serve.arms] if n not in docs]:
        raise SystemExit(f"arms without validation results: {missing}")
    top = max(docs[n]["mean"] for n in serve.arms)
    tied = [n for n in serve.arms if top - docs[n]["mean"] <= serve.tie]
    chosen = min(tied, key=lambda n: (not ARMS[n].non_negative, -docs[n]["mean"]))
    best = max(docs[chosen]["seeds"], key=lambda r: r["validation"]["macro_f1"])
    labels = ctx.cd.labels
    arms = {}
    for n in serve.arms:
        arms[n] = {k: docs[n][k] for k in ("mean", "sd", "min", "mean_rules", "mean_active", "mean_decisive")}
        arms[n]["seeds"] = {r["seed"]: r["validation"]["macro_f1"] for r in docs[n]["seeds"]}
        arms[n]["gain_over_served"] = docs[n]["mean"] - docs["served"]["mean"]
        arms[n]["suppression"] = [
            {k: v for k, v in suppression_stats(r["mixture"]["coef"], labels, r["rules"]).items()
             if k != "mostly_suppressing"} for r in docs[n]["seeds"]]
    gate, current = serve.serve_if_validation_mean_at_least, serve.current_run or ctx.cfg.served_run
    rule = (f"highest mean validation macro-F1 among {serve.arms}; arms within {serve.tie} of it are tied and the tie "
            "goes to non-negative weights; the published seed is the chosen arm's best validation seed; ")
    rule += ("no margin over the served model (the mixture is published for every task, user decision 2026-11-09)"
             if gate is None else f"published only if the chosen arm's mean validation macro-F1 is at least {gate} "
             f"(pre-registered gate), otherwise {current} stays")
    out = {
        "rule": rule, "current_run": current,
        "pruning": {n: ARMS[n].pruning for n in serve.arms}, "mixture_prune_threshold": ctx.cfg.mixture_prune_threshold,
        "reference": "served", "reference_mean": docs["served"]["mean"], "reference_sd": docs["served"]["sd"],
        "reference_seeds": {r["seed"]: r["validation"]["macro_f1"] for r in docs["served"]["seeds"]},
        "arms": arms, "tied": tied, "chosen": chosen, "proposed_seed": best["seed"], "information_arm": None,
        "params": dict(serve.params), "serve_if_validation_mean_at_least": serve.serve_if_validation_mean_at_least,
        "serve": (serve.serve_if_validation_mean_at_least is None
                  or docs[chosen]["mean"] >= serve.serve_if_validation_mean_at_least),
        "chosen_fit": {"n_rules": best["n_rules"], "n_active": best["mixture"]["n_active"],
                       "n_decisive": best["mixture"]["n_decisive"], "converged": best["mixture"]["converged"],
                       "suppression": suppression_stats(best["mixture"]["coef"], labels, best["rules"]),
                       "text": best["mixture"]["text"]},
    }
    (ctx.out / "decision.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def decide(ctx: Context) -> dict:
    if ctx.cfg.serve is not None:
        return decide_serve(ctx)
    docs = {n: ctx.load_json(n) for n in ARMS if (ctx.out / "val" / f"{n}.json").exists()}
    missing = [n for n in ARMS if n not in docs]
    if missing:
        raise SystemExit(f"arms without validation results: {missing}")
    out = decide_arms(docs, ctx.cfg.decision, len(ctx.seeds))
    (ctx.out / "decision.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


# ---------------------------------------------------------------------------------------------- final (test)


def served_reference(ctx: Context, names: list[str]) -> dict:
    """``validation/all`` and ``all`` (test) macro-F1 of estimators in the served model's metrics.json."""
    rows = json.loads((ctx.served_run / "metrics.json").read_text())["rows"]
    out = {}
    for name in names:
        got = {r["slice"]: r for r in rows if r["estimator"] == name and r["metric"] == "macro_f1"
               and r["slice"] in ("validation/all", "all")}
        out[name] = {"validation": got["validation/all"]["value"], "test": got["all"]["value"],
                     "n_validation": got["validation/all"]["n"], "n_test": got["all"]["n"]}
    return out


def final(ctx: Context) -> None:
    marker = ctx.out / "TEST_READ"
    if marker.exists():
        raise SystemExit(f"the test rows were already read ({marker.read_text().strip()}); refusing a second read")
    decision = json.loads((ctx.out / "decision.json").read_text())
    tested = decision["chosen"] or decision["information_arm"]
    marker.write_text(f"{datetime.now().isoformat()} chosen={decision['chosen']} tested={tested}\n")
    cd, d = ctx.cd, ctx.cd.data
    periods = {p: ctx.sub_rows if ctx.smoke else d.positions(p) for p in ("validation", "test")}  # smoke: no real rows
    out = {"decision": decision, "tested_arm": tested, "rows": {p: int(len(v)) for p, v in periods.items()},
           "fuzzy": {}, "baselines": {}, "checks": {}}
    for name in ["served", tested]:
        rows = []
        for seed in ctx.arm_seeds(name):
            with open(ctx.out / "models" / f"{name}-seed{seed}.pkl", "rb") as fh:
                model = pickle.load(fh)  # noqa: S301 - written by this module
            rows.append({"seed": seed, **{p: _metrics(cd, pos, model.predict(d.frame.loc[pos, ctx.features]))
                                          for p, pos in periods.items()}})
        out["fuzzy"][name] = rows
        _log(f"final {name}: test macro-F1 {[round(r['test']['macro_f1'], 4) for r in rows]}")
    reference = served_reference(ctx, ["exfuzzy_classifier", *ctx.cfg.reference_baselines])
    out["baselines"]["served_metrics_json"] = reference
    served_row = next((r for r in out["fuzzy"]["served"] if r["seed"] == ctx.cfg.served_seed), None)
    if served_row is not None:  # [this experiment, metrics.json]: the same rows give the same score
        out["checks"]["served_seed_reproduces_metrics_json"] = {
            p: [served_row[p]["macro_f1"], reference["exfuzzy_classifier"][p]] for p in ("validation", "test")}
    # logistic regression refitted on the same fitting sample: the fuzzy inputs, and (NYC) the baselines' inputs
    variants = {"logistic_regression_subsample_fuzzy_inputs": (logistic_regression_baseline, ctx.features)}
    if getattr(ctx.task, "baseline_features", None):
        variants["logistic_regression_subsample_baseline_inputs"] = (logistic_regression_baseline,
                                                                     list(ctx.task.baseline_features))
    if ctx.cfg.serve is not None:  # AT-041j: the forest of the same rows and inputs as well
        variants["random_forest_subsample_fuzzy_inputs"] = (random_forest_baseline, ctx.features)
    sub = ctx.sub_rows
    for name, (make, features) in variants.items():
        baseline = make(name, features, seed=ctx.task.base.seed)
        baseline.fit(d.frame.loc[sub], cd.y_class[sub])
        out["baselines"][name] = {"features": features, **{
            p: _metrics(cd, pos, np.concatenate([baseline.predict(d.frame.loc[pos[i:i + 500_000]])
                                                 for i in range(0, max(len(pos), 1), 500_000)]))
            for p, pos in periods.items()}}
        _log(f"final {name}: val {out['baselines'][name]['validation']['macro_f1']:.3f} "
             f"test {out['baselines'][name]['test']['macro_f1']:.3f}")
    (ctx.out / "final_test.json").write_text(json.dumps(out, indent=2, default=_json) + "\n")


# ---------------------------------------------------------------------------------------------- run directory


def mixture_readability_rows(model, X: np.ndarray, rule_ids: list[str], prefix: str = "",
                             include_static: bool = True) -> list:
    """Readability rows of a mixture of rules: rule counts and, on the finite rows ``X``, how often no rule fires and
    each rule's top-contributor and decisive shares (contract v0.7 importance measures; never probabilities)."""
    from atlas.contracts import models as m
    from atlas.explain.mixture import compute_mixture_activations, fitted_mixture
    from atlas.ml.experiment_class import FUZZY_CLASSIFIER

    est = FUZZY_CLASSIFIER
    coef = np.asarray(fitted_mixture(model).coef_)
    spread = coef.max(axis=1) - coef.min(axis=1)
    centred = coef - coef.mean(axis=1, keepdims=True)
    n_rules = len(rule_ids)
    rows = []
    if include_static:
        rules = classifier_rule_sets(model, model.class_labels)
        rows += [
            m.MetricRow(estimator=est, metric="n_rules", value=float(n_rules), n=n_rules),
            m.MetricRow(estimator=est, metric="mean_rule_length", n=n_rules,
                        value=float(np.mean([len(a) for a, _ in rules])) if rules else 0.0),
            m.MetricRow(estimator=est, metric="n_rules_weight_spread_ge_0.25", n=n_rules,
                        value=float((spread >= 0.25).sum())),
            m.MetricRow(estimator=est, metric=f"n_rules_suppressing_le_-{SUPPRESSION_THRESHOLD:g}", n=n_rules,
                        value=float((centred.min(axis=1) <= -SUPPRESSION_THRESHOLD).sum())),
        ]
    n = len(X)
    tops, decisive, fired = np.zeros(n_rules), np.zeros(n_rules), 0
    for i in range(0, max(n, 1), 200_000):
        if not n:
            break
        act = compute_mixture_activations(model, X[i:i + 200_000])
        tops += np.bincount(act.top[act.top >= 0], minlength=n_rules)
        decisive += act.decisive.sum(axis=0)
        fired += int(np.any(act.firing > 0, axis=1).sum())
    rows.append(m.MetricRow(estimator=est, metric="share_no_rule_fires", value=float(1 - fired / n) if n else 0.0,
                            n=n, slice=prefix + "all"))
    for r, rule_id in enumerate(rule_ids):
        rows.append(m.MetricRow(estimator=est, metric="rule_top_share", value=float(tops[r] / n) if n else 0.0, n=n,
                                slice=f"{prefix}rule={rule_id}"))
        rows.append(m.MetricRow(estimator=est, metric="rule_decisive_share", value=float(decisive[r] / n) if n else 0.0,
                                n=n, slice=f"{prefix}rule={rule_id}"))
    return rows


def write_serve_run(ctx: Context) -> Path:
    """The run directory of the chosen arm and seed (AT-041j): model, contract v0.7 rules, metrics, test predictions."""
    from datetime import timezone

    from atlas.contracts import models as m
    from atlas.explain.classifier import rule_ids
    from atlas.ml import artifacts
    from atlas.ml.classification import classification_metric_rows
    from atlas.ml.exfuzzy_features import provenance_warnings
    from atlas.ml.experiment_class import FUZZY_CLASSIFIER, VALIDATION_PREFIX
    from atlas.ml.rules_export import export_classifier_rules

    decision = json.loads((ctx.out / "decision.json").read_text())
    if not (ctx.out / "final_test.json").exists():
        raise SystemExit("runs needs final --test first (the run directory reports the test period)")
    arm, seed = decision["chosen"], decision["proposed_seed"]
    if not decision.get("serve", True):
        raise SystemExit(f"the pre-registered gate was not met ({decision['arms'][arm]['mean']:.4f} < "
                         f"{decision['serve_if_validation_mean_at_least']}): "
                         f"{decision.get('current_run', ctx.cfg.served_run)} stays")
    with open(ctx.out / "models" / f"{arm}-seed{seed}.pkl", "rb") as fh:
        model = pickle.load(fh)  # noqa: S301 - written by this module
    fit = json.loads((ctx.out / "fits" / f"{arm}-seed{seed}.json").read_text())
    cd, d, base = ctx.cd, ctx.cd.data, ctx.task.base
    nyc = ctx.cfg.kind == "nyc"
    run_id = f"{ctx.cfg.serve.run_prefix}-{'nonneg' if ARMS[arm].non_negative else 'free'}-seed{seed}"
    model_id = f"exfuzzy-{base.task_id}-{run_id}"
    if nyc:
        from atlas.ml.experiment_nyc import TARGET_LABEL
        scheme, target_label = cd.target_scheme, TARGET_LABEL
    else:
        scheme, target_label = cd.scheme.to_target_scheme(), ctx.task.target_label
    sub_frame = d.frame.loc[ctx.sub_rows]
    rules = export_classifier_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=target_label,
        target_scheme=scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
        synthetic=base.synthetic, feature_units=base.feature_units, X_reference=sub_frame[ctx.features])
    ids = rule_ids(model.rule_base)
    served = json.loads((ctx.served_run / "metrics.json").read_text())
    rows = [m.MetricRow.model_validate(r) for r in served["rows"] if r["estimator"] != FUZZY_CLASSIFIER]
    for period, prefix in (("validation", VALIDATION_PREFIX), ("test", "")):
        pos = d.positions(period)
        frame = d.frame.loc[pos]
        rows += classification_metric_rows(FUZZY_CLASSIFIER, cd.y_class[pos], model.predict(frame[ctx.features]),
                                           cd.labels, {"entity": frame["entity_id"].array}, prefix=prefix)
        X = frame[ctx.features].to_numpy(dtype=float)
        rows += mixture_readability_rows(model, X[np.isfinite(X).all(axis=1)], ids, prefix,
                                         include_static=period == "test")
    rows += [m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_seconds", value=fit["fit_seconds"],
                         n=fit["n_fit_rows"]),
             m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_peak_rss_mb", value=fit["peak_rss_mb"],
                         n=fit["n_fit_rows"])]
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    served_manifest = json.loads((ctx.served_run / "run_manifest.json").read_text())
    counts = np.bincount(cd.y_class[ctx.sub_rows], minlength=len(cd.labels)).tolist()
    mix = fit["mixture"]
    warnings = [
        f"fitted on the served model's class-aware subsample of {len(ctx.sub_rows)} of the {len(d.train_pos)} "
        f"complete training rows (class counts {counts}; {ctx.served_dir.relative_to(ctx.artifacts)}/"
        "subsample_keys.parquet); the mixture weights and biases therefore reflect that sampling, not the natural "
        "class frequencies",
        "mixture of rules (ex_fuzzy inference='mixture', contract v0.7): every rule that fires adds class_weights x "
        "firing to every class score and the class is the largest score plus bias; no single rule decides. A weight "
        "is a coefficient of a fitted multinomial logistic model on the rule firings, not a probability, a confidence "
        "or a risk; negative centred weights suppress a class relative to the others, they are not evidence against "
        "it. The softmax of the scores is not served",
        f"rules re-searched under the mixture (mixture_search) with the served model's "
        f"{'budget' if ctx.cfg.serve.params else 'shape, budget'}"
        f"{'' if not ctx.cfg.serve.params else ' and the shape ' + str(ctx.cfg.serve.params)}, terms and "
        + ("pruning" if ARMS[arm].pruning == "winning_rule" else
           "weighting, but the candidates and the final model pruned by the rules' role in the mixture (a rule whose "
           f"largest centred contribution on the fitting sample is at most {ctx.cfg.mixture_prune_threshold:g} "
           "log-odds is deleted, so rules that only suppress a class stay)")
        + f"; selected in experiment {ctx.cfg.experiment_id} ({arm}, seed {seed}): {decision['rule']}",
        *provenance_warnings(ctx.task),
    ]
    if nyc:
        warnings.append(served_manifest["warnings"][1])  # the level is relative to the zone's own 2024 norm
    hyper = {
        **model.params.as_dict(), "task_type": "classification", "target_label": target_label,
        "class_labels": cd.labels, "persistence_feature": base.persistence_feature, "timezone": base.timezone,
        "n_train_rows": len(ctx.sub_rows), "fit_info": model.fit_info,
        "sampling_power": served_manifest["hyperparameters"].get("sampling_power"),
        "experiment": json.loads(ctx.task.model_dump_json(exclude={"base"})),
        "run_config": json.loads(base.model_copy(update={"seed": seed, "run_id": run_id}).model_dump_json()),
        "selected_arm": arm, "selection_experiment": ctx.cfg.experiment_id,
        "selection": {k: decision[k] for k in ("rule", "chosen", "proposed_seed", "tied")},
        "served_reference_run": ctx.cfg.served_run,
        "mixture": {"C": ctx.cfg.mixture_C, "non_negative": ARMS[arm].non_negative, "pruning": ARMS[arm].pruning,
                    "n_iter": mix["n_iter"],
                    "converged": mix["converged"], "n_active_rules_spread_ge_0.25": mix["n_active"],
                    "n_decisive_rules_fitting_sample": mix["n_decisive"]},
        "baseline_rows": f"copied from {ctx.cfg.served_run}/metrics.json (same rows, split and fitting sample)",
    }
    if not nyc:
        hyper["official_labels"] = cd.official.labels
    created = datetime.now(timezone.utc)
    commit, dirty = artifacts.git_state()
    manifest = m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
        git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
        python_version=artifacts.python_version(), seed=seed, split=base.split, data_version=base.data_version,
        data_checksums=base.data_checksums, target=base.target, horizon_hours=base.horizon_hours,
        features=list(base.features), hyperparameters=hyper,
        artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                   "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE},
        warnings=warnings,
    )
    test_all = d.frame.loc[d.masks["test"]]
    if nyc:
        from atlas.services.publish import _class_predictions

        predictions = _class_predictions(
            model, test_all, list(base.features), test_all[base.target_column].to_numpy(dtype=float), scheme,
            pd.Timedelta(hours=base.horizon_hours), test_all[ctx.task.label_column], mixture=True, rule_ids=ids)
        predictions["model_id"] = model_id
    else:
        from atlas.ml.experiment_class import _class_prediction_table

        predictions = _class_prediction_table(model, test_all, cd, model_id)
    run_dir = artifacts.write_run_dir(
        ctx.artifacts / base.task_id / run_id, model=model,
        parity_sample=d.frame.loc[d.positions("test"), list(base.features)].head(500),
        json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                    "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                    "rules.json": rules.model_dump_json(indent=2) + "\n"},
        parquet_files={"predictions.parquet": predictions},
    )
    _log(f"wrote {run_dir}")
    return run_dir


# ---------------------------------------------------------------------------------------------- report


def _ms(values) -> str:
    values = np.asarray(values, dtype=float)
    sd = np.std(values, ddof=1) if len(values) > 1 else 0.0
    return f"{np.mean(values):.3f} ± {sd:.3f}"


def _each(values) -> str:
    return " / ".join(f"{v:.3f}" for v in values)


def report(ctx: Context) -> str:
    """The validation table of every arm and, once ``final`` ran, the test table."""
    spread = ctx.cfg.decision.active_spread
    lines = [f"| arm | val macro-F1 | seeds | bal-acc | acc | rules | rules with weight spread >= {spread} | "
             "decisive rules | fit s |", "|---|---|---|---|---|---|---|---|---|"]
    for name in ARMS:
        path = ctx.out / "val" / f"{name}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        v = [r["validation"] for r in doc["seeds"]]
        f1 = [x["macro_f1"] for x in v]
        cells = [name, _ms(f1), _each(f1), _ms([x["balanced_accuracy"] for x in v]), _ms([x["accuracy"] for x in v]),
                 f"{doc['mean_rules']:.1f}", f"{doc.get('mean_active', float('nan')):.1f}",
                 f"{doc.get('mean_decisive', float('nan')):.1f}",
                 f"{np.mean([r['fit_seconds'] for r in doc['seeds']]):.0f}"]
        lines.append("| " + " | ".join(cells) + " |")
    path = ctx.out / "final_test.json"
    if path.exists():
        doc = json.loads(path.read_text())
        lines += ["", "| model | val macro-F1 | test macro-F1 | test bal-acc | test acc |", "|---|---|---|---|---|"]
        for name, rows in doc["fuzzy"].items():
            cells = [f"ExFuzzy {name}", _ms([r["validation"]["macro_f1"] for r in rows]),
                     *[_ms([r["test"][k] for r in rows]) for k in ("macro_f1", "balanced_accuracy", "accuracy")]]
            lines.append("| " + " | ".join(cells) + " |")
            seeds = " / ".join(str(r["seed"]) for r in rows)
            lines.append(f"| ExFuzzy {name}, seeds {seeds} | {_each(r['validation']['macro_f1'] for r in rows)} | "
                         f"{_each(r['test']['macro_f1'] for r in rows)} | | |")
        for name, res in doc["baselines"]["served_metrics_json"].items():
            lines.append(f"| {name} (served metrics.json) | {res['validation']:.3f} | {res['test']:.3f} | | |")
        for name, res in doc["baselines"].items():
            if name != "served_metrics_json":
                test = res["test"]
                lines.append(f"| {name} (refit) | {res['validation']['macro_f1']:.3f} | {test['macro_f1']:.3f} | "
                             f"{test['balanced_accuracy']:.3f} | {test['accuracy']:.3f} |")
    text = "\n".join(lines)
    print(text)
    return text


def serve_summary(contexts: list[Context]) -> str:
    """AT-041j: one markdown table of validation and test macro-F1 per task, rule counts and suppression."""
    head = ["| task | model | val macro-F1 | test macro-F1 |", "|---|---|---|---|"]
    rules = ["| task | published run | rules | weight spread >= 0.25 | decisive (fit sample) | suppressing "
             f"(centred <= -{SUPPRESSION_THRESHOLD:g}) | mostly suppressing | served model rules |",
             "|---|---|---|---|---|---|---|---|"]
    for ctx in contexts:
        task = ctx.task.base.task_id
        decision = json.loads((ctx.out / "decision.json").read_text())
        final_doc = json.loads((ctx.out / "final_test.json").read_text())
        arm, seed = decision["chosen"], decision["proposed_seed"]
        served = final_doc["fuzzy"]["served"]
        chosen = final_doc["fuzzy"][arm]
        pick = next(r for r in chosen if r["seed"] == seed)
        own = next(r for r in served if r["seed"] == ctx.cfg.served_seed)
        tag = "nonneg" if ARMS[arm].non_negative else "free"

        def cell(rows, period):
            return _ms([r[period]["macro_f1"] for r in rows])

        lines = [
            (f"winning rule, served (seed {ctx.cfg.served_seed})", f"{own['validation']['macro_f1']:.3f}",
             f"{own['test']['macro_f1']:.3f}"),
            ("winning rule, served arm (3 seeds)", cell(served, "validation"), cell(served, "test")),
            (f"**mixture `{arm}`, published (seed {seed})**", f"**{pick['validation']['macro_f1']:.3f}**",
             f"**{pick['test']['macro_f1']:.3f}**"),
            (f"mixture `{arm}` (3 seeds)", cell(chosen, "validation"), cell(chosen, "test")),
        ]
        other = [n for n in ctx.cfg.serve.arms if n != arm]
        for n in other:
            doc = decision["arms"][n]
            lines.append((f"mixture `{n}` (3 seeds, not tested)", f"{doc['mean']:.3f} ± {doc['sd']:.3f}", "-"))
        ref = final_doc["baselines"]["served_metrics_json"]
        names = {"persistence": "persistence", "persistence_24h": "same hour yesterday (`persistence_24h`)",
                 "persistence_rel_lag24": "same hour yesterday (`persistence_rel_lag24`)",
                 "logistic_regression_subsample": "LR, fitting sample (served metrics.json)",
                 "random_forest_subsample": "RF, fitting sample (served metrics.json)"}
        for key, label in names.items():
            if key in ref:
                if key.endswith("_subsample") and ctx.cfg.kind == "nyc":
                    label += ", 12 baseline inputs"
                lines.append((label, f"{ref[key]['validation']:.3f}", f"{ref[key]['test']:.3f}"))
        for key, label in (("logistic_regression_subsample_fuzzy_inputs", "LR refit, fitting sample, model inputs"),
                           ("random_forest_subsample_fuzzy_inputs", "RF refit, fitting sample, model inputs")):
            if key in final_doc["baselines"]:
                b = final_doc["baselines"][key]
                lines.append((label, f"{b['validation']['macro_f1']:.3f}", f"{b['test']['macro_f1']:.3f}"))
        for k, (label, val, test) in enumerate(lines):
            head.append(f"| {task if k == 0 else ''} | {label} | {val} | {test} |")
        fit = decision["chosen_fit"]
        sup = fit["suppression"]
        served_rules = json.loads((ctx.served_run / "rules.json").read_text())["rules"]
        run_id = f"{ctx.cfg.serve.run_prefix}-{tag}-seed{seed}"
        rules.append(f"| {task} | `{run_id}` | {fit['n_rules']} | {fit['n_active']} | "
                     f"{fit['n_decisive']} | {sup['n_rules_suppressing']} of {sup['n_rules']} "
                     f"({sup['share_rules_suppressing']:.0%}) | {sup['n_rules_mostly_suppressing']} | "
                     f"{len(served_rules)} |")
    text = "\n".join([*head, "", *rules])
    print(text)
    return text


# --------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_mixture",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=["arms", "decide", "final", "runs", "report", "summary"])
    parser.add_argument("--config", type=Path, nargs="+", required=True,
                        help="one or more experiment configs; each stage runs them in order (arms numbers its [k/N] "
                        "progress over all of them)")
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", default=None, help="arms: comma separated subset of the arms")
    parser.add_argument("--smoke", action="store_true",
                        help="tiny search, seed 0, into <experiment_id>-smoke; every score is on the fitting sample")
    parser.add_argument("--test", action="store_true", help="final: read the test rows (once)")
    args = parser.parse_args(argv)
    contexts = [Context(MixtureConfig.model_validate_json(path.read_text()), args.artifacts_dir, smoke=args.smoke)
                for path in args.config]
    start = time.perf_counter()
    if args.stage == "arms":
        plan = []
        for ctx in contexts:
            arms = args.only.split(",") if args.only else ctx.cfg.arms
            if unknown := [a for a in arms if a not in ARMS]:
                raise SystemExit(f"unknown arms {unknown}; known: {list(ARMS)}")
            plan.append((ctx, arms))
        total, done = sum(len(pending_jobs(ctx, arms)) for ctx, arms in plan), 0
        _log(f"{total} fits to run over {len(plan)} task(s)")
        for ctx, arms in plan:
            done += run_fits(ctx, arms, args.workers, progress=(done, total))
            ctx._cd = ctx._sub = None  # free the task's table before the next one
    if args.stage == "summary":
        serve_summary(contexts)
    for ctx in contexts:
        if args.stage == "decide":
            print(json.dumps(decide(ctx), indent=2))
        elif args.stage == "final":
            if not args.test:
                raise SystemExit("final reads the test rows: pass --test (once)")
            final(ctx)
        elif args.stage == "runs":
            if ctx.cfg.serve is None:
                raise SystemExit("runs is the publication stage of a serve config (AT-041j)")
            print(write_serve_run(ctx))
        elif args.stage == "report":
            report(ctx)
    _log(f"{args.stage} finished in {time.perf_counter() - start:.0f}s at {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
