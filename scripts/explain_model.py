"""Write the explanation of one published model's rule base, in Spanish and English, with Claude (contract v0.6.2).

The text is what Atlas shows above the rules in Patrones (``GET /api/v1/models/{model_id}/explanation``). It is
written by Claude, called headless through the Claude Code CLI, from ``configs/explanations/TEMPLATE.md`` and a
``CONTEXT`` JSON that this script builds **only** from the model's published files (rules.json, importance.json,
card.json, summary.json and registry.json). Every number in the context carries the string it may be written as
(``display``: «0,41» / "0.41", «24 %» / "24%"), and the comparison with the baselines is the web's Performance report
(``apps/web/src/lib/performance.ts``) with its standing already computed.

The answer is checked before it is saved: the output schema and the template's length limits, the wording audit
(``scripts/qa/wording_audit.py`` and the web's wording guards for Patrones), every number against the ``display``
values of the context (±1 in the last shown digit), and every rule id against the model. On a failure Claude is
asked once more with the errors; if that fails too nothing is written and the exit code is 1.

Usage::

    python scripts/explain_model.py --model-id exfuzzy-madrid_no2_h6-ica4-yday-seed1           # writes the file
    python scripts/explain_model.py --model-id <id> --dry-run                                   # prints the prompt
    python scripts/explain_model.py --model-id <id> --model opus --published-dir <dir> --out-dir <dir>

The file is ``configs/explanations/<model_id>.json`` with ``reviewed: false``: a person reads it before it is
marked reviewed. Regenerate it (never edit its numbers by hand) whenever the model is republished:
``tests/integration/test_explanations.py`` fails when ``input_sha256`` no longer matches the published files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "qa"))

import wording_audit as wa  # noqa: E402

from atlas.contracts import models as m  # noqa: E402

TEMPLATE = REPO / "configs" / "explanations" / "TEMPLATE.md"
OUT_DIR = REPO / "configs" / "explanations"
PUBLISHED = REPO / "artifacts" / "published"
ATTEMPTS = 2  # the first answer and one retry with the validator's errors
MIXTURE = m.InferenceFamily.RULE_MIXTURE_CLASSIFIER.value
SUPPORTED_FAMILIES = {m.InferenceFamily.WINNING_RULE_CLASSIFIER.value, m.InferenceFamily.TSK_ZERO_ORDER.value, MIXTURE}

# The template's limits ("What to write").
HEADLINE_WORDS = 25
SUMMARY_PARAGRAPHS = (2, 3)
PARAGRAPH_WORDS = 70
POINTS = (3, 5)
POINT_WORDS = 25

# ------------------------------------------------------------------------------------------------ number formats
# The web's lib/format.ts: comma decimals and a thin space before "%" in Spanish, point and no space in English.

THIN = " "
_UNITS = {"ug/m3": "µg/m³", "degC": "°C"}
_MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}


def _dec(value: float, digits: int, lang: str) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if lang == "es" else text


def _pct(share: float, lang: str) -> str:
    """lib/format.ts ``pct``: 74 % from 10 %, 2,6 % below, <0,1 % for a share that is not 0 but rounds to it.

    One addition at the top: a share below 1 is never written "100 %" (99,8 %, or >99,9 %), so a text cannot say that
    three rules decide every prediction when others decide a few."""
    sp = THIN if lang == "es" else ""
    v = share * 100
    if v == 0:
        return f"0{sp}%"
    if v < 0.05:
        return f"<{_dec(0.1, 1, lang)}{sp}%"
    if 99.5 <= v < 100:
        return f"{_dec(v, 1, lang)}{sp}%" if v < 99.95 else f">{_dec(99.9, 1, lang)}{sp}%"
    return f"{_dec(v, 0 if v >= 10 else 1, lang)}{sp}%"


def _unit(unit: str | None) -> str:
    return _UNITS.get(unit or "", unit or "")


def share(value: float) -> dict:
    return {"value": round(value, 4), "display": {lang: _pct(value, lang) for lang in ("es", "en")}}


def score(value: float) -> dict:
    """Macro-F1 (and any 0-1 score shown as a decimal): two decimals, as the Performance report."""
    return {"value": round(value, 4), "display": {lang: _dec(value, 2, lang) for lang in ("es", "en")}}


def amount(value: float, unit: str | None, digits: int = 2) -> dict:
    u = _unit(unit)
    return {"value": round(value, 4),
            "display": {lang: f"{_dec(value, digits, lang)}{THIN if u else ''}{u}" for lang in ("es", "en")}}


def signed(value: float) -> dict:
    """A centred weight: two decimals with its sign (a real minus), so a reader sees support (+) and suppression (−)."""
    def text(lang: str) -> str:
        shown = _dec(abs(value), 2, lang)
        if round(abs(value), 2) == 0:
            return shown
        return f"{'+' if value > 0 else '−'}{shown}"
    return {"value": round(value, 4), "display": {lang: text(lang) for lang in ("es", "en")}}


def count(value: int) -> dict:
    return {"value": int(value), "display": {"es": str(int(value)), "en": str(int(value))}}


def mean(value: float) -> dict:
    return {"value": round(value, 4), "display": {lang: _dec(value, 1, lang) for lang in ("es", "en")}}


def _date(day: datetime, lang: str) -> str:
    month = _MONTHS[lang][day.month - 1]
    return f"{day.day} de {month} de {day.year}" if lang == "es" else f"{day.day} {month} {day.year}"


def period(start_utc: str, end_utc: str, zone: str | None = None) -> dict:
    """A period by its first and last day; a whole calendar year is just the year. ``end_utc`` is exclusive.

    Boundaries at midnight UTC are dated in UTC; others (NYC's splits are New York midnights, 05:00Z) in ``zone``, the
    task's time zone, so the last day is the one a local reader would name."""
    start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    if zone and not all((t.hour, t.minute, t.second) == (0, 0, 0) for t in (start, end)):
        start, end = start.astimezone(ZoneInfo(zone)), end.astimezone(ZoneInfo(zone))
    last = end - timedelta(microseconds=1)
    if (start.month, start.day) == (1, 1) and (last.month, last.day) == (12, 31) and start.year == last.year:
        return {"display": {"es": str(start.year), "en": str(start.year)}}
    return {"display": {"es": f"del {_date(start, 'es')} al {_date(last, 'es')}",
                        "en": f"{_date(start, 'en')} to {_date(last, 'en')}"}}


# ------------------------------------------------------------------------------------------------- the context


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _named(es: str | None, en: str | None) -> dict:
    """A display name in both languages; a missing English name keeps the Spanish one (the web's ``localized``)."""
    return {"label": es, "label_en": en or es}


_GENERIC_TERMS = {"low": ("baja", "low"), "medium": ("media", "medium"), "high": ("alta", "high")}


def _class_names(c: dict) -> dict:
    es = c.get("display_label") or c["label"]
    return _named(es, c.get("display_label_en"))


def _term_names(term: dict, classes: dict[str, dict]) -> dict:
    """lib/labels.ts ``namesFor``: the term's own label, else the class it names, else the generic low/medium/high."""
    generic = _GENERIC_TERMS.get(term["name"].lower(), (term["name"], term["name"]))
    cls = classes.get(term["name"])
    es = term.get("label") or (cls["label"] if cls else None) or generic[0]
    en = term.get("label_en") or term.get("label") or (cls["label_en"] if cls else None) or generic[1]
    return {"label": es, "label_en": en}


def _variable_names(v: dict) -> dict:
    """lib/labels.ts ``labelerFor``: the published label, without "(h)" for an hour of the day."""
    def tidy(text: str | None) -> str | None:
        return re.sub(r"\s*\(h\)$", "", text) if text and v.get("unit") in ("h", "hour") else text
    es = tidy(v.get("label")) or v["feature"]
    return {"label": es, "label_en": tidy(v.get("label_en")) or es}


def _condition(a: dict, variables: dict, term_names: dict) -> dict:
    """One condition of a rule's ``if``. A plain term (``is``) is written as it always was, so the context of a model
    without ordinal or compound conditions does not change. ``at_least`` / ``at_most`` (contract v0.8) add the
    ``operator`` (the term is the threshold) and ``covers`` (every term the condition holds for, low to high); a
    compound (``any_of``) is named by its display name and ``covers`` the terms it unites."""
    item = {"variable": a["feature"], **_variable_names(variables[a["feature"]])}
    operator = a.get("operator", "is")
    if operator == "is":
        return {**item, "term": {"name": a["term"], **term_names[(a["feature"], a["term"])]}}
    covers = [{"name": t, **term_names[(a["feature"], t)]} for t in a["terms"]]
    if operator == "any_of":
        return {**item, "operator": operator,
                "term": {"name": a["term"], **_named(a.get("label") or a["term"], a.get("label_en") or a["term"])},
                "covers": covers}
    return {**item, "operator": operator, "term": {"name": a["term"], **term_names[(a["feature"], a["term"])]},
            "covers": covers}


def _bar_names(key: str, classifier: bool) -> dict:
    """lib/performance.ts ``barLabel``."""
    names = {
        "persistence": ("Repetir la última categoría", "Repeat the last category") if classifier
        else ("Repetir el último valor", "Repeat the last value"),
        "persistence_24h": ("Repetir la de ayer a la misma hora", "Repeat yesterday's, same hour") if classifier
        else ("Repetir el de ayer a la misma hora", "Repeat yesterday's, same hour"),
        # model families keep their technical (English) name in both languages, as in the web (#104)
        "linear": ("Logistic regression", "Logistic regression") if classifier
        else ("Linear regression", "Linear regression"),
        "forest": ("Random forest", "Random forest"),
    }[key]
    return {"label": names[0], "label_en": names[1]}


def _metric_value(rows: list[dict], estimator: str, metric: str, slice_: str) -> float | None:
    for r in rows:
        if r["estimator"] == estimator and r["metric"] == metric and (r.get("slice") or "all") == slice_:
            return r["value"]
    return None


def _pick_variant(rows: list[dict], prefix: str, selection: str) -> str | None:
    """lib/performance.ts ``pickVariant``: the variant of a baseline family that scored best on VALIDATION."""
    higher = selection == "macro_f1"
    candidates = []
    for e in dict.fromkeys(r["estimator"] for r in rows):
        if re.match(prefix, e):
            v = _metric_value(rows, e, selection, "validation/all")
            if v is not None:
                candidates.append((-v if higher else v, e))
    return min(candidates)[1] if candidates else None


def _standing(model: float, other: float, higher_is_better: bool) -> str:
    """lib/performance.ts ``standing``: within 0.01 (or 1 % of the error) is a tie."""
    tol = 0.01 if higher_is_better else 0.01 * abs(other)
    if abs(model - other) < tol:
        return "on a par"
    return "better" if (model > other) == higher_is_better else "worse"


def performance(card: dict, unit: str | None, zone: str | None = None) -> dict | None:
    """The web's Performance report: ExFuzzy against the standard baselines on the test period, nothing recomputed."""
    rows = [r for r in (card.get("metrics") or {}).get("rows", [])
            if (r.get("slice") or "all") in ("all", "validation/all")]
    classifier = card.get("target_scheme") is not None
    selection = "macro_f1" if classifier else "mae"
    metrics = ["macro_f1", "accuracy"] if classifier else ["mae"]
    own = next((e for e in dict.fromkeys(r["estimator"] for r in rows) if e.startswith("exfuzzy")), None)
    if own is None:
        return None
    fmt = {"macro_f1": score, "accuracy": share, "mae": lambda v: amount(v, unit)}
    model = {"estimator": own,
             **{k: fmt[k](v) for k in metrics if (v := _metric_value(rows, own, k, "all")) is not None}}
    if len(model) == 1:
        return None
    wanted = [
        ("persistence", "persistence"),
        ("persistence_24h", "persistence_24h"),
        ("linear", _pick_variant(rows, r"^logistic_regression" if classifier else r"^(ridge|linear)", selection)),
        ("forest", _pick_variant(rows, r"^random_forest", selection)),
    ]
    baselines = []
    for key, estimator in wanted:
        if estimator is None:
            continue
        entry: dict = {"key": key, **_bar_names(key, classifier), "estimator": estimator,
                       "trivial": key in ("persistence", "persistence_24h")}
        for k in metrics:
            v = _metric_value(rows, estimator, k, "all")
            mine = _metric_value(rows, own, k, "all")
            if v is not None and mine is not None:
                entry[k] = {**fmt[k](v), "standing": _standing(mine, v, k != "mae")}
        if any(k in entry for k in metrics):
            baselines.append(entry)
    split = card["manifest"]["split"]
    return {
        "period": period(split["test_from_utc"], split["test_to_utc"], zone),
        "metrics": metrics,
        # the names the web uses (apps/web/src/i18n/GLOSSARY.md)
        "metric_names": {k: {"macro_f1": _named("F1 macro", "macro-F1"), "accuracy": _named("acierto", "accuracy"),
                             "mae": _named("error medio absoluto", "mean absolute error")}[k] for k in metrics},
        "higher_is_better": classifier,
        "selection_note": "The logistic or linear regression and the random forest are the variants that scored best "
        "on the validation period; every value is on the test period, on the same predictions. "
        "`standing` says how ExFuzzy stands against each baseline: better, on a par (within 0.01, or 1% of the error) "
        "or worse.",
        "model": model,
        "baselines": baselines,
    }


def build_context(published: Path, model_id: str) -> dict:
    """The CONTEXT of the template, from the model's published files only."""
    registry = _read(published / "registry.json")["tasks"]
    served = [(t, e) for t, e in registry.items() if e["model_id"] == model_id]
    if not served:
        raise SystemExit(f"{model_id} is not served in {published / 'registry.json'}")
    task_id, entry = served[0]
    model_dir = published / model_id
    rules = _read(model_dir / "rules.json")
    card = _read(model_dir / "card.json")
    imp_path = model_dir / "importance.json"
    if not imp_path.is_file():
        raise SystemExit(f"{model_id} has no importance.json (published before contract v0.5): "
                         "run atlas.services.enrich")
    imp = _read(imp_path)
    summary = _read(model_dir / "summary.json") if (model_dir / "summary.json").is_file() else None

    inference = rules["inference"]
    if inference["family"] not in SUPPORTED_FAMILIES:
        raise SystemExit(f"{model_id}: inference family {inference['family']!r} is not supported yet "
                         f"(build_context reads {sorted(SUPPORTED_FAMILIES)})")
    mixture = inference["family"] == MIXTURE
    classifier = mixture or inference["family"] == m.InferenceFamily.WINNING_RULE_CLASSIFIER.value
    scheme = rules.get("target_scheme") if classifier else None
    unit = entry.get("unit")
    classes = {c["label"]: {"key": c["label"], **_class_names(c)} for c in (scheme or {}).get("classes", [])}
    observed = imp.get("observed_class_shares") or {}
    by_rule = {r["rule_id"]: r for r in imp["rules"]}
    by_var = {v["feature"]: v for v in imp["variables"]}

    # the rules, from the one that decides most to the one that decides least (lib/importance.ts rankedRules); in a
    # mixture no rule decides: from the one that is most often the top rule to the one that is least
    rank_key = "top_contributor_share" if mixture else "decided_share"
    order = sorted(range(len(rules["rules"])),
                   key=lambda i: (-(by_rule.get(rules["rules"][i]["rule_id"], {}).get(rank_key) or 0), i))
    variables = {v["feature"]: v for v in rules["variables"]}
    term_names = {(v["feature"], t["name"]): _term_names(t, classes) for v in rules["variables"] for t in v["terms"]}
    predicted: dict[str, float] = {}
    rule_list, cumulative = [], 0.0
    for rank, i in enumerate(order, start=1):
        rule = rules["rules"][i]
        stats = by_rule.get(rule["rule_id"], {})
        if mixture:
            rule_list.append(_mixture_rule(rule, stats, rank, variables, term_names, classes))
            continue
        decided = stats.get("decided_share", 0.0)
        cumulative += decided
        item: dict = {
            "rule_id": rule["rule_id"],
            "rank_by_decided_share": rank,
            "if": [_condition(a, variables, term_names) for a in rule["antecedents"]],
        }
        consequent = rule["consequent"]
        if classifier:
            item["then_class"] = classes.get(consequent["term"], {"key": consequent["term"],
                                                                 **_named(consequent["term"], None)})
            predicted[consequent["term"]] = predicted.get(consequent["term"], 0.0) + decided
        elif consequent.get("value") is not None:
            item["then_value"] = amount(consequent["value"], consequent.get("unit") or unit)
        if inference.get("rule_weighting") not in (None, "none") and rule.get("weight") is not None:
            item["weight"] = score(rule["weight"])
        item["decided_share"] = share(decided)
        item["decided_share_of_this_and_higher_ranked_rules"] = share(min(cumulative, 1.0))
        if stats.get("accuracy") is not None:
            item["accuracy"] = share(stats["accuracy"])
        if classifier and consequent["term"] in observed:
            item["base_rate"] = share(observed[consequent["term"]])
        if stats.get("mean_weight_share") is not None:
            item["mean_weight_share"] = share(stats["mean_weight_share"])
        if stats.get("mae") is not None:
            item["mae"] = amount(stats["mae"], unit)
        rule_list.append(item)

    hours = imp["n_predicted"] + imp["n_no_rule"] + imp.get("n_withheld", 0)
    coverage = {}
    if mixture and imp.get("n_no_top_rule") and imp["n_predicted"]:
        coverage["no_top_rule_share_of_predictions"] = share(imp["n_no_top_rule"] / imp["n_predicted"])
        coverage["when_no_rule_supports_the_predicted_category"] = {
            "es": "la categoría gana por su sesgo y por lo que las reglas restan a las demás",
            "en": "the category wins by its bias and by what the rules take away from the other categories"}
    if imp["n_no_rule"] and hours:
        coverage["no_rule_holds_share"] = share(imp["n_no_rule"] / hours)
        coverage["when_no_rule_holds"] = (
            {"es": "el modelo da la media del entrenamiento", "en": "the model gives the training mean"}
            if inference.get("fallback") == "train_target_mean"
            else {"es": "el modelo no da predicción", "en": "the model gives no prediction"})
    if imp.get("n_withheld") and hours:
        coverage["withheld_share"] = share(imp["n_withheld"] / hours)
        coverage["withheld_note"] = {
            "es": "una regla se cumple pero no se publica predicción porque falta el nivel de referencia",
            "en": "a rule holds but no prediction is published: the reference level is missing"}

    horizon = entry["horizon_hours"]
    split = card["manifest"]["split"]
    zone = (summary or {}).get("timezone") or card["manifest"]["hyperparameters"].get("timezone")
    context: dict = {
        "model_id": model_id,
        "data_version": rules["data_version"],
        "task": {
            "task_id": task_id,
            "task_type": entry["task_type"],
            "territory": _named(entry.get("territory_title"), entry.get("territory_title_en")),
            "target": {
                "variable": entry["target"],
                **(_named(summary["label"], summary.get("label_en")) if summary else _named(entry["target"], None)),
                "unit": _unit(unit),
            },
            "horizon": {
                "hours": horizon,
                "display": {"es": "inferencia sobre la misma muestra, no un pronóstico",
                            "en": "inference on the same sample, not a forecast"} if horizon == 0
                else {"es": f"+{horizon} h", "en": f"+{horizon} h"},
            },
            "test_period": period(split["test_from_utc"], split["test_to_utc"], zone),
            "rules_period": period(imp["period_from_utc"], imp["period_to_utc"], zone),
            "rules_period_note": (
                "top_rule_share, decisive_share and accuracy of the rules, and the base_rate of the categories, are "
                "measured over rules_period; performance over test_period." if mixture else
                "decided_share, accuracy, base_rate and mae of the rules are measured over "
                "rules_period; performance over test_period."),
        },
        "inference": {
            "family": inference["family"],
            "tnorm": inference.get("tnorm"),
            **({} if mixture else {"rule_mode": inference.get("rule_mode")}),
            "how_a_prediction_is_made": _how(inference, classifier),
        },
        # a mixture has no rule weighting (its weights are per category): the winning-rule wording would not apply
        **({} if mixture else {"rule_weighting": inference.get("rule_weighting") or "none"}),
        "variables": [
            {"variable": v["feature"], **_variable_names(v),
             "n_rules_using_it": count(by_var[v["feature"]]["n_rules"]) if v["feature"] in by_var else None,
             **(_mixture_variable(by_var.get(v["feature"])) if mixture else
                {"share_of_predictions_decided_by_rules_using_it": share(by_var[v["feature"]]["decided_share"])
                 if v["feature"] in by_var else None}),
             "terms": [{"name": t["name"], **term_names[(v["feature"], t["name"])]} for t in v["terms"]]}
            for v in rules["variables"]
        ],
        "rules": rule_list,
        "model_size": {
            "n_rules": count(len(rules["rules"])),
            "mean_conditions_per_rule": mean(
                sum(len(r["antecedents"]) for r in rules["rules"]) / len(rules["rules"]) if rules["rules"] else 0),
            **({"n_rules_that_are_the_top_rule_at_least_once": count(sum(1 for r in imp["rules"] if r["n_top"] > 0))}
               if mixture else
               {"n_rules_that_decide_at_least_one_prediction": count(
                   sum(1 for r in imp["rules"] if r["n_decided"] > 0))}),
        },
        "performance": performance(card, unit, zone),
    }
    if mixture:
        context["rules_note"] = MIXTURE_RULES_NOTE
    if coverage:
        context["coverage"] = coverage
    if scheme:
        context["target_scheme"] = {
            **_named(scheme["name"], scheme.get("name_en")),
            "short": _named(scheme.get("short_name"), scheme.get("short_name_en")),
            "kind": scheme.get("kind"),
            "classes": [
                {**classes[c["label"]],
                 # an official index describes its classes with health wording: only Atlas's own scheme is described
                 **({"description": _named(c.get("description"), c.get("description_en"))}
                    if scheme.get("kind") != "official_index" and c.get("description") else {}),
                 **({"base_rate": share(observed[c["label"]])} if c["label"] in observed else {}),
                 **({} if mixture else {"predicted_share": share(min(predicted.get(c["label"], 0.0), 1.0))})}
                for c in scheme["classes"]
            ],
            "base_rate_note": (
                "base_rate: how often the class is observed among the predictions with an observation over "
                "rules_period." if mixture else
                "base_rate: how often the class is observed among the predictions with an observation "
                "over rules_period; predicted_share: share of the predictions that are this class."),
        }
    return context


MIXTURE_RULES_NOTE = (
    "Rules are listed from the one that is most often the top rule (top_rule_share) to the one that is least. "
    "class_weights_centred: the rule's weight for each category minus the mean of its weights, so + means the rule "
    "supports the category and − that it suppresses it compared with the other categories. strongest_class: the "
    "category with the largest weight. top_rule_share: the share of the predictions in which this rule adds the most "
    "to the predicted category. decisive_share: the share of the predictions whose category would change without "
    "this rule. accuracy: how often the predicted category is right in the predictions where the rule is the top rule. "
    "Several rules can be decisive for the same prediction, so do not add the shares of different rules.")


def _mixture_variable(stats: dict | None) -> dict:
    return {
        "share_of_predictions_whose_top_rule_uses_it":
            share(stats["top_contributor_share"]) if stats and stats.get("top_contributor_share") is not None else None,
        "share_of_predictions_with_a_decisive_rule_using_it":
            share(stats["decisive_share"]) if stats and stats.get("decisive_share") is not None else None,
    }


def _mixture_rule(rule: dict, stats: dict, rank: int, variables: dict, term_names: dict, classes: dict) -> dict:
    """A rule of a mixture: its centred weights per category and its share as top rule. The ``consequent`` takes no
    part in the prediction (contract v0.7), so it is not given."""
    def named(label: str) -> dict:
        return classes.get(label, {"key": label, **_named(label, None)})
    weights = rule.get("class_weights_centred") or {}
    item: dict = {
        "rule_id": rule["rule_id"],
        "rank_by_top_rule_share": rank,
        "if": [_condition(a, variables, term_names) for a in rule["antecedents"]],
    }
    if rule.get("strongest_class"):
        item["strongest_class"] = named(rule["strongest_class"])
    if weights:
        item["class_weights_centred"] = [{"class": named(c), "weight": signed(w)} for c, w in weights.items()]
        item["supports"] = [named(c) for c, w in weights.items() if round(w, 2) > 0]
        item["suppresses"] = [named(c) for c, w in weights.items() if round(w, 2) < 0]
    for key, source in (("top_rule_share", "top_contributor_share"), ("decisive_share", "decisive_share"),
                        ("accuracy", "accuracy")):
        if stats.get(source) is not None:
            item[key] = share(stats[source])
    return item


def _how(inference: dict, classifier: bool) -> dict:
    if inference["family"] == MIXTURE:
        return {"es": "Cada regla tiene un peso para cada categoría. Las reglas que se cumplen suman su apoyo a cada "
                      "categoría, y se predice la categoría con el total mayor. Ninguna regla decide sola, y los pesos "
                      "de una regla solo tienen sentido junto a los de las demás.",
                "en": "Every rule has a weight for each category. The rules that hold add up their support for each "
                      "category, and the category with the largest total is predicted. No single rule decides, and a "
                      "rule's weights only make sense together with the others."}
    if classifier and (inference.get("rule_weighting") or "none") == "none":
        return {"es": "Cada predicción la decide una sola regla: la que más se cumple; en un empate decide la primera "
                      "en el orden del modelo.",
                "en": "Each prediction is decided by one rule: the one that holds most; a tie goes to the first rule "
                      "in the model's order."}
    if classifier:
        return {"es": "Decide cada predicción la regla cuyo grado de cumplimiento multiplicado por su peso es mayor.",
                "en": "The rule with the highest degree × weight decides each prediction."}
    return {"es": "Cada estimación es un promedio ponderado de los valores de las reglas que se cumplen, según cuánto "
                  "se cumple cada una; el valor de una regla no es el valor observado en las muestras que cubre. Una "
                  "regla «decide» la estimación en la que su parte del promedio es la mayor.",
            "en": "Each estimate is a weighted average of the values of the rules that hold, by how much each holds; "
                  "a rule's value is not the value observed in the samples it covers. A rule “decides” the estimate "
                  "in which its share of the average is the largest."}


def context_sha256(context: dict) -> str:
    canonical = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------- prompt and call


def read_template(path: Path = TEMPLATE) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    found = re.search(r"\(version\s+([\w.]+)\)", text.splitlines()[0])
    if not found:
        raise SystemExit(f"{path}: the first line must say '(version N)'")
    return text, found.group(1)


def build_prompt(template: str, context: dict) -> str:
    return f"{template.rstrip()}\n\n```json\n{json.dumps(context, indent=2, ensure_ascii=False)}\n```\n"


def _language_schema() -> dict:
    text = {"type": "string", "minLength": 1}
    return {
        "type": "object", "additionalProperties": False, "required": ["headline", "summary", "points"],
        "properties": {
            "headline": text,
            "summary": {"type": "array", "items": text, "minItems": SUMMARY_PARAGRAPHS[0],
                        "maxItems": SUMMARY_PARAGRAPHS[1]},
            "points": {"type": "array", "items": text, "minItems": POINTS[0], "maxItems": POINTS[1]},
        },
    }


OUTPUT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["es", "en"],
                 "properties": {"es": _language_schema(), "en": _language_schema()}}


def claude_command(model: str | None) -> list[str]:
    """``claude -p`` headless: structured JSON output, no tools, nothing that can prompt or act, no saved session."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(OUTPUT_SCHEMA),
        "--tools", "",                      # no built-in tool at all: the call can only answer
        "--permission-mode", "dontAsk",     # anything that would need a permission is denied, never asked
        "--permission-prompts", "none",
        "--strict-mcp-config",              # and no MCP servers
        "--safe-mode",                      # no CLAUDE.md, skills, plugins or hooks of this machine
        "--no-session-persistence",
    ]
    return cmd + (["--model", model] if model else [])


def cli_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    return out.split()[0] if out else "unknown"


def call_claude(prompt: str, model: str | None) -> tuple[dict | None, str | None, str]:
    """(the structured answer, the model the CLI reports, an error message or "")."""
    with tempfile.TemporaryDirectory() as cwd:  # an empty working directory: nothing of the repo is in reach
        done = subprocess.run(claude_command(model), input=prompt, capture_output=True, text=True, cwd=cwd,
                              timeout=900)
    if done.returncode != 0:
        return None, None, f"claude exited {done.returncode}: {done.stderr.strip()[-500:]}"
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        return None, None, f"claude did not answer JSON: {done.stdout[-500:]}"
    usage = result.get("modelUsage") or {}
    used = max(usage, key=lambda k: usage[k].get("outputTokens", 0)) if usage else None
    if result.get("is_error") or not isinstance(result.get("structured_output"), dict):
        return None, used, f"claude returned no structured output ({result.get('subtype')}): {result.get('result')}"
    return result["structured_output"], used, ""


# ------------------------------------------------------------------------------------------------- validation

# The web's wording guards of Patrones (App.wording.test.tsx, App.wording.en.test.tsx): stricter than the scanner, a
# negation does not excuse these words, and "activation" belongs to Explorar.
_GUARD = {
    "es": [re.compile(r"probabilidad|riesgo|contribuci[oó]n|causa(?:l|s)?\b|causalidad|certeza|confianza", re.I),
           re.compile(r"importancia[^.]{0,60}activaci[oó]n|activaci[oó]n[^.]{0,60}importancia", re.I),
           re.compile(r"activaci[oó]n", re.I)],
    "en": [re.compile(r"probabilit|risk|contribut|caus(e|al)|certaint|confiden", re.I),
           re.compile(r"importance[^.]{0,60}activation|activation[^.]{0,60}importance", re.I),
           re.compile(r"activation", re.I)],
}
# the baselines' model families are running text here, as in the web's verdict (2026-11-10): «la regresión logística»,
# «la regresión lineal», «el Random Forest» / "logistic regression", "linear regression", "the random forest". The
# capitalised English names are labels (bars, tables) and do not belong in a sentence; at the start of an English
# sentence only "Logistic regression" and "Linear regression" may keep their capital. Spanish keeps "Random Forest"
# (capital F) and never translates it.
_TECHNICAL_FAMILY = {
    "es": re.compile(r"\b(Logistic regression|Linear regression|Random forest)\b|\bbosques? aleatorios?\b", re.I),
    "en": re.compile(r"\b(Logistic regression|Linear regression|Random [Ff]orest)\b"),
}
_MARKETING = re.compile(r"\b(powerful|impressive|remarkable|amazing|potente|impresionante|asombros[oa])\b", re.I)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
# a number not glued to a letter (R02, NO2, h6): integers, decimals with comma or point, percentages, "<0,1 %"
_NUMBER = re.compile(r"(?<![\w.,])([<>]\s?)?(\d+(?:[.,]\d+)?)(\s?%)?(?![\d])")
_RULE_ID = re.compile(r"\bR\d+\b")


def _numbers(text: str) -> list[tuple[str, str, float, int, bool, str]]:
    """(token, '<' or '>' or '', value, decimals, is_percent, separator) of every number in ``text``."""
    out = []
    for match in _NUMBER.finditer(text):
        token = match.group(2)
        sep = "," if "," in token else "." if "." in token else ""
        decimals = len(token.split(sep)[1]) if sep else 0
        out.append((match.group(0).strip(), (match.group(1) or "").strip(), float(token.replace(",", ".")), decimals,
                    bool(match.group(3)), sep))
    return out


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, int) and not isinstance(node, bool):
        yield str(node)  # a rank, the horizon in hours
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _allowed_numbers(context: dict) -> set[tuple[str, float, int, bool]]:
    """Every number written in the context: its strings (``display`` values, labels, periods) and its integers."""
    return {(lt, round(v, 6), d, p) for s in _strings(context) for _, lt, v, d, p, _ in _numbers(s)}


def _number_ok(lt: str, value: float, decimals: int, percent: bool, allowed) -> bool:
    for a_lt, a_value, a_dec, a_pct in allowed:
        if (a_lt, a_dec, a_pct) != (lt, decimals, percent):
            continue
        # ±1 in the last shown digit for a share or a decimal; a plain integer (a count, a year, hours) is exact
        tolerance = 10 ** -decimals if (percent or decimals) else 0
        if abs(value - a_value) <= tolerance + 1e-9:
            return True
    return False


def typeset(texts: dict) -> dict:
    """Spanish typography of the web: a narrow no-break space before "%" ("46 %" never wraps before the sign)."""
    def fix(text: str) -> str:
        return re.sub(r"(\d)[ \u00a0]%", "\\1" + THIN + "%", text)
    es = texts.get("es") if isinstance(texts, dict) else None
    if not isinstance(es, dict):
        return texts
    fixed = {k: (fix(v) if isinstance(v, str) else [fix(x) if isinstance(x, str) else x for x in v]
                 if isinstance(v, list) else v) for k, v in es.items()}
    return {**texts, "es": fixed}


def _words(text: str) -> int:
    """Words as a reader counts them: a lone "%" or dash (the thin space of «84 %» splits it off) is not a word."""
    return sum(1 for token in text.split() if re.search(r"\w", token))


def validate(texts: dict, context: dict) -> list[str]:
    """Errors of an answer against the schema, the template's limits, the wording rules and the context's numbers."""
    errors: list[str] = []
    allowed = _allowed_numbers(context)
    rule_ids = {r["rule_id"] for r in context["rules"]}
    for lang in ("es", "en"):
        part = texts.get(lang) if isinstance(texts, dict) else None
        if not isinstance(part, dict):
            errors.append(f"{lang}: missing")
            continue
        try:
            m.ExplanationText.model_validate(part)
        except ValueError as exc:
            errors.append(f"{lang}: does not match the schema ({exc})")
            continue
        headline, summary, points = part["headline"], part["summary"], part["points"]
        if _words(headline) > HEADLINE_WORDS:
            errors.append(f"{lang}.headline: {_words(headline)} words, at most {HEADLINE_WORDS}")
        if not SUMMARY_PARAGRAPHS[0] <= len(summary) <= SUMMARY_PARAGRAPHS[1]:
            errors.append(f"{lang}.summary: {len(summary)} paragraphs, {SUMMARY_PARAGRAPHS[0]} to "
                          f"{SUMMARY_PARAGRAPHS[1]}")
        if not POINTS[0] <= len(points) <= POINTS[1]:
            errors.append(f"{lang}.points: {len(points)} points, {POINTS[0]} to {POINTS[1]}")
        strings = [(f"{lang}.headline", headline)]
        strings += [(f"{lang}.summary[{i}]", p) for i, p in enumerate(summary)]
        strings += [(f"{lang}.points[{i}]", p) for i, p in enumerate(points)]
        for where, text in strings:
            if where.startswith(f"{lang}.summary") and _words(text) > PARAGRAPH_WORDS:
                errors.append(f"{where}: {_words(text)} words, at most {PARAGRAPH_WORDS}")
            if where.startswith(f"{lang}.points") and _words(text) > POINT_WORDS:
                errors.append(f"{where}: {_words(text)} words, at most {POINT_WORDS}")
            for hit in wa.scan_text(text, where):
                errors.append(f"{where}: forbidden word {hit.term!r} ({hit.excerpt})")
            for guard in _GUARD[lang]:
                if found := guard.search(text):
                    errors.append(f"{where}: forbidden wording {found.group(0)!r} (the Patrones wording guard)")
            for found in _TECHNICAL_FAMILY[lang].finditer(text):
                before = text[:found.start()].rstrip()
                starts_sentence = not before or before.endswith((".", "!", "?"))
                if lang == "es" and found.group(0) == "Random Forest":
                    continue
                if lang == "en" and starts_sentence and not found.group(0).startswith("Random"):
                    continue
                errors.append(f"{where}: {found.group(0)!r}: write the baseline as running text "
                              "(la regresión logística, la regresión lineal, el Random Forest / "
                              "logistic regression, linear regression, the random forest)")
            if "!" in text or "¡" in text:
                errors.append(f"{where}: no exclamation marks")
            if found := _MARKETING.search(text):
                errors.append(f"{where}: marketing word {found.group(0)!r}")
            if _EMOJI.search(text):
                errors.append(f"{where}: no emojis")
            for rid in _RULE_ID.findall(text):
                if rid not in rule_ids:
                    errors.append(f"{where}: rule {rid} does not exist in this model")
            for token, lt, value, decimals, percent, sep in _numbers(text):
                if sep and sep != ("," if lang == "es" else "."):
                    errors.append(f"{where}: {token!r} uses the wrong decimal separator for {lang}")
                elif not _number_ok(lt, value, decimals, percent, allowed):
                    errors.append(f"{where}: the number {token!r} is not one of the display values of CONTEXT")
    return errors


# ----------------------------------------------------------------------------------------------------- main


def explain(model_id: str, published: Path, out_dir: Path, model: str | None, dry_run: bool) -> int:
    context = build_context(published, model_id)
    template, template_version = read_template()
    prompt = build_prompt(template, context)
    if dry_run:
        print(prompt)
        return 0
    answer, used, errors = None, None, []
    retry_prompt = prompt
    for attempt in range(1, ATTEMPTS + 1):
        answer, used, failure = call_claude(retry_prompt, model)
        answer = typeset(answer) if answer else answer
        errors = [failure] if failure else validate(answer, context)
        print(f"{model_id}, attempt {attempt} of {ATTEMPTS}: " + ("ok" if not errors else f"{len(errors)} error(s)"),
              flush=True)
        for e in errors:
            print(f"    {e}", flush=True)
        if not errors:
            break
        retry_prompt = (
            f"{prompt}\n## Your previous answer was rejected\n\n"
            + (f"```json\n{json.dumps(answer, indent=2, ensure_ascii=False)}\n```\n\n" if answer else "")
            + "The validator found these problems. Write the whole answer again and fix every one of them:\n\n"
            + "\n".join(f"- {e}" for e in errors) + "\n"
        )
    if errors:
        print(f"{model_id}: no explanation written after {ATTEMPTS} attempts", file=sys.stderr)
        return 1
    explanation = m.ModelExplanation(
        data_version=context["data_version"], synthetic=False, model_id=model_id,
        template_version=template_version,
        generated_by=m.ExplanationAuthor(tool="Claude Code", tool_version=cli_version(), model=used),
        generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0),
        input_sha256=context_sha256(context), reviewed=False,
        es=m.ExplanationText.model_validate(answer["es"]), en=m.ExplanationText.model_validate(answer["en"]),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{model_id}.json"
    path.write_text(json.dumps(explanation.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {path} ({attempt} attempt{'s' if attempt > 1 else ''}, {used})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--published-dir", type=Path, default=PUBLISHED)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--model", default=None, help="Claude model for the CLI (default: the CLI's own choice)")
    parser.add_argument("--dry-run", action="store_true", help="print the prompt and call nothing")
    args = parser.parse_args(argv)
    return explain(args.model_id, args.published_dir, args.out_dir, args.model, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
