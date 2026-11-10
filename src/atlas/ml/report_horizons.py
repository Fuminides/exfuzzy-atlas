"""Markdown tables of ``docs/ml/horizons.md``, generated from the experiment summaries (AT-080).

::

    python -m atlas.ml.report_horizons [--territory madrid|de|nyc] [--timings <dir>]

One model per forecast horizon, each fitted with the protocol of its published h6 / h1 model. Every number comes from
``experiments/<id>/summary.json`` and ``class_distribution.json`` (written by ``atlas.ml.experiment_class`` and
``atlas.ml.experiment_nyc``); the costs come from the ``<label>-<stage>.time`` files of ``--timings``
(``/usr/bin/time -f "wall_s=%e peak_rss_kb=%M exit=%x"``). The standard deviation is the sample one (ddof 1) over the
three seeds.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from atlas.paths import ARTIFACTS_DIR

TREE_BASELINES = ("hist_gradient_boosting", "hist_gradient_boosting_balanced", "random_forest",
                  "random_forest_balanced", "hist_gradient_boosting_subsample", "random_forest_subsample",
                  "random_forest_balanced_subsample")
CLIMATOLOGY = ("climatology_majority_class", "majority_class")  # Madrid / Germany; NYC has the majority class only
TERRITORIES = {
    "madrid": {"title": "Madrid (ICA NO2)", "experiment": "ica2-justified", "label": "madrid", "tasks": {
        1: "madrid_no2_h1", 3: "madrid_no2_h3", 6: "madrid_no2_h6", 12: "madrid_no2_h12", 24: "madrid_no2_h24"}},
    "de": {"title": "Germany (EAQI NO2)", "experiment": "eaqi-justified", "label": "de", "tasks": {
        1: "de_no2_h1", 3: "de_no2_h3", 6: "de_no2_h6", 12: "de_no2_h12", 24: "de_no2_h24"}},
    "nyc": {"title": "New York (yellow-taxi demand level)", "experiment": "level-rel7", "label": "nyc", "tasks": {
        1: "nyc_pickups_h1", 3: "nyc_pickups_h3", 6: "nyc_pickups_h6", 24: "nyc_pickups_h24"}},
}


def _md(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _f(v, digits=3) -> str:
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{digits}f}"


def _pm(values: list[float]) -> str:
    return f"{np.mean(values):.3f} ± {np.std(values, ddof=1):.3f}"


def overall(metrics: dict) -> dict:
    """The overall metrics of a period (NYC nests them under ``overall``, next to the slices by group and month)."""
    return metrics["overall"] if "overall" in metrics else metrics


def f1_by_class(metrics: dict, labels: list[str]) -> list[float]:
    p, r = overall(metrics)["precision"], overall(metrics)["recall"]
    return [0.0 if p[k] + r[k] == 0 else 2 * p[k] * r[k] / (p[k] + r[k]) for k in labels]


def load(artifacts: Path, task: str, experiment: str) -> dict:
    base = artifacts / task / "experiments" / experiment
    return {"summary": json.loads((base / "summary.json").read_text()),
            "dist": json.loads((base / "class_distribution.json").read_text())}


def best_tree(baselines: dict) -> str:
    """The tree baseline with the highest validation macro-F1 (the test is not used to choose it)."""
    names = [n for n in TREE_BASELINES if n in baselines]
    return max(names, key=lambda n: overall(baselines[n]["validation"])["macro_f1"])


def rows_table(data: dict[int, dict], labels: list[str]) -> str:
    """Complete rows and class shares per period; ``class_distribution.json`` has two layouts (ICA / EAQI and NYC)."""
    rows = []
    for h, d in data.items():
        for period in ("train", "validation", "test"):
            info = d["dist"]["periods"][period]
            n, share = (info["n"], info["used_share"]) if "used_share" in info else (info["n_complete"], info["share"])
            rows.append([f"t+{h} h", period, f"{n:,}", *[f"{100 * share[k]:.2f} %" for k in labels]])
    return _md(["horizon", "period", "complete rows", *labels], rows)


def shape_table(data: dict[int, dict]) -> str:
    rows = []
    for h, d in data.items():
        s, c = d["summary"], d["summary"]["chosen"]
        n_rules = [r["n_rules"] for r in s["runs"]]
        rows.append([f"t+{h} h", c["nRules"], c["nAnts"], c["n_linguistic_variables"], c["sampling_power"],
                     n_rules[0], f"{np.mean(n_rules):.1f} ({min(n_rules)}-{max(n_rules)})",
                     f"{np.mean([r['fit_seconds'] for r in s['runs']]):.0f}", s["published_seed"],
                     _f(overall(s["runs"][s["published_seed"]]["test"])["macro_f1"]),
                     _f(s["rule_stability"]["mean_pairwise_jaccard_rule"])])
    return _md(["horizon", "nRules (cap)", "nAnts", "terms", "sampling power", "rules, seed 0", "rules, mean (range)",
                "fit s per seed", "published seed (highest validation macro-F1)", "test macro-F1 of that seed",
                "rule overlap between seeds (mean pairwise Jaccard)"], rows)


def metric_table(data: dict[int, dict], metric: str, split: str) -> str:
    rows = []
    for h, d in data.items():
        s = d["summary"]
        base = s["baselines"]
        tree = best_tree(base)
        clim = next(k for k in CLIMATOLOGY if k in base)
        seeds = [overall(r[split])[metric] for r in s["runs"]]
        pers = overall(base["persistence"][split])[metric]
        rows.append([f"t+{h} h", _f(seeds[0]), _pm(seeds), _f(pers), _f(overall(base[clim][split])[metric]),
                     _f(overall(base[tree][split])[metric]), f"{np.mean(seeds) - pers:+.3f}", tree])
    return _md(["horizon", "ExFuzzy seed 0", "ExFuzzy mean ± sd", "persistence", "climatology / majority class",
                "best tree baseline", "ExFuzzy mean − persistence", "best tree (chosen on validation)"], rows)


def class_table(data: dict[int, dict], labels: list[str], split: str) -> str:
    rows = []
    for h, d in data.items():
        s = d["summary"]
        per_seed = np.array([f1_by_class(r[split], labels) for r in s["runs"]])
        pers = f1_by_class(s["baselines"]["persistence"][split], labels)
        rows.append([f"t+{h} h", "ExFuzzy seed 0", *[_f(x) for x in per_seed[0]]])
        rows.append(["", "ExFuzzy mean ± sd", *[f"{m:.3f} ± {sd:.3f}" for m, sd in
                                              zip(per_seed.mean(0), per_seed.std(0, ddof=1), strict=True)]])
        rows.append(["", "persistence", *[_f(x) for x in pers]])
    return _md(["horizon", "model", *labels], rows)


def timing_table(label: str, horizons: list[int], timings: Path, extra: tuple[str, ...] = ()) -> str:
    rows = []
    for h in horizons:
        cells = [f"t+{h} h"]
        for stage in ("tbl", "select", "final", "runs"):
            stems = {"tbl": [f"tbl-{label}-h{h}", f"tbl-{label}lv-h{h}"], "select": [f"{label}-h{h}-select"],
                     "final": [f"{label}-h{h}-final"], "runs": [f"{label}-h{h}-runs"]}[stage]
            parts = []
            for stem in stems:
                path = timings / f"{stem}.time"
                if path.exists():
                    m = re.search(r"wall_s=([\d.]+) peak_rss_kb=(\d+)", path.read_text())
                    if m:
                        parts.append((float(m[1]), int(m[2]) / 1024 / 1024))
            cells.append("n/a" if not parts else f"{sum(p[0] for p in parts):.0f} s, {max(p[1] for p in parts):.1f} GB")
        rows.append(cells)
    return _md(["horizon", "feature table", "select (validation)", "final (3 seeds + baselines + test)",
                "run directories"], rows)


def reading(d_val: float, d_test: float, sd_test: float) -> str:
    """"above" / "below" persistence when the validation and test gaps have the same sign and the test gap exceeds the
    seed sd; otherwise "no clear difference". A rule of thumb for three seeds, not a significance test."""
    if d_val > 0 and d_test > sd_test:
        return "above"
    if d_val < 0 and -d_test > sd_test:
        return "below"
    return "no clear difference"


def summary_table(artifacts: Path, territories: list[str]) -> str:
    """Test macro-F1 of the three-seed mean against persistence, all horizons of all territories in one table."""
    rows = []
    for territory in territories:
        t = TERRITORIES[territory]
        for h, task in t["tasks"].items():
            if not (artifacts / task / "experiments" / t["experiment"] / "summary.json").exists():
                continue
            s = load(artifacts, task, t["experiment"])["summary"]
            val = [overall(r["validation"])["macro_f1"] for r in s["runs"]]
            test = [overall(r["test"])["macro_f1"] for r in s["runs"]]
            pv = overall(s["baselines"]["persistence"]["validation"])["macro_f1"]
            pt = overall(s["baselines"]["persistence"]["test"])["macro_f1"]
            tree = overall(s["baselines"][best_tree(s["baselines"])]["test"])["macro_f1"]
            clim = overall(s["baselines"][next(k for k in CLIMATOLOGY if k in s["baselines"])]["test"])["macro_f1"]
            sd = float(np.std(test, ddof=1))
            rows.append([t["title"].split(" (")[0], f"t+{h} h", _pm(test), _f(pt), _f(clim), _f(tree),
                         f"{np.mean(val) - pv:+.3f}", f"{np.mean(test) - pt:+.3f}", f"{sd:.3f}",
                         reading(np.mean(val) - pv, np.mean(test) - pt, sd)])
    return _md(["territory", "horizon", "test macro-F1, ExFuzzy mean ± sd", "persistence",
                "climatology / majority class", "best tree baseline", "validation gap to persistence",
                "test gap to persistence", "seed sd (test)", "reading"], rows)


def render(territory: str, artifacts: Path, timings: Path | None) -> str:
    t = TERRITORIES[territory]
    data = {h: load(artifacts, task, t["experiment"]) for h, task in t["tasks"].items()
            if (artifacts / task / "experiments" / t["experiment"] / "summary.json").exists()}
    labels = next(iter(data.values()))["summary"]["labels"]
    out = [f"### {t['title']}", "",
           "**Complete rows and class shares (classes of the model)**", "", rows_table(data, labels), "",
           "**Selected shape and rules**", "", shape_table(data), "",
           ]
    for split in ("validation", "test"):
        out += [f"**Macro-F1, {split}**", "", metric_table(data, "macro_f1", split), "",
                f"**Balanced accuracy, {split}**", "", metric_table(data, "balanced_accuracy", split), ""]
    for split in ("validation", "test"):
        out += [f"**F1 per class, {split}**", "", class_table(data, labels, split), ""]
    if timings is not None:
        out += ["**Cost (wall time, peak RSS of the process)**", "",
                timing_table(t["label"], list(data), timings), ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--territory", choices=[*TERRITORIES, "all"], default="all")
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--timings", type=Path, default=None, help="directory with the <label>-<stage>.time files")
    parser.add_argument("--summary", action="store_true", help="print only the one-table summary against persistence")
    args = parser.parse_args(argv)
    if args.summary:
        print(summary_table(args.artifacts_dir, list(TERRITORIES) if args.territory == "all" else [args.territory]))
        return
    for territory in (TERRITORIES if args.territory == "all" else [args.territory]):
        print(render(territory, args.artifacts_dir, args.timings))


if __name__ == "__main__":
    main()
