"""scripts/explain_model.py (contract v0.6.2): the context it builds and the validator of Claude's answer.

No call to Claude here: the context is built from a synthetic published model and the validator is fed by hand.
"""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

import pytest

from atlas.ml.exfuzzy_features import has_rule_mixture
from atlas.services.synthetic import build_synthetic

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import explain_model as em  # noqa: E402


@pytest.fixture(scope="module")
def context(built_class_v04):
    return em.build_context(built_class_v04.published_dir, built_class_v04.run.manifest.model_id)


def _answer(context, es_extra="", en_extra=""):
    rule = context["rules"][0]
    es_share, en_share = rule["decided_share"]["display"]["es"], rule["decided_share"]["display"]["en"]
    rid = rule["rule_id"]
    return {
        "es": {"headline": f"{rid} decide el {es_share} de las predicciones",
               "summary": [f"La regla {rid} decide el {es_share}.{es_extra}", "El modelo compara su F1 macro."],
               "points": [f"Mira {rid}.", "Hay pocas reglas.", "Los datos son inventados."]},
        "en": {"headline": f"{rid} decides {en_share} of the predictions",
               "summary": [f"Rule {rid} decides {en_share}.{en_extra}", "The model is compared on macro-F1."],
               "points": [f"Look at {rid}.", "There are few rules.", "The data are made up."]},
    }


def test_the_context_comes_from_the_published_files_and_is_stable(context, built_class_v04):
    assert context["model_id"] == built_class_v04.run.manifest.model_id
    assert context["task"]["task_type"] == "classification" and context["rule_weighting"] == "dominance_score"
    assert [r["rank_by_decided_share"] for r in context["rules"]] == list(range(1, len(context["rules"]) + 1))
    shares = [r["decided_share"]["value"] for r in context["rules"]]
    assert shares == sorted(shares, reverse=True)
    for rule in context["rules"]:
        assert set(rule["decided_share"]["display"]) == {"es", "en"}
        assert {"label", "label_en"} <= set(rule["then_class"])
    again = em.build_context(built_class_v04.published_dir, built_class_v04.run.manifest.model_id)
    assert em.context_sha256(again) == em.context_sha256(context)


def test_number_formats_follow_the_web():
    assert em.share(0.2398)["display"] == {"es": "24 %", "en": "24%"}
    assert em.share(0.026)["display"] == {"es": "2,6 %", "en": "2.6%"}
    assert em.share(0.0001)["display"] == {"es": "<0,1 %", "en": "<0.1%"}
    assert em.share(0.998)["display"] == {"es": "99,8\u202f%", "en": "99.8%"}  # never "100 %" below 1
    assert em.share(0.9997)["display"] == {"es": ">99,9\u202f%", "en": ">99.9%"}
    assert em.share(1.0)["display"] == {"es": "100\u202f%", "en": "100%"}
    assert em.score(0.4107)["display"] == {"es": "0,41", "en": "0.41"}
    assert em.amount(0.6351, "mg/l")["display"] == {"es": "0,64 mg/l", "en": "0.64 mg/l"}
    assert em.period("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")["display"]["es"] == "2025"
    assert em.period("2025-02-08T00:00:00Z", "2025-04-01T00:00:00Z")["display"] == {
        "es": "del 8 de febrero de 2025 al 31 de marzo de 2025", "en": "8 February 2025 to 31 March 2025"}
    # NYC's split boundaries are New York midnights: dated in that zone, the last day is 31 March, not 1 April
    assert em.period("2025-02-08T05:00:00Z", "2025-04-01T04:00:00Z", "America/New_York")["display"]["en"] == (
        "8 February 2025 to 31 March 2025")
    assert em.period("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "Europe/Berlin")["display"]["en"] == "2025"


def test_standing_is_the_web_s():
    assert em._standing(0.41, 0.405, True) == "on a par"
    assert em._standing(0.41, 0.29, True) == "better"
    assert em._standing(0.41, 0.43, True) == "worse"
    assert em._standing(0.635, 0.659, False) == "better"  # a lower error is better; 1 % of the error is a tie


def test_a_faithful_answer_passes(context):
    assert em.validate(_answer(context), context) == []


@pytest.mark.parametrize(("es_extra", "en_extra", "expected"), [
    (" Es una probabilidad.", "", "forbidden"),
    ("", " This is not a probability.", "forbidden wording"),  # the Patrones guard: no negation excuses it
    ("", " The rule's activation is high.", "forbidden wording"),
    (" Acierta el 73,4 %.", "", "not one of the display values"),
    (" Acierta 0.5.", "", "wrong decimal separator"),
    ("", " It is right 0,5.", "wrong decimal separator"),
    (" Mira R99.", "", "R99 does not exist"),
    (" Deciden el >99,9 %.", "", "not one of the display values"),
    (" Es impresionante.", "", "marketing word"),
    (" Es peor que Random forest.", "", "write the baseline as running text"),
    (" Es peor que el bosque aleatorio.", "", "write the baseline as running text"),
    (" Es peor que la Logistic regression.", "", "write the baseline as running text"),
    ("", " It is worse than the Random forest.", "write the baseline as running text"),
    ("", " It is worse than the Random Forest.", "write the baseline as running text"),
    ("", " It is worse than Linear regression.", "write the baseline as running text"),
    ("", " Great!", "exclamation"),
    (" Y la t+0h.", "", "forbidden"),
])
def test_the_validator_rejects(context, es_extra, en_extra, expected):
    errors = em.validate(_answer(context, es_extra, en_extra), context)
    assert any(expected in e for e in errors), errors


def test_the_baselines_are_running_text(context):
    ok = _answer(
        context,
        " Es peor que el Random Forest y que la regresión lineal. Queda por debajo del Random Forest.",
        " It is worse than the random forest and logistic regression. Logistic regression is better.",
    )
    assert em.validate(ok, context) == []


def test_the_validator_allows_one_unit_in_the_last_shown_digit(context):
    rule = context["rules"][0]
    shown = rule["decided_share"]["value"] * 100
    if shown < 10:
        pytest.skip("the first rule's share is shown with a decimal here")
    near = f" Casi el {round(shown) + 1} %."
    assert em.validate(_answer(context, near), context) == []
    far = f" Casi el {round(shown) + 3} %."
    assert any("not one of the display values" in e for e in em.validate(_answer(context, far), context))


def test_typeset_puts_a_narrow_no_break_space_before_percent_in_spanish():
    got = em.typeset({"es": {"headline": "el 46 % y el 0,8 %", "summary": ["a 5 %"], "points": []},
                      "en": {"headline": "46 %", "summary": [], "points": []}})
    assert got["es"]["headline"] == "el 46\u202f% y el 0,8\u202f%" and got["es"]["summary"] == ["a 5\u202f%"]
    assert got["en"]["headline"] == "46 %"


def test_a_percentage_is_one_word():
    assert em._words("decide el 84\u202f% — y acierta") == 5


def test_the_limits_of_the_template(context):
    answer = _answer(context)
    long = copy.deepcopy(answer)
    long["es"]["headline"] = " ".join(["palabra"] * (em.HEADLINE_WORDS + 1))
    long["en"]["summary"] = ["one"]
    long["en"]["points"] = ["a"] * 6
    errors = em.validate(long, context)
    assert any("es.headline" in e for e in errors)
    assert any("en.summary: 1 paragraphs" in e for e in errors)
    assert any("en.points: 6 points" in e for e in errors)


def test_the_prompt_is_the_template_then_the_context(context):
    template, version = em.read_template()
    assert version == "5"
    prompt = em.build_prompt(template, context)
    assert prompt.startswith("# Rule-base explanation template (version 5)")
    assert "rule_mixture_classifier" in prompt  # the mixture section (contract v0.7) travels with every prompt
    assert context["model_id"] in prompt.split("## CONTEXT", 1)[1]


def test_the_call_cannot_act():
    cmd = em.claude_command(None)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--model" not in cmd and em.claude_command("opus")[-2:] == ["--model", "opus"]


# ------------------------------------------------------------------------------ a rule mixture (contract v0.7)

needs_mixture = pytest.mark.skipif(not has_rule_mixture() and not os.environ.get("CI"),
                                   reason="needs ex_fuzzy with inference='mixture' (EXFUZZY_SRC, docs/reproduce.md)")


@pytest.fixture(scope="module")
def mixture_context(tmp_path_factory):
    built = build_synthetic(tmp_path_factory.mktemp("published-mixture"), task="mixture", v04=True)
    return em.build_context(built.published_dir, built.run.manifest.model_id)


def _walk(node):
    """Every key and every string of the context."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)
    elif isinstance(node, str):
        yield node


def _mixture_answer(context):
    rule, other = context["rules"][0], context["rules"][1]
    top = rule["top_rule_share"]["display"]
    weight = rule["class_weights_centred"][0]["weight"]["display"]
    return {
        "es": {"headline": f"{rule['rule_id']} es la regla que más suma a la categoría predicha en el {top['es']}",
               "summary": [f"Las reglas suman su apoyo a cada categoría y ninguna decide sola. {rule['rule_id']} pesa "
                           f"{weight['es']} en la primera categoría y {other['rule_id']} le sigue.",
                           "El modelo compara su F1 macro."],
               "points": [f"Mira {rule['rule_id']}.", "Hay pocas reglas.", "Los datos son inventados."]},
        "en": {"headline": f"{rule['rule_id']} adds the most to the predicted category in {top['en']}",
               "summary": [f"The rules add up their support for each category and no single rule decides. "
                           f"{rule['rule_id']} weighs {weight['en']} on the first category and {other['rule_id']} "
                           "comes next.", "The model is compared on macro-F1."],
               "points": [f"Look at {rule['rule_id']}.", "There are few rules.", "The data are made up."]},
    }


@needs_mixture
def test_a_mixture_context_describes_what_the_published_files_give(mixture_context):
    ctx = mixture_context
    assert ctx["inference"]["family"] == "rule_mixture_classifier"
    assert "rule_weighting" not in ctx and "rule_mode" not in ctx["inference"]
    how = ctx["inference"]["how_a_prediction_is_made"]
    assert "weight" in how["en"] and "peso" in how["es"] and ":" not in how["en"] + how["es"]
    shares = [r["top_rule_share"]["value"] for r in ctx["rules"]]
    assert shares == sorted(shares, reverse=True)
    assert [r["rank_by_top_rule_share"] for r in ctx["rules"]] == list(range(1, len(ctx["rules"]) + 1))
    for rule in ctx["rules"]:
        assert not {"then_class", "consequent", "decided_share", "weight"} & set(rule)  # no part in the prediction
        for number in (rule["top_rule_share"], rule["decisive_share"]):
            assert set(number["display"]) == {"es", "en"}
        weights = {w["class"]["key"]: w["weight"] for w in rule["class_weights_centred"]}
        assert [c["key"] for c in rule["supports"]] == [k for k, w in weights.items() if w["display"]["en"][0] == "+"]
        assert [c["key"] for c in rule["suppresses"]] == [k for k, w in weights.items() if w["display"]["en"][0] == "−"]
    assert "predicted_share" not in ctx["target_scheme"]["classes"][0]
    size = ctx["model_size"]
    assert size["n_rules_that_are_the_top_rule_at_least_once"]["value"] <= size["n_rules"]["value"]
    assert all("share_of_predictions_whose_top_rule_uses_it" in v for v in ctx["variables"])


def test_a_centred_weight_shows_its_sign():
    assert em.signed(2.2233)["display"] == {"es": "+2,22", "en": "+2.22"}
    assert em.signed(-1.3428)["display"] == {"es": "−1,34", "en": "−1.34"}
    assert em.signed(-0.0004)["display"] == {"es": "0,00", "en": "0.00"}  # a weight that rounds to zero has no sign


@needs_mixture
def test_a_mixture_context_has_no_word_the_guard_rejects(mixture_context):
    forbidden = re.compile(r"contribut|contribuci|importance|importancia|probabilit|confiden|confianza|risk|riesgo|"
                           r"cause|causa|activation|activaci|certainty|certeza", re.I)
    for text in _walk(mixture_context):
        assert not forbidden.search(text), text
        assert not any(guard.search(text) for guards in em._GUARD.values() for guard in guards), text
        assert not em.wa.scan_text(text, "context"), text


@needs_mixture
def test_a_faithful_mixture_answer_passes_without_a_winning_rule_wording(mixture_context):
    answer = _mixture_answer(mixture_context)
    assert em.validate(answer, mixture_context) == []
    assert not re.search(r"decide[sn]? (?:el|la|\d)|decides? \d|the rule that holds most", str(answer))


@needs_mixture
def test_a_mixture_answer_with_a_made_up_weight_or_rule_is_rejected(mixture_context):
    answer = _mixture_answer(mixture_context)
    answer["en"]["summary"][0] += " R99 weighs +9.99 on the first category."
    errors = em.validate(answer, mixture_context)
    assert any("R99 does not exist" in e for e in errors) and any("9.99" in e for e in errors), errors


def test_the_winning_rule_with_weights_is_described_as_the_template_does():
    how = em._how({"family": "winning_rule_classifier", "rule_weighting": "dominance_score"}, True)
    assert how["en"] == "The rule with the highest degree × weight decides each prediction."
    assert how["es"].startswith("Decide cada predicción la regla cuyo grado de cumplimiento multiplicado por su peso")
    assert ":" not in how["en"] + how["es"]
