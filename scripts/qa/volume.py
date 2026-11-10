"""Volume test (AT-061): >= 1M input rows and >= 20M activation records, with a RAM and latency profile.

Stages (each one is a separate process when run through ``all``, so ``ru_maxrss`` is that stage's own peak):

    build        train a 20-rule model on a small synthetic table, then publish a big synthetic table of it
                 (60 entities x 730 days hourly = 1.05M input rows x 20 rules = 21M activation records)
    relayout     copy the model dir with the activations re-sorted by (rule_id, issued_at_utc, entity_id)
    profile      the API (ArtifactStore + TestClient) over a published dir: cold/uncached/cached latency per endpoint
    concurrency  uvicorn in a subprocess and N concurrent client threads for S seconds
    validator    ``validate_observations`` over a real observation set: all at once vs per partition
    all          everything, merged into one JSON report

    PYTHONPATH=src:apps/api python scripts/qa/volume.py all --out <scratch dir> --report volume.json
    PYTHONPATH=src:apps/api python scripts/qa/volume.py all --smoke --out <scratch dir>  # 6 ents x 30 d

Every stage refuses to continue when ``MemAvailable`` < 2 GB or its own RSS > 2.5 GB (``Guard``). Nothing is ever
written under ``artifacts/published``: ``--out`` is required and refused if it is inside the repository.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import random
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psutil

REPO = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
MIN_AVAILABLE_GB = 2.0
MAX_RSS_GB = 2.5
HOUR = timedelta(hours=1)


# ------------------------------------------------------------------------------------------------ memory guard


def available_gb() -> float:
    return psutil.virtual_memory().available / 2**30


def peak_rss_mb() -> float:
    """Peak resident set of this process so far (``ru_maxrss`` is in KiB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class Guard:
    """Samples RSS of this process (and of ``extra`` pids) every 50 ms; exits the process on the memory limits."""

    def __init__(self, max_rss_gb: float = MAX_RSS_GB, min_available_gb: float = MIN_AVAILABLE_GB):
        self.max_rss, self.min_available = max_rss_gb * 2**30, min_available_gb * 2**30
        self.procs = [psutil.Process()]
        self.peak = 0
        self.phase_peak = 0
        self.phase_by_pid: dict[int, int] = {}
        self.min_avail_seen = float("inf")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def watch(self, pid: int) -> None:
        self.procs.append(psutil.Process(pid))

    @staticmethod
    def _tree_rss(p) -> int:
        """RSS of a process plus its children (uvicorn ``--workers`` are children of the parent)."""
        total = 0
        try:
            for q in [p, *p.children(recursive=True)]:
                try:
                    total += q.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        return total

    def _rss(self, procs) -> int:
        return sum(self._tree_rss(p) for p in procs)

    def _run(self) -> None:
        while not self._stop.wait(0.05):
            for p in list(self.procs):  # each watched process against the per-process limit
                rss = self._tree_rss(p)
                self.peak = max(self.peak, rss)
                self.phase_peak = max(self.phase_peak, rss)
                self.phase_by_pid[p.pid] = max(self.phase_by_pid.get(p.pid, 0), rss)
                if rss > self.max_rss:
                    self._abort(f"RSS of pid {p.pid} is {rss / 2**30:.2f} GB > {self.max_rss / 2**30:.1f} GB")
            avail = psutil.virtual_memory().available
            self.min_avail_seen = min(self.min_avail_seen, avail)
            if avail < self.min_available:
                self._abort(f"MemAvailable {avail / 2**30:.2f} GB < {self.min_available / 2**30:.1f} GB")

    def _abort(self, why: str) -> None:
        print(f"GUARD ABORT: {why}", file=sys.stderr, flush=True)
        for p in self.procs[1:]:
            try:
                p.kill()
            except psutil.Error:
                pass
        os._exit(3)

    def __enter__(self) -> Guard:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()

    @contextmanager
    def phase(self):
        """Yields a dict filled on exit with the sampled peak RSS (MB) reached inside the block."""
        out = {}
        self.phase_peak = max(self._tree_rss(p) for p in self.procs)
        self.phase_by_pid = {}
        yield out
        out["peak_rss_mb"] = round(self.phase_peak / 2**20, 1)
        out["peak_rss_mb_by_pid"] = {pid: round(v / 2**20, 1) for pid, v in self.phase_by_pid.items()}


def stats(values) -> dict:
    a = np.asarray(values, dtype=float)
    if not len(a):
        return {"n": 0}
    p50, p95 = np.percentile(a, [50, 95])
    return {"n": len(a), "p50_ms": round(float(p50), 2), "p95_ms": round(float(p95), 2),
            "max_ms": round(float(a.max()), 2)}


def machine(scratch: Path) -> dict:
    mem = psutil.virtual_memory()
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    import duckdb

    return {
        "cpu_count": psutil.cpu_count(), "ram_total_gb": round(mem.total / 2**30, 1),
        "ram_available_gb_at_start": round(mem.available / 2**30, 1),
        "swap_used_gb": round(psutil.swap_memory().used / 2**30, 1),
        "load_avg_1_5_15": [round(x, 2) for x in os.getloadavg()], "python": platform.python_version(),
        "duckdb": duckdb.__version__, "git_commit": commit.stdout.strip(),
        "scratch_free_gb": round(shutil.disk_usage(scratch).free / 2**30, 1),
    }


def dir_mb(path: Path) -> float:
    return round(sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) / 2**20, 1)


def drop_page_cache(path: Path) -> None:
    """Ask the kernel to drop the cached pages of every file under ``path`` (clean pages only; no root needed)."""
    for p in Path(path).rglob("*"):
        if p.is_file():
            fd = os.open(p, os.O_RDONLY)
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(fd)


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def report_path(path: Path) -> str:
    """A path as reports record it: relative to the repo root, or just its name outside the repo (never absolute)."""
    path = Path(path).resolve()
    return str(path.relative_to(REPO)) if REPO in path.parents else path.name


def refuse_repo_out(out: Path) -> None:
    out = out.resolve()
    if REPO in out.parents or out == REPO:
        raise SystemExit(f"--out {out} is inside the repository; use a scratch directory")


# ----------------------------------------------------------------------------------------------------- build


def build(out: Path, n_entities: int, days: int, n_rules: int, guard: Guard) -> dict:
    """Train a ``n_rules`` model on a small table, publish ``n_entities x days x 24`` rows of a bigger one."""
    from atlas.contracts import models as m
    from atlas.ml.fuzzy import FuzzyParams
    from atlas.ml.pipeline import RunConfig, train_run
    from atlas.ml.split import chronological_split_spec
    from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET, make_synthetic_table
    from atlas.services import layout
    from atlas.services.publish import publish_run
    from atlas.services.synthetic import HORIZON_HOURS, LAGS

    out.mkdir(parents=True, exist_ok=True)
    small = make_synthetic_table(n_entities=3, n_hours=24 * 45, seed=1, exo_missing_fraction=0.03)
    config = RunConfig(
        task_id="volume_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u",
        horizon_hours=HORIZON_HOURS, features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t",
        split=chronological_split_spec(small["issued_at_utc"], horizon_hours=HORIZON_HOURS), seed=3,
        data_version="synthetic-volume", synthetic=True, gbm_max_iter=20,
        fuzzy=FuzzyParams(nRules=n_rules, nAnts=3, n_gen=8, pop_size=16),
    )
    with guard.phase() as train_phase:
        t0 = time.perf_counter()
        run_dir = train_run(small, config, artifacts_dir=out / "runs").run_dir
        train_seconds = time.perf_counter() - t0
    rules = m.ModelRules.model_validate_json((run_dir / "rules.json").read_text())

    with guard.phase() as table_phase:
        t0 = time.perf_counter()
        big = make_synthetic_table(
            n_entities=n_entities, n_hours=days * 24, seed=7, exo_missing_fraction=0.03)
        big.to_parquet(out / "features.parquet", index=False)
        table_seconds = time.perf_counter() - t0
    n_rows_table = len(big)
    start = big["issued_at_utc"].min()
    last = big["issued_at_utc"].max()
    del big, small
    gc.collect()

    side = int(np.ceil(np.sqrt(n_entities)))
    entities = m.EntityCollection(
        data_version="synthetic-entities", synthetic=True, type="FeatureCollection", domain=m.Domain.AIR,
        features=[
            m.EntityFeature(
                type="Feature", id=f"E{e}",
                geometry=m.PointGeometry(
                    type="Point", coordinates=(-3.80 + 0.02 * (e % side), 40.35 + 0.02 * (e // side))),
                properties=m.EntityProperties(
                    entity_id=f"E{e}", domain=m.Domain.AIR, name=f"Synthetic station E{e} (not real)",
                    geometry_support=m.GeometrySupport.OBSERVED_POINT, geometry_source="synthetic",
                    timezone="Europe/Madrid"),
            )
            for e in range(n_entities)
        ],
    )
    (out / "entities.geojson").write_text(entities.model_dump_json(indent=2))
    spec = layout.FeatureSpec(features={
        f: layout.FeatureSource(unit=FEATURE_UNITS[f], source_id=f"synthetic-{f}", lag_hours=LAGS[f])
        for f in FEATURES})
    (out / "feature_spec.json").write_text(spec.model_dump_json(indent=2))

    published = out / "published"
    if published.exists():
        shutil.rmtree(published)
    with guard.phase() as publish_phase:
        t0 = time.perf_counter()
        summary = publish_run(
            run_dir, out / "features.parquet", out / "entities.geojson", out / "feature_spec.json",
            start + timedelta(days=4), last + HOUR, published_dir=published, synthetic=True)
        publish_seconds = time.perf_counter() - t0
    mdir = summary.model_dir
    sizes = {p.name: dir_mb(p) if p.is_dir() else round(p.stat().st_size / 2**20, 2) for p in sorted(mdir.iterdir())}
    return {
        "n_entities": n_entities, "days": days, "n_rules_requested": n_rules, "n_rules_trained": len(rules.rules),
        "table_rows_generated": n_rows_table, "input_rows_published": summary.n_input_rows,
        "activation_records": summary.n_activation_records, "published_entities": summary.n_entities,
        "train_seconds": round(train_seconds, 1), "table_seconds": round(table_seconds, 1),
        "publish_seconds": round(publish_seconds, 1),
        "publish_rows_per_second": round(summary.n_input_rows / publish_seconds),
        "publish_activation_records_per_second": round(summary.n_activation_records / publish_seconds),
        "sampled_peak_rss_mb": {"train": train_phase["peak_rss_mb"], "generate_table": table_phase["peak_rss_mb"],
                                "publish": publish_phase["peak_rss_mb"]},
        "disk_mb": {"model_dir_total": dir_mb(mdir),
                    "feature_table_input": round((out / "features.parquet").stat().st_size / 2**20, 1), **sizes},
        "bytes_per_activation_record": round(dir_mb(mdir / "activations") * 2**20 / summary.n_activation_records, 2),
        "activation_files": len(list((mdir / "activations").rglob("*.parquet"))),
        "model_dir": report_path(mdir),
    }


def row_group_info(model_dir: Path) -> dict:
    import pyarrow.parquet as pq

    files = sorted((Path(model_dir) / "activations").rglob("*.parquet"))
    rg = [pq.ParquetFile(f).metadata for f in files]
    return {"files": len(files), "records_per_file_max": max(x.num_rows for x in rg),
            "row_groups_per_file_max": max(x.num_row_groups for x in rg)}


def relayout(src_dir: Path, dst_published: Path, row_group_size: int, dense: bool = False, sort: bool = True,
             time_order: bool = False) -> dict:
    """Copy ``src_dir`` (one model dir) into ``dst_published`` with each activations file sorted by rule_id first.

    ``dense``: replace both firing columns by uniform random numbers (worst case for size and scan cost; NOT model
    output, only for timing the store). ``sort=False`` keeps the published row order, which since AT-061 B3 is
    ``(rule_id, issued_at_utc, entity_id)``; ``time_order`` rewrites the layout ``publish`` had before B3, ordered by
    ``(issued_at_utc, entity_id, rule_id)`` (use it with ``--row-group-size 1048576`` for one row group per file).
    """
    import duckdb

    from atlas.ml.artifacts import CHECKSUM_FILE
    from atlas.services import layout

    dst = dst_published / src_dir.name
    if dst_published.exists():
        shutil.rmtree(dst_published)
    t0 = time.perf_counter()
    dst.mkdir(parents=True)
    for p in src_dir.iterdir():
        if p.name in ("activations", CHECKSUM_FILE):
            continue
        shutil.copytree(p, dst / p.name) if p.is_dir() else shutil.copyfile(p, dst / p.name)
    con = duckdb.connect(config={"memory_limit": "1GB", "threads": 2})
    con.execute("SET TimeZone='UTC'")
    for f in sorted((src_dir / "activations").rglob("*.parquet")):
        target = dst / f.relative_to(src_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        columns = ("entity_id, issued_at_utc, rule_id, random() AS firing_strength, random() AS effective_firing, "
                   "missing_reason") if dense else "*"
        order = (" ORDER BY issued_at_utc, entity_id, rule_id" if time_order
                 else " ORDER BY rule_id, issued_at_utc, entity_id" if sort else "")
        con.execute(
            f"COPY (SELECT {columns} FROM read_parquet('{f}'){order}) TO '{target}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {row_group_size})")
    shutil.copyfile(src_dir.parent / layout.REGISTRY_FILE, dst_published / layout.REGISTRY_FILE)
    layout.write_checksums(dst)
    return {"seconds": round(time.perf_counter() - t0, 1), "row_group_size": row_group_size, "dense": dense,
            "sorted_by_rule": sort and not time_order, "time_order": time_order,
            "activations_mb": dir_mb(dst / "activations"), **row_group_info(dst), "model_dir": report_path(dst)}


# --------------------------------------------------------------------------------------------- workloads


class Workload:
    """Request generator for one task of a published dir. Parameters come from the published files only."""

    def __init__(self, published: Path, task_id: str, seed: int = 20261031):
        import duckdb

        from atlas.contracts import models as m
        from atlas.services import layout

        self.published = Path(published)
        entry = layout.read_registry(self.published).tasks[task_id]
        self.task_id, self.model_id = task_id, entry.model_id
        mdir = self.published / entry.model_id
        rules = m.ModelRules.model_validate_json((mdir / "rules.json").read_text())
        ents = m.EntityCollection.model_validate_json((mdir / layout.ENTITIES_FILE).read_text())
        self.entities = [f.properties.entity_id for f in ents.features]
        self.rules = [r.rule_id for r in rules.rules]
        info = json.loads((mdir / layout.PUBLISH_INFO_FILE).read_text())
        self.n_input_rows, self.n_activation_records = info["n_input_rows"], info["n_activation_records"]
        rows = duckdb.connect().execute(
            "SELECT DISTINCT issued_at_utc FROM read_parquet(?) ORDER BY 1",
            [str(mdir / layout.INPUTS_FILE)]).fetchall()
        self.times = [r[0].astimezone(timezone.utc) for r in rows]
        # (entity, issue time) pairs that exist: Water is sparse and irregular, so not every combination does
        pairs = duckdb.connect().execute(
            "SELECT entity_id, issued_at_utc FROM read_parquet(?) USING SAMPLE reservoir(20000 ROWS) REPEATABLE (7)",
            [str(mdir / layout.INPUTS_FILE)]).fetchall()
        self.pairs = [(e, t.astimezone(timezone.utc)) for e, t in pairs]
        # a series exists only for entities that have predictions
        self.series_entities = [r[0] for r in duckdb.connect().execute(
            "SELECT DISTINCT entity_id FROM read_parquet(?) ORDER BY 1", [str(mdir / layout.PREDICTIONS_FILE)]
        ).fetchall()]
        self.t_min, self.t_max = self.times[0], self.times[-1]
        self.rng = random.Random(f"{seed}-{task_id}")
        self.seed = seed

    def fork(self, tag: str) -> Workload:
        other = object.__new__(Workload)
        other.__dict__.update(self.__dict__)
        other.rng = random.Random(f"{self.seed}-{self.task_id}-{tag}")
        return other

    def _window(self, days: int) -> tuple[datetime, datetime, int]:
        span = (self.t_max - self.t_min) + HOUR
        width = min(timedelta(days=days), span)
        slack_hours = int((span - width) / HOUR)
        lo = self.t_min + HOUR * self.rng.randint(0, max(slack_hours, 0))
        return lo, lo + width, width.days

    # each returns (path, params)
    def firing(self):
        return "/api/v1/rule-map", {"model_id": self.model_id, "rule_id": self.rng.choice(self.rules),
                                    "metric": "firing_strength", "time": iso(self.rng.choice(self.times))}

    def window(self, days: int, metric: str):
        lo, hi, _ = self._window(days)
        params = {"model_id": self.model_id, "rule_id": self.rng.choice(self.rules), "metric": metric,
                  "from": iso(lo), "to": iso(hi)}
        if metric == "activation_frequency":
            params["tau"] = self.rng.choice([0.1, 0.2, 0.3, 0.5, 0.7])
        return "/api/v1/rule-map", params

    def effective_days(self, days: int) -> int:
        return min(days, ((self.t_max - self.t_min) + HOUR).days)

    def trace(self):
        eid, at = self.rng.choice(self.pairs)
        return f"/api/v1/entities/{eid}/rule-trace", {"model_id": self.model_id, "at": iso(at)}

    def series_full(self):
        return "/api/v1/series", {"task_id": self.task_id, "entity_id": self.rng.choice(self.series_entities)}

    def series_window(self, days: int = 7):
        lo, hi, _ = self._window(days)
        return "/api/v1/series", {"task_id": self.task_id, "entity_id": self.rng.choice(self.series_entities),
                                  "from": iso(lo), "to": iso(hi)}

    def meta(self):
        return self.rng.choice([("/api/v1/domains", {}), (f"/api/v1/models/{self.model_id}", {}),
                                (f"/api/v1/models/{self.model_id}/rules", {})])

    def endpoint_kinds(self) -> dict:
        return {
            "rule_map_firing": self.firing,
            "rule_map_mean_30d": lambda: self.window(30, "mean_activation"),
            "rule_map_freq_30d": lambda: self.window(30, "activation_frequency"),
            "rule_map_mean_366d": lambda: self.window(366, "mean_activation"),
            "rule_map_freq_366d": lambda: self.window(366, "activation_frequency"),
            "rule_trace": self.trace,
            "health_baseline": lambda: ("/api/v1/health", {}),
            "series_full": self.series_full,
            "series_7d": self.series_window,
            "domains_card_rules": self.meta,
        }


def check_bounded(kind: str, body: dict, w: Workload) -> list[str]:
    """Structural size checks: the response never grows with the number of input rows."""
    problems = []
    if kind.startswith("rule_map"):
        if len(body["features"]) > len(w.entities):
            problems.append("rule-map has more features than entities")
        if any(k not in ("entity_id", "rule_id", "metric", "value", "n_valid", "time_from_utc", "time_to_utc",
                         "issued_at_utc", "valid_at_utc", "tau", "model_id", "data_version", "geometry_support",
                         "missing_reason", "quality") for f in body["features"] for k in f["properties"]):
            problems.append("unexpected property in rule-map feature")
    elif kind.startswith("series"):
        from atlas_api.artifact_store import SERIES_MAX_POINTS

        if len(body["points"]) > SERIES_MAX_POINTS:
            problems.append("series page longer than SERIES_MAX_POINTS")
    elif kind == "rule_trace":
        if len(body["rules"]) > len(w.rules) if "rules" in body else False:
            problems.append("trace has more rules than the model")
    return problems


def profile(published: Path, label: str, n: int, guard: Guard) -> dict:
    """Latency and RSS of every endpoint kind, per task in the registry, through the real FastAPI app."""
    from fastapi.testclient import TestClient

    from atlas.services import layout
    from atlas_api.artifact_store import ArtifactStore
    from atlas_api.main import create_app

    result: dict = {"label": label, "published": report_path(published), "tasks": {}}
    for task_id in sorted(layout.read_registry(published).tasks):
        w = Workload(published, task_id)
        mdir = published / w.model_id
        store = ArtifactStore(published)
        client = TestClient(create_app(store))
        kinds = w.endpoint_kinds()
        rss0 = psutil.Process().memory_info().rss / 2**20
        task: dict = {
            "model_id": w.model_id, "input_rows": w.n_input_rows, "activation_records": w.n_activation_records,
            "entities": len(w.entities), "rules": len(w.rules), "distinct_issue_times": len(w.times),
            "span_days": round(((w.t_max - w.t_min) + HOUR).total_seconds() / 86400, 1),
            "effective_days_for_366d_window": w.effective_days(366), "rss_after_import_mb": round(rss0, 1),
            "cold": {}, "uncached": {}, "cached": {}, "bounds": {"max_response_bytes": {}, "problems": []},
        }

        def get(kind, path, params, tag, _client=client, _w=w, _task=task):
            t0 = time.perf_counter()
            r = _client.get(path, params=params)
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                raise RuntimeError(f"{kind} {path} {params} -> {r.status_code} {r.text[:200]}")
            size = len(r.content)
            _task["bounds"]["max_response_bytes"][kind] = max(_task["bounds"]["max_response_bytes"].get(kind, 0), size)
            _task["bounds"]["problems"] += check_bounded(kind, r.json(), _w)
            return ms

        # cold: fresh store, the model dir dropped from the page cache before every first request
        order = ["health_baseline", "domains_card_rules", "rule_map_firing", "rule_map_mean_30d", "rule_map_freq_30d",
                 "rule_map_mean_366d", "rule_map_freq_366d", "series_full", "series_7d", "rule_trace"]
        for kind in order:
            drop_page_cache(mdir)
            path, params = kinds[kind]()
            with guard.phase() as ph:
                ms = get(kind, path, params, "cold")
            task["cold"][kind] = {"ms": round(ms, 1), "peak_rss_mb": ph["peak_rss_mb"]}

        counts = {"rule_map_firing": n, "rule_map_mean_30d": max(n // 2, 5), "rule_map_freq_30d": max(n // 2, 5),
                  "rule_map_mean_366d": max(n // 5, 3), "rule_map_freq_366d": max(n // 5, 3), "rule_trace": n,
                  "series_full": max(n // 4, 5), "series_7d": n, "domains_card_rules": n,
                  "health_baseline": n}
        for kind in order:
            ms_list = []
            with guard.phase() as ph:
                for _ in range(counts[kind]):
                    path, params = kinds[kind]()
                    ms_list.append(get(kind, path, params, "uncached"))
            task["uncached"][kind] = {**stats(ms_list), "peak_rss_mb": ph["peak_rss_mb"]}

        # the whole range of one entity, page by page (the cost for a client that wants every point)
        paged = []
        for _ in range(max(n // 6, 3)):
            path, params = kinds["series_full"]()
            t0, pages, points, nbytes, cursor = time.perf_counter(), 0, 0, 0, None
            while True:
                r = client.get(path, params={**params, **({"cursor": cursor} if cursor else {})})
                assert r.status_code == 200, r.text[:200]
                body = r.json()
                pages, points, nbytes = pages + 1, points + len(body["points"]), nbytes + len(r.content)
                cursor = body["next_cursor"]
                if cursor is None:
                    break
            paged.append({"ms": (time.perf_counter() - t0) * 1000, "pages": pages, "points": points, "bytes": nbytes})
        task["series_all_pages"] = {**stats([p["ms"] for p in paged]), "pages_max": max(p["pages"] for p in paged),
                                    "points_max": max(p["points"] for p in paged),
                                    "bytes_max": max(p["bytes"] for p in paged)}

        # cached: the same rule-map key again (the store keeps 256 responses)
        for kind in ("rule_map_firing", "rule_map_mean_30d", "rule_map_freq_366d"):
            path, params = kinds[kind]()
            get(kind, path, params, "prime")
            task["cached"][kind] = stats([get(kind, path, params, "cached") for _ in range(n)])

        # cache footprint: 300 distinct rule-map keys through the store (it keeps 256), RSS before and after
        rss_before = psutil.Process().memory_info().rss / 2**20
        for _ in range(300):
            path, params = kinds["rule_map_mean_30d"]()
            get("rule_map_mean_30d", path, params, "fill")
        task["cache_fill"] = {"requests": 300, "entries": len(store._cache), "cache_bytes": store._cache.bytes,
                              "cache_budget_bytes": store._cache.max_bytes,
                              "rss_delta_mb": round(psutil.Process().memory_info().rss / 2**20 - rss_before, 1)}

        # the 366-day limit: a longer window is refused before any file is read
        lo, hi, _ = w._window(30)
        t0 = time.perf_counter()
        r = client.get("/api/v1/rule-map", params={
            "model_id": w.model_id, "rule_id": w.rules[0], "metric": "mean_activation",
            "from": iso(w.t_min), "to": iso(w.t_min + timedelta(days=367))})
        task["window_367d"] = {"status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000, 2)}
        task["rss_end_mb"] = round(psutil.Process().memory_info().rss / 2**20, 1)
        task["cache_entries_end"] = len(store._cache)
        result["tasks"][task_id] = task
        client.close()
        del client, store
        gc.collect()
    result["process_peak_rss_mb"] = round(peak_rss_mb(), 1)
    return result


# ---------------------------------------------------------------------------------------------- concurrency

MIX = [("rule_map_firing", 40), ("rule_map_mean_30d", 12), ("rule_map_freq_30d", 8), ("rule_map_mean_366d", 3),
       ("rule_map_freq_366d", 2), ("rule_trace", 15), ("series_full", 5), ("series_7d", 10), ("domains_card_rules", 5)]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def concurrency(published: Path, task_id: str, clients: int, seconds: float, scenarios: list[str], guard: Guard,
                workers: int = 1) -> dict:
    import httpx

    w0 = Workload(published, task_id)
    port = free_port()
    env = {**os.environ, "ATLAS_API_MODE": "artifacts", "ATLAS_PUBLISHED_DIR": str(published),
           "PYTHONPATH": f"{REPO / 'src'}:{REPO / 'apps/api'}"}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "atlas_api.main:app", "--port", str(port), "--workers", str(workers),
         "--log-level", "warning"], cwd=REPO, env=env)
    guard.watch(server.pid)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):
            try:
                if httpx.get(f"{base}/api/v1/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("uvicorn did not start")
        out = {"workers": workers, "clients": clients, "scenarios": {}}
        for name in scenarios:
            out["scenarios"][name] = _scenario(name, base, w0, clients, seconds, guard, server.pid)
        return out
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


def _scenario(name: str, base: str, w0: Workload, clients: int, seconds: float, guard: Guard, server_pid: int) -> dict:
    import httpx

    if name == "heavy_366d":
        mix = [("rule_map_mean_366d", 1), ("rule_map_freq_366d", 1)]
        p_hot = 0.0
    elif name == "hot":  # a map user dragging a slider over a few views: 80% of the requests repeat a recent view
        mix, p_hot = MIX, 0.8
    elif name == "hot_no_series_full":
        mix, p_hot = [(k, wt) for k, wt in MIX if k != "series_full"], 0.8
    elif name == "distinct":
        mix, p_hot = MIX, 0.0
    elif name == "no_series_full":  # `distinct` without the 4 MB series pages
        mix, p_hot = [(k, wt) for k, wt in MIX if k != "series_full"], 0.0
    else:
        raise ValueError(name)
    kinds_names = [k for k, _ in mix]
    weights = [wt for _, wt in mix]
    hot_w = w0.fork("hot")
    hot = {k: [hot_w.endpoint_kinds()[k]() for _ in range(6)] for k in kinds_names}
    records: list[tuple[str, float, int, int]] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + seconds

    def worker(i: int) -> None:
        w = w0.fork(f"{name}-{i}")
        kinds = w.endpoint_kinds()
        rng = random.Random(f"{name}-{i}")
        local = []
        with httpx.Client(base_url=base, timeout=300) as c:
            while time.perf_counter() < stop_at:
                kind = rng.choices(kinds_names, weights)[0]
                path, params = rng.choice(hot[kind]) if rng.random() < p_hot else kinds[kind]()
                t0 = time.perf_counter()
                try:
                    r = c.get(path, params=params)
                    local.append((kind, (time.perf_counter() - t0) * 1000, r.status_code, len(r.content)))
                except httpx.HTTPError:
                    local.append((kind, (time.perf_counter() - t0) * 1000, 599, 0))
        with lock:
            records.extend(local)

    server = psutil.Process(server_pid)
    rss_before = Guard._tree_rss(server) / 2**20
    with guard.phase() as ph:
        t0 = time.perf_counter()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(clients)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        wall = time.perf_counter() - t0
    per = {}
    for kind in kinds_names:
        rows = [r for r in records if r[0] == kind]
        ok = [r[1] for r in rows if r[2] == 200]
        per[kind] = {**stats(ok), "errors": len(rows) - len(ok),
                     "max_response_bytes": max((r[3] for r in rows), default=0)}
    all_ok = [r[1] for r in records if r[2] == 200]
    return {
        "seconds": round(wall, 1), "requests": len(records), "req_per_s": round(len(records) / wall, 1),
        "errors": sum(1 for r in records if r[2] != 200), "overall": stats(all_ok),
        "p99_ms": round(float(np.percentile(all_ok, 99)), 2) if all_ok else None,
        "server_rss_before_mb": round(rss_before, 1), "server_rss_after_mb": round(Guard._tree_rss(server) / 2**20, 1),
        "server_peak_rss_mb_incl_workers": ph["peak_rss_mb_by_pid"].get(server_pid),
        "client_peak_rss_mb": ph["peak_rss_mb_by_pid"].get(os.getpid()), "per_endpoint": per,
        "p_hot": p_hot, "loadavg_end": [round(x, 1) for x in os.getloadavg()],
        "min_available_gb_seen": round(guard.min_avail_seen / 2**30, 2),
    }


# ------------------------------------------------------------------------------------------------ validator


def validator(root: Path, mode: str, first_k: int | None, guard: Guard, memory_limit: str = "1GB") -> dict:
    """``validate_observations`` over ``root`` (hive ``year=/month=`` Parquet): ``whole`` or ``per_partition``."""
    import duckdb

    from atlas.contracts.observations import validate_observations, validate_observations_partitioned

    parts = sorted(d for d in root.glob("year=*/month=*") if d.is_dir())
    if first_k:
        parts = parts[:first_k]
    count = duckdb.connect()
    n_rows = sum(count.execute(f"SELECT count(*) FROM read_parquet('{d}/*.parquet')").fetchone()[0] for d in parts)
    base_rss = psutil.Process().memory_info().rss / 2**20
    errors: list[str] = []
    per = []
    with tempfile.TemporaryDirectory(prefix="volume-obs-") as tmp:
        subset = Path(tmp)  # a copy of the first K partitions (tens of MB), so that one glob covers exactly them
        for d in parts:
            (subset / d.parent.name).mkdir(exist_ok=True)
            shutil.copytree(d, subset / d.parent.name / d.name)
        t0 = time.perf_counter()
        with guard.phase() as ph:
            if mode == "per_year":
                for year in sorted({d.parent for d in parts}):
                    t1 = time.perf_counter()
                    errors += validate_observations(str(year / "**" / "*.parquet"))
                    per.append(round(time.perf_counter() - t1, 2))
            elif mode == "whole":  # same call as A1: one glob over the hive partitions, validated at once
                errors = validate_observations(str(subset / "**" / "*.parquet"), memory_limit=memory_limit)
            elif mode == "partitioned":  # the AT-061 helper: one call per partition, memory_limit applied to each
                errors = validate_observations_partitioned(subset, memory_limit=memory_limit)
            else:
                for d in parts:
                    t1 = time.perf_counter()
                    errors += validate_observations(str(d / "*.parquet"))
                    per.append(round(time.perf_counter() - t1, 2))
        seconds = time.perf_counter() - t0
    return {
        "mode": mode, "memory_limit": memory_limit, "partitions": len(parts), "rows": n_rows, "errors": errors[:5],
        "seconds": round(seconds, 1),
        "rows_per_second": round(n_rows / seconds), "baseline_rss_mb": round(base_rss, 1),
        "peak_rss_mb_ru_maxrss": round(peak_rss_mb(), 1), "sampled_peak_rss_mb": ph["peak_rss_mb"],
        "slowest_call_s": max(per) if per else None,
    }


# --------------------------------------------------------------------------------------------------- driver


def run_stage(stage: str, args: list[str], out_json: Path, allow_fail: bool = False) -> dict:
    cmd = [sys.executable, str(SELF), stage, *args, "--json", str(out_json)]
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO / 'apps/api'}"}
    print(f"\n=== {stage} {' '.join(args)}", flush=True)
    t0 = time.perf_counter()
    out_json.unlink(missing_ok=True)
    proc = subprocess.run(cmd, cwd=REPO, env=env)
    if proc.returncode != 0:
        if allow_fail:
            return {"failed": f"exit code {proc.returncode} (see the console; 3 = memory guard)"}
        raise SystemExit(f"stage {stage} failed with exit code {proc.returncode} (3 = memory guard)")
    data = json.loads(out_json.read_text())
    data["_stage_wall_seconds"] = round(time.perf_counter() - t0, 1)
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=["build", "relayout", "profile", "concurrency", "validator", "all"])
    parser.add_argument("--out", type=Path, help="scratch directory (required by build/relayout/all)")
    parser.add_argument("--json", type=Path, help="stage output file")
    parser.add_argument("--report", type=Path, default=None, help="all: final JSON report")
    parser.add_argument("--published", type=Path, help="profile/concurrency: a published dir")
    parser.add_argument("--task-id", default="volume_y_h6")
    parser.add_argument("--label", default="synthetic")
    parser.add_argument("--entities", type=int, default=60)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--rules", type=int, default=20)
    parser.add_argument("--n", type=int, default=30, help="profile: requests per endpoint kind (scaled per kind)")
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--scenarios", default="hot,distinct,no_series_full,hot_no_series_full,heavy_366d")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--row-group-size", type=int, default=100_000)
    parser.add_argument("--dense", action="store_true", help="relayout: random firing values (worst-case scan cost)")
    parser.add_argument("--keep-order", action="store_true", help="relayout: do not sort the activations")
    parser.add_argument("--time-order", action="store_true",
                        help="relayout: the layout before AT-061 B3 (sorted by issued_at_utc, entity_id, rule_id)")
    parser.add_argument("--src", type=Path, help="relayout: the model dir to copy")
    parser.add_argument("--dst", type=Path, help="relayout: the published dir to create")
    parser.add_argument("--obs", type=Path, help="validator: observations dir (year=/month= hive)")
    parser.add_argument("--mode", default="whole", choices=["whole", "per_partition", "per_year", "partitioned"])
    parser.add_argument("--memory-limit", default="1GB", help="validator: DuckDB memory_limit of validate_observations")
    parser.add_argument("--first-k", type=int, default=None, help="validator: only the first K partitions")
    parser.add_argument("--real", type=Path, default=Path(os.environ.get(
        "ATLAS_REAL_PUBLISHED", REPO / "artifacts" / "published")))
    parser.add_argument("--real-data", type=Path, default=Path(os.environ.get(
        "ATLAS_REAL_DATA", REPO / "data" / "processed")))
    parser.add_argument("--layouts", default="legacy_time_order,dense_legacy_time_order,dense_sorted_by_rule",
                        help="all: activation layouts to profile besides the published one")
    parser.add_argument("--smoke", action="store_true", help="all: tiny sizes (6 entities x 30 days, 5 s scenarios)")
    parser.add_argument("--skip", default="",
                        help="all: comma list of steps to skip: build relayout profile real concurrency validator")
    a = parser.parse_args(argv)

    if a.stage == "all":
        return run_all(a)

    with Guard() as guard:
        if a.stage == "build":
            refuse_repo_out(a.out)
            result = build(a.out, a.entities, a.days, a.rules, guard)
        elif a.stage == "relayout":
            refuse_repo_out(a.dst)
            result = relayout(a.src, a.dst, a.row_group_size, a.dense, not a.keep_order, a.time_order)
        elif a.stage == "profile":
            result = profile(a.published, a.label, a.n, guard)
        elif a.stage == "concurrency":
            result = concurrency(a.published, a.task_id, a.clients, a.seconds, a.scenarios.split(","), guard, a.workers)
        else:
            result = validator(a.obs, a.mode, a.first_k, guard, a.memory_limit)
        result["stage_peak_rss_mb_ru_maxrss"] = round(peak_rss_mb(), 1)
        result["loadavg_1_5_15_at_end"] = [round(x, 1) for x in os.getloadavg()]
        result["min_available_gb_seen"] = round(guard.min_avail_seen / 2**30, 2)
    if a.json:
        a.json.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str)[:3000])


def run_all(a) -> None:
    out = a.out
    if out is None:
        raise SystemExit("--out is required")
    refuse_repo_out(out)
    out.mkdir(parents=True, exist_ok=True)
    skip = set(filter(None, a.skip.split(",")))
    ent, days, seconds, n = (6, 30, 5.0, 5) if a.smoke else (a.entities, a.days, a.seconds, a.n)
    report: dict = {"machine": machine(out), "parameters": {
        "entities": ent, "days": days, "rules": a.rules, "n": n, "clients": a.clients, "seconds": seconds,
        "smoke": a.smoke, "started_utc": datetime.now(timezone.utc).isoformat()}}
    published = out / "published"

    def keep() -> None:
        if a.report:
            a.report.write_text(json.dumps(report, indent=2, default=str))

    def step(name: str, stage: str, args: list[str], json_name: str, allow_fail: bool = False) -> dict:
        """Run a stage, or, when ``name`` is in --skip, reuse the JSON an earlier run left in --out."""
        path = out / json_name
        if name in skip:
            return json.loads(path.read_text()) if path.exists() else {"skipped": True}
        data = run_stage(stage, args, path, allow_fail)
        return data

    report["build"] = step("build", "build", ["--out", str(out), "--entities", str(ent), "--days", str(days),
                                              "--rules", str(a.rules)], "build.json")
    keep()
    # build publishes into <out>/published/<model_id>; the report keeps only the model id (--out is outside the repo)
    mdir = published / Path(report["build"]["model_dir"]).name if "model_dir" in report["build"] else None
    if mdir:
        report["activation_layout_as_published"] = row_group_info(mdir)
    layouts = {  # name -> relayout flags; "published" is the dir the build wrote, the rest are copies of it
        "legacy_time_order": ["--time-order", "--row-group-size", "1048576"],  # the layout before AT-061 B3
        "dense_legacy_time_order": ["--dense", "--time-order", "--row-group-size", "1048576"],
        "dense_sorted_by_rule": ["--dense", "--row-group-size", str(a.row_group_size)],
    }
    wanted = ["legacy_time_order"] if a.smoke else a.layouts.split(",")
    layouts = {k: v for k, v in layouts.items() if k in wanted}
    report["relayout"] = {}
    for name, flags in layouts.items():
        if mdir:
            report["relayout"][name] = step(
                "relayout", "relayout", ["--src", str(mdir), "--dst", str(out / f"published_{name}"), *flags],
                f"r-{name}.json")
            keep()
    profiles = report["profiles"] = {}
    todo = {"synthetic_as_published": published, **{f"synthetic_{k}": out / f"published_{k}" for k in layouts}}
    for name, path in todo.items():
        if path.exists():
            profiles[name] = step(
                "profile", "profile", ["--published", str(path), "--label", name, "--n", str(n)], f"p-{name}.json")
            keep()
    if (a.real / "registry.json").exists():
        profiles["real_models"] = step(
            "real", "profile", ["--published", str(a.real), "--label", "real_models", "--n", str(n)], "p-real.json",
            allow_fail=True)
        keep()
    common = ["--published", str(published), "--task-id", "volume_y_h6", "--clients", str(a.clients),
              "--seconds", str(seconds)]
    report["concurrency"] = step(
        "concurrency", "concurrency", [*common, "--scenarios", a.scenarios, "--workers", "1"], "c-w1.json")
    keep()
    report["concurrency_2_workers"] = step(
        "concurrency", "concurrency", [*common, "--scenarios", "distinct,no_series_full", "--workers", "2"],
        "c-w2.json")
    keep()
    obs = a.real_data / "air" / "observations"
    cases = report["validator"] = {}
    if obs.exists():
        for name, extra in (("air_whole", ["--mode", "whole"]),
                            ("air_whole_unlimited", ["--mode", "whole", "--memory-limit", "80%"]),
                            ("air_partitioned_helper", ["--mode", "partitioned"]),
                            ("air_per_year", ["--mode", "per_year"]),
                            ("air_per_partition", ["--mode", "per_partition"]),
                            ("air_whole_first_24_partitions", ["--mode", "whole", "--first-k", "24"]),
                            ("air_whole_first_48_partitions", ["--mode", "whole", "--first-k", "48"])):
            cases[name] = step("validator", "validator", ["--obs", str(obs), *extra], f"v-{name}.json")
            keep()
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    keep()
    print(f"\nreport: {a.report}")


if __name__ == "__main__":
    main()
