"""Precomputed what-if (docs/static_export.md section 9): one input changed at a time, at the featured instants.

The engine of ``atlas.explain`` (the one ``POST /scenarios`` re-runs) evaluates every variant; the files hold firing,
the memberships of the changed input and the pred-shard output columns, nothing else.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.services import layout
from atlas.services.static import engine, fmt
from atlas.services.static.extract import Ctx, ModelCtx, _out_columns


def grid_for(variable, steps: int = fmt.WHATIF_STEPS) -> list[float]:
    """``steps`` uniform values over the variable's domain plus every term breakpoint inside it, sorted and unique."""
    lo, hi = variable.domain
    values = list(np.linspace(lo, hi, steps))
    for term in variable.terms:
        values += term.params[:1] if term.membership_type == "gaussian" else term.params
    clipped = {float(min(max(round(float(v), 12), lo), hi)) for v in values if lo <= v <= hi}
    return sorted(clipped)


def export_whatif(ctx: Ctx, mc: ModelCtx) -> int:
    """One file per modelled entity with at least one featured row. Returns bytes written."""
    h, out = mc.h, ctx.out
    mid = h.model_id
    variables = {v.feature: v for v in h.rules.variables}
    feats = [f for f in h.features if variables.get(f) is not None and variables[f].domain is not None]
    grids = {f: grid_for(variables[f]) for f in feats}
    ant = engine.antecedent_features(h.model, mc.family)
    pos = {f: j for j, f in enumerate(ant)}
    pairs = engine.pair_positions(h.model, mc.family, mc.pairs)
    pairs_of = {f: [p for p, (ff, _, _) in enumerate(mc.pairs) if ff == f] for f in feats}
    instants = None if not mc.regular else _instants(mc)
    cols = ", ".join(f'"{f}"' for f in ant)
    sql = f"SELECT entity_id, issued_at_utc, {cols} FROM read_parquet(?)"
    params: list = [str(h.path / layout.INPUTS_FILE)]
    if instants is not None:
        sql += " WHERE issued_at_utc IN (SELECT unnest(?))"
        params.append([fmt.parse_iso(t) for t in instants])
    frame = ctx.frame(sql, params)
    if frame.empty:
        return 0
    frame = frame[frame["entity_id"].isin(mc.eidx)].dropna(subset=list(ant))
    frame = frame.assign(_at=[fmt.iso(pd.Timestamp(t).to_pydatetime()) for t in frame["issued_at_utc"]])
    total = 0
    for entity, rows in frame.groupby("entity_id", sort=True):
        rel = f"models/{mid}/whatif/{entity}.json.gz"
        if out.exists(rel) and not out.force:
            continue
        rows = rows.sort_values("issued_at_utc")
        base = rows[list(ant)].to_numpy(dtype=float)
        ats = rows["_at"].tolist()
        k = len(ats)
        blocks, index = [], {}
        start = 0
        for f in feats:
            g = np.array(grids[f])
            block = np.repeat(base, len(g), axis=0)  # instant-major, step-minor
            block[:, pos[f]] = np.tile(g, k)
            blocks.append(block)
            index[f] = (start, len(g))
            start += block.shape[0]
        X = np.vstack(blocks)
        mem, fire, outcols = engine.activate_batches(h.model, mc.family, X, pairs)
        cols_out = _out_columns(mc, outcols)
        variants: dict[str, dict] = {}
        for i, at in enumerate(ats):
            per: dict[str, dict] = {}
            for f in feats:
                s0, size = index[f]
                sl = slice(s0 + i * size, s0 + (i + 1) * size)
                entry = {"f": fire[sl].T, "m": mem[pairs_of[f]][:, sl]}
                for name, col in cols_out.items():
                    entry[name] = col[sl]
                per[f] = entry
            variants[at] = per
        total += out.write(rel, {"v": 1, "kind": "whatif", "model_id": mid, "entity_id": entity, "at": ats,
                                 "grid": grids, "variants": variants})
    return total


def _instants(mc: ModelCtx) -> list[str]:
    from atlas.services.static.extract import whatif_instants

    return whatif_instants(mc)[1] or []
