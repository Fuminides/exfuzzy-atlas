"""fNIRS n-back experiment: the manuscript split, subject folds, event mapping and metrics (no ex_fuzzy fit)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from atlas.ml import experiment_fnirs as fx
from atlas.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/ml/fnirs_nback_experiment.json"


def _table(tmp_path, events=(7, 8, 9)):
    rng = np.random.default_rng(0)
    rows = [{"subject": s, "trial": t, "event": events[(t - 1) % len(events)]}
            for s in range(1, 4) for t in range(1, 7)]
    frame = pd.DataFrame(rows)
    for sig in ("s1", "s2"):
        for ch in range(36):
            frame[f"tmb_{sig}_chC{ch}"] = rng.normal(size=len(frame))
    path = tmp_path / "block.csv"
    frame.to_csv(path, index=False)
    return path


def test_manuscript_split_is_reproduced():
    assert fx.manuscript_test_subjects() == list(fx.MANUSCRIPT_TEST_SUBJECTS) == [3, 4, 5, 9, 16, 19]


def test_config_keeps_the_manuscript_test_subjects_and_a_fixed_published_seed():
    config = fx.load_config(CONFIG)
    assert sorted(config.test_subjects) == fx.manuscript_test_subjects()
    assert config.published_seed in config.final_seeds
    assert len({s.key for s in config.shapes()}) == len(config.shapes())


def test_config_refuses_another_test_split(tmp_path):
    raw = json.loads(CONFIG.read_text())
    raw["test_subjects"] = [1, 2, 3, 4, 5, 6]
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="manuscript"):
        fx.load_config(path)


def test_subject_folds_are_disjoint_and_cover_every_subject():
    subjects = [s for s in range(1, 27) if s not in fx.MANUSCRIPT_TEST_SUBJECTS]
    folds = fx.subject_folds(subjects, 5, seed=0)
    flat = [s for f in folds for s in f]
    assert sorted(flat) == subjects and len(flat) == len(set(flat))
    assert {len(f) for f in folds} == {4}
    assert folds == fx.subject_folds(subjects, 5, seed=0)


def test_load_table_maps_events_and_refuses_unknown_codes(tmp_path):
    frame = fx.load_table(_table(tmp_path))
    assert frame.groupby("event")["y"].first().to_dict() == {7: 0, 8: 1, 9: 1}
    assert len(fx.feature_columns(frame)) == 72
    with pytest.raises(ValueError, match="unknown event"):
        fx.load_table(_table(tmp_path, events=(7, 8, 10)))


def test_unknown_prediction_counts_as_an_error():
    y = np.array([0, 0, 1, 1])
    perfect = fx.scores(y, y.copy())
    with_unknown = fx.scores(y, np.array([0, -1, 1, 1]))
    assert perfect["mcc"] == pytest.approx(1.0)
    assert with_unknown["accuracy"] == pytest.approx(0.75)
    assert with_unknown["share_unknown"] == pytest.approx(0.25)
    assert with_unknown["mcc"] < 1.0
