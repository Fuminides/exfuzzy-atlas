"""NYC yellow-taxi demand level (baja / normal / alta / muy alta): ExFuzzy classifier versus baselines (AT-041e).

::

    C=configs/ml/nyc_pickups_h1_level_all12_experiment.json
    python -m atlas.ml.experiment_nyc profile --config $C   # hourly profile of the training period (hour terms)
    python -m atlas.ml.experiment_nyc select  --config $C   # validation only
    python -m atlas.ml.experiment_nyc final   --config $C   # seeds, baselines, test (read once)
    python -m atlas.ml.experiment_nyc runs    --config $C   # run directories

Same protocol as ``atlas.ml.experiment_class`` (Madrid ICA), whose fitting, selection and readability code it reuses,
with the differences of this target (``docs/ml/nyc_pickups_h1_level_ica.md``):

* The class is **precomputed** (``target_level``: percentile of the count in its zone x week-hour train cell, cut at
  25/75/95); ``ClassScheme.classify`` (integer ICA bands) does not apply. Rows without a label (``low_volume``,
  ``insufficient_samples``, ``target_missing``) are *not complete*: never fitted, never scored, never counted as
  ``normal``. The scheme is the contract ``TargetScheme`` of ``configs/mobility/nyc_level_scheme.json``.
* Every score is reported overall, per ``volume_group`` (a column to slice by, never a feature) and per local month,
  with the predicted and the observed class shares per month: the test period (Feb-Mar 2025) has a base rate far from
  the training one (season, congestion pricing from 2025-01-05 and vendor reporting are confounded).
* Level persistence is the class of ``rel_lag1`` (cuts 25/75/95), also of ``rel_lag24`` and ``rel_lag168``.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.class_baselines import SklearnClassBaseline, logistic_regression_baseline, random_forest_baseline
from atlas.ml.classification import class_counts, classification_metric_rows, classification_metrics
from atlas.ml.evaluation import classifier_readability_rows, classifier_rule_sets, rule_set_stability
from atlas.ml.exfuzzy_features import ensure_config, exfuzzy_version, provenance_hyperparameters, provenance_warnings
from atlas.ml.experiment import experiment_dir, load_data
from atlas.ml.experiment_class import (
    FUZZY_CLASSIFIER,
    RF_FULL_MAX_SAMPLES,
    VALIDATION_PREFIX,
    Candidate,
    ClassData,
    ClassExperimentConfig,
    _fit,
    _log,
    _params,
    _summary,
    run_selection,
)
from atlas.ml.fuzzy_classifier import FuzzyClassifier
from atlas.ml.rules_export import export_classifier_rules
from atlas.paths import ARTIFACTS_DIR, DATA_DIR, REPO_ROOT
from atlas.services.publish import _class_predictions

TARGET_LABEL = "nivel"  # rule text: "IF ... THEN nivel = muy alta (peso 0.71)"
NO_REFERENCE = "sin referencia"
CUTS = (25.0, 75.0, 95.0)  # percentile cut points of the scheme (baja | normal | alta | muy alta), lower-inclusive
PERSISTENCE_FEATURES = ("rel_lag1", "rel_lag24", "rel_lag168")


class NycExperimentConfig(ClassExperimentConfig):
    label_column: str = "target_level"
    status_column: str = "level_status"
    group_column: str = "volume_group"
    baseline_features: list[str] | None = None  # inputs of the sklearn baselines (None: the fuzzy inputs)


# ------------------------------------------------------------------------------------------------------ data


class NycData(ClassData):
    """``Data`` plus the precomputed class: label per row (``-1`` where there is none) and the slicing columns."""

    def __init__(self, config: NycExperimentConfig, frame: pd.DataFrame | None = None):
        self.config = config
        path = Path(config.scheme)
        path = path if path.is_absolute() else REPO_ROOT / path
        self.target_scheme = m.TargetScheme.model_validate_json(path.read_text())
        if self.target_scheme.boundary != "lower_inclusive":
            raise ValueError("the NYC scheme is lower-inclusive over percentiles")
        self.labels = [c.label for c in self.target_scheme.classes]
        frame = load_nyc_frame(config) if frame is None else frame
        self.data = load_data(config, frame)
        f = self.data.frame
        codes = pd.Categorical(f[config.label_column], categories=self.labels).codes
        self.y_class = np.asarray(codes, dtype=int)  # -1: no label
        self.fixed = config.partitions.resolve()
        for feature, partition in self.fixed.items():
            if partition.follows_target_scheme and [b.name for b in partition.bands] != self.labels:
                raise ValueError(f"{feature}: its terms are not the classes of the target scheme {self.labels}")
        self.group = f[config.group_column].astype(str).to_numpy()
        self.month = np.asarray(self.data.issued.tz_convert(config.base.timezone).strftime("%Y-%m"))

    def periods(self) -> dict[str, np.ndarray]:
        d = self.data
        return {"train": d.train_pos, "validation": d.positions("validation"), "test": d.positions("test")}

    def distribution(self) -> dict:
        d, k, f = self.data, len(self.labels), self.data.frame
        out = {"labels": self.labels, "no_reference_label": NO_REFERENCE, "periods": {}}
        for name, pos in self.periods().items():
            span = d.masks[name]
            known = span & np.isfinite(d.y)
            unlabeled = known & (self.y_class < 0)
            entry = {
                "n_complete": int(len(pos)),
                "counts": dict(zip(self.labels, map(int, class_counts(self.y_class[pos], k)), strict=True)),
                "share": dict(zip(self.labels, (class_counts(self.y_class[pos], k) / max(len(pos), 1)).tolist(),
                                  strict=True)),
                "n_target_known_without_label": int(unlabeled.sum()),
                "without_label_by_status": f.loc[unlabeled, self.config.status_column].value_counts().to_dict(),
                "by_group": {}, "by_month": {},
            }
            for key, values in (("by_group", self.group), ("by_month", self.month)):
                for v in sorted(set(values[pos])):
                    sel = pos[values[pos] == v]
                    c = class_counts(self.y_class[sel], k)
                    entry[key][v] = {"n": int(len(sel)), "share": dict(zip(self.labels, (c / len(sel)).tolist(),
                                                                           strict=True))}
            out["periods"][name] = entry
        return out


def load_nyc_frame(config: NycExperimentConfig) -> pd.DataFrame:
    """The level table with a ``complete`` column: label present and every input finite (``require_columns`` and the
    inputs of both the fuzzy model and the baselines, so every arm of a comparison scores the same rows)."""
    base = config.base
    path = Path(config.table)
    path = path if path.is_absolute() else DATA_DIR / path
    need = list(dict.fromkeys([*base.features, *(config.baseline_features or []), *config.require_columns,
                               *PERSISTENCE_FEATURES]))
    columns = ["entity_id", "issued_at_utc", base.target_column, config.label_column, config.status_column,
               config.group_column, *need]
    frame = pd.read_parquet(path, columns=list(dict.fromkeys(columns)))
    finite = np.isfinite(frame[need].to_numpy(dtype=float)).all(axis=1)
    frame["complete"] = frame[config.label_column].notna().to_numpy() & finite
    frame[config.group_column] = frame[config.group_column].astype("category")
    frame[config.status_column] = frame[config.status_column].astype("category")
    return frame


# -------------------------------------------------------------------------------------------------- baselines


class LevelPersistence:
    """Class of a percentile column through the scheme cuts (lower-inclusive); ``-1`` where it is missing."""

    def __init__(self, feature: str, cuts=CUTS, name: str | None = None):
        self.feature, self.cuts = feature, np.asarray(cuts, dtype=float)
        self.name = name or f"persistence_{feature}"

    def fit(self, frame, y) -> LevelPersistence:
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        v = frame[self.feature].to_numpy(dtype=float)
        return np.where(np.isfinite(v), np.searchsorted(self.cuts, v, side="right"), -1).astype(int)


class MajorityClass:
    """The most frequent training class, for every row (ties: the lower class)."""

    name = "majority_class"

    def __init__(self, n_classes: int):
        self.n_classes = n_classes

    def fit(self, frame, y) -> MajorityClass:
        self.class_ = int(np.bincount(np.asarray(y, dtype=int), minlength=self.n_classes).argmax())
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full(len(frame), self.class_, dtype=int)


def _baselines(config: NycExperimentConfig, n_classes: int):
    """(fitted on the whole training period, fitted on the fuzzy subsample); sklearn ones use ``baseline_features``."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    base = config.base
    features = config.baseline_features or base.features

    def hgb(name, weight=None):
        return SklearnClassBaseline(name, HistGradientBoostingClassifier(
            max_iter=base.gbm_max_iter, early_stopping=False, random_state=base.seed, class_weight=weight), features)

    def lr(name, balanced=False):
        return logistic_regression_baseline(name, features, balanced=balanced, seed=base.seed)

    def rf(name, balanced=False, max_samples=None):
        return random_forest_baseline(name, features, balanced=balanced, seed=base.seed, max_samples=max_samples)

    full = [
        LevelPersistence("rel_lag1", name="persistence"), LevelPersistence("rel_lag24"), LevelPersistence("rel_lag168"),
        MajorityClass(n_classes),
        hgb("hist_gradient_boosting"), hgb("hist_gradient_boosting_balanced", "balanced"),
        lr("logistic_regression"), lr("logistic_regression_balanced", True),
        rf("random_forest", max_samples=RF_FULL_MAX_SAMPLES), rf("random_forest_balanced", True, RF_FULL_MAX_SAMPLES),
    ]
    sub = [hgb("hist_gradient_boosting_subsample"), lr("logistic_regression_subsample"),
           rf("random_forest_subsample")]
    return full, sub


# --------------------------------------------------------------------------------------------------- scoring


def _shares(y: np.ndarray, k: int, with_none: bool) -> list[float]:
    counts = np.bincount(np.where(y < 0, k, y), minlength=k + 1)[: k + 1 if with_none else k].astype(float)
    return (counts / max(len(y), 1)).tolist()


def _block(cd: NycData, pos: np.ndarray, pred: np.ndarray) -> dict:
    """Metrics overall, per volume group and per month, and class shares per month (observed and predicted)."""
    k, y = len(cd.labels), cd.y_class[pos]
    out = {"overall": _summary(classification_metrics(y, pred, k), cd.labels), "by_group": {}, "by_month": {},
           "shares_by_month": {}}
    out["overall"]["n"] = int(len(y))
    for key, values in (("by_group", cd.group[pos]), ("by_month", cd.month[pos])):
        for v in sorted(set(values)):
            sel = values == v
            out[key][v] = {**_summary(classification_metrics(y[sel], pred[sel], k), cd.labels), "n": int(sel.sum())}
    for v in sorted(set(cd.month[pos])):
        sel = cd.month[pos] == v
        out["shares_by_month"][v] = {"observed": _shares(y[sel], k, False), "predicted": _shares(pred[sel], k, True)}
    out["shares_by_month"]["labels"] = [*cd.labels, "no_prediction"]
    return out


def _rows(cd: NycData, name: str, pos: np.ndarray, pred: np.ndarray, prefix: str) -> list[m.MetricRow]:
    return classification_metric_rows(
        name, cd.y_class[pos], pred, cd.labels, {"volume_group": cd.group[pos], "month": cd.month[pos]},
        prefix=prefix, per_slice_scalar=("macro_f1", "balanced_accuracy", "accuracy"))


# --------------------------------------------------------------------------------------------------- final


def run_final(config: NycExperimentConfig, cd: NycData, out_dir: Path, *, selection: dict | None = None,
              test: bool = True, baselines: bool = True) -> dict:
    """Seeds, baselines and scoring; ``test=False`` never reads the test rows (``summary_validation.json``)."""
    base, d, k = config.base, cd.data, len(cd.labels)
    ensure_config(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "models").mkdir(exist_ok=True)
    selection = selection or json.loads((out_dir / "selection.json").read_text())
    chosen = Candidate.model_validate(selection["chosen"])
    names = ("validation", "test") if test else ("validation",)
    periods = {p: d.positions(p) for p in names}
    frames = {p: d.frame.loc[pos] for p, pos in periods.items()}
    _log(f"final: rows {({p: len(v) for p, v in periods.items()})}, chosen {chosen}")

    sub_rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, chosen.sampling_power)
    pd.DataFrame({"entity_id": d.frame["entity_id"].to_numpy()[sub_rows], "issued_at_utc": d.issued[sub_rows]}
                 ).to_parquet(out_dir / "subsample_keys.parquet", index=False)
    sub_frame, y_sub = d.frame.loc[sub_rows], cd.y_class[sub_rows]
    train_frame, y_train = d.frame.loc[d.train_pos], cd.y_class[d.train_pos]

    baseline_rows: list[m.MetricRow] = []
    baseline_blocks: dict[str, dict] = {}
    fits = []
    if baselines:
        full, sub = _baselines(config, k)
        fits = [(b, train_frame, y_train) for b in full] + [(b, sub_frame, y_sub) for b in sub]
    for baseline, frame_fit, y_fit in fits:
        _log(f"final: baseline {baseline.name} (fit rows {len(frame_fit)})")
        start = time.perf_counter()
        baseline.fit(frame_fit, y_fit)
        fit_s = time.perf_counter() - start
        baseline_blocks[baseline.name] = {}
        for p in names:
            pred = baseline.predict(frames[p])
            baseline_blocks[baseline.name][p] = _block(cd, periods[p], pred)
            baseline_rows += _rows(cd, baseline.name, periods[p], pred, VALIDATION_PREFIX if p == "validation" else "")
        baseline_rows.append(m.MetricRow(estimator=baseline.name, metric="fit_seconds", value=fit_s, n=len(frame_fit)))

    params = _params(chosen, config.final.n_gen, config.final.pop_size, config.final.patience)
    reference = cd.partition_reference()
    X_sub = sub_frame[base.features]
    runs, rule_sets = [], []
    for seed in config.final.seeds:
        _log(f"final: fuzzy seed {seed} {params}")
        model, fit_s, rss = _fit(params, base.feature_units, X_sub, y_sub, cd.labels, seed, reference, cd.fixed)
        rows, blocks = list(baseline_rows), {}
        for p in names:
            X = frames[p][base.features]
            pred = model.predict(X)
            prefix = VALIDATION_PREFIX if p == "validation" else ""
            blocks[p] = _block(cd, periods[p], pred)
            rows += _rows(cd, FUZZY_CLASSIFIER, periods[p], pred, prefix)
            finite = np.isfinite(X.to_numpy(dtype=float)).all(axis=1)
            rows += classifier_readability_rows(
                FUZZY_CLASSIFIER, model, X.to_numpy(dtype=float)[finite], cd.labels, cd.y_class[periods[p]][finite],
                prefix, include_static=p == names[-1])
        rows += [m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_seconds", value=fit_s, n=len(y_sub)),
                 m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_peak_rss_mb", value=rss, n=len(y_sub))]
        rule_sets.append(classifier_rule_sets(model, cd.labels))
        with open(out_dir / "models" / f"seed{seed}.pkl", "wb") as fh:
            pickle.dump(model, fh)
        (out_dir / "models" / f"rows_seed{seed}.json").write_text(json.dumps([r.model_dump() for r in rows]) + "\n")
        runs.append({
            "seed": seed, "fit_seconds": fit_s, "peak_rss_mb": rss, "fit_info": model.fit_info,
            "n_rules": len(rule_sets[-1]), **blocks,
            "rules": [{"antecedents": [list(p) for p in a], "class": c} for a, c in rule_sets[-1]],
        })
    best = max(runs, key=lambda r: r["validation"]["overall"]["macro_f1"])
    summary = {
        "experiment_id": config.experiment_id, "labels": cd.labels, "features": base.features,
        "baseline_features": config.baseline_features or base.features,
        "n_complete_rows": {"train_full": int(len(d.train_pos)), "train_subsample": int(len(sub_rows)),
                            **{p: int(len(v)) for p, v in periods.items()}},
        "subsample_class_counts": np.bincount(y_sub, minlength=k).tolist(),
        "chosen": chosen.model_dump(),
        "final_budget": {"n_gen": params.n_gen, "pop_size": params.pop_size, "patience": params.patience,
                         "seeds": config.final.seeds},
        "runs": runs, "published_seed_rule": "highest validation macro-F1 among the seeds",
        "published_seed": best["seed"], "rule_stability": rule_set_stability(rule_sets),
        "baselines": baseline_blocks,
        "fixed_partitions": {f: json.loads(fp.model_dump_json()) for f, fp in cd.fixed.items()},
        **({"exfuzzy_source": config.exfuzzy_source} if config.exfuzzy_source else {}),
    }
    (out_dir / ("summary.json" if test else "summary_validation.json")).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# ------------------------------------------------------------------------------------------- run directories


def write_runs(config: NycExperimentConfig, cd: NycData, out_dir: Path, artifacts_dir: Path) -> list[Path]:
    """One run directory per fitted seed (``artifacts/<task>/<experiment_id>-seed<k>``): manifest, metrics, rules
    (contract v0.3 with the lower-inclusive percentile scheme) and the test-period predictions."""
    base, d = config.base, cd.data
    summary = json.loads((out_dir / "summary.json").read_text())
    test_all = d.frame.loc[d.masks["test"]]
    power = Candidate(**summary["chosen"]).sampling_power
    sub_rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, power)
    sub_frame = d.frame.loc[sub_rows]
    created, dirs = datetime.now(timezone.utc), []
    commit, dirty = artifacts.git_state()
    for run in summary["runs"]:
        seed = run["seed"]
        with open(out_dir / "models" / f"seed{seed}.pkl", "rb") as fh:
            model: FuzzyClassifier = pickle.load(fh)  # noqa: S301 - written by run_final
        run_id = f"{config.experiment_id}-seed{seed}"
        model_id = f"exfuzzy-{base.task_id}-{run_id}"
        raw_rows = json.loads((out_dir / "models" / f"rows_seed{seed}.json").read_text())
        rows = [m.MetricRow.model_validate(r) for r in raw_rows]
        metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
        rules = export_classifier_rules(
            model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=TARGET_LABEL,
            target_scheme=cd.target_scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
            synthetic=base.synthetic, feature_units=base.feature_units, X_reference=sub_frame[base.features])
        manifest = m.RunManifest(
            run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
            git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
            python_version=artifacts.python_version(), seed=seed, split=base.split, data_version=base.data_version,
            data_checksums=base.data_checksums, target=base.target, horizon_hours=base.horizon_hours,
            features=base.features,
            hyperparameters={
                **model.params.as_dict(), "task_type": "classification", "target_label": TARGET_LABEL,
                "class_labels": cd.labels, "persistence_feature": base.persistence_feature,
                "timezone": base.timezone, "n_train_rows": len(sub_rows), "fit_info": model.fit_info,
                "sampling_power": summary["chosen"]["sampling_power"],
                "experiment": json.loads(config.model_dump_json(exclude={"base"})),
                "run_config": json.loads(base.model_copy(update={"seed": seed, "run_id": run_id}).model_dump_json()),
                **provenance_hyperparameters(config),
            },
            artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                       "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE},
            warnings=[
                f"fitted on a class-aware subsample of {len(sub_rows)} of the {len(d.train_pos)} complete training "
                f"rows (class counts {summary['subsample_class_counts']}); the dominance scores and rule weights "
                "therefore reflect that sampling, not the natural class frequencies",
                "the level is relative to the zone's own April-December 2024 norm for that hour of the week; "
                "'alta' in February-March 2025 mixes unusual demand with season, vendor-reporting and "
                "congestion-pricing effects (not separable); rows without a reference level carry no class",
                *provenance_warnings(config),
            ],
        )
        predictions = _class_predictions(
            model, test_all, base.features, test_all[base.target_column].to_numpy(dtype=float), cd.target_scheme,
            pd.Timedelta(hours=base.horizon_hours), test_all[config.label_column])
        predictions["model_id"] = model_id
        run_dir = artifacts.write_run_dir(
            Path(artifacts_dir) / base.task_id / run_id, model=model,
            parity_sample=d.frame.loc[d.positions("test"), base.features].head(500),
            json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                        "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                        "rules.json": rules.model_dump_json(indent=2) + "\n"},
            parquet_files={"predictions.parquet": predictions},
        )
        dirs.append(run_dir)
        _log(f"wrote {run_dir}")
    return dirs


# ------------------------------------------------------------------------------------------------- profile


def hourly_profile(config: NycExperimentConfig) -> dict:
    """Citywide pickups per local hour in the training period, by day type, divided by the mean of the 24 hours.

    Used to read the day periods of ``local_hour`` (``configs/ml/nyc_partitions.json``); sums over all zones of the
    table, rows with a known target, training period only.
    """
    base = config.base
    path = Path(config.table)
    path = path if path.is_absolute() else DATA_DIR / path
    f = pd.read_parquet(path, columns=["issued_at_utc", base.target_column, "local_hour", "local_dow"])
    f = f[np.isfinite(f[base.target_column])]
    f = f[(f["issued_at_utc"] >= base.split.train_from_utc) & (f["issued_at_utc"] < base.split.train_to_utc)]
    f["day_type"] = np.where(f["local_dow"] < 5, "workday", np.where(f["local_dow"] == 5, "saturday", "sunday"))
    table = f.groupby(["day_type", "local_hour"])[base.target_column].sum().unstack(0)
    table = table / table.mean()
    out = {"relative_to_daily_mean": {c: table[c].round(3).tolist() for c in table},
           "workday_p25_p50_p75": np.quantile(table["workday"], [0.25, 0.5, 0.75]).round(3).tolist(),
           "n_rows": int(len(f))}
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_nyc", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["profile", "select", "final", "runs", "all"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--validation-only", action="store_true",
                        help="final: seeds scored on validation only (no test rows read, summary_validation.json)")
    parser.add_argument("--no-baselines", action="store_true", help="final: skip the baselines")
    parser.add_argument("--selection", type=Path, default=None,
                        help="final: selection.json (its 'chosen' shape) of another experiment, instead of this one")
    args = parser.parse_args(argv)
    config = NycExperimentConfig.model_validate_json(args.config.read_text())
    if args.command == "profile":
        print(json.dumps(hourly_profile(config), indent=1))
        return
    out_dir = experiment_dir(config, args.artifacts_dir)
    cd = NycData(config)
    if args.command in ("select", "all"):
        print(json.dumps(run_selection(config, cd, out_dir)["chosen"]))
    if args.command in ("final", "all"):
        selection = json.loads(args.selection.read_text()) if args.selection else None
        summary = run_final(config, cd, out_dir, selection=selection, test=not args.validation_only,
                            baselines=not args.no_baselines)
        print(json.dumps({"published_seed": summary["published_seed"]}))
    if args.command == "runs":
        print(json.dumps([str(p) for p in write_runs(config, cd, out_dir, args.artifacts_dir)]))


if __name__ == "__main__":
    main()
