"""The hand-written toy rule base behind ``fixtures/synthetic`` (invented, not trained).

``scripts/make_fixtures.py`` computes the fixtures from it and the mock API reruns it for what-if scenarios, so both
go through the same pinned ex_fuzzy engine. Nothing here is real data.
"""

from __future__ import annotations

import numpy as np
from ex_fuzzy import fuzzy_sets as fs
from ex_fuzzy import rules as exf_rules
from ex_fuzzy.evolutionary_fit_regression import RuleBaseT1Regression

FALLBACK = 35.0

# (feature, unit, domain, {term: trapezoid params})
VARIABLES = [
    ("no2_t", "ug/m3", [0.0, 200.0], {
        "Low": [0.0, 0.0, 20.0, 40.0], "Medium": [20.0, 40.0, 60.0, 80.0], "High": [60.0, 80.0, 200.0, 200.0],
    }),
    ("wind_speed_t", "m/s", [0.0, 20.0], {
        "Low": [0.0, 0.0, 1.5, 3.0], "Medium": [1.5, 3.0, 4.5, 6.0], "High": [4.5, 6.0, 20.0, 20.0],
    }),
]
# (rule_id, {feature: term}, crisp consequent in ug/m3)
RULES = [
    ("R01", {"no2_t": "High", "wind_speed_t": "Low"}, 72.0),
    ("R02", {"no2_t": "Medium"}, 44.0),
    ("R03", {"wind_speed_t": "High"}, 18.0),
]


def build_rulebase() -> RuleBaseT1Regression:
    variables = [
        fs.fuzzyVariable(name, [fs.FS(t, p, domain) for t, p in terms.items()], units=unit)
        for name, unit, domain, terms in VARIABLES
    ]
    names = [v[0] for v in VARIABLES]
    term_names = [list(v[3]) for v in VARIABLES]
    rule_list = []
    for _, antecedents, _ in RULES:
        idx = [term_names[i].index(antecedents[f]) if f in antecedents else -1 for i, f in enumerate(names)]
        rule_list.append(exf_rules.RuleSimple(idx, consequent=0))
    consequents = np.array([c for _, _, c in RULES])
    return RuleBaseT1Regression(variables, rule_list, consequents, y_mean=FALLBACK, tnorm=np.prod)
