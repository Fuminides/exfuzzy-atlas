"""Fixed linguistic variables whose terms are named bands, with a documented justification per variable (AT-041d).

The quantile partitions of AT-041c give terms such as ``no2_last IS High`` that start at 28-47 ug/m3: they describe
the training distribution, not the target. Here a variable can instead have one term per *band* of a scheme (the ICA
categories for NO2, or hand-written bands such as Night / Morning / Afternoon / Evening for the hour), so that a rule
reads ``IF no2_last IS Regular AND wind_speed IS Calma THEN ICA = Regular``.

Shape of a term (``trapezoids``): the **core** (membership 1) is exactly the band ``[lower, upper]``, inclusive; outside
the core the membership falls linearly to 0 over the width of the shoulder (same unit as the variable). There is one
shoulder width per *boundary* between two consecutive bands, used by both neighbours: the trapezoid of a band is
``(lower - w_below, lower, upper, upper + w_above)``. The first band starts at the domain minimum and the last ends at
the domain maximum, with no shoulder towards the domain edge (``a == b`` and ``c == d``; the library then gives
membership 1 at that edge). Neighbouring terms overlap over the shoulders: a value just inside one band has a smaller
but non-zero membership in the next. The partition is not a Ruspini partition (memberships do not sum to 1); with
width 0 it is crisp (and on whole numbers a width of 1 is crisp as well). Nothing here estimates a parameter from data.
``configs/ml/madrid_partitions.json`` holds the partitions of the Madrid NO2 task with the rationale and source of every
variable; ``load_partition_file`` reads it and checks that the written parameters are the ones the cores and shoulders
give.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import utils
from pydantic import BaseModel, ConfigDict, model_validator

from atlas.ml.classification import ClassScheme
from atlas.paths import REPO_ROOT


class Band(BaseModel):
    """One term: its name and its core ``[lower, upper]`` (inclusive)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    lower: float
    upper: float


class FixedPartition(BaseModel):
    """Bands of one variable in increasing order, the shoulder width and the domain they cover."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    bands: list[Band]
    shoulder: float | list[float]  # one width for every boundary, or one per boundary (len(bands) - 1)
    domain: tuple[float, float]
    follows_target_scheme: bool = False  # terms must be the classes of the target scheme (checked by the experiment)

    @property
    def boundary_shoulders(self) -> list[float]:
        if isinstance(self.shoulder, list):
            return [float(w) for w in self.shoulder]
        return [float(self.shoulder)] * (len(self.bands) - 1)

    @model_validator(mode="after")
    def _check(self) -> FixedPartition:
        if len(self.bands) < 2:
            raise ValueError("a partition needs at least two bands")
        if isinstance(self.shoulder, list) and len(self.shoulder) != len(self.bands) - 1:
            raise ValueError("one shoulder width per boundary is required")
        if any(w < 0 for w in self.boundary_shoulders):
            raise ValueError("shoulder widths must be >= 0")
        if len({b.name for b in self.bands}) != len(self.bands):
            raise ValueError("band names must be unique")
        lo, hi = self.domain
        if not lo < hi:
            raise ValueError("domain must be increasing")
        if self.bands[0].lower != lo or self.bands[-1].upper != hi:
            raise ValueError("the first band must start at the domain minimum and the last end at its maximum")
        for band in self.bands:
            if band.lower > band.upper:
                raise ValueError(f"band {band.name!r}: lower > upper")
        for left, right in zip(self.bands, self.bands[1:], strict=False):
            if right.lower <= left.upper:
                raise ValueError(f"bands {left.name!r} and {right.name!r} overlap or are not increasing")
        return self


class PartitionConfig(BaseModel):
    """Which inputs get fixed terms. Every other input keeps its quantile terms.

    ``file`` is a partitions file (``configs/ml/madrid_partitions.json``, relative to the repository root) and
    ``use_features`` limits it to some of its fixed variables (None: all of them); ``fixed`` are extra hand-written
    partitions (tests).
    """

    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    use_features: list[str] | None = None
    fixed: list[FixedPartition] = []

    def resolve(self) -> dict[str, FixedPartition]:
        out: dict[str, FixedPartition] = {}
        if self.file:
            path = Path(self.file)
            loaded = load_partition_file(path if path.is_absolute() else REPO_ROOT / path)
            wanted = self.use_features if self.use_features is not None else list(loaded)
            missing = sorted(set(wanted) - set(loaded))
            if missing:
                raise ValueError(f"{self.file}: no fixed partition for {missing}")
            out = {f: loaded[f] for f in wanted}
        for partition in self.fixed:
            if partition.feature in out:
                raise ValueError(f"{partition.feature!r} is defined twice")
            out[partition.feature] = partition
        return out


def load_partition_file(path: Path) -> dict[str, FixedPartition]:
    """The fixed partitions of a partitions file, by feature.

    Entries of ``variables`` have ``features``, ``kind`` (``"fixed"`` or ``"quantile"``), ``rationale`` and, for fixed
    ones, ``domain``, ``shoulders`` (a width, or a list with one width per boundary), ``terms`` (``name``,
    ``core`` = [lower, upper], ``params`` = [a, b, c, d]) and optionally ``follows_target_scheme``. The written
    ``params`` must be those the cores and shoulders give: editing one without the other is refused. ``quantile``
    entries only document the data-driven variables and give no partition.
    """
    document = json.loads(Path(path).read_text())
    out: dict[str, FixedPartition] = {}
    for entry in document["variables"]:
        if entry["kind"] == "quantile":
            continue
        if entry["kind"] != "fixed":
            raise ValueError(f"unknown kind {entry['kind']!r}")
        for feature in entry["features"]:
            partition = FixedPartition(
                feature=feature, shoulder=entry["shoulders"], domain=tuple(entry["domain"]),
                follows_target_scheme=entry.get("follows_target_scheme", False),
                bands=[Band(name=t["name"], lower=t["core"][0], upper=t["core"][1]) for t in entry["terms"]])
            for (name, params), term in zip(trapezoids(partition), entry["terms"], strict=True):
                if [float(p) for p in term["params"]] != params:
                    raise ValueError(f"{path}: {feature}/{name}: written params {term['params']} != computed {params}")
            if feature in out:
                raise ValueError(f"{path}: {feature!r} is defined twice")
            out[feature] = partition
    return out


def scheme_partition(feature: str, scheme: ClassScheme, shoulder: float | None = None,
                     relative_shoulder: float | None = None, domain_upper: float | None = None,
                     domain_lower: float | None = None) -> FixedPartition:
    """One term per class of ``scheme`` (term name = class label, core = the class band).

    ``shoulder`` is one width for every boundary; ``relative_shoulder`` makes the width at each boundary that fraction
    of the boundary value (the upper bound of the class below it), e.g. 0.15 for a 15 % measurement uncertainty.
    ``domain_upper`` is the end of the variable's domain when the last class is open-ended (EAQI ">150");
    ``domain_lower`` the start of the first term's core when values below the first class belong to it
    (``scheme.below_first_as_first``: noise under 0 ug/m3).
    """
    if (shoulder is None) == (relative_shoulder is None):
        raise ValueError("give exactly one of shoulder and relative_shoulder")
    top = scheme.classes[-1].upper
    if top is None:
        if domain_upper is None:
            raise ValueError("the last class is open-ended: give domain_upper")
        top = domain_upper
    bands = [Band(name=c.label, lower=c.lower, upper=top if c.upper is None else c.upper) for c in scheme.classes]
    widths = shoulder if relative_shoulder is None else [relative_shoulder * c.upper for c in scheme.classes[:-1]]
    bottom = scheme.classes[0].lower
    if domain_lower is not None:
        if not scheme.below_first_as_first:
            raise ValueError("domain_lower below the first class needs a scheme with below_first_as_first")
        bands[0] = bands[0].model_copy(update={"lower": domain_lower})
        bottom = domain_lower
    return FixedPartition(feature=feature, bands=bands, shoulder=widths, follows_target_scheme=True,
                          domain=(bottom, top))


def trapezoids(partition: FixedPartition) -> list[tuple[str, list[float]]]:
    """``(term name, [a, b, c, d])`` per band; see the module docstring for the shape."""
    lo, hi = partition.domain
    widths = partition.boundary_shoulders
    out = []
    for i, band in enumerate(partition.bands):
        a, b = (lo, lo) if band.lower <= lo else (band.lower - widths[i - 1], band.lower)
        c, d = (hi, hi) if band.upper >= hi else (band.upper, band.upper + widths[i])
        out.append((band.name, [round(float(v), 9) for v in (a, b, c, d)]))
    return out


def fixed_variable(partition: FixedPartition, unit: str | None = None) -> fs.fuzzyVariable:
    """The ex_fuzzy variable of a fixed partition (type-1 trapezoids, one per band)."""
    sets = [fs.FS(name, params, list(partition.domain)) for name, params in trapezoids(partition)]
    return fs.fuzzyVariable(partition.feature, sets, unit)


def build_variables(
    X_reference: np.ndarray, feature_names: list[str], fixed: dict[str, FixedPartition] | None,
    n_terms: int, units: dict[str, str] | None = None,
) -> list[fs.fuzzyVariable]:
    """One variable per feature: fixed partitions where given, quantile terms (``n_terms``) from ``X_reference`` else.

    The quantile partitions are computed on the non-fixed columns only, so a fixed column may be constant in the
    reference. Names and units are set on every variable.
    """
    fixed = dict(fixed or {})
    unknown = sorted(set(fixed) - set(feature_names))
    if unknown:
        raise ValueError(f"fixed partitions for features that are not inputs: {unknown}")
    units = units or {}
    free = [i for i, n in enumerate(feature_names) if n not in fixed]
    quantile = iter(utils.construct_partitions(np.asarray(X_reference, dtype=float)[:, free], n_partitions=n_terms,
                                               detect_categorical=False)) if free else iter(())
    variables = []
    for name in feature_names:
        variable = fixed_variable(fixed[name]) if name in fixed else next(quantile)
        variable.name = name
        variable.units = units.get(name)
        variables.append(variable)
    return variables
