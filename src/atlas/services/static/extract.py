"""Writers of every file group of the static export (docs/static_export.md sections 3-9).

Exact bodies come from the real FastAPI app (``TestClient``); shards come from the same ``ArtifactStore`` (predictions),
the published Parquet tables (firing, inputs, window statistics) and the ex_fuzzy engine of ``atlas.explain``
(memberships, what-if). One model and one day at a time: memory stays bounded by a day of one model.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.static import engine, fmt
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

WHATIF_RULES = {"nyc": "daily_13utc"}  # every other regular territory: weekly_wed_12utc; irregular: all_samples


# ------------------------------------------------------------------------------------------------ output tree
class Out:
    """``<root>/data/<export_id>/`` (deployed), ``<root>/golden/<export_id>/`` (tests); atomic allow-listed writes."""

    def __init__(self, root: Path, export_id: str, *, force: bool = False):
        self.root, self.export_id, self.force = Path(root), export_id, force
        self.data = self.root / "data" / export_id
        self.golden = self.root / "golden" / export_id
        self.work = self.root / "work" / export_id  # scratch outside the deployable tree
        for d in (self.data, self.golden, self.work):
            d.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str, *, golden: bool = False) -> Path:
        fmt.check_allowed(rel)
        return (self.golden if golden else self.data) / rel

    def exists(self, rel: str) -> bool:
        return self.path(rel).is_file()

    def write(self, rel: str, obj, *, golden: bool = False) -> int:
        target = self.path(rel, golden=golden)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = fmt.gz(fmt.dumps(obj))
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
        return len(raw)

    def read(self, rel: str):
        return json.loads(fmt.unzip(self.path(rel).read_bytes()))


# ------------------------------------------------------------------------------------------------ context
@dataclass
class ModelCtx:
    task_id: str
    entry: layout.RegistryEntry
    h: object  # artifact_store._Published
    modelled: list[str]
    eidx: dict[str, int]
    regular: bool
    keys: list[str]
    days: list[str]  # UTC days with rows (for window statistics; = keys when regular)
    first: datetime  # first and last issue time exported: the card coverage clipped to the period
    last: datetime
    step_hours: int
    pairs: list[tuple[str, str, str]]  # (feature, operator, term): the P axis of mem shards
    period: tuple[datetime, datetime] | None = None  # None: the whole coverage
    full: tuple[datetime, datetime] | None = None  # the card coverage
    family: m.InferenceFamily = field(init=False)

    def __post_init__(self):
        self.family = self.h.rules.inference.family

    @property
    def model_id(self) -> str:
        return self.h.model_id

    @property
    def bounds(self) -> tuple[datetime, datetime]:
        """``[lo, hi)`` that contains every exported issue time."""
        if self.period is None:
            return datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2200, 1, 1, tzinfo=timezone.utc)
        return self.first, self.last + timedelta(hours=self.step_hours)

    def clip(self, lo: datetime, hi: datetime) -> tuple[datetime, datetime]:
        b_lo, b_hi = self.bounds
        return max(lo, b_lo), min(hi, b_hi)


class Ctx:
    def __init__(self, published: Path, out: Out, *, memory_limit: str = "1GB", threads: int = 2,
                 periods: dict[str, tuple[datetime, datetime]] | None = None):
        self.published, self.out = Path(published), out
        self.periods = periods or {}  # task_id -> (first, last) issue time; absent: the whole coverage
        self.store = ArtifactStore(self.published, memory_limit="768MB", threads=threads)
        self.client = TestClient(create_app(self.store))
        self.db = duckdb.connect(config={"memory_limit": memory_limit, "threads": threads})
        self.db.execute("SET TimeZone='UTC'")
        self.registry = layout.read_registry(self.published)
        self._models: dict[str, ModelCtx] = {}

    def get(self, url: str, **params):
        r = self.client.get(url, params=params)
        return r

    def exact(self, url: str, **params) -> dict | None:
        """The API's own body (redacted), or None for a 404 (the file is then simply absent)."""
        r = self.get(url, **params)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(f"{url} {params}: HTTP {r.status_code} {r.text[:200]}")
        return fmt.redact(r.json())

    def query(self, sql: str, params: list | None = None):
        return self.db.execute(sql, params or []).fetchall()

    def frame(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.db.execute(sql, params or []).df()

    # ------------------------------------------------------------------------------------------ model context
    def model(self, task_id: str) -> ModelCtx:
        if task_id in self._models:
            return self._models[task_id]
        entry = self.registry.tasks[task_id]
        fmt.check_id(task_id)
        fmt.check_id(entry.model_id)
        h = self.store._model(entry.model_id)
        modelled = [f.properties.entity_id for f in h.entities.features if f.properties.modelled is not False]
        for eid in modelled:
            fmt.check_id(eid)
        cov = h.card.coverage
        regular = cov is None or cov.regular
        pred = str(h.path / layout.PREDICTIONS_FILE)
        period = self.periods.get(task_id)
        step = cov.step_hours if cov else 1
        p_lo, p_hi = (period[0], period[1] + timedelta(hours=step)) if period else (
            datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2200, 1, 1, tzinfo=timezone.utc))
        days = [r[0] for r in self.query(
            "SELECT DISTINCT strftime(issued_at_utc, '%Y-%m-%d') d FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ? ORDER BY 1", [pred, p_lo, p_hi])]
        if not days:
            raise ValueError(f"{task_id}: no rows in the period")
        if regular and cov is not None and cov.step_hours != 1:
            raise ValueError(f"{task_id}: regular tasks must have step_hours = 1 (got {cov.step_hours})")
        first, last = (cov.issued_from_utc, cov.issued_to_utc) if cov else (None, None)
        if cov is None:
            lo, hi = self.query("SELECT min(issued_at_utc), max(issued_at_utc) FROM read_parquet(?)", [pred])[0]
            first, last = lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)
        full = (first, last)
        if period:
            first, last = max(first, period[0]), min(last, period[1])
        mc = ModelCtx(task_id, entry, h, modelled, {e: i for i, e in enumerate(modelled)}, regular,
                      days if regular else ["all"], days, first, last, step, antecedent_pairs(h.rules),
                      period=period, full=full)
        self._models[task_id] = mc
        return mc


CONDITION_OPERATORS = ("is", "at_least", "at_most", "any_of")


def antecedent_pairs(rules: m.ModelRules) -> list[tuple[str, str, str]]:
    """The conditions the rules use as ``(feature, operator, term)``, in order of first appearance (P axis of ``mem``).

    A condition is one membership: the term's own for ``is``, the bounded sum of the covered terms for ``at_least`` /
    ``at_most`` / ``any_of`` (``term`` is then the threshold term or the compound's internal name; contract v0.8). This,
    ``engine.pair_positions`` and ``store._antecedent_traces`` are the only readers of the shape of an antecedent; an
    operator they do not know fails the export instead of writing memberships that mean something else.
    """
    pairs: list[tuple[str, str, str]] = []
    for rule in rules.rules:
        for a in rule.antecedents:
            if a.operator not in CONDITION_OPERATORS:
                raise NotImplementedError(f"{rules.model_id} {rule.rule_id}: unknown condition operator {a.operator!r}")
            key = (a.feature, a.operator, a.term)
            if key not in pairs:
                pairs.append(key)
    return pairs


# ------------------------------------------------------------------------------------------------ export id
def export_id_for(published: Path, tasks: list[str], explanations_dir: Path, extra: dict) -> str:
    registry = layout.read_registry(published)
    h = hashlib.sha256()
    h.update(f"format{fmt.FORMAT_VERSION}".encode())
    h.update(json.dumps(extra, sort_keys=True).encode())
    for task in sorted(tasks):
        entry = registry.tasks[task]
        h.update(json.dumps(entry.model_dump(mode="json"), sort_keys=True).encode())
        sums = Path(published) / entry.model_id / "SHA256SUMS"
        h.update(sums.read_bytes())
        expl = Path(explanations_dir) / f"{entry.model_id}.json"
        h.update(expl.read_bytes() if expl.is_file() else b"-")
    return h.hexdigest()[:12]


# ------------------------------------------------------------------------------------------------ static group
def export_static_files(ctx: Ctx, tasks: list[str]) -> dict[str, int]:
    """domains, entities, summary, card, rules, importance, explanation: the API's own bodies. {rel: bytes}."""
    sizes: dict[str, int] = {}
    out = ctx.out

    def put(rel, body):
        if body is not None:
            sizes[rel] = out.write(rel, body)

    put("domains.json.gz", ctx.exact("/api/v1/domains"))
    for task in tasks:
        mc = ctx.model(task)
        put(f"tasks/{task}/entities.json.gz", ctx.exact("/api/v1/entities", domain=mc.entry.domain.value, task_id=task))
        put(f"tasks/{task}/summary.json.gz", ctx.exact("/api/v1/summary", task_id=task))
        mid = mc.model_id
        for name, url in (("card", f"/api/v1/models/{mid}"), ("rules", f"/api/v1/models/{mid}/rules"),
                          ("importance", f"/api/v1/models/{mid}/importance"),
                          ("explanation", f"/api/v1/models/{mid}/explanation")):
            put(f"models/{mid}/{name}.json.gz", ctx.exact(url))
    return sizes


# ------------------------------------------------------------------------------------------------ inputs sharing
def assign_inputs(ctx: Ctx, tasks: list[str]) -> dict:
    """Which input columns can share one file: same territory, same name, identical values on the common keys.

    Returns ``{"base": {model_id: {feature: base_path}}, "members": {base_path: [model_id, ...]}}`` (cached).
    """
    cache = ctx.out.work / "input_groups.json"
    wanted = sorted(tasks)
    if cache.is_file():
        stored = json.loads(cache.read_text())
        if stored.get("tasks") == wanted:
            return stored
    base: dict[str, dict[str, str]] = {}
    members: dict[str, list[str]] = {}
    variants: dict[tuple[str, str], list[str]] = defaultdict(list)  # (territory, name) -> base paths
    for task in wanted:
        mc = ctx.model(task)
        if not mc.regular:
            base[mc.model_id] = {f: f"models/{mc.model_id}/inputs/{f}" for f in mc.h.features}
            continue
        territory = mc.entry.territory or mc.entry.domain.value
        fmt.check_id(territory)
        path = str(mc.h.path / layout.INPUTS_FILE)
        base[mc.model_id] = {}
        for feature in mc.h.features:
            chosen = None
            for cand in variants[(territory, feature)]:
                if all(_same_column(ctx, path, str(ctx.model_of(other).h.path / layout.INPUTS_FILE), feature)
                       for other in members[cand]):
                    chosen = cand
                    break
            if chosen is None:
                n = len(variants[(territory, feature)]) + 1
                chosen = f"inputs/{territory}/{feature}" + ("" if n == 1 else f"-{n}")
                variants[(territory, feature)].append(chosen)
                members[chosen] = []
            members[chosen].append(mc.model_id)
            base[mc.model_id][feature] = chosen
    result = {"tasks": wanted, "base": base, "members": members}
    tmp = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")  # several processes may race here: same content
    tmp.write_text(json.dumps(result, indent=1))
    tmp.replace(cache)
    return result


def _same_column(ctx: Ctx, a: str, b: str, feature: str) -> bool:
    n, bad = ctx.query(
        f'SELECT count(*), count(*) FILTER (WHERE x."{feature}" IS DISTINCT FROM y."{feature}") '
        "FROM read_parquet(?) x JOIN read_parquet(?) y USING (entity_id, issued_at_utc)", [a, b])[0]
    return n > 0 and bad == 0


def _model_of(self: Ctx, model_id: str) -> ModelCtx:
    for task, entry in self.registry.tasks.items():
        if entry.model_id == model_id:
            return self.model(task)
    raise KeyError(model_id)


Ctx.model_of = _model_of  # type: ignore[attr-defined]


def _epoch(series) -> np.ndarray:
    idx = pd.DatetimeIndex(series)
    idx = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    return idx.tz_localize(None).to_numpy("datetime64[s]").astype("int64")


def export_inputs(ctx: Ctx, territory_models: list[str], groups: dict, day: str) -> int:
    """Lattice files of one UTC day for one territory (all of its regular models): the union over the members."""
    day_lo = fmt.utc_midnight(day)
    mcs = [ctx.model(t) for t in territory_models]
    modelled = mcs[0].modelled
    for mc in mcs:
        if mc.modelled != modelled:
            raise ValueError("models of one territory must have the same modelled entities, in the same order")
    n_e = len(modelled)
    eidx = mcs[0].eidx
    lattices: dict[str, np.ndarray] = {}
    for mc in mcs:
        lo, hi = mc.clip(day_lo, day_lo + fmt.DAY)
        cols = ", ".join(f'"{f}"' for f in mc.h.features)
        frame = ctx.frame(
            f"SELECT entity_id, issued_at_utc, {cols} FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ?",
            [str(mc.h.path / layout.INPUTS_FILE), lo, hi])
        if frame.empty:
            continue
        e = frame["entity_id"].map(eidx).to_numpy(dtype=float)
        ok = ~np.isnan(e)
        hour = ((_epoch(frame["issued_at_utc"]) - int(day_lo.timestamp())) // 3600)[ok]
        slot = hour * n_e + e[ok].astype(int)
        for feature in mc.h.features:
            base = groups["base"][mc.model_id][feature]
            lat = lattices.setdefault(base, np.full(24 * n_e, np.nan))
            vals = frame[feature].to_numpy(dtype=float)[ok]
            keep = ~np.isnan(vals)
            lat[slot[keep]] = vals[keep]
    written = 0
    for base, lat in lattices.items():
        written += ctx.out.write(
            f"{base}/{day}.json.gz", {"v": 1, "kind": "inputs", "layout": "lattice", "values": lat})
    return written


# ------------------------------------------------------------------------------------------------ meta
def feature_units(ctx: Ctx, mc: ModelCtx):
    """(trace_unit by feature, InferenceSpec JSON, texts) from a real trace of the model (store.rule_trace)."""
    h = mc.h
    cond = " AND ".join(f'"{f}" IS NOT NULL' for f in h.features)
    rows = ctx.query(f"SELECT entity_id, issued_at_utc FROM read_parquet(?) WHERE {cond} LIMIT 1",
                     [str(h.path / layout.INPUTS_FILE)])
    if not rows:
        raise ValueError(f"{mc.task_id}: no complete input row to read the trace units from")
    trace = ctx.store.rule_trace(h.model_id, rows[0][0], rows[0][1])
    texts: dict[str, str] = {}
    if h.classifier:  # the warning of a trace whose label the published row withholds, from the API's own code
        texts["no_reference_warning"] = ArtifactStore._without_reference(trace).quality.warnings[-1]
    return {fv.feature: fv.unit for fv in trace.feature_values}, trace.inference.model_dump(mode="json"), texts


def calendar_days(mc: ModelCtx) -> list[str]:
    """Every UTC day of the exported range, with or without rows (a window is recognised wherever it overlaps it)."""
    d, last, out = fmt.utc_midnight(fmt.day_key(mc.first)), fmt.utc_midnight(fmt.day_key(mc.last)), []
    while d <= last:
        out.append(fmt.day_key(d))
        d += fmt.DAY
    return out


def windows_of(mc: ModelCtx) -> dict:
    """Window starts (day keys) of each kind that overlap the exported range, and whether the coverage window fits."""
    result: dict = {}
    for kind in fmt.WINDOW_KINDS:
        starts = sorted({fmt.day_key(fmt.window_of(kind, fmt.utc_midnight(d))[0]) for d in calendar_days(mc)})
        result[kind] = starts
    result["coverage"] = fmt.coverage_fits(mc.first, mc.last, mc.step_hours)
    return result


def whatif_instants(mc: ModelCtx) -> tuple[str, list[str] | None]:
    """The featured instants of a regular model (docs section 9); ``None`` for irregular ones (every sample)."""
    if not mc.regular:
        return "all_samples", None
    territory = mc.entry.territory or ""
    rule = WHATIF_RULES.get(territory, "weekly_wed_12utc")
    out = []
    for d in mc.days:
        day = fmt.utc_midnight(d)
        if rule == "daily_13utc":
            at = day + timedelta(hours=13)
        elif day.weekday() == 2:
            at = day + timedelta(hours=12)
        else:
            continue
        if mc.first <= at <= mc.last:
            out.append(fmt.iso(at))
    return rule, out


def build_meta(ctx: Ctx, mc: ModelCtx, groups: dict, *, with_whatif: bool = True) -> dict:
    h, e = mc.h, mc.entry
    if set(engine.antecedent_features(h.model, mc.family)) != set(h.features):
        raise ValueError(f"{mc.task_id}: the rule base inputs differ from the manifest features")
    trace_units, inference, texts = feature_units(ctx, mc)
    rule, instants = whatif_instants(mc)
    return {
        "format_version": fmt.FORMAT_VERSION, "model_id": h.model_id, "task_id": mc.task_id, "domain": e.domain.value,
        "territory": e.territory, "task_type": e.task_type, "family": mc.family.value, "data_version": h.data_version,
        "synthetic": h.synthetic, "target": e.target, "unit": e.unit, "target_unit": h.target_unit,
        "horizon_hours": e.horizon_hours, "antecedent_order": engine.antecedent_features(h.model, mc.family),
        "regular": mc.regular, "step_hours": mc.step_hours,
        "coverage": {"from": fmt.iso(mc.first), "to": fmt.iso(mc.last)},
        "full_coverage": {"from": fmt.iso(mc.full[0]), "to": fmt.iso(mc.full[1])},
        "period": None if mc.period is None else {"from": fmt.iso(mc.period[0]), "to": fmt.iso(mc.period[1])},
        "keys": mc.keys, "entities": mc.modelled, "rules": h.rule_order, "classes": h.class_labels,
        "decides": bool(h.decides), "mixture": bool(h.mixture),
        "features": [
            {"name": f, "obs_unit": h.spec.features[f].unit, "trace_unit": trace_units.get(f),
             "source_id": h.spec.features[f].source_id, "lag_hours": h.spec.features[f].lag_hours,
             "input": groups["base"][h.model_id][f]}
            for f in h.features],
        "mem_pairs": [list(p) for p in mc.pairs], "inference": inference, "windows": windows_of(mc),
        "stories": {"tau": fmt.STORIES_TAU, "limit": fmt.STORIES_LIMIT}, "taus": fmt.TAUS, "texts": texts,
        "missing_reasons": fmt.MISSING_REASONS,
        "whatif": ({"rule": rule, "instants": instants, "steps": fmt.WHATIF_STEPS, "per_entity": True}
                   if with_whatif else None),
    }


# ------------------------------------------------------------------------------------------------ day shards
def _out_columns(mc: ModelCtx, out: dict[str, np.ndarray]) -> dict[str, list]:
    cols: dict[str, list] = {}
    if "pred" in out:
        cols["pred"] = out["pred"].tolist()
    if "plabel" in out:
        cols["plabel"] = [None if v < 0 else int(v) for v in out["plabel"]]
    if "decided" in out:
        cols["decided"] = [None if v < 0 else int(v) for v in out["decided"]]
    if "top" in out:
        cols["top"] = [None if v < 0 else int(v) for v in out["top"]]
        pairs = zip(out["top"], out["tshare"], strict=True)
        cols["tshare"] = [None if (t < 0 or np.isnan(s)) else float(s) for t, s in pairs]
    return cols


def export_day(ctx: Ctx, mc: ModelCtx, key: str) -> int:
    """pred, fire and mem of one shard (a UTC day, or ``all``); mem is written last and marks the shard done."""
    h, out = mc.h, ctx.out
    mid = h.model_id
    if out.exists(f"models/{mid}/{key}/mem.json.gz") and not out.force:
        return 0
    if key == "all":
        lo, hi = mc.bounds
    else:
        lo, hi = mc.clip(fmt.utc_midnight(key), fmt.utc_midnight(key) + fmt.DAY)
    pred_path = str(h.path / layout.PREDICTIONS_FILE)
    times = [r[0] for r in ctx.query(
        "SELECT DISTINCT issued_at_utc FROM read_parquet(?) WHERE issued_at_utc >= ? AND issued_at_utc < ? ORDER BY 1",
        [pred_path, lo, hi])]
    horizon = timedelta(hours=mc.entry.horizon_hours)
    classes = {c: i for i, c in enumerate(h.class_labels)}
    rules = {r: i for i, r in enumerate(h.rule_order)}
    cols: dict[str, list] = defaultdict(list)
    ti: list[int] = []
    ei: list[int] = []
    t_iso: list[str] = []
    for k, t in enumerate(times):
        t_iso.append(fmt.iso(t))
        resp = ctx.store.predictions(mc.task_id, t, None, None)
        for f in resp.features:
            p = f.properties
            e = mc.eidx.get(p.entity_id)
            if e is None or p.issued_at_utc is None:
                continue
            if p.valid_at_utc - p.issued_at_utc != horizon:
                raise ValueError(f"{mid}: valid_at - issued_at differs from the horizon")
            ti.append(k)
            ei.append(e)
            if not h.classifier:
                cols["pred"].append(p.prediction)
            else:
                cols["plabel"].append(None if p.prediction_label is None else classes[p.prediction_label])
                cols["olabel"].append(None if p.observed_label is None else classes[p.observed_label])
            cols["obs"].append(p.observed)
            reason = p.missing_reason
            cols["reason"].append(None if reason is None else fmt.MISSING_REASONS.index(reason.value))
            if h.decides:
                cols["decided"].append(None if p.decided_by_rule_id is None else rules[p.decided_by_rule_id])
            if h.mixture:
                cols["top"].append(None if p.top_rule_id is None else rules[p.top_rule_id])
                cols["tshare"].append(p.top_rule_share)
    n = len(ti)
    t_epoch = np.array([int(t.timestamp()) for t in times], dtype="int64")
    e_arr, t_arr = np.array(ei, dtype=int), np.array(ti, dtype=int)
    rowid = np.full((max(len(times), 1), max(len(mc.modelled), 1)), -1, dtype=int)
    rowid[t_arr, e_arr] = np.arange(n)
    if h.classifier:
        raw = ctx.frame(
            "SELECT entity_id, issued_at_utc FROM read_parquet(?) WHERE issued_at_utc >= ? AND issued_at_utc < ? "
            "AND prediction_label IS NULL AND missing_reason = 'prediction_unavailable'", [pred_path, lo, hi])
        noref = np.zeros(n, dtype=int)
        if len(raw):
            ee = raw["entity_id"].map(mc.eidx).to_numpy(dtype=float)
            tt = np.searchsorted(t_epoch, _epoch(raw["issued_at_utc"]))
            ok = ~np.isnan(ee)
            r = rowid[tt[ok], ee[ok].astype(int)]
            noref[r[r >= 0]] = 1
        if noref.any():
            cols["noref"] = noref.tolist()
    shard = {"v": 1, "kind": "pred", "model_id": mid, "key": key, "t": t_iso, "n": n, "ti": ti, "ei": ei, **cols}
    out.write(f"models/{mid}/{key}/pred.json.gz", shard)

    # firing: the published table, aligned to the rows
    files = ctx.store._files(h, layout.ACTIVATIONS_DIR, lo, hi) if key != "all" else sorted(
        str(p) for p in (h.path / layout.ACTIVATIONS_DIR).rglob("*.parquet"))
    n_r = len(h.rule_order)
    fire = np.full((n_r, n), np.nan)
    if files and n:
        fr = ctx.frame(
            "SELECT entity_id, issued_at_utc, rule_id, firing_strength FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ?", [files, lo, hi])
        ee = fr["entity_id"].map(mc.eidx).to_numpy(dtype=float)
        rr = fr["rule_id"].map(rules).to_numpy(dtype=float)
        tt = np.clip(np.searchsorted(t_epoch, _epoch(fr["issued_at_utc"])), 0, len(times) - 1)
        ok = ~np.isnan(ee) & ~np.isnan(rr) & (t_epoch[tt] == _epoch(fr["issued_at_utc"]))
        row = np.full(len(fr), -1)
        row[ok] = rowid[tt[ok], ee[ok].astype(int)]
        ok &= row >= 0
        fire[rr[ok].astype(int), row[ok]] = fr["firing_strength"].to_numpy(dtype=float)[ok]
        del fr
    out.write(f"models/{mid}/{key}/fire.json.gz", {"v": 1, "kind": "fire", "n": n, "f": fire})

    # inputs of the rows -> memberships (finite rows only); water also stores its inputs here, row-aligned
    cols_sql = ", ".join(f'"{f}"' for f in h.features)
    X = np.full((n, len(h.features)), np.nan)
    if n:
        fr = ctx.frame(
            f"SELECT entity_id, issued_at_utc, {cols_sql} FROM read_parquet(?) "
            "WHERE issued_at_utc >= ? AND issued_at_utc < ?",
            [str(h.path / layout.INPUTS_FILE), lo, hi])
        ee = fr["entity_id"].map(mc.eidx).to_numpy(dtype=float)
        tt = np.clip(np.searchsorted(t_epoch, _epoch(fr["issued_at_utc"])), 0, len(times) - 1)
        ok = ~np.isnan(ee) & (t_epoch[tt] == _epoch(fr["issued_at_utc"]))
        row = np.full(len(fr), -1)
        row[ok] = rowid[tt[ok], ee[ok].astype(int)]
        ok &= row >= 0
        X[row[ok]] = fr[list(h.features)].to_numpy(dtype=float)[ok]
        del fr
    if not mc.regular:
        for j, f in enumerate(h.features):
            out.write(f"models/{mid}/inputs/{f}/all.json.gz",
                      {"v": 1, "kind": "inputs", "layout": "rows", "values": X[:, j]})
    ant = engine.antecedent_features(h.model, mc.family)
    pos = {f: j for j, f in enumerate(h.features)}
    Xa = X[:, [pos[f] for f in ant]] if n else np.zeros((0, len(ant)))
    pairs = engine.pair_positions(h.model, mc.family, mc.pairs)
    finite = np.isfinite(Xa).all(axis=1) if n else np.zeros(0, dtype=bool)
    mem = np.full((len(pairs), n), np.nan)
    if finite.any():
        mem[:, finite], _, _ = engine.activate_batches(h.model, mc.family, Xa[finite], pairs)
    out.write(f"models/{mid}/{key}/mem.json.gz", {"v": 1, "kind": "mem", "n": n, "m": mem})
    return n


# ------------------------------------------------------------------------------------------------ window statistics
class Acc:
    def __init__(self, n_r: int, n_e: int, winning: bool):
        self.n_records = np.zeros(n_e, dtype=np.int64)
        self.n_valid = np.zeros(n_e, dtype=np.int64)
        self.sum = np.zeros((n_r, n_e))
        self.over = np.zeros((len(fmt.TAUS), n_r, n_e), dtype=np.int64)
        self.win = np.zeros((n_r, n_e), dtype=np.int64) if winning else None

    def add(self, other: Acc) -> None:
        self.n_records += other.n_records
        self.n_valid += other.n_valid
        self.sum += other.sum
        self.over += other.over
        if self.win is not None:
            self.win += other.win

    def doc(self, model_id: str, kind: str, lo: datetime, hi: datetime) -> dict:
        doc = {"v": 1, "kind": "agg", "model_id": model_id,
               "window": {"kind": kind, "from": fmt.iso(lo), "to": fmt.iso(hi)},
               "n_records": self.n_records, "n_valid": self.n_valid, "sum": self.sum.ravel(),
               "over": [o.ravel() for o in self.over]}
        if self.win is not None:
            doc["win"] = self.win.ravel()
        return doc


def day_stats(ctx: Ctx, mc: ModelCtx, lo: datetime, hi: datetime) -> Acc:
    """``ArtifactStore._territory_stats`` for one UTC day, with the count above every tau of the grid."""
    h = mc.h
    n_r, n_e = len(h.rule_order), len(mc.modelled)
    acc = Acc(n_r, n_e, bool(h.winning_rule))
    files = ctx.store._files(h, layout.ACTIVATIONS_DIR, lo, hi)
    if not files:
        return acc
    extra = ", is_winner" if h.winning_rule else ""
    over = ", ".join(f"count(*) FILTER (WHERE ok AND f >= {t!r})" for t in fmt.TAUS)
    win = ", count(*) FILTER (WHERE ok AND is_winner)" if h.winning_rule else ""
    fr = ctx.frame(
        "WITH r AS (SELECT entity_id, rule_id, firing_strength AS f, "
        f"(firing_strength IS NOT NULL AND NOT isnan(firing_strength)) AS ok{extra} FROM read_parquet(?) "
        "WHERE issued_at_utc >= ? AND issued_at_utc < ?) "
        "SELECT entity_id, rule_id, count(*) AS n_rec, count(*) FILTER (WHERE ok) AS n_val, "
        f"coalesce(sum(f) FILTER (WHERE ok), 0) AS s, {over}{win} FROM r GROUP BY entity_id, rule_id", [files, lo, hi])
    if fr.empty:
        return acc
    e = fr["entity_id"].map(mc.eidx).to_numpy(dtype=float)
    r = fr["rule_id"].map({x: i for i, x in enumerate(h.rule_order)}).to_numpy(dtype=float)
    ok = ~np.isnan(e) & ~np.isnan(r)
    e, r = e[ok].astype(int), r[ok].astype(int)
    acc.n_records[e] = fr["n_rec"].to_numpy()[ok]
    acc.n_valid[e] = fr["n_val"].to_numpy()[ok]
    acc.sum[r, e] = fr["s"].to_numpy(dtype=float)[ok]
    values = fr.iloc[:, 5:].to_numpy()[ok]
    for k in range(len(fmt.TAUS)):
        acc.over[k][r, e] = values[:, k]
    if h.winning_rule:
        acc.win[r, e] = values[:, len(fmt.TAUS)]
    return acc


def export_agg(ctx: Ctx, mc: ModelCtx) -> int:
    """Day statistics from the published table, summed into week/month/year/coverage windows (all additive)."""
    h, out = mc.h, ctx.out
    mid = h.model_id
    n_r, n_e = len(h.rule_order), len(mc.modelled)
    total = 0
    current: dict[str, tuple[datetime, datetime, Acc]] = {}
    cov = Acc(n_r, n_e, bool(h.winning_rule))

    def flush(kind: str) -> int:
        lo, hi, acc = current.pop(kind)  # the file is named by the standard window; the window itself is clipped
        c_lo, c_hi = mc.clip(lo, hi)
        return out.write(f"models/{mid}/agg/{kind}/{fmt.day_key(lo)}.json.gz", acc.doc(mid, kind, c_lo, c_hi))

    for d in calendar_days(mc):  # empty days too: a recognised window with no data is an empty file, not a missing one
        lo = fmt.utc_midnight(d)
        d_lo, d_hi = mc.clip(lo, lo + fmt.DAY)
        day = day_stats(ctx, mc, d_lo, d_hi)
        total += out.write(f"models/{mid}/agg/day/{d}.json.gz", day.doc(mid, "day", d_lo, d_hi))
        for kind in ("week", "month", "year"):
            w_lo, w_hi = fmt.window_of(kind, lo)
            if kind in current and current[kind][0] != w_lo:
                total += flush(kind)
            if kind not in current:
                current[kind] = (w_lo, w_hi, Acc(n_r, n_e, bool(h.winning_rule)))
            current[kind][2].add(day)
        cov.add(day)
    for kind in list(current):
        total += flush(kind)
    if fmt.coverage_fits(mc.first, mc.last, mc.step_hours):
        c_lo, c_hi = fmt.coverage_window(mc.first, mc.last, mc.step_hours)
        total += out.write(f"models/{mid}/agg/coverage/all.json.gz", cov.doc(mid, "coverage", c_lo, c_hi))
    return total


# ------------------------------------------------------------------------------------------------ stories
def story_windows(mc: ModelCtx) -> list[tuple[str, datetime, datetime, str]]:
    """(kind, from, to, file name) of every window with a stories file."""
    wins = []
    for kind in fmt.WINDOW_KINDS:
        for start in windows_of(mc)[kind]:
            lo, hi = mc.clip(*fmt.window_of(kind, fmt.utc_midnight(start)))
            wins.append((kind, lo, hi, f"{start}.json.gz"))
    if fmt.coverage_fits(mc.first, mc.last, mc.step_hours):
        lo, hi = fmt.coverage_window(mc.first, mc.last, mc.step_hours)
        wins.append(("coverage", lo, hi, "all.json.gz"))
    return wins


def export_stories(ctx: Ctx, mc: ModelCtx) -> int:
    total = 0
    for kind, lo, hi, name in story_windows(mc):
        rel = f"models/{mc.model_id}/stories/{kind}/{name}"
        if ctx.out.exists(rel) and not ctx.out.force:
            continue
        body = ctx.exact("/api/v1/rule-stories", model_id=mc.model_id, **{"from": fmt.iso(lo), "to": fmt.iso(hi)},
                         tau=fmt.STORIES_TAU, limit=fmt.STORIES_LIMIT)
        total += ctx.out.write(rel, body)
    return total
