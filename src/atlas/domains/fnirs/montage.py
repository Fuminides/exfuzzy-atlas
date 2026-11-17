"""NIRS channel positions of Shin et al. (2018), read from the dataset description, never placed by hand.

::

    PYTHONPATH=src python -m atlas.domains.fnirs.montage   # data/raw/fnirs-nback/... -> configs/fnirs/montage.json

The table "Locations of NIRS channels in Cartesian coordinate system" of ``dataset_description_MATLAB.pdf`` gives the
36 channels (the midpoint of a source-detector pair, named after the nearest 10-5 position) on a unit sphere: x to the
right ear, y to the nose, z to the vertex. The output keeps those numbers as printed (4 decimals) and adds the sha256
of the PDF, so a test can check the committed file without the PDF.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from atlas.ml.artifacts import sha256_file
from atlas.paths import DATA_DIR, REPO_ROOT

PDF = DATA_DIR / "raw/fnirs-nback/dataset_description_MATLAB.pdf"
OUT = REPO_ROOT / "configs/fnirs/montage.json"
TABLE_TITLE = "Locations of NIRS channels in Cartesian coordinate system"
N_CHANNELS = 36
_NUM = r"(-?\d+(?:\.\d+)?)"
_ROW = re.compile(rf"^\s*([A-Za-z]+\d*h?)\s+{_NUM}\s+{_NUM}\s+{_NUM}\s*$", re.M)


def parse_channels(text: str) -> list[dict]:
    """The rows of the NIRS table: the first ``N_CHANNELS`` ``label x y z`` lines after its title."""
    start = text.find(TABLE_TITLE)
    if start < 0:
        raise ValueError(f"table {TABLE_TITLE!r} not found")
    rows = _ROW.findall(text[start + len(TABLE_TITLE):])[:N_CHANNELS]
    if len(rows) != N_CHANNELS:
        raise ValueError(f"expected {N_CHANNELS} channels, found {len(rows)}")
    labels = [r[0] for r in rows]
    if len(set(labels)) != N_CHANNELS:
        raise ValueError("duplicate channel labels")
    return [{"label": label, "xyz": [float(x), float(y), float(z)]} for label, x, y, z in rows]


def build(pdf: Path = PDF) -> dict:
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    return {
        "source": "Shin et al. (2018), Dataset description_MATLAB.pdf, table '" + TABLE_TITLE + "'",
        "source_url": "http://doc.ml.tu-berlin.de/simultaneous_EEG_NIRS/Dataset%20description_MATLAB.pdf",
        "source_sha256": sha256_file(pdf),
        "frame": "unit sphere; x towards the right ear, y towards the nose, z towards the vertex",
        "channels": parse_channels(text),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, default=PDF)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build(args.pdf), indent=1) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
