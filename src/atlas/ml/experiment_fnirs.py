"""fNIRS n-back (0-back versus 2/3-back) from block-averaged haemoglobin changes, ExFuzzy classifier versus baselines.

::

    C=configs/ml/fnirs_nback_experiment.json
    python -u -m atlas.ml.experiment_fnirs select --config $C   # cross-validation over the training subjects only
    python -u -m atlas.ml.experiment_fnirs final  --config $C   # chosen shape, seeds, baselines, test (read once)
    python -u -m atlas.ml.experiment_fnirs seeds  --config $C   # error bars: every estimator x seed on test, x fold
    python -u -m atlas.ml.experiment_fnirs nested --config $C   # spread over people: nested CV over all subjects

Data: ``block_avg_tmb.csv`` of the ex-Fuzzy fNIRS demo (Caterson et al.; ``docs/fnirs/README.md``), one row per
(subject, trial) of the n-back task of Shin et al. (2018): 26 subjects x 27 trials, 72 inputs = 36 NIRS channels x
{HbO (``s1``), HbR (``s2``)}. Each input is the mean concentration change (mmol/L) 10-40 s after the block onset minus
the mean over -5..-2 s. The target is the published grouping: 0-back (event 7) versus 2-back or 3-back (events 8, 9).

* **Split by subject.** The test subjects are the manuscript's (``random.seed(1); random.sample(range(1, 27), 6)``),
  so no subject is in both train and test. They are not read by ``select``.
* **Selection** (``select``): every shape of the grid is fitted on the training subjects of each fold of a
  subject-grouped k-fold and scored on the held-out subjects of that fold. The shape with the largest mean
  validation macro-F1 wins; the baselines are scored on the same folds. The manuscript chose its model on the test
  subjects instead; this experiment does not, so its test numbers are not comparable with the manuscript's.
* **Final** (``final``): the chosen shape on every training subject with several seeds; the published seed is fixed in
  the config before the run. Baselines (majority class, logistic regression, random forest, RBF SVM) see the same
  inputs and the same split. Test is scored once.
* Partitions: three quantile terms per input, from the fitting rows (``FuzzyClassifier``). ``-1`` (no rule fired)
  counts as an error in every metric; MCC replaces it by the wrong class.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.ml import artifacts
from atlas.ml.classification import classification_metrics
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.paths import ARTIFACTS_DIR, DATA_DIR

CLASS_LABELS = ["0-back", "2/3-back"]
EVENT_CLASS = {7: 0, 8: 1, 9: 1}  # 7 = 0-back, 8 = 2-back, 9 = 3-back (dataset description, block_avg_tmb.csv)
SIGNALS = {"s1": "HbO", "s2": "HbR"}  # 002_Block_Averaging.ipynb: signal 1 = oxy, signal 2 = deoxy
UNIT = "mmol/L"  # 001_Pre_Processing.m: epo.oxy.yUnit = epo.deoxy.yUnit = 'mmol/L'
N_SUBJECTS = 26
MANUSCRIPT_TEST_SUBJECTS = (3, 4, 5, 9, 16, 19)


def manuscript_test_subjects(seed: int = 1, n_subjects: int = N_SUBJECTS, n_test: int = 6) -> list[int]:
    """The test subjects of notebooks 003/004 of the ex-Fuzzy fNIRS demo (Python ``random``, not numpy)."""
    rng = random.Random(seed)
    return sorted(rng.sample(list(range(1, n_subjects + 1)), n_test))


def _log(text: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


# ---------------------------------------------------------------------------------------------------- config


class Shape(BaseModel):
    """One point of the grid; the remaining ``FuzzyClassifierParams`` come from ``FnirsConfig.base``."""

    model_config = ConfigDict(extra="forbid")

    nRules: int
    nAnts: int
    inference: str = "winning_rule"
    ordinal_conditions: bool = False

    def params(self, base: dict) -> FuzzyClassifierParams:
        mixture = self.inference == "mixture"
        return FuzzyClassifierParams(**base, nRules=self.nRules, nAnts=self.nAnts, inference=self.inference,
                                     mixture_non_negative=mixture, mixture_search=mixture,
                                     ordinal_conditions=self.ordinal_conditions)

    @property
    def key(self) -> str:
        return (f"{self.inference}-r{self.nRules}-a{self.nAnts}" + ("-ordinal" if self.ordinal_conditions else ""))


class FnirsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    task_id: str
    table: str  # relative paths resolve against ATLAS_DATA_DIR
    test_subjects: list[int]
    n_folds: int
    fold_seed: int
    selection_seeds: list[int]
    base: dict  # FuzzyClassifierParams fields shared by every shape (n_gen, pop_size, ...)
    grid: dict[str, list]  # nRules, nAnts, inference, ordinal_conditions: the cartesian product is the grid
    final_seeds: list[int]
    published_seed: int
    workers: int = 4

    def shapes(self) -> list[Shape]:
        g = self.grid
        return [Shape(nRules=r, nAnts=a, inference=i, ordinal_conditions=o)
                for i in g["inference"] for o in g["ordinal_conditions"] for r in g["nRules"] for a in g["nAnts"]]


def load_config(path: str | Path) -> FnirsConfig:
    config = FnirsConfig.model_validate_json(Path(path).read_text())
    if sorted(config.test_subjects) != manuscript_test_subjects():
        raise ValueError("test_subjects must be the manuscript's split (random.seed(1), 6 of 26)")
    if config.published_seed not in config.final_seeds:
        raise ValueError("published_seed must be one of final_seeds")
    return config


# ------------------------------------------------------------------------------------------------------ data


def feature_columns(frame: pd.DataFrame) -> list[str]:
    cols = [c for c in frame.columns if c.startswith("tmb_s")]
    if len(cols) != 72:
        raise ValueError(f"expected 72 tmb_s<signal>_ch<channel> inputs, found {len(cols)}")
    return cols


def load_table(path: Path) -> pd.DataFrame:
    """Rows sorted by (subject, trial), integer ids, ``y`` from the event code; refuses gaps or non-finite inputs."""
    frame = pd.read_csv(path)
    frame[["subject", "trial", "event"]] = frame[["subject", "trial", "event"]].astype(int)
    if frame.duplicated(["subject", "trial"]).any():
        raise ValueError("duplicate (subject, trial) rows")
    features = feature_columns(frame)
    if not np.isfinite(frame[features].to_numpy(float)).all():
        raise ValueError("non-finite input")
    frame["y"] = frame["event"].map(EVENT_CLASS)
    if frame["y"].isna().any():
        raise ValueError(f"unknown event codes: {sorted(set(frame['event']) - set(EVENT_CLASS))}")
    if "stimulus" in frame and not (frame["stimulus"].astype(int) == frame["y"]).all():
        raise ValueError("stimulus column disagrees with the event mapping")
    frame["y"] = frame["y"].astype(int)
    return frame.sort_values(["subject", "trial"]).reset_index(drop=True)


def subject_folds(subjects: list[int], n_folds: int, seed: int) -> list[list[int]]:
    """Disjoint groups of subjects (a seeded shuffle dealt round-robin), covering every subject once."""
    order = sorted(subjects)
    np.random.default_rng(seed).shuffle(order)
    return [sorted(order[k::n_folds]) for k in range(n_folds)]


def scores(y: np.ndarray, pred: np.ndarray) -> dict:
    """Macro-F1, accuracy, balanced accuracy, unknown share and MCC (an unknown counts as the wrong class)."""
    from sklearn.metrics import matthews_corrcoef

    res = classification_metrics(y, pred, len(CLASS_LABELS))
    forced = np.where(pred < 0, 1 - y, pred)
    return {"macro_f1": res["macro_f1"], "accuracy": res["accuracy"], "balanced_accuracy": res["balanced_accuracy"],
            "share_unknown": res["share_unknown"], "mcc": float(matthews_corrcoef(y, forced)), "n": res["n"]}


def _one_thread() -> None:
    """Pool initializer: one BLAS/OpenMP thread per worker (several threaded workers slow a fit about 40-fold)."""
    from threadpoolctl import threadpool_limits

    threadpool_limits(1)


def _fit_score(shape: Shape, base: dict, fit: pd.DataFrame, held: pd.DataFrame, features: list[str],
               seed: int) -> dict:
    t0 = time.time()
    model = FuzzyClassifier(shape.params(base), {f: UNIT for f in features})
    model.fit(fit[features], fit["y"].to_numpy(), CLASS_LABELS, seed=seed)
    out = scores(held["y"].to_numpy(), model.predict(held[features]))
    out.update(n_rules=len(list(model.rule_base.get_rules())), seconds=round(time.time() - t0, 1),
               generations=model.fit_info["n_generations_run"])
    return out


# ---------------------------------------------------------------------------------------------------- select


def select(config: FnirsConfig) -> dict:
    frame = load_table(_resolve(config.table))
    features = feature_columns(frame)
    train = frame[~frame["subject"].isin(config.test_subjects)]  # test subjects are never read below
    folds = subject_folds(sorted(train["subject"].unique().tolist()), config.n_folds, config.fold_seed)
    shapes = config.shapes()
    jobs = [(s, k, seed) for s in shapes for k in range(len(folds)) for seed in config.selection_seeds]
    _log(f"select: {len(shapes)} shapes x {len(folds)} folds x {len(config.selection_seeds)} seeds = {len(jobs)} fits")
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=config.workers, initializer=_one_thread) as pool:
        futures = {}
        for shape, k, seed in jobs:
            held = train["subject"].isin(folds[k])
            futures[pool.submit(_fit_score, shape, config.base, train[~held], train[held], features, seed)] = (
                shape, k, seed)
        for done, fut in enumerate(as_completed(futures), start=1):
            shape, k, seed = futures[fut]
            row = {"shape": shape.key, "fold": k, "seed": seed, **fut.result()}
            results.append(row)
            print(f"[{done}/{len(jobs)}] {shape.key} fold={k} seed={seed} macro_f1={row['macro_f1']:.3f} "
                  f"mcc={row['mcc']:.3f} rules={row['n_rules']}", flush=True)
    table = pd.DataFrame(results)
    summary = (table.groupby("shape")
               .agg(macro_f1=("macro_f1", "mean"), macro_f1_sd=("macro_f1", "std"), mcc=("mcc", "mean"),
                    accuracy=("accuracy", "mean"), share_unknown=("share_unknown", "mean"),
                    n_rules=("n_rules", "mean"), n=("macro_f1", "size"))
               .sort_values(["macro_f1", "n_rules"], ascending=[False, True]))
    chosen = summary.index[0]
    baselines = []
    for k, fold in enumerate(folds):  # same folds, test subjects still unread
        held = train["subject"].isin(fold)
        for name, estimator in _baselines(features, seed=0).items():
            estimator.fit(train.loc[~held, features].to_numpy(float), train.loc[~held, "y"].to_numpy())
            pred = estimator.predict(train.loc[held, features].to_numpy(float)).astype(int)
            baselines.append({"estimator": name, "fold": k, **scores(train.loc[held, "y"].to_numpy(), pred)})
    baseline_summary = (pd.DataFrame(baselines).groupby("estimator")
                        .agg(macro_f1=("macro_f1", "mean"), macro_f1_sd=("macro_f1", "std"), mcc=("mcc", "mean"),
                             accuracy=("accuracy", "mean")).sort_values("macro_f1", ascending=False))
    _log("baselines (validation): " + ", ".join(f"{n} {r.macro_f1:.3f}" for n, r in baseline_summary.iterrows()))
    report = {
        "experiment_id": config.experiment_id, "stage": "select", "exfuzzy_version": exfuzzy_version(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "folds": folds, "test_subjects_read": False, "criterion": "largest mean validation macro-F1",
        "chosen_shape": chosen, "chosen": next(s.model_dump() for s in shapes if s.key == chosen),
        "summary": summary.reset_index().to_dict(orient="records"),
        "baselines": baseline_summary.reset_index().to_dict(orient="records"), "baseline_fits": baselines,
        "fits": results,
    }
    out = _experiments_dir(config) / f"{config.experiment_id}-select.json"
    out.write_text(json.dumps(report, indent=2, default=float))
    _log(f"chosen {chosen}: macro_f1={summary.iloc[0]['macro_f1']:.3f}; wrote {out}")
    return report


# ----------------------------------------------------------------------------------------------------- final


def _baselines(features: list[str], seed: int) -> dict:
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    return {
        "majority_class": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=seed)),
        "random_forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced",
                                                n_jobs=2, random_state=seed),
        "svm_rbf": make_pipeline(StandardScaler(), SVC(C=1.0, gamma="scale", class_weight="balanced",
                                                       random_state=seed)),
    }


def final(config: FnirsConfig) -> dict:
    selection = json.loads((_experiments_dir(config) / f"{config.experiment_id}-select.json").read_text())
    shape = Shape(**selection["chosen"])
    frame = load_table(_resolve(config.table))
    features = feature_columns(frame)
    test_mask = frame["subject"].isin(config.test_subjects).to_numpy()
    train, test = frame[~test_mask], frame[test_mask]
    y_test = test["y"].to_numpy()
    rows: dict[str, dict] = {}
    n_steps = len(config.final_seeds) + 1
    _one_thread()  # the published model must not depend on the machine's thread count
    for k, seed in enumerate(config.final_seeds, start=1):
        model = FuzzyClassifier(shape.params(config.base), {f: UNIT for f in features})
        model.fit(train[features], train["y"].to_numpy(), CLASS_LABELS, seed=seed)
        pred = model.predict(test[features])
        rows[f"exfuzzy-seed{seed}"] = {**scores(y_test, pred), "n_rules": len(list(model.rule_base.get_rules())),
                                        "train": scores(train["y"].to_numpy(), model.predict(train[features]))}
        predictions = frame[["subject", "trial", "event", "y"]].assign(
            split=np.where(test_mask, "test", "train"), predicted=model.predict(frame[features]))
        run_dir = ARTIFACTS_DIR / config.task_id / f"{shape.key}-seed{seed}"
        artifacts.write_run_dir(run_dir, model=model, parity_sample=test[features], parquet_files={
            "predictions.parquet": predictions}, json_files={
            "run.json": json.dumps({
                "experiment_id": config.experiment_id, "task_id": config.task_id, "shape": shape.model_dump(),
                "params": shape.params(config.base).as_dict(), "seed": seed, "exfuzzy_version": exfuzzy_version(),
                "git": artifacts.git_state(), "python": artifacts.python_version(),
                "test_subjects": config.test_subjects, "class_labels": CLASS_LABELS, "unit": UNIT,
                "fit_info": model.fit_info, "test": rows[f"exfuzzy-seed{seed}"],
                "published": seed == config.published_seed}, indent=2, default=float)})
        print(f"[{k}/{n_steps}] exfuzzy seed={seed} test_macro_f1={rows[f'exfuzzy-seed{seed}']['macro_f1']:.3f} "
              f"test_mcc={rows[f'exfuzzy-seed{seed}']['mcc']:.3f} -> {run_dir.name}", flush=True)
    for name, estimator in _baselines(features, seed=config.published_seed).items():
        estimator.fit(train[features].to_numpy(float), train["y"].to_numpy())
        rows[name] = scores(y_test, estimator.predict(test[features].to_numpy(float)).astype(int))
    print(f"[{n_steps}/{n_steps}] baselines done", flush=True)
    fuzzy = pd.DataFrame([v for k, v in rows.items() if k.startswith("exfuzzy-")])
    report = {
        "experiment_id": config.experiment_id, "stage": "final", "exfuzzy_version": exfuzzy_version(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "shape": shape.model_dump(),
        "published_seed": config.published_seed, "test_subjects": config.test_subjects,
        "n_train": int((~test_mask).sum()), "n_test": int(test_mask.sum()),
        "test_class_counts": np.bincount(y_test, minlength=2).tolist(),
        "exfuzzy_seed_mean": fuzzy[["macro_f1", "accuracy", "mcc", "share_unknown", "n_rules"]].mean().to_dict(),
        "exfuzzy_seed_sd": fuzzy[["macro_f1", "accuracy", "mcc"]].std().to_dict(),
        "estimators": rows,
    }
    out = _experiments_dir(config) / f"{config.experiment_id}-final.json"
    out.write_text(json.dumps(report, indent=2, default=float))
    _log(f"wrote {out}")
    return report


# ----------------------------------------------------------------------------------------------------- seeds


def seeds(config: FnirsConfig) -> dict:
    """Error bars for the report: the test scores of every estimator for each final seed (ExFuzzy from ``final``; each
    baseline refitted with that seed, so the deterministic ones repeat their score) and the validation scores of each
    subject fold (``select``; ExFuzzy averaged over its GA seeds). Test is not used to choose anything here."""
    experiments = _experiments_dir(config)
    select_report = json.loads((experiments / f"{config.experiment_id}-select.json").read_text())
    final_report = json.loads((experiments / f"{config.experiment_id}-final.json").read_text())
    frame = load_table(_resolve(config.table))
    features = feature_columns(frame)
    test_mask = frame["subject"].isin(config.test_subjects).to_numpy()
    train, test = frame[~test_mask], frame[test_mask]
    keep = ("macro_f1", "accuracy", "mcc", "n")
    out: dict = {"experiment_id": config.experiment_id, "seeds": config.final_seeds, "folds": select_report["folds"],
                 "test": {"exfuzzy": {}}, "validation": {"exfuzzy": {}}}
    for seed in config.final_seeds:
        out["test"]["exfuzzy"][seed] = {k: final_report["estimators"][f"exfuzzy-seed{seed}"][k] for k in keep}
    for k, seed in enumerate(config.final_seeds, start=1):
        for name, estimator in _baselines(features, seed=seed).items():
            estimator.fit(train[features].to_numpy(float), train["y"].to_numpy())
            res = scores(test["y"].to_numpy(), estimator.predict(test[features].to_numpy(float)).astype(int))
            out["test"].setdefault(name, {})[seed] = {key: res[key] for key in keep}
        print(f"[{k}/{len(config.final_seeds)}] seed={seed} baselines refitted", flush=True)
    chosen = select_report["chosen_shape"]
    fits = pd.DataFrame([f for f in select_report["fits"] if f["shape"] == chosen])
    for fold, g in fits.groupby("fold"):
        out["validation"]["exfuzzy"][int(fold)] = {"macro_f1": g["macro_f1"].mean(), "accuracy": g["accuracy"].mean(),
                                                   "mcc": g["mcc"].mean(), "n": int(g["n"].iloc[0])}
    for f in select_report["baseline_fits"]:
        out["validation"].setdefault(f["estimator"], {})[int(f["fold"])] = {key: f[key] for key in keep}
    path = experiments / f"{config.experiment_id}-seeds.json"
    path.write_text(json.dumps(out, indent=2, default=float))
    _log(f"wrote {path}")
    return out


# ---------------------------------------------------------------------------------------------------- nested


def nested(config: FnirsConfig, workers: int | None = None) -> dict:
    """Spread over *people* for every model: subject-grouped cross-validation over all subjects (``n_folds`` outer
    groups). In each outer fold the ExFuzzy shape is chosen again by the same grid and inner subject folds on the
    other subjects (the outer group is never read for that), then every estimator is fitted on those subjects with
    each final seed and scored on the outer group. The published model (manuscript split) is not touched."""
    frame = load_table(_resolve(config.table))
    features = feature_columns(frame)
    subjects = sorted(frame["subject"].unique().tolist())
    outer = subject_folds(subjects, config.n_folds, config.fold_seed)
    shapes = config.shapes()
    inner = {k: subject_folds([s for s in subjects if s not in fold], config.n_folds, config.fold_seed)
             for k, fold in enumerate(outer)}
    jobs = [(k, shape, j, seed) for k in range(len(outer)) for shape in shapes for j in range(config.n_folds)
            for seed in config.selection_seeds]
    total = len(jobs) + len(outer) * len(config.final_seeds)
    _log(f"nested: {len(outer)} outer folds; {len(jobs)} inner fits + {len(outer) * len(config.final_seeds)} final")
    done = 0
    inner_scores: dict[tuple[int, str], list[float]] = {}
    with ProcessPoolExecutor(max_workers=workers or config.workers, initializer=_one_thread) as pool:
        futures = {}
        for k, shape, j, seed in jobs:
            rest = frame[~frame["subject"].isin(outer[k])]
            held = rest["subject"].isin(inner[k][j])
            futures[pool.submit(_fit_score, shape, config.base, rest[~held], rest[held], features, seed)] = (k, shape)
        for fut in as_completed(futures):
            k, shape = futures[fut]
            res = fut.result()
            inner_scores.setdefault((k, shape.key), []).append(res["macro_f1"])
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"[{done}/{total}] inner fold of outer {k}: {shape.key} macro_f1={res['macro_f1']:.3f}",
                      flush=True)
        chosen = {k: max(shapes, key=lambda sh: (float(np.mean(inner_scores[(k, sh.key)])), -sh.nRules))
                  for k in range(len(outer))}
        finals = {}
        for k, fold in enumerate(outer):
            train = frame[~frame["subject"].isin(fold)]
            test = frame[frame["subject"].isin(fold)]
            for seed in config.final_seeds:
                finals[pool.submit(_fit_score, chosen[k], config.base, train, test, features, seed)] = (k, seed)
        exfuzzy: dict[int, dict] = {}
        for fut in as_completed(finals):
            k, seed = finals[fut]
            exfuzzy.setdefault(k, {})[seed] = fut.result()
            done += 1
            print(f"[{done}/{total}] outer {k} seed={seed} {chosen[k].key} "
                  f"test_macro_f1={exfuzzy[k][seed]['macro_f1']:.3f}", flush=True)
    keep = ("macro_f1", "accuracy", "mcc")
    folds = []
    for k, fold in enumerate(outer):
        train = frame[~frame["subject"].isin(fold)]
        test = frame[frame["subject"].isin(fold)]
        y = test["y"].to_numpy()
        per = {"exfuzzy": {seed: {m: exfuzzy[k][seed][m] for m in keep} for seed in config.final_seeds}}
        for seed in config.final_seeds:
            for name, estimator in _baselines(features, seed=seed).items():
                estimator.fit(train[features].to_numpy(float), train["y"].to_numpy())
                res = scores(y, estimator.predict(test[features].to_numpy(float)).astype(int))
                per.setdefault(name, {})[seed] = {m: res[m] for m in keep}
        folds.append({
            "fold": k, "test_subjects": fold, "n_test": int(len(test)), "chosen_shape": chosen[k].key,
            "inner_macro_f1": float(np.mean(inner_scores[(k, chosen[k].key)])),
            "mean_over_seeds": {e: {m: float(np.mean([v[m] for v in by.values()])) for m in keep}
                                for e, by in per.items()},
            "per_seed": per,
        })
    report = {"experiment_id": config.experiment_id, "stage": "nested", "exfuzzy_version": exfuzzy_version(),
              "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "outer_folds": outer,
              "seeds": config.final_seeds, "folds": folds}
    path = _experiments_dir(config) / f"{config.experiment_id}-nested.json"
    path.write_text(json.dumps(report, indent=2, default=float))
    _log(f"wrote {path}")
    return report


# ------------------------------------------------------------------------------------------------------- cli


def _resolve(table: str) -> Path:
    path = Path(table)
    return path if path.is_absolute() else DATA_DIR / path


def _experiments_dir(config: FnirsConfig) -> Path:
    path = ARTIFACTS_DIR / config.task_id / "experiments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=["select", "final", "seeds", "nested"])
    parser.add_argument("--workers", type=int, default=None, help="processes (default: the config's)")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.stage == "nested":
        nested(config, workers=args.workers)
    else:
        {"select": select, "final": final, "seeds": seeds}[args.stage](config)


if __name__ == "__main__":
    main()
