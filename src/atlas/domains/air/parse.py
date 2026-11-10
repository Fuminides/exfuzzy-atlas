"""Parsing of the Madrid hourly air-quality files and conversion to the canonical long table.

Source layout (``interprete_ficheros_calidad_aire_horario.pdf``): one record per station x magnitude x day
with 24 hourly values ``H01..H24`` and validity codes ``V01..V24``, in **local Madrid time**.

Time convention, fixed by the interpreter's note on ``H24`` ("mean of the six ten-minute values from 23h to
24h") and confirmed empirically (slot ``H03`` is invalid for every station on every spring-forward day, see
``docs/air/madrid_air_quality.md``): slot ``Hnn`` is the hour **ending** at ``nn:00`` local time, i.e. it starts
at ``(nn-1):00``. ``timestamp_utc`` is the **start** of that hour in UTC.

DST strategy (documented in ``docs/air/README.md``):

* Spring forward (23-hour day): the local hour ``02:00-03:00`` does not exist. The source leaves slot ``H03``
  invalid; it has no UTC instant, so no canonical row is written for it and it is counted in the report.
* Fall back (25-hour day): the local hour ``02:00-03:00`` happens twice but the source holds 24 slots; the
  interpreter says the *repeated* hour is eliminated. Slot ``H03`` is therefore the **first** occurrence (summer time,
  UTC+2) and the second one (``01:00Z``) has no row at all.
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyarrow as pa

from atlas.contracts.observations import OBSERVATION_SCHEMA

TIMEZONE = "Europe/Madrid"
SOURCE_ID = "madrid-air"
VALID_FLAG = "V"
SLOTS = [f"{i:02d}" for i in range(1, 25)]
VALUE_COLUMNS = [f"H{s}" for s in SLOTS]
FLAG_COLUMNS = [f"V{s}" for s in SLOTS]

# Magnitude code -> (feature_name, unit). Annex II of the interpreter; units written ASCII like the contract examples.
MAGNITUDES: dict[int, tuple[str, str]] = {
    1: ("so2", "ug/m3"),
    6: ("co", "mg/m3"),
    7: ("no", "ug/m3"),
    8: ("no2", "ug/m3"),
    9: ("pm25", "ug/m3"),
    10: ("pm10", "ug/m3"),
    12: ("nox", "ug/m3"),
    14: ("o3", "ug/m3"),
    20: ("tol", "ug/m3"),
    30: ("ben", "ug/m3"),
    35: ("ebe", "ug/m3"),
    37: ("mxy", "ug/m3"),
    38: ("pxy", "ug/m3"),
    39: ("oxy", "ug/m3"),
    42: ("tch", "mg/m3"),
    43: ("ch4", "mg/m3"),
    44: ("nmhc", "mg/m3"),
    431: ("mpx", "mg/m3"),
}

KEY = ["station", "magnitude", "year", "month", "day"]
ID_COLUMNS = ["province", "municipality", "station", "magnitude", "technique", "year", "month", "day"]
_CSV_RENAME = {
    "PROVINCIA": "province",
    "MUNICIPIO": "municipality",
    "ESTACION": "station",
    "MAGNITUD": "magnitude",
    "PUNTO_MUESTREO": "sampling_point",
    "ANO": "year",
    "MES": "month",
    "DIA": "day",
}
_CSV_HEADER = [*_CSV_RENAME, *(c for s in SLOTS for c in (f"H{s}", f"V{s}"))]
# Pre-October-2017 TXT files have two-digit years; the data set starts in 2019 so only the 4-digit layout is read.
_TXT_COLUMNS = [
    *"province municipality station magnitude technique period year month day".split(),
    *(c for s in SLOTS for c in (f"H{s}", f"V{s}")),
]


COUNTER_KEYS = (
    "wide_rows_read",
    "slots_read",
    "canonical_rows",
    "valid_rows",
    "valid_negative_rows",
    "rows_impossible_date",
    "slots_impossible_date",
    "slots_dst_nonexistent",
    "slots_dst_nonexistent_not_flagged_invalid",
    "duplicate_slots_same_format",
    "overlap_slots_cross_format",
    "invalid_slots_with_zero",
    "invalid_slots_with_number",
)


class SchemaError(ValueError):
    """The file does not look like the documented layout (the portal changed it)."""


@dataclass
class Stats:
    """Counters gathered while converting; merged across units."""

    counters: Counter = field(default_factory=Counter)
    by_flag: Counter = field(default_factory=Counter)
    unknown_magnitude_slots: Counter = field(default_factory=Counter)
    dst_days: dict[str, dict] = field(default_factory=dict)
    txt_only_slots: Counter = field(default_factory=Counter)  # "year/feature" -> slots present only in TXT

    def merge(self, other: Stats) -> None:
        self.counters.update(other.counters)
        self.by_flag.update(other.by_flag)
        self.unknown_magnitude_slots.update(other.unknown_magnitude_slots)
        self.txt_only_slots.update(other.txt_only_slots)
        for day, info in other.dst_days.items():
            mine = self.dst_days.setdefault(day, {"rows": 0, "invalid_per_slot": [0] * 24})
            mine["rows"] += info["rows"]
            mine["invalid_per_slot"] = [
                a + b for a, b in zip(mine["invalid_per_slot"], info["invalid_per_slot"], strict=True)
            ]


# ------------------------------------------------------------------------------ readers


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_csv_wide(raw: bytes | str, chunksize: int | None = None):
    """Read a semicolon CSV of the official layout into the wide frame (all values kept as text).

    With ``chunksize`` returns an iterator of frames, otherwise a single frame.
    """
    text = raw if isinstance(raw, str) else _decode(raw)
    first = text.split("\n", 1)[0].replace('"', "").strip().replace("AÑO", "ANO")
    if first.split(";") != _CSV_HEADER:
        raise SchemaError(f"unexpected CSV header: {first[:200]}")
    reader = pd.read_csv(
        io.StringIO(text),
        sep=";",
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        header=0,
        names=_CSV_HEADER,
        skiprows=0,
    )
    if chunksize is None:
        return _from_csv(reader)
    return (_from_csv(chunk) for chunk in reader)


def _from_csv(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns=_CSV_RENAME)
    frame["technique"] = frame["sampling_point"].str.rsplit("_", n=1).str[-1].str.strip()
    frame["fmt"] = "csv"
    return frame.drop(columns="sampling_point")


def read_txt_wide(raw: bytes | str) -> pd.DataFrame:
    """Read a comma-separated, header-less TXT (``28,079,004,08,08,02,2019,01,01,00023,V,...``)."""
    text = raw if isinstance(raw, str) else _decode(raw)
    frame = pd.read_csv(io.StringIO(text), sep=",", header=None, dtype=str, keep_default_na=False)
    if frame.shape[1] != len(_TXT_COLUMNS):
        raise SchemaError(f"unexpected TXT width {frame.shape[1]}, expected {len(_TXT_COLUMNS)}")
    frame.columns = _TXT_COLUMNS
    if (frame["period"] != "02").any():
        raise SchemaError("TXT file contains non-hourly records (period code != 02)")
    if frame["year"].str.len().min() != 4:
        raise SchemaError("two-digit years (pre-October-2017 layout) are not supported")
    frame["technique"] = frame["technique"].str.lstrip("0")
    frame["fmt"] = "txt"
    return frame.drop(columns="period")


def iter_zip_units(zip_path) -> Iterator[tuple[str, list[pd.DataFrame]]]:
    """Yield ``(stem, [csv_frame, txt_frame])`` per monthly file of an annual ZIP (CSV first: it has precedence).

    The 2019-2021 ZIPs are flat, the 2022+ ones nest the files in ``AnioYY/``; XML copies are ignored.
    """
    with zipfile.ZipFile(zip_path) as archive:
        members: dict[str, dict[str, str]] = {}
        for name in archive.namelist():
            stem, _, ext = name.rpartition(".")
            if ext.lower() in ("csv", "txt"):
                members.setdefault(stem.lower(), {})[ext.lower()] = name
        for stem in sorted(members):
            frames = []
            if "csv" in members[stem]:
                frames.append(read_csv_wide(archive.read(members[stem]["csv"])))
            if "txt" in members[stem]:
                frames.append(read_txt_wide(archive.read(members[stem]["txt"])))
            yield stem, frames


# ------------------------------------------------------------------------- conversion


def dst_transition_days(dates: pd.Series) -> set[pd.Timestamp]:
    """Local dates whose length is not 24 h (spring forward / fall back)."""
    out = set()
    for day in pd.Series(dates.dropna().unique()):
        day = pd.Timestamp(day)
        start = day.tz_localize(TIMEZONE)
        end = (day + pd.Timedelta(days=1)).tz_localize(TIMEZONE)
        if (end - start) != pd.Timedelta(hours=24):
            out.add(day)
    return out


def wide_to_long(
    wide: pd.DataFrame,
    *,
    data_version: str,
    seen: dict | None = None,
    stats: Stats | None = None,
    magnitudes: dict[int, tuple[str, str]] | None = None,
    source_id: str = SOURCE_ID,
) -> tuple[pa.Table, Stats]:
    """Convert wide frames (CSV first, then TXT) to canonical observations.

    Args:
        wide: one or more concatenated wide frames; rows repeated across formats keep the first occurrence.
        data_version: stamped on every row.
        seen: ``key -> format`` already converted in this run (shared across calls to find duplicates across units).
        stats: counters to update; a fresh one is created otherwise.
        magnitudes: ``code -> (feature_name, unit)``; defaults to the air-quality ``MAGNITUDES`` (the meteorological
            files share the layout and pass their own table and ``source_id``).
        source_id: stamped on every row.

    Returns:
        The Arrow table (``OBSERVATION_SCHEMA``) and the stats.
    """
    stats = stats if stats is not None else Stats()
    seen = seen if seen is not None else {}
    magnitudes = MAGNITUDES if magnitudes is None else magnitudes
    c = stats.counters
    wide = wide.reset_index(drop=True)
    c["wide_rows_read"] += len(wide)

    for col in ("year", "month", "day", "magnitude"):
        wide[col] = pd.to_numeric(wide[col], errors="coerce")
    date = pd.to_datetime({"year": wide["year"], "month": wide["month"], "day": wide["day"]}, errors="coerce")
    bad_date = date.isna()
    c["rows_impossible_date"] += int(bad_date.sum())
    c["slots_impossible_date"] += int(bad_date.sum()) * 24

    known = wide["magnitude"].isin(list(magnitudes)) & ~bad_date
    unknown = ~wide["magnitude"].isin(list(magnitudes)) & ~bad_date
    for code, n in wide.loc[unknown, "magnitude"].value_counts().items():
        stats.unknown_magnitude_slots[str(int(code)) if pd.notna(code) else "nan"] += int(n) * 24

    entity = (
        wide["province"].str.strip()
        + wide["municipality"].str.strip().str.zfill(3)
        + pd.to_numeric(wide["station"], errors="coerce").fillna(-1).astype(int).astype(str).str.zfill(3)
    )
    keys = list(zip(entity, wide["magnitude"], wide["year"], wide["month"], wide["day"], strict=True))
    keep = np.zeros(len(wide), dtype=bool)
    for i, key in enumerate(keys):
        if not known.iat[i]:
            continue
        fmt = wide["fmt"].iat[i]
        prior = seen.get(key)
        if prior is not None:
            # Same format twice is a real duplicate; CSV vs TXT is expected overlap (CSV has precedence).
            c["duplicate_slots_same_format" if prior == fmt else "overlap_slots_cross_format"] += 24
            continue
        seen[key] = fmt
        keep[i] = True
        if fmt == "txt":
            stats.txt_only_slots[f"{int(wide['year'].iat[i])}/{magnitudes[int(wide['magnitude'].iat[i])][0]}"] += 24
    wide, date, entity = wide[keep], date[keep], entity[keep]
    n = len(wide)
    if n == 0:
        return OBSERVATION_SCHEMA.empty_table(), stats

    values = wide[VALUE_COLUMNS].to_numpy(dtype=object).ravel()
    flags = wide[FLAG_COLUMNS].to_numpy(dtype=object).ravel()
    slot = np.tile(np.arange(24), n)
    day_rep = np.repeat(date.to_numpy(), 24)
    local_start = pd.DatetimeIndex(day_rep + slot.astype("timedelta64[h]").astype("timedelta64[ns]"))
    # Fall back: the ambiguous 02:00 wall time is the first occurrence (DST, UTC+2); spring forward: NaT.
    utc = local_start.tz_localize(TIMEZONE, ambiguous=np.ones(len(local_start), dtype=bool), nonexistent="NaT")
    nonexistent = np.asarray(pd.isna(utc))

    value_text = pd.Series(values, dtype=object).str.strip().str.replace(",", ".", regex=False)
    flag_text = pd.Series(flags, dtype=object).str.strip().str.upper()
    flag_text = flag_text.mask(flag_text.eq(""), None)
    empty = value_text.eq("").to_numpy()
    number = pd.to_numeric(value_text, errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(number)
    valid_flag = flag_text.eq(VALID_FLAG).to_numpy()

    if nonexistent.any():
        c["slots_dst_nonexistent"] += int(nonexistent.sum())
        c["slots_dst_nonexistent_not_flagged_invalid"] += int((nonexistent & valid_flag).sum())

    reason = np.full(len(values), None, dtype=object)
    reason[~valid_flag] = "invalid_observation"
    reason[valid_flag & ~finite] = "invalid_observation"
    reason[empty] = "no_observation"
    out_value = np.where(pd.isna(reason), number, np.nan)

    keep_slot = ~nonexistent
    mag = np.repeat(wide["magnitude"].to_numpy(dtype=int), 24)
    names = np.array([magnitudes[int(m)][0] for m in mag], dtype=object)
    units = np.array([magnitudes[int(m)][1] for m in mag], dtype=object)
    wording = np.char.add(
        np.char.add(np.repeat(date.dt.strftime("%Y-%m-%d").to_numpy(dtype=str), 24), " H"),
        np.char.zfill((slot + 1).astype(str), 2),
    )

    n_out = int(keep_slot.sum())
    table = pa.table(
        {
            "domain": pa.array(["air"] * n_out, pa.string()),
            "entity_id": pa.array(np.repeat(entity.to_numpy(dtype=object), 24)[keep_slot], pa.string()),
            "timestamp_utc": pa.array(utc[keep_slot].tz_convert("UTC").to_numpy(), pa.timestamp("us", tz="UTC")),
            "source_timestamp_local": pa.array(wording[keep_slot], pa.string()),
            "timezone": pa.array([TIMEZONE] * n_out, pa.string()),
            "feature_name": pa.array(names[keep_slot], pa.string()),
            "value": pa.array(out_value[keep_slot], pa.float64(), from_pandas=True),
            "unit": pa.array(units[keep_slot], pa.string()),
            "validity_flag": pa.array(flag_text.to_numpy(dtype=object)[keep_slot], pa.string()),
            "missing_reason": pa.array(reason[keep_slot], pa.string()),
            "censoring": pa.nulls(n_out, pa.string()),
            "source_id": pa.array([source_id] * n_out, pa.string()),
            "data_version": pa.array([data_version] * n_out, pa.string()),
            "aggregation_window_start_utc": pa.nulls(n_out, pa.timestamp("us", tz="UTC")),
            "aggregation_window_end_utc": pa.nulls(n_out, pa.timestamp("us", tz="UTC")),
            "n_records": pa.nulls(n_out, pa.int64()),
        },
        schema=OBSERVATION_SCHEMA,
    )

    c["slots_read"] += len(values)
    c["canonical_rows"] += n_out
    c["valid_rows"] += int(np.isfinite(out_value[keep_slot]).sum())
    discarded = keep_slot & ~valid_flag & ~empty & finite
    c["invalid_slots_with_number"] += int((discarded & (number != 0)).sum())
    c["invalid_slots_with_zero"] += int((discarded & (number == 0)).sum())
    c["valid_negative_rows"] += int((out_value[keep_slot] < 0).sum())
    for flag, count in flag_text[keep_slot].value_counts(dropna=False).items():
        stats.by_flag["(empty)" if flag is None or pd.isna(flag) else str(flag)] += int(count)

    # DST evidence: share of invalid slots per hour on transition days.
    transition = dst_transition_days(date)
    if transition:
        invalid = ~wide[FLAG_COLUMNS].eq(VALID_FLAG).to_numpy()
        for day in transition:
            rows = (date == day).to_numpy()
            info = stats.dst_days.setdefault(str(day.date()), {"rows": 0, "invalid_per_slot": [0] * 24})
            info["rows"] += int(rows.sum())
            info["invalid_per_slot"] = [
                a + int(b) for a, b in zip(info["invalid_per_slot"], invalid[rows].sum(axis=0), strict=True)
            ]
    return table, stats
