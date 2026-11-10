"""Committed schemas and fixtures must match what the code generates today.

The fixture comparison is also the golden parity check: the traces were computed by the
pinned ex_fuzzy engine (since v0.7 a git commit, pyproject.toml), so a library upgrade that changes memberships, firing
or the mixture weights fails here.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]


# v0.7: the weights of the synthetic mixture are an L-BFGS-B solution; another numpy / scipy / BLAS gives the same rules
# and classes but weights that differ in the last digits (seen: 1e-12), so that file is compared with a tolerance
APPROXIMATE = {"v07_responses.json"}


def _close(a, b, rel=1e-6, abs_=1e-9) -> bool:
    """Equal structure and strings, numbers within ``abs_ + rel * |b|``."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], rel, abs_) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, rel, abs_) for x, y in zip(a, b, strict=True))
    if isinstance(a, float | int) and isinstance(b, float | int) and not isinstance(a, bool):
        return abs(a - b) <= abs_ + rel * abs(b)
    return a == b


def _is_mixture(item) -> bool:
    return isinstance(item, dict) and "-mixture-" in str(item.get("model_id", ""))


def run(script, out):
    # the subprocess imports the same ex_fuzzy as this one (a checkout given with EXFUZZY_SRC, or the installed one)
    exfuzzy = Path(importlib.util.find_spec("ex_fuzzy").origin).resolve().parents[1]
    # PATH so that git can name the commit of an ex_fuzzy checkout (the version recorded in the fixtures)
    env = {"PYTHONPATH": f"{exfuzzy}:{REPO / 'src'}:{REPO / 'apps' / 'api'}", "PATH": os.environ.get("PATH", "")}
    subprocess.run([sys.executable, str(REPO / "scripts" / script), "--out", str(out)], check=True, env=env)


def test_json_schemas_are_up_to_date(tmp_path):
    run("export_schemas.py", tmp_path)
    committed = REPO / "src" / "atlas" / "contracts" / "schemas"
    fresh = sorted(p.name for p in tmp_path.iterdir())
    assert fresh == sorted(p.name for p in committed.iterdir())
    for name in fresh:
        assert (tmp_path / name).read_text() == (committed / name).read_text(), f"{name} is stale: make schemas"


def test_fixtures_are_reproducible_with_pinned_exfuzzy(tmp_path):
    run("make_fixtures.py", tmp_path)
    committed = REPO / "fixtures" / "synthetic"
    for path in committed.glob("*.json"):
        fresh, kept = json.loads((tmp_path / path.name).read_text()), json.loads(path.read_text())
        if path.name in APPROXIMATE:
            assert _close(fresh, kept), path.name
        elif isinstance(kept, list) and any(_is_mixture(x) for x in kept):  # the mixture's entries, with a tolerance
            assert len(fresh) == len(kept), path.name
            for a, b in zip(fresh, kept, strict=True):
                assert (_close(a, b) if _is_mixture(b) else a == b), f"{path.name}: {b.get('model_id')}"
        else:
            assert fresh == kept, path.name
    assert pq.read_table(tmp_path / "observations_air.parquet").equals(
        pq.read_table(committed / "observations_air.parquet")
    )
