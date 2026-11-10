"""Pydantic models for the ExFuzzy Atlas interoperability contract.

These models are the normative form of ``CONTRACTS.md``. Changing a field is a contract
change: bump ``SCHEMA_VERSION``, run ``make schemas fixtures`` and add a compatibility test.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.8.0"
PARITY_TOLERANCE = 1e-9


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be in UTC")
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Envelope(_Model):
    """Fields every API payload carries."""

    schema_version: str = SCHEMA_VERSION
    data_version: str
    synthetic: bool = Field(False, description="True for fixtures; the UI must label them as synthetic.")


# --------------------------------------------------------------------------- enums


class Domain(str, Enum):
    AIR = "air"
    WATER = "water"
    MOBILITY = "mobility"


class GeometrySupport(str, Enum):
    """Spatial meaning of a geometry. ``estimated_surface`` is deliberately absent in v0.1."""

    OBSERVED_POINT = "observed_point"
    OBSERVED_POLYGON = "observed_polygon"
    DERIVED_AGGREGATE = "derived_aggregate"


class MissingReason(str, Enum):
    NO_OBSERVATION = "no_observation"  # the source has no record for this entity and time
    INVALID_OBSERVATION = "invalid_observation"  # a record exists but its validity flag rejects it
    CENSORED = "censored"  # beyond a detection limit and not usable as a number
    MISSING_INPUT = "missing_input"  # a model input is unavailable, so inference was not run
    PREDICTION_UNAVAILABLE = "prediction_unavailable"
    NOT_MODELLED = "not_modelled"  # the entity has no model (v0.4): no value is ever produced for it


class Censoring(str, Enum):
    LEFT = "left"  # true value below the reported limit ("<")
    RIGHT = "right"  # true value above the reported limit (">")


class RuleMapMetric(str, Enum):
    FIRING_STRENGTH = "firing_strength"  # one record: degree returned by the model, never a probability
    MEAN_ACTIVATION = "mean_activation"  # mean firing over the n_valid records of a window
    ACTIVATION_FREQUENCY = "activation_frequency"  # share of n_valid records with firing >= tau


class SchemeKind(str, Enum):
    """What a classification scheme is (v0.4); the UI words the classes differently for each."""

    OFFICIAL_INDEX = "official_index"  # bands defined by an official source (e.g. the Spanish ICA)
    PERCENTILE_REFERENCE = "percentile_reference"  # bands relative to a reference distribution (e.g. NYC level)
    ANALYTICAL = "analytical"  # bands chosen by the analysts; no external authority


class InferenceFamily(str, Enum):
    TSK_ZERO_ORDER = "tsk_zero_order"
    MAMDANI = "mamdani"
    WINNING_RULE_CLASSIFIER = "winning_rule_classifier"  # class of the rule with max firing x weight
    # v0.7: class with the largest b_c + sum_r W[r, c] x firing_r (ex_fuzzy inference='mixture'); no rule decides alone
    RULE_MIXTURE_CLASSIFIER = "rule_mixture_classifier"


CLASSIFIER_FAMILIES = (InferenceFamily.WINNING_RULE_CLASSIFIER, InferenceFamily.RULE_MIXTURE_CLASSIFIER)


class TNorm(str, Enum):
    PRODUCT = "product"
    MINIMUM = "minimum"


class RuleMode(str, Enum):
    ADDITIVE = "additive"  # every rule takes part in the inference
    SUFFICIENT = "sufficient"  # only the strongest rule, if it clears the tolerance


class QualityStatus(str, Enum):
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class Quality(_Model):
    status: QualityStatus = QualityStatus.VALID
    warnings: list[str] = []


# ------------------------------------------------------------------------ geometry

Position = tuple[Annotated[float, Field(ge=-180, le=180)], Annotated[float, Field(ge=-90, le=90)]]


class PointGeometry(_Model):
    type: Literal["Point"]
    coordinates: Position


class PolygonGeometry(_Model):
    type: Literal["Polygon"]
    coordinates: list[list[Position]]


class MultiPolygonGeometry(_Model):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[Position]]]


Geometry = Annotated[PointGeometry | PolygonGeometry | MultiPolygonGeometry, Field(discriminator="type")]

_GEOMETRY_TYPES = {
    GeometrySupport.OBSERVED_POINT: {"Point"},
    GeometrySupport.OBSERVED_POLYGON: {"Polygon", "MultiPolygon"},
    GeometrySupport.DERIVED_AGGREGATE: {"Point", "Polygon", "MultiPolygon"},
}


def _check_geometry(geometry: Any, support: GeometrySupport) -> None:
    if geometry is not None and geometry.type not in _GEOMETRY_TYPES[support]:
        raise ValueError(f"geometry {geometry.type} does not match geometry_support={support.value}")


def _check_value_or_reason(value: float | None, reason: MissingReason | None) -> None:
    """A null value needs a reason and a number must not carry one: 0 is never 'missing'."""
    if value is None and reason is None:
        raise ValueError("value is null, so missing_reason is required")
    if value is not None and reason is not None:
        raise ValueError("missing_reason must be null when value is present")
    if value is not None and not math.isfinite(value):
        raise ValueError("value must be finite")


def _check_prediction(value: float | None, label: str | None, reason: MissingReason | None) -> None:
    """A prediction is a number (regression) or a class label (classification), or null with a reason."""
    if label is None:
        _check_value_or_reason(value, reason)
    elif reason is not None:
        raise ValueError("missing_reason must be null when a label is present")


# ------------------------------------------------------------------------ entities


class Attribution(_Model):
    """Credit and licence of a data source (v0.4); the text is what a redistribution must show."""

    text: str
    text_en: str | None = Field(
        None, description="v0.6.1: the same credit in English; the UI shows it when the interface is in English, else "
        "falls back to `text`. The licence and the URL are the same in both languages."
    )
    license: str | None = Field(None, description="Licence name; null when the source declares none (say so in text).")
    url: str | None = None


class EntityProperties(_Model):
    entity_id: str
    domain: Domain
    name: str | None = None
    geometry_support: GeometrySupport
    geometry_source: str = Field(description="URL or source_id of the official geometry.")
    timezone: str = Field(description="IANA zone of the entity, e.g. Europe/Madrid.")
    modelled: bool | None = Field(
        None,
        description="v0.4. False: the entity exists in the geometry file but the model has no data for it, so every "
        "view returns null with missing_reason=not_modelled. Null: not stated (published before v0.4).",
    )
    attributes: dict[str, Any] = {}


class EntityFeature(_Model):
    type: Literal["Feature"]
    id: str
    geometry: Geometry | None = Field(description="Null when the source has no geometry; never fabricated.")
    properties: EntityProperties

    @model_validator(mode="after")
    def _consistent(self) -> EntityFeature:
        if self.id != self.properties.entity_id:
            raise ValueError("Feature.id must equal properties.entity_id")
        _check_geometry(self.geometry, self.properties.geometry_support)
        return self


class EntityCollection(_Envelope):
    type: Literal["FeatureCollection"]
    domain: Domain
    attribution: list[Attribution] = Field([], description="v0.4: credits of the sources behind these entities.")
    features: list[EntityFeature]


# -------------------------------------------------------------------- observations


class ObservationRecord(_Model):
    """One canonical (long-format) observation; ``atlas.contracts.observations`` holds the Arrow form."""

    domain: Domain
    entity_id: str
    timestamp_utc: UtcDatetime
    source_timestamp_local: str | None = None
    timezone: str
    feature_name: str
    value: float | None
    unit: str
    validity_flag: str | None = Field(None, description="Original source code, kept verbatim.")
    missing_reason: MissingReason | None = None
    censoring: Censoring | None = None
    source_id: str
    data_version: str
    aggregation_window_start_utc: UtcDatetime | None = None
    aggregation_window_end_utc: UtcDatetime | None = None
    n_records: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> ObservationRecord:
        _check_value_or_reason(self.value, self.missing_reason)
        start, end = self.aggregation_window_start_utc, self.aggregation_window_end_utc
        if (start is None) != (end is None):
            raise ValueError("aggregation window needs both start and end")
        if start is not None and end <= start:
            raise ValueError("aggregation window end must be after start")
        return self


# --------------------------------------------------------------------- predictions


class RuleFiring(_Model):
    rule_id: str
    firing_strength: UnitInterval


class PredictionExplanation(_Model):
    rule_firings: list[RuleFiring]


class PredictionRecord(_Envelope):
    domain: Domain
    task_id: str
    entity_id: str
    issued_at_utc: UtcDatetime
    valid_at_utc: UtcDatetime
    target: str
    unit: str
    prediction: float | None
    prediction_label: str | None = Field(None, description="Predicted class (classification tasks).")
    observed: float | None = Field(
        None, description="Filled only when observed; says nothing about availability at issue time."
    )
    model_id: str
    missing_reason: MissingReason | None = None
    quality: Quality = Quality()
    explanation: PredictionExplanation | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PredictionRecord:
        if self.valid_at_utc < self.issued_at_utc:
            raise ValueError("valid_at_utc must not precede issued_at_utc")
        _check_prediction(self.prediction, self.prediction_label, self.missing_reason)
        return self


class SeriesPoint(_Model):
    issued_at_utc: UtcDatetime
    valid_at_utc: UtcDatetime
    observed: float | None
    prediction: float | None
    observed_label: str | None = Field(None, description="Class of the observed value (classification tasks).")
    predicted_label: str | None = Field(None, description="Predicted class (classification tasks).")
    missing_reason: MissingReason | None = Field(None, description="Why the prediction is null, if it is.")
    quality: Quality = Quality()

    @model_validator(mode="after")
    def _consistent(self) -> SeriesPoint:
        _check_prediction(self.prediction, self.predicted_label, self.missing_reason)
        return self


class SeriesResponse(_Envelope):
    task_id: str
    entity_id: str
    model_id: str
    target: str
    unit: str
    horizon_hours: int = Field(ge=0, description="0 for same-time inference (no forecast).")
    points: list[SeriesPoint]
    next_cursor: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> SeriesResponse:
        horizon = timedelta(hours=self.horizon_hours)
        for point in self.points:
            if point.valid_at_utc - point.issued_at_utc != horizon:
                raise ValueError("every point must have valid_at - issued_at == horizon_hours")
        return self


# --------------------------------------------------------------------------- rules


class LinguisticTerm(_Model):
    name: str
    label: str | None = Field(
        None, description="v0.5.1: display name of the term, e.g. '≤ límite de detección' for '<=L'; the UI shows it "
        "instead of `name`, which stays the key that rules refer to."
    )
    label_en: str | None = Field(
        None, description="v0.6: English display name of the term, e.g. '≤ detection limit'; the UI shows it when "
        "the interface is in English, else falls back to `label` (then `name`)."
    )
    membership_type: Literal["trapezoidal", "triangular", "gaussian"]
    params: list[float] = Field(
        description="ex_fuzzy semantics: trapezoidal and triangular are both [a, b, c, d] (trapezoid form); "
        "gaussian is [mean, std] with mu = exp(-((x - mean) / std) ** 2), no 1/2 factor."
    )


class LinguisticVariable(_Model):
    feature: str
    unit: str | None = None
    label: str | None = Field(
        None, description="v0.5: display name of the input, e.g. 'NO₂ hace 3 h'; the UI shows it instead of `feature`."
    )
    description: str | None = Field(
        None, description="v0.5: what the input is and when it is known relative to the issue time."
    )
    label_en: str | None = Field(
        None, description="v0.6: English display name of the input, e.g. 'NO₂ 4 h ago'; the UI shows it when the "
        "interface is in English, else falls back to `label` (then `feature`)."
    )
    description_en: str | None = Field(
        None, description="v0.6: English version of `description`; the UI shows it when the interface is in English, "
        "else falls back to `description`."
    )
    domain: tuple[float, float] | None = Field(
        None, description="Universe of discourse. ex_fuzzy clips inputs to it: values outside get the edge membership."
    )
    terms: list[LinguisticTerm] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> LinguisticVariable:
        if self.domain is not None and not self.domain[0] < self.domain[1]:
            raise ValueError("domain must be [min, max] with min < max")
        return self


class InferenceSpec(_Model):
    family: InferenceFamily
    tnorm: TNorm
    rule_mode: RuleMode | None = Field(None, description="TSK/Mamdani only: how many rules take part.")
    tolerance: float = Field(0.0, ge=0)
    fallback: Literal["train_target_mean", "unknown", "largest_bias"] | None = Field(
        description="Output when no rule fires. 'largest_bias' (v0.7, rule mixture without allow_unknown): the class "
        "of the largest class_bias."
    )
    rule_weighting: Literal["dominance_score", "weight", "none"] | None = Field(
        None, description="Winning-rule classifier only: association degree = firing x this rule weight (ex_fuzzy "
        "ds_mode)."
    )
    allow_unknown: bool | None = Field(None, description="Classifier only: no class when no rule fires.")
    mixture_weights: Literal["non_negative", "unconstrained"] | None = Field(
        None, description="v0.7, rule mixture only: how the class weights were fitted. Both describe the same family "
        "of decision functions (adding a constant to all the class weights of one rule changes no prediction); only "
        "the L2 penalty differs. Compare rules with RuleDefinition.class_weights_centred."
    )
    mixture_C: float | None = Field(
        None, gt=0, description="v0.7, rule mixture only: inverse strength of the L2 penalty ||W||^2 / 2 of the "
        "multinomial logistic fit of the weights on the firing strengths of the fitting rows (scikit-learn's C)."
    )
    exfuzzy_version: str

    @model_validator(mode="after")
    def _consistent(self) -> InferenceSpec:
        mixture = self.family == InferenceFamily.RULE_MIXTURE_CLASSIFIER
        if (self.mixture_weights is not None or self.mixture_C is not None) and not mixture:
            raise ValueError("mixture_weights and mixture_C are for the rule mixture only")
        if self.family == InferenceFamily.WINNING_RULE_CLASSIFIER:
            if self.rule_weighting is None or self.allow_unknown is None:
                raise ValueError("a classifier needs rule_weighting and allow_unknown")
        elif mixture:
            if self.allow_unknown is None or self.mixture_weights is None or self.mixture_C is None:
                raise ValueError("a rule mixture needs allow_unknown, mixture_weights and mixture_C")
            if self.rule_weighting is not None or self.rule_mode is not None:
                raise ValueError("a rule mixture has no rule_weighting and no rule_mode")
            if self.fallback != ("unknown" if self.allow_unknown else "largest_bias"):
                raise ValueError("a rule mixture falls back to 'unknown' with allow_unknown, else to 'largest_bias'")
        elif self.rule_mode is None or self.rule_weighting is not None:
            raise ValueError("TSK/Mamdani need rule_mode and no rule_weighting")
        return self


ConditionOperator = Literal["is", "at_least", "at_most", "any_of"]


def _check_condition(operator: str, term: str, terms: list[str]) -> list[str]:
    """Shared by ``Antecedent`` and ``AntecedentTrace``: the ``terms`` of a condition, filled in for ``is``."""
    if operator == "is":
        if terms and terms != [term]:
            raise ValueError("an 'is' condition covers exactly its term")
        return [term]
    if len(terms) < 2 or len(set(terms)) != len(terms):
        raise ValueError(f"'{operator}' covers at least two distinct terms, listed once")
    if operator == "at_least" and terms[0] != term:
        raise ValueError("'at_least' names the lowest term it covers")
    if operator == "at_most" and terms[-1] != term:
        raise ValueError("'at_most' names the highest term it covers")
    return terms


class Antecedent(_Model):
    feature: str
    term: str = Field(
        description="The term the condition refers to: for `is` the term itself, for `at_least` / `at_most` the "
        "threshold term (the lowest / the highest term covered), for `any_of` the compound's internal name (the key "
        "of `label`), which is not a term of the variable."
    )
    modifier: float | None = Field(None, description="Hedge exponent applied to the membership, if any.")
    operator: ConditionOperator = Field(
        "is", description="v0.8: `is` one term; `at_least` / `at_most` a term of the ordered terms of a quantity input "
        "('x is at least Fair'); `any_of` a named compound of terms (a stretch of the clock or the week). The "
        "membership of the last three is the bounded sum min(1, sum of the memberships of `terms`) (ex_fuzzy)."
    )
    terms: list[str] = Field(
        [], description="v0.8: names of the base terms of the variable that the condition covers, in the variable's "
        "order (low to high). A compound may cover non-adjacent terms: the first and the last term of a clock are the "
        "two ends of one stretch of the day that wraps midnight. `[term]` for `is`; filled in when absent."
    )
    label: str | None = Field(
        None, description="v0.8, `any_of` only: Spanish display name of the compound, e.g. 'Noche larga', from an "
        "Atlas config keyed by `term` (configs/compound_terms.json); display only, so names can change without "
        "refitting."
    )
    label_en: str | None = Field(
        None, description="v0.8, `any_of` only: English display name of the compound, e.g. 'Long night'."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Antecedent:
        self.terms = _check_condition(self.operator, self.term, self.terms)
        if (self.label is not None or self.label_en is not None) and self.operator != "any_of":
            raise ValueError("label and label_en are for compound ('any_of') conditions only")
        return self


class Consequent(_Model):
    type: Literal["crisp", "fuzzy", "class"]
    value: float | None = None
    term: str | None = Field(None, description="Output term (fuzzy) or class label (class).")
    unit: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Consequent:
        if self.type == "crisp" and self.value is None:
            raise ValueError("a crisp consequent needs value")
        if self.type in ("fuzzy", "class") and self.term is None:
            raise ValueError(f"a {self.type} consequent needs term")
        return self


class TargetClass(_Model):
    label: str
    display_label: str | None = Field(
        None, description="v0.5.1: name shown in the UI language when the official `label` is in another one, e.g. "
        "EAQI 'Good' -> 'Buena'. `label` stays the key and the official name."
    )
    display_label_en: str | None = Field(
        None, description="v0.6: English display name of the class, e.g. ICA 'Buena' -> 'Good' (EAQI: its own "
        "official name); the UI shows it when the interface is in English, else falls back to `display_label` "
        "(then `label`)."
    )
    lower: float | None = Field(description="Lower bound in the scheme unit; null = unbounded.")
    upper: float | None = Field(description="Upper bound in the scheme unit; null = unbounded.")
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$", description="Official colour, if any.")
    description: str | None = None
    description_en: str | None = Field(
        None, description="v0.6: English version of `description`; the UI shows it when the interface is in English, "
        "else falls back to `description`."
    )
    merged_from: list[str] = Field(
        [], description="v0.4: labels of the official classes this one groups (e.g. ICA 'Desfavorable o peor')."
    )


class TargetScheme(_Model):
    """Ordered categories of a classification target, taken from a cited source (e.g. an official index)."""

    name: str
    name_en: str | None = Field(
        None, description="v0.6: English display name of the scheme; the UI shows it when the interface is in "
        "English, else falls back to `name`."
    )
    short_name: str | None = Field(None, description="v0.4: compact name for legends, e.g. 'ICA'.")
    short_name_en: str | None = Field(
        None, description="v0.6: English compact name, e.g. 'Relative level' for 'Nivel relativo'; the UI shows it "
        "when the interface is in English, else falls back to `short_name`."
    )
    kind: SchemeKind | None = Field(None, description="v0.4: official index, percentile reference or analytical.")
    source_url: str
    unit: str
    boundary: Literal["lower_inclusive", "upper_inclusive"] = Field(
        "lower_inclusive", description="Which bound a value exactly on a boundary belongs to."
    )
    classes: list[TargetClass] = Field(min_length=2)

    @model_validator(mode="after")
    def _consistent(self) -> TargetScheme:
        labels = [c.label for c in self.classes]
        if len(labels) != len(set(labels)):
            raise ValueError("class labels must be unique")
        for c in self.classes:
            if c.lower is not None and c.upper is not None and not c.lower < c.upper:
                raise ValueError(f"{c.label}: lower must be < upper")
        for prev, nxt in zip(self.classes, self.classes[1:], strict=False):
            if prev.upper is None or nxt.lower is None or prev.upper != nxt.lower:
                raise ValueError("classes must be ordered and contiguous (upper of one == lower of the next)")
        return self


class RuleDefinition(_Model):
    rule_id: str = Field(description="Stable within one model_id only; R07 of another model is unrelated.")
    position: int = Field(ge=0, description="Index in the model's rule base.")
    antecedents: list[Antecedent] = Field(min_length=1)
    consequent: Consequent = Field(
        description="What the rule concludes. Rule mixture (v0.7): the class the genetic search attached to the rule, "
        "used by the search and its pruning only; it does not enter the prediction (class_weights do), so it must not "
        "be shown as the rule's conclusion."
    )
    text: str
    duplicate_of: str | None = Field(
        None, description="rule_id of the first rule with identical antecedents; such rules always fire together."
    )
    weight: float | None = Field(
        None, ge=0, description="Winning-rule classifier: weight multiplying the firing in the association degree."
    )
    class_weights: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture only: W[r, c] for every class of target_scheme, as fitted. The rule adds "
        "W[r, c] x firing to the score of class c. Signed when mixture_weights is 'unconstrained'. A weight is a "
        "coefficient of a fitted linear model on firing strengths: not a probability, a confidence or a risk."
    )
    class_weights_centred: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture only: class_weights minus their mean over the classes. Adding a "
        "constant to all the weights of one rule changes no prediction, so this is the form to read and to compare "
        "between non-negative and unconstrained fits: a positive value means the rule supports that class (raises "
        "its score relative to the other classes), a negative one that it suppresses it (lowers it relative to the "
        "others). Suppression is not 'evidence against' the class, and neither is a probability."
    )
    strongest_class: str | None = Field(
        None, description="v0.7, rule mixture only: the class with the largest weight (first in scheme order on "
        "ties); null when all its weights are equal (a duplicate rule, whose weights are all zero): such a rule "
        "changes no prediction."
    )
    metrics: dict[str, float] = Field({}, description="Support, coverage, ... Never probabilities.")


class ModelRules(_Envelope):
    model_id: str
    task_id: str
    domain: Domain
    inference: InferenceSpec
    target_scheme: TargetScheme | None = Field(None, description="Required for classifiers: the class labels.")
    variables: list[LinguisticVariable]
    rules: list[RuleDefinition]
    class_bias: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture only: b_c for every class of target_scheme (centred to mean 0). The "
        "score of class c is b_c + sum over the rules of class_weights[c] x firing; it is the score of a row that "
        "fires no rule."
    )

    @model_validator(mode="after")
    def _consistent(self) -> ModelRules:
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique within a model")
        for i, rule in enumerate(self.rules):
            if rule.duplicate_of is not None and rule.duplicate_of not in ids[:i]:
                raise ValueError(f"{rule.rule_id}: duplicate_of must name an earlier rule")
        order = {var.feature: [term.name for term in var.terms] for var in self.variables}
        for rule in self.rules:
            for ant in rule.antecedents:
                names = order.get(ant.feature, [])
                if ant.operator == "any_of":
                    if ant.term in names or any(t not in names for t in ant.terms):
                        raise ValueError(f"{rule.rule_id}: compound {ant.feature}={ant.term} must have its own name "
                                         "and cover terms of the variable")
                elif ant.term not in names:
                    raise ValueError(f"{rule.rule_id}: unknown term {ant.feature}={ant.term}")
                elif ant.operator != "is":  # a run of consecutive terms, from the threshold to the end of the scale
                    at = [names.index(t) for t in ant.terms]
                    expected = (list(range(at[0], len(names))) if ant.operator == "at_least"
                                else list(range(0, at[-1] + 1)))
                    if at != expected:
                        raise ValueError(f"{rule.rule_id}: {ant.feature} {ant.operator} {ant.term} must cover "
                                         "the terms from the threshold to that end of the scale")
        family = self.inference.family
        mixture = family == InferenceFamily.RULE_MIXTURE_CLASSIFIER
        if not mixture and (self.class_bias is not None or any(
                r.class_weights is not None or r.class_weights_centred is not None or r.strongest_class is not None
                for r in self.rules)):
            raise ValueError("class_bias, class_weights, class_weights_centred and strongest_class are for the rule "
                             "mixture only")
        if family in CLASSIFIER_FAMILIES:
            if self.target_scheme is None:
                raise ValueError("a classifier needs target_scheme")
            labels = {c.label for c in self.target_scheme.classes}
            for rule in self.rules:
                if rule.consequent.type != "class" or rule.consequent.term not in labels:
                    raise ValueError(f"{rule.rule_id}: consequent must be a class of target_scheme")
                if mixture:
                    if rule.weight is not None:
                        raise ValueError(f"{rule.rule_id}: a mixture rule has class_weights, not weight")
                elif rule.weight is None:
                    raise ValueError(f"{rule.rule_id}: a classifier rule needs weight")
        if mixture:
            self._check_mixture()
        return self

    def _check_mixture(self) -> None:
        """Weights for exactly the scheme classes, centred form, strongest class, signs and duplicates."""
        order = [c.label for c in self.target_scheme.classes]
        if self.class_bias is None or list(self.class_bias) != order:
            raise ValueError("a rule mixture needs class_bias with the target_scheme classes, in scheme order")
        non_negative = self.inference.mixture_weights == "non_negative"
        for rule in self.rules:
            weights, centred = rule.class_weights, rule.class_weights_centred
            if weights is None or list(weights) != order or centred is None or list(centred) != order:
                raise ValueError(f"{rule.rule_id}: class_weights and class_weights_centred need every scheme class, "
                                 "in scheme order")
            values = list(weights.values())
            if not all(math.isfinite(v) for v in [*values, *centred.values()]):
                raise ValueError(f"{rule.rule_id}: weights must be finite")
            if non_negative and min(values) < 0:
                raise ValueError(f"{rule.rule_id}: non-negative mixture weights cannot be negative")
            mean = sum(values) / len(values)
            if any(abs(centred[c] - (weights[c] - mean)) > PARITY_TOLERANCE for c in order):
                raise ValueError(f"{rule.rule_id}: class_weights_centred != class_weights - their mean")
            if rule.duplicate_of is not None and any(values):
                raise ValueError(f"{rule.rule_id}: a duplicate rule carries all-zero weights (the first one has them)")
            expected = None if max(values) == min(values) else order[values.index(max(values))]
            if rule.strongest_class != expected:
                raise ValueError(f"{rule.rule_id}: strongest_class must be the first class of largest weight, or "
                                 "null when all weights are equal")


# ------------------------------------------------------------------------ rule map


class RuleMapProperties(_Model):
    entity_id: str
    rule_id: str
    metric: RuleMapMetric
    value: UnitInterval | None
    n_valid: int = Field(ge=0, description="Records the value is computed from (the denominator).")
    time_from_utc: UtcDatetime | None
    time_to_utc: UtcDatetime | None
    issued_at_utc: UtcDatetime | None = None
    valid_at_utc: UtcDatetime | None = None
    tau: UnitInterval | None = None
    model_id: str
    data_version: str
    geometry_support: GeometrySupport
    missing_reason: MissingReason | None = None
    quality: Quality = Quality()

    @model_validator(mode="after")
    def _consistent(self) -> RuleMapProperties:
        _check_value_or_reason(self.value, self.missing_reason)
        if self.value is not None and self.n_valid < 1:
            raise ValueError("a value needs n_valid >= 1")
        if self.metric == RuleMapMetric.FIRING_STRENGTH:
            if self.n_valid > 1:
                raise ValueError("firing_strength is a single-record value; aggregate with another metric")
            if self.issued_at_utc is None:
                raise ValueError("firing_strength needs issued_at_utc")
        if (self.metric == RuleMapMetric.ACTIVATION_FREQUENCY) != (self.tau is not None):
            raise ValueError("tau is required for activation_frequency and only for it")
        if self.tau is not None and self.tau <= 0:
            raise ValueError("tau must be > 0")
        if self.time_from_utc and self.time_to_utc and self.time_to_utc < self.time_from_utc:
            raise ValueError("time_to_utc must not precede time_from_utc")
        return self


class RuleMapFeature(_Model):
    type: Literal["Feature"]
    id: str
    geometry: Geometry | None
    properties: RuleMapProperties

    @model_validator(mode="after")
    def _consistent(self) -> RuleMapFeature:
        if self.id != self.properties.entity_id:
            raise ValueError("Feature.id must equal properties.entity_id")
        _check_geometry(self.geometry, self.properties.geometry_support)
        return self


class RuleMapResponse(_Envelope):
    type: Literal["FeatureCollection"]
    model_id: str
    rule_id: str
    metric: RuleMapMetric
    tau: UnitInterval | None = None
    time_from_utc: UtcDatetime | None
    time_to_utc: UtcDatetime | None
    features: list[RuleMapFeature]

    @model_validator(mode="after")
    def _consistent(self) -> RuleMapResponse:
        seen = set()
        for feature in self.features:
            p = feature.properties
            if (p.model_id, p.rule_id, p.metric, p.data_version, p.tau) != (
                self.model_id, self.rule_id, self.metric, self.data_version, self.tau
            ):
                raise ValueError(f"feature {feature.id} disagrees with the collection metadata")
            if feature.id in seen:
                raise ValueError(f"duplicate entity {feature.id}")
            seen.add(feature.id)
        return self


# ---------------------------------------------------------------------- rule trace


class FeatureValue(_Model):
    feature: str
    value: float | None
    unit: str | None = None
    observed_at_utc: UtcDatetime | None = Field(None, description="Time of the source observation used.")
    source_id: str | None = None
    missing_reason: MissingReason | None = None

    @model_validator(mode="after")
    def _consistent(self) -> FeatureValue:
        _check_value_or_reason(self.value, self.missing_reason)
        return self


class AntecedentTrace(_Model):
    feature: str
    term: str = Field(description="As `Antecedent.term` (v0.8: for a compound, its internal name).")
    operator: ConditionOperator = Field(
        "is", description="v0.8: as `Antecedent.operator`. For `at_least`, `at_most` and `any_of`, `membership` is "
        "the bounded sum of the memberships of `terms` that ex_fuzzy computes."
    )
    terms: list[str] = Field([], description="v0.8: as `Antecedent.terms`; `[term]` for `is`, filled in when absent.")
    membership: UnitInterval = Field(description="Membership of the input value, as computed by ex_fuzzy.")
    modifier: float | None = None
    effective_membership: UnitInterval = Field(description="membership ** modifier; equals membership without one.")

    @model_validator(mode="after")
    def _consistent(self) -> AntecedentTrace:
        self.terms = _check_condition(self.operator, self.term, self.terms)
        return self


class RuleTraceEntry(_Model):
    rule_id: str
    antecedents: list[AntecedentTrace] = Field(min_length=1)
    firing_strength: UnitInterval = Field(description="T-norm of the effective memberships.")
    effective_firing: UnitInterval = Field(description="Firing after rule_mode; used by the inference.")
    weight: float | None = Field(
        None, ge=0, description="Winning-rule classifier: the rule weight in the association degree."
    )
    association_degree: float | None = Field(
        None, ge=0, description="Winning-rule classifier: firing x weight; the rule with the largest one decides the "
        "class."
    )
    class_weights: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture: the rule's class weights W[r, c] (as in rules.json)."
    )
    class_contributions: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture: W[r, c] x firing_strength for every class, what this rule adds to each "
        "class score (ex_fuzzy mixture_contributions). Not a probability, a share of evidence or a cause."
    )
    class_contributions_centred: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture: class_weights_centred[c] x firing_strength. They differ from "
        "class_contributions by the same amount for every class, so they change no comparison between classes: "
        "positive = the rule supports the class here, negative = it suppresses it, relative to the other classes."
    )


class TracePrediction(_Model):
    value: float | None
    label: str | None = Field(None, description="Predicted class (classifier).")
    winning_rule_id: str | None = Field(
        None, description="Winning-rule classifier: the rule that decided the class. Always null for the rule mixture, "
        "where no single rule decides."
    )
    unit: str
    fallback_used: bool = Field(description="True when no rule fired and the model returned its fallback.")
    missing_reason: MissingReason | None = None
    class_scores: dict[str, float] | None = Field(
        None, description="v0.7, rule mixture: b_c + sum of the rules' class_contributions, per class (ex_fuzzy "
        "mixture_scores); the predicted class is the first of largest score. Scores of a fitted linear model: not "
        "probabilities (no softmax is served)."
    )
    class_bias: dict[str, float] | None = Field(None, description="v0.7, rule mixture: b_c (as in rules.json).")
    top_rule_id: str | None = Field(
        None, description="v0.7, rule mixture: the rule with the largest positive centred contribution to the "
        "predicted class (first in rule order on ties): the rule that supports this prediction the most. It did not "
        "decide it alone. Null without a label or when no rule supports the predicted class."
    )
    top_rule_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture: the top rule's centred contribution to the predicted class over the sum "
        "of the positive centred contributions to it (the bias is not counted)."
    )

    @model_validator(mode="after")
    def _consistent(self) -> TracePrediction:
        _check_prediction(self.value, self.label, self.missing_reason)
        if self.class_scores is None:  # winning rule: one rule decides, so a label always names it
            if (self.label is None) != (self.winning_rule_id is None):
                raise ValueError("label and winning_rule_id go together")
            if self.class_bias is not None or self.top_rule_id is not None or self.top_rule_share is not None:
                raise ValueError("class_bias and the top rule come with class_scores (rule mixture)")
        else:
            if self.winning_rule_id is not None:
                raise ValueError("a rule mixture has no winning_rule_id: no single rule decides")
            if self.class_bias is None or list(self.class_bias) != list(self.class_scores):
                raise ValueError("class_scores and class_bias name the same classes")
            if (self.top_rule_id is None) != (self.top_rule_share is None):
                raise ValueError("top_rule_id and top_rule_share go together")
            if self.top_rule_id is not None and self.label is None:
                raise ValueError("top_rule_id needs a predicted class")
        return self


_TNORMS = {TNorm.PRODUCT: math.prod, TNorm.MINIMUM: min}


def top_contributor(values: Sequence[float]) -> int | None:
    """Position of the largest positive value, the first on exact ties (numpy ``argmax``); None if none is positive.

    v0.7, the rule mixture: applied to the centred contributions of the rules to the predicted class, it gives the
    ``top_rule_id`` of a trace, of ``GET /predictions`` and of ``/importance`` (one definition everywhere)."""
    best = max(values, default=0.0)
    return None if best <= 0 else list(values).index(best)


class RuleTrace(_Envelope):
    model_id: str
    task_id: str
    entity_id: str
    issued_at_utc: UtcDatetime
    valid_at_utc: UtcDatetime
    inference: InferenceSpec
    feature_values: list[FeatureValue]
    rules: list[RuleTraceEntry]
    prediction: TracePrediction
    observation_ids: list[str] = []
    observed: float | None = Field(
        None, description="v0.4: target value observed at valid_at_utc, when known; not available at issue time."
    )
    observed_label: str | None = Field(None, description="v0.4: class of the observed value (classification tasks).")
    quality: Quality = Quality()

    @model_validator(mode="after")
    def _consistent(self) -> RuleTrace:
        if self.valid_at_utc < self.issued_at_utc:
            raise ValueError("valid_at_utc must not precede issued_at_utc")
        for fv in self.feature_values:
            if fv.observed_at_utc is not None and fv.observed_at_utc > self.issued_at_utc:
                raise ValueError(f"{fv.feature} was observed after issued_at_utc (future information)")
        tnorm = _TNORMS[self.inference.tnorm]
        for entry in self.rules:
            for ant in entry.antecedents:
                expected = ant.membership if ant.modifier is None else ant.membership**ant.modifier
                if abs(expected - ant.effective_membership) > PARITY_TOLERANCE:
                    raise ValueError(f"{entry.rule_id}: effective_membership != membership ** modifier")
            firing = tnorm([ant.effective_membership for ant in entry.antecedents])
            if abs(firing - entry.firing_strength) > PARITY_TOLERANCE:
                raise ValueError(f"{entry.rule_id}: firing_strength != {self.inference.tnorm.value} t-norm")
            if (
                self.inference.rule_mode == RuleMode.ADDITIVE
                and abs(entry.effective_firing - entry.firing_strength) > PARITY_TOLERANCE
            ):
                raise ValueError(f"{entry.rule_id}: additive mode needs effective_firing == firing_strength")
        if self.inference.family == InferenceFamily.WINNING_RULE_CLASSIFIER:
            self._check_winning_rule()
        elif self.inference.family == InferenceFamily.RULE_MIXTURE_CLASSIFIER:
            self._check_mixture()
        elif self.prediction.class_scores is not None or any(
                e.class_weights is not None or e.class_contributions is not None for e in self.rules):
            raise ValueError("class weights, contributions and scores are for the rule mixture only")
        return self

    def _check_mixture(self) -> None:
        """contributions = weight x firing, scores = bias + sum, label = first argmax, top rule (v0.7)."""
        p = self.prediction
        for entry in self.rules:
            if entry.weight is not None or entry.association_degree is not None:
                raise ValueError(f"{entry.rule_id}: a mixture trace has no weight or association_degree")
        if not self.rules:  # no inference (missing input, not modelled): nothing to check
            if p.class_scores is not None or p.label is not None:
                raise ValueError("a mixture trace without rules has no scores and no class")
            return
        if p.class_scores is None:
            raise ValueError("a mixture trace with rules needs class_scores")
        order = list(p.class_scores)
        rebuilt = dict(p.class_bias)
        centred_sum = dict.fromkeys(order, 0.0)
        for entry in self.rules:
            w, raw, centred = entry.class_weights, entry.class_contributions, entry.class_contributions_centred
            if any(d is None or list(d) != order for d in (w, raw, centred)):
                raise ValueError(f"{entry.rule_id}: class weights and contributions need every class, in order")
            mean = sum(w.values()) / len(order)
            for c in order:
                if abs(raw[c] - w[c] * entry.firing_strength) > PARITY_TOLERANCE:
                    raise ValueError(f"{entry.rule_id}: class_contributions != class_weights x firing_strength")
                if abs(centred[c] - (w[c] - mean) * entry.firing_strength) > PARITY_TOLERANCE:
                    raise ValueError(f"{entry.rule_id}: class_contributions_centred != centred weights x firing")
                rebuilt[c] += raw[c]
                centred_sum[c] += centred[c]
        if any(abs(rebuilt[c] - p.class_scores[c]) > PARITY_TOLERANCE for c in order):
            raise ValueError("class_scores != class_bias + the sum of the class_contributions")
        fired = any(e.firing_strength > 0 for e in self.rules)
        if p.fallback_used == fired:
            raise ValueError("fallback_used is set exactly when no rule fires")
        if p.label is None:
            return
        if not fired and self.inference.allow_unknown:
            raise ValueError("with allow_unknown a row that fires no rule has no class")
        scores = list(p.class_scores.values())
        if p.label != order[scores.index(max(scores))]:
            raise ValueError("label must be the first class of largest class_scores")
        support = [e.class_contributions_centred[p.label] for e in self.rules]
        top = top_contributor(support)
        if p.top_rule_id != (None if top is None else self.rules[top].rule_id):
            raise ValueError("top_rule_id must be the first rule of largest positive centred contribution to the label")
        if top is not None:
            share = support[top] / sum(v for v in support if v > 0)
            if abs(share - p.top_rule_share) > PARITY_TOLERANCE:
                raise ValueError("top_rule_share != top centred contribution / sum of the positive ones")

    def _check_winning_rule(self) -> None:
        """association == firing x weight, and the predicted class comes from the argmax rule."""
        for entry in self.rules:
            if entry.weight is None or entry.association_degree is None:
                raise ValueError(f"{entry.rule_id}: a classifier trace needs weight and association_degree")
            weight = 1.0 if self.inference.rule_weighting == "none" else entry.weight
            if abs(entry.firing_strength * weight - entry.association_degree) > PARITY_TOLERANCE:
                raise ValueError(f"{entry.rule_id}: association_degree != firing_strength x weight")
        if self.prediction.label is not None:
            best = max(self.rules, key=lambda e: e.association_degree, default=None)  # first max, as numpy argmax
            if best is None or best.association_degree <= 0 or best.rule_id != self.prediction.winning_rule_id:
                raise ValueError("winning_rule_id must be the rule with the largest positive association_degree")


# ---------------------------------------------------------------- data provenance


class SourceFile(_Model):
    path: str = Field(description="Relative to the source's raw directory.")
    sha256: Sha256
    bytes: int = Field(ge=0)
    url: str | None = None


class SourceManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    source_id: str
    domain: Domain
    title: str
    landing_url: str
    license: str
    attribution: str
    downloaded_at_utc: UtcDatetime
    period_start: date | None = None
    period_end: date | None = None
    files: list[SourceFile]
    notes: list[str] = []


class QualityReport(_Model):
    """Audit table required for every source (DATA_SOURCES.md)."""

    schema_version: str = SCHEMA_VERSION
    source_id: str
    source_url: str
    downloaded_at_utc: UtcDatetime
    period_start: date | None
    period_end: date | None
    license: str
    input_sha256: dict[str, Sha256]
    raw_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    uniqueness_key: list[str]
    missing_by_column: dict[str, int]
    invalid_codes: dict[str, int] = {}
    outliers_flagged: int = Field(0, ge=0)
    date_range_utc: tuple[UtcDatetime, UtcDatetime] | None
    geographic_coverage: dict[str, Any]
    sampling_frequency: str
    value_units: dict[str, str]
    known_limitations: list[str]

    @model_validator(mode="after")
    def _consistent(self) -> QualityReport:
        if self.valid_rows > self.raw_rows:
            raise ValueError("valid_rows cannot exceed raw_rows")
        return self


# ------------------------------------------------------------------- ML artifacts


class SplitSpec(_Model):
    """Chronological split. Periods are half-open [from, to) and must not overlap."""

    train_from_utc: UtcDatetime
    train_to_utc: UtcDatetime
    validation_from_utc: UtcDatetime | None = None
    validation_to_utc: UtcDatetime | None = None
    test_from_utc: UtcDatetime
    test_to_utc: UtcDatetime
    embargo_hours: int = Field(ge=0, description="Gap between consecutive periods, at least the horizon.")

    @model_validator(mode="after")
    def _consistent(self) -> SplitSpec:
        periods = [(self.train_from_utc, self.train_to_utc)]
        if (self.validation_from_utc is None) != (self.validation_to_utc is None):
            raise ValueError("validation period needs both ends")
        if self.validation_from_utc is not None:
            periods.append((self.validation_from_utc, self.validation_to_utc))
        periods.append((self.test_from_utc, self.test_to_utc))
        gap = timedelta(hours=self.embargo_hours)
        for start, end in periods:
            if end <= start:
                raise ValueError("every period must end after it starts")
        for (_, prev_end), (next_start, _) in zip(periods, periods[1:], strict=False):
            if next_start < prev_end + gap:
                raise ValueError("periods must be chronological and separated by embargo_hours")
        return self


class RunManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    model_id: str
    task_id: str
    domain: Domain
    created_at_utc: UtcDatetime
    git_commit: str | None
    git_dirty: bool
    exfuzzy_version: str
    python_version: str
    seed: int
    split: SplitSpec
    data_version: str
    data_checksums: dict[str, Sha256]
    target: str
    horizon_hours: int = Field(ge=0, description="0 for same-time inference (no forecast).")
    features: list[str]
    hyperparameters: dict[str, Any]
    artifacts: dict[str, str] = Field(description="Name -> path relative to the run directory.")
    warnings: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> RunManifest:
        if self.split.embargo_hours < self.horizon_hours:
            raise ValueError("embargo_hours must be at least horizon_hours to avoid target leakage")
        return self


class MetricRow(_Model):
    estimator: str
    metric: str
    value: float
    n: int = Field(ge=0)
    slice: str = "all"


class MetricsReport(_Model):
    """Every estimator in one report is evaluated on the same split."""

    schema_version: str = SCHEMA_VERSION
    model_id: str
    task_id: str
    split: SplitSpec
    rows: list[MetricRow]


# ---------------------------------------------------------------------- API shapes


class TaskInfo(_Model):
    task_id: str
    task_type: Literal["regression", "classification"] = "regression"
    target: str
    unit: str
    horizon_hours: int = Field(ge=0, description="0 for same-time inference (no forecast).")
    status: Literal["planned", "available"]
    model_id: str | None = Field(None, description="Model the API serves for this task; null while none exists.")
    title: str | None = Field(None, description="Title of the task (its territory), e.g. 'Madrid air quality'; v0.4.1.")
    territory: str | None = Field(
        None, description="v0.5: territory id shared by the tasks that differ only in horizon_hours, e.g. 'madrid'. "
        "The UI offers one territory with a horizon selector over its tasks."
    )
    territory_title: str | None = Field(None, description="v0.5: display name of the territory, e.g. 'Madrid'.")
    territory_title_en: str | None = Field(
        None, description="v0.6: English display name of the territory, e.g. 'Germany' for 'Alemania'; the UI shows "
        "it when the interface is in English, else falls back to `territory_title`."
    )


class DomainInfo(_Model):
    domain: Domain
    title: str
    status: Literal["planned", "etl", "available"]
    tasks: list[TaskInfo]


class DomainsResponse(_Envelope):
    domains: list[DomainInfo]


class TimeCoverage(_Model):
    """Issue times with precomputed outputs; drives the timeline."""

    issued_from_utc: UtcDatetime
    issued_to_utc: UtcDatetime
    step_hours: int = Field(gt=0)
    regular: bool = Field(
        True,
        description="v0.4. False: issue times are irregular sample times (step_hours=1 is only the finest step the "
        "contract expresses); use window aggregates, not issue-time instants.",
    )


class ModelCard(_Envelope):
    manifest: RunManifest
    target_scheme: TargetScheme | None = Field(None, description="Class labels, bounds and colours (classifiers).")
    metrics: MetricsReport | None = None
    coverage: TimeCoverage | None = None
    attribution: list[Attribution] = Field([], description="v0.4: credits and licences of the model's data.")


class Health(_Model):
    status: Literal["ok"]
    schema_version: str = SCHEMA_VERSION
    mode: Literal["mock", "artifacts"]


# ------------------------------------------------- v0.4: map views, territories, stories, what-if

TIE_TOLERANCE = 1e-12
WHAT_IF_LABEL = "respuesta del modelo ante entradas modificadas"
STORIES_DISCLAIMER = "Descripciones de activaciones del modelo en la ventana pedida."


class TerritoryMeasure(str, Enum):
    MEAN_ACTIVATION = "mean_activation"  # mean firing over the n_valid records
    ACTIVATION_FREQUENCY = "activation_frequency"  # share of n_valid records with firing >= tau
    WINNER_SHARE = "winner_share"  # classifiers: share of n_valid records the rule decided the class


class StoryKind(str, Enum):
    CO_ACTIVATION_BURST = "co_activation_burst"  # many entities above tau at once, for consecutive issue times
    LOCALIZED_RULE = "localized_rule"  # a rule that is often active in only a few entities
    TERRITORY_LEADER = "territory_leader"  # the rule that is dominant (mean_activation) in most entities


def dominant_index(values: Sequence[float]) -> int | None:
    """Position of the largest value; values within ``TIE_TOLERANCE`` of it tie and the lowest position wins.

    ``None`` when nothing is positive: a rule is never called dominant for a measure that is 0 everywhere.
    """
    if not values:
        return None
    best = max(values)
    if best <= 0:
        return None
    return next(i for i, v in enumerate(values) if v >= best - TIE_TOLERANCE)


def _window_ok(start: datetime | None, end: datetime | None) -> None:
    if start is None or end is None or end <= start:
        raise ValueError("a window needs time_from_utc < time_to_utc")


# --- GET /api/v1/predictions


class PredictionProperties(_Model):
    entity_id: str
    model_id: str
    data_version: str
    unit: str
    issued_at_utc: UtcDatetime | None = Field(description="Null when the entity has no row in the query.")
    valid_at_utc: UtcDatetime | None
    prediction: float | None
    prediction_label: str | None = Field(None, description="Predicted class (classification tasks).")
    observed: float | None = Field(None, description="Target observed at valid_at_utc, if known. Not a prediction.")
    observed_label: str | None = None
    geometry_support: GeometrySupport
    missing_reason: MissingReason | None = None
    quality: Quality = Quality()
    decided_by_rule_id: str | None = Field(
        None, description="v0.5.1: the rule that decided this prediction, by the /importance measure: the winning rule "
        "(winning-rule classifier) or the rule with the largest weight share f_r/Σf (TSK). Null without a prediction "
        "or with no rule fired, and always null for the rule mixture (no single rule decides; see top_rule_id). It is "
        "not a cause."
    )
    top_rule_id: str | None = Field(
        None, description="v0.7, rule mixture only: the rule that supports the predicted class the most (largest "
        "positive centred contribution to its score). Every rule that fires contributes; this one did not decide "
        "alone. Null without a prediction or when no rule supports the predicted class."
    )
    top_rule_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture only: the top rule's centred contribution to the predicted class over "
        "the sum of the positive centred contributions to it."
    )

    @model_validator(mode="after")
    def _consistent(self) -> PredictionProperties:
        _check_prediction(self.prediction, self.prediction_label, self.missing_reason)
        if self.decided_by_rule_id is not None and self.prediction is None and self.prediction_label is None:
            raise ValueError("decided_by_rule_id needs a prediction")
        if (self.top_rule_id is None) != (self.top_rule_share is None):
            raise ValueError("top_rule_id and top_rule_share go together")
        if self.top_rule_id is not None and (self.prediction_label is None or self.decided_by_rule_id is not None):
            raise ValueError("top_rule_id needs a predicted class and excludes decided_by_rule_id")
        if (self.issued_at_utc is None) != (self.valid_at_utc is None):
            raise ValueError("issued_at_utc and valid_at_utc go together")
        if self.issued_at_utc is None and self.missing_reason is None:
            raise ValueError("an entity without a row needs missing_reason")
        if self.missing_reason == MissingReason.NOT_MODELLED and (self.observed is not None or self.issued_at_utc):
            raise ValueError("an entity with no model has no row")
        return self


class PredictionFeature(_Model):
    type: Literal["Feature"]
    id: str
    geometry: Geometry | None
    properties: PredictionProperties

    @model_validator(mode="after")
    def _consistent(self) -> PredictionFeature:
        if self.id != self.properties.entity_id:
            raise ValueError("Feature.id must equal properties.entity_id")
        _check_geometry(self.geometry, self.properties.geometry_support)
        return self


class PredictionsResponse(_Envelope):
    """All entities at one issue time (``issued_at_utc``) or, for irregular tasks, the latest sample in a window."""

    type: Literal["FeatureCollection"]
    task_id: str
    model_id: str
    task_type: Literal["regression", "classification"]
    target: str
    unit: str
    horizon_hours: int = Field(ge=0)
    issued_at_utc: UtcDatetime | None = Field(None, description="Set for a query by time; each feature has its own.")
    time_from_utc: UtcDatetime | None = Field(None, description="Window start (inclusive) when queried by window.")
    time_to_utc: UtcDatetime | None = Field(None, description="Window end (exclusive) when queried by window.")
    features: list[PredictionFeature]

    @model_validator(mode="after")
    def _consistent(self) -> PredictionsResponse:
        instant = self.issued_at_utc is not None
        if instant == (self.time_from_utc is not None) or (self.time_from_utc is None) != (self.time_to_utc is None):
            raise ValueError("a query is a single time or a window from/to, not both and not neither")
        if not instant:
            _window_ok(self.time_from_utc, self.time_to_utc)
        horizon, seen = timedelta(hours=self.horizon_hours), set()
        for feature in self.features:
            p = feature.properties
            if p.model_id != self.model_id or p.data_version != self.data_version or p.unit != self.unit:
                raise ValueError(f"feature {feature.id} disagrees with the collection metadata")
            if feature.id in seen:
                raise ValueError(f"duplicate entity {feature.id}")
            seen.add(feature.id)
            if p.issued_at_utc is not None:
                if p.valid_at_utc - p.issued_at_utc != horizon:
                    raise ValueError(f"{feature.id}: valid_at - issued_at must equal horizon_hours")
                if instant and p.issued_at_utc != self.issued_at_utc:
                    raise ValueError(f"{feature.id}: issued_at_utc differs from the query time")
                if not instant and not self.time_from_utc <= p.issued_at_utc < self.time_to_utc:
                    raise ValueError(f"{feature.id}: issued_at_utc is outside the window")
        return self


# --- GET /api/v1/observations (data mode)


class ObservationProperties(_Model):
    """Observed target and model inputs of one entity at one issue time. Not a prediction, not an interpolation."""

    entity_id: str
    model_id: str
    data_version: str
    issued_at_utc: UtcDatetime | None
    valid_at_utc: UtcDatetime | None
    target: FeatureValue | None = Field(
        description="The target observed at valid_at_utc (= issued + horizon), so not known at issue time unless the "
        "horizon is 0. value null = missing, with its reason."
    )
    target_label: str | None = Field(None, description="Class of the observed target (classification tasks).")
    inputs: list[FeatureValue] = Field(
        description="Model input values at issue time; observed_at_utc <= issued_at_utc."
    )
    geometry_support: GeometrySupport
    missing_reason: MissingReason | None = Field(
        None, description="Set when the entity has no row at all (no_observation) or no model (not_modelled)."
    )
    quality: Quality = Quality()

    @model_validator(mode="after")
    def _consistent(self) -> ObservationProperties:
        if (self.issued_at_utc is None) != (self.valid_at_utc is None):
            raise ValueError("issued_at_utc and valid_at_utc go together")
        has_row = self.issued_at_utc is not None
        if has_row == (self.missing_reason is not None):
            raise ValueError("an entity has a row xor a missing_reason")
        if not has_row and (self.target is not None or self.inputs or self.target_label is not None):
            raise ValueError("an entity without a row carries no values")
        if has_row and self.target is None:
            raise ValueError("a row needs a target (value null with a reason when missing)")
        for fv in self.inputs:
            if fv.observed_at_utc is not None and fv.observed_at_utc > self.issued_at_utc:
                raise ValueError(f"{fv.feature} was observed after issued_at_utc (future information)")
        return self


class ObservationFeature(_Model):
    type: Literal["Feature"]
    id: str
    geometry: Geometry | None
    properties: ObservationProperties

    @model_validator(mode="after")
    def _consistent(self) -> ObservationFeature:
        if self.id != self.properties.entity_id:
            raise ValueError("Feature.id must equal properties.entity_id")
        _check_geometry(self.geometry, self.properties.geometry_support)
        return self


class ObservationsResponse(_Envelope):
    type: Literal["FeatureCollection"]
    task_id: str
    model_id: str
    target: str
    unit: str
    horizon_hours: int = Field(ge=0)
    issued_at_utc: UtcDatetime | None = None
    time_from_utc: UtcDatetime | None = None
    time_to_utc: UtcDatetime | None = None
    note: str = Field(
        "Valores observados publicados (entradas del modelo y objetivo en valid_at_utc), no predicciones ni "
        "interpolaciones; null = ausente, con su motivo."
    )
    features: list[ObservationFeature]

    @model_validator(mode="after")
    def _consistent(self) -> ObservationsResponse:
        instant = self.issued_at_utc is not None
        if instant == (self.time_from_utc is not None) or (self.time_from_utc is None) != (self.time_to_utc is None):
            raise ValueError("a query is a single time or a window from/to, not both and not neither")
        if not instant:
            _window_ok(self.time_from_utc, self.time_to_utc)
        seen = set()
        for feature in self.features:
            p = feature.properties
            if p.model_id != self.model_id or p.data_version != self.data_version:
                raise ValueError(f"feature {feature.id} disagrees with the collection metadata")
            if feature.id in seen:
                raise ValueError(f"duplicate entity {feature.id}")
            seen.add(feature.id)
            if p.issued_at_utc is not None and p.valid_at_utc - p.issued_at_utc != timedelta(hours=self.horizon_hours):
                raise ValueError(f"{feature.id}: valid_at - issued_at must equal horizon_hours")
        return self


# --- GET /api/v1/rule-territories (E2)


class TerritoryRuleStats(_Model):
    rule_id: str
    mean_activation: UnitInterval = Field(description="Mean firing over the entity's n_valid records.")
    activation_frequency: UnitInterval = Field(description="Share of the n_valid records with firing >= tau.")
    winner_share: UnitInterval | None = Field(
        None, description="Winning-rule classifiers: share of the n_valid records in which this rule decided the "
        "class. Null for the rule mixture, where no rule decides alone."
    )


class TerritoryProperties(_Model):
    entity_id: str
    model_id: str
    data_version: str
    geometry_support: GeometrySupport
    n_records: int = Field(ge=0, description="Published issue times of the entity in the window.")
    n_valid: int = Field(ge=0, description="Records with every model input present: the denominator of all values.")
    dominant_rule_id: str | None = Field(
        None, description="Argmax of the chosen measure only (ties: lowest rule position). Not the rule that "
        "'explains' the prediction; null when n_valid is 0 or the measure is 0 for every rule."
    )
    dominant_value: UnitInterval | None = None
    rules: list[TerritoryRuleStats] = Field([], description="Every rule of the model; empty when n_valid is 0.")
    missing_reason: MissingReason | None = None
    quality: Quality = Quality()

    @model_validator(mode="after")
    def _consistent(self) -> TerritoryProperties:
        if self.n_valid > self.n_records:
            raise ValueError("n_valid cannot exceed n_records")
        if (self.n_valid == 0) != (self.missing_reason is not None):
            raise ValueError("missing_reason is required exactly when n_valid is 0")
        if self.n_valid == 0 and (self.rules or self.dominant_rule_id is not None):
            raise ValueError("an entity without valid records carries no rule values")
        if (self.dominant_rule_id is None) != (self.dominant_value is None):
            raise ValueError("dominant_rule_id and dominant_value go together")
        if self.n_valid and not self.rules:
            raise ValueError("an entity with valid records lists every rule")
        return self


class TerritoryFeature(_Model):
    type: Literal["Feature"]
    id: str
    geometry: Geometry | None
    properties: TerritoryProperties

    @model_validator(mode="after")
    def _consistent(self) -> TerritoryFeature:
        if self.id != self.properties.entity_id:
            raise ValueError("Feature.id must equal properties.entity_id")
        _check_geometry(self.geometry, self.properties.geometry_support)
        return self


class RuleTerritoriesResponse(_Envelope):
    """Empirical territory of every rule over a window ``[from, to)``. Territories overlap: they are not a partition."""

    type: Literal["FeatureCollection"]
    model_id: str
    inference_family: InferenceFamily
    measure: TerritoryMeasure = Field(description="Measure that picks each entity's dominant rule.")
    tau: UnitInterval = Field(gt=0, description="Threshold of activation_frequency (reported for every rule).")
    time_from_utc: UtcDatetime
    time_to_utc: UtcDatetime
    n_rules: int = Field(ge=1)
    tie_break: str
    denominators: str
    notes: list[str] = []
    features: list[TerritoryFeature]

    @model_validator(mode="after")
    def _consistent(self) -> RuleTerritoriesResponse:
        _window_ok(self.time_from_utc, self.time_to_utc)
        classifier = self.inference_family == InferenceFamily.WINNING_RULE_CLASSIFIER
        if self.measure == TerritoryMeasure.WINNER_SHARE and not classifier:
            raise ValueError("winner_share only exists for winning-rule classifiers")
        seen = set()
        for feature in self.features:
            p = feature.properties
            if p.model_id != self.model_id or p.data_version != self.data_version:
                raise ValueError(f"feature {feature.id} disagrees with the collection metadata")
            if feature.id in seen:
                raise ValueError(f"duplicate entity {feature.id}")
            seen.add(feature.id)
            if not p.rules:
                continue
            if len(p.rules) != self.n_rules:
                raise ValueError(f"{feature.id}: every rule must be listed")
            if any((r.winner_share is not None) != classifier for r in p.rules):
                raise ValueError(f"{feature.id}: winner_share exactly for classifiers")
            chosen = dominant_index([getattr(r, self.measure.value) for r in p.rules])
            expected = None if chosen is None else p.rules[chosen].rule_id
            if p.dominant_rule_id != expected:
                raise ValueError(f"{feature.id}: dominant_rule_id must be the argmax of {self.measure.value}")
        return self


# --- GET /api/v1/rule-stories (Rule Stories, MAP_EXPERIENCE section 8)


class StoryQuery(_Model):
    """A request that returns the data a story is computed from."""

    method: Literal["GET"] = "GET"
    path: Literal["/api/v1/rule-map", "/api/v1/rule-territories"]
    params: dict[str, str]


class StoryCheck(_Model):
    """Machine-checkable claim: count the features of ``queries[query]`` whose property satisfies ``op``."""

    query: int = Field(ge=0, description="Index into the story's queries.")
    property: str = Field(description="Key of Feature.properties, e.g. value, dominant_rule_id or n_valid.")
    op: Literal["gte", "eq", "not_null"]
    operand: float | str | None = Field(None, description="Right-hand side of gte/eq; null for not_null.")
    expected: int = Field(ge=0, description="The number of features that must satisfy it.")

    @model_validator(mode="after")
    def _consistent(self) -> StoryCheck:
        if (self.op == "not_null") != (self.operand is None):
            raise ValueError("operand is required for gte/eq and absent for not_null")
        return self


class RuleStory(_Model):
    story_id: str = Field(description="Deterministic: kind, rule and anchor.")
    kind: StoryKind
    rule_id: str
    text: str = Field(description="Template-built statement about activations. Never a cause or an explanation.")
    score: UnitInterval = Field(
        description="Interestingness used for ranking (see RuleStoriesResponse.score_definition)."
    )
    numbers: dict[str, float | int | str] = Field(description="Every number quoted in the text.")
    queries: list[StoryQuery] = Field(min_length=1)
    checks: list[StoryCheck] = Field(min_length=1, description="Counts over the query results that reproduce numbers.")

    @model_validator(mode="after")
    def _consistent(self) -> RuleStory:
        for check in self.checks:
            if check.query >= len(self.queries):
                raise ValueError("check refers to a query that does not exist")
        return self


class RuleStoriesResponse(_Envelope):
    model_id: str
    time_from_utc: UtcDatetime
    time_to_utc: UtcDatetime
    tau: UnitInterval = Field(gt=0)
    limit: int = Field(ge=1)
    n_candidates: int = Field(ge=0, description="Stories found before the cap.")
    score_definition: str
    disclaimer: str = STORIES_DISCLAIMER
    stories: list[RuleStory]

    @model_validator(mode="after")
    def _consistent(self) -> RuleStoriesResponse:
        _window_ok(self.time_from_utc, self.time_to_utc)
        if len(self.stories) > self.limit:
            raise ValueError("more stories than the limit")
        scores = [s.score for s in self.stories]
        if scores != sorted(scores, reverse=True):
            raise ValueError("stories must be ranked by descending score")
        ids = [s.story_id for s in self.stories]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate story_id")
        return self


# --- POST /api/v1/scenarios (E5, what-if)


class ScenarioRequest(_Model):
    model_id: str
    entity_id: str
    at: UtcDatetime = Field(description="Issue time of the published row to start from.")
    overrides: dict[str, Annotated[float, Field(allow_inf_nan=False)]] = Field(
        {}, description="feature -> value. Known features only, finite, inside the variable's domain."
    )


class ScenarioInput(_Model):
    feature: str
    unit: str | None = None
    origin: Literal["observed", "overridden"]
    original_value: float | None
    scenario_value: float | None
    domain: tuple[float, float] | None = Field(None, description="Allowed range of an override.")
    missing_reason: MissingReason | None = Field(None, description="Why original_value is null, if it is.")


class RuleDelta(_Model):
    rule_id: str
    firing_original: float | None
    firing_scenario: float | None
    firing_delta: float | None = Field(description="scenario - original; null if either side has no inference.")
    association_original: float | None = None
    association_scenario: float | None = None
    association_delta: float | None = None


class PredictionChange(_Model):
    original_value: float | None
    scenario_value: float | None
    value_delta: float | None = None
    original_label: str | None = None
    scenario_label: str | None = None
    label_changed: bool | None = None
    original_winning_rule_id: str | None = None
    scenario_winning_rule_id: str | None = None
    original_top_rule_id: str | None = Field(None, description="v0.7, rule mixture: top_rule_id of the original trace.")
    scenario_top_rule_id: str | None = Field(None, description="v0.7, rule mixture: top_rule_id of the modified trace.")


class ScenarioResponse(_Envelope):
    """The model's answer to a modified input row. Nothing is written anywhere; the dataset is untouched."""

    model_id: str
    entity_id: str
    issued_at_utc: UtcDatetime
    synthetic_what_if: Literal[True] = True
    label: str = WHAT_IF_LABEL
    inputs: list[ScenarioInput]
    original: RuleTrace
    modified: RuleTrace
    rule_deltas: list[RuleDelta]
    prediction_change: PredictionChange

    @model_validator(mode="after")
    def _consistent(self) -> ScenarioResponse:
        for trace in (self.original, self.modified):
            key = (trace.model_id, trace.entity_id, trace.issued_at_utc)
            if key != (self.model_id, self.entity_id, self.issued_at_utc):
                raise ValueError("both traces must be for the requested model, entity and time")
        by_feature = {fv.feature: fv for fv in self.modified.feature_values}
        for item in self.inputs:
            if by_feature[item.feature].value != item.scenario_value:
                raise ValueError(f"{item.feature}: scenario_value differs from the modified trace")
            if item.origin == "observed" and item.scenario_value != item.original_value:
                raise ValueError(f"{item.feature}: an observed input cannot change")
        before = {e.rule_id: e for e in self.original.rules}
        after = {e.rule_id: e for e in self.modified.rules}
        for delta in self.rule_deltas:
            a, b = before.get(delta.rule_id), after.get(delta.rule_id)
            if (delta.firing_original, delta.firing_scenario) != (
                None if a is None else a.firing_strength, None if b is None else b.firing_strength
            ):
                raise ValueError(f"{delta.rule_id}: deltas disagree with the traces")
            if (delta.firing_delta is None) != (a is None or b is None):
                raise ValueError(f"{delta.rule_id}: firing_delta needs both traces")
            if delta.firing_delta is not None and (
                abs(delta.firing_scenario - delta.firing_original - delta.firing_delta) > PARITY_TOLERANCE
            ):
                raise ValueError(f"{delta.rule_id}: firing_delta != scenario - original")
        return self


# --- GET /api/v1/models/{model_id}/importance (v0.5)


class ImportanceMeasure(str, Enum):
    WINNING_RULE = "winning_rule"  # classifier: the rule with the largest firing x weight decides the class
    WEIGHTED_AVERAGE = "weighted_average"  # TSK zero order, additive: output = sum(f_r c_r) / sum(f_r)
    RULE_MIXTURE = "rule_mixture"  # v0.7: every rule contributes W[r, c] x firing to each class score


class RuleImportance(_Model):
    """How much one rule weighs in the model's published predictions. Faithful to the inference, not causal.

    Winning-rule classifier and TSK: ``n_decided`` / ``decided_share``. Rule mixture (v0.7): no rule decides alone, so
    those are null and the rule has ``n_top`` / ``top_contributor_share`` and ``n_decisive`` / ``decisive_share``."""

    rule_id: str
    n_decided: int | None = Field(
        None, ge=0, description="Predictions this rule decided: the winning rule (classifier) or the rule with the "
        "largest share of the weighted average (regression; ties: lowest position). Null for the rule mixture."
    )
    decided_share: UnitInterval | None = Field(
        None, description="n_decided / n_predicted of the response. Null for the rule mixture."
    )
    n_checked: int = Field(
        ge=0, description="Of n_decided (rule mixture: of n_top), those with an observed value to compare with."
    )
    accuracy: UnitInterval | None = Field(
        None, description="Classifier: share of the n_checked predictions (decided by the rule; for the rule "
        "mixture, those where it is the top rule) whose class is the observed class; null when n_checked is 0 or for "
        "regression."
    )
    n_top: int | None = Field(
        None, ge=0, description="v0.7, rule mixture: predictions where this rule is the top rule (largest positive "
        "centred contribution to the predicted class; see TracePrediction.top_rule_id)."
    )
    top_contributor_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture: n_top / n_predicted. The shares of the rules add up to at most 1."
    )
    n_decisive: int | None = Field(
        None, ge=0, description="v0.7, rule mixture: predictions whose class would change if this rule's weights were "
        "set to 0 (the model's own argmax, recomputed by ex_fuzzy with that rule's weights removed)."
    )
    decisive_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture: n_decisive / n_predicted. Several rules can be decisive for one "
        "prediction and none for another, so the shares do not add up to 1. Measured, not a probability."
    )
    mean_weight_share: UnitInterval | None = Field(
        None, description="Regression only: mean over the predictions of f_r / sum(f), the exact share of this rule in "
        "the weighted average (the shares of one prediction add up to 1)."
    )
    mae: float | None = Field(
        None, ge=0, description="Regression only: mean absolute error of the n_checked predictions this rule decided."
    )


class VariableImportance(_Model):
    feature: str
    n_rules: int = Field(ge=0, description="Rules whose antecedents use the input.")
    decided_share: UnitInterval | None = Field(
        None, description="Winning-rule classifier: share of the predictions decided by a rule that uses the input. "
        "Regression: mean over the predictions of the summed weight share of the rules that use it. Null for the "
        "rule mixture."
    )
    top_contributor_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture: share of the predictions whose top rule uses the input."
    )
    decisive_share: UnitInterval | None = Field(
        None, description="v0.7, rule mixture: share of the predictions for which at least one rule that uses the "
        "input is decisive (zeroing that rule's weights changes the class)."
    )


class EntityRuleImportance(_Model):
    rule_id: str
    decided_share: UnitInterval | None = Field(
        None, description="Share of the entity's n_predicted decided by this rule; null for the rule mixture."
    )
    accuracy: UnitInterval | None = None
    mean_weight_share: UnitInterval | None = None
    mae: float | None = Field(None, ge=0)
    top_contributor_share: UnitInterval | None = Field(None, description="v0.7, rule mixture: as RuleImportance.")
    decisive_share: UnitInterval | None = Field(None, description="v0.7, rule mixture: as RuleImportance.")


class EntityImportance(_Model):
    """The same measures inside one entity ('by zone'). Only rules that decided at least one prediction (rule mixture:
    that are the top rule or decisive for at least one) are listed."""

    entity_id: str
    n_predicted: int = Field(ge=0)
    rules: list[EntityRuleImportance]


class RuleImportanceResponse(_Envelope):
    """Rule and input importance over the published period of a model (precomputed at publish time)."""

    model_id: str
    task_id: str
    measure: ImportanceMeasure
    period_from_utc: UtcDatetime
    period_to_utc: UtcDatetime
    n_predicted: int = Field(ge=0, description="Published predictions with a model output (some rule fired).")
    n_no_rule: int = Field(ge=0, description="Published issue times with complete inputs where no rule fired.")
    n_withheld: int = Field(
        0, ge=0, description="v0.5: issue times where a rule fired but the publish withheld the prediction (e.g. NYC "
        "cells without a reference level); attributed to no rule and not in n_predicted."
    )
    n_no_top_rule: int | None = Field(
        None, ge=0, description="v0.7, rule mixture: predictions where no rule supports the predicted class (it wins "
        "on its bias and on what the rules take away from the other classes); they have no top rule."
    )
    rules: list[RuleImportance] = Field(description="Every rule of the model, in rule-base order.")
    variables: list[VariableImportance] = Field(description="Every input of the model.")
    entities: list[EntityImportance]
    observed_class_shares: dict[str, float] | None = Field(
        None, description="v0.5.2, classifiers: share of each observed class among the predictions with an observation "
        "(the union of the rules' n_checked), so a rule's accuracy can be read against how often its class occurs in "
        "the same predictions. Keys are scheme labels; the shares add up to 1."
    )

    @model_validator(mode="after")
    def _consistent(self) -> RuleImportanceResponse:
        regression = self.measure == ImportanceMeasure.WEIGHTED_AVERAGE
        mixture = self.measure == ImportanceMeasure.RULE_MIXTURE
        if self.observed_class_shares is not None:
            if regression:
                raise ValueError("observed_class_shares is for classifiers")
            if self.observed_class_shares and abs(sum(self.observed_class_shares.values()) - 1) > 1e-6:
                raise ValueError("observed_class_shares add up to 1")
        if mixture != (self.n_no_top_rule is not None):
            raise ValueError("n_no_top_rule is set exactly for the rule mixture")
        for r in self.rules:
            mixture_fields = (r.n_top, r.top_contributor_share, r.n_decisive, r.decisive_share)
            if mixture != all(v is not None for v in mixture_fields) or (not mixture and any(
                    v is not None for v in mixture_fields)):
                raise ValueError(f"{r.rule_id}: the top and decisive measures are for the rule mixture, and only there")
            if mixture == (r.n_decided is not None) or mixture == (r.decided_share is not None):
                raise ValueError(f"{r.rule_id}: n_decided and decided_share are for the winning rule and TSK only")
            if r.n_checked > (r.n_top if mixture else r.n_decided):
                raise ValueError(f"{r.rule_id}: n_checked cannot exceed the predictions it counts")
            if mixture and r.n_decisive > self.n_predicted:
                raise ValueError(f"{r.rule_id}: n_decisive cannot exceed n_predicted")
            if regression and (r.accuracy is not None or r.mean_weight_share is None):
                raise ValueError(f"{r.rule_id}: regression carries mean_weight_share and no accuracy")
            if not regression and (r.mean_weight_share is not None or r.mae is not None):
                raise ValueError(f"{r.rule_id}: classifier rules carry no weight share or mae")
        if mixture:
            if sum(r.n_top for r in self.rules) + self.n_no_top_rule != self.n_predicted:
                raise ValueError("every prediction has one top rule or is counted in n_no_top_rule")
        elif sum(r.n_decided for r in self.rules) != self.n_predicted:
            raise ValueError("every prediction is decided by exactly one rule")
        if regression and self.n_predicted and abs(sum(r.mean_weight_share for r in self.rules) - 1) > 1e-6:
            raise ValueError("the mean weight shares add up to 1")
        for v in self.variables:
            if mixture != (v.decided_share is None) or (mixture and (
                    v.top_contributor_share is None or v.decisive_share is None)) or (not mixture and (
                    v.top_contributor_share is not None or v.decisive_share is not None)):
                raise ValueError(f"{v.feature}: decided_share for the winning rule and TSK, top_contributor_share and "
                                 "decisive_share for the rule mixture")
        return self


# --- GET /api/v1/summary (v0.5): what the data say, without the model


class SummaryGroup(str, Enum):
    ALL = "all"
    YEAR = "year"  # key '2019'
    MONTH = "month"  # key '01'..'12', local time
    HOUR = "hour"  # key '00'..'23', local time
    WEEKDAY = "weekday"  # key '0' (Monday)..'6', local time
    ENTITY = "entity"  # key = entity_id


class DistributionRow(_Model):
    key: str
    n: int = Field(ge=0, description="Observed values in the group.")
    shares: list[UnitInterval] | None = Field(
        None, description="Classified variable: share of n in each class of the response's `classes`, same order."
    )
    quantiles: dict[str, float] | None = Field(
        None, description="Numeric variable: 'p10', 'p25', 'p50', 'p75', 'p90' and 'mean'."
    )


class SummaryResponse(_Envelope):
    """Distribution of the observed variable of a task over its whole history (precomputed at publish time)."""

    task_id: str
    domain: Domain
    variable: str = Field(description="Observed variable summarised, e.g. 'no2'; not a model output.")
    label: str = Field(description="Display name, e.g. 'NO₂ horario observado'.")
    label_en: str | None = Field(
        None, description="v0.6: English display name, e.g. 'Observed hourly NO₂'; the UI shows it when the "
        "interface is in English, else falls back to `label`."
    )
    unit: str
    timezone: str = Field(description="IANA zone of the month, hour and weekday groups.")
    period_from_utc: UtcDatetime
    period_to_utc: UtcDatetime
    classes: list[TargetClass] | None = Field(
        None, description="When set, values are binned into these classes (the task's target scheme); otherwise "
        "rows carry quantiles."
    )
    groups: dict[SummaryGroup, list[DistributionRow]]
    notes: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> SummaryResponse:
        if SummaryGroup.ALL not in self.groups or len(self.groups[SummaryGroup.ALL]) != 1:
            raise ValueError("groups['all'] holds exactly one row")
        for group, rows in self.groups.items():
            for row in rows:
                if self.classes is not None:
                    if row.quantiles is not None or row.shares is None or len(row.shares) != len(self.classes):
                        raise ValueError(f"{group}/{row.key}: a classified summary has one share per class")
                    if row.n and abs(sum(row.shares) - 1) > 1e-6:
                        raise ValueError(f"{group}/{row.key}: shares add up to 1")
                elif row.shares is not None or (row.n and row.quantiles is None):
                    raise ValueError(f"{group}/{row.key}: a numeric summary has quantiles")
        return self


# --- GET /api/v1/models/{model_id}/explanation (v0.6.2): a text about the rule base, written by an AI


class ExplanationText(_Model):
    """The explanation in one language: a headline, a few short paragraphs and a few points to check on the page."""

    headline: str = Field(min_length=1)
    summary: list[str] = Field(min_length=1, description="Short paragraphs, in reading order.")
    points: list[str] = Field(description="Things the reader can check in the rules below.")


class ExplanationAuthor(_Model):
    """Who wrote the text. It was written by an AI (Claude, called through the Claude Code CLI) from the model's
    published files only (rules, importance, card metrics, summary, registry), and is not a human analysis."""

    tool: str = Field(description="What produced the text, e.g. 'Claude Code' (the CLI that called the model).")
    tool_version: str | None = Field(None, description="Version of that tool, as it reports it (e.g. '2.1.319').")
    model: str | None = Field(None, description="The AI model as the tool reported it (e.g. 'claude-opus-5-5').")


class ModelExplanation(_Envelope):
    """v0.6.2: a short explanation of one published model's rule base, in Spanish and English, written by an AI from
    a template (``configs/explanations/TEMPLATE.md``) and the model's published files. Every number in it is one of
    the published figures; the text describes how the model maps inputs to outputs and claims no causes."""

    model_id: str
    template_version: str = Field(description="Version of the template the text was written from.")
    generated_by: ExplanationAuthor
    generated_at_utc: UtcDatetime
    input_sha256: Sha256 = Field(
        description="sha256 of the context JSON built from the published files; a republished model no longer matches."
    )
    reviewed: bool = Field(description="True once a person has read the text against the rules and metrics.")
    es: ExplanationText
    en: ExplanationText
