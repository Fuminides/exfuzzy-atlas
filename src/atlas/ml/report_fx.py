"""Markdown tables of the FX retrain (``docs/ml/fx_retrain_with_fixed_exfuzzy.md``), generated from the artifacts.

::

    python -m atlas.ml.report_fx madrid --arm base=ica2-justified --arm h5_fix=fx-m5-fix ...
    python -m atlas.ml.report_fx nyc    --arm h4=level-rel7 --arm h5_fix=fx-n5-fix ...
    python -m atlas.ml.report_fx water  --arm base=configs/ml/fx_water_do_chrono_temp_base_experiment.json ...

``--arm NAME=EXPERIMENT_ID`` reads ``<artifacts>/<task>/experiments/<id>/summary_validation.json`` (or ``summary.json``
when there is no validation-only file); for ``water`` the value is the experiment config, whose training rows are
needed for the consequent-support check. Means are over the seeds, standard deviations use n - 1. Every table is
validation; a test period appears only in the arm that the decision rule of the document sends to it.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

from atlas.explain.classifier import feature_names as classifier_feature_names
from atlas.explain.classifier import get_master_rulebase, rule_classes, rule_weights
from atlas.ml.fx_checks import classifier_term_usage
from atlas.ml.report_class import _f, _md
from atlas.paths import ARTIFACTS_DIR

TASKS = {"madrid": "madrid_no2_h6", "nyc": "nyc_pickups_h1", "water": "uk_water_do"}


def mean_sd(values) -> tuple[float, float]:
    v = np.asarray(list(values), dtype=float)
    return float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0


def pm(values, digits: int = 3) -> str:
    mean, sd = mean_sd(values)
    return f"{mean:.{digits}f} ± {sd:.{digits}f}"


def load_summary(artifacts_dir: Path, task: str, experiment_id: str) -> dict:
    root = Path(artifacts_dir) / TASKS[task] / "experiments" / experiment_id
    for name in ("summary_validation.json", "summary.json"):
        if (root / name).exists():
            return json.loads((root / name).read_text())
    raise FileNotFoundError(f"no summary in {root}")


def validation_block(run: dict) -> dict:
    """Madrid summaries hold the metrics directly, NYC ones under ``overall``."""
    v = run["validation"]
    return v["overall"] if "overall" in v else v


def classifier_row(name: str, summary: dict, classes: tuple[str, ...] = ()) -> list:
    """One row: macro-F1, balanced accuracy, accuracy, recall and precision of ``classes``, rules, Jaccard."""
    blocks = [validation_block(r) for r in summary["runs"]]
    row = [name, pm([b["macro_f1"] for b in blocks]), pm([b["balanced_accuracy"] for b in blocks]),
           pm([b["accuracy"] for b in blocks])]
    for label in classes:
        row += [pm([b["recall"][label] for b in blocks]), pm([b["precision"][label] for b in blocks])]
    row += [f"{np.mean([r['n_rules'] for r in summary['runs']]):.1f}",
            _f(summary["rule_stability"]["mean_pairwise_jaccard_rule"]),
            ", ".join(f"{b['macro_f1']:.3f}" for b in blocks)]
    return row


def classifier_table(arms: dict[str, dict], classes: tuple[str, ...] = ()) -> str:
    head = ["arm", "macro-F1", "bal-acc", "acc"]
    for label in classes:
        head += [f"{label} recall", f"{label} prec"]
    head += ["rules", "Jaccard", "macro-F1 by seed"]
    return _md(head, [classifier_row(n, s, classes) for n, s in arms.items()])


def term_usage_counts(artifacts_dir: Path, task: str, experiment_id: str, features: list[str]) -> dict:
    """``{feature: {term: [antecedents in seed 0, seed 1, ...]}}`` of the models in ``models/seed*.pkl``."""
    root = Path(artifacts_dir) / TASKS[task] / "experiments" / experiment_id / "models"
    totals: dict[str, dict[str, list[int]]] = {}
    for path in sorted(root.glob("seed*.pkl")):
        with open(path, "rb") as fh:
            model = pickle.load(fh)  # noqa: S301 - written by the experiment
        for feature, terms in classifier_term_usage(model).items():
            if feature in features:
                for term, count in terms.items():
                    totals.setdefault(feature, {}).setdefault(term, []).append(count)
    return totals


def term_usage_table(artifacts_dir: Path, task: str, experiment_id: str, features: list[str]) -> str:
    """Antecedents per term of ``features`` over the seeds' models (``models/seed*.pkl``)."""
    totals = term_usage_counts(artifacts_dir, task, experiment_id, features)
    rows = [[feature, i, term, "/".join(map(str, counts)), sum(counts)]
            for feature, terms in totals.items() for i, (term, counts) in enumerate(terms.items())]
    return _md(["feature", "term index", "term", "antecedents per seed", "total"], rows)


def usage_comparison_table(usages: dict[str, dict], features: list[str]) -> str:
    """One row per (feature, term), one column per arm: antecedents summed over the seeds (arms share the terms)."""
    first = next(iter(usages.values()))
    rows = []
    for feature in features:
        for i, term in enumerate(first.get(feature, {})):
            rows.append([feature, i, term] + [sum(u[feature][term]) if term in u.get(feature, {}) else "-"
                                                for u in usages.values()])
    return _md(["feature", "term index", "term", *usages], rows)


def classifier_rule_texts(model, class_labels: list[str], target_label: str) -> list[str]:
    """``IF f IS term AND ... THEN target = class (peso w)`` per rule, features in input order, rules by class."""
    rb = get_master_rulebase(model)
    names = classifier_feature_names(rb)
    terms = [v.linguistic_variable_names() for v in rb.antecedents]
    weights = rule_weights(rb)
    out = []
    for rule, cls, weight in zip(rb.get_rules(), rule_classes(rb), weights, strict=True):
        ants = " AND ".join(f"{names[f]} IS {terms[f][int(t)]}" for f, t in enumerate(rule.antecedents) if t >= 0)
        out.append(f"IF {ants} THEN {target_label} = {class_labels[cls]} (peso {float(weight):.3g})")
    return out


def best_seed_model(artifacts_dir: Path, task: str, experiment_id: str, summary: dict):
    """The unpickled model of the seed with the highest validation macro-F1 (the seed that would be published)."""
    best = max(summary["runs"], key=lambda r: validation_block(r)["macro_f1"])
    path = Path(artifacts_dir) / TASKS[task] / "experiments" / experiment_id / "models" / f"seed{best['seed']}.pkl"
    with open(path, "rb") as fh:
        return best["seed"], pickle.load(fh)  # noqa: S301 - written by the experiment


def usage_of_features(summary: dict, features: list[str]) -> list[int]:
    """Per seed: number of rules with an antecedent on any of ``features``."""
    return [sum(any(f in features for f, _ in rule["antecedents"]) for rule in run["rules"])
            for run in summary["runs"]]


def water_row(name: str, summary: dict, support: dict[int, list[dict]]) -> list:
    """RMSE / MAE / R2 and readability of the rule sets; ``support`` is ``consequent_support`` per seed."""
    runs = summary["runs"]
    metric = lambda key: [r["validation"]["overall"][key] for r in runs]  # noqa: E731
    n_rules = [len(r["rules"]) for r in runs]
    distinct = [len({tuple(map(tuple, rule)) for rule in r["rules"]}) for r in runs]
    outside = [sum(s["status"] == "outside" for s in support[r["seed"]]) for r in runs]
    no_support = [sum(s["status"] == "no_support" for s in support[r["seed"]]) for r in runs]
    return [name, pm(metric("rmse")), pm(metric("mae")), pm(metric("r2")), "/".join(map(str, n_rules)),
            "/".join(map(str, distinct)), "/".join(str(a - b) for a, b in zip(n_rules, distinct, strict=True)),
            "/".join(map(str, outside)), "/".join(map(str, no_support)),
            ", ".join(f"{r['validation_rmse']:.3f}" for r in runs)]


WATER_HEAD = ["arm", "val RMSE", "val MAE", "val R2", "rules", "distinct antecedent sets", "duplicates",
              "consequent outside covered range", "no support", "RMSE by seed"]


def water_support(config_path: Path, artifacts_dir: Path) -> tuple[dict, dict[int, list[dict]], dict[int, list[str]]]:
    """``(summary, consequent_support per seed, single-antecedent season rules per seed)`` of a water experiment."""
    from atlas.ml.experiment_water import WaterConfig, WaterData, experiment_dir
    from atlas.ml.fx_checks import consequent_support

    config = WaterConfig.model_validate_json(Path(config_path).read_text())
    summary = load_summary(artifacts_dir, "water", config.experiment_id)
    wd, base = WaterData(config), config.base
    X = wd.frame.loc[wd.train_pos, base.features].to_numpy(dtype=float)
    y = wd.y[wd.train_pos]
    support, season = {}, {}
    for run in summary["runs"]:
        with open(experiment_dir(config, artifacts_dir) / f"seed{run['seed']}.pkl", "rb") as fh:
            model = pickle.load(fh)  # noqa: S301 - written by the experiment
        rulebase = model.get_rulebase()
        support[run["seed"]] = consequent_support(rulebase, X, y)
        names = [v.name for v in rulebase.antecedents]
        terms = [v.linguistic_variable_names() for v in rulebase.antecedents]
        season[run["seed"]] = [
            f"{names[f]} IS {terms[f][t]} -> {c:.3f}"
            for rule, c in zip(rulebase.rules, rulebase.scalar_consequents, strict=True)
            for f, t in enumerate(rule.antecedents)
            if t >= 0 and names[f] == "days_from_midwinter" and sum(a >= 0 for a in rule.antecedents) == 1]
    return summary, support, season


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report_fx", description=__doc__.split("\n\n")[0])
    parser.add_argument("task", choices=list(TASKS))
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=EXPERIMENT_ID", required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--usage", nargs="*", default=[], help="classifier tasks: features whose term usage to print")
    parser.add_argument("--compare-usage", action="store_true",
                        help="with --usage: one table of the antecedents per term, summed over the seeds, per arm "
                             "(arms must share the terms of the features)")
    parser.add_argument("--rules", action="store_true", help="classifier tasks: the rules of each arm's best seed")
    args = parser.parse_args(argv)
    if args.task == "water":
        rows, lines = [], []
        for spec in args.arm:
            name, _, config_path = spec.partition("=")
            summary, support, season = water_support(Path(config_path), args.artifacts_dir)
            rows.append(water_row(name, summary, support))
            lines += [f"* {name}, seed {seed}: " + ("; ".join(rules) or "no single-condition season rule")
                      for seed, rules in season.items()]
        print(_md(WATER_HEAD, rows) + "\n\nSingle-condition season rules:\n\n" + "\n".join(lines))
        return
    arms = {}
    for spec in args.arm:
        name, _, experiment_id = spec.partition("=")
        arms[name] = (experiment_id, load_summary(args.artifacts_dir, args.task, experiment_id))
    classes = ("Regular", "Desfavorable o peor") if args.task == "madrid" else ()
    print(classifier_table({n: s for n, (_, s) in arms.items()}, classes))
    for name, (experiment_id, summary) in arms.items():
        if args.usage:
            print(f"\n**Term usage, {name}**\n\n" + term_usage_table(args.artifacts_dir, args.task, experiment_id,
                                                                   args.usage))
            print(f"\nrules with an antecedent on {args.usage}, per seed: {usage_of_features(summary, args.usage)}")
        if args.rules:
            seed, model = best_seed_model(args.artifacts_dir, args.task, experiment_id, summary)
            target = "ICA" if args.task == "madrid" else "nivel"
            print(f"\n**Rules of {name}, seed {seed} (best validation macro-F1)**\n")
            print("\n".join(f"* {t}" for t in classifier_rule_texts(model, model.class_labels, target)))
    if args.usage and args.compare_usage:
        usages = {name: term_usage_counts(args.artifacts_dir, args.task, experiment_id, args.usage)
                  for name, (experiment_id, _) in arms.items()}
        print("\n**Antecedents per term, summed over the seeds**\n\n" + usage_comparison_table(usages, args.usage))


if __name__ == "__main__":
    main()
