"""AT-041e: ways to improve the Madrid ICA winning-rule classifier, each isolated against AT-041d, validation only.

::

    python -m atlas.ml.experiment_ica3 <stage> --config configs/ml/madrid_no2_h6_ica3_experiment.json

Stages (all resumable, all write ``<artifacts>/madrid_no2_h6/experiments/<experiment_id>/val/<arm>.json``):
``base``, ``calib`` (idea 1), ``natw`` (idea 2), ``pool`` + ``consensus`` + ``restarts`` (ideas 3 and 6), ``features``
(idea 5), ``ordinal`` (idea 4), ``report`` (markdown tables from the arm files). The test rows are read by
``final`` only (``--test``), once, for the arm chosen by ``decide`` and for the AT-041d reference.
The protocol and its decision rules are in ``docs/ml/madrid_no2_h6_ica_v3.md`` section 0.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.ml import calibration as cal
from atlas.ml import consensus as cons
from atlas.ml import extra_features as xf
from atlas.ml import ordinal as ordn
from atlas.ml.classification import class_sample, classification_metrics
from atlas.ml.evaluation import classifier_rule_sets, rule_set_stability
from atlas.ml.experiment_class import (
    Candidate,
    ClassData,
    ClassExperimentConfig,
    _fit,
    _log,
    _params,
    _resolve,
    _summary,
    experiment_dir,
)
from atlas.ml.fuzzy_classifier import FuzzyClassifier
from atlas.ml.partitions import FixedPartition, load_partition_file
from atlas.ml.split import split_masks
from atlas.paths import ARTIFACTS_DIR, DATA_DIR, REPO_ROOT

SET_KEYS = ("A", "B", "C")


class CalibrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grid_log10: tuple[float, float, int] = (-2.0, 3.0, 41)
    sweeps: int = 3


class ConsensusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int = 20000
    n_gen: int = 100
    pop_size: int = 60
    sampling_power: float = 0.5
    seed_sets: dict[str, list[int]]
    pi: list[float] = [0.3, 0.5]
    pi_posthoc: list[float] = []  # added after pi 0.3 / 0.5 gave one or two rules per set: reported, never selected
    restart_k: list[int] = [5, 15]


class OrdinalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int = 30000
    n_gen: int = 150
    pop_size: int = 60
    sampling_power: float = 0.5
    seeds: list[int] = [0, 1, 2]


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_gain: float = 0.011  # one seed sd of the AT-041d reference
    tie: float = 0.005
    reference_jaccard: float = 0.151
    jaccard_gain: float = 0.05


class Ica3Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = "ica3"
    base_config: str  # the AT-041d justified experiment (relative to the repository root)
    base_experiment: str = "ica2-justified"  # its experiment directory: models/seed<k>.pkl, summary*.json
    base_seeds: list[int] = [0, 1, 2]
    extra_partitions: str = "configs/ml/madrid_partitions_extra.json"
    stations: str = "processed/air/stations.geojson"  # relative to ATLAS_DATA_DIR
    feature_arms: dict[str, list[str]] = {}
    calibration: CalibrationConfig = CalibrationConfig()
    consensus: ConsensusConfig
    ordinal: OrdinalConfig = OrdinalConfig()
    decision: DecisionConfig = DecisionConfig()


# ------------------------------------------------------------------------------------------------ context


class Context:
    """The AT-041d configuration, the table with the extra inputs and the artifact directories."""

    def __init__(self, config: Ica3Config, artifacts_dir: Path):
        self.cfg = config
        self.base_cfg = ClassExperimentConfig.model_validate_json((REPO_ROOT / config.base_config).read_text())
        self.out = experiment_dir(self.base_cfg, artifacts_dir).parent / config.experiment_id
        self.base_dir = experiment_dir(self.base_cfg, artifacts_dir).parent / config.base_experiment
        for sub in ("val", "models", "pool"):
            (self.out / sub).mkdir(parents=True, exist_ok=True)
        selection = json.loads((self.base_dir / "selection.json").read_text())
        self.chosen = Candidate.model_validate(selection["chosen"])
        self._frame: pd.DataFrame | None = None
        self.audit: dict = {}
        self.extra_fixed: dict[str, FixedPartition] = load_partition_file(REPO_ROOT / config.extra_partitions)

    @property
    def frame(self) -> pd.DataFrame:
        """The main table (needed columns) with the three extra inputs, whose reference uses training rows only."""
        if self._frame is None:
            base = self.base_cfg.base
            columns = ["entity_id", "issued_at_utc", base.target_column, *base.features, self.base_cfg.complete_column]
            frame = pd.read_parquet(_resolve(self.base_cfg.table), columns=columns)
            train = split_masks(pd.DatetimeIndex(frame["issued_at_utc"]), base.split)["train"]
            self._frame, self.audit = xf.add_extra_features(
                frame, train, timezone=base.timezone, stations_geojson=DATA_DIR / self.cfg.stations)
        return self._frame

    def class_data(self, extras: list[str] | None = None) -> ClassData:
        """``ClassData`` whose inputs are the AT-041d features plus ``extras`` (with their fixed terms)."""
        extras = list(extras or [])
        config = self.base_cfg.model_copy(deep=True)
        config.base.features = [*config.base.features, *extras]
        config.base.feature_units = {**config.base.feature_units, **{e: xf.UNITS[e] for e in extras}}
        cd = ClassData(config, frame=self.frame)
        cd.fixed.update({e: self.extra_fixed[e] for e in extras})
        return cd

    def check_same_rows(self, cd: ClassData, reference: ClassData) -> None:
        a, b = cd.data, reference.data
        if not (np.array_equal(a.complete, b.complete) and np.array_equal(a.train_pos, b.train_pos)):
            raise ValueError(f"the extra inputs change the complete rows: {int(a.complete.sum())} against "
                             f"{int(b.complete.sum())}")

    def save_json(self, name: str, document: dict) -> None:
        (self.out / "val" / f"{name}.json").write_text(json.dumps(document, indent=2, default=_json) + "\n")

    def load_json(self, name: str) -> dict:
        return json.loads((self.out / "val" / f"{name}.json").read_text())

    def exists(self, name: str) -> bool:
        return (self.out / "val" / f"{name}.json").exists()

    def save_model(self, name: str, model) -> None:
        with open(self.out / "models" / f"{name}.pkl", "wb") as fh:
            pickle.dump(model, fh)

    def load_model(self, name: str):
        with open(self.out / "models" / f"{name}.pkl", "rb") as fh:
            return pickle.load(fh)  # noqa: S301 - written by this module


def _json(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


# ------------------------------------------------------------------------------------------------ helpers


def _features(cd: ClassData) -> list[str]:
    return cd.config.base.features


def _xy(cd: ClassData, period: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Inputs, class indexes and positions of the complete rows of a period (``train`` = the training positions)."""
    d = cd.data
    pos = d.train_pos if period == "train" else d.positions(period)
    return d.frame.loc[pos, _features(cd)], cd.y_class[pos], pos


def _seed_record(model, cd: ClassData, X: pd.DataFrame, y: np.ndarray, label, **extra) -> dict:
    """Validation summary, rules and size of one fitted model."""
    pred = model.predict(X)
    rules = classifier_rule_sets(model, cd.labels)
    return {"seed": label, "validation": _summary(classification_metrics(y, pred, len(cd.labels)), cd.labels),
            "n_rules": len(rules), "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rules],
            **extra}


def _rule_sets(record: dict) -> list[tuple]:
    return [(tuple(tuple(p) for p in r["antecedents"]), r["class"]) for r in record["rules"]]


def _arm(name: str, description: str, records: list[dict], **extra) -> dict:
    sets = [_rule_sets(r) for r in records]
    return {"arm": name, "description": description, "seeds": records,
            "stability": rule_set_stability(sets) if len(sets) > 1 else None, **extra}


def _calibrated_records(models, cd: ClassData, X: pd.DataFrame, y: np.ndarray, issued, config: Ica3Config, labels
                        ) -> tuple[list[dict], list]:
    """For each model: tune class factors on validation, apply, and record in-sample and cross-fitted results."""
    k = len(cd.labels)
    kwargs = {"grid_log10": config.calibration.grid_log10, "sweeps": config.calibration.sweeps}
    groups = cal.week_parity(issued)
    out, fitted = [], []
    for model, label in zip(models, labels, strict=True):
        assoc = cal.class_max_association(model, X.to_numpy(dtype=float), k)
        factors = cal.tune_class_factors(assoc, y, **kwargs)
        scaled = cal.apply_class_factors(model, factors)
        crossfit = classification_metrics(y, cal.cross_fit_predictions(assoc, y, groups, **kwargs), k)
        record = _seed_record(scaled, cd, X, y, label, class_factors=factors.tolist(),
                              crossfit=_summary(crossfit, cd.labels))
        mismatch = float(np.mean(cal.predict_with_factors(assoc, factors) != scaled.predict(X)))
        record["share_search_vs_library_mismatch"] = mismatch
        out.append(record)
        fitted.append(scaled)
    return out, fitted


# ------------------------------------------------------------------------------------------------- stages


def stage_base(ctx: Context) -> None:
    """AT-041d seeds as published, re-scored on validation (reproduction check against ``summary_validation.json``)."""
    if ctx.exists("base"):
        return
    cd = ctx.class_data()
    X, y, _ = _xy(cd, "validation")
    reference = json.loads((ctx.base_dir / "summary_validation.json").read_text())["runs"]
    records, models = [], []
    for seed in ctx.cfg.base_seeds:
        with open(ctx.base_dir / "models" / f"seed{seed}.pkl", "rb") as fh:
            model = pickle.load(fh)  # noqa: S301 - AT-041d artifact of this repository's runs
        rec = _seed_record(model, cd, X, y, seed)
        published = next(r for r in reference if r["seed"] == seed)["validation"]["macro_f1"]
        rec["reproduces_published"] = bool(abs(rec["validation"]["macro_f1"] - published) < 1e-9)
        records.append(rec)
        models.append(model)
        ctx.save_model(f"base-seed{seed}", model)
        _log(f"base seed {seed}: val macro-F1 {rec['validation']['macro_f1']:.4f} (published {published:.4f})")
    ctx.save_json("base", _arm("base", "AT-041d justified, seeds 0-2 as published", records,
                               n_validation_rows=int(len(y))))


def _base_models(ctx: Context) -> list:
    return [ctx.load_model(f"base-seed{s}") for s in ctx.cfg.base_seeds]


def stage_calib(ctx: Context) -> None:
    if ctx.exists("calib"):
        return
    cd = ctx.class_data()
    X, y, pos = _xy(cd, "validation")
    records, models = _calibrated_records(_base_models(ctx), cd, X, y, cd.data.issued[pos], ctx.cfg,
                                          ctx.cfg.base_seeds)
    for s, model in zip(ctx.cfg.base_seeds, models, strict=True):
        ctx.save_model(f"calib-seed{s}", model)
    ctx.save_json("calib", _arm("calib", "idea 1: per-class factors on the AT-041d models", records))
    _log("calib done")


def stage_natw(ctx: Context) -> None:
    if ctx.exists("natw_calib"):
        return
    cd = ctx.class_data()
    X, y, pos = _xy(cd, "validation")
    Xt, yt, _ = _xy(cd, "train")
    rescored = []
    for s, model in zip(ctx.cfg.base_seeds, _base_models(ctx), strict=True):
        rescored.append(cal.rescore(model, Xt.to_numpy(dtype=float), yt))
        ctx.save_model(f"natw-seed{s}", rescored[-1])
    records = [_seed_record(m, cd, X, y, s,
                            weights_raw=[float(r.score_raw) for r in m.rule_base.get_rules()],
                            weights_fit_sample=[float(r.score) for r in _base_models(ctx)[i].rule_base.get_rules()])
               for i, (m, s) in enumerate(zip(rescored, ctx.cfg.base_seeds, strict=True))]
    ctx.save_json("natw", _arm("natw", "idea 2: dominance scores recomputed on all training rows", records))
    cal_records, models = _calibrated_records(rescored, cd, X, y, cd.data.issued[pos], ctx.cfg, ctx.cfg.base_seeds)
    for s, model in zip(ctx.cfg.base_seeds, models, strict=True):
        ctx.save_model(f"natw_calib-seed{s}", model)
    ctx.save_json("natw_calib", _arm("natw_calib", "idea 2 then 1", cal_records))
    _log("natw done")


# ---- consensus pool


def _pool_path(ctx: Context, key: str, seed: int) -> Path:
    return ctx.out / "pool" / f"{key}-seed{seed}.pkl"


def stage_pool(ctx: Context, only: str | None = None, extras: list[str] | None = None, tag: str = "") -> None:
    """Fit the N classifiers of each seed set on fresh class-aware draws (resumable, one pickle + json per fit)."""
    c = ctx.cfg.consensus
    cd = ctx.class_data(extras)
    X_val, y_val, _ = _xy(cd, "validation")
    reference = cd.partition_reference()
    params = _params(ctx.chosen, c.n_gen, c.pop_size, None)
    for key in SET_KEYS:
        if only and key != only:
            continue
        for seed in c.seed_sets[key]:
            path = _pool_path(ctx, tag + key, seed)
            if path.exists():
                continue
            rows = cd.train_sample(c.n_rows, seed, c.sampling_power)
            model, secs, rss = _fit(params, cd.config.base.feature_units, cd.data.frame.loc[rows, _features(cd)],
                                    cd.y_class[rows], cd.labels, seed, reference, cd.fixed)
            rec = _seed_record(model, cd, X_val, y_val, seed, fit_seconds=secs, peak_rss_mb=rss,
                               train_class_counts=np.bincount(cd.y_class[rows], minlength=len(cd.labels)).tolist())
            path.with_suffix(".json").write_text(json.dumps(rec, default=_json) + "\n")
            with open(path, "wb") as fh:
                pickle.dump(model, fh)
            _log(f"pool {tag}{key} seed {seed}: val macro-F1 {rec['validation']['macro_f1']:.3f} rules "
                 f"{rec['n_rules']} fit {secs:.0f}s rss {rss:.0f} MB")


def _load_pool(ctx: Context, key: str, tag: str = "") -> tuple[list[FuzzyClassifier], list[dict]]:
    models, records = [], []
    for seed in ctx.cfg.consensus.seed_sets[key]:
        with open(_pool_path(ctx, tag + key, seed), "rb") as fh:
            models.append(pickle.load(fh))  # noqa: S301
        records.append(json.loads(_pool_path(ctx, tag + key, seed).with_suffix(".json").read_text()))
    return models, records


def stage_consensus(ctx: Context, extras: list[str] | None = None, tag: str = "") -> None:
    """Stability selection per seed set and pi: build, recompute weights on all training rows, score, calibrate."""
    c = ctx.cfg.consensus
    cd = ctx.class_data(extras)
    X, y, pos = _xy(cd, "validation")
    Xt, yt, _ = _xy(cd, "train")
    for pi in [*c.pi, *c.pi_posthoc]:
        name = f"{tag}{'posthoc_' if pi in c.pi_posthoc else ''}cons_p{int(round(pi * 100)):02d}"
        if ctx.exists(name + "_calib"):
            continue
        built, fits, freq_info = [], [], {}
        for key in SET_KEYS:
            models, records = _load_pool(ctx, key, tag)
            cons.check_same_variables(models)
            sets = cons.pool_rule_sets(models, cd.labels)
            freqs = cons.selection_frequencies(sets)
            keys = cons.consensus_keys(freqs, pi)
            freq_info[key] = {"n_fits": len(models), "n_distinct_rules": len(freqs), "n_consensus": len(keys),
                              "max_frequency": max(freqs.values()),
                              "mean_rules_per_fit": float(np.mean([len(s) for s in sets])),
                              "mean_single_fit_val_macro_f1": float(np.mean(
                                  [r["validation"]["macro_f1"] for r in records]))}
            if not keys:  # ex_fuzzy cannot wrap a rule base without rules
                built.append(None)
                fits.append(key)
                continue
            model = cal.rescore(cons.build_consensus_model(models[0], keys, freqs), Xt.to_numpy(dtype=float), yt)
            built.append(model)
            fits.append(key)
            ctx.save_model(f"{name}-set{key}", model)
        if any(m is None for m in built):
            ctx.save_json(name + "_calib", {"arm": name, "description": "empty consensus", "frequency": freq_info,
                                            "seeds": [], "empty": True})
            _log(f"{name}: empty consensus rule base in some set; skipped")
            continue
        records = [_seed_record(m, cd, X, y, k, selection_frequencies=[
            float(r.selection_frequency) for r in m.rule_base.get_rules()]) for m, k in zip(built, fits, strict=True)]
        ctx.save_json(name, _arm(name, f"idea 3: consensus pi={pi}, weights on all training rows", records,
                                 frequency=freq_info))
        cal_records, cal_models = _calibrated_records(built, cd, X, y, cd.data.issued[pos], ctx.cfg, fits)
        for k, m in zip(fits, cal_models, strict=True):
            ctx.save_model(f"{name}_calib-set{k}", m)
        ctx.save_json(name + "_calib", _arm(name + "_calib", f"consensus pi={pi}, then class factors", cal_records,
                                            frequency=freq_info))
        _log(f"{name} done")


def stage_restarts(ctx: Context, tag: str = "") -> None:
    c = ctx.cfg.consensus
    for k in c.restart_k:
        name = f"{tag}restart_k{k}"
        if ctx.exists(name):
            continue
        records = []
        for key in SET_KEYS:
            _, recs = _load_pool(ctx, key, tag)
            best = cons.best_of([r["validation"]["macro_f1"] for r in recs], k)
            records.append({**recs[best], "seed": key, "picked_fit_seed": recs[best]["seed"]})
        ctx.save_json(name, _arm(name, f"idea 6: best of the first {k} fits by validation macro-F1", records))
        _log(f"{name} done")


# ---- extra inputs


def stage_features(ctx: Context) -> None:
    cd0 = ctx.class_data()
    for name, extras in ctx.cfg.feature_arms.items():
        if ctx.exists(name):
            continue
        cd = ctx.class_data(extras)
        ctx.check_same_rows(cd, cd0)
        X, y, _ = _xy(cd, "validation")
        sub_rows = cd.train_sample(ctx.base_cfg.subsample.n_rows, ctx.base_cfg.subsample.seed,
                                   ctx.chosen.sampling_power)
        params = _params(ctx.chosen, ctx.base_cfg.final.n_gen, ctx.base_cfg.final.pop_size, ctx.base_cfg.final.patience)
        reference, records = cd.partition_reference(), []
        for seed in ctx.base_cfg.final.seeds:
            model, secs, rss = _fit(params, cd.config.base.feature_units, cd.data.frame.loc[sub_rows, _features(cd)],
                                    cd.y_class[sub_rows], cd.labels, seed, reference, cd.fixed)
            ctx.save_model(f"{name}-seed{seed}", model)
            records.append(_seed_record(model, cd, X, y, seed, fit_seconds=secs, peak_rss_mb=rss))
            _log(f"{name} seed {seed}: val macro-F1 {records[-1]['validation']['macro_f1']:.3f} fit {secs:.0f}s")
        ctx.save_json(name, _arm(name, f"idea 5: AT-041d plus {extras}", records, extras=extras,
                                 audit=ctx.audit))
        del cd


# ---- control: do the extra inputs carry information for a flexible learner?


def stage_control(ctx: Context) -> None:
    """HGB (AT-041d settings, full training period) with and without the extra inputs, validation only."""
    if ctx.exists("control_hgb"):
        return
    from sklearn.ensemble import HistGradientBoostingClassifier

    out = {}
    for name, extras in {"base_features": [], "plus_trend_anomaly_type": list(xf.EXTRA_FEATURES)}.items():
        cd = ctx.class_data(extras)
        Xt, yt, _ = _xy(cd, "train")
        X, y, _ = _xy(cd, "validation")
        model = HistGradientBoostingClassifier(max_iter=ctx.base_cfg.base.gbm_max_iter, early_stopping=False,
                                               random_state=ctx.base_cfg.base.seed)
        model.fit(Xt.to_numpy(dtype=float), yt)
        pred = model.predict(X.to_numpy(dtype=float)).astype(int)
        out[name] = _summary(classification_metrics(y, pred, len(cd.labels)), cd.labels)
        _log(f"control {name}: val macro-F1 {out[name]['macro_f1']:.3f}")
        del cd
    ctx.save_json("control_hgb", {"arm": "control_hgb", "description": "HistGradientBoosting, full training period",
                                  "variants": out})


# ---- ordinal decomposition


def stage_ordinal(ctx: Context) -> None:
    if ctx.exists("ordinal"):
        return
    c = ctx.cfg.ordinal
    cd = ctx.class_data()
    d, k = cd.data, len(cd.labels)
    X_val, y_val, pos_val = _xy(cd, "validation")
    reference = cd.partition_reference()
    params = _params(ctx.chosen, c.n_gen, c.pop_size, None)
    bounds = [cd.scheme.classes[i].upper for i in range(k - 1)]
    names = [f"supera {b:g} ug/m3" for b in bounds]
    binary_all = ordn.threshold_targets(cd.y_class, k)  # positions of the whole frame
    labels2 = ["no", "si"]
    X_val_np = X_val.to_numpy(dtype=float)
    per_seed = []
    for seed in c.seeds:
        decisions, assoc, rule_counts, binary_f1, fit_secs = [], [], [], [], 0.0
        for t, name in enumerate(names):
            path = ctx.out / "models" / f"ordinal-t{t}-seed{seed}.pkl"
            if path.exists():
                model = ctx.load_model(f"ordinal-t{t}-seed{seed}")
            else:
                yb = binary_all[d.train_pos, t]
                picked = class_sample(yb, d.frame["entity_id"].to_numpy()[d.train_pos], d.issued[d.train_pos],
                                      c.n_rows, ctx.base_cfg.subsample.seed, c.sampling_power)
                rows = d.train_pos[picked]
                model, secs, _ = _fit(params, cd.config.base.feature_units, d.frame.loc[rows, _features(cd)],
                                      binary_all[rows, t], labels2, seed, reference, cd.fixed)
                fit_secs += secs
                ctx.save_model(f"ordinal-t{t}-seed{seed}", model)
            pred = model.predict(X_val)
            decisions.append(pred)
            assoc.append(cal.class_max_association(model, X_val_np, 2))
            rule_counts.append(len(model.rule_base.get_rules()))
            binary_f1.append(classification_metrics(binary_all[pos_val, t], pred, 2)["macro_f1"])
            _log(f"ordinal seed {seed} {name}: binary val macro-F1 {binary_f1[-1]:.3f} rules {rule_counts[-1]}")
        dec = np.stack(decisions, axis=1)
        per_seed.append({"seed": seed, "decisions": dec, "assoc": assoc, "rules": rule_counts, "binary_f1": binary_f1,
                         "fit_seconds": fit_secs})
    groups = cal.week_parity(d.issued[pos_val])
    records = []
    for row in per_seed:
        rec = {"seed": row["seed"], "n_rules": int(sum(row["rules"])), "rules_per_threshold": row["rules"],
               "binary_macro_f1": row["binary_f1"], "fit_seconds": row["fit_seconds"], "variants": {}}
        for how in ("highest", "count"):
            dec = row["decisions"]
            pred = ordn.combine(dec, how)
            rec["variants"][f"raw_{how}"] = {
                "validation": _summary(classification_metrics(y_val, pred, k), cd.labels),
                "inconsistency_rate": ordn.inconsistency_rate(dec),
                "share_any_unknown": float(np.mean((dec < 0).any(axis=1)))}
            kwargs = {"how": how, "grid_log10": ctx.cfg.calibration.grid_log10, "sweeps": ctx.cfg.calibration.sweeps}
            factors = ordn.tune_threshold_factors(row["assoc"], y_val, k, **kwargs)
            dec_c = ordn.decisions_with_factors(row["assoc"], factors)
            cross = np.empty(len(y_val), dtype=int)
            for g in np.unique(groups):
                held = groups == g
                f_g = ordn.tune_threshold_factors([a[~held] for a in row["assoc"]], y_val[~held], k, **kwargs)
                cross[held] = ordn.combine(ordn.decisions_with_factors([a[held] for a in row["assoc"]], f_g), how)
            rec["variants"][f"calib_{how}"] = {
                "validation": _summary(classification_metrics(y_val, ordn.combine(dec_c, how), k), cd.labels),
                "crossfit": _summary(classification_metrics(y_val, cross, k), cd.labels),
                "threshold_factors": factors.tolist(), "inconsistency_rate": ordn.inconsistency_rate(dec_c),
                "share_any_unknown": float(np.mean((dec_c < 0).any(axis=1)))}
        records.append(rec)
    ctx.save_json("ordinal", {"arm": "ordinal", "description": "idea 4: Frank and Hall decomposition, three binary "
                              "winning-rule classifiers", "thresholds": names, "seeds": records})
    _log("ordinal done")


# --------------------------------------------------------------------------------------------------- CLI

STAGES = ("base", "calib", "natw", "pool", "consensus", "restarts", "features", "ordinal", "control")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_ica3", description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=[*STAGES, "report", "decide", "final", "rundirs"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--only", default=None, help="pool: one seed set (A, B or C)")
    parser.add_argument("--features", default=None, help="pool/consensus/restarts: comma separated extra inputs")
    parser.add_argument("--tag", default="", help="prefix of the arm names and pool files (combination)")
    parser.add_argument("--test", action="store_true", help="final: read the test rows (once)")
    args = parser.parse_args(argv)
    ctx = Context(Ica3Config.model_validate_json(args.config.read_text()), args.artifacts_dir)
    extras = args.features.split(",") if args.features else None
    start = time.perf_counter()
    if args.stage == "base":
        stage_base(ctx)
    elif args.stage == "calib":
        stage_calib(ctx)
    elif args.stage == "natw":
        stage_natw(ctx)
    elif args.stage == "pool":
        stage_pool(ctx, args.only, extras, args.tag)
    elif args.stage == "consensus":
        stage_consensus(ctx, extras, args.tag)
    elif args.stage == "restarts":
        stage_restarts(ctx, args.tag)
    elif args.stage == "features":
        stage_features(ctx)
    elif args.stage == "ordinal":
        stage_ordinal(ctx)
    elif args.stage == "control":
        stage_control(ctx)
    else:  # report / decide / final live in ica3_report (they read the arm files)
        from atlas.ml import ica3_report

        getattr(ica3_report, args.stage)(ctx, test=args.test)
    _log(f"{args.stage} finished in {time.perf_counter() - start:.0f}s at {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
