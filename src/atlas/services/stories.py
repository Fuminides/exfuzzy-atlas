"""Rule Stories (MAP_EXPERIENCE section 8): deterministic, template-built statements about rule activations.

No language model is involved. Every story states a count that a client can reproduce by itself: ``queries`` are
the exact ``rule-map`` / ``rule-territories`` requests and ``checks`` say which count over their features gives which
number. Stories describe activations (a degree of match with the inputs) and never causes, probabilities or
contributions to a prediction.

Kinds and scores (all in [0, 1]; ``SCORE_DEFINITION`` is served with the response):

* ``co_activation_burst`` (regular issue-time grids only): at each issue time a rule has ``share = n_active /
  n_reporting`` (entities with firing >= tau over entities with all inputs present; ``n_reporting >= 3``). A burst is
  a run of at least 3 consecutive steps with ``n_active >= 2`` and ``share >= max(0.25, 2 x baseline)``, where the
  baseline is the rule's mean share over the window; runs longer than 72 steps are regimes, not bursts. Score =
  ``peak_share x (1 - baseline) x min(1, hours / 12)``. One burst per rule (the best).
* ``localized_rule``: a rule with ``activation_frequency >= 0.10`` in only ``k`` entities, ``1 <= k <= n / 4``
  (``n >= 4`` entities with valid records). Score = ``0.8 x (1 - k / n) x mean frequency of those k``.
* ``territory_leader``: the rule that is the ``mean_activation`` dominant rule in most entities (at least 2).
  Score = ``0.5 x entities led / n``.

Ranking is by score, then by kind and rule position, so the order is deterministic. The score orders what to show;
it is not a statistical test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import pandas as pd

from atlas.contracts import models as m

MIN_ENTITIES = 3
MIN_RUN_STEPS = 3
MAX_RUN_STEPS = 72
MIN_SHARE = 0.25
LOCALIZED_MIN_FREQUENCY = 0.10
LOCALIZED_MAX_SHARE = 0.25
SCORE_DEFINITION = (
    "co_activation_burst: peak_share x (1 - baseline_share) x min(1, hours / 12); localized_rule: 0.8 x (1 - k / n) x "
    "mean frequency of the k entities; territory_leader: 0.5 x entities_led / n. Ordering heuristic, not a statistical "
    "test and not a probability. Ties: kind order, then lowest rule position."
)
STEP_COLUMNS = ["rule_id", "issued_at_utc", "n_reporting", "n_active"]
_KIND_ORDER = {m.StoryKind.CO_ACTIVATION_BURST: 0, m.StoryKind.LOCALIZED_RULE: 1, m.StoryKind.TERRITORY_LEADER: 2}
_NOUNS = {m.Domain.AIR: "estaciones", m.Domain.WATER: "puntos de muestreo", m.Domain.MOBILITY: "zonas"}


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _fmt(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M")


def _map_query(model_id, rule_id, metric, tau=None, time=None, start=None, end=None) -> m.StoryQuery:
    params = {"model_id": model_id, "rule_id": rule_id, "metric": metric}
    if time is not None:
        params["time"] = iso(time)
    else:
        params.update({"from": iso(start), "to": iso(end)})
    if tau is not None:
        params["tau"] = f"{tau:g}"
    return m.StoryQuery(path="/api/v1/rule-map", params=params)


def build_stories(
    *, model_id: str, data_version: str, synthetic: bool, domain: m.Domain, rule_ids: Sequence[str],
    territories: m.RuleTerritoriesResponse, step_stats: pd.DataFrame | None, step_hours: int,
    entity_names: Mapping[str, str], start: datetime, end: datetime, tau: float, limit: int,
) -> m.RuleStoriesResponse:
    """Ranked stories. ``step_stats`` (``STEP_COLUMNS``) is None for irregular tasks, which have no bursts."""
    noun = _NOUNS[domain]
    found = []
    if step_stats is not None:
        found += _bursts(model_id, rule_ids, step_stats, step_hours, noun, start, end, tau)
    valid = [f.properties for f in territories.features if f.properties.n_valid > 0]
    found += _localized(model_id, rule_ids, valid, entity_names, noun, start, end, tau)
    found += _leader(model_id, rule_ids, valid, noun, start, end, tau)
    position = {rule_id: i for i, rule_id in enumerate(rule_ids)}
    found.sort(key=lambda s: (-s.score, _KIND_ORDER[s.kind], position[s.rule_id]))
    return m.RuleStoriesResponse(
        data_version=data_version, synthetic=synthetic, model_id=model_id, time_from_utc=start, time_to_utc=end,
        tau=tau, limit=limit, n_candidates=len(found), score_definition=SCORE_DEFINITION, stories=found[:limit],
    )


def _bursts(model_id, rule_ids, step_stats, step_hours, noun, start, end, tau) -> list[m.RuleStory]:
    stories = []
    step = timedelta(hours=step_hours)
    for rule_id in rule_ids:
        rows = step_stats[step_stats["rule_id"] == rule_id].sort_values("issued_at_utc")
        rows = rows[rows["n_reporting"] >= MIN_ENTITIES]
        if rows.empty:
            continue
        share = rows["n_active"] / rows["n_reporting"]
        baseline = float(share.mean())
        threshold = max(MIN_SHARE, 2 * baseline)
        hot = ((share >= threshold) & (rows["n_active"] >= 2)).tolist()
        times = [t.to_pydatetime() for t in rows["issued_at_utc"]]
        best, run = None, []
        for index, (t, flag) in enumerate([*zip(times, hot, strict=True), (None, False)]):
            if flag and (not run or t - times[run[-1]] == step):
                run.append(index)
                continue
            if MIN_RUN_STEPS <= len(run) <= MAX_RUN_STEPS:
                score = _burst_score(rows, share, run, baseline, step_hours)
                if best is None or score > best[0]:
                    best = (score, run)
            run = [index] if flag else []
        if best is not None:
            stories.append(_burst_story(model_id, rule_id, rows, best, baseline, step, step_hours, noun, tau))
    return stories


def _burst_score(rows, share, run, baseline, step_hours) -> float:
    peak = float(share.iloc[run].max())
    return peak * (1 - baseline) * min(1.0, len(run) * step_hours / 12)


def _burst_story(model_id, rule_id, rows, best, baseline, step, step_hours, noun, tau) -> m.RuleStory:
    score, run = best
    steps = rows.iloc[run]
    peak = int((steps["n_active"] / steps["n_reporting"]).to_numpy().argmax())
    n_active, n_reporting = int(steps["n_active"].iloc[peak]), int(steps["n_reporting"].iloc[peak])
    times = [t.to_pydatetime() for t in steps["issued_at_utc"]]
    hours = len(run) * step_hours
    queries = [_map_query(model_id, rule_id, "firing_strength", time=t) for t in times]
    checks = []
    for i, (_, row) in enumerate(steps.iterrows()):
        checks.append(m.StoryCheck(query=i, property="value", op="gte", operand=tau, expected=int(row["n_active"])))
        checks.append(m.StoryCheck(query=i, property="value", op="not_null", expected=int(row["n_reporting"])))
    text = (
        f"{rule_id} superó τ={tau:g} en {n_active} de {n_reporting} {noun} a la vez (máximo), durante {hours} h "
        f"seguidas: emisiones del {_fmt(times[0])} al {_fmt(times[-1])} UTC."
    )
    return m.RuleStory(
        story_id=f"{m.StoryKind.CO_ACTIVATION_BURST.value}:{rule_id}:{iso(times[0])}",
        kind=m.StoryKind.CO_ACTIVATION_BURST, rule_id=rule_id, text=text, score=round(min(1.0, score), 6),
        numbers={
            "tau": tau, "n_active_at_peak": n_active, "n_reporting_at_peak": n_reporting,
            "peak_time_utc": iso(times[peak]),
            "steps": len(run), "hours": hours, "first_issue_utc": iso(times[0]), "last_issue_utc": iso(times[-1]),
            "baseline_share": round(baseline, 6),
        },
        queries=queries, checks=checks,
    )


def _localized(model_id, rule_id_list, valid, entity_names, noun, start, end, tau) -> list[m.RuleStory]:
    n = len(valid)
    if n < 4:
        return []
    stories = []
    for r, rule_id in enumerate(rule_id_list):
        freq = [(p.entity_id, p.rules[r].activation_frequency) for p in valid]
        hot = [(eid, f) for eid, f in freq if f >= LOCALIZED_MIN_FREQUENCY]
        k = len(hot)
        if not 1 <= k <= max(1, int(n * LOCALIZED_MAX_SHARE)):
            continue
        mean_freq = sum(f for _, f in hot) / k
        score = 0.8 * (1 - k / n) * mean_freq
        names = [entity_names.get(eid, eid) for eid, _ in hot]
        shown = ", ".join(names[:5]) + (", …" if k > 5 else "")
        text = (
            f"{rule_id} superó τ={tau:g} en al menos el {round(LOCALIZED_MIN_FREQUENCY * 100):d} % de los registros "
            f"válidos solo en {k} de {n} {noun} ({shown}) entre {_fmt(start)} y {_fmt(end)} UTC."
        )
        stories.append(m.RuleStory(
            story_id=f"{m.StoryKind.LOCALIZED_RULE.value}:{rule_id}:{iso(start)}",
            kind=m.StoryKind.LOCALIZED_RULE, rule_id=rule_id, text=text, score=round(min(1.0, score), 6),
            numbers={"tau": tau, "min_frequency": LOCALIZED_MIN_FREQUENCY, "k": k, "n": n,
                     "entity_ids": ",".join(eid for eid, _ in hot)},
            queries=[_map_query(model_id, rule_id, "activation_frequency", tau=tau, start=start, end=end)],
            checks=[
                m.StoryCheck(query=0, property="value", op="gte", operand=LOCALIZED_MIN_FREQUENCY, expected=k),
                m.StoryCheck(query=0, property="n_valid", op="gte", operand=1, expected=n),
            ],
        ))
    return stories


def _leader(model_id, rule_ids, valid, noun, start, end, tau) -> list[m.RuleStory]:
    n = len(valid)
    led = {rule_id: 0 for rule_id in rule_ids}
    for p in valid:
        if p.dominant_rule_id is not None:
            led[p.dominant_rule_id] += 1
    if not led:
        return []
    rule_id = max(rule_ids, key=lambda r: (led[r], -rule_ids.index(r)))
    k = led[rule_id]
    if k < 2:
        return []
    text = (
        f"{rule_id} es la regla con mayor activación media en {k} de {n} {noun} entre {_fmt(start)} y {_fmt(end)} UTC "
        "(activación media; no es la contribución a la predicción)."
    )
    query = m.StoryQuery(path="/api/v1/rule-territories", params={
        "model_id": model_id, "measure": m.TerritoryMeasure.MEAN_ACTIVATION.value, "tau": f"{tau:g}",
        "from": iso(start), "to": iso(end),
    })
    return [m.RuleStory(
        story_id=f"{m.StoryKind.TERRITORY_LEADER.value}:{rule_id}:{iso(start)}",
        kind=m.StoryKind.TERRITORY_LEADER, rule_id=rule_id, text=text, score=round(min(1.0, 0.5 * k / n), 6),
        numbers={"tau": tau, "entities_led": k, "n": n, "measure": m.TerritoryMeasure.MEAN_ACTIVATION.value},
        queries=[query],
        checks=[
            m.StoryCheck(query=0, property="dominant_rule_id", op="eq", operand=rule_id, expected=k),
            m.StoryCheck(query=0, property="n_valid", op="gte", operand=1, expected=n),
        ],
    )]
