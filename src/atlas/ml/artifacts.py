"""Atomic run directories: ``artifacts/<task_id>/<run_id>/``.

Everything is written to a hidden temp directory next to the final one, the pickled model is reloaded and
compared with the in-memory model, and only then is the directory renamed. A crash leaves no half-written
run under its final name. ``SHA256SUMS`` lets ``load_model`` refuse a tampered ``model.pkl`` before
unpickling (pickle executes code: only load runs you produced).
"""

from __future__ import annotations

import hashlib
import os
import pickle
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.paths import REPO_ROOT

MODEL_FILE = "model.pkl"
CHECKSUM_FILE = "SHA256SUMS"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_state(repo: Path = REPO_ROOT) -> tuple[str | None, bool]:
    """(commit, dirty). ``(None, False)`` when git is unavailable; ignored files do not count as dirty."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, False
    return commit, bool(status)


def python_version() -> str:
    return platform.python_version()


def assert_pickle_parity(path: Path, model, X_sample: pd.DataFrame) -> None:
    """Reload ``path`` and require bit-identical predictions to ``model`` on ``X_sample`` (NaN == NaN)."""
    with open(path, "rb") as fh:
        reloaded = pickle.load(fh)  # noqa: S301 - we just wrote this file
    if not np.array_equal(model.predict(X_sample), reloaded.predict(X_sample), equal_nan=True):
        raise RuntimeError("model.pkl does not reproduce the in-memory predictions")


def write_run_dir(
    final_dir: Path,
    *,
    model,
    parity_sample: pd.DataFrame,
    json_files: dict[str, str],
    parquet_files: dict[str, pd.DataFrame],
) -> Path:
    """Write the run to ``final_dir`` atomically; raises ``FileExistsError`` rather than overwrite a run."""
    final_dir = Path(final_dir)
    if final_dir.exists():
        raise FileExistsError(f"run directory already exists: {final_dir}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{final_dir.name}-", dir=final_dir.parent))
    try:
        with open(tmp / MODEL_FILE, "wb") as fh:
            pickle.dump(model, fh, protocol=pickle.HIGHEST_PROTOCOL)
        assert_pickle_parity(tmp / MODEL_FILE, model, parity_sample)
        for name, text in json_files.items():
            (tmp / name).write_text(text)
        for name, frame in parquet_files.items():
            frame.to_parquet(tmp / name, index=False)
        names = sorted(p.name for p in tmp.iterdir())
        (tmp / CHECKSUM_FILE).write_text("".join(f"{sha256_file(tmp / n)}  {n}\n" for n in names))
        os.rename(tmp, final_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final_dir


def verify_checksums(run_dir: Path) -> None:
    """Raise if any file listed in ``SHA256SUMS`` is missing or changed."""
    for line in (Path(run_dir) / CHECKSUM_FILE).read_text().splitlines():
        digest, name = line.split("  ", 1)
        if sha256_file(Path(run_dir) / name) != digest:
            raise ValueError(f"checksum mismatch for {name} in {run_dir}")


def load_model(run_dir: Path):
    """Verify checksums, then unpickle ``model.pkl`` (trusted artifacts only)."""
    verify_checksums(run_dir)
    with open(Path(run_dir) / MODEL_FILE, "rb") as fh:
        return pickle.load(fh)  # noqa: S301 - checksummed artifact written by write_run_dir
