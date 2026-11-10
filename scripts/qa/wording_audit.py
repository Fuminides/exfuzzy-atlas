"""Wording audit (AT-062): words that must not describe a rule firing, an association degree or a rule weight.

``MAP_EXPERIENCE.md`` §9 blocks "80 % de probabilidad" and "80 % de importancia" for an activation of 0.8, and a
dominant rule presented as a cause or contribution. This scanner finds, in plain text, the words

    probabilidad / probability, riesgo / risk, contribución / contribution, importancia / importance,
    causa / cause / causal, relevancia / influencia, certeza / certainty, confianza / confidence

that are used in the context of a rule (firing, activation, association, weight, membership, antecedent) **without** an
explicit negation earlier in the same sentence ("No es una probabilidad, un riesgo ni una contribución", "Never
importance"). A negated mention is the project's own disclaimer and is never a hit.

It also flags "+0 h" / "(t+0h)" (a zero horizon is same-time inference, not a forecast "t+0h").

Usage::

    python scripts/qa/wording_audit.py                  # web sources + published payloads (ATLAS_PUBLISHED_DIR)
    python scripts/qa/wording_audit.py --web-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

TERMS = re.compile(
    r"\b(probabilidad(?:es)?|probability|probabilities|riesgo|riesgos|risk|risks|contribuci[oó]n|contribuciones|"
    r"contribution|contributions|importancia|importance|causa|causas|causal|causalidad|cause|causes|causing|"
    r"relevancia|relevance|influencia|influence|certeza|certidumbre|certainty|confianza|confidence|confident)\b",
    re.IGNORECASE,
)
CONTEXT = re.compile(
    r"firing|activaci|activation|activa\b|asociaci|association|\bpeso\b|weight|\bregla|\brules?\b|membership|"
    r"pertenencia|antecedent|dominan|winning|\\bTHEN\\b",
    re.IGNORECASE,
)
# Web *source code* may name the contract v0.5 measure: ``GET /models/{id}/importance`` returns
# ``RuleImportanceResponse`` ("decide y acierta": the share of predictions a rule decides and how often it is right,
# never its activation), so identifiers and paths say "importance". The UI is in Spanish: the user-visible
# "importancia" stays forbidden in a rule context, and the rendered-text audit of the web smoke keeps every term.
WEB_SOURCE_TERMS = re.compile(TERMS.pattern.replace("importancia|importance|", "importancia|"), re.IGNORECASE)
NEGATION = re.compile(
    r"\b(no|ni|nunca|jamás|tampoco|ninguna?|sin|never|not|nor|without|neither)\b|n't|\bNOT\b", re.IGNORECASE
)
ZERO_HORIZON = re.compile(r"\(\s*t\s*\+\s*0\s*h\s*\)|\bt\s*\+\s*0\s*h\b|\+\s*0\s*h\b", re.IGNORECASE)
# a sentence ends at . ! ? ; (not inside a number like 0.5) followed by a space, a quote or the end
_SENTENCE_END = re.compile(r"(?<!\d)[.!?;](?=[\s\"'`<)]|$)|\n\s*\n")
_LOOKBACK = 400


@dataclass(frozen=True)
class Hit:
    source: str  # file path, or "api:<endpoint>"
    line: int | str  # 1-based line for files, JSON path for payloads
    kind: str  # "rule-context" | "other-context" | "zero-horizon"
    term: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.source}:{self.line} [{self.kind}] {self.term!r}: {self.excerpt}"


def _excerpt(text: str, start: int, end: int, width: int = 80) -> str:
    """The matched line, trimmed around the match."""
    first = text.rfind("\n", 0, start) + 1
    last = text.find("\n", end)
    line = text[first : len(text) if last < 0 else last]
    at = start - first
    return re.sub(r"\s+", " ", line[max(0, at - width) : at + width]).strip()


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - _LOOKBACK) : start]
    ends = list(_SENTENCE_END.finditer(window))
    sentence = window[ends[-1].end() :] if ends else window
    return bool(NEGATION.search(sentence))


def scan_text(text: str, source: str, *, locate=None, terms: re.Pattern = TERMS) -> list[Hit]:
    """Hits in ``text``; ``locate(offset)`` maps a character offset to a line number (default: line in ``text``)."""
    locate = locate or (lambda off: text.count("\n", 0, off) + 1)
    hits: list[Hit] = []
    for match in terms.finditer(text):
        if _negated(text, match.start()):
            continue
        around = text[max(0, match.start() - 250) : match.end() + 250]
        kind = "rule-context" if CONTEXT.search(around) else "other-context"
        hits.append(
            Hit(source, locate(match.start()), kind, match.group(0), _excerpt(text, match.start(), match.end()))
        )
    for match in ZERO_HORIZON.finditer(text):
        if _negated(text, match.start()):  # e.g. a comment saying 'never "+0 h"'
            continue
        hits.append(
            Hit(
                source,
                locate(match.start()),
                "zero-horizon",
                match.group(0),
                _excerpt(text, match.start(), match.end()),
            )
        )
    return hits


def scan_file(path: Path, root: Path = REPO, terms: re.Pattern = TERMS) -> list[Hit]:
    return scan_text(
        path.read_text(encoding="utf-8"), str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        terms=terms,
    )


def web_sources(root: Path = REPO) -> Iterator[Path]:
    web = root / "apps" / "web"
    yield web / "index.html"
    for path in sorted((web / "src").rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".css"} or ".test." in path.name or "generated" in path.parts:
            continue
        if path.name == "setup.ts" or "test" in path.relative_to(web / "src").parts[:1]:
            continue
        yield path


def scan_web(root: Path = REPO) -> list[Hit]:
    return [h for path in web_sources(root) if path.exists() for h in scan_file(path, root, WEB_SOURCE_TERMS)]


def _walk_strings(node, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_strings(value, f"{path}[{i}]")


def scan_payload(payload, source: str) -> list[Hit]:
    """Hits in every string value of a JSON payload; ``line`` is the JSON path."""
    hits: list[Hit] = []
    for json_path, text in _walk_strings(payload):
        hits += [Hit(h.source, json_path, h.kind, h.term, h.excerpt) for h in scan_text(text, source)]
    return hits


def scan_json_strings(payload, source: str) -> list[Hit]:
    """Hits in the string values of a JSON document, with the line each one has in its indent=2 rendering.

    Only the string itself (not neighbouring JSON keys) decides whether it is "about a rule".
    """
    pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    cursor, hits = 0, []
    for _, text in _walk_strings(payload):
        found = pretty.find(json.dumps(text, ensure_ascii=False), cursor)
        if found >= 0:
            cursor = found
        for hit in scan_text(text, source):
            hits.append(Hit(hit.source, pretty.count("\n", 0, cursor) + 1, hit.kind, hit.term, hit.excerpt))
    return hits


def scan_published_files(published: Path, model_id: str | None = None) -> list[Hit]:
    """The JSON files a model publishes (rules, card, manifest, metrics, feature spec); every model dir by default."""
    hits: list[Hit] = []
    for model_dir in sorted(p for p in published.iterdir() if p.is_dir() and model_id in (None, p.name)):
        for name in ("rules.json", "card.json", "run_manifest.json", "metrics.json", "feature_spec.json"):
            path = model_dir / name
            if path.exists():
                hits += scan_json_strings(json.loads(path.read_text(encoding="utf-8")), f"{model_dir.name}/{name}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--web-only", action="store_true")
    parser.add_argument("--published", default=os.environ.get("ATLAS_PUBLISHED_DIR", str(REPO / "artifacts/published")))
    args = parser.parse_args()
    hits = scan_web()
    if not args.web_only and (Path(args.published) / "registry.json").exists():
        hits += scan_published_files(Path(args.published))
    for hit in hits:
        print(hit)
    flagged = [h for h in hits if h.kind != "other-context"]
    print(f"\n{len(flagged)} hit(s) about rules or a zero horizon, {len(hits) - len(flagged)} other (informational)")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
