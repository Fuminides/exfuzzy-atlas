"""Feature/target table ``uk_water_do``: dissolved oxygen inferred from the other determinands of the same sample (AT-021).

    PYTHONPATH=src python -m atlas.domains.water.features --write-spec

This is a **descriptive, same-sample inference, not a forecast**. One row per river sample that has dissolved oxygen (DO,
determinand 9924, mg/l); the inputs are what the same sample says about ammoniacal nitrogen, orthophosphate, water
temperature and pH, plus calendar context of the sampling instant and (optionally) a train-period profile of the sampling
point. Rules learned on it describe associations in the archive, not causes.

Conventions (the tests pin them):

* ``issued_at_utc`` is the sample time and ``valid_at_utc == issued_at_utc``: there is no horizon, the target is measured on
  the very sample whose other determinands are the inputs. ``lag_hours = 0`` for every feature in ``feature_spec.json``
  means "same sample / same instant", not "available in real time" (the laboratory result date is not modelled).
* Censoring (``<x`` results): see :func:`encode_input`. A left-censored ammonia or phosphate result is raised to a
  common detection limit together with every value at or below it; nothing is substituted silently, the status of every
  row goes to the table and the counts to the report.
* Point context uses the rows of the chronological **train** period only and never the target.
"""

# ruff: noqa: E501  (prose)

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.contracts.models import SplitSpec
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "water" / "uk_water_do.json"
FEATURE_SPEC_PATH = REPO_ROOT / "configs" / "water" / "feature_spec.json"
TABLE_DIRNAME = "uk_water_do"
SOURCE_ID = "uk-water-quality"
CALENDAR_SOURCE_ID = "calendar-europe-london"
TARGET_FEATURE = "dissolved_oxygen"
KEYS = ("entity_id", "sample_id", "issued_at_utc", "valid_at_utc")
TARGET = "target"
POINT_CONTEXT = "point_median_phosphate_train"
SEED_HASH_BITS = 64

STATUSES = (
    "measured",
    "measured_at_common_limit",
    "measured_below_common_limit_raised",
    "censored_at_common_limit",
    "censored_below_common_limit_raised",
    "censored_above_common_limit_dropped",
    "right_censored_dropped",
    "censored_dropped",
    "missing",
)


@dataclass(frozen=True)
class Feature:
    name: str
    unit: str
    source_id: str
    lag_hours: float  # 0: observed on the same sample / at the same instant
    recommended: bool
    description: str


FEATURES: tuple[Feature, ...] = (
    Feature(
        "ammoniacal_nitrogen",
        "mg/l",
        SOURCE_ID,
        0,
        True,
        "determinand 0111, same sample; censored results harmonised to the common limit 0.03 mg/l (see encode_input)",
    ),
    Feature(
        "orthophosphate_reactive",
        "mg/l",
        SOURCE_ID,
        0,
        True,
        "determinand 0180, same sample; censored results harmonised to the common limit 0.01 mg/l",
    ),
    Feature("water_temperature", "degC", SOURCE_ID, 0, True, "determinand 0076, same sample"),
    Feature("ph", "pH", SOURCE_ID, 0, True, "determinand 0061, same sample"),
    Feature(
        "days_from_midwinter",
        "days",
        CALENDAR_SOURCE_ID,
        0,
        True,
        "days between the local sample date and the nearest 21 December (0 = midwinter, about 183 = midsummer); no seam at New Year",
    ),
    Feature(
        "local_hour",
        "hour",
        CALENDAR_SOURCE_ID,
        0,
        True,
        "Europe/London clock time of the sample as decimal hours (10.5 = 10:30); dissolved oxygen has a daily cycle",
    ),
    Feature(
        "local_day_of_year",
        "day",
        CALENDAR_SOURCE_ID,
        0,
        False,
        "day of the year of the local sample date, 1-366; seam: 31 December and 1 January are far apart",
    ),
    Feature(
        POINT_CONTEXT,
        "mg/l",
        SOURCE_ID,
        0,
        False,
        "median harmonised orthophosphate of the sampling point over the chronological TRAIN period; null if fewer than min_train_samples; never uses DO",
    ),
)
FEATURE_NAMES = [f.name for f in FEATURES]
RECOMMENDED = [f.name for f in FEATURES if f.recommended]
INPUT_DETERMINANDS = ("ammoniacal_nitrogen", "orthophosphate_reactive", "water_temperature", "ph")


# ---------------------------------------------------------------------------------------------------- censoring


def encode_input(
    value: pd.Series, censoring: pd.Series, common_limit: float | None
) -> tuple[pd.Series, pd.Series]:
    """Numeric input and a per-row status from a (value, censoring) pair of the canonical observations.

    For a left-censored result the canonical ``value`` is the reported detection limit, not an estimate. Detection limits
    differ within the same determinand (ammonia ``<0.03`` and ``<0.002``), so ``value = limit`` would put a censored
    ``<0.03`` above a measured 0.01 although the former may be lower. With ``common_limit = L`` (the dominant limit) every
    result known to be ``<= L`` is encoded as ``L``:

    * measured ``> L``: kept (``measured``);
    * measured ``== L`` / ``< L`` and censored ``< L``: ``L`` (``measured_at_common_limit``,
      ``measured_below_common_limit_raised``, ``censored_at_common_limit``, ``censored_below_common_limit_raised``);
    * censored at a limit ``> L``, or right-censored: unknown relative to ``L`` -> null (``*_dropped``);
    * no result: null (``missing``).

    With ``common_limit = None`` (pH, temperature: no harmonisation wanted) any censored result is null (``censored_dropped``).
    The encoded value ``L`` therefore reads "at or below L"; below ``L`` the table has no information.
    """
    v = value.astype(float)
    cens = censoring.where(censoring.notna(), "").astype(str)
    out = v.copy()
    status = pd.Series("measured", index=v.index, dtype=object)
    missing = v.isna()
    left, right = cens.eq("left") & ~missing, cens.eq("right") & ~missing
    measured = ~missing & ~left & ~right
    status[missing] = "missing"
    out[missing] = np.nan
    if common_limit is None:
        dropped = left | right
        status[dropped] = "censored_dropped"
        out[dropped] = np.nan
        return out, status
    atol = 1e-12
    at = np.isclose(v, common_limit, rtol=0, atol=atol)
    below = (v < common_limit) & ~at
    above = (v > common_limit) & ~at
    status[right] = "right_censored_dropped"
    out[right] = np.nan
    status[left & at] = "censored_at_common_limit"
    status[left & below] = "censored_below_common_limit_raised"
    status[left & above] = "censored_above_common_limit_dropped"
    out[left & above] = np.nan
    out[left & (at | below)] = common_limit
    status[measured & at] = "measured_at_common_limit"
    status[measured & below] = "measured_below_common_limit_raised"
    out[measured & below] = common_limit
    return out, status


# ------------------------------------------------------------------------------------------------ observations


OBS_COLUMNS = (
    "entity_id",
    "timestamp_utc",
    "feature_name",
    "value",
    "censoring",
    "sample_id",
    "sample_material",
    "sampling_purpose",
    "data_version",
)


def read_observations(observations: Path) -> pd.DataFrame:
    """Canonical water observations (hive Parquet written by ``ingest``), only the columns this table needs."""
    return pd.read_parquet(Path(observations), columns=list(OBS_COLUMNS))


def read_unlocated_entities(entities_geojson: Path) -> dict[str, str]:
    """``entity_id -> reason`` of sampling points whose geometry is null (placeholder or missing coordinates)."""
    collection = json.loads(Path(entities_geojson).read_text(encoding="utf-8"))
    out = {}
    for feature in collection["features"]:
        if feature["geometry"] is None:
            props = feature["properties"]
            out[props["entity_id"]] = (props.get("attributes") or {}).get("coordinate_flag") or "no_coordinates"
    return out


def pivot_samples(obs: pd.DataFrame, determinands: list[str]) -> pd.DataFrame:
    """One row per sample: identifiers, ``<det>`` value and ``<det>__censoring`` for each determinand (joined on ``sample_id``).

    A sample whose observations disagree on instant, point or material is an error (the API gives one per sample);
    a (sample, determinand) pair that repeats is an error too, so the join cannot multiply rows.
    """
    obs = obs[obs["feature_name"].isin(determinands)]
    if obs.duplicated(["sample_id", "feature_name"]).any():
        raise ValueError("a (sample_id, feature_name) pair appears more than once")
    for column in ("entity_id", "timestamp_utc", "sample_material"):
        if (obs.groupby("sample_id")[column].nunique() > 1).any():
            raise ValueError(f"observations of one sample disagree on {column}")
    head = obs.groupby("sample_id", sort=True).agg(
        entity_id=("entity_id", "first"),
        issued_at_utc=("timestamp_utc", "first"),
        sample_material=("sample_material", "first"),
        sampling_purpose=("sampling_purpose", "first"),
    )
    values = obs.pivot(index="sample_id", columns="feature_name", values="value").reindex(columns=determinands)
    cens = obs.pivot(index="sample_id", columns="feature_name", values="censoring").reindex(columns=determinands)
    cens.columns = [f"{c}__censoring" for c in cens.columns]
    return head.join(values).join(cens).reset_index()


# ----------------------------------------------------------------------------------------------- calendar


def season_features(issued_at_utc: pd.Series, timezone_name: str) -> pd.DataFrame:
    """Calendar context of the local sampling instant (all numeric, none a 0/1 flag)."""
    local = pd.DatetimeIndex(issued_at_utc).tz_convert(timezone_name)
    date = pd.DatetimeIndex(local.tz_localize(None).normalize())
    distances = []
    for shift in (-1, 0, 1):
        midwinter = pd.to_datetime({"year": date.year + shift, "month": 12, "day": 21})
        distances.append(np.abs((date - pd.DatetimeIndex(midwinter)).days.to_numpy()))
    return pd.DataFrame(
        {
            "days_from_midwinter": np.minimum.reduce(distances).astype(float),
            "local_hour": local.hour + local.minute / 60 + local.second / 3600,
            "local_day_of_year": local.day_of_year.astype(float),
        },
        index=issued_at_utc.index,
    )


# ---------------------------------------------------------------------------------------------------- table


def parse_utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_convert("UTC") if pd.Timestamp(text).tzinfo else pd.Timestamp(text, tz="UTC")


def split_spec(config: dict) -> SplitSpec:
    s = config["split"]
    return SplitSpec(
        train_from_utc=parse_utc(s["train"][0]),
        train_to_utc=parse_utc(s["train"][1]),
        validation_from_utc=parse_utc(s["validation"][0]),
        validation_to_utc=parse_utc(s["validation"][1]),
        test_from_utc=parse_utc(s["test"][0]),
        test_to_utc=parse_utc(s["test"][1]),
        embargo_hours=s["embargo_hours"],
    )


def point_context(
    issued_at_utc: pd.Series,
    entity_id: pd.Series,
    values: pd.Series,
    train_from: pd.Timestamp,
    train_to: pd.Timestamp,
    min_samples: int,
) -> pd.Series:
    """Per-row median of ``values`` over the point's rows in ``[train_from, train_to)``; null with fewer than ``min_samples``.

    Only the ``values`` column (an input, never the target) and only train-period rows enter, so a row's context cannot
    depend on anything later than the train period. The row's own value is part of the median when the row is in train
    (not leave-one-out), which makes train contexts slightly closer to the row's own input than test contexts.
    """
    in_train = (issued_at_utc >= train_from) & (issued_at_utc < train_to) & values.notna()
    stats = values[in_train].groupby(entity_id[in_train]).agg(["median", "count"])
    stats = stats[stats["count"] >= min_samples]
    return entity_id.map(stats["median"]).astype(float)


def build_table(
    obs: pd.DataFrame, config: dict, unlocated: dict[str, str] | None = None
) -> tuple[pd.DataFrame, dict]:
    """The ``uk_water_do`` table and the report of everything excluded or recoded. See the module docstring."""
    unlocated = unlocated or {}
    inputs = config["inputs"]
    determinands = [TARGET_FEATURE, *inputs]
    wide = pivot_samples(obs, determinands)
    report: dict = {"samples_in_observations": int(len(wide))}

    do = wide[TARGET_FEATURE]
    do_cens = wide[f"{TARGET_FEATURE}__censoring"]
    has_do = do.notna()
    report["samples_without_dissolved_oxygen"] = int((~has_do).sum())
    target_censored = has_do & do_cens.notna()
    material = wide["sample_material"] != config["sample_material"]
    no_geometry = wide["entity_id"].isin(unlocated)
    implausible = has_do & (do > config["target"]["plausible_max"])
    report["independent"] = {  # among samples with DO, each condition alone
        "target_censored": int(target_censored.sum()),
        "non_river_sample_material": int((has_do & material).sum()),
        "unlocated_sampling_point": int((has_do & no_geometry).sum()),
        "target_above_plausible_max": int(implausible.sum()),
    }
    keep = has_do.copy()
    sequential = {"samples_with_dissolved_oxygen": int(keep.sum())}
    for name, drop in (
        ("target_censored", target_censored),
        ("non_river_sample_material", material),
        ("unlocated_sampling_point", no_geometry),
        ("target_above_plausible_max", implausible),
    ):
        removed = keep & drop
        sequential[f"removed_{name}"] = int(removed.sum())
        keep &= ~drop
    sequential["table_rows"] = int(keep.sum())
    report["sequential"] = sequential
    report["unlocated_points"] = {
        k: {"reason": v, "do_samples": int(((wide["entity_id"] == k) & has_do).sum())} for k, v in sorted(unlocated.items())
    }
    report["non_river_materials"] = (
        wide[has_do & material]["sample_material"].value_counts().sort_index().astype(int).to_dict()
    )

    rows = wide[keep].sort_values(["entity_id", "issued_at_utc", "sample_id"]).reset_index(drop=True)
    issued = pd.to_datetime(rows["issued_at_utc"], utc=True).astype("datetime64[us, UTC]")
    table = pd.DataFrame(
        {
            "entity_id": rows["entity_id"].astype(str),
            "sample_id": rows["sample_id"].astype(str),
            "issued_at_utc": issued,
            "valid_at_utc": issued,
            TARGET: rows[TARGET_FEATURE].astype(float),
        }
    )
    statuses = {}
    for name, spec in inputs.items():
        encoded, status = encode_input(rows[name], rows[f"{name}__censoring"], spec["common_limit"])
        table[name] = encoded.astype(float)
        statuses[name] = status
        report.setdefault("input_status", {})[name] = {
            s: int((status == s).sum()) for s in STATUSES if (status == s).any()
        }
    for name, series in season_features(table["issued_at_utc"], config["timezone"]).items():
        table[name] = series
    s = config["split"]
    ctx = config["point_context"]
    table[POINT_CONTEXT] = point_context(
        table["issued_at_utc"],
        table["entity_id"],
        table[ctx["input"]],
        parse_utc(s["train"][0]),
        parse_utc(s["train"][1]),
        ctx["min_train_samples"],
    )
    table = table[[*KEYS, TARGET, *FEATURE_NAMES]]
    for name in ("ammoniacal_nitrogen", "orthophosphate_reactive"):  # audit columns, not features
        table[f"{name}_status"] = statuses[name].to_numpy()
    table["sampling_purpose"] = rows["sampling_purpose"].astype(str).to_numpy()
    if table.duplicated(["entity_id", "issued_at_utc"]).any():
        raise ValueError("duplicate (entity_id, issued_at_utc): the pipeline of A4 needs a unique key")
    if len(table) != sequential["table_rows"]:
        raise ValueError("row count differs from the number of kept DO samples")
    report["data_version"] = _single(obs["data_version"])
    return table, report


def _single(values: pd.Series) -> str:
    unique = values.dropna().unique()
    if len(unique) != 1:
        raise ValueError(f"expected one data_version, found {list(unique)}")
    return str(unique[0])


def complete_mask(table: pd.DataFrame) -> pd.Series:
    """Target and every recommended feature finite."""
    return table[[TARGET, *RECOMMENDED]].notna().all(axis=1)


# ---------------------------------------------------------------------------------------------------- splits


def chronological_assignment(issued_at_utc: pd.Series, spec: SplitSpec) -> pd.Series:
    """``train`` / ``validation`` / ``test`` by half-open periods; rows in an embargo gap or outside get ``gap``."""
    t = pd.DatetimeIndex(issued_at_utc)
    out = pd.Series("gap", index=issued_at_utc.index, dtype=object)
    for name, lo, hi in (
        ("train", spec.train_from_utc, spec.train_to_utc),
        ("validation", spec.validation_from_utc, spec.validation_to_utc),
        ("test", spec.test_from_utc, spec.test_to_utc),
    ):
        out[np.asarray((t >= lo) & (t < hi))] = name
    return out


def spatial_group(entity_id: str, seed: int, fractions: dict[str, float]) -> str:
    """Group of a whole sampling point, from ``sha256("<seed>:<entity_id>")``: independent of the data and of any library RNG."""
    digest = hashlib.sha256(f"{seed}:{entity_id}".encode()).digest()
    u = int.from_bytes(digest[: SEED_HASH_BITS // 8], "big") / 2**SEED_HASH_BITS
    edge = 0.0
    for name in ("train", "validation", "test"):
        edge += fractions[name]
        if u < edge - 1e-12:
            return name
    return "test"


def spatial_assignment(entity_id: pd.Series, seed: int, fractions: dict[str, float]) -> pd.Series:
    groups = {e: spatial_group(e, seed, fractions) for e in entity_id.unique()}
    return entity_id.map(groups)


# ---------------------------------------------------------------------------------------------------- report


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


def split_counts(table: pd.DataFrame, assignment: pd.Series) -> dict:
    complete = complete_mask(table)
    out = {}
    for name in ("train", "validation", "test", "gap"):
        mask = assignment == name
        if mask.any() or name != "gap":
            out[name] = {
                "rows": int(mask.sum()),
                "complete_rows": int((mask & complete).sum()),
                "points": int(table.loc[mask, "entity_id"].nunique()),
                "points_complete": int(table.loc[mask & complete, "entity_id"].nunique()),
            }
    return out


def censoring_sensitivity(obs_wide: pd.DataFrame, config: dict) -> dict:
    """Descriptive rank correlation of DO with ammonia / phosphate under alternative censoring encodings (no model)."""
    out = {}
    for name in ("ammoniacal_nitrogen", "orthophosphate_reactive"):
        limit = config["inputs"][name]["common_limit"]
        value = obs_wide[name].astype(float)
        censored = obs_wide[f"{name}__censoring"].eq("left")
        target = obs_wide[TARGET_FEATURE]
        ok = value.notna() & ~obs_wide[f"{name}__censoring"].eq("right") & target.notna()
        encodings = {
            "value_at_reported_limit": value,
            "half_of_reported_limit": value.where(~censored, value / 2),
            "harmonised_common_limit": encode_input(value, obs_wide[f"{name}__censoring"], limit)[0],
            "uncensored_rows_only": value.where(~censored),
        }
        entry = {}
        for label, enc in encodings.items():
            m = ok & enc.notna()
            entry[label] = {"n": int(m.sum()), "spearman_with_do": round(_spearman(target[m], enc[m]), 4)}
        out[name] = entry
    return out


def describe(table: pd.DataFrame, config: dict, obs_wide: pd.DataFrame, spec: SplitSpec) -> dict:
    """Coverage, distribution, split counts and descriptive associations. Everything here is computed on all kept rows."""
    complete = complete_mask(table)
    local_year = pd.DatetimeIndex(table["issued_at_utc"]).tz_convert(config["timezone"]).year
    by_year = pd.DataFrame({"year": local_year, "complete": complete, "entity": table["entity_id"]}).groupby("year")
    per_year = {
        int(y): {
            "rows": int(len(g)),
            "complete_rows": int(g["complete"].sum()),
            "points": int(g["entity"].nunique()),
        }
        for y, g in by_year
    }
    per_point = table.groupby("entity_id").size()
    per_point_complete = table[complete].groupby("entity_id").size()
    quantiles = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
    y = table[TARGET]
    do_distribution = {
        "n": int(y.notna().sum()),
        "mean": float(y.mean()),
        "std": float(y.std()),
        "min": float(y.min()),
        "max": float(y.max()),
        "quantiles": {str(q): float(y.quantile(q)) for q in quantiles},
        "share_below_mg_l": {str(t): round(float((y < t).mean()), 4) for t in (3, 5, 7, 8, 9, 10)},
        "count_below_mg_l": {str(t): int((y < t).sum()) for t in (3, 5, 7, 8, 9, 10)},
    }
    c = table[complete]
    corr = {f: round(_spearman(c[TARGET], c[f]), 4) for f in RECOMMENDED}
    tertiles = pd.qcut(c["water_temperature"].rank(method="first"), 3, labels=["cold", "mid", "warm"])
    within = {
        str(t): {
            f: round(_spearman(g[TARGET], g[f]), 4)
            for f in ("ammoniacal_nitrogen", "orthophosphate_reactive", "ph")
        }
        | {"n": int(len(g)), "temperature_range": [float(g["water_temperature"].min()), float(g["water_temperature"].max())]}
        for t, g in c.groupby(tertiles, observed=True)
    }
    month = pd.DatetimeIndex(table["issued_at_utc"]).tz_convert(config["timezone"]).month
    by_month = y.groupby(month).agg(["count", "mean", "std"]).round(3)
    assign = chronological_assignment(table["issued_at_utc"], spec)
    train_points = set(table.loc[assign == "train", "entity_id"])
    unseen = {
        name: {
            "rows_at_points_unseen_in_train": int((~table.loc[assign == name, "entity_id"].isin(train_points)).sum()),
            "rows": int((assign == name).sum()),
        }
        for name in ("validation", "test")
    }
    fractions = config["spatial_split"]["fractions"]
    spatial = spatial_assignment(table["entity_id"], config["spatial_split"]["seed"], fractions)
    return {
        "rows": int(len(table)),
        "complete_rows": int(complete.sum()),
        "complete_share": round(float(complete.mean()), 4),
        "points": int(table["entity_id"].nunique()),
        "points_complete": int(c["entity_id"].nunique()),
        "issued_from_utc": table["issued_at_utc"].min().isoformat(),
        "issued_to_utc": table["issued_at_utc"].max().isoformat(),
        "whole_number_features_with_at_most_5_distinct_values": [  # ex_fuzzy would auto-categorise these
            f
            for f in FEATURE_NAMES
            if table[f].dropna().nunique() <= 5 and (table[f].dropna() % 1 == 0).all()
        ],
        "nulls_by_column": {k: int(v) for k, v in table[[TARGET, *FEATURE_NAMES]].isna().sum().items()},
        "per_year": per_year,
        "samples_per_point": {
            "all_rows": {str(q): float(per_point.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
            | {"max": int(per_point.max()), "points_with_at_least_12": int((per_point >= 12).sum())},
            "complete_rows": {str(q): float(per_point_complete.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
            | {"max": int(per_point_complete.max()), "points_with_at_least_12": int((per_point_complete >= 12).sum())},
        },
        "do_distribution": do_distribution,
        "do_by_local_month": {
            int(m): {"n": int(r["count"]), "mean": float(r["mean"]), "std": float(r["std"])} for m, r in by_month.iterrows()
        },
        "spearman_do_vs_feature_complete_rows": corr,
        "spearman_do_vs_feature_within_temperature_tertile": within,
        "censoring_sensitivity": censoring_sensitivity(obs_wide[obs_wide["sample_id"].isin(table["sample_id"])], config),
        "chronological_split": {
            "spec": json.loads(spec.model_dump_json()),
            "counts": split_counts(table, assign),
            "unseen_points": unseen,
        },
        "spatial_split": {
            "seed": config["spatial_split"]["seed"],
            "fractions": fractions,
            "counts": split_counts(table, spatial),
            "points": {
                name: sorted(table.loc[spatial == name, "entity_id"].unique().tolist())
                for name in ("train", "validation", "test")
            },
        },
    }


# ---------------------------------------------------------------------------------------------------- output


def feature_spec() -> dict:
    return {
        "features": {
            f.name: {"unit": f.unit, "source_id": f.source_id, "lag_hours": f.lag_hours} for f in FEATURES
        }
    }


def write_table(table: pd.DataFrame, table_dir: Path) -> None:
    if table_dir.exists():
        shutil.rmtree(table_dir)
    out = table.copy()
    issued = pd.DatetimeIndex(out["issued_at_utc"])  # UTC, as in the other tables
    out["year"], out["month"] = issued.year.astype("int32"), issued.month.astype("int32")
    arrow = pa.Table.from_pandas(out, preserve_index=False)
    pq.write_to_dataset(arrow, str(table_dir), partition_cols=["year", "month"], compression="zstd")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(
    *,
    config: dict | None = None,
    water_dir: Path | None = None,
    out_dir: Path | None = None,
    write_spec: bool = False,
    spec_path: Path = FEATURE_SPEC_PATH,
    log=print,
) -> dict:
    config = config or load_config()
    water_dir = water_dir or PROCESSED_DIR / "water"
    out_dir = out_dir or water_dir / "features"
    obs = read_observations(water_dir / "observations")
    unlocated = read_unlocated_entities(water_dir / "entities.geojson")
    table, report = build_table(obs, config, unlocated)
    spec = split_spec(config)
    wide = pivot_samples(obs, [TARGET_FEATURE, *config["inputs"]])
    report["summary"] = describe(table, config, wide, spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_table(table, out_dir / TABLE_DIRNAME)
    spatial = report["summary"]["spatial_split"]
    (out_dir / f"{TABLE_DIRNAME}_spatial_split.json").write_text(
        json.dumps(
            {"seed": spatial["seed"], "fractions": spatial["fractions"], "hash": "sha256('<seed>:<entity_id>') first 8 bytes / 2**64", "points": spatial["points"]},
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    report["task_id"] = config["task_id"]
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (out_dir / f"{TABLE_DIRNAME}_feature_report.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    if write_spec:
        spec_path.write_text(json.dumps(feature_spec(), indent=2) + "\n", encoding="utf-8")
    log(
        f"{len(table)} rows ({report['summary']['complete_rows']} complete), "
        f"{report['summary']['points']} points -> {out_dir / TABLE_DIRNAME}"
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the uk_water_do feature/target table from the water observations.")
    parser.add_argument("--water-dir", type=Path, default=None, help="default: data/processed/water")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <water-dir>/features")
    parser.add_argument("--write-spec", action="store_true", help=f"also write {FEATURE_SPEC_PATH.relative_to(REPO_ROOT)}")
    args = parser.parse_args(argv)
    run(water_dir=args.water_dir, out_dir=args.out_dir, write_spec=args.write_spec)


if __name__ == "__main__":
    main()
