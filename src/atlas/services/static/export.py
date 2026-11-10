"""Command line of the static export: ``python -m atlas.services.static.export`` (docs/static_export.md section 14)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.paths import REPO_ROOT
from atlas.services import layout
from atlas.services.static import fmt
from atlas.services.static.extract import (
    Ctx,
    Out,
    assign_inputs,
    build_meta,
    export_agg,
    export_day,
    export_id_for,
    export_inputs,
    export_static_files,
    export_stories,
)
from atlas.services.static.store import StaticStore
from atlas_api.main import create_app

# The `kind` of a golden sample / self-check request, and what its `request` holds (docs section 13).
GOLDEN_KINDS = ["predictions", "observations", "ruleMapInstant", "ruleMapWindow", "ruleTerritories", "ruleStories",
                "ruleTrace", "series", "scenario"]
GROUPS = ("static", "inputs", "days", "agg", "stories", "whatif", "finalize")
EXPLANATIONS_DIR = REPO_ROOT / "configs" / "explanations"


# ------------------------------------------------------------------------------------------------ comparison
def diff(a, b, path: str = "$", tol: float = 1e-9):
    """First difference between two decoded JSON values, or None. Floats within ``tol`` (relative, absolute floor)."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return None if a == b and type(a) is type(b) else f"{path}: {a!r} != {b!r}"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return None
        if isinstance(a, float) or isinstance(b, float):
            if math.isclose(a, b, rel_tol=tol, abs_tol=tol):
                return None
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: keys differ {sorted(set(a) ^ set(b))[:5]}"
        for k in a:
            d = diff(a[k], b[k], f"{path}.{k}", tol)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = diff(x, y, f"{path}[{i}]", tol)
            if d:
                return d
        return None
    return f"{path}: type {type(a).__name__} != {type(b).__name__}"


# ------------------------------------------------------------------------------------------------ self-check
class Sampler:
    """Random requests over the real coverage of one model, as the web would make them."""

    def __init__(self, ctx: Ctx, task: str, rng: random.Random):
        self.ctx, self.task, self.rng = ctx, task, rng
        self.mc = ctx.model(task)
        self.meta = ctx.out.read(f"models/{self.mc.model_id}/meta.json.gz")
        self.mid = self.mc.model_id

    def times(self, n: int) -> list[str]:
        keys = self.meta["keys"]
        out = []
        for _ in range(n):
            shard = self.ctx.out.read(f"models/{self.mid}/{self.rng.choice(keys)}/pred.json.gz")
            out.append(self.rng.choice(shard["t"]))
        return out

    def window(self):
        kinds = [k for k in fmt.WINDOW_KINDS if self.meta["windows"][k]]
        if self.meta["windows"]["coverage"]:
            kinds.append("coverage")
        kind = self.rng.choice(kinds)
        if kind == "coverage":
            lo, hi = fmt.coverage_window(fmt.parse_iso(self.meta["coverage"]["from"]),
                                         fmt.parse_iso(self.meta["coverage"]["to"]), self.meta["step_hours"])
        else:
            lo, hi = fmt.window_of(kind, fmt.utc_midnight(self.rng.choice(self.meta["windows"][kind])))
            if self.meta.get("period"):  # inside a period the windows are clipped to it
                lo, hi = self.mc.clip(lo, hi)
        return fmt.iso(lo), fmt.iso(hi)

    def requests(self, n: int) -> list[dict]:
        r, meta = self.rng, self.meta
        task, mid = self.task, self.mid
        rules = meta["rules"]
        taus = meta["taus"]
        regular = meta["regular"]
        entities = meta["entities"]
        reqs: list[dict] = []
        for _ in range(n):
            if regular:
                (t,) = self.times(1)
                reqs.append({"kind": "predictions", "request": {"taskId": task, "time": t}})
                (t,) = self.times(1)
                reqs.append({"kind": "observations", "request": {"taskId": task, "time": t}})
                (t,) = self.times(1)
                reqs.append({"kind": "ruleMapInstant", "request": {
                    "modelId": mid, "ruleId": r.choice(rules), "metric": "firing_strength", "time": t}})
            else:
                lo, hi = self.window()
                reqs.append({"kind": "predictions", "request": {"taskId": task, "from": lo, "to": hi}})
                reqs.append({"kind": "observations", "request": {"taskId": task, "from": lo, "to": hi}})
                (t,) = self.times(1)
                reqs.append({"kind": "predictions", "request": {"taskId": task, "time": t}})
            lo, hi = self.window()
            metric = r.choice(["mean_activation", "activation_frequency"])
            q = {"modelId": mid, "ruleId": r.choice(rules), "metric": metric, "from": lo, "to": hi}
            if metric == "activation_frequency":
                q["tau"] = r.choice(taus)
            reqs.append({"kind": "ruleMapWindow", "request": q})
            lo, hi = self.window()
            measures = ["mean_activation", "activation_frequency"] + (
                ["winner_share"] if meta["family"] == m.InferenceFamily.WINNING_RULE_CLASSIFIER.value else [])
            reqs.append({"kind": "ruleTerritories", "request": {
                "modelId": mid, "from": lo, "to": hi, "measure": r.choice(measures), "tau": r.choice(taus)}})
            lo, hi = self.window()
            reqs.append({"kind": "ruleStories", "request": {
                "modelId": mid, "from": lo, "to": hi, "tau": fmt.STORIES_TAU, "limit": fmt.STORIES_LIMIT}})
            (t,) = self.times(1)
            reqs.append({"kind": "ruleTrace", "request": {"entityId": r.choice(entities), "modelId": mid, "at": t}})
            e = r.choice(entities)
            (t,) = self.times(1)
            t0 = fmt.parse_iso(t)
            s_lo, s_hi = self.mc.clip(t0 - timedelta(days=2), t0 + timedelta(days=4))
            reqs.append({"kind": "series", "request": {
                "taskId": task, "entityId": e, "from": fmt.iso(s_lo), "to": fmt.iso(s_hi)}})
            others = [f.properties.entity_id for f in self.mc.h.entities.features if f.properties.modelled is False]
            if others:
                (t,) = self.times(1)
                reqs.append({"kind": "ruleTrace", "request": {"entityId": r.choice(others), "modelId": mid, "at": t}})
                reqs.append({"kind": "series", "request": {"taskId": task, "entityId": others[0]}})
            if regular:  # an hour that may have no row at all: both sides must say no_observation / 404 alike
                lo = fmt.parse_iso(meta["coverage"]["from"])
                span = int((fmt.parse_iso(meta["coverage"]["to"]) - lo).total_seconds() // 3600) + 1
                at = fmt.iso(lo + timedelta(hours=r.randrange(0, min(span, 24 * 40))))
                reqs.append({"kind": "predictions", "request": {"taskId": task, "time": at}})
                reqs.append({"kind": "ruleTrace", "request": {
                    "entityId": r.choice(entities), "modelId": mid, "at": at}})
            sc = self.scenario()
            if sc:
                reqs.append({"kind": "scenario", "request": sc})
        return reqs

    def scenario(self) -> dict | None:
        files = sorted((self.ctx.out.data / "models" / self.mid / "whatif").glob("*.json.gz"))
        if not files:
            return None
        doc = self.ctx.out.read(f"models/{self.mid}/whatif/{self.rng.choice(files).name}")
        at = self.rng.choice(doc["at"])
        feature = self.rng.choice(sorted(doc["grid"]))
        return {"model_id": self.mid, "entity_id": doc["entity_id"], "at": at,
                "overrides": {feature: self.rng.choice(doc["grid"][feature])}}


def call(client: TestClient, req: dict):
    """The API call behind an ``api.*`` request: (status, JSON body with the redactor applied)."""
    q, kind = req["request"], req["kind"]
    p = {k: v for k, v in {"from": q.get("from"), "to": q.get("to"), "time": q.get("time"), "tau": q.get("tau")}.items()
         if v is not None}
    if kind in ("predictions", "observations"):
        r = client.get(f"/api/v1/{kind}", params={"task_id": q["taskId"], **p})
    elif kind in ("ruleMapInstant", "ruleMapWindow"):
        r = client.get("/api/v1/rule-map", params={"model_id": q["modelId"], "rule_id": q["ruleId"],
                                                   "metric": q["metric"], **p})
    elif kind == "ruleTerritories":
        r = client.get("/api/v1/rule-territories", params={"model_id": q["modelId"], "measure": q["measure"], **p})
    elif kind == "ruleStories":
        r = client.get("/api/v1/rule-stories", params={"model_id": q["modelId"], "limit": q["limit"], **p})
    elif kind == "ruleTrace":
        r = client.get(f"/api/v1/entities/{q['entityId']}/rule-trace", params={"model_id": q["modelId"], "at": q["at"]})
    elif kind == "series":
        r = client.get("/api/v1/series", params={"task_id": q["taskId"], "entity_id": q["entityId"], **p})
    elif kind == "scenario":
        r = client.post("/api/v1/scenarios", json=q)
    else:
        raise ValueError(kind)
    return r.status_code, fmt.redact(r.json())


def self_check(ctx: Ctx, tasks: list[str], data_dir: Path, n: int, seed: int, golden_n: int = 2) -> dict:
    """Random requests answered by the real API and by ``StaticStore`` over the exported files; bodies must match."""
    static = TestClient(create_app(StaticStore(data_dir)))
    by_kind: dict[str, dict] = defaultdict(lambda: {"n": 0, "ok": 0})  # plus http_<status> counts
    failures: list[dict] = []
    golden_by_model: dict[str, list] = defaultdict(list)
    kept: Counter = Counter()
    for task in tasks:
        sampler = Sampler(ctx, task, random.Random(f"{seed}/{task}"))
        mid = sampler.mid
        for req in sampler.requests(n):
            status_a, body_a = call(ctx.client, req)
            status_s, body_s = call(static, req)
            stat = by_kind[req["kind"]]
            stat["n"] += 1
            stat[f"http_{status_a}"] = stat.get(f"http_{status_a}", 0) + 1
            problem = None if status_a == status_s else f"status {status_a} != {status_s}"
            problem = problem or diff(body_a, body_s)
            if problem:
                failures.append({"kind": req["kind"], "model_id": mid, "request": req["request"], "diff": problem})
            else:
                stat["ok"] += 1
                if kept[(mid, req["kind"])] < golden_n:
                    kept[(mid, req["kind"])] += 1
                    golden_by_model[mid].append({"kind": req["kind"], "model_id": mid, "request": req["request"],
                                                 "status": status_a, "body": body_a})
        # exact bodies: the static copy equals the API's answer
        for url in (f"/api/v1/models/{mid}", f"/api/v1/models/{mid}/rules", f"/api/v1/models/{mid}/importance",
                    f"/api/v1/models/{mid}/explanation"):
            req = {"kind": "exact", "request": {"url": url}}
            a, b = ctx.client.get(url), static.get(url)
            stat = by_kind["exact"]
            stat["n"] += 1
            problem = None if a.status_code == b.status_code else f"status {a.status_code} != {b.status_code}"
            problem = problem or diff(fmt.redact(a.json()), b.json())
            if problem:
                failures.append({"kind": "exact", "model_id": mid, "request": req["request"], "diff": problem})
            else:
                stat["ok"] += 1
    for mid, items in golden_by_model.items():
        ctx.out.write(f"{mid}.json.gz", items, golden=True)
    ctx.out.write("index.json.gz", {
        "format": 1, "export_id": ctx.out.export_id, "n": sum(map(len, golden_by_model.values())),
        "kinds": GOLDEN_KINDS,
        "models": {mid: {"file": f"{mid}.json.gz", "n": len(items)} for mid, items in sorted(golden_by_model.items())}},
        golden=True)
    total = sum(s["n"] for s in by_kind.values())
    ok = sum(s["ok"] for s in by_kind.values())
    return {"n_checked": total, "n_passed": ok, "tolerance": 1e-9, "seed": seed, "per_model": n,
            "by_kind": dict(by_kind), "failures": failures[:20]}


# ------------------------------------------------------------------------------------------------ manifest
def file_kind(rel: str) -> str:
    parts = rel.split("/")
    name = parts[-1].removesuffix(".json.gz")
    if parts[0] == "inputs" or "inputs" in parts:
        return "inputs"
    if "agg" in parts:
        return "agg"
    if "stories" in parts:
        return "stories"
    if "whatif" in parts:
        return "whatif"
    if name in ("pred", "fire", "mem", "meta", "card", "rules", "importance", "explanation", "summary", "entities"):
        return name
    return "other"


def finalize(ctx: Ctx, tasks: list[str], args, export_id: str, started: float) -> dict:
    out = ctx.out
    data = out.data
    fmt.audit_tree(data)
    index, by_kind, per_model = {}, Counter(), defaultdict(Counter)
    for p in fmt.walk_files(data):
        rel = p.relative_to(data).as_posix()
        if rel in ("manifest.json", "files.json.gz"):
            continue
        raw = p.read_bytes()
        index[rel] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        kind = file_kind(rel)
        by_kind[kind] += len(raw)
        mid = next((x for x in rel.split("/") if x.startswith("exfuzzy-")), None)
        if mid:
            per_model[mid][kind] += len(raw)
            per_model[mid]["files"] += 1
    out.write("files.json.gz", index)
    index_raw = (data / "files.json.gz").read_bytes()
    reasons = fmt.MISSING_REASONS
    golden = self_check(ctx, tasks, data, args.check_n, args.seed)
    manifest = {
        "format": "exfuzzy-atlas-static", "format_version": fmt.FORMAT_VERSION, "export_id": export_id,
        "created_at_utc": fmt.iso(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
        "schema_version": m.SCHEMA_VERSION, "exfuzzy_version": _exfuzzy(), "exporter": fmt.EXPORTER,
        "source": {
            "registry_sha256": hashlib.sha256((ctx.published / layout.REGISTRY_FILE).read_bytes()).hexdigest(),
            "models": {ctx.registry.tasks[t].model_id: {
                "checksums_sha256": _sha_or_none(ctx.published / ctx.registry.tasks[t].model_id / "SHA256SUMS"),
                "explanation_sha256": _sha_or_none(
                    Path(args.explanations_dir) / f"{ctx.registry.tasks[t].model_id}.json"),
            } for t in tasks}},
        "tasks": {t: {"model_id": ctx.registry.tasks[t].model_id, "domain": ctx.registry.tasks[t].domain.value,
                      "territory": ctx.registry.tasks[t].territory, "regular": ctx.model(t).regular,
                      "keys": len(ctx.model(t).keys),
                      "coverage": {"from": fmt.iso(ctx.model(t).first), "to": fmt.iso(ctx.model(t).last)},
                      "period": _period_doc(ctx.model(t))} for t in tasks},
        "base": {"export_id": args.base_id, "reused_tasks": args.reused},
        "params": {"taus": fmt.TAUS, "stories_tau": fmt.STORIES_TAU, "stories_limit": fmt.STORIES_LIMIT,
                   "series_max_points": fmt.SERIES_MAX_POINTS, "missing_reasons": reasons,
                   "whatif_steps": fmt.WHATIF_STEPS, "whatif": not args.no_whatif},
        "totals": {"files": len(index), "bytes": sum(v["bytes"] for v in index.values()),
                   "by_kind": dict(by_kind)},
        "per_model": {k: {"files": v.pop("files"), "bytes": sum(v.values()), "by_kind": dict(v)}
                      for k, v in per_model.items()},
        "files_index": {"path": "files.json.gz", "sha256": hashlib.sha256(index_raw).hexdigest()},
        "texts": texts(), "golden": golden,
        "privacy": {"files_scanned": 0, "checks": fmt.PRIVACY_CHECKS, "violations": 0},
        "cuts": [], "seconds": round(time.time() - started),
    }
    text = json.dumps(manifest, indent=1, ensure_ascii=False)
    (data / "manifest.json").write_text(text)
    n_files, bad = fmt.scan_privacy(data)
    manifest["privacy"].update(files_scanned=n_files, violations=len(bad), hits=bad[:20])
    (data / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    if bad:
        raise SystemExit(f"privacy check failed ({len(bad)} files): {bad[:5]}")
    if golden["n_passed"] != golden["n_checked"]:
        raise SystemExit(f"golden parity failed: {golden['n_passed']}/{golden['n_checked']}: {golden['failures'][:3]}")
    return manifest


def _period_doc(mc):
    return None if mc.period is None else {"from": fmt.iso(mc.period[0]), "to": fmt.iso(mc.period[1])}


def _territory(mc) -> str:
    return mc.entry.territory or mc.entry.domain.value


def texts() -> dict:
    """Texts the API writes from constants of its own code that the web rebuilds into responses: shipped, not copied."""
    from atlas.services import scenarios, territories

    return {
        "tie_break": territories.TIE_BREAK, "denominators": territories.DENOMINATORS,
        "territory_notes": territories.NOTES, "tie_tolerance": m.TIE_TOLERANCE,
        "what_if_label": m.WHAT_IF_LABEL, "what_if_warning": scenarios.OVERRIDE_WARNING,
        "override_source_id": scenarios.OVERRIDE_SOURCE_ID,
        "observations_note": m.ObservationsResponse.model_fields["note"].default,
    }


def _sha_or_none(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _exfuzzy() -> str:
    from atlas.ml.exfuzzy_features import exfuzzy_version

    return exfuzzy_version()


# ------------------------------------------------------------------------------------------------ main
def resolve(ctx: Ctx, names: list[str] | None) -> list[str]:
    tasks = ctx.registry.tasks
    if not names:
        return sorted(tasks)
    out = []
    for n in names:
        hit = [t for t, e in tasks.items() if n in (t, e.model_id)]
        if not hit:
            raise SystemExit(f"{n}: not a task_id or model_id of the registry")
        out.append(hit[0])
    return sorted(out)


def parse_instant_pair(text: str):
    lo, hi = text.split(",")
    return fmt.parse_iso(lo), fmt.parse_iso(hi)


def resolve_periods(ctx: Ctx, tasks: list[str], overrides: list[str]) -> dict[str, tuple]:
    """task_id -> (first, last) issue time: ``--period`` by task, model or territory, else ``DEFAULT_PERIODS``."""
    given = dict(o.split("=", 1) for o in overrides)
    out = {}
    for t in tasks:
        e = ctx.registry.tasks[t]
        for key in (t, e.model_id, e.territory):
            if key in given:
                text = given[key]
                break
        else:
            default = fmt.DEFAULT_PERIODS.get(e.territory or "")
            text = f"{default[0]},{default[1]}" if default else "full"
        if text != "full":
            out[t] = parse_instant_pair(text)
    return out


def reuse_from_base(ctx: Ctx, base: Path, tasks: list[str], only: set[str], args) -> set[str]:
    """Hard-link (else copy) the files of the models that a previous export already holds, unchanged."""
    import os
    import shutil

    manifest = json.loads((base / "manifest.json").read_text())
    args.base_id = manifest["export_id"]
    if (manifest.get("format_version") != fmt.FORMAT_VERSION or manifest["params"]["taus"] != fmt.TAUS
            or manifest["params"].get("whatif") != (not args.no_whatif)):
        return set()
    ok: set[str] = set()
    for t in tasks:
        e = ctx.registry.tasks[t]
        old = manifest["source"]["models"].get(e.model_id)
        sums = _sha_or_none(ctx.published / e.model_id / "SHA256SUMS")
        expl = _sha_or_none(Path(args.explanations_dir) / f"{e.model_id}.json")
        period = _period_doc(ctx.model(t))
        same = (old and old["checksums_sha256"] == sums and old["explanation_sha256"] == expl
                and manifest["tasks"].get(t, {}).get("model_id") == e.model_id
                and manifest["tasks"][t].get("period") == period)
        if same and t not in only and (base / "models" / e.model_id).is_dir():
            ok.add(t)

    def link_tree(rel: str) -> None:
        src = base / rel
        for p in sorted(src.rglob("*")) if src.is_dir() else []:
            if p.is_file():
                dst = ctx.out.data / p.relative_to(base)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.unlink(missing_ok=True)
                try:
                    os.link(p, dst)
                except OSError:
                    shutil.copy2(p, dst)

    for t in ok:
        link_tree(f"models/{ctx.registry.tasks[t].model_id}")
        link_tree(f"tasks/{t}")
    # the shared inputs of a territory are reusable only if every task of it is, and the territory is the same;
    # otherwise they are rewritten from every member's table (the reused models keep their own files)
    by_ter: dict[str, set[str]] = defaultdict(set)
    for t in tasks:
        if ctx.model(t).regular:
            by_ter[_territory(ctx.model(t))].add(t)
    args.rebuild_inputs = set()
    for ter, ts in by_ter.items():
        before = {t for t, v in manifest["tasks"].items() if v["regular"] and (v["territory"] or v["domain"]) == ter}
        if ts <= ok and before == ts:
            link_tree(f"inputs/{ter}")
        else:
            args.rebuild_inputs.add(ter)
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m atlas.services.static.export", description=__doc__)
    ap.add_argument("--published-dir", type=Path, default=REPO_ROOT / "artifacts" / "published")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--explanations-dir", type=Path, default=EXPLANATIONS_DIR)
    ap.add_argument("--tasks", help="task_id or model_id list of this export (default: the whole registry)")
    ap.add_argument("--only", help="restrict this run to these tasks/models (the export id does not change)")
    ap.add_argument("--groups", default=",".join(GROUPS), help=f"comma list of {GROUPS}")
    ap.add_argument("--force", action="store_true", help="rewrite files that already exist")
    ap.add_argument("--check-n", type=int, default=3, help="self-check: random requests per kind and model")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-whatif", action="store_true", help="skip the what-if group (and its meta)")
    ap.add_argument("--period", action="append", default=[], metavar="KEY=FROM,TO",
                    help="issue-time period of a task, model or territory (inclusive); 'KEY=full' = whole coverage. "
                         "Default: germany=2025-01-01T00:00:00Z,2025-03-31T23:00:00Z")
    ap.add_argument("--base", type=Path, help="a previous data/<export_id> directory: models whose published files, "
                    "explanation and period are unchanged are reused (hard links), the rest is exported")
    args = ap.parse_args(argv)
    groups = [g for g in args.groups.split(",") if g]
    unknown = set(groups) - set(GROUPS)
    if unknown:
        raise SystemExit(f"unknown groups {sorted(unknown)}")
    started = time.time()
    probe = Ctx(args.published_dir, Out.__new__(Out))  # registry only
    tasks = resolve(probe, args.tasks.split(",") if args.tasks else None)
    periods = resolve_periods(probe, tasks, args.period)
    spec = {"taus": fmt.TAUS, "whatif": not args.no_whatif,
            "periods": {t: [fmt.iso(p[0]), fmt.iso(p[1])] for t, p in sorted(periods.items())}}
    export_id = export_id_for(args.published_dir, tasks, args.explanations_dir, spec)
    out = Out(args.out, export_id, force=args.force)
    ctx = Ctx(args.published_dir, out, periods=periods)
    only = resolve(ctx, args.only.split(",")) if args.only else None
    if only is not None and not set(only) <= set(tasks):
        raise SystemExit("--only must be inside --tasks")
    args.base_id, args.reused, args.rebuild_inputs = None, [], None
    reused: set[str] = set()
    if args.base:
        reused = reuse_from_base(ctx, args.base, tasks, set(only or ()), args)
        args.reused = sorted(reused)
        print(f"base {args.base_id}: reusing {len(reused)} of {len(tasks)} tasks", flush=True)
    work = [t for t in (only or tasks) if t not in reused]
    needs_inputs = {"static", "inputs", "days", "whatif", "finalize"}
    groups_info = assign_inputs(ctx, tasks) if set(groups) & needs_inputs else None
    territories: dict[str, list[str]] = defaultdict(list)
    for t in work:
        mc = ctx.model(t)
        if mc.regular:
            territories[_territory(mc)].append(t)
    for ter in args.rebuild_inputs or ():  # shared inputs that change although no model of the territory does
        territories.setdefault(ter, [])
    units = []
    if "static" in groups:  # cheap, and it rewrites the meta of reused models (their input paths may have changed)
        units += [("static", t) for t in (tasks if args.base else work)]
    if "inputs" in groups:
        units += [("inputs", ter) for ter in sorted(territories)]
    for g in ("days", "agg", "stories", "whatif"):
        if g in groups:
            units += [(g, t) for t in work if not (g == "whatif" and args.no_whatif)]
    if "finalize" in groups:
        units.append(("finalize", "all"))
    N = len(units)
    print(f"export_id={export_id} tasks={len(tasks)} work={len(work)} out={out.data}", flush=True)
    for k, (group, what) in enumerate(units, 1):
        t0 = time.time()
        if group == "static":
            mc = ctx.model(what)
            export_static_files(ctx, [what])
            meta = build_meta(ctx, mc, groups_info, with_whatif=not args.no_whatif)
            out.write(f"models/{mc.model_id}/meta.json.gz", meta)
        elif group == "inputs":
            ts = sorted(t for t in tasks if ctx.model(t).regular and _territory(ctx.model(t)) == what)
            days = sorted({d for t in ts for d in ctx.model(t).days})
            for n, d in enumerate(days, 1):
                export_inputs(ctx, ts, groups_info, d)
                if n % 50 == 0:
                    print(f"  inputs {what}: day {n} of {len(days)}", flush=True)
        elif group == "days":
            mc = ctx.model(what)
            for n, key in enumerate(mc.keys, 1):
                export_day(ctx, mc, key)
                if n % 25 == 0:
                    print(f"  days {mc.task_id}: shard {n} of {len(mc.keys)}", flush=True)
        elif group == "agg":
            export_agg(ctx, ctx.model(what))
        elif group == "stories":
            export_stories(ctx, ctx.model(what))
        elif group == "whatif":
            from atlas.services.static.whatif import export_whatif

            export_whatif(ctx, ctx.model(what))
        elif group == "finalize":
            manifest = finalize(ctx, tasks, args, export_id, started)
            print(f"  total {manifest['totals']['bytes'] / 1e6:.1f} MB in {manifest['totals']['files']} files; "
                  f"golden {manifest['golden']['n_passed']}/{manifest['golden']['n_checked']}; "
                  f"privacy violations {manifest['privacy']['violations']}", flush=True)
        print(f"[{k}/{N}] group={group} {what} ({time.time() - t0:.0f}s)", flush=True)
    print(f"done in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
