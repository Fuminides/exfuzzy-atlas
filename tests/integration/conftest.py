"""Integration (AT-062) tests run against the real published models and skip cleanly when there are none.

Point them at a published directory with ``ATLAS_PUBLISHED_DIR`` (default ``artifacts/published``). CI has no
artifacts, so every test that needs them is skipped with the reason below.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "qa"))  # wording_audit

from qa_support import TASK_IDS, Task, published_dir  # noqa: E402


def _missing_reason() -> str | None:
    root = published_dir()
    if not (root / "registry.json").is_file():
        return (
            f"no published models at {root} (registry.json missing); build them as in docs/reproduce.md "
            "or set ATLAS_PUBLISHED_DIR"
        )
    return None


@pytest.fixture(scope="session")
def published() -> Path:
    reason = _missing_reason()
    if reason:
        pytest.skip(reason)
    return published_dir()


@pytest.fixture(scope="session")
def client(published):
    from fastapi.testclient import TestClient

    from atlas_api.artifact_store import ArtifactStore
    from atlas_api.main import create_app

    with TestClient(create_app(ArtifactStore(published))) as c:
        yield c


@pytest.fixture(scope="session", params=TASK_IDS)
def task(request, published) -> Task:
    registry = json.loads((published / "registry.json").read_text())["tasks"]
    if request.param not in registry:
        pytest.skip(f"task {request.param} is not in the published registry")
    return Task(published, request.param, registry[request.param])
