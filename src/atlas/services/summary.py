"""Distribution of the observed variable of a task over its whole history (contract v0.5, ``GET /api/v1/summary``).

Computed once, from the feature table that was published from (all of it, not only the published window), and stored as
``summary.json``. It describes the data, not the model.

* **Observed variable.** The table's target column (``RunConfig.target_column``), or the ``column`` of the ``summary``
  block of the publish metadata. Air: the hourly NO2 of the target hour. Water: the dissolved oxygen of the sample. NYC:
  the raw pickups of the zone-hour (the level classes are relative to each zone's own normal and uniform by
  construction, so they say nothing).
* **Each observed value counts once** per entity and time: rows are deduplicated on ``(entity_id, time)`` and two
  rows of the same entity and time with different values are an error. The time is the time of the observed value:
  the table's ``valid_at_utc`` (issue time + horizon) unless the metadata says ``issued_at_utc`` (NYC: the pickups
  of ``[T, T+1)`` are keyed by ``T``, while ``valid_at_utc`` is the end of that window).
* **Entities.** Those the model was published for (``modelled`` in ``entities.geojson``), which share one time zone;
  month, hour and weekday are local to it.
* **Classes or quantiles.** With an official or analytical ``target_scheme`` the values are binned into its classes with
  the convention of ``publish.classify_observed``; otherwise rows carry p10, p25, p50, p75, p90 and the mean.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.contracts import models as m

QUANTILES = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90}
_GROUPS = {  # group -> (column of the grouped query, key text)
    m.SummaryGroup.YEAR: ("y", lambda v: f"{int(v)}"),
    m.SummaryGroup.MONTH: ("mo", lambda v: f"{int(v):02d}"),
    m.SummaryGroup.HOUR: ("h", lambda v: f"{int(v):02d}"),
    m.SummaryGroup.WEEKDAY: ("wd", lambda v: f"{int(v)}"),
    m.SummaryGroup.ENTITY: ("entity_id", str),
}
_SETS = "GROUPING SETS ((), (y), (mo), (h), (wd), (entity_id))"


class SummaryError(ValueError):
    pass


def classes_for(scheme: m.TargetScheme | None) -> m.TargetScheme | None:
    """The scheme to bin into: an official or analytical one (a percentile-reference level is not observed)."""
    if scheme is None or scheme.kind == m.SchemeKind.PERCENTILE_REFERENCE:
        return None
    return scheme


def _table_columns(con, source: str) -> set[str]:
    return {row[0] for row in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [source]).fetchall()}


def compute_summary(
    con, *, source: str, task_id: str, domain: m.Domain, variable: str, label: str, unit: str, column: str,
    time_column: str, horizon_hours: int, entity_ids: list[str], timezone: str, scheme: m.TargetScheme | None,
    data_version: str, synthetic: bool, notes: list[str] = (),
) -> m.SummaryResponse:
    """``SummaryResponse`` of the feature table ``source`` (a Parquet file, glob or directory pattern).

    ``scheme`` is the class scheme to bin into (``None``: quantiles). ``time_column`` is ``valid_at_utc`` or
    ``issued_at_utc``; a table without ``valid_at_utc`` gets issue time + ``horizon_hours``.
    """
    from atlas.services.publish import classify_observed  # publish imports this module's caller

    columns = _table_columns(con, source)
    if column not in columns or "entity_id" not in columns or "issued_at_utc" not in columns:
        raise SummaryError(f"the feature table needs entity_id, issued_at_utc and the observed column {column!r}")
    if time_column == "valid_at_utc" and "valid_at_utc" not in columns:
        time = f"CAST(issued_at_utc AS TIMESTAMPTZ) + INTERVAL {int(horizon_hours)} HOUR"
    elif time_column in ("valid_at_utc", "issued_at_utc"):
        time = f"CAST({time_column} AS TIMESTAMPTZ)"
    else:
        raise SummaryError(f"time_column must be valid_at_utc or issued_at_utc, got {time_column!r}")
    tz = timezone.replace("'", "''")
    scheme_sql = "CAST(floor(v + 0.5) AS BIGINT) AS rv, " if scheme is not None else ""
    # numeric: the quantiles of each group; classes: the count of each rounded value (a few hundred distinct values)
    if scheme is None:
        measures = "count(*) AS n, quantile_cont(v, [0.1, 0.25, 0.5, 0.75, 0.9]) AS q, avg(v) AS mean"
        by_value = ""
    else:
        measures = "count(*) AS n"
        by_value = ", rv"
    query = f"""
        WITH d AS (
            SELECT entity_id, {time} AS t, any_value({_q(column)}) AS v, count(DISTINCT {_q(column)}) AS nv
            FROM read_parquet(?)
            WHERE {_q(column)} IS NOT NULL AND isfinite({_q(column)}) AND list_contains(?, entity_id)
            GROUP BY entity_id, {time}),
        l AS (
            SELECT entity_id, v, nv, t, {scheme_sql}
                   year(timezone('{tz}', t)) AS y, month(timezone('{tz}', t)) AS mo,
                   hour(timezone('{tz}', t)) AS h, isodow(timezone('{tz}', t)) - 1 AS wd
            FROM d)
        SELECT y, mo, h, wd, entity_id{by_value}, {measures}, max(nv) AS nv_max, min(t) AS t_min, max(t) AS t_max
        FROM l GROUP BY {_SETS}{by_value}
    """
    frame = con.execute(query, [source, list(entity_ids)]).df()
    if frame.empty:
        raise SummaryError("the feature table has no observed values for the published entities")
    if int(frame["nv_max"].max()) > 1:
        raise SummaryError("two rows of one entity and time carry different observed values")

    def rows_of(group: m.SummaryGroup) -> pd.DataFrame:
        if group == m.SummaryGroup.ALL:
            return frame[frame[["y", "mo", "h", "wd", "entity_id"]].isna().all(axis=1)]
        col = _GROUPS[group][0]
        others = [c for c in ("y", "mo", "h", "wd", "entity_id") if c != col]
        return frame[frame[col].notna() & frame[others].isna().all(axis=1)]

    everything = rows_of(m.SummaryGroup.ALL)
    period = (everything["t_min"].min(), everything["t_max"].max())

    labels = None
    out_of_scheme = 0
    if scheme is not None:
        values = sorted(frame["rv"].dropna().astype("int64").unique())
        label_of = dict(zip(values, classify_observed(scheme, values), strict=True))
        names = [c.label for c in scheme.classes]
        labels = {v: (names.index(c) if c is not None else None) for v, c in label_of.items()}

    def distribution(key: str, part: pd.DataFrame) -> m.DistributionRow:
        if scheme is None:
            row = part.iloc[0]
            return m.DistributionRow(
                key=key, n=int(row["n"]),
                quantiles={**dict(zip(QUANTILES, (float(x) for x in row["q"]), strict=True)),
                           "mean": float(row["mean"])},
            )
        counts = np.zeros(len(scheme.classes))
        for rv, n in zip(part["rv"].astype("int64"), part["n"], strict=True):
            if labels[rv] is not None:
                counts[labels[rv]] += n
        n = int(counts.sum())
        return m.DistributionRow(key=key, n=n, shares=[float(c / n) if n else 0.0 for c in counts])

    groups: dict[m.SummaryGroup, list[m.DistributionRow]] = {m.SummaryGroup.ALL: [distribution("all", everything)]}
    for group, (col, text) in _GROUPS.items():
        part = rows_of(group)
        rows = {text(k): g for k, g in part.groupby(col)}
        if group == m.SummaryGroup.ENTITY:  # every published entity, also one without observed values
            groups[group] = [distribution(e, rows[e]) if e in rows else _no_values(e, scheme)
                             for e in sorted(entity_ids)]
        else:
            groups[group] = [distribution(k, rows[k]) for k in sorted(rows)]
    if scheme is not None:
        out_of_scheme = int(everything["n"].sum()) - groups[m.SummaryGroup.ALL][0].n
    n_values = int(everything["n"].sum())

    texts = list(notes) + [
        f"{n_values} valores observados entre {period[0]:%Y-%m-%d} y {period[1]:%Y-%m-%d}: todo el histórico de la "
        "tabla de variables, no solo el periodo publicado; cada valor cuenta una vez por entidad e instante.",
        f"Mes, hora y día de la semana en hora local ({timezone}). Describe los datos, no el modelo.",
    ]
    if out_of_scheme:
        texts.append(f"{out_of_scheme} valores quedan fuera de las clases del esquema y no se cuentan en ellas.")
    return m.SummaryResponse(
        data_version=data_version, synthetic=synthetic, task_id=task_id, domain=domain, variable=variable, label=label,
        unit=unit, timezone=timezone, period_from_utc=period[0], period_to_utc=period[1],
        classes=None if scheme is None else scheme.classes, groups=groups, notes=texts,
    )


def _no_values(key: str, scheme: m.TargetScheme | None) -> m.DistributionRow:
    return m.DistributionRow(key=key, n=0, shares=None if scheme is None else [0.0] * len(scheme.classes))


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
