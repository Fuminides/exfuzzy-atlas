"""Approximate brain region and Brodmann area per NIRS channel, as the ex-Fuzzy fNIRS demo authors assigned them.

::

    PYTHONPATH=src python -m atlas.domains.fnirs.regions   # data/raw/fnirs-nback/005_...ipynb -> configs/fnirs/...

The table ``eeg_location_data`` of notebook ``005_Visualisation_Demo_with_PyCirclize.ipynb`` (commit ``244d8a0``) maps
each channel name to "Approximate Brodmann Area(s)" and "Brain Region". It is read with ``ast.literal_eval`` (the
notebook is never executed). It is an assignment by name, not a measurement on these subjects: the montage response
says so (``region_approximate``). The Spanish names are Atlas's translation of the English ones.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from atlas.ml.artifacts import sha256_file
from atlas.paths import DATA_DIR, REPO_ROOT

NOTEBOOK = DATA_DIR / "raw/fnirs-nback/005_Visualisation_Demo_with_PyCirclize.ipynb"
OUT = REPO_ROOT / "configs/fnirs/regions.json"
TABLE = "eeg_location_data"
SOURCE = ("ex-Fuzzy fNIRS demo (Caterson et al.), notebook 005_Visualisation_Demo_with_PyCirclize.ipynb, commit "
          "244d8a0: approximate Brodmann area and brain region per channel")
ES = {
    "prefrontal cortex": "corteza prefrontal",
    "premotor cortex": "corteza premotora",
    "primary motor cortex": "corteza motora primaria",
    "primary somatosensory cortex": "corteza somatosensorial primaria",
    "somatosensory association cortex": "corteza somatosensorial de asociación",
    "superior parietal lobule": "lobulillo parietal superior",
    "visual association cortex": "corteza visual de asociación",
    "primary visual cortex": "corteza visual primaria",
}
SIDES = {"Left": ("izquierda", "izquierdo"), "Right": ("derecha", "derecho"), "Medial": ("medial", "medial")}


def spanish(region: str) -> str:
    """'Left superior parietal lobule' -> 'Lobulillo parietal superior izquierdo' (side after the noun, agreed)."""
    side, _, rest = region.partition(" ")
    if side not in SIDES:
        side, rest = None, region
    base = ES[rest.lower()]
    if side is not None:
        feminine, masculine = SIDES[side]
        base = f"{base} {masculine if base.startswith('lobulillo') else feminine}"
    return base[0].upper() + base[1:]


def parse_table(source: str) -> dict:
    """The dict literal assigned to ``eeg_location_data`` in a code cell."""
    start = source.index("{", source.index(TABLE))
    depth = 0
    for end, char in enumerate(source[start:], start):
        depth += (char == "{") - (char == "}")
        if depth == 0:
            return ast.literal_eval(source[start:end + 1])
    raise ValueError(f"unterminated {TABLE}")


def build(notebook: Path = NOTEBOOK) -> dict:
    cells = json.loads(Path(notebook).read_text())["cells"]
    source = next("".join(c["source"]) for c in cells if c["cell_type"] == "code" and TABLE in "".join(c["source"]))
    table = parse_table(source)
    names, areas, regions = table["EEG Electrode"], table["Approximate Brodmann Area(s)"], table["Brain Region"]
    if not len(names) == len(areas) == len(regions) or len(set(names)) != len(names):
        raise ValueError("the region table must have one row per channel")
    return {
        "source": SOURCE, "source_sha256": sha256_file(notebook), "approximate": True,
        "channels": {n: {"brodmann": a, "region_en": r, "region": spanish(r)}
                     for n, a, r in sorted(zip(names, areas, regions, strict=True))},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.out.write_text(json.dumps(build(args.notebook), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
