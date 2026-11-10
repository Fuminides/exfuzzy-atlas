"""Regression budget at volume (AT-061): opt-in, so CI and ``make test`` are not affected.

    ATLAS_QA_VOLUME=1 make test ARGS=...        # or: ATLAS_QA_VOLUME=1 pytest tests/integration/test_volume_budget.py

It needs a published model with >= 1M input rows and >= 20M activation records (60 entities x 730 days x 20 rules):

* ``ATLAS_VOLUME_DIR`` points at a published dir already built by ``scripts/qa/volume.py build`` (fast), or
* nothing is set and the test builds one in a temp dir (about 30 s, <1 GB RAM, ~50 MB of disk).

The budgets are medians of 10 uncached requests through the real FastAPI app (TestClient, in process) and are about
5x what the workstation measured (docs/qa/volume.md), so they catch an order-of-magnitude regression (a query that stops
pruning partitions, a response that grows with the rows), not noise. ``ATLAS_VOLUME_BUDGET_SCALE=2`` doubles them on a
slower machine. ``ATLAS_VOLUME_ENTITIES`` / ``ATLAS_VOLUME_DAYS`` build a smaller model; the row-count test then skips.
"""

from __future__ import annotations

import os
import statistics
import time
from datetime import timedelta
from pathlib import Path

import pytest

# psutil is not a project dependency (CI has no need of it): without it the module is skipped, not an error
psutil = pytest.importorskip("psutil")
volume = pytest.importorskip("volume")  # scripts/qa/volume.py (conftest puts scripts/qa on sys.path)

pytestmark = pytest.mark.skipif(
    os.environ.get("ATLAS_QA_VOLUME") != "1", reason="volume test is opt-in: set ATLAS_QA_VOLUME=1 (docs/qa/volume.md)"
)

MIN_INPUT_ROWS = 1_000_000
MIN_ACTIVATION_RECORDS = 20_000_000
SCALE = float(os.environ.get("ATLAS_VOLUME_BUDGET_SCALE", "1"))
REPEATS = 10

# kind -> median budget in ms for one uncached request (in-process). Measured p50 on the workstation in the comments.
BUDGET_MS = {
    "rule_map_firing": 50,  # 7 ms
    "rule_map_mean_30d": 100,  # 13 ms
    "rule_map_freq_30d": 100,  # 13 ms
    "rule_map_mean_366d": 400,  # 60 ms
    "rule_map_freq_366d": 400,  # 58 ms
    "rule_trace": 150,  # 16 ms
    "series_7d": 100,  # 14 ms
    "series_full": 250,  # one page of 2 000 points (0.4 MB of JSON); the endpoint whose size follows the rows, capped
    "domains_card_rules": 50,  # 2 ms
}
MAX_RESPONSE_BYTES = {  # independent of the number of input rows
    "rule_map": 150_000,  # 60 point features
    "rule_trace": 50_000,
    "series_7d": 100_000,
    "series_full": 700_000,  # SERIES_MAX_POINTS = 2 000 points
    "domains_card_rules": 100_000,
}


@pytest.fixture(scope="module")
def volume_dir(tmp_path_factory) -> Path:
    given = os.environ.get("ATLAS_VOLUME_DIR")
    if given:
        root = Path(given)
        if not (root / "registry.json").is_file():
            pytest.fail(f"ATLAS_VOLUME_DIR={root} has no registry.json")
        return root
    out = tmp_path_factory.mktemp("volume")
    entities = int(os.environ.get("ATLAS_VOLUME_ENTITIES", "60"))
    days = int(os.environ.get("ATLAS_VOLUME_DAYS", "730"))
    with volume.Guard() as guard:
        volume.build(out, entities, days, 20, guard)
    return out / "published"


@pytest.fixture(scope="module")
def workload(volume_dir):
    return volume.Workload(volume_dir, "volume_y_h6")


@pytest.fixture(scope="module")
def client(volume_dir):
    from fastapi.testclient import TestClient

    from atlas_api.artifact_store import ArtifactStore
    from atlas_api.main import create_app

    with TestClient(create_app(ArtifactStore(volume_dir))) as c:
        yield c


def test_the_model_is_big_enough(workload):
    if "ATLAS_VOLUME_ENTITIES" in os.environ or "ATLAS_VOLUME_DAYS" in os.environ:
        pytest.skip("a smaller model was requested")
    assert workload.n_input_rows >= MIN_INPUT_ROWS
    assert workload.n_activation_records >= MIN_ACTIVATION_RECORDS


@pytest.mark.parametrize("kind", list(BUDGET_MS))
def test_median_latency_within_budget(client, workload, kind):
    make = workload.endpoint_kinds()[kind]
    path, params = make()
    assert client.get(path, params=params).status_code == 200  # warm the model load / file cache; not timed
    timings, biggest = [], 0
    for _ in range(REPEATS):
        path, params = make()
        t0 = time.perf_counter()
        r = client.get(path, params=params)
        timings.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, r.text[:200]
        biggest = max(biggest, len(r.content))
        assert not volume.check_bounded(kind, r.json(), workload)
    budget = BUDGET_MS[kind] * SCALE
    median = statistics.median(timings)
    assert median <= budget, f"{kind}: median {median:.0f} ms over the {budget:.0f} ms budget ({sorted(timings)})"
    limit = MAX_RESPONSE_BYTES["rule_map" if kind.startswith("rule_map") else kind]
    assert biggest <= limit, f"{kind}: a {biggest} byte response (limit {limit}); responses must not follow the rows"


def test_no_window_over_366_days_and_the_limit_is_cheap(client, workload):
    t0 = time.perf_counter()
    r = client.get("/api/v1/rule-map", params={
        "model_id": workload.model_id, "rule_id": workload.rules[0], "metric": "mean_activation",
        "from": volume.iso(workload.t_min), "to": volume.iso(workload.t_min + timedelta(days=367))})
    assert r.status_code == 422
    assert (time.perf_counter() - t0) * 1000 <= 100 * SCALE


def test_cache_returns_the_same_map_faster(client, workload):
    path, params = workload.window(366, "mean_activation")
    t0 = time.perf_counter()
    first = client.get(path, params=params)
    cold_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    second = client.get(path, params=params)
    warm_ms = (time.perf_counter() - t0) * 1000
    assert first.json() == second.json()
    assert warm_ms <= max(cold_ms, 10 * SCALE)


def test_memory_stays_bounded(client, workload):
    """After all the requests above, this process (store + DuckDB + the TestClient) is far under the 2.5 GB cap."""
    for kind in ("rule_map_mean_366d", "series_full", "rule_trace"):
        path, params = workload.endpoint_kinds()[kind]()
        assert client.get(path, params=params).status_code == 200
    assert psutil.Process().memory_info().rss <= 2.5 * 2**30


def test_series_without_a_window_is_one_page_and_the_cursor_continues(client, workload):
    from atlas_api.artifact_store import SERIES_MAX_POINTS

    path, params = workload.series_full()
    first = client.get(path, params=params).json()
    assert len(first["points"]) == SERIES_MAX_POINTS and first["next_cursor"] is not None
    second = client.get(path, params={**params, "cursor": first["next_cursor"]}).json()
    assert second["points"][0]["issued_at_utc"] == first["next_cursor"]


def test_activations_are_sorted_by_rule_in_row_groups(workload, volume_dir):
    import pyarrow.parquet as pq

    from atlas.services.publish import ACTIVATION_ROW_GROUP_SIZE

    file = max((volume_dir / workload.model_id / "activations").rglob("*.parquet"), key=lambda p: p.stat().st_size)
    parquet = pq.ParquetFile(file)
    rows = [parquet.metadata.row_group(i).num_rows for i in range(parquet.metadata.num_row_groups)]
    assert len(rows) > 1 and max(rows) <= 1.1 * ACTIVATION_ROW_GROUP_SIZE
    column = parquet.schema_arrow.names.index("rule_id")
    stats = [parquet.metadata.row_group(i).column(column).statistics for i in range(len(rows))]
    rule = workload.rules[len(workload.rules) // 2]
    # a query for one rule touches a small share of the row groups (min/max pruning)
    assert sum(s.min <= rule <= s.max for s in stats) <= max(2, len(rows) // 5)


def test_the_response_cache_stays_inside_its_byte_budget(volume_dir, workload):
    from fastapi.testclient import TestClient

    from atlas_api.artifact_store import ArtifactStore
    from atlas_api.main import create_app

    store = ArtifactStore(volume_dir, cache_bytes=200_000)  # ~ six of the 33 KiB maps
    with TestClient(create_app(store)) as c:
        for _ in range(40):
            path, params = workload.window(30, "mean_activation")
            assert c.get(path, params=params).status_code == 200
            assert store._cache.bytes <= 200_000
    assert 0 < len(store._cache) < 40
