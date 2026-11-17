"""The committed NIRS montage: parsed from the dataset description, on the unit sphere, mirror-symmetric."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from atlas.domains.fnirs import montage
from atlas.ml.experiment_fnirs import feature_columns
from atlas.paths import DATA_DIR, REPO_ROOT

MONTAGE = json.loads((REPO_ROOT / "configs/fnirs/montage.json").read_text())


def _mirror(label: str) -> str:
    """10-5 names: odd digits are left, even digits right, z midline; 'h' marks the half position."""
    digits = "".join(c for c in label if c.isdigit())
    if not digits:
        return label
    n = int(digits)
    return label.replace(digits, str(n + 1 if n % 2 else n - 1))


def test_36_channels_on_the_unit_sphere():
    xyz = np.array([c["xyz"] for c in MONTAGE["channels"]])
    assert xyz.shape == (36, 3)
    assert np.allclose(np.linalg.norm(xyz, axis=1), 1.0, atol=2e-3)
    assert (xyz[:, 2] >= 0).all()  # all above the ear plane


def test_left_right_symmetry():
    by_label = {c["label"]: np.array(c["xyz"]) for c in MONTAGE["channels"]}
    for label, p in by_label.items():
        other = by_label[_mirror(label)]
        assert np.allclose(other, p * [-1, 1, 1], atol=2e-4), label


def test_channels_are_the_inputs_of_the_table():
    table = DATA_DIR / "raw/fnirs-nback/block_avg_tmb.csv"
    if not table.exists():
        pytest.skip("raw fNIRS table not available")
    columns = feature_columns(pd.read_csv(table, nrows=1))
    assert sorted(columns) == sorted(f"tmb_s{s}_ch{c['label']}" for s in (1, 2) for c in MONTAGE["channels"])


def test_committed_file_matches_the_pdf():
    if not montage.PDF.exists():
        pytest.skip("dataset description PDF not available")
    assert montage.build() == MONTAGE


def test_parser_reads_the_table_and_refuses_a_short_one():
    lines = "\n".join(f"{c['label']} {c['xyz'][0]} {c['xyz'][1]} {c['xyz'][2]}" for c in MONTAGE["channels"])
    text = f"EEG table\nFp1 -0.3 0.95 0.0\n{montage.TABLE_TITLE}\nclab X Y Z\n{lines}\nData Organization"
    assert montage.parse_channels(text) == MONTAGE["channels"]
    with pytest.raises(ValueError, match="expected 36"):
        montage.parse_channels("\n".join(text.splitlines()[:20]))


REGIONS = json.loads((REPO_ROOT / "configs/fnirs/regions.json").read_text())


def test_regions_cover_the_montage_and_agree_with_its_sides():
    assert REGIONS["approximate"] is True
    xyz = {c["label"]: c["xyz"] for c in MONTAGE["channels"]}
    assert set(REGIONS["channels"]) == set(xyz)
    for label, r in REGIONS["channels"].items():
        side = r["region_en"].split()[0]
        x = xyz[label][0]
        assert {"Left": x < 0, "Right": x > 0}.get(side, abs(x) < 1e-3), label


def test_spanish_region_names():
    from atlas.domains.fnirs.regions import spanish

    assert spanish("Left prefrontal cortex") == "Corteza prefrontal izquierda"
    assert spanish("Right superior parietal lobule") == "Lobulillo parietal superior derecho"
    assert spanish("Primary visual cortex") == "Corteza visual primaria"


def test_committed_regions_match_the_notebook():
    from atlas.domains.fnirs import regions

    if not regions.NOTEBOOK.exists():
        pytest.skip("notebook 005 not available")
    assert regions.build() == REGIONS
