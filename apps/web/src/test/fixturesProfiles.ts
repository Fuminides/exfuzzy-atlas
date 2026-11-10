import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { RuleImportanceResponse } from "../api/types";

/**
 * The per-entity rule shares of three SERVED models (artifacts/published, 2026-11-09), as integer counts (decided_share ×
 * n_predicted, which reconstruct the published shares exactly): exfuzzy-de_no2_h6-ica4-yday-seed2 (437 stations, 371
 * with predictions), exfuzzy-nyc_pickups_h1-level-rel7-seed0 (110 modelled taxi zones), exfuzzy-uk_water_do-fx-w-unique-seed0
 * (195 sampling points, a median of 18 predictions each). Not synthetic.
 */
export type ProfilesModel = "de_h6" | "nyc_h1" | "water";

interface Compact {
  model_id: string;
  measure: RuleImportanceResponse["measure"];
  n_predicted: number;
  rules: { rule_id: string; n_decided: number; decided_share: number }[];
  entities: { id: string; n: number; counts: Record<string, number> }[];
}

/** The importance as the API serves it, keeping only what the zone views read (shares and counts). */
export function servedShares(name: ProfilesModel): Pick<RuleImportanceResponse, "rules" | "entities" | "measure"> {
  const c = JSON.parse(readFileSync(resolve(process.cwd(), "src/test/fixtures-real/profiles", `${name}.json`), "utf8")) as Compact;
  return {
    measure: c.measure,
    rules: c.rules.map((r) => ({ rule_id: r.rule_id, decided_share: r.decided_share, n_decided: r.n_decided, n_checked: 0 })),
    entities: c.entities.map((e) => ({ entity_id: e.id, n_predicted: e.n, rules: Object.entries(e.counts).map(([rule_id, k]) => ({ rule_id, decided_share: k / e.n })) })),
  };
}
