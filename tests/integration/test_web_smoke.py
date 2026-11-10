"""AT-062 #7: accessibility smoke of the built web against the real API, with headless Chrome (opt-in, local only).

``make qa-web`` (or ``ATLAS_QA_WEB=1 pytest tests/integration/test_web_smoke.py``). Needs the published models, the
built web (``apps/web/dist``), Node and Chrome. It starts ``scripts/qa/demo.sh`` (API :8000, web :4173 by default;
``ATLAS_QA_API_PORT`` / ``ATLAS_QA_WEB_PORT`` move them next to a running demo) unless both are already up, drives
``scripts/qa/web_smoke.mjs`` and checks, per territory and per section (Resumen, Patrones, Predicción, Explorar): the
page title and its one-sentence lead, legends with units, a table alternative to every map with the right row count,
keyboard reachability, attribution, no raw identifier in the redesigned text, and the wording audit over the rendered
text. The v0.5 payloads (summary, importance) answer 404 until the backend publishes them: that state must be the
explicit "no disponible todavía", never an error or an empty chart. Screenshots go to ``ATLAS_QA_OUT`` (default: a
temp dir) as ``qa-<territory>-<section>[-<view>].png``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
import wording_audit as wa
from qa_support import REPO, published_dir

WEB_PORT = os.environ.get("ATLAS_QA_WEB_PORT", "4173")
API_PORT = os.environ.get("ATLAS_QA_API_PORT", "8000")
WEB_URL, API_URL = f"http://127.0.0.1:{WEB_PORT}", f"http://127.0.0.1:{API_PORT}"
TERRITORIES = ("madrid", "germany", "nyc", "water")
# every entity of the geometry is a row (v0.4): NYC lists its 263 zones, 110 modelled and 153 "sin modelo"
ENTITIES = {"madrid": 24, "germany": 437, "nyc": 263, "water": 195}
UNIT = {"madrid": "µg/m³", "germany": "µg/m³", "nyc": "percentil", "water": "mg/l"}


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    if os.environ.get("ATLAS_QA_WEB") != "1":
        pytest.skip("opt-in browser smoke: run `make qa-web` (ATLAS_QA_WEB=1)")
    if not (published_dir() / "registry.json").is_file():
        pytest.skip(f"no published models at {published_dir()}")
    chrome = next((p for p in (shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser")) if p), None)
    if not (chrome and shutil.which("node")):
        pytest.skip("needs Node and Chrome/Chromium")
    procs: list[subprocess.Popen] = []
    try:
        if not (_up(f"{API_URL}/api/v1/health") and _up(f"{WEB_URL}/")):
            env = {
                **os.environ,
                "ATLAS_PUBLISHED_DIR": str(published_dir()),
                "API_PORT": API_PORT,
                "WEB_PORT": WEB_PORT,
            }
            demo = subprocess.Popen(
                [str(REPO / "scripts/qa/demo.sh")],
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            procs.append(demo)
            for _ in range(120):
                if _up(f"{API_URL}/api/v1/health") and _up(f"{WEB_URL}/"):
                    break
                if demo.poll() is not None:
                    pytest.skip(f"demo.sh exited: {demo.stderr.read().decode()[:300]}")
                time.sleep(1)
            else:
                pytest.skip("demo servers did not start")
        out = Path(os.environ.get("ATLAS_QA_OUT") or tmp_path_factory.mktemp("web-smoke"))
        out.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        profile = tmp_path_factory.mktemp("chrome-profile")
        procs.append(
            subprocess.Popen(
                [
                    chrome,
                    "--headless=new",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={profile}",
                    "--no-first-run",
                    "--disable-gpu",
                    "--use-gl=swiftshader",
                    "--enable-unsafe-swiftshader",
                    "--window-size=1500,1050",
                    "about:blank",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        for _ in range(30):
            if _up(f"http://127.0.0.1:{port}/json/version"):
                break
            time.sleep(0.5)
        run = subprocess.run(
            ["node", str(REPO / "scripts/qa/web_smoke.mjs"), "--url", WEB_URL, "--cdp", str(port), "--out", str(out)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert run.returncode == 0, run.stderr[-1000:]
        data = json.loads((out / "web_smoke.json").read_text())
        yield {"data": data, "out": out}
    finally:
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGINT)
                p.wait(timeout=15)
            except Exception:
                os.killpg(p.pid, signal.SIGKILL)


def _view(smoke, territory, tab, view=None):
    return smoke["data"][f"{territory}-{tab}" if view is None else f"{territory}-explorar-{view}"]


def test_the_bare_url_opens_the_landing_with_one_h1_a_start_button_and_its_artifacts(smoke):
    v = smoke["data"]["landing"]
    assert len(v["h1"]) == 1, v["h1"]
    assert v["start"], "no «Empezar la demo» button"
    # the artifacts are drawn from the API's data: the report figure and the rule card at least
    assert {"landing-perf", "landing-rule"} <= set(v["artifacts"]), v["artifacts"]
    assert not v["overflowX"], "the landing scrolls sideways"


# A snake_case word is an identifier (`no2_lag3h`, `valid_hour_local`): the redesigned text must have none.
IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


@pytest.mark.parametrize("territory", TERRITORIES)
@pytest.mark.parametrize("tab", ("resumen", "patrones", "prediccion", "rendimiento", "explorar"))
def test_every_section_has_a_title_a_lead_sentence_and_no_error(smoke, territory, tab):
    v = _view(smoke, territory, tab, "rules" if tab == "explorar" else None)
    assert v["error"] is None, v["error"]
    assert v["title"], "the page has no title"
    assert v["lead"] and len(v["lead"]) > 40, "the page does not say what is being looked at"
    assert v["tabsOk"], "the five sections are not a tablist with one selected tab"
    assert v["unnamedMain"] == 0, "controls without an accessible name"
    # the sections that are data are never described with forbidden words in their own title or lead
    assert not wa.scan_text(v["title"] + ". " + v["lead"], "lead")


@pytest.mark.parametrize("territory", TERRITORIES)
def test_resumen_is_a_summary_of_the_data_or_says_it_is_not_available_yet(smoke, territory):
    v = _view(smoke, territory, "resumen")
    if v["notYet"]:  # the backend has not published summary.json for this model: an explicit state, no empty charts
        assert any("no disponible todavía" in n for n in v["notYet"]) and v["charts"] == 0
        return
    assert v["charts"] == 4, "year, month, hour and weekday"
    assert v["dataStripHeight"] is not None and v["dataStripHeight"] < 140, "the data block is not a quiet strip"
    assert v["legends"] and all(leg["text"] for leg in v["legends"]), "no map legend"
    ranking = [t for t in v["tables"] if t["name"].lower().startswith("ranking")]
    assert ranking and ranking[0]["rows"] == ENTITIES[territory], "the ranking is not a complete table alternative"
    assert v["mapRegions"] and "tabla" in v["mapRegions"][0].lower()
    assert not IDENTIFIER.findall(v["ownedText"]), IDENTIFIER.findall(v["ownedText"])


@pytest.mark.parametrize("territory", TERRITORIES)
def test_patrones_shows_rules_as_sentences_and_importance_or_says_it_is_not_available_yet(smoke, territory):
    v = _view(smoke, territory, "patrones")
    assert v["firstTab"] == "Patrones", "the rules are not the first section"
    assert v["ruleCards"] > 0 and v["ruleSentences"], "the rules are not listed"
    assert v["rulesFirst"] is not False, "the variables come before the rules"
    if v["dataLine"]:  # one slim line of data context, only when /summary exists
        assert v["dataLine"].startswith("Datos: ")
    assert all(sentence.startswith("Si ") and "→" in sentence for sentence in v["ruleSentences"])
    assert not IDENTIFIER.findall(v["ownedText"]), IDENTIFIER.findall(v["ownedText"])
    if v["notYet"]:  # importance.json missing: no bars, and the map by zones says so too
        assert any("no disponible todavía" in n for n in v["notYet"]) and v["variableBars"] == 0
        return
    assert v["variableBars"] > 0
    zones = [t for t in v["tables"] if t["name"].lower().startswith("tabla de")]
    assert zones and zones[0]["rows"] == ENTITIES[territory]


@pytest.mark.parametrize("territory", TERRITORIES)
def test_prediccion_explains_the_horizon_and_has_title_legend_unit_table_and_keyboard_access(smoke, territory):
    v = _view(smoke, territory, "prediccion")
    assert v["horizon"] and ("+" in v["horizon"] or "Misma muestra" in v["horizon"]), "the horizon is not stated"
    sentence = v["horizonSentence"] or ""
    if territory == "water":  # horizon 0: same-sample inference, never a forecast
        assert "sobre la misma muestra" in sentence and "+0" not in sentence
    else:
        assert "(+" in sentence and " h)" in sentence and "hora de emisión" in sentence
    assert v["reportLink"], "Predicción does not link to the performance report"
    assert v["title"] and v["mapTitle"], "the map has no title"
    legend = " ".join(leg["label"] + " " + leg["text"] for leg in v["legends"])
    assert UNIT[territory] in legend and "activación de regla (0–1)" not in v["mapTitle"]
    assert v["mapRegions"] and "tabla" in v["mapRegions"][0].lower(), "the map region does not point to its table"
    stations = [t for t in v["tables"] if t["name"].lower().startswith(("estaciones", "zonas", "puntos"))]
    assert stations and stations[0]["rows"] == ENTITIES[territory]
    assert v["railTabbable"] >= 3 and v["railUnnamed"] == 0, "rail controls without an accessible name"
    assert v["keyboard"]["distinct"] >= 3, "Tab does not walk through distinct controls"
    assert v["attribution"] and "OpenStreetMap" in v["attribution"], "basemap attribution (ODbL) missing"
    # strict: a renamed slider used to make this check skip silently (the label lost "(issue time)" in v0.5)
    # Water's issue times are irregular samples: it moves by windows (WindowNavigator), there is no hourly slider
    slider = v["keyboard"].get("slider")
    if territory == "water":
        assert slider is None
    else:
        assert slider, "no time slider labelled «Hora de emisión»"
        assert slider["before"] != slider["after"], "PageDown does not move the timeline"
    assert not IDENTIFIER.findall(v["ownedText"]), IDENTIFIER.findall(v["ownedText"])


@pytest.mark.parametrize("territory", TERRITORIES)
def test_explorar_keeps_the_expert_views_with_activation_labelled_as_what_it_is(smoke, territory):
    rules, data = _view(smoke, territory, "explorar", "rules"), _view(smoke, territory, "explorar", "data")
    assert "no es importancia ni probabilidad" in rules["lead"]
    legend = " ".join(leg["label"] + " " + leg["text"] for leg in rules["legends"])
    assert "0–1" in legend and "No es una probabilidad" in legend
    assert ("ventana" in rules["mapTitle"]) == (territory == "water")
    assert territory == "water" or "instante de emisión" in rules["mapTitle"]
    for v in (rules, data):
        assert v["mapRegions"] and "tabla" in v["mapRegions"][0].lower()
        table = [t for t in v["tables"] if t["name"].lower().startswith(("estaciones", "zonas", "puntos"))]
        assert table and table[0]["rows"] == ENTITIES[territory]
        assert v["railTabbable"] >= 3 and v["railUnnamed"] == 0
        assert v["keyboard"]["distinct"] >= 3
        assert v["legends"] and all(leg["text"] for leg in v["legends"])


def test_licence_attribution_is_shown_per_territory(smoke):
    want = {
        "madrid": "CC BY 4.0",
        "germany": "CC BY 4.0",
        "nyc": "licencia no declarada",
        "water": "Open Government Licence",
    }
    for territory, needle in want.items():
        assert needle in _view(smoke, territory, "explorar", "rules")["footerAttribution"], territory


def test_rendered_text_never_describes_a_rule_with_forbidden_words(smoke):
    hits = []
    for path in sorted(smoke["out"].glob("qa-*.txt")):
        hits += [h for h in wa.scan_text(path.read_text(), f"rendered:{path.stem}") if h.kind == "rule-context"]
    assert hits == [], "\n".join(map(str, hits))


def test_water_never_renders_t_plus_0h(smoke):
    hits = []
    for path in sorted(smoke["out"].glob("qa-water-*.txt")):
        hits += [h for h in wa.scan_text(path.read_text(), f"rendered:{path.stem}") if h.kind == "zero-horizon"]
    assert hits == [], "\n".join(map(str, hits))


@pytest.mark.parametrize("territory", TERRITORIES)
def test_rendimiento_compares_the_model_with_the_baselines_and_says_how_often_it_is_right(smoke, territory):
    v = _view(smoke, territory, "rendimiento")
    assert v["perfBars"] and v["perfBars"][0] == "model", "no bars, or the model is not the first one"
    assert "forest" in v["perfBars"], "the random forest baseline is missing"
    assert v["accuracyBlock"], "no plain-language accuracy block (in «Detalle técnico»)"

