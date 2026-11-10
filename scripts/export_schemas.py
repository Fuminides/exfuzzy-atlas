"""Write the JSON Schemas of the API payloads to src/atlas/contracts/schemas/.

The web client generates its TypeScript types from these files; a test fails when they
are stale. Usage: python scripts/export_schemas.py [--out DIR]
"""

import argparse
import json
from pathlib import Path

from atlas.contracts import models as m

REPO = Path(__file__).resolve().parents[1]
EXPORTED = [
    m.Health, m.DomainsResponse, m.EntityCollection, m.ModelCard, m.ModelRules, m.SeriesResponse,
    m.RuleMapResponse, m.RuleTrace, m.PredictionRecord, m.ObservationRecord,
    m.PredictionsResponse, m.ObservationsResponse, m.RuleTerritoriesResponse, m.RuleStoriesResponse,
    m.ScenarioRequest, m.ScenarioResponse, m.RuleImportanceResponse, m.SummaryResponse, m.ModelExplanation,
    m.SourceManifest, m.QualityReport, m.RunManifest, m.MetricsReport,
]


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for model in EXPORTED:
        schema = model.model_json_schema(mode="serialization")
        schema["$id"] = f"https://exfuzzy-atlas/schemas/{m.SCHEMA_VERSION}/{model.__name__}.schema.json"
        (out / f"{model.__name__}.schema.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(EXPORTED)} schemas to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "src" / "atlas" / "contracts" / "schemas")
    main(parser.parse_args().out)
