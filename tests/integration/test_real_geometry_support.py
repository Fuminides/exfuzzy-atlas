"""AT-062 #3: geometry type matches geometry_support; no estimated surface; NYC polygons valid; points only."""

from __future__ import annotations

import json

import pandas as pd
import pytest
from qa_support import api_get, feature_by_entity, iso, rule_map

SUPPORT_OF_TYPE = {"Point": "observed_point", "Polygon": "observed_polygon", "MultiPolygon": "observed_polygon"}


def _coords(geometry):
    if geometry["type"] == "Point":
        yield geometry["coordinates"]
    else:
        stack = [geometry["coordinates"]]
        while stack:
            node = stack.pop()
            if node and isinstance(node[0], (int, float)):
                yield node
            else:
                stack.extend(node)


def test_entities_have_the_documented_support_and_geometry_type(client, task):
    body = api_get(client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id)
    feats = body["features"]
    assert len(feats) == task.expect.n_entities
    assert {f["properties"]["entity_id"] for f in feats} == {
        f["properties"]["entity_id"] for f in task.entities["features"]
    }
    lon0, lat0, lon1, lat1 = task.expect.bbox
    for f in feats:
        where = f"{task.task_id} {f['id']}"
        assert f["geometry"] is not None, (
            f"{where}: a null-geometry entity is published (it can only be listed, never drawn)"
        )
        assert f["geometry"]["type"] in task.expect.geometries, where
        assert f["properties"]["geometry_support"] == task.expect.support == SUPPORT_OF_TYPE[f["geometry"]["type"]], (
            where
        )
        assert f["properties"]["geometry_source"], f"{where}: official geometry source missing"
        for lon, lat, *_ in _coords(f["geometry"]):
            assert lon0 <= lon <= lon1 and lat0 <= lat <= lat1, f"{where}: ({lon}, {lat}) outside the sanity box"


def test_rule_map_features_match_the_entity_geometry_and_never_carry_a_null_geometry(client, task):
    entities = {
        f["properties"]["entity_id"]: f
        for f in api_get(client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id)["features"]
    }
    t = task.sample_rows(1, "geom")["issued_at_utc"].iloc[0]
    resp = rule_map(client, task, task.rule_ids[0], metric="firing_strength", time=iso(t))
    assert len(resp["features"]) == len(entities)
    for f in resp["features"]:
        assert f["geometry"] is not None, f"rule-map sent a null-geometry entity: {f['id']}"
        assert f["geometry"] == entities[f["id"]]["geometry"], "rule-map geometry differs from /entities"
        assert f["geometry"]["type"] in task.expect.geometries
        assert f["properties"]["geometry_support"] == SUPPORT_OF_TYPE[f["geometry"]["type"]] == task.expect.support
    assert feature_by_entity(resp).keys() == entities.keys()


def test_no_estimated_surface_in_any_payload(client, task):
    t = task.sample_rows(1, "surface")["issued_at_utc"].iloc[0]
    payloads = [
        api_get(client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id),
        api_get(client, f"/api/v1/models/{task.model_id}"),
        api_get(client, f"/api/v1/models/{task.model_id}/rules"),
        rule_map(client, task, task.rule_ids[0], metric="firing_strength", time=iso(t)),
        rule_map(
            client,
            task,
            task.rule_ids[0],
            metric="mean_activation",
            **{"from": iso(t), "to": iso(t + pd.Timedelta(days=1))},
        ),
    ]
    for body in payloads:
        text = json.dumps(body)
        assert "estimated_surface" not in text
    assert "estimated_surface" not in {
        s for f in task.entities["features"] for s in [f["properties"]["geometry_support"]]
    }


def test_every_series_and_prediction_entity_has_a_geometry(task):
    with_geometry = {f["properties"]["entity_id"] for f in task.entities["features"] if f["geometry"]}
    assert set(task.preds["entity_id"]) <= with_geometry
    assert set(task.inputs["entity_id"]) <= with_geometry
    published = set(json.loads((task.path / "publish.json").read_text())["entities"])
    assert published == with_geometry - task.unmodelled_ids  # an unmodelled entity is drawn but has no data


def test_nyc_zone_polygons_are_valid_closed_and_non_empty(task):
    if task.task_id != "nyc_pickups_h1":
        pytest.skip("polygon check applies to NYC taxi zones only")
    shapely_geometry = pytest.importorskip("shapely.geometry")
    from shapely.validation import explain_validity

    for f in task.entities["features"]:
        geom = shapely_geometry.shape(f["geometry"])
        assert geom.is_valid, f"zone {f['id']}: {explain_validity(geom)}"
        assert not geom.is_empty and geom.area > 0, f"zone {f['id']} has no area"
        polygons = (
            [f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"]
        )
        for poly in polygons:
            for ring in poly:
                assert ring[0] == ring[-1] and len(ring) >= 4, f"zone {f['id']}: ring not closed"
