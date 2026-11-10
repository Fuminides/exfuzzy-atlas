"""Shared helpers of the AT-062 QA tests over the *published* models (see ``conftest.py``).

The ground truth is read straight from the published Parquet/JSON files with DuckDB/pandas, never through the API
store, so a bug in the store cannot make a test agree with itself.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SEED = 20261031  # every sample below is drawn from random.Random(f"{SEED}-{task}-{what}")

TASK_IDS = ("madrid_no2_h6", "nyc_pickups_h1", "uk_water_do", "de_no2_h6")


@dataclass(frozen=True)
class Expect:
    """What each task is documented to be (MASTER_PLAN, CONTRACTS §9, docs/ml/*)."""

    domain: str
    task_type: str
    horizon_hours: int
    support: str
    geometries: frozenset[str]
    n_entities: int  # entities served (contract v0.4: includes the ones marked modelled = false)
    n_modelled: int
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max (sanity box, not a claim of precision)


EXPECT = {
    "madrid_no2_h6": Expect(
        "air", "classification", 6, "observed_point", frozenset({"Point"}), 24, 24, (-4.0, 40.2, -3.4, 40.7)
    ),
    "nyc_pickups_h1": Expect(
        "mobility",
        "classification",
        1,
        "observed_polygon",
        frozenset({"Polygon", "MultiPolygon"}),
        263,  # the 263 taxi zones with a polygon: 110 have a model, 153 are published as "sin modelo"
        110,
        (-74.3, 40.45, -73.65, 40.95),
    ),
    "uk_water_do": Expect(
        "water", "regression", 0, "observed_point", frozenset({"Point"}), 195, 195, (-3.2, 54.3, -0.5, 55.9)
    ),
    "de_no2_h6": Expect(
        "air", "classification", 6, "observed_point", frozenset({"Point"}),
        437,  # 440 EEA stations with 2025 rows; 3 have no official coordinates and are left out by publish
        437,
        (5.8, 47.2, 15.1, 55.1),
    ),
}


def nulls_as_none(df: pd.DataFrame) -> pd.DataFrame:
    """Text columns with ``None`` for a missing value, as the contract's ``null``.

    pandas 3 reads Parquet strings with its ``str`` dtype, where a missing value is ``NaN``; pandas 2 gave ``object``
    columns with ``None``. The ground truth below is compared with ``is None``, so both versions must give ``None``.
    """
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col].dtype):
            df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def published_dir() -> Path:
    return Path(os.environ.get("ATLAS_PUBLISHED_DIR") or REPO / "artifacts" / "published")


def iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def rng(task_id: str, what: str) -> random.Random:
    return random.Random(f"{SEED}-{task_id}-{what}")


class Task:
    """One published task, with its ground-truth tables read lazily from disk."""

    def __init__(self, root: Path, task_id: str, entry: dict):
        self.root, self.task_id, self.entry = root, task_id, entry
        self.model_id: str = entry["model_id"]
        self.path = root / self.model_id
        self.expect = EXPECT[task_id]
        self.classifier = entry["task_type"] == "classification"
        self.horizon = timedelta(hours=entry["horizon_hours"])

    def json(self, name: str) -> dict:
        return json.loads((self.path / name).read_text(encoding="utf-8"))

    @cached_property
    def rules(self) -> dict:
        return self.json("rules.json")

    @cached_property
    def mixture(self) -> bool:
        """Contract v0.7: a mixture-of-rules classifier (no rule decides alone; class scores and a top rule)."""
        return self.rules["inference"]["family"] == "rule_mixture_classifier"

    @cached_property
    def winning_rule(self) -> bool:
        return self.rules["inference"]["family"] == "winning_rule_classifier"

    @cached_property
    def rule_ids(self) -> list[str]:
        return [r["rule_id"] for r in self.rules["rules"]]

    @cached_property
    def class_of_rule(self) -> dict[str, str]:
        return {
            r["rule_id"]: r["consequent"]["term"] for r in self.rules["rules"] if r["consequent"]["type"] == "class"
        }

    @cached_property
    def labels(self) -> list[str]:
        scheme = self.rules.get("target_scheme")
        return [c["label"] for c in scheme["classes"]] if scheme else []

    @cached_property
    def spec(self) -> dict:
        return self.json("feature_spec.json")["features"]

    @cached_property
    def entities(self) -> dict:
        return self.json("entities.geojson")

    @cached_property
    def unmodelled_ids(self) -> set[str]:
        """Entities published with ``modelled = false`` (contract v0.4): drawn as "sin modelo", never given a value."""
        features = self.entities["features"]
        return {f["properties"]["entity_id"] for f in features if f["properties"].get("modelled") is False}

    @cached_property
    def preds(self) -> pd.DataFrame:
        return nulls_as_none(pd.read_parquet(self.path / "predictions.parquet"))

    @cached_property
    def inputs(self) -> pd.DataFrame:
        return nulls_as_none(pd.read_parquet(self.path / "inputs.parquet"))

    @cached_property
    def _db(self) -> duckdb.DuckDBPyConnection:
        db = duckdb.connect(config={"memory_limit": "1GB", "threads": 2})
        db.execute("SET TimeZone='UTC'")
        return db

    def activations(self, where: str = "TRUE", params: list | None = None) -> pd.DataFrame:
        """Rows of the firing table (hive columns dropped), straight from the Parquet files."""
        glob = str(self.path / "activations" / "*" / "*" / "*.parquet")
        return self._db.execute(
            f"SELECT * EXCLUDE (year, month) FROM read_parquet(?, hive_partitioning=true) WHERE {where}",
            [glob, *(params or [])],
        ).df().pipe(nulls_as_none)

    # ---- deterministic samples -------------------------------------------------------------------------------

    def sample_rows(self, n: int, what: str = "rows", where=None) -> pd.DataFrame:
        """``n`` (entity, issue time) rows of predictions.parquet, distinct issue times when possible."""
        df = self.preds if where is None else self.preds[where(self.preds)]
        times = sorted(df["issued_at_utc"].unique())
        chosen = rng(self.task_id, what).sample(times, min(n, len(times)))
        out = []
        for t in sorted(chosen):
            at = df[df["issued_at_utc"] == t]
            out.append(at.iloc[rng(self.task_id, f"{what}-{t}").randrange(len(at))])
        return pd.DataFrame(out)


def trace_params(task: Task, entity_id: str, issued) -> dict:
    return {"model_id": task.model_id, "at": iso(issued)}


def api_get(client, path: str, **params) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == 200, f"{path} {params} -> {response.status_code} {response.text[:300]}"
    return response.json()


def rule_map(client, task: Task, rule_id: str, **params) -> dict:
    return api_get(client, "/api/v1/rule-map", model_id=task.model_id, rule_id=rule_id, **params)


def trace(client, task: Task, entity_id: str, issued) -> dict:
    return api_get(client, f"/api/v1/entities/{entity_id}/rule-trace", model_id=task.model_id, at=iso(issued))


def series(client, task: Task, entity_id: str, start=None, end=None) -> dict:
    """Every point of the series in ``[start, end)``, following ``next_cursor``."""
    params = {"task_id": task.task_id, "entity_id": entity_id}
    if start is not None:
        params["from"] = iso(start)
    if end is not None:
        params["to"] = iso(end)
    out = None
    while True:
        page = api_get(client, "/api/v1/series", **params)
        out = page if out is None else {**out, "points": out["points"] + page["points"]}
        if not page["next_cursor"]:
            return out
        params["cursor"] = page["next_cursor"]


def feature_by_entity(response: dict) -> dict[str, dict]:
    return {f["properties"]["entity_id"]: f["properties"] for f in response["features"]}
