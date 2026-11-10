"""B3 (AT-061): activations are published sorted by rule with row groups; the API's answers do not change.

The "before" side is rebuilt in the test: the same records in the old layout (time, entity, rule order; one row
group per monthly file). Every endpoint that reads the activations must answer identically on both.
"""

import shutil
from datetime import datetime, timezone

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import layout
from atlas.services.publish import ACTIVATION_SCHEMA, ACTIVATION_SORT, CLASS_ACTIVATION_SCHEMA
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

WINDOWS = [
    ("2024-01-10T00:00:00Z", "2024-01-20T00:00:00Z"),
    ("2024-01-25T00:00:00Z", "2024-02-05T00:00:00Z"),  # across the monthly files
    ("2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"),
]
ULP = 1e-12  # a mean sums the same numbers in another order: equal up to rounding, never more
LEGACY_SORT = [("issued_at_utc", "ascending"), ("entity_id", "ascending"), ("rule_id", "ascending")]


def same(a, b) -> None:
    """Equal payloads: every field identical, floating-point values equal up to the order of a sum."""
    if isinstance(a, float) and isinstance(b, float):
        assert a == pytest.approx(b, abs=ULP, rel=0)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            same(x, y)
    else:
        assert a == b


@pytest.fixture(scope="module", params=["regression", "classification"])
def pair(request, built, built_class, tmp_path_factory):
    """``(built, new-layout client, legacy-layout client)`` over copies of the same published model."""
    b = built if request.param == "regression" else built_class
    legacy = tmp_path_factory.mktemp("legacy-" + request.param)
    shutil.copytree(b.published_dir, legacy, dirs_exist_ok=True)
    model_dir = legacy / b.run.manifest.model_id
    for path in (model_dir / layout.ACTIVATIONS_DIR).rglob("*.parquet"):
        table = pq.read_table(path)
        table = table.sort_by(LEGACY_SORT)
        pq.write_table(table, path, compression="zstd", row_group_size=10**9)
    layout.write_checksums(model_dir)
    return (b, ArtifactStore(b.published_dir), ArtifactStore(legacy))


def test_published_files_are_sorted_by_rule_with_row_groups(built, built_class, tmp_path):
    from atlas.services.publish import publish_run

    for b in (built, built_class):
        published = tmp_path / b.run.manifest.task_id
        publish_run(
            b.run.run_dir, b.root / "features.parquet", b.root / "entities.geojson", b.root / "feature_spec.json",
            "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z", published_dir=published, synthetic=True,
            activation_row_group_size=1000,
        )
        files = sorted((published / b.run.manifest.model_id / layout.ACTIVATIONS_DIR).rglob("*.parquet"))
        assert len(files) == 2  # one file per month
        for file in files:
            parquet = pq.ParquetFile(file)
            assert parquet.metadata.num_row_groups > 1
            # the schema is the published schema (names, types, nullability), not whatever the sorter infers
            expected = CLASS_ACTIVATION_SCHEMA if b is built_class else ACTIVATION_SCHEMA
            assert pq.read_schema(file).remove_metadata().equals(expected)
            groups = [parquet.metadata.row_group(i).num_rows for i in range(parquet.metadata.num_row_groups)]
            assert groups[:-1] == [1000] * (len(groups) - 1) and 0 < groups[-1] <= 1000
            keys = list(zip(*[pq.read_table(file, columns=list(ACTIVATION_SORT)).column(c).to_pylist()
                              for c in ACTIVATION_SORT], strict=True))
            assert keys == sorted(keys)
            # pruning is possible: a given rule lives in few row groups (statistics min <= rule <= max)
            rule = keys[0][0]
            column = parquet.schema_arrow.names.index("rule_id")
            touching = [
                i for i in range(parquet.metadata.num_row_groups)
                if (s := parquet.metadata.row_group(i).column(column).statistics).min <= rule <= s.max
            ]
            assert 0 < len(touching) < parquet.metadata.num_row_groups


def test_the_default_row_group_is_about_100k_rows(built):
    from atlas.services.publish import ACTIVATION_ROW_GROUP_SIZE

    assert ACTIVATION_ROW_GROUP_SIZE == 100_000
    first = next((built.model_dir / layout.ACTIVATIONS_DIR).rglob("*.parquet"))
    assert pq.ParquetFile(first).metadata.num_row_groups == 1  # the synthetic month is far below 100 000 rows


def test_the_published_model_still_verifies(built, built_class):
    for b in (built, built_class):
        artifacts.verify_checksums(b.model_dir)


def test_rule_maps_are_identical_in_both_layouts(pair):
    b, new, old = pair
    model_id = b.run.manifest.model_id
    rules = [r.rule_id for r in b.run.rules.rules]
    asked = 0
    for start, end in WINDOWS:
        lo, hi = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
        for rule in rules:
            for metric, tau in ((m.RuleMapMetric.MEAN_ACTIVATION, None), (m.RuleMapMetric.ACTIVATION_FREQUENCY, 0.3)):
                same(new.rule_map(model_id, rule, metric, None, lo, hi, tau).model_dump(),
                     old.rule_map(model_id, rule, metric, None, lo, hi, tau).model_dump())
                asked += 1
    instant = datetime(2024, 1, 12, 7, tzinfo=timezone.utc)
    for rule in rules:
        metric = m.RuleMapMetric.FIRING_STRENGTH
        same(new.rule_map(model_id, rule, metric, instant, None, None, None).model_dump(),
             old.rule_map(model_id, rule, metric, instant, None, None, None).model_dump())
    assert asked > 20


def test_territories_and_stories_are_identical_in_both_layouts(pair):
    b, new, old = pair
    model_id = b.run.manifest.model_id
    measures = [m.TerritoryMeasure.MEAN_ACTIVATION, m.TerritoryMeasure.ACTIVATION_FREQUENCY]
    if b.run.rules.inference.family == m.InferenceFamily.WINNING_RULE_CLASSIFIER:
        measures.append(m.TerritoryMeasure.WINNER_SHARE)
    for start, end in WINDOWS:
        lo, hi = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
        for measure in measures:
            same(new.rule_territories(model_id, lo, hi, measure, 0.4).model_dump(),
                 old.rule_territories(model_id, lo, hi, measure, 0.4).model_dump())
        same(new.rule_stories(model_id, lo, hi, 0.4, 10).model_dump(),
             old.rule_stories(model_id, lo, hi, 0.4, 10).model_dump())


def test_the_http_answers_do_not_change_either(pair):
    b, new, old = pair
    params = {"model_id": b.run.manifest.model_id, "rule_id": b.run.rules.rules[0].rule_id,
              "metric": "mean_activation", "from": WINDOWS[1][0], "to": WINDOWS[1][1]}
    got = TestClient(create_app(new)).get("/api/v1/rule-map", params=params)
    assert got.status_code == 200
    same(got.json(), TestClient(create_app(old)).get("/api/v1/rule-map", params=params).json())
