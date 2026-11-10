"""Data locations, relative to the checkout so every git worktree resolves its own.

``data/raw/<source>`` holds symlinks to the machine dataset root (see
LLM_help/DATASETS_PATHS.md); ``data/processed`` and ``artifacts`` are generated and
git-ignored. ``ATLAS_DATA_DIR`` / ``ATLAS_ARTIFACTS_DIR`` override the defaults, and
``ATLAS_DATASETS_ROOT`` the dataset root (default ``~/Datasets``).
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACTS_DIR = Path(os.environ.get("ATLAS_ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
# Machine dataset root (raw downloads, outside the checkout); the CLIs read ``ATLAS_DATASETS_ROOT`` first.
DEFAULT_DATASETS_ROOT = str(Path.home() / "Datasets")
