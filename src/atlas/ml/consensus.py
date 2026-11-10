"""Consensus rules by stability selection (Meinshausen and Buehlmann 2010) for winning-rule classifiers (AT-041e).

Several classifiers are fitted on different training samples with different seeds, all with the *same* linguistic
variables. A rule is identified by its antecedent set (sorted ``(feature, term)`` pairs) and its class. Its
``selection_frequency`` is the share of the fits whose final rule base contains it. The consensus rule base keeps the
rules whose frequency is at least ``pi``; it is assembled with ex_fuzzy's public classes (``RuleSimple``,
``RuleBaseT1``, ``MasterRuleBase``) and its weights are recomputed by the library afterwards (``calibration.rescore``).

A frequency is a count of fits, not a probability of the rule being "true". With a rule space this large two fits
rarely contain the identical rule, so the consensus is expected to be short and made of simple rules.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Sequence

import numpy as np
from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier
from ex_fuzzy.rules import MasterRuleBase, RuleBaseT1, RuleSimple

from atlas.explain.classifier import get_master_rulebase
from atlas.ml.evaluation import classifier_rule_sets
from atlas.ml.exfuzzy_features import condition_labels
from atlas.ml.fuzzy_classifier import FuzzyClassifier

RuleKey = tuple[tuple[tuple[str, str], ...], str]  # (sorted (feature, term) pairs, class label)


def selection_frequencies(rule_sets: Sequence[Sequence[RuleKey]]) -> dict[RuleKey, float]:
    """Share of the fits that contain each rule (a rule repeated inside one fit counts once)."""
    n = len(rule_sets)
    if n == 0:
        raise ValueError("no fits")
    counts = Counter(key for rules in rule_sets for key in set(rules))
    return {key: count / n for key, count in counts.items()}


def consensus_keys(frequencies: dict[RuleKey, float], pi: float) -> list[RuleKey]:
    """Rules with frequency >= ``pi``, ordered by class label, then decreasing frequency, then antecedent text."""
    if not 0.0 < pi <= 1.0:
        raise ValueError("pi must be in (0, 1]")
    # the epsilon absorbs count / n float noise (e.g. 3 / 10 against pi = 0.3)
    keep = [k for k, f in frequencies.items() if f >= pi - 1e-12]
    return sorted(keep, key=lambda k: (k[1], -frequencies[k], k[0]))


def jaccard(a: Sequence[RuleKey], b: Sequence[RuleKey]) -> float:
    """Jaccard index of two rule sets (1.0 when both are empty)."""
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def pairwise_jaccard(rule_sets: Sequence[Sequence[RuleKey]]) -> list[float]:
    return [jaccard(rule_sets[i], rule_sets[j]) for i in range(len(rule_sets)) for j in range(i + 1, len(rule_sets))]


def build_consensus_model(template: FuzzyClassifier, keys: Sequence[RuleKey],
                          frequencies: dict[RuleKey, float]) -> FuzzyClassifier:
    """A ``FuzzyClassifier`` whose rule base holds exactly ``keys`` (in the order given).

    The variables (terms, units) are taken from ``template``, a fitted classifier of the pool; rules are put in the rule
    base of their class (all classes get a possibly empty rule base). Scores are *not* set here: call
    ``calibration.rescore`` afterwards. Each rule carries ``selection_frequency``.
    """
    rb_template = get_master_rulebase(template)
    antecedents = copy.deepcopy(rb_template.antecedents)
    names = [str(v.name) for v in antecedents]
    term_index = [{t: i for i, t in enumerate(condition_labels(v))} for v in antecedents]  # a code per condition
    labels = list(template.class_labels)
    per_class: list[list[RuleSimple]] = [[] for _ in labels]
    for antecedent_set, label in keys:
        indexes = [-1] * len(names)
        for feature, term in antecedent_set:
            indexes[names.index(feature)] = term_index[names.index(feature)][term]
        c = labels.index(label)
        rule = RuleSimple(indexes, consequent=c)
        rule.selection_frequency = float(frequencies[(antecedent_set, label)])
        per_class[c].append(rule)
    tnorm = rb_template.rule_bases[0].tnorm
    master = MasterRuleBase([RuleBaseT1(antecedents, rules, tnorm=tnorm) for rules in per_class], labels,
                            ds_mode=0, allow_unknown=True)
    return wrap_master_rulebase(master, template)


def wrap_master_rulebase(master: MasterRuleBase, template: FuzzyClassifier) -> FuzzyClassifier:
    """A ``FuzzyClassifier`` (same ``predict(DataFrame)`` and ``rule_base`` as a fitted one) around ``master``."""
    p = template.params
    estimator = BaseFuzzyRulesClassifier(
        nRules=max(len(master.get_rules()), 1), nAnts=p.nAnts, n_linguistic_variables=p.n_linguistic_variables,
        linguistic_variables=list(master.antecedents), class_names=list(template.class_labels), tolerance=p.tolerance,
        ds_mode=0, allow_unknown=True, backend=p.backend, **p.ordinal_options())
    estimator.load_master_rule_base(master)
    out = FuzzyClassifier(p, template.feature_units)
    out.estimator, out.feature_names, out.class_labels, out.seed = estimator, list(template.feature_names), \
        list(template.class_labels), None
    return out


def pool_rule_sets(models: Sequence[FuzzyClassifier], class_labels: Sequence[str]) -> list[list[RuleKey]]:
    return [classifier_rule_sets(m, class_labels) for m in models]


def check_same_variables(models: Sequence[FuzzyClassifier]) -> None:
    """Rules of different fits are comparable only if the variables, terms and membership parameters are the same."""
    def spec(m):
        return [(str(v.name), tuple((str(t.name), tuple(float(p) for p in t.membership_parameters))
                                    for t in v.linguistic_variables))
                for v in get_master_rulebase(m).antecedents]
    first = spec(models[0])
    if any(spec(m) != first for m in models[1:]):
        raise ValueError("the fits do not share linguistic variables and terms")


def best_of(scores: Sequence[float], k: int) -> int:
    """Index of the best score among the first ``k`` fits (ties: the earliest)."""
    return int(np.argmax(np.asarray(scores[:k], dtype=float)))


__all__ = ["RuleKey", "selection_frequencies", "consensus_keys", "jaccard", "pairwise_jaccard",
           "build_consensus_model", "wrap_master_rulebase", "pool_rule_sets", "check_same_variables", "best_of"]
