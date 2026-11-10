import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { RuleTrace } from "../api/types";
import { fmt, fmtFine } from "./format";
import { associationStory } from "./association";
import * as nyc from "../test/fixturesReal";
import * as cls from "../test/fixturesClass";

const nycTrace = (): RuleTrace => nyc.nyc.traces.find((t) => t.entity_id === nyc.NYC_ZONE && t.issued_at_utc === nyc.NYC_EVENING)!;

describe("associationStory", () => {
  it("real NYC trace: a rule that fires fully loses on weight, in the trace's own numbers", () => {
    const t = nycTrace();
    const by = (id: string) => t.rules.find((r) => r.rule_id === id)!;
    expect(t.prediction.winning_rule_id).toBe("R01");
    // the strongest-firing loser (firing 1; ties broken by association) is R08, and R01 fires less
    expect([by("R08").firing_strength, by("R01").firing_strength]).toEqual([1, 0.8941391941391937]);
    const story = associationStory(t.rules, "R01")!;
    expect(story.loserId).toBe("R08");
    expect(story.winner).toBe(
      "R01 decide la categoría. Se activa con grado 0,894 y su peso es 0,062, así que su asociación (activación × peso) es 0,056, la mayor de todas las reglas.",
    );
    expect(story.loser).toBe(
      "R08 se activa por completo (1,000), más que R01 (0,894), pero su peso (0,031) es menor que el de R01 (0,062), así que su asociación (0,031) queda por debajo de la de R01 (0,056).",
    );
    // every number in the sentences is a formatting of a number in the trace
    expect(story.loser).toContain(fmtFine(by("R08").weight!));
    expect(story.loser).toContain(fmtFine(by("R08").association_degree!));
    expect(story.winner).toContain(fmt(by("R01").firing_strength));
  });

  it("equal activation is said as equal, and the weight alone explains the order", () => {
    const t = cls.trace("E0", "2024-01-06T10:00:00Z");
    const story = associationStory(t.rules, t.prediction.winning_rule_id ?? null)!;
    expect(story.winnerId).toBe("R04");
    expect(story.loser).toBe(
      "R02 se activa por completo (1,000), igual que R04 (1,000), pero su peso (0,086) es menor que el de R04 (0,112), así que su asociación (0,086) queda por debajo de la de R04 (0,112).",
    );
  });

  it("tiny weights keep two significant digits, never 0.000", () => {
    const rules = [
      { rule_id: "R01", firing_strength: 0.4, weight: 0.00064, association_degree: 0.000256 },
      { rule_id: "R02", firing_strength: 1, weight: 0.00008, association_degree: 0.00008 },
    ];
    const story = associationStory(rules, "R01")!;
    expect(story.winner).toContain("su peso es 0,00064");
    expect(story.winner).toContain("0,00026");
    expect(story.loser).toContain("su peso (0,00008) es menor que el de R01 (0,00064)");
    expect(`${story.winner}${story.loser}`).not.toContain("0,000,");
  });

  it("says nothing when there is no winner, no weight, or no other rule that fires", () => {
    const t = nycTrace();
    expect(associationStory(t.rules, null)).toBeNull();
    expect(associationStory([{ rule_id: "R01", firing_strength: 1 }], "R01")).toBeNull();
    const only = associationStory([{ rule_id: "R01", firing_strength: 1, weight: 0.1, association_degree: 0.1 }], "R01")!;
    expect(only.loser).toBeNull();
  });

  it("never uses the words probability, confidence, importance or risk", () => {
    const t = nycTrace();
    const story = associationStory(t.rules, "R01")!;
    expect(`${story.winner} ${story.loser}`).not.toMatch(/probabilidad|confianza|importancia|riesgo|contribuci/i);
  });
});

describe("associationStory in English", () => {
  afterEach(() => setLang("es"));

  it("writes the whole sentences in English with English numbers, and the same comparisons", () => {
    setLang("en");
    const t = nycTrace();
    const story = associationStory(t.rules, "R01")!;
    expect(story.winner).toBe(
      "R01 decides the category. Its activation degree is 0.894 and its weight 0.062, so its association (activation × weight) is 0.056, the highest of all the rules.",
    );
    expect(story.loser).toBe(
      "R08 fires fully (1.000), more than R01 (0.894), but its weight (0.031) is lower than that of R01 (0.062), so its association (0.031) stays below that of R01 (0.056).",
    );
    const tie = cls.trace("E0", "2024-01-06T10:00:00Z");
    expect(associationStory(tie.rules, tie.prediction.winning_rule_id ?? null)!.loser).toBe(
      "R02 fires fully (1.000), the same as R04 (1.000), but its weight (0.086) is lower than that of R04 (0.112), so its association (0.086) stays below that of R04 (0.112).",
    );
  });

  it("never uses the words probability, confidence, importance, risk, contribution or cause", () => {
    setLang("en");
    const t = nycTrace();
    const story = associationStory(t.rules, "R01")!;
    expect(`${story.winner} ${story.loser}`).not.toMatch(/probabilit|confiden|importan|risk|contribut|caus(e|al)|certaint/i);
  });
});
