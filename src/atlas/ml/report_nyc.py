"""Markdown tables for ``docs/ml/nyc_pickups_h1_level_ica.md``, generated from the artifacts (AT-041e).

::

    python -m atlas.ml.report_nyc --experiment artifacts/nyc_pickups_h1/experiments/level-rel7 \\
        --other artifacts/nyc_pickups_h1/experiments/level-all12

Every number of the write-up comes from ``class_distribution.json``, ``selection.json``, ``summary.json`` and the
run directories of the published seed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from atlas.ml.experiment_class import FUZZY_CLASSIFIER
from atlas.ml.report_class import _f, _md

ORDER = ["persistence", "persistence_rel_lag24", "persistence_rel_lag168", "majority_class", "logistic_regression",
         "logistic_regression_balanced", "random_forest", "random_forest_balanced", "hist_gradient_boosting",
         "hist_gradient_boosting_balanced", "logistic_regression_subsample", "random_forest_subsample",
         "hist_gradient_boosting_subsample", FUZZY_CLASSIFIER]


def _estimators(summary: dict, period: str) -> dict[str, dict]:
    """``name -> block`` for the published seed and every baseline."""
    published = next(r for r in summary["runs"] if r["seed"] == summary["published_seed"])
    blocks = {FUZZY_CLASSIFIER: published[period], **{k: v[period] for k, v in summary["baselines"].items()}}
    return {k: blocks[k] for k in ORDER if k in blocks}


def distribution_tables(dist: dict) -> str:
    labels = dist["labels"]
    rows = []
    for period, info in dist["periods"].items():
        rows.append([period, info["n_complete"], info["n_target_known_without_label"]] +
                    [f"{100 * info['share'][lab]:.1f} %" for lab in labels])
    out = ["**Complete rows (label and the 12 inputs) and rows without a reference level**\n\n" +
           _md(["period", "n complete", "target known, no label", *labels], rows)]
    for key, title in (("by_group", "volume group"), ("by_month", "local month")):
        rows = []
        for period, info in dist["periods"].items():
            for v, e in info[key].items():
                rows.append([period, v, e["n"]] + [f"{100 * e['share'][lab]:.1f}" for lab in labels])
        out.append(f"**Class shares (%) by {title}**\n\n" + _md(["period", title, "n", *labels], rows))
    return "\n\n".join(out)


def selection_table(selection: dict) -> str:
    rows = []
    for f in selection["fits"]:
        c, v = f["candidate"], f["validation"]
        rows.append([c["nRules"], c["nAnts"], f["n_rules"], _f(v["macro_f1"]), _f(v["balanced_accuracy"]),
                     _f(v["accuracy"]), _f(v["mae_class_index"]), _f(v["share_unknown"]), f"{f['fit_seconds']:.0f}"])
    rows.sort(key=lambda r: -float(r[3]))
    return _md(["nRules", "nAnts", "rules kept", "val macro-F1", "val bal-acc", "val acc", "val MAE idx", "unknown",
                "fit s"], rows)


def overall_table(summary: dict, period: str) -> str:
    rows = []
    for name, b in _estimators(summary, period).items():
        o = b["overall"]
        rows.append([name, _f(o["macro_f1"]), _f(o["balanced_accuracy"]), _f(o["accuracy"]), _f(o["mae_class_index"]),
                     _f(o["share_off_by_2plus"]), _f(o["share_unknown"])])
    return _md(["estimator", "macro_f1", "balanced_accuracy", "accuracy", "mae_class_index", "off_by_2plus", "unknown"],
               rows)


def per_class_table(summary: dict, period: str, which: str) -> str:
    labels = summary["labels"]
    rows = [[name, *[_f(b["overall"][which][lab]) for lab in labels]]
            for name, b in _estimators(summary, period).items()]
    return _md(["estimator", *labels], rows)


def slice_table(summary: dict, period: str, key: str, metric: str) -> str:
    est = _estimators(summary, period)
    first = next(iter(est.values()))[key]
    header = ["estimator", *[f"{v} (n={first[v]['n']})" for v in first]]
    rows = [[name, *[_f(b[key][v][metric]) for v in first]] for name, b in est.items()]
    return _md(header, rows)


def share_tables(summary: dict, period: str, names: list[str]) -> str:
    est = _estimators(summary, period)
    out = []
    for month, shares in next(iter(est.values()))["shares_by_month"].items():
        if month == "labels":
            continue
        labels = est[FUZZY_CLASSIFIER]["shares_by_month"]["labels"]
        rows = [["observed", *[f"{100 * s:.1f}" for s in shares["observed"]], ""]]
        for name in (n for n in names if n in est):
            rows.append([name, *[f"{100 * s:.1f}" for s in est[name]["shares_by_month"][month]["predicted"]]])
        out.append(f"**{period} {month}: share of rows (%) by class, observed and predicted**\n\n" +
                   _md(["", *labels], rows))
    return "\n\n".join(out)


def seeds_table(summary: dict) -> str:
    rows = []
    for period in ("validation", "test"):
        vals = np.array([[r[period]["overall"][k] for k in ("macro_f1", "balanced_accuracy", "accuracy")]
                         for r in summary["runs"]])
        rows.append([period, *[f"{vals[:, i].mean():.3f} +- {vals[:, i].std(ddof=1):.3f}" for i in range(3)],
                     ", ".join(f"{v:.3f}" for v in vals[:, 0])])
    return _md(["period", "macro_f1", "balanced_accuracy", "accuracy", "macro_f1 by seed"], rows)


def rules_table(run_dir: Path) -> str:
    rules = json.loads((run_dir / "rules.json").read_text())["rules"]
    metrics = json.loads((run_dir / "metrics.json").read_text())["rows"]
    win = {r["slice"].split("=", 1)[1]: r["value"] for r in metrics
           if r["estimator"] == FUZZY_CLASSIFIER and r["metric"] == "rule_win_share" and r["slice"].startswith("rule=")}
    rows = [[r["rule_id"], r["text"], _f(win.get(r["rule_id"]))] for r in rules]
    rows.sort(key=lambda r: -float(r[2] or 0))
    return _md(["rule", "text", "share of test rows it decides"], rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report_nyc", description=__doc__.split("\n\n")[0])
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--other", type=Path, default=None, help="the other feature-set arm (selection only)")
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    exp = args.experiment
    summary = json.loads((exp / "summary.json").read_text())
    print("## Class distribution\n\n" + distribution_tables(json.loads((exp / "class_distribution.json").read_text())))
    for path in [exp, *([args.other] if args.other else [])]:
        print(f"\n## Selection {path.name} (seed 0, validation)\n\n" +
              selection_table(json.loads((path / "selection.json").read_text())))
    print("\n## Seeds of the final shape\n\n" + seeds_table(summary))
    for period in ("validation", "test"):
        print(f"\n## {period}: overall\n\n" + overall_table(summary, period))
    print("\n## test: per-class recall\n\n" + per_class_table(summary, "test", "recall"))
    print("\n## test: per-class precision\n\n" + per_class_table(summary, "test", "precision"))
    for period in ("validation", "test"):
        for key in ("by_group", "by_month"):
            for metric in ("macro_f1", "balanced_accuracy", "accuracy"):
                print(f"\n## {period}: {metric} {key}\n\n" + slice_table(summary, period, key, metric))
    names = [FUZZY_CLASSIFIER, "persistence", "hist_gradient_boosting", "random_forest"]
    print("\n## Predicted and observed shares\n\n" + share_tables(summary, "test", names))
    print("\n" + share_tables(summary, "validation", names))
    run_dir = exp.parent.parent / f"{summary['experiment_id']}-seed{summary['published_seed']}"
    if run_dir.exists():
        print(f"\n## Rules of the published seed ({run_dir.name})\n\n" + rules_table(run_dir))
    print("\n## Rule stability across seeds\n\n```json\n" + json.dumps(
        {k: v for k, v in summary["rule_stability"].items() if k != "feature_usage"}, indent=1) + "\n```")


if __name__ == "__main__":
    main()
