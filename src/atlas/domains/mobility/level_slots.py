# ruff: noqa: E501  (prose)
"""Why the reference cell is zone x week-hour (AT-031b): a hold-out comparison of slot granularities, train period only.

    PYTHONPATH=src python -m atlas.domains.mobility.level_slots

For each candidate slot definition, the reference of a (zone, slot) cell is the empirical distribution of the target in the
fit part of the train period (before ``--holdout-from``); it is scored on the target of the held-out part of the **train**
period (validation and test are not read) with the CRPS of that empirical distribution, divided by the zone's fit mean so
zones of any size weigh the same, and averaged over zones. Lower is better. It answers "which cell predicts the usual level
of unseen weeks better", not "which gives the best classifier".
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from atlas.domains.mobility import features as F
from atlas.paths import PROCESSED_DIR, REPO_ROOT

SLOTS = {
    "zone": lambda h, w: np.zeros(len(h), int),
    "hour": lambda h, w: h,
    "hour x weekday/weekend": lambda h, w: h * 2 + (w >= 5),
    "hour x weekday/Sat/Sun": lambda h, w: h * 3 + np.where(w < 5, 0, w - 4),
    "hour x day of week (168)": lambda h, w: h * 7 + w,
}


def crps_empirical(sample: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of the empirical distribution of ``sample`` for each observation in ``y``."""
    x = np.sort(sample)
    n = len(x)
    pairwise = (2 * (2 * np.arange(1, n + 1) - n - 1) * x).sum() / n**2  # E|X - X'|
    return np.abs(x[None, :] - y[:, None]).mean(axis=1) - 0.5 * pairwise


def compare(frame: pd.DataFrame, train: list[str], holdout_from: str, edges=(3, 10, 50)) -> pd.DataFrame:
    t0, t1, cut = (pd.Timestamp(s) for s in (train[0], train[1], holdout_from))
    df = frame[frame.target.notna() & (frame.issued_at_utc >= t0) & (frame.issued_at_utc < t1)]
    fit, hold = df[df.issued_at_utc < cut], df[df.issued_at_utc >= cut]
    zone_mean = fit.groupby("entity_id").target.mean()
    group = pd.Series(np.searchsorted(np.array(edges, float), zone_mean.to_numpy(), side="right"), index=zone_mean.index)
    out = {}
    for name, slot in SLOTS.items():
        f = fit.assign(s=slot(fit.local_hour.to_numpy(), fit.local_dow.to_numpy()))
        h = hold.assign(s=slot(hold.local_hour.to_numpy(), hold.local_dow.to_numpy()))
        cells = {k: g.target.to_numpy() for k, g in f.groupby(["entity_id", "s"])}
        scores = {}
        for (zone, s), g in h.groupby(["entity_id", "s"]):
            scores.setdefault(zone, []).append(crps_empirical(cells[(zone, s)], g.target.to_numpy()))
        per_zone = pd.Series({z: np.concatenate(v).mean() for z, v in scores.items()}) / zone_mean
        row = {"all zones": per_zone.mean()}
        for i, label in enumerate(["<3/h", "3-10/h", "10-50/h", ">=50/h"]):
            row[label] = per_zone[group.reindex(per_zone.index) == i].mean()
        row["cells per zone"] = f.groupby(["entity_id", "s"]).ngroups / f.entity_id.nunique()
        out[name] = row
    return pd.DataFrame(out).T


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-from", default="2024-10-01T00:00:00Z")
    args = parser.parse_args(argv)
    cfg = json.loads((REPO_ROOT / "configs" / "mobility" / "nyc_pickups_h1.json").read_text())
    frame = pd.read_parquet(
        PROCESSED_DIR / "mobility" / "features" / F.TABLE_DIRNAME,
        columns=["entity_id", "issued_at_utc", "target", "local_hour", "local_dow"],
    )
    frame["entity_id"] = frame["entity_id"].astype(str)
    print(compare(frame, cfg["split"]["train"], args.holdout_from).round(4).to_string())


if __name__ == "__main__":
    main()
