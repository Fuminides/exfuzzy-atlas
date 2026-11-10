"""The clip used by the FX2 reproduction check is the 3.3.1 / PR 32 decoding (no fit is run)."""

import numpy as np
import pytest

from atlas.ml import exfuzzy_features as xf
from atlas.ml.fx2_clip_check import clip_term, clip_terms


def test_clip_keeps_dont_care_and_clips_to_the_last_term():
    assert [clip_term(g, 3, 5) for g in (-1, 0, 1, 2, 3, 4)] == [-1, 0, 1, 2, 2, 2]
    genes = np.array([[-1, 0, 4], [2, 3, 1]])
    assert clip_terms(genes, np.array([3, 4, 5]), 5).tolist() == [[-1, 0, 4], [2, 3, 1]]
    assert clip_terms(genes, np.array([3, 3, 3]), 5).tolist() == [[-1, 0, 2], [2, 2, 1]]


@pytest.mark.skipif(not xf.has_proportional_term_remap(), reason="needs ex_fuzzy PR 35 (integration build)")
def test_undo_remap_equals_the_remap_only_for_equal_term_counts(monkeypatch):
    from ex_fuzzy import _array_fitness, _fitness, _population_fitness, evolutionary_fit

    genes = np.arange(-1, 5)
    for n in (3, 4, 5):  # n == M: identity, the remap and the clip agree
        same = n == 5
        assert (clip_terms(genes, n, 5) == _fitness.remap_terms(genes, n, 5)).all() == same
    from atlas.ml import fx2_clip_check

    saved = [(m, k, getattr(m, k)) for m, k in ((_fitness, "remap_term"), (_fitness, "remap_terms"),
             (_array_fitness, "remap_terms"), (_population_fitness, "remap_terms"), (evolutionary_fit, "remap_term"))]
    try:
        fx2_clip_check.undo_remap()
        assert evolutionary_fit.remap_term(2, 3, 5) == 2 and _array_fitness.remap_terms(np.array([2]), 3, 5)[0] == 2
    finally:
        for module, name, original in saved:
            setattr(module, name, original)
    assert evolutionary_fit.remap_term(2, 3, 5) == 1
