import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { storiesGolden } from "../test/fixturesV04";
import { checkText, queryText, reproduceTarget } from "./stories";

const query = (path: string, params: Record<string, string>) => ({ method: "GET" as const, path: path as "/api/v1/rule-map", params });

describe("reproduceTarget (a story's query as the state of the app)", () => {
  it("maps a firing_strength rule-map query to rule, metric and issue time", () => {
    expect(reproduceTarget(query("/api/v1/rule-map", { model_id: "m", rule_id: "R14", metric: "firing_strength", time: "2025-01-13T12:00:00Z" }))).toEqual({
      view: "rule",
      ruleId: "R14",
      metric: "firing_strength",
      time: "2025-01-13T12:00:00Z",
      from: null,
      to: null,
      tau: null,
    });
  });

  it("maps a windowed rule-map query with tau, keeping the window exactly", () => {
    const localized = storiesGolden.stories.find((s) => s.kind === "localized_rule")!.queries[0]!;
    expect(reproduceTarget(localized)).toEqual({
      view: "rule",
      ruleId: "R03",
      metric: "activation_frequency",
      time: null,
      from: "2025-01-15T06:00:00Z",
      to: "2025-01-15T12:00:00Z",
      tau: 0.5,
    });
  });

  it("maps a rule-territories query to measure, window and tau", () => {
    const leader = storiesGolden.stories.find((s) => s.kind === "territory_leader")!.queries[0]!;
    expect(reproduceTarget(leader)).toEqual({ view: "territories", measure: "mean_activation", from: "2025-01-15T06:00:00Z", to: "2025-01-15T12:00:00Z", tau: 0.5 });
  });

  it("returns null for a query it cannot show (never guesses a rule, a metric or a window)", () => {
    expect(reproduceTarget(query("/api/v1/rule-map", { rule_id: "R01", metric: "firing_strength" }))).toBeNull(); // no time
    expect(reproduceTarget(query("/api/v1/rule-map", { rule_id: "R01", metric: "mean_activation", from: "2025-01-01T00:00:00Z" }))).toBeNull(); // no to
    expect(reproduceTarget(query("/api/v1/rule-map", { metric: "mean_activation", from: "a", to: "b" }))).toBeNull(); // no rule
    expect(reproduceTarget(query("/api/v1/rule-map", { rule_id: "R01", metric: "dominant", from: "a", to: "b" }))).toBeNull();
    expect(reproduceTarget(query("/api/v1/rule-territories", { measure: "mean_activation" }))).toBeNull();
    expect(reproduceTarget(query("/api/v1/entities", { rule_id: "R01" }))).toBeNull();
  });
});

describe("check and query wording", () => {
  it("spells out a check as the API defines it", () => {
    expect(checkText({ query: 0, property: "value", op: "gte", operand: 0.5, expected: 19 })).toBe("consulta 1: contar las entidades con value ≥ 0.5 → 19");
    expect(checkText({ query: 2, property: "dominant_rule_id", op: "eq", operand: "R06", expected: 22 })).toBe("consulta 3: contar las entidades con dominant_rule_id = R06 → 22");
    expect(checkText({ query: 0, property: "value", op: "not_null", operand: null, expected: 4 })).toBe("consulta 1: contar las entidades con value no es null → 4");
  });

  it("describes the request it reproduces", () => {
    expect(queryText(query("/api/v1/rule-map", { rule_id: "R03", metric: "activation_frequency", from: "A", to: "B", tau: "0.5" }))).toBe(
      "rule-map · regla R03 · activation_frequency · [A, B), τ=0.5",
    );
    expect(queryText(query("/api/v1/rule-map", { rule_id: "R03", metric: "firing_strength", time: "T" }))).toBe("rule-map · regla R03 · firing_strength · emisión T");
  });
});

describe("check and query wording in English", () => {
  afterEach(() => setLang("es"));

  it("spells out checks and requests in English (property names and parameters stay as the API sends them)", () => {
    setLang("en");
    expect(checkText({ query: 0, property: "value", op: "gte", operand: 0.5, expected: 19 })).toBe("query 1: count the entities with value ≥ 0.5 → 19");
    expect(checkText({ query: 0, property: "value", op: "not_null", operand: null, expected: 4 })).toBe("query 1: count the entities with value is not null → 4");
    expect(queryText(query("/api/v1/rule-map", { rule_id: "R03", metric: "firing_strength", time: "T" }))).toBe("rule-map · rule R03 · firing_strength · issue T");
    expect(queryText(query("/api/v1/rule-territories", { measure: "winner_share", from: "A", to: "B" }))).toBe("rule-territories · winner_share · [A, B)");
  });
});
