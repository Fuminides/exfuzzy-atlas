"""AT-041h: diurnal inputs for the Madrid ICA winning-rule classifier (ex_fuzzy 3.3.1), validation first, test once.

::

    python -m atlas.ml.experiment_ica4 <stage> --config configs/ml/madrid_no2_h6_ica4_experiment.json [--workers 8]

Stages (resumable; everything is written under ``<artifacts>/<task>/experiments/<experiment_id>/``):

* ``base``: the AT-041d pickles re-scored on the common validation rows (``val/base_published.json``).
* ``arms``: the pre-registered stage-1 arms (``base_refit`` and one diurnal input each), seeds 0-2.
* ``stage2``: the arms that the stage-1 results define by the pre-registered rule (combination, compact inputs).
* ``shape``: nRules x nAnts re-selection (3 seeds per shape) of the best stage-1/2 arm.
* ``robust``: seeds 3-4 of the winner and of ``base_refit`` (information only, never selects).
* ``report`` / ``decide``: markdown tables; the decision rule of ``docs/ml/madrid_no2_h6_ica_v4.md`` section 0.
* ``final --test``: the test rows, read once (a marker file refuses a second run), for the chosen arm, base,
  persistence and the control baselines with and without the new inputs.

Fits of a stage run in parallel worker processes (fork; the table is loaded once). The log has one
``[k/N] arm=... seed=...`` line per finished fit.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pickle
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.ml import diurnal_features as dfe
from atlas.ml.classification import classification_metrics
from atlas.ml.evaluation import classifier_rule_sets, rule_set_stability
from atlas.ml.experiment_class import (
    Candidate,
    ClassData,
    ClassExperimentConfig,
    _baselines,
    _fit,
    _log,
    _params,
    _resolve,
    _summary,
    experiment_dir,
)
from atlas.ml.partitions import load_partition_file
from atlas.ml.split import split_masks
from atlas.ml.subsample import stratified_subsample
from atlas.paths import ARTIFACTS_DIR, REPO_ROOT

LAGS = ("no2_lag1h", "no2_lag3h", "no2_lag24h")
EXPECTATION_FAMILY = (dfe.CLIM_VALID, dfe.EXPECTED, dfe.EXPECTED_RATIO, dfe.EXPECTED_DAMPED)


class ArmSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: list[str]  # the inputs in order (the first nAnts must have the largest number of terms)
    nRules: int = 60
    nAnts: int = 4
    sampling_power: float | None = None  # None: the AT-041d value (0.5)
    rule_weighting: str | None = None  # None: the AT-041d value (dominance_score); "none" = association is the firing
    description: str = ""


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_gain: float = 0.011  # stage 1 -> stage 2: one seed sd of AT-041d
    win_gain: float = 0.02  # final: about two standard errors of a difference of two 3-seed means
    tie: float = 0.005
    max_mean_rules: float = 22.0
    max_combo_others: int = 2


class Ica4Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = "ica4"
    base_config: str
    base_experiment: str = "ica2-justified"
    base_seeds: list[int] = [0, 1, 2]
    seeds: list[int] = [0, 1, 2]
    robust_seeds: list[int] = [3, 4]
    diurnal_partitions: str | None = "configs/ml/madrid_partitions_diurnal.json"  # None: the terms of no2_last
    candidate_inputs: list[str]  # every diurnal input of the experiment: rows lacking any of them are left out
    stage1: list[str]  # names of the stage-1 arms: "base_refit" or a diurnal input added to the AT-041d inputs
    round2: list[str] = []  # post-hoc extra arms (rounds 2 and 3, report section 4): decided against round 1's choice
    extra_arms: dict[str, ArmSpec] = {}  # other tasks (section 0.7): the Madrid +6 h winner's structure, fixed ahead
    shapes: list[tuple[int, int]] = [(30, 2), (30, 3), (30, 4), (60, 2), (60, 3), (60, 4)]
    decision: DecisionConfig = DecisionConfig()


# ------------------------------------------------------------------------------------------------ context


class Context:
    def __init__(self, config: Ica4Config, artifacts_dir: Path):
        self.cfg = config
        self.base_cfg = ClassExperimentConfig.model_validate_json((REPO_ROOT / config.base_config).read_text())
        root = experiment_dir(self.base_cfg, artifacts_dir).parent
        self.out, self.base_dir = root / config.experiment_id, root / config.base_experiment
        for sub in ("val", "models", "fits"):
            (self.out / sub).mkdir(parents=True, exist_ok=True)
        self.chosen = Candidate.model_validate(json.loads((self.base_dir / "selection.json").read_text())["chosen"])
        self.diurnal_fixed = (load_partition_file(REPO_ROOT / config.diurnal_partitions)
                              if config.diurnal_partitions else {})
        self._cd: ClassData | None = None
        self.audit: dict = {}

    @property
    def base_features(self) -> list[str]:
        return list(self.base_cfg.base.features)

    @property
    def cd(self) -> ClassData:
        """ClassData with every AT-041d and candidate input; complete = AT-041d complete and all candidates finite."""
        if self._cd is None:
            b = self.base_cfg.base
            columns = ["entity_id", "issued_at_utc", b.target_column, *b.features, self.base_cfg.complete_column]
            frame = pd.read_parquet(_resolve(self.base_cfg.table), columns=columns)
            train = split_masks(pd.DatetimeIndex(frame["issued_at_utc"]), b.split)["train"]
            frame, self.audit = dfe.add_diurnal_features(
                frame, train, timezone=b.timezone, horizon_hours=b.horizon_hours, target_column=b.target_column,
                complete_column=self.base_cfg.complete_column, features=tuple(self.cfg.candidate_inputs))
            base_complete = frame[self.base_cfg.complete_column].to_numpy(dtype=bool)
            finite = np.isfinite(frame[self.cfg.candidate_inputs].to_numpy(dtype=float)).all(axis=1)
            frame[self.base_cfg.complete_column] = base_complete & finite
            self.audit["rows_base_complete"] = {p: int((base_complete & m).sum()) for p, m in split_masks(
                pd.DatetimeIndex(frame["issued_at_utc"]), b.split).items()}
            config = self.base_cfg.model_copy(deep=True)
            config.base.features = [*b.features, *self.cfg.candidate_inputs]
            config.base.feature_units = {**b.feature_units, **{f: dfe.UNITS[f] for f in self.cfg.candidate_inputs}}
            cd = ClassData(config, frame=frame)
            for f in self.cfg.candidate_inputs:
                fixed = self.diurnal_fixed.get(f) or cd.fixed["no2_last"].model_copy(update={"feature": f})
                if [(x.name, x.lower, x.upper) for x in fixed.bands] != [
                        (x.name, x.lower, x.upper) for x in cd.fixed["no2_last"].bands]:
                    raise ValueError(f"{f}: its terms are not those of no2_last")
                cd.fixed[f] = fixed
            self.audit["rows_common"] = {p: int(len(cd.data.positions(p))) for p in ("validation", "test")}
            self.audit["rows_common"]["train"] = int(len(cd.data.train_pos))
            self._cd = cd
        return self._cd

    def arm_specs(self) -> dict[str, ArmSpec]:
        """Every arm defined so far: stage 1 from the config, stage 2 and shapes from their written files."""
        specs = {}
        for name in self.cfg.stage1:
            extra = [] if name == "base_refit" else [name]
            specs[name] = ArmSpec(features=[*self.base_features, *extra],
                                  description="AT-041d inputs" + (f" + {name}" if extra else ", refitted"))
        specs.update(self.cfg.extra_arms)
        for file in ("stage2_arms.json", "shape_arms.json"):
            path = self.out / file
            if path.exists():
                specs.update({k: ArmSpec.model_validate(v) for k, v in json.loads(path.read_text())["arms"].items()})
        return specs

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


def n_terms(cd: ClassData, feature: str) -> int:
    fixed = cd.fixed.get(feature)
    return len(fixed.bands) if fixed else cd.config.selection.candidates[0].n_linguistic_variables


def check_slot_bounds(cd: ClassData, spec: ArmSpec) -> None:
    """ex_fuzzy 3.3.1 bounds the term gene of antecedent slot j by the terms of feature j (v2 observation 10)."""
    most = max(n_terms(cd, f) for f in spec.features)
    first = [n_terms(cd, f) for f in spec.features[:spec.nAnts]]
    if min(first) < most:
        raise ValueError(f"the first {spec.nAnts} inputs {spec.features[:spec.nAnts]} have {first} terms; "
                         f"an input has {most}: its last term could never be used")


# ------------------------------------------------------------------------------------------------ fitting

_CTX: Context | None = None  # set in the parent before forking; the workers read the shared table


def _fit_one(job: tuple[str, dict, int]) -> dict:
    name, spec_dict, seed = job
    ctx, spec = _CTX, ArmSpec.model_validate(spec_dict)
    cd, d = ctx.cd, ctx.cd.data
    power = ctx.chosen.sampling_power if spec.sampling_power is None else spec.sampling_power
    sub = cd.train_sample(ctx.base_cfg.subsample.n_rows, ctx.base_cfg.subsample.seed, power)
    shape = ctx.chosen.model_copy(update={"nRules": spec.nRules, "nAnts": spec.nAnts, "sampling_power": power,
                                          "rule_weighting": spec.rule_weighting or ctx.chosen.rule_weighting})
    params = _params(shape, ctx.base_cfg.final.n_gen, ctx.base_cfg.final.pop_size, ctx.base_cfg.final.patience)
    units = {f: cd.config.base.feature_units[f] for f in spec.features}
    fixed = {f: p for f, p in cd.fixed.items() if f in spec.features}
    reference = cd.partition_reference()[spec.features]  # the task's own rule (all training rows, or a sample)
    model, secs, rss = _fit(params, units, d.frame.loc[sub, spec.features], cd.y_class[sub], cd.labels, seed,
                            reference, fixed)
    record = score(model, cd, spec.features, "validation", seed)
    record.update(fit_seconds=secs, peak_rss_mb=rss, n_fit_rows=int(len(sub)))
    with open(ctx.out / "models" / f"{name}-seed{seed}.pkl", "wb") as fh:
        pickle.dump(model, fh)
    (ctx.out / "fits" / f"{name}-seed{seed}.json").write_text(json.dumps(record, default=_json) + "\n")
    return {"arm": name, "seed": seed, "macro_f1": record["validation"]["macro_f1"], "rules": record["n_rules"],
            "secs": secs}


def score(model, cd: ClassData, features: list[str], period: str, seed) -> dict:
    pos = cd.data.positions(period)
    pred = model.predict(cd.data.frame.loc[pos, features])
    rules = classifier_rule_sets(model, cd.labels)
    return {"seed": seed, period: _summary(classification_metrics(cd.y_class[pos], pred, len(cd.labels)), cd.labels),
            "n_rules": len(rules), "mean_rule_length": float(np.mean([len(a) for a, _ in rules])) if rules else 0.0,
            "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rules]}


def run_fits(ctx: Context, arms: list[str], seeds: list[int], workers: int) -> None:
    """Fit every (arm, seed) not on disk yet, in parallel; then aggregate each arm into ``val/<arm>.json``."""
    global _CTX
    specs = ctx.arm_specs()
    cd = ctx.cd  # loaded once in the parent, inherited by the forked workers
    for name in arms:
        check_slot_bounds(cd, specs[name])
    jobs = [(a, specs[a].model_dump(), s) for a in arms for s in seeds
            if not (ctx.out / "fits" / f"{a}-seed{s}.json").exists()]
    _CTX = ctx
    _log(f"{len(jobs)} fits to run ({len(arms)} arms x {len(seeds)} seeds, the rest on disk), {workers} workers; "
         f"rows {ctx.audit.get('rows_common')}")
    if jobs:
        with mp.get_context("fork").Pool(min(workers, len(jobs)), maxtasksperchild=1) as pool:
            for k, r in enumerate(pool.imap_unordered(_fit_one, jobs), start=1):
                print(f"[{k}/{len(jobs)}] arm={r['arm']} seed={r['seed']} val_macroF1={r['macro_f1']:.3f} "
                      f"rules={r['rules']} fit={r['secs']:.0f}s", flush=True)
    for name in arms:
        aggregate(ctx, name, specs[name])


def aggregate(ctx: Context, name: str, spec: ArmSpec, seeds: list[int] | None = None) -> dict | None:
    seeds = seeds or ctx.cfg.seeds
    paths = [ctx.out / "fits" / f"{name}-seed{s}.json" for s in seeds]
    if not all(p.exists() for p in paths):
        return None
    records = [json.loads(p.read_text()) for p in paths]
    sets = [[(tuple(tuple(x) for x in r["antecedents"]), r["class"]) for r in rec["rules"]] for rec in records]
    doc = {"arm": name, "spec": spec.model_dump(), "seeds": records, "stability": rule_set_stability(sets),
           "mean": float(np.mean([r["validation"]["macro_f1"] for r in records])),
           "sd": float(np.std([r["validation"]["macro_f1"] for r in records], ddof=1)),
           "min": float(np.min([r["validation"]["macro_f1"] for r in records])),
           "mean_rules": float(np.mean([r["n_rules"] for r in records])), "audit": ctx.audit}
    ctx.save_json(name, doc)
    return doc


# ------------------------------------------------------------------------------------------------- stages


def stage_base(ctx: Context) -> None:
    """AT-041d pickles re-scored on the common validation rows (and on their own rows, as a reproduction check)."""
    cd = ctx.cd
    summary = ctx.base_dir / "summary_validation.json"
    reference = json.loads((summary if summary.exists() else ctx.base_dir / "summary.json").read_text())["runs"]
    records = []
    for seed in ctx.cfg.base_seeds:
        with open(ctx.base_dir / "models" / f"seed{seed}.pkl", "rb") as fh:
            model = pickle.load(fh)  # noqa: S301 - AT-041d artifact of this repository
        rec = score(model, cd, ctx.base_features, "validation", seed)
        rec["published_macro_f1_own_rows"] = next(r for r in reference if r["seed"] == seed)["validation"]["macro_f1"]
        records.append(rec)
        _log(f"base seed {seed}: common rows {rec['validation']['macro_f1']:.4f} "
             f"(published, own rows {rec['published_macro_f1_own_rows']:.4f})")
    sets = [[(tuple(tuple(x) for x in r["antecedents"]), r["class"]) for r in rec["rules"]] for rec in records]
    f1 = [r["validation"]["macro_f1"] for r in records]
    ctx.save_json("base_published", {
        "arm": "base_published", "spec": ArmSpec(features=ctx.base_features).model_dump(), "seeds": records,
        "stability": rule_set_stability(sets), "mean": float(np.mean(f1)), "sd": float(np.std(f1, ddof=1)),
        "min": float(np.min(f1)), "mean_rules": float(np.mean([r["n_rules"] for r in records])),
        "audit": ctx.audit})


def reference_mean(ctx: Context) -> float:
    return max(ctx.load_json("base_published")["mean"], ctx.load_json("base_refit")["mean"])


def stage2_arms(ctx: Context) -> dict[str, dict]:
    """The combination and compact arms defined by the stage-1 results (pre-registered rule, section 0)."""
    ref, dec = reference_mean(ctx), ctx.cfg.decision
    singles = {a: ctx.load_json(a)["mean"] for a in ctx.cfg.stage1 if a != "base_refit"}
    entered = {a: m for a, m in singles.items() if m - ref >= dec.entry_gain}
    family = sorted((a for a in entered if a in EXPECTATION_FAMILY), key=lambda a: -entered[a])[:1]
    others = sorted((a for a in entered if a not in EXPECTATION_FAMILY), key=lambda a: -entered[a])
    chosen = sorted([*family, *others[:dec.max_combo_others]], key=lambda a: -entered[a])
    arms = {}
    if len(chosen) >= 2:
        arms["combo"] = ArmSpec(features=[*ctx.base_features, *chosen],
                                description=f"AT-041d inputs + {chosen}").model_dump()
    if chosen:
        rest = [f for f in ctx.base_features if f not in ("no2_last", *LAGS)]
        four = [f for f in rest if n_terms(ctx.cd, f) == 4]
        three = [f for f in rest if n_terms(ctx.cd, f) != 4]
        arms["compact"] = ArmSpec(features=["no2_last", *chosen, *four, *three],
                                  description=f"no2_lag1h/3h/24h replaced by {chosen}").model_dump()
    return {"reference_mean": ref, "single_means": singles, "entered": entered, "combo_inputs": chosen, "arms": arms}


def stage2(ctx: Context, workers: int) -> None:
    path = ctx.out / "stage2_arms.json"
    if not path.exists():
        doc = stage2_arms(ctx)
        path.write_text(json.dumps(doc, indent=2) + "\n")
        _log(f"stage 2: entered {doc['entered']}; arms {list(doc['arms'])}")
    arms = list(json.loads(path.read_text())["arms"])
    if arms:
        run_fits(ctx, arms, ctx.cfg.seeds, workers)


def best_arm(ctx: Context, names: list[str]) -> str:
    docs = {n: ctx.load_json(n) for n in names}
    return max(docs, key=lambda n: docs[n]["mean"])


def stage_shape(ctx: Context, workers: int) -> None:
    path = ctx.out / "shape_arms.json"
    if not path.exists():
        stage2_doc = json.loads((ctx.out / "stage2_arms.json").read_text())
        pool = [*stage2_doc["entered"], *stage2_doc["arms"]]
        if not pool:
            path.write_text(json.dumps({"source": None, "arms": {}}, indent=2) + "\n")
            _log("shape: nothing entered stage 2; no shape re-selection")
            return
        source = best_arm(ctx, pool)
        spec = ctx.arm_specs()[source]
        arms = {f"{source}_r{r}a{a}": ArmSpec(features=spec.features, nRules=r, nAnts=a,
                                              description=f"{source}, {r} rules x {a} antecedents").model_dump()
                for r, a in ctx.cfg.shapes if (r, a) != (spec.nRules, spec.nAnts)}
        path.write_text(json.dumps({"source": source, "arms": arms}, indent=2) + "\n")
    arms = list(json.loads(path.read_text())["arms"])
    if arms:
        run_fits(ctx, arms, ctx.cfg.seeds, workers)


def candidates(ctx: Context) -> list[str]:
    names = [a for a in ctx.arm_specs() if a != "base_refit" and a not in ctx.cfg.round2
             and (ctx.out / "val" / f"{a}.json").exists()]
    return names


def decide(ctx: Context) -> dict:
    """Section 0 of the report: highest mean among eligible arms, must beat the reference by win_gain."""
    dec, ref = ctx.cfg.decision, reference_mean(ctx)
    docs = {n: ctx.load_json(n) for n in candidates(ctx)}
    eligible = {n: d for n, d in docs.items() if d["mean_rules"] <= dec.max_mean_rules}
    winners = {n: d for n, d in eligible.items() if d["mean"] - ref >= dec.win_gain and d["min"] > ref}
    chosen = None
    if winners:
        top = max(d["mean"] for d in winners.values())
        near = [n for n, d in winners.items() if top - d["mean"] <= dec.tie]
        chosen = min(near, key=lambda n: (len(docs[n]["spec"]["features"]), docs[n]["mean_rules"]))
    seed = None
    if chosen:
        seed = max(docs[chosen]["seeds"], key=lambda r: r["validation"]["macro_f1"])["seed"]
    out = {"reference_mean": ref, "base_published": ctx.load_json("base_published")["mean"],
           "base_refit": ctx.load_json("base_refit")["mean"],
           "arms": {n: {"mean": d["mean"], "sd": d["sd"], "min": d["min"], "gain": d["mean"] - ref,
                        "mean_rules": d["mean_rules"], "eligible": n in eligible, "wins": n in winners}
                    for n, d in docs.items()},
           "chosen": chosen, "published_seed": seed}
    if ctx.cfg.round2 and chosen:
        out["round2"] = decide_round2(ctx, docs[chosen])
    (ctx.out / "decision.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def decide_round2(ctx: Context, first: dict) -> dict:
    """Round 2 (post-hoc, report section 4): an arm replaces round 1's choice only by the same margins over it."""
    dec = ctx.cfg.decision
    docs = {n: ctx.load_json(n) for n in ctx.cfg.round2 if (ctx.out / "val" / f"{n}.json").exists()}
    wins = {n: d for n, d in docs.items() if d["mean_rules"] <= dec.max_mean_rules
            and d["mean"] - first["mean"] >= dec.win_gain and d["min"] > first["mean"]}
    chosen = max(wins, key=lambda n: wins[n]["mean"]) if wins else None
    return {"reference": first["arm"], "reference_mean": first["mean"],
            "arms": {n: {"mean": d["mean"], "sd": d["sd"], "min": d["min"], "gain": d["mean"] - first["mean"],
                         "mean_rules": d["mean_rules"], "wins": n in wins} for n, d in docs.items()},
            "chosen": chosen, "published_seed": None if chosen is None else max(
                docs[chosen]["seeds"], key=lambda r: r["validation"]["macro_f1"])["seed"]}


def stage_robust(ctx: Context, workers: int) -> None:
    decision = json.loads((ctx.out / "decision.json").read_text())
    later = (decision.get("round2") or {}).get("chosen")
    arms = ["base_refit", *[a for a in (decision["chosen"], later) if a]]
    specs = ctx.arm_specs()
    run_fits(ctx, arms, ctx.cfg.robust_seeds, workers)
    for a in arms:
        doc = aggregate(ctx, a, specs[a], [*ctx.cfg.seeds, *ctx.cfg.robust_seeds])
        (ctx.out / "val" / f"{a}.json").rename(ctx.out / "val" / f"robust_{a}.json")
        aggregate(ctx, a, specs[a])  # val/<arm>.json stays the 3-seed record that the decision read
        _log(f"robust {a}: {len(doc['seeds'])} seeds mean {doc['mean']:.4f} sd {doc['sd']:.4f}")


# ---------------------------------------------------------------------------------------------- final (test)


def _metrics(cd: ClassData, pos: np.ndarray, pred: np.ndarray) -> dict:
    return _summary(classification_metrics(cd.y_class[pos], pred, len(cd.labels)), cd.labels)


def final(ctx: Context) -> None:
    """Test rows, read once: chosen arm (or none), base (published pickles), persistence, control baselines."""
    marker = ctx.out / "TEST_READ"
    if marker.exists():
        raise SystemExit(f"the test rows were already read ({marker.read_text().strip()}); refusing a second read")
    decision = json.loads((ctx.out / "decision.json").read_text())
    marker.write_text(f"{datetime.now().isoformat()} chosen={decision['chosen']}\n")
    cd, d = ctx.cd, ctx.cd.data
    out: dict = {"decision": decision, "rows": ctx.audit, "fuzzy": {}, "baselines": {}}
    periods = {p: d.positions(p) for p in ("validation", "test")}
    # base published pickles, and the chosen arm's seeds, on the common rows
    published = [ctx.base_dir / "models" / f"seed{s}.pkl" for s in ctx.cfg.base_seeds]
    refit = [ctx.out / "models" / f"base_refit-seed{s}.pkl" for s in ctx.cfg.seeds]
    arms = {"base_published": (ctx.base_features, published), "base_refit": (ctx.base_features, refit)}
    chosen = decision["chosen"]
    for name in [chosen, (decision.get("round2") or {}).get("chosen")]:
        if name:
            spec = ctx.arm_specs()[name]
            arms[name] = (spec.features, [ctx.out / "models" / f"{name}-seed{s}.pkl" for s in ctx.cfg.seeds])
    for name, (features, paths) in arms.items():
        rows = []
        for path in paths:
            with open(path, "rb") as fh:
                model = pickle.load(fh)  # noqa: S301
            rows.append({p: _metrics(cd, pos, model.predict(d.frame.loc[pos, features])) for p, pos in periods.items()})
        out["fuzzy"][name] = rows
        _log(f"final {name}: test macro-F1 {[round(r['test']['macro_f1'], 4) for r in rows]}")
    # seasonal persistence (added after round 1, report section 4): the ICA class of the inputs used as the forecast
    for f in ("no2_last", dfe.YDAY_VALID):
        if f in d.frame:
            out["baselines"].setdefault("class_of_input", {})[f] = {
                p: _metrics(cd, pos, cd.scheme.classify(d.frame[f].to_numpy(dtype=float)[pos]))
                for p, pos in periods.items()}
    # control baselines on the full training period (and the fuzzy subsample), with and without the new inputs
    variants = {"base_inputs": ctx.base_features}
    if chosen:
        variants["chosen_inputs"] = ctx.arm_specs()[chosen].features
    keep = {"persistence", "climatology_majority_class", "hist_gradient_boosting",
            "hist_gradient_boosting_regression_binned", "random_forest", "hist_gradient_boosting_subsample",
            "random_forest_subsample", "logistic_regression_subsample"}
    sub = cd.train_sample(ctx.base_cfg.subsample.n_rows, ctx.base_cfg.subsample.seed, ctx.chosen.sampling_power)
    for variant, features in variants.items():
        config = ctx.base_cfg.model_copy(deep=True)
        config.base.features = list(features)
        full, subsample = _baselines(config, cd)
        out["baselines"][variant] = {}
        train_rows = d.train_pos
        if config.baseline_train_rows and config.baseline_train_rows < len(train_rows):  # the task's own bound
            train_rows = train_rows[stratified_subsample(d.frame["entity_id"].array[train_rows], d.issued[train_rows],
                                                         config.baseline_train_rows, config.subsample.seed)]
        for baseline, rows in [*[(b, train_rows) for b in full], *[(b, sub) for b in subsample]]:
            if baseline.name not in keep:
                continue
            if hasattr(baseline, "values"):
                baseline.values = d.y[rows]
            baseline.fit(d.frame.loc[rows], cd.y_class[rows])
            res = {}
            for p, pos in periods.items():
                frame = d.frame.loc[pos]
                pred = np.concatenate([baseline.predict(frame.iloc[i:i + 250_000]) for i in range(0, len(frame),
                                                                                                  250_000)])
                res[p] = _metrics(cd, pos, pred)
            out["baselines"][variant][baseline.name] = res
            _log(f"final {variant} {baseline.name}: val {res['validation']['macro_f1']:.3f} "
                 f"test {res['test']['macro_f1']:.3f}")
            del baseline
    (ctx.out / "final_test.json").write_text(json.dumps(out, indent=2, default=_json) + "\n")


# ------------------------------------------------------------------------------------ publication run dirs

PUBLISH_ID = "ica4-yday"  # run ids ica4-yday-seed<k>, model ids exfuzzy-<task>-ica4-yday-seed<k>
TIE_RULE = ("unweighted inference (ex_fuzzy ds_mode 1): a row goes to the rule with the largest firing; on equal "
            "firing the first rule in the library's class-major order wins (numpy argmax), i.e. the rule of the "
            "better class, and among rules of one class the earlier one")


def prune_never_deciding(model, X: np.ndarray) -> tuple[object, list[dict]]:
    """A copy of ``model`` without the rules that win no row of ``X``, and what was removed.

    Removing a rule that never wins cannot change the winner of any row of ``X`` (the winner is the first rule with
    the largest association, and the removed rules are never it); this is checked. Rows outside ``X`` can change.
    """
    import copy

    from atlas.explain import classifier as ce

    X = np.asarray(X, dtype=float)
    X = X[np.isfinite(X).all(axis=1)]
    rb = ce.get_master_rulebase(model)
    act = ce.compute_classifier_activations(model, X)
    wins = np.bincount(act.winner[act.winner >= 0], minlength=len(rb.get_rules()))
    rules = classifier_rule_sets(model, model.class_labels)
    removed, flat = [], 0
    out = copy.deepcopy(model)
    for rule_base in ce.get_master_rulebase(out).rule_bases:
        local = []
        for i in range(len(rule_base.get_rules())):
            if wins[flat] == 0:
                local.append(i)
                ante, label = rules[flat]
                removed.append({"rule_id": ce.rule_ids(rb)[flat], "class": label,
                                "antecedents": [list(a) for a in ante], "rows_decided": 0})
            flat += 1
        if local:
            rule_base.remove_rules(local)
    if not ce.get_master_rulebase(out).get_rules():
        raise ValueError("pruning would leave no rule")
    after = ce.compute_classifier_activations(out, X)
    if not np.array_equal(after.prediction, act.prediction):
        raise AssertionError("pruning changed a prediction on the rows it was computed on")
    return out, removed


def _pub_config(ctx: Context, spec: ArmSpec, card_sha: str) -> ClassExperimentConfig:
    """The ClassExperimentConfig of the published model: the task's protocol with the chosen arm's inputs."""
    from atlas.ml.partitions import PartitionConfig

    pub = ctx.base_cfg.model_copy(deep=True)
    pub.experiment_id = PUBLISH_ID
    pub.base.features = list(spec.features)
    pub.base.feature_units = {f: {**ctx.base_cfg.base.feature_units, **dfe.UNITS}[f] for f in spec.features}
    pub.base.data_checksums = {**pub.base.data_checksums, "feature_card.json": card_sha}
    file_fixed = load_partition_file(REPO_ROOT / ctx.base_cfg.partitions.file)
    extra = [ctx.cd.fixed[f] for f in spec.features if f not in file_fixed]
    pub.partitions = PartitionConfig(file=ctx.base_cfg.partitions.file,
                                     use_features=[f for f in spec.features if f in file_fixed], fixed=extra)
    pub.selection.candidates = [ctx.chosen.model_copy(update={
        "nRules": spec.nRules, "nAnts": spec.nAnts,
        "rule_weighting": spec.rule_weighting or ctx.chosen.rule_weighting,
        "sampling_power": ctx.chosen.sampling_power if spec.sampling_power is None else spec.sampling_power})]
    pub.final.seeds = list(ctx.cfg.seeds)
    pub.persistence_baselines = {"persistence_24h": dfe.YDAY_VALID}
    return pub


def stage_publish_runs(ctx: Context, config_out: Path, config_only: bool = False) -> Path:
    """Run directory of the chosen arm and seed: the selected ica4 fits, pruned, scored on the task's own rows.

    The publication config is written to ``config_out`` (``config_only``: only that); if the file exists it must be
    the one this stage would write, so that a committed config is what the run directory records."""
    import hashlib

    from atlas.ml.experiment_class import run_final, write_class_runs

    decision = json.loads((ctx.out / "decision.json").read_text())
    later = decision.get("round2") or {}
    chosen = later.get("chosen") or decision["chosen"]
    seed = later.get("published_seed") if later.get("chosen") else decision["published_seed"]
    if not chosen:
        raise SystemExit("nothing was chosen for this task: the served model stays")
    spec = ctx.arm_specs()[chosen]
    card = _resolve(ctx.base_cfg.table).parent / "feature_card.json"
    pub = _pub_config(ctx, spec, hashlib.sha256(card.read_bytes()).hexdigest())
    text = pub.model_dump_json(indent=2) + "\n"
    if config_out.exists() and config_out.read_text() != text:
        raise SystemExit(f"{config_out} differs from the publication config of this decision and feature table")
    config_out.write_text(text)
    if config_only:
        return config_out
    pub = ClassExperimentConfig.model_validate_json(config_out.read_text())
    _log(f"publication config {config_out}: arm {chosen}, seed {seed}, inputs {spec.features}")

    cd_ica4, cd = ctx.cd, ClassData(pub)
    keys = ["entity_id", "issued_at_utc"]
    # the table's column must be the quantity ica4 computed (diurnal_features), row for row
    a = cd_ica4.data.frame[[*keys, dfe.YDAY_VALID]].merge(cd.data.frame[[*keys, dfe.YDAY_VALID]], on=keys)
    precision = cd.data.frame[dfe.YDAY_VALID].dtype  # float32 when the task loads compactly (Germany)
    both = np.stack([a[f"{dfe.YDAY_VALID}_x"].to_numpy().astype(precision),
                     a[f"{dfe.YDAY_VALID}_y"].to_numpy().astype(precision)], axis=1)
    same = (both[:, 0] == both[:, 1]) | (np.isnan(both[:, 0]) & np.isnan(both[:, 1]))
    if not same.all():
        raise AssertionError(f"{int((~same).sum())} rows where the table's {dfe.YDAY_VALID} differs from ica4's")
    # the fitting sample of the ica4 fits, as positions of the publication frame
    sample = cd_ica4.train_sample(ctx.base_cfg.subsample.n_rows, ctx.base_cfg.subsample.seed,
                                  pub.selection.candidates[0].sampling_power)
    want = cd_ica4.data.frame.loc[sample, keys].reset_index(drop=True)
    index = cd.data.frame[keys].reset_index().rename(columns={"index": "pos"})
    found = want.merge(index, on=keys, how="left")
    if found["pos"].isna().any() or not np.isin(found["pos"].to_numpy(), cd.data.train_pos).all():
        raise AssertionError("the ica4 fitting sample is not inside the publication training rows")
    sub_rows = np.sort(found["pos"].to_numpy(dtype=int))

    val = cd.data.positions("validation")
    X_val = cd.data.frame.loc[val, spec.features].to_numpy(dtype=float)
    models, fit_records, pruning = {}, {}, {}
    for s in ctx.cfg.seeds:
        with open(ctx.out / "models" / f"{chosen}-seed{s}.pkl", "rb") as fh:
            model = pickle.load(fh)  # noqa: S301 - written by this module
        models[s], removed = prune_never_deciding(model, X_val)
        before, after = model.predict(cd.data.frame.loc[cd.data.positions("test"), spec.features]), \
            models[s].predict(cd.data.frame.loc[cd.data.positions("test"), spec.features])
        pruning[s] = {"removed": removed, "n_rules_before": len(model.rule_base.get_rules()),
                      "n_rules_after": len(models[s].rule_base.get_rules()),
                      "test_rows_whose_prediction_changes": int((before != after).sum()),
                      "test_rows": int(len(before))}
        fit_records[s] = json.loads((ctx.out / "fits" / f"{chosen}-seed{s}.json").read_text())
        changed = pruning[s]["test_rows_whose_prediction_changes"]
        _log(f"seed {s}: pruned {len(removed)} rules ({pruning[s]['n_rules_before']} -> "
             f"{pruning[s]['n_rules_after']}); test predictions changed {changed}")
    out_dir = ctx.out.parent / PUBLISH_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pruning.json").write_text(json.dumps({"arm": chosen, "published_seed": seed, "rows": "validation rows "
                                          "of the publication (the task's complete rows with every input finite)",
                                          "seeds": pruning}, indent=2) + "\n")
    run_final(pub, cd, out_dir, selection={"chosen": pub.selection.candidates[0].model_dump()}, models=models,
              sub_rows=sub_rows, fit_records=fit_records)
    warnings = [
        f"selected in experiment ica4 ({chosen}, docs/ml/madrid_no2_h6_ica_v4.md): fitted there on a class-aware "
        f"sample of the training rows where all of {ctx.cfg.candidate_inputs} were finite; the published seed is the "
        "one chosen by its pre-registered rule (highest validation macro-F1 on those rows)",
        f"{len(pruning[seed]['removed'])} rules that decided no validation row were removed after fitting "
        f"({[r['rule_id'] for r in pruning[seed]['removed']]} of the fitted rule base); validation predictions are "
        f"unchanged, {pruning[seed]['test_rows_whose_prediction_changes']} of {pruning[seed]['test_rows']} test "
        f"predictions change ({ctx.out.parent.name}/{PUBLISH_ID}/pruning.json)",
        TIE_RULE,
    ]
    dirs = write_class_runs(pub, cd, out_dir, ctx.out.parents[2], sub_rows=sub_rows, seeds=[seed],
                            extra_warnings=warnings,
                            extra_hyperparameters={"tie_rule": TIE_RULE, "pruned_rules": pruning[seed]["removed"],
                                                   "selected_arm": chosen, "selection_experiment": "ica4"})
    return dirs[0]


# ---------------------------------------------------------------------------------------------- report


def _row(name: str, doc: dict) -> str:
    v = [r["validation"] for r in doc["seeds"]]

    def ms(key, sub=None):
        x = [r[key][sub] if sub else r[key] for r in v]
        x = [np.nan if a is None else a for a in x]
        return f"{np.mean(x):.3f} ± {np.std(x, ddof=1):.3f}"

    labels = list(v[0]["recall"])
    st = doc["stability"]["pairwise_jaccard_rule"] if doc.get("stability") else None
    jac = f"{np.mean(st):.3f}" if st is not None and np.size(st) else "-"
    return (f"| {name} | {ms('macro_f1')} | {ms('balanced_accuracy')} | {ms('accuracy')} | "
            f"{ms('recall', labels[2])} | {ms('precision', labels[2])} | {ms('recall', labels[3])} | "
            f"{ms('precision', labels[3])} | {doc['mean_rules']:.1f} | "
            f"{np.mean([r['mean_rule_length'] for r in doc['seeds']]):.2f} | {jac} |")


def report(ctx: Context) -> str:
    head = ("| arm | macro-F1 | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | rules | "
            "mean length | Jaccard |\n|---|---|---|---|---|---|---|---|---|---|---|")
    names = ["base_published", *[a for a in ctx.arm_specs() if (ctx.out / "val" / f"{a}.json").exists()]]
    lines = [head, *[_row(n, ctx.load_json(n)) for n in names]]
    if (ctx.out / "final_test.json").exists():
        lines += ["", report_test(json.loads((ctx.out / "final_test.json").read_text()))]
    text = "\n".join(lines)
    print(text)
    return text


def report_test(doc: dict) -> str:
    """Validation and test of the fuzzy arms (mean ± sd over seeds) and of every baseline, from ``final_test.json``."""
    def cells(m: dict) -> list[str]:
        labels = list(m["recall"])
        return [f"{m['macro_f1']:.3f}", f"{m['balanced_accuracy']:.3f}", f"{m['accuracy']:.3f}",
                f"{m['recall'][labels[2]]:.3f}", f"{m['precision'][labels[2]]:.3f}",
                f"{m['recall'][labels[3]]:.3f}", f"{m['precision'][labels[3]]:.3f}"]

    lines = ["| model | val macro-F1 | test macro-F1 | test bal-acc | test acc | test recall class 3 | "
             "test prec class 3 | test recall class 4 | test prec class 4 |", "|---|---|---|---|---|---|---|---|---|"]
    for name, rows in doc["fuzzy"].items():
        val = [r["validation"]["macro_f1"] for r in rows]
        test = np.array([[float(c) for c in cells(r["test"])] for r in rows])
        sd = test.std(axis=0, ddof=1) if len(rows) > 1 else np.zeros(test.shape[1])
        lines.append(f"| ExFuzzy {name} ({len(rows)} seeds) | {np.mean(val):.3f} ± {np.std(val, ddof=1):.3f} | "
                     + " | ".join(f"{m:.3f} ± {s:.3f}" for m, s in zip(test.mean(axis=0), sd, strict=True)) + " |")
        lines.append(f"| ExFuzzy {name}, per seed | {' / '.join(f'{v:.3f}' for v in val)} | "
                     + " / ".join(f"{r['test']['macro_f1']:.3f}" for r in rows) + " | | | | | | |")
    for variant, models in doc["baselines"].items():
        for name, res in models.items():
            c = cells(res["test"])
            lines.append(f"| {name} [{variant}] | {res['validation']['macro_f1']:.3f} | {' | '.join(c)} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_ica4", description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=["base", "arms", "stage2", "shape", "decide", "robust", "report", "final",
                                          "publish-runs"])
    parser.add_argument("--config-only", action="store_true", help="publish-runs: write the config and stop")
    parser.add_argument("--publish-config", type=Path, default=None,
                        help="publish-runs: where to write the publication ClassExperimentConfig")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", default=None, help="arms: comma separated subset of the stage-1 / extra arms")
    parser.add_argument("--test", action="store_true", help="final: read the test rows (once)")
    args = parser.parse_args(argv)
    ctx = Context(Ica4Config.model_validate_json(args.config.read_text()), args.artifacts_dir)
    start = time.perf_counter()
    if args.stage == "base":
        stage_base(ctx)
    elif args.stage == "arms":
        arms = args.only.split(",") if args.only else [*ctx.cfg.stage1, *ctx.cfg.extra_arms]
        run_fits(ctx, arms, ctx.cfg.seeds, args.workers)
    elif args.stage == "stage2":
        stage2(ctx, args.workers)
    elif args.stage == "shape":
        stage_shape(ctx, args.workers)
    elif args.stage == "decide":
        print(json.dumps(decide(ctx), indent=2))
    elif args.stage == "robust":
        stage_robust(ctx, args.workers)
    elif args.stage == "report":
        report(ctx)
    elif args.stage == "publish-runs":
        if args.publish_config is None:
            raise SystemExit("publish-runs needs --publish-config configs/ml/<task>_ica4_publish_experiment.json")
        _log(f"wrote {stage_publish_runs(ctx, args.publish_config, args.config_only)}")
    elif args.stage == "final":
        if not args.test:
            raise SystemExit("final reads the test rows: pass --test (once)")
        final(ctx)
    _log(f"{args.stage} finished in {time.perf_counter() - start:.0f}s at {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
