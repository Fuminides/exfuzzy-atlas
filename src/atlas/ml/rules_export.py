"""``rules.json`` (AT-042): a fitted crisp TSK rule base as a ``ModelRules`` contract object.

Linguistic variables, terms and membership parameters are read from the fitted model, never re-derived.
Membership classes are mapped by *exact* type; anything unknown (categorical, interval type-2, ...) raises
``UnsupportedModelError`` instead of being exported with invented parameters.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from ex_fuzzy import fuzzy_sets as fs

from atlas import compound_terms
from atlas.contracts import models as m
from atlas.explain import (
    UnsupportedModelError,
    compute_activations,
    duplicate_groups,
    feature_names,
    get_rulebase,
    inference_spec,
    rule_ids,
)
from atlas.explain import classifier as clf_engine
from atlas.explain import mixture as mix_engine
from atlas.explain.engine import rule_modifier
from atlas.ml.exfuzzy_features import rule_conditions

# exact class -> (contract membership_type, number of parameters). triangularFS keeps ex_fuzzy's
# four-parameter trapezoid form; gaussianFS is exp(-((x - mean) / std) ** 2), with no 1/2 factor.
_MEMBERSHIP = {
    fs.FS: ("trapezoidal", 4),
    fs.triangularFS: ("triangular", 4),
    fs.gaussianFS: ("gaussian", 2),
}
ACTIVATION_TAU = 0.5


def _conditions(rule, variables, names: Sequence[str], labels: dict) -> list[tuple[int, m.Antecedent]]:
    """``(feature index, Antecedent)`` of every condition of ``rule`` (contract v0.8).

    ``is`` / ``at_least`` / ``at_most`` / ``any_of`` and the base terms they cover come from ``rule.conditions()``
    (``rule_conditions``), never from the printed rule; a compound takes its display names from ``labels``
    (``atlas.compound_terms``, keyed by its internal name).
    """
    out = []
    for c in rule_conditions(rule, variables):
        antecedent = m.Antecedent(feature=names[c.feature], term=c.term, operator=c.operator, terms=list(c.terms))
        out.append((c.feature, compound_terms.label_antecedent(antecedent, labels)))
    return out


_OPERATOR_WORDS = {"is": "", "at_least": "at least ", "at_most": "at most ", "any_of": ""}


def condition_text(antecedents: Sequence[m.Antecedent]) -> str:
    """"a IS x AND b IS at least y AND c IS <compound>": the rule's conditions as ex_fuzzy prints them."""
    return " AND ".join(f"{a.feature} IS {_OPERATOR_WORDS[a.operator]}{a.term}" for a in antecedents)


def _term(fuzzy_set) -> m.LinguisticTerm:
    kind = _MEMBERSHIP.get(type(fuzzy_set))
    if kind is None:
        raise UnsupportedModelError(
            f"term {fuzzy_set.name!r} has unsupported fuzzy set class {type(fuzzy_set).__name__}"
        )
    membership_type, n_params = kind
    params = [float(p) for p in fuzzy_set.membership_parameters]
    if len(params) != n_params:
        raise UnsupportedModelError(f"term {fuzzy_set.name!r}: expected {n_params} parameters, got {params}")
    return m.LinguisticTerm(name=str(fuzzy_set.name), membership_type=membership_type, params=params)


def _valid_time(horizon_hours: int) -> str:
    """'t+6h' for a forecast; plain 't' for same-time inference (horizon 0)."""
    return f"t+{horizon_hours}h" if horizon_hours else "t"


def export_model_rules(
    model,
    *,
    model_id: str,
    task_id: str,
    domain: m.Domain,
    target: str,
    target_unit: str,
    horizon_hours: int,
    data_version: str,
    synthetic: bool = False,
    feature_units: dict[str, str] | None = None,
    X_reference: pd.DataFrame | None = None,
) -> m.ModelRules:
    """Describe the fitted model. ``X_reference`` (training rows) adds per-rule activation summaries.

    Rule ids are positional (R01, R02, ...) and therefore unique even when the GA returns several rules with
    identical antecedents; such rules get ``duplicate_of`` naming the first rule of the group and a note in
    ``text``. Rules are never merged or dropped, so column ``r`` of every
    firing array and rule ``R(r+1)`` stay aligned with the model.
    """
    rulebase = get_rulebase(model)
    names = feature_names(rulebase)
    ids = rule_ids(rulebase)
    units = {name: getattr(var, "units", None) for name, var in zip(names, rulebase.antecedents, strict=True)}
    units.update(feature_units or {})
    variables = [
        m.LinguisticVariable(
            feature=name, unit=units[name], domain=getattr(var.linguistic_variables[0], "domain", None),
            terms=[_term(s) for s in var.linguistic_variables],
        )
        for name, var in zip(names, rulebase.antecedents, strict=True)
    ]
    first_of_duplicate = {}
    for group in duplicate_groups(rulebase):
        for position in group[1:]:
            first_of_duplicate[position] = group[0]

    summary = {}
    if X_reference is not None:
        values = X_reference[names].to_numpy(dtype=float)
        values = values[np.isfinite(values).all(axis=1)]
        if len(values):
            act = compute_activations(rulebase, values, with_prediction=False)
            summary = {
                "mean_activation": act.raw.mean(axis=0),
                f"activation_frequency_tau{ACTIVATION_TAU:g}": (act.raw >= ACTIVATION_TAU).mean(axis=0),
            }

    compound_labels = compound_terms.load_labels()
    rules = []
    for position, rule in enumerate(rulebase.rules):
        antecedents = [
            a.model_copy(update={"modifier": rule_modifier(rule, f)})
            for f, a in _conditions(rule, rulebase.antecedents, names, compound_labels)
        ]
        value = float(rulebase.scalar_consequents[position])
        text = (
            "IF " + condition_text(antecedents)
            + f" THEN {target}({_valid_time(horizon_hours)}) = {value:.4g} {target_unit}"
        )
        metrics = {"n_antecedents": float(len(antecedents))}
        duplicate_of = None
        if position in first_of_duplicate:
            duplicate_of = ids[first_of_duplicate[position]]
            text += f"  [same antecedents as {duplicate_of}]"
        for key, column in summary.items():
            metrics[key] = float(column[position])
        rules.append(m.RuleDefinition(
            rule_id=ids[position], position=position, antecedents=antecedents,
            consequent=m.Consequent(type="crisp", value=value, unit=target_unit), text=text,
            duplicate_of=duplicate_of, metrics=metrics,
        ))
    return m.ModelRules(
        data_version=data_version, synthetic=synthetic, model_id=model_id, task_id=task_id, domain=domain,
        inference=inference_spec(rulebase), variables=variables, rules=rules,
    )


def export_classifier_rules(
    model,
    *,
    model_id: str,
    task_id: str,
    domain: m.Domain,
    target_label: str,
    target_scheme: m.TargetScheme,
    horizon_hours: int,
    data_version: str,
    synthetic: bool = False,
    feature_units: dict[str, str] | None = None,
    X_reference: pd.DataFrame | None = None,
    rule_metrics: dict[str, Sequence[float]] | None = None,
) -> m.ModelRules:
    """Describe a fitted winning-rule classifier (``FuzzyClassifier`` wrapper or ``MasterRuleBase``).

    Same conventions as ``export_model_rules``: positional rule ids, nothing merged or dropped, terms read from the
    model. Each rule carries its class (``Consequent(type="class", term=label)``) and ``weight`` (the factor that
    multiplies the firing: the dominance score, the evolved weight, or 1.0 when ``rule_weighting == "none"``).
    ``text`` reads ``IF ... THEN <target_label> = <class> (peso <weight>)``. Per-rule ``metrics`` are mean activation
    and activation frequency on ``X_reference`` (a degree of rule match, never a probability). ``rule_metrics`` adds
    named per-rule values (rule order) to ``RuleDefinition.metrics``, e.g. ``dominance_score_raw`` or
    ``selection_frequency`` (AT-041e).

    A mixture of rules (contract v0.7, ``inference='mixture'``) gets the family ``rule_mixture_classifier``: every rule
    carries ``class_weights`` (as fitted), ``class_weights_centred`` and ``strongest_class``, the document carries
    ``class_bias``, ``weight`` is null, ``consequent`` keeps the class the genetic search attached to the rule (search
    and pruning only; it does not enter the prediction) and ``text`` lists the centred weights. ``metrics`` adds
    ``weight_spread`` (max - min of the rule's weights).
    """
    rb = clf_engine.get_master_rulebase(model)
    mixture = mix_engine.is_mixture(model)
    spec = mix_engine.inference_spec(model) if mixture else clf_engine.inference_spec(rb)
    names = clf_engine.feature_names(rb)
    ids = clf_engine.rule_ids(rb)
    labels = [c.label for c in target_scheme.classes]
    classes = clf_engine.rule_classes(rb)
    weights = clf_engine.rule_weights(rb)
    units = {name: getattr(var, "units", None) for name, var in zip(names, rb.antecedents, strict=True)}
    units.update(feature_units or {})
    variables = [
        m.LinguisticVariable(
            feature=name, unit=units[name], domain=getattr(var.linguistic_variables[0], "domain", None),
            terms=[_term(s) for s in var.linguistic_variables],
        )
        for name, var in zip(names, rb.antecedents, strict=True)
    ]
    first_of_duplicate = {}
    for group in clf_engine.duplicate_groups(rb):
        for position in group[1:]:
            first_of_duplicate[position] = group[0]
    summary = {}
    if X_reference is not None:
        values = X_reference[names].to_numpy(dtype=float)
        values = values[np.isfinite(values).all(axis=1)]
        if len(values):
            firing = clf_engine.compute_classifier_activations(rb, values).firing
            summary = {"mean_activation": firing.mean(axis=0),
                       f"activation_frequency_tau{ACTIVATION_TAU:g}": (firing >= ACTIVATION_TAU).mean(axis=0)}
    if mixture:
        fitted = mix_engine.fitted_mixture(model)
        coef, centred = np.asarray(fitted.coef_, dtype=float), mix_engine.centred_weights(fitted.coef_)
        if coef.shape != (len(ids), len(labels)):
            raise ValueError(f"mixture weights {coef.shape} for {len(ids)} rules and {len(labels)} classes")
        mixture_fields = {"class_bias": {c: float(b) for c, b in zip(labels, fitted.intercept_, strict=True)}}
    else:
        mixture_fields = {}
    compound_labels = compound_terms.load_labels()
    rules = []
    for position, rule in enumerate(rb.get_rules()):
        antecedents = [a for _, a in _conditions(rule, rb.antecedents, names, compound_labels)]
        label = labels[classes[position]]
        weight = float(weights[position])
        condition = "IF " + condition_text(antecedents)
        extra = {}
        if mixture:
            strongest = mix_engine.strongest_class(coef[position])
            extra = {"class_weights": {c: float(w) for c, w in zip(labels, coef[position], strict=True)},
                     "class_weights_centred": {c: float(w) for c, w in zip(labels, centred[position], strict=True)},
                     "strongest_class": None if strongest is None else labels[strongest]}
            text = (f"{condition}: {target_label} centred weights (+ supports, - suppresses) "
                    + " | ".join(f"{c} {w:+.2f}" for c, w in zip(labels, centred[position], strict=True)))
        else:
            text = f"{condition} THEN {target_label} = {label}"
            if spec.rule_weighting != "none":
                text += f" (peso {weight:.2g})"
        metrics = {"n_antecedents": float(len(antecedents))}
        if mixture:
            metrics["weight_spread"] = float(coef[position].max() - coef[position].min())
        duplicate_of = None
        if position in first_of_duplicate:
            duplicate_of = ids[first_of_duplicate[position]]
            text += f"  [same antecedents as {duplicate_of}]"
        for key, column in summary.items():
            metrics[key] = float(column[position])
        for key, column in (rule_metrics or {}).items():
            metrics[key] = float(column[position])
        rules.append(m.RuleDefinition(
            rule_id=ids[position], position=position, antecedents=antecedents,
            consequent=m.Consequent(type="class", term=label), text=text, duplicate_of=duplicate_of,
            weight=None if mixture else 1.0 if spec.rule_weighting == "none" else weight, metrics=metrics, **extra,
        ))
    return m.ModelRules(
        data_version=data_version, synthetic=synthetic, model_id=model_id, task_id=task_id, domain=domain,
        inference=spec, target_scheme=target_scheme, variables=variables, rules=rules, **mixture_fields,
    )

