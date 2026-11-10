"""Checksum verification of published model directories.

    python -m atlas.services.verify <published_model_dir> [<published_model_dir> ...]
    python -m atlas.services.verify <published_dir>        # a directory with registry.json: every registered model

Two levels, because the files carry different risk:

* **Code**: ``model.pkl`` is a pickle (unpickling executes code), and ``rules.json`` / ``card.json`` define what the
  model means. :func:`load_verified_model` checks these three against ``SHA256SUMS`` before the API unpickles anything.
* **Data**: activations, predictions, inputs and the rest are data. They are verified when the model is published and
  by this command (the full ``SHA256SUMS``, plus a check that no file is missing from it), not on every model load: the
  cost of that check grows with the size of the model, the API's does not.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

from atlas.ml import artifacts
from atlas.services import layout

CODE_FILES = (layout.MODEL_FILE, "rules.json", layout.CARD_FILE)


def _listed(model_dir: Path) -> dict[str, str]:
    sums = Path(model_dir) / artifacts.CHECKSUM_FILE
    if not sums.is_file():
        raise ValueError(f"{model_dir} has no {artifacts.CHECKSUM_FILE}: not a published model directory")
    return dict(reversed(line.split("  ", 1)) for line in sums.read_text().splitlines())


def verify_files(model_dir: Path, names) -> None:
    """Raise ``ValueError`` if a name is not listed in ``SHA256SUMS`` or differs from it ("checksum mismatch")."""
    model_dir = Path(model_dir)
    listed = _listed(model_dir)
    for name in names:
        if name not in listed:
            raise ValueError(f"{name} is not listed in {model_dir / artifacts.CHECKSUM_FILE}")
        path = model_dir / name
        if not path.is_file() or artifacts.sha256_file(path) != listed[name]:
            raise ValueError(f"checksum mismatch for {name} in {model_dir}")


def verify_code_files(model_dir: Path) -> None:
    """Verify only ``model.pkl``, ``rules.json`` and ``card.json`` (what must hold before unpickling)."""
    verify_files(model_dir, CODE_FILES)


def load_verified_model(model_dir: Path):
    """Verify the code files, then unpickle ``model.pkl`` (trusted artifacts only). Data files are not read."""
    verify_code_files(model_dir)
    with open(Path(model_dir) / layout.MODEL_FILE, "rb") as fh:
        return pickle.load(fh)  # noqa: S301 - model.pkl was just checked against SHA256SUMS


def verify_model_dir(model_dir: Path) -> None:
    """The full check: every file in ``SHA256SUMS`` matches, and every file in the directory is listed."""
    model_dir = Path(model_dir)
    listed = _listed(model_dir)
    present = {p.relative_to(model_dir).as_posix() for p in model_dir.rglob("*") if p.is_file()}
    present.discard(artifacts.CHECKSUM_FILE)
    if unlisted := sorted(present - set(listed)):
        raise ValueError(f"files not listed in {artifacts.CHECKSUM_FILE} in {model_dir}: {unlisted}")
    verify_files(model_dir, sorted(listed))


def _targets(path: Path) -> list[Path]:
    """The model directories to check: ``path`` itself, or every model of the registry found in it."""
    if (path / layout.REGISTRY_FILE).is_file() and not (path / artifacts.CHECKSUM_FILE).is_file():
        return sorted({path / e.model_id for e in layout.read_registry(path).tasks.values()})
    return [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atlas.services.verify", description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path, help="published model directory (or a published directory)")
    args = parser.parse_args(argv)
    failed = 0
    for given in args.paths:
        for model_dir in _targets(given):
            try:
                verify_model_dir(model_dir)
            except (ValueError, OSError) as exc:
                failed += 1
                print(f"FAIL {model_dir}: {exc}", file=sys.stderr)
            else:
                n = len(_listed(model_dir))
                print(f"ok   {model_dir} ({n} files)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
