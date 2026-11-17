"""A synthetic montage task, fitted and published with the real engine (tests and the web's fixture; never real data).

::

    PYTHONPATH=src:apps/api python -m atlas.domains.fnirs.synthetic   # apps/web/src/test/fnirsFixture.json

Random trials of 6 subjects on the 36 channels of ``configs/fnirs/montage.json`` (one informative channel), a small rule
mixture fitted by ex_fuzzy, and ``atlas.domains.fnirs.publish``. The web fixture keeps two subjects, two traces and the
variables the rules use, with every ``synthetic`` flag set.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.domains.fnirs import publish as pub
from atlas.ml import artifacts
from atlas.ml.experiment_fnirs import CLASS_LABELS, UNIT, feature_columns, load_table
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.paths import REPO_ROOT

MONTAGE = json.loads((REPO_ROOT / "configs/fnirs/montage.json").read_text())
SUBJECTS, TEST = list(range(1, 7)), [3, 4]
WEB_FIXTURE = REPO_ROOT / "apps/web/src/test/fnirsFixture.json"
WEB_SUBJECTS, WEB_TRACES = (3, 1), ("s03-t01", "s03-t03")


def build(root: Path):
    """``(published model dir, model, table)`` under ``root``."""
    root = Path(root)
    rng = np.random.default_rng(0)
    rows = [{"subject": s, "trial": t, "event": (7, 8, 9)[(t - 1) % 3]} for s in SUBJECTS for t in range(1, 10)]
    frame = pd.DataFrame(rows)
    for sig in ("s1", "s2"):
        for ch in MONTAGE["channels"]:
            frame[f"tmb_{sig}_ch{ch['label']}"] = rng.normal(0, 1e-3, len(frame))
    frame["tmb_s1_chAF7"] += np.where(frame["event"] == 7, -2e-3, 2e-3)  # one informative channel
    table = root / "block.csv"
    frame.to_csv(table, index=False)
    data = load_table(table)
    features = feature_columns(data)
    train = data[~data["subject"].isin(TEST)]
    params = FuzzyClassifierParams(nRules=5, nAnts=2, n_gen=3, pop_size=10, inference="mixture",
                                   mixture_non_negative=True, mixture_search=True, ordinal_conditions=True)
    model = FuzzyClassifier(params, {f: UNIT for f in features}).fit(train[features], train["y"].to_numpy(),
                                                                    CLASS_LABELS, seed=0)
    shape = "mixture-r5-a2-ordinal"
    runs = root / "runs"
    run_dir = artifacts.write_run_dir(
        runs / f"{shape}-seed0", model=model, parity_sample=data[features].head(5),
        parquet_files={"predictions.parquet": data[["subject", "trial", "event", "y"]].assign(
            predicted=model.predict(data[features]))},
        json_files={"run.json": json.dumps({
            "experiment_id": "synthetic", "seed": 0, "params": params.as_dict(), "exfuzzy_version": "3.5.0",
            "git": [None, False], "python": "3.12", "test_subjects": TEST, "published": True})})
    fold = {"n": 9, "macro_f1": 0.5, "accuracy": 0.5, "balanced_accuracy": 0.5, "mcc": 0.0, "share_unknown": 0.0}
    estimator = {**fold, "n": 18, "train": {**fold, "n": 36}}
    (runs / "experiments").mkdir()
    (runs / "experiments/synthetic-select.json").write_text(json.dumps({
        "chosen_shape": shape, "folds": [[1, 2], [5, 6]],
        "fits": [{"shape": shape, "seed": 0, **fold}] * 4,
        "baselines": [{"estimator": "majority_class", "macro_f1": 0.4, "accuracy": 0.67, "mcc": 0.0}]}))
    (runs / "experiments/synthetic-final.json").write_text(json.dumps({"estimators": {
        "exfuzzy-seed0": estimator, "svm_rbf": {**fold, "n": 18}}}))
    one = {"macro_f1": 0.5, "accuracy": 0.5, "mcc": 0.0, "n": 18}
    (runs / "experiments/synthetic-seeds.json").write_text(json.dumps({
        "test": {"exfuzzy": {str(k): {**one, "macro_f1": 0.5 + 0.02 * k} for k in range(3)},
                 "svm_rbf": {str(k): one for k in range(3)}},
        "validation": {"exfuzzy": {"0": {**one, "n": 18}, "1": {**one, "macro_f1": 0.6, "n": 18}},
                       "svm_rbf": {"0": one, "1": one}}}))
    (runs / "experiments/synthetic-nested.json").write_text(json.dumps({"folds": [
        {"fold": k, "n_test": 18, "mean_over_seeds": {"exfuzzy": {**one, "macro_f1": 0.55 + 0.05 * k},
                                                      "svm_rbf": {**one, "macro_f1": 0.6 - 0.04 * k}}}
        for k in range(3)]}))
    out = pub.publish(run_dir, root / "published", table=table)
    return out, model, data


def _synthetic(obj):
    if isinstance(obj, dict):
        return {k: True if k == "synthetic" else _synthetic(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_synthetic(v) for v in obj]
    return obj


def web_fixture(out: Path) -> dict:
    """The trimmed bodies the web tests serve: rules (used variables only), montage, card, trials, two traces."""
    rules = json.loads((out / "rules.json").read_text())
    used = {a["feature"] for r in rules["rules"] for a in r["antecedents"]}
    rules["variables"] = [v for v in rules["variables"] if v["feature"] in used]
    trials = json.loads((out / "trials.json").read_text())
    trials["trials"] = [t for t in trials["trials"] if t["subject"] in WEB_SUBJECTS]
    traces = json.loads((out / "traces.json").read_text())
    return _synthetic({"rules": rules, "montage": json.loads((out / "montage.json").read_text()),
                       "card": json.loads((out / "card.json").read_text()), "trials": trials,
                       "traces": {k: traces[k] for k in WEB_TRACES}})


def main(argv: list[str] | None = None) -> None:
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=WEB_FIXTURE)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        out, _, _ = build(Path(tmp))
        args.out.write_text(json.dumps(web_fixture(out), separators=(",", ":")))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
