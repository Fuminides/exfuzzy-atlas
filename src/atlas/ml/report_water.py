"""Markdown tables for ``docs/ml/water_uk_do_regression.md``, generated from the artifacts (AT-041f).

::

    python -m atlas.ml.report_water --artifacts-dir artifacts

Reads the four experiments ``water-do-{chrono,spatial}-{temp,notemp}`` under ``artifacts/uk_water_do/experiments``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from atlas.ml.report_class import _f, _md

ARMS = [("chrono", "temp"), ("chrono", "notemp"), ("spatial", "temp"), ("spatial", "notemp")]
FUZZY = "exfuzzy_tsk"
ORDER = ["global_mean", "point_mean", "season_only", "temperature_only_quadratic", "ridge", "random_forest",
         "hist_gradient_boosting", FUZZY]


def _load(root: Path, kind: str, temp: str) -> dict:
    return json.loads((root / f"water-do-{kind}-{temp}" / "summary.json").read_text())


def _estimators(summary: dict, period: str) -> dict[str, dict]:
    published = next(r for r in summary["runs"] if r["seed"] == summary["published_seed"])
    blocks = {FUZZY: published[period], **{k: v[period] for k, v in summary["baselines"].items()}}
    return {k: blocks[k] for k in ORDER if k in blocks}


def selection_table(selection: dict) -> str:
    rows = [[f["nRules"], f["nAnts"], _f(f["validation"]["mae"]), _f(f["validation"]["rmse"]),
             _f(f["validation"].get("r2")), f["n_distinct_rules"], _f(f["mean_rule_length"], 2),
             f"{f['fit_seconds']:.0f}"]
            for f in selection["fits"]]
    rows.sort(key=lambda r: float(r[3]))
    return _md(["nRules", "nAnts", "val MAE", "val RMSE", "val R2", "distinct rules", "mean length", "fit s"], rows)


def overall_table(summary: dict, period: str) -> str:
    rows = [[name, _f(b["overall"]["mae"]), _f(b["overall"]["rmse"]), _f(b["overall"].get("r2"))]
            for name, b in _estimators(summary, period).items()]
    return _md(["estimator", "MAE (mg/l)", "RMSE (mg/l)", "R2"], rows)


def comparison_table(root: Path) -> str:
    """Test MAE / RMSE / R2 of every estimator in the four arms (published seed for ExFuzzy)."""
    summaries = {(k, t): _load(root, k, t) for k, t in ARMS}
    rows = []
    for name in ORDER:
        row = [name]
        for key in ARMS:
            b = _estimators(summaries[key], "test").get(name)
            row += [_f(b["overall"]["rmse"]) + " / " + _f(b["overall"].get("r2"), 2) if b else ""]
        rows.append(row)
    return _md(["test RMSE / R2", *[f"{k}, {'with' if t == 'temp' else 'without'} temperature" for k, t in ARMS]], rows)


def slice_table(summary: dict, period: str, name: str) -> str:
    est = _estimators(summary, period)
    first = next(iter(est.values()))["slices"].get(name)
    if first is None:
        return ""
    header = ["estimator", *[f"{v} (n={first[v]['n']}) RMSE" for v in first]]
    rows = [[n, *[_f(b["slices"][name][v]["rmse"]) for v in first]] for n, b in est.items()]
    return _md(header, rows)


def seeds_table(summary: dict) -> str:
    rows = []
    for period in ("validation", "test"):
        vals = np.array([[r[period]["overall"][k] for k in ("mae", "rmse", "r2")] for r in summary["runs"]])
        rows.append([period, *[f"{vals[:, i].mean():.3f} +- {vals[:, i].std(ddof=1):.3f}" for i in range(3)],
                     ", ".join(f"{v:.3f}" for v in vals[:, 1])])
    return _md(["period", "MAE", "RMSE", "R2", "RMSE by seed"], rows)


def partitions_table(summary: dict) -> str:
    rows = []
    run = next(r for r in summary["runs"] if r["seed"] == summary["published_seed"])
    for feature, terms in run["partitions"].items():
        for term, p in terms.items():
            rows.append([feature, term, "[" + ", ".join(f"{v:.4g}" for v in p) + "]"])
    return _md(["variable", "term", "trapezoid [a, b, c, d]"], rows)


def rules_table(run_dir: Path) -> str:
    doc = json.loads((run_dir / "rules.json").read_text())
    rows = [[r["rule_id"], r["text"], "yes" if r.get("duplicate_of") else ""] for r in doc["rules"]]
    return _md(["rule", "text", "duplicate antecedents"], rows)


def readability(summary: dict, root: Path) -> str:
    rows = []
    for run in summary["runs"]:
        rule_dir = Path(run["run_dir"]) if "run_dir" in run else None
        consequents = []
        if rule_dir and rule_dir.exists():
            doc = json.loads((rule_dir / "rules.json").read_text())
            consequents = [float(r["consequent"]["value"]) for r in doc["rules"]]
        sigs = [tuple(map(tuple, s)) for s in run["rules"]]
        rows.append([run["seed"], len(sigs), len(set(sigs)), len(sigs) - len(set(sigs)),
                     _f(np.mean([len(s) for s in sigs]), 2),
                     (f"{min(consequents):.2f} .. {max(consequents):.2f}" if consequents else "n/a"),
                     (f"{sum(c < 0 for c in consequents)}" if consequents else "n/a")])
    return _md(["seed", "rules", "distinct antecedent sets", "duplicates", "mean length", "consequent range",
                "negative consequents"], rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report_water", description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.artifacts_dir / "uk_water_do" / "experiments"
    print("## Comparison on test (published seed of each arm)\n\n" + comparison_table(root))
    for kind, temp in ARMS:
        exp = root / f"water-do-{kind}-{temp}"
        summary = json.loads((exp / "summary.json").read_text())
        title = f"{kind}, {'with' if temp == 'temp' else 'without'} temperature"
        print(f"\n# {title}\n")
        print(f"rows: {summary['n_complete_rows']}, chosen shape {summary['chosen_shape']}, "
              f"published seed {summary['published_seed']}\n")
        selection = json.loads((exp / "selection.json").read_text())
        print("**Selection (seed 0, validation)**\n\n" + selection_table(selection))
        print("\n**Seeds**\n\n" + seeds_table(summary))
        for period in ("validation", "test"):
            print(f"\n**{period}**\n\n" + overall_table(summary, period))
        for name in ("season", "low_do", "point_in_train"):
            t = slice_table(summary, "test", name)
            if t:
                print(f"\n**test RMSE by {name}**\n\n" + t)
        print("\n**Readability by seed**\n\n" + readability(summary, root))
        print("\n**Linguistic terms of the published seed**\n\n" + partitions_table(summary))
        run = next(r for r in summary["runs"] if r["seed"] == summary["published_seed"])
        if "run_dir" in run:
            run_dir = Path(run["run_dir"])
            print(f"\n**Rules of the published seed ({run_dir.name})**\n\n" + rules_table(run_dir))
        print("\n```json\n" + json.dumps({k: v for k, v in summary["rule_stability"].items()
                                          if k != "feature_usage"}, indent=1) + "\n```")


if __name__ == "__main__":
    main()
