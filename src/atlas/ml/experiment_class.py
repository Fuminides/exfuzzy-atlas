"""ICA classification experiment: ExFuzzy winning-rule classifier versus baselines, chronological split (AT-041c).

::

    python -m atlas.ml.experiment_class select --config configs/ml/madrid_no2_h6_ica_experiment.json  # validation only
    python -m atlas.ml.experiment_class final  --config configs/ml/madrid_no2_h6_ica_experiment.json  # seeds, test
    python -m atlas.ml.experiment_class runs   --config configs/ml/madrid_no2_h6_ica_experiment.json  # run directories

Protocol (all of it is in the config and echoed in ``summary.json``):

* The target is the class of the observed t+6h NO2 concentration in the official ICA scheme
  (``configs/ml/ica_no2_scheme.json``). Classes at the top with fewer than ``merge_min_train_rows`` *complete
  training rows* are merged into their lower neighbour; the rule only looks at the training counts and is fixed here
  (``class_distribution.json`` records the counts of every period and the merge).
* The split, embargo, complete-row definition and training-subsample code are those of AT-041
  (``atlas.ml.experiment.Data``). The fuzzy classifier is fitted on a class-aware subsample of the *training period*
  (``sampling_power``: class sizes proportional to ``count ** power``); partitions come from the whole training period.
* ``select`` fits the candidate list on validation and ranks by validation macro-F1 (ties: fewer rules); the test
  rows are never read there. ``final`` fits the chosen shape with several seeds, fits the baselines on the full
  training period and scores everything on all complete validation and test rows.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.class_baselines import (
    ClimatologyMajorityClass,
    PersistenceClass,
    RegressionThenBinned,
    SklearnClassBaseline,
    logistic_regression_baseline,
    random_forest_baseline,
)
from atlas.ml.classification import (
    ClassScheme,
    class_counts,
    class_sample,
    classification_metric_rows,
    classification_metrics,
    load_scheme,
)
from atlas.ml.evaluation import (
    PeakRss,
    classifier_readability_rows,
    classifier_rule_sets,
    rule_set_stability,
)
from atlas.ml.exfuzzy_features import (
    ensure_config,
    exfuzzy_version,
    provenance_hyperparameters,
    provenance_warnings,
)
from atlas.ml.experiment import Data, ExperimentConfig, experiment_dir, load_data
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.partitions import FixedPartition, PartitionConfig
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.subsample import stratified_subsample
from atlas.paths import ARTIFACTS_DIR, DATA_DIR, REPO_ROOT

VALIDATION_PREFIX = "validation/"
PREDICT_CHUNK = 500_000  # rows per baseline prediction call (a 300-tree forest on 3 M rows needs GBs at once)
RF_FULL_MAX_SAMPLES = 100_000  # bootstrap draw per tree of the random forests fitted on the full training period
FUZZY_CLASSIFIER = "exfuzzy_classifier"


class ClassSubsampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int
    seed: int
    partition_rows: int | None = None  # uniform thinning of the training rows used to build partitions (None: all)


class Candidate(BaseModel):
    """One shape of the selection grid. ``sampling_power``: class sizes ~ count ** power (1 = natural)."""

    model_config = ConfigDict(extra="forbid")

    nRules: int = 30
    nAnts: int = 3
    n_linguistic_variables: int = 3
    rule_weighting: str = "dominance_score"
    sampling_power: float = 0.5

    def key(self) -> tuple:
        return tuple(self.model_dump().values())


class ClassSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate]
    n_gen: int
    pop_size: int
    patience: int | None = None
    seed: int = 0


class ClassFinalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_gen: int
    pop_size: int
    patience: int | None = None
    seeds: list[int]


class ExtraTable(BaseModel):
    """A table joined 1:1 on (entity_id, issued_at_utc), inner: only the keys of this table are kept (AT-041d)."""

    model_config = ConfigDict(extra="forbid")

    table: str  # parquet file or hive directory; relative paths resolve against ATLAS_DATA_DIR
    columns: list[str]


class ClassExperimentConfig(ExperimentConfig):
    scheme: str = "configs/ml/ica_no2_scheme.json"  # relative to the repository root
    # Rare upper classes are merged from the top: fewer than ``merge_min_train_rows`` complete training rows (default
    # 500 when neither is given), or a share of the complete training rows below ``merge_min_train_share``.
    merge_min_train_rows: int | None = None
    merge_min_train_share: float | None = None
    target_label: str = "ICA"  # name of the target in rule text: "IF ... THEN ICA = Regular (peso 0.71)"
    # Baselines of the full training period are fitted on this many rows (uniform within station x month blocks,
    # natural class proportions) instead of all of them; None: every complete training row.
    baseline_train_rows: int | None = None
    partitions: PartitionConfig = PartitionConfig()  # fixed terms for some inputs (default: all quantile terms)
    extra_tables: list[ExtraTable] = []  # e.g. the AT-012 traffic table; its columns may be features
    require_columns: list[str] = []  # rows need finite values here even if they are not features
    # Extra persistence baselines {estimator name: feature}: the class of that feature (AT-041h: persistence_24h =
    # no2_yday_valid, the value 24 h before the target hour). Same metrics and slices as ``persistence``.
    persistence_baselines: dict[str, str] = {}
    subsample: ClassSubsampleConfig  # type: ignore[assignment]
    selection: ClassSelectionConfig  # type: ignore[assignment]
    final: ClassFinalConfig  # type: ignore[assignment]

    @model_validator(mode="after")
    def _merge_rule(self) -> ClassExperimentConfig:
        if self.merge_min_train_rows is not None and self.merge_min_train_share is not None:
            raise ValueError("merge_min_train_rows and merge_min_train_share are mutually exclusive")
        if self.merge_min_train_share is None:
            self.merge_min_train_rows = 500 if self.merge_min_train_rows is None else self.merge_min_train_rows
        elif not 0 < self.merge_min_train_share < 1:
            raise ValueError("merge_min_train_share must be in (0, 1)")
        return self


def _log(text: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


def _resolve(table: str) -> Path:
    path = Path(table)
    return path if path.is_absolute() else DATA_DIR / path


def load_class_frame(config: ClassExperimentConfig) -> pd.DataFrame | None:
    """The main table joined with ``extra_tables`` (None when there is nothing to join or require).

    Inner join on ``(entity_id, issued_at_utc)``, ``1:1`` checked, and every key of an extra table must exist in the
    main table. Rows whose ``require_columns`` or features are not finite get ``complete = False`` (they stay in the
    frame, so the split masks are unchanged, but no arm evaluates or fits them).
    """
    if not config.extra_tables and not config.require_columns:
        return None
    if config.compact_load:
        raise ValueError("compact_load does not support extra_tables or require_columns")
    base, keys = config.base, ["entity_id", "issued_at_utc"]
    extra_cols = {c for t in config.extra_tables for c in t.columns}
    columns = [*keys, base.target_column, *[f for f in base.features if f not in extra_cols]]
    if config.complete_column:
        columns.append(config.complete_column)
    frame = pd.read_parquet(_resolve(config.table), columns=columns)
    for extra in config.extra_tables:
        other = pd.read_parquet(_resolve(extra.table), columns=[*keys, *extra.columns])
        merged = frame.merge(other, on=keys, how="inner", validate="1:1")
        if len(merged) != len(other):
            raise ValueError(f"{extra.table}: {len(other) - len(merged)} keys are not in {config.table}")
        frame = merged
    need = list(dict.fromkeys([*base.features, *config.require_columns]))
    finite = np.isfinite(frame[need].to_numpy(dtype=float)).all(axis=1)
    if config.complete_column:
        frame[config.complete_column] = frame[config.complete_column].to_numpy(dtype=bool) & finite
    return frame


class ClassData:
    """``Data`` plus the class target: official scheme, the merged scheme used, and a class index per row."""

    def __init__(self, config: ClassExperimentConfig, frame: pd.DataFrame | None = None):
        self.config = config
        self.data: Data = load_data(config, load_class_frame(config) if frame is None else frame)
        path = Path(config.scheme)
        self.official = load_scheme(path if path.is_absolute() else REPO_ROOT / path)
        self.official_class = self.official.classify(self.data.y)
        train_counts = class_counts(self.official_class[self.data.train_pos], len(self.official.classes))
        self.scheme: ClassScheme = self.official.merge_rare_upper_tail(
            train_counts.tolist(), config.merge_min_train_rows, min_share=config.merge_min_train_share)
        self.y_class = self.scheme.classify(self.data.y)
        self.labels = self.scheme.labels
        self.fixed: dict[str, FixedPartition] = config.partitions.resolve()
        for feature, partition in self.fixed.items():
            # an open top class ends at the domain edge; so does the first class when values below it are class 0
            edges = [(c.label, partition.domain[0] if i == 0 and self.scheme.below_first_as_first else c.lower,
                      partition.domain[1] if c.upper is None else c.upper)
                     for i, c in enumerate(self.scheme.classes)]
            if partition.follows_target_scheme and [(b.name, b.lower, b.upper) for b in partition.bands] != edges:
                raise ValueError(f"{feature}: its terms are not the classes of the target scheme used {self.labels}")

    @property
    def _merge_threshold(self) -> str:
        c = self.config
        if c.merge_min_train_share is None:
            return str(c.merge_min_train_rows)
        return f"{c.merge_min_train_share:.2%} of the"

    def distribution(self) -> dict:
        d, k = self.data, len(self.official.classes)
        periods = {"train": d.train_pos, "validation": d.positions("validation"), "test": d.positions("test")}
        out = {
            "official_labels": self.official.labels,
            "used_labels": self.labels,
            "merge_rule": f"from the worst class downwards, a class with fewer than {self._merge_threshold} "
                          "complete training rows is merged with the next better class; stops at the first class "
                          "with enough rows. Thresholds are never changed.",
            "merged": [{"label": c.label, "lower": c.lower, "upper": c.upper, "merged_from": c.merged_from}
                       for c in self.scheme.classes if c.merged_from],
            "periods": {},
        }
        for name, pos in periods.items():
            official = class_counts(self.official_class[pos], k)
            used = class_counts(self.y_class[pos], len(self.labels))
            out["periods"][name] = {
                "n": int(len(pos)),
                "official": dict(zip(self.official.labels, map(int, official), strict=True)),
                "official_share": dict(zip(self.official.labels, (official / len(pos)).tolist(), strict=True)),
                "used": dict(zip(self.labels, map(int, used), strict=True)),
                "used_share": dict(zip(self.labels, (used / len(pos)).tolist(), strict=True)),
            }
        return out

    def train_sample(self, n_rows: int, seed: int, power: float) -> np.ndarray:
        d = self.data
        pos = d.train_pos
        picked = class_sample(self.y_class[pos], d.frame["entity_id"].array[pos], d.issued[pos], n_rows, seed,
                              power)  # .array: a categorical stays codes, no object array of 15 M strings
        return pos[picked]

    def partition_reference(self) -> pd.DataFrame:
        d, n = self.data, self.config.subsample.partition_rows
        pos = d.train_pos
        if n and n < len(pos):
            pos = pos[np.random.default_rng(self.config.subsample.seed).choice(len(pos), n, replace=False)]
        return d.frame.loc[pos, self.config.base.features]


def _fit(params: FuzzyClassifierParams, units: dict, X: pd.DataFrame, y: np.ndarray, labels: list[str], seed: int,
         reference: pd.DataFrame, fixed: dict[str, FixedPartition] | None = None):
    with PeakRss() as rss:
        start = time.perf_counter()
        model = FuzzyClassifier(params, units).fit(X, y, labels, seed, partition_reference=reference, fixed=fixed)
        seconds = time.perf_counter() - start
    return model, seconds, rss.peak_mb


def _params(c: Candidate, n_gen: int, pop: int, patience: int | None) -> FuzzyClassifierParams:
    return FuzzyClassifierParams(
        nRules=c.nRules, nAnts=c.nAnts, n_linguistic_variables=c.n_linguistic_variables,
        rule_weighting=c.rule_weighting, n_gen=n_gen, pop_size=pop, patience=patience)


def _summary(metrics: dict, labels: list[str]) -> dict:
    out = {k: metrics[k] for k in ("macro_f1", "balanced_accuracy", "accuracy", "mae_class_index",
                                   "share_off_by_2plus", "share_unknown")}
    out["recall"] = {lab: (None if np.isnan(r) else float(r)) for lab, r in zip(labels, metrics["recall"], strict=True)}
    out["precision"] = {lab: float(p) for lab, p in zip(labels, metrics["precision"], strict=True)}
    out["confusion"] = metrics["confusion"].tolist()
    return out


# ----------------------------------------------------------------------------------------------------- select


def run_selection(config: ClassExperimentConfig, cd: ClassData, out_dir: Path) -> dict:
    """Fit every candidate (resumable) on a class-aware training subsample, rank on validation macro-F1."""
    base, sel = config.base, config.selection
    ensure_config(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "class_distribution.json").write_text(json.dumps(cd.distribution(), indent=2) + "\n")
    path = out_dir / "selection.json"
    result = json.loads(path.read_text()) if path.exists() else {"fits": []}
    if config.exfuzzy_source:
        result["exfuzzy_source"] = config.exfuzzy_source
    d = cd.data
    val = d.positions("validation")
    X_val, y_val = d.frame.loc[val, base.features], cd.y_class[val]
    reference = cd.partition_reference()
    done = {tuple(f["candidate"].values()) for f in result["fits"]}
    for cand in sel.candidates:
        if cand.key() in done:
            continue
        rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, cand.sampling_power)
        params = _params(cand, sel.n_gen, sel.pop_size, sel.patience)
        _log(f"select: {cand} on {len(rows)} rows, classes {np.bincount(cd.y_class[rows]).tolist()}")
        model, secs, rss = _fit(params, base.feature_units, d.frame.loc[rows, base.features], cd.y_class[rows],
                                cd.labels, sel.seed, reference, cd.fixed)
        pred = model.predict(X_val)
        metrics = classification_metrics(y_val, pred, len(cd.labels))
        n_rules = len(model.rule_base.get_rules())
        result["fits"].append({
            "candidate": cand.model_dump(), "seed": sel.seed, "n_gen": sel.n_gen, "pop_size": sel.pop_size,
            "n_train_rows": len(rows), "train_class_counts": np.bincount(cd.y_class[rows]).tolist(),
            "validation": _summary(metrics, cd.labels), "n_validation_rows": len(val), "n_rules": n_rules,
            "fit_info": model.fit_info, "fit_seconds": secs, "peak_rss_mb": rss,
        })
        _log(f"select: val macro-F1 {metrics['macro_f1']:.3f} bal-acc {metrics['balanced_accuracy']:.3f} "
             f"acc {metrics['accuracy']:.3f} unknown {metrics['share_unknown']:.3f} rules {n_rules} "
             f"fit {secs:.0f}s rss {rss:.0f} MB")
        path.write_text(json.dumps(result, indent=2) + "\n")
    best = max(result["fits"], key=lambda f: (f["validation"]["macro_f1"], -f["n_rules"]))
    result["criterion"] = "highest validation macro-F1 (ties: fewer rules)"
    result["chosen"] = best["candidate"]
    path.write_text(json.dumps(result, indent=2) + "\n")
    return result


# ------------------------------------------------------------------------------------------------------ final


def _baselines(config: ClassExperimentConfig, cd: ClassData):
    """(baselines fitted on the full training period, baselines fitted on the fuzzy subsample)."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    base = config.base
    n = len(cd.labels)

    def hgb(name, weight=None):
        return SklearnClassBaseline(name, HistGradientBoostingClassifier(
            max_iter=base.gbm_max_iter, early_stopping=False, random_state=base.seed, class_weight=weight),
            base.features)

    def lr(name, balanced=False):
        return logistic_regression_baseline(name, base.features, balanced=balanced, seed=base.seed)

    def rf(name, balanced=False, max_samples=None):
        return random_forest_baseline(name, base.features, balanced=balanced, seed=base.seed, max_samples=max_samples)

    reg = RegressionThenBinned("hist_gradient_boosting_regression_binned", HistGradientBoostingRegressor(
        max_iter=base.gbm_max_iter, early_stopping=False, random_state=base.seed), base.features, cd.scheme)
    full = [
        PersistenceClass(base.persistence_feature, cd.scheme),
        *[PersistenceClass(feature, cd.scheme, name) for name, feature in config.persistence_baselines.items()],
        ClimatologyMajorityClass(base.horizon_hours, base.timezone, n),
        hgb("hist_gradient_boosting"),
        hgb("hist_gradient_boosting_balanced", "balanced"),
        reg,
        lr("logistic_regression"),
        lr("logistic_regression_balanced", True),
        rf("random_forest", max_samples=RF_FULL_MAX_SAMPLES),
        rf("random_forest_balanced", True, RF_FULL_MAX_SAMPLES),
    ]
    subsample = [
        hgb("hist_gradient_boosting_subsample"),
        lr("logistic_regression_subsample"),
        lr("logistic_regression_balanced_subsample", True),
        rf("random_forest_subsample"),
        rf("random_forest_balanced_subsample", True),
    ]
    return full, subsample


def _eval_rows(name, frame, y_class, pred, labels, base, prefix):
    return classification_metric_rows(name, y_class, pred, labels, {"entity": frame["entity_id"].array},
                                      prefix=prefix)


def run_final(config: ClassExperimentConfig, cd: ClassData, out_dir: Path, *, selection: dict | None = None,
              test: bool = True, baselines: bool = True, models: dict[int, FuzzyClassifier] | None = None,
              sub_rows: np.ndarray | None = None, fit_records: dict[int, dict] | None = None) -> dict:
    """Seeds, baselines and scoring. ``test=False`` never touches the test rows and writes ``summary_validation.json``
    (the seed fits, their models and rows files; ``summary.json`` and the run directories need ``test=True``);
    ``baselines=False`` skips the baselines (validation-only comparisons of fuzzy configurations).

    ``models`` (seed -> fitted classifier) scores classifiers fitted elsewhere instead of fitting them (AT-041h: the
    selected ica4 fits, pruned); ``sub_rows`` is then their fitting sample (positions in ``cd.data.frame``), used by the
    subsample baselines and the summary, and ``fit_records`` (seed -> ``fit_seconds`` / ``peak_rss_mb``) their cost."""
    base, d = config.base, cd.data
    ensure_config(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "models").mkdir(exist_ok=True)
    selection = selection or json.loads((out_dir / "selection.json").read_text())
    chosen = Candidate.model_validate(selection["chosen"])
    names = ("validation", "test") if test else ("validation",)
    periods = {p: d.positions(p) for p in names}
    frames = {p: d.frame.loc[pos] for p, pos in periods.items()}
    yc = {p: cd.y_class[pos] for p, pos in periods.items()}
    _log(f"final: rows {({p: len(v) for p, v in yc.items()})}, chosen {chosen}")

    if sub_rows is None:
        sub_rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, chosen.sampling_power)
    pd.DataFrame({"entity_id": d.frame["entity_id"].iloc[sub_rows].to_numpy(), "issued_at_utc": d.issued[sub_rows]}
                 ).to_parquet(out_dir / "subsample_keys.parquet", index=False)
    sub_frame, y_sub = d.frame.loc[sub_rows], cd.y_class[sub_rows]
    # Baselines "of the full training period": all complete training rows, or (baseline_train_rows) a bounded sample
    # of them, uniform within station x month blocks, natural class proportions. Climatology only counts, so it
    # always uses the whole period (keys only).
    train_pos = d.train_pos
    bounded = bool(config.baseline_train_rows) and config.baseline_train_rows < len(d.train_pos)
    if bounded:
        train_pos = d.train_pos[stratified_subsample(d.frame["entity_id"].array[d.train_pos], d.issued[d.train_pos],
                                                     config.baseline_train_rows, config.subsample.seed)]
    train_frame, y_train = d.frame.loc[train_pos], cd.y_class[train_pos]
    whole = ((d.frame.loc[d.train_pos, ["entity_id", "issued_at_utc"]], cd.y_class[d.train_pos], d.train_pos)
             if bounded and baselines else None)

    # --- baselines
    baseline_rows: list[m.MetricRow] = []
    baseline_pred: dict[str, dict[str, np.ndarray]] = {}
    fits = []
    if baselines:
        full_baselines, sub_baselines = _baselines(config, cd)
        own = (train_frame, y_train, train_pos)
        fits = [(b, *(whole if bounded and isinstance(b, ClimatologyMajorityClass) else own)) for b in full_baselines]
        fits += [(b, sub_frame, y_sub, sub_rows) for b in sub_baselines]
        del full_baselines, sub_baselines
    while fits:
        baseline, frame_fit, y_fit, pos_fit = fits.pop(0)  # popped: a scored baseline (a forest) is freed at once
        _log(f"final: baseline {baseline.name} (fit rows {len(frame_fit)})")
        if isinstance(baseline, RegressionThenBinned):
            baseline.values = d.y[pos_fit]
        start = time.perf_counter()
        baseline.fit(frame_fit, y_fit)
        fit_s = time.perf_counter() - start
        baseline_pred[baseline.name] = {}
        for period in names:
            pred = np.concatenate([baseline.predict(frames[period].iloc[i:i + PREDICT_CHUNK])
                                   for i in range(0, max(len(frames[period]), 1), PREDICT_CHUNK)])
            baseline_pred[baseline.name][period] = pred
            baseline_rows += _eval_rows(baseline.name, frames[period], yc[period], pred, cd.labels, base,
                                        VALIDATION_PREFIX if period == "validation" else "")
        baseline_rows.append(m.MetricRow(estimator=baseline.name, metric="fit_seconds", value=fit_s,
                                         n=len(frame_fit)))
        del baseline, frame_fit

    # --- the fuzzy classifier, one fit per seed
    params = _params(chosen, config.final.n_gen, config.final.pop_size, config.final.patience)
    reference = cd.partition_reference()
    X_sub = sub_frame[base.features]
    runs, rule_sets = [], []
    for seed in config.final.seeds:
        if models is not None:
            model = models[seed]
            fit_s, rss = (float((fit_records or {}).get(seed, {}).get(k, float("nan"))) for k in
                          ("fit_seconds", "peak_rss_mb"))
            _log(f"final: fuzzy seed {seed}, fitted elsewhere ({len(model.rule_base.get_rules())} rules)")
        else:
            _log(f"final: fuzzy seed {seed} {params}")
            model, fit_s, rss = _fit(params, base.feature_units, X_sub, y_sub, cd.labels, seed, reference, cd.fixed)
        rows = list(baseline_rows)
        pred = {}
        for period in names:
            X = frames[period][base.features]
            pred[period] = model.predict(X)
            prefix = VALIDATION_PREFIX if period == "validation" else ""
            rows += _eval_rows(FUZZY_CLASSIFIER, frames[period], yc[period], pred[period], cd.labels, base, prefix)
            finite = np.isfinite(X.to_numpy(dtype=float)).all(axis=1)
            rows += classifier_readability_rows(
                FUZZY_CLASSIFIER, model, X.to_numpy(dtype=float)[finite], cd.labels, yc[period][finite], prefix,
                include_static=period == names[-1])
        rows += [m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_seconds", value=fit_s, n=len(y_sub)),
                 m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_peak_rss_mb", value=rss, n=len(y_sub))]
        rule_sets.append(classifier_rule_sets(model, cd.labels))
        with open(out_dir / "models" / f"seed{seed}.pkl", "wb") as fh:
            pickle.dump(model, fh)
        (out_dir / "models" / f"rows_seed{seed}.json").write_text(
            json.dumps([r.model_dump() for r in rows]) + "\n")
        runs.append({
            "seed": seed, "fit_seconds": fit_s, "peak_rss_mb": rss, "fit_info": model.fit_info,
            "n_rules": len(rule_sets[-1]),
            **{p: _summary(classification_metrics(yc[p], pred[p], len(cd.labels)), cd.labels) for p in names},
            "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rule_sets[-1]],
        })
    best = max(runs, key=lambda r: r["validation"]["macro_f1"])
    summary = {
        "experiment_id": config.experiment_id,
        "labels": cd.labels,
        "n_complete_rows": {"train_full": int(len(d.train_pos)), "train_subsample": int(len(sub_rows)),
                            **({"train_baselines_bounded_sample": int(len(train_pos))} if bounded else {}),
                            **{p: int(len(yc[p])) for p in names}},
        "subsample_class_counts": np.bincount(y_sub, minlength=len(cd.labels)).tolist(),
        "chosen": chosen.model_dump(),
        "final_budget": {"n_gen": params.n_gen, "pop_size": params.pop_size, "patience": params.patience,
                         "seeds": config.final.seeds},
        "runs": runs,
        "published_seed_rule": "highest validation macro-F1 among the seeds",
        "published_seed": best["seed"],
        "rule_stability": rule_set_stability(rule_sets),
        "baselines": {
            name: {p: _summary(classification_metrics(yc[p], pred, len(cd.labels)), cd.labels)
                   for p, pred in preds.items()} for name, preds in baseline_pred.items()
        },
    }
    summary["fixed_partitions"] = {f: json.loads(fp.model_dump_json()) for f, fp in cd.fixed.items()}
    if config.exfuzzy_source:
        summary["exfuzzy_source"] = config.exfuzzy_source
    name = "summary.json" if test else "summary_validation.json"
    (out_dir / name).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# ------------------------------------------------------------------------------------------- run directories

TARGET_LABEL = "ICA"  # rule text: "IF ... THEN ICA = Regular (peso 0.71)"


def _class_prediction_table(model: FuzzyClassifier, frame: pd.DataFrame, cd: ClassData, model_id: str) -> pd.DataFrame:
    """Predicted ICA class for every row of ``frame``: null label plus a reason where there is no prediction."""
    base = cd.config.base
    X = frame[base.features]
    pred = model.predict(X)
    finite = np.isfinite(X.to_numpy(dtype=float)).all(axis=1)
    labels = np.array([*cd.labels, None], dtype=object)[np.where(pred < 0, len(cd.labels), pred)]
    observed = frame[base.target_column].to_numpy(dtype=float)
    observed_class = cd.scheme.classify(observed)
    reason = np.where(pred >= 0, None, np.where(finite, m.MissingReason.PREDICTION_UNAVAILABLE.value,
                                                m.MissingReason.MISSING_INPUT.value))
    issued = pd.DatetimeIndex(frame["issued_at_utc"])
    return pd.DataFrame({
        "entity_id": frame["entity_id"].to_numpy(), "issued_at_utc": issued,
        "valid_at_utc": issued + timedelta(hours=base.horizon_hours),
        "observed": np.where(np.isfinite(observed), observed, np.nan),
        "observed_label": np.array([*cd.labels, None], dtype=object)[np.where(observed_class < 0, len(cd.labels),
                                                                              observed_class)],
        "prediction": np.full(len(frame), np.nan), "prediction_label": labels, "model_id": model_id,
        "missing_reason": reason,
    })


def write_class_runs(config: ClassExperimentConfig, cd: ClassData, out_dir: Path, artifacts_dir: Path, *,
                     sub_rows: np.ndarray | None = None, seeds: list[int] | None = None,
                     extra_warnings: list[str] | None = None, extra_hyperparameters: dict | None = None) -> list[Path]:
    """One run directory per fitted seed (``artifacts/<task>/<experiment_id>-seed<k>``), from ``models/`` and
    ``summary.json``: manifest, metrics, rules (contract v0.3, with the target scheme), test-period predictions.

    ``sub_rows`` is the fitting sample when the models were fitted elsewhere (``run_final(models=...)``), ``seeds``
    limits the directories written, ``extra_warnings`` / ``extra_hyperparameters`` go to the manifest."""
    base, d = config.base, cd.data
    summary = json.loads((out_dir / "summary.json").read_text())
    test_all = d.frame.loc[d.masks["test"]]
    power = Candidate(**summary["chosen"]).sampling_power
    if sub_rows is None:
        sub_rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, power)
    sub_frame = d.frame.loc[sub_rows]
    scheme = cd.scheme.to_target_scheme()
    created, dirs = datetime.now(timezone.utc), []
    commit, dirty = artifacts.git_state()
    for run in summary["runs"]:
        seed = run["seed"]
        if seeds is not None and seed not in seeds:
            continue
        with open(out_dir / "models" / f"seed{seed}.pkl", "rb") as fh:
            model: FuzzyClassifier = pickle.load(fh)  # noqa: S301 - written by run_final
        run_id = f"{config.experiment_id}-seed{seed}"
        model_id = f"exfuzzy-{base.task_id}-{run_id}"
        raw_rows = json.loads((out_dir / "models" / f"rows_seed{seed}.json").read_text())
        rows = [m.MetricRow.model_validate(r) for r in raw_rows]
        metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
        rules = export_classifier_rules(
            model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=config.target_label,
            target_scheme=scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
            synthetic=base.synthetic, feature_units=base.feature_units, X_reference=sub_frame[base.features])
        manifest = m.RunManifest(
            run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
            git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
            python_version=artifacts.python_version(), seed=seed, split=base.split, data_version=base.data_version,
            data_checksums=base.data_checksums, target=base.target, horizon_hours=base.horizon_hours,
            features=base.features,
            hyperparameters={
                **model.params.as_dict(), "task_type": "classification", "target_label": config.target_label,
                "class_labels": cd.labels, "official_labels": cd.official.labels,
                "persistence_feature": base.persistence_feature, "timezone": base.timezone,
                "n_train_rows": len(sub_rows), "fit_info": model.fit_info,
                "sampling_power": summary["chosen"]["sampling_power"],
                "experiment": json.loads(config.model_dump_json(exclude={"base"})),
                "run_config": json.loads(base.model_copy(update={"seed": seed, "run_id": run_id}).model_dump_json()),
                **provenance_hyperparameters(config),
                **(extra_hyperparameters or {}),
            },
            artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                       "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE},
            warnings=[f"fitted on a class-aware subsample of {len(sub_rows)} of the {len(d.train_pos)} complete "
                      f"training rows (class counts {summary['subsample_class_counts']}); "
                      + ("the dominance scores and rule weights therefore reflect that sampling, not the natural "
                         "class frequencies" if model.params.rule_weighting != "none" else
                         "the rules are unweighted (every weight is 1), so only the rule search saw that sampling"),
                      *provenance_warnings(config), *(extra_warnings or [])],
        )
        run_dir = artifacts.write_run_dir(
            Path(artifacts_dir) / base.task_id / run_id, model=model,
            parity_sample=d.frame.loc[d.positions("test"), base.features].head(500),
            json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                        "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                        "rules.json": rules.model_dump_json(indent=2) + "\n"},
            parquet_files={"predictions.parquet": _class_prediction_table(model, test_all, cd, model_id)},
        )
        dirs.append(run_dir)
        _log(f"wrote {run_dir}")
    return dirs


# --------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_class", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["select", "final", "runs", "all"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--validation-only", action="store_true",
                        help="final: seeds scored on validation only (no test rows read, summary_validation.json)")
    parser.add_argument("--no-baselines", action="store_true", help="final: skip the baselines")
    parser.add_argument("--selection", type=Path, default=None,
                        help="final: selection.json (its 'chosen' shape) of another experiment, instead of this one")
    args = parser.parse_args(argv)
    config = ClassExperimentConfig.model_validate_json(args.config.read_text())
    out_dir = experiment_dir(config, args.artifacts_dir)
    cd = ClassData(config)
    if args.command in ("select", "all"):
        print(json.dumps(run_selection(config, cd, out_dir)["chosen"]))
    if args.command in ("final", "all"):
        selection = json.loads(args.selection.read_text()) if args.selection else None
        summary = run_final(config, cd, out_dir, selection=selection, test=not args.validation_only,
                            baselines=not args.no_baselines)
        print(json.dumps({"published_seed": summary["published_seed"]}))
    if args.command == "runs":
        print(json.dumps([str(p) for p in write_class_runs(config, cd, out_dir, args.artifacts_dir)]))


if __name__ == "__main__":
    main()
