import { describe, expect, it } from "vitest";
import { entities, rules as classRules } from "../test/fixturesClass";
import { classifiedSummary } from "../test/fixturesV05";
import { count, defaultThreshold, distributionText, lcFirst, orMore, periodText, rowsOf, stationsWithData, thresholdLabel, worseShare } from "./summary";

const summary = classifiedSummary(classRules, entities, "t");
const classes = summary.classes!;

describe("worse classes", () => {
  it("starts counting at the middle class of the scheme and says 'o peor' for an air index, 'o más' for levels", () => {
    expect(defaultThreshold(classes)).toBe(Math.floor(classes.length / 2));
    expect(thresholdLabel(classes, 1, "air")).toBe(`${classes[1]!.label} o peor`);
    expect(thresholdLabel(classes, classes.length - 1, "air")).toBe(classes[classes.length - 1]!.label);
    expect(orMore("mobility")).toBe("o más");
  });

  it("sums the shares from the threshold on; a group with no observations is null, never 0", () => {
    const row = { n: 10, shares: [0.5, 0.3, 0.2] };
    expect(worseShare(row, 1)).toBeCloseTo(0.5, 12);
    expect(worseShare(row, 2)).toBeCloseTo(0.2, 12);
    expect(worseShare({ n: 0, shares: null }, 1)).toBeNull();
    expect(worseShare(undefined, 1)).toBeNull();
  });
});

describe("wording of the summary", () => {
  it("writes the distribution with es-ES percentages and leaves out empty classes", () => {
    expect(distributionText(classes.slice(0, 3), [0.74, 0.23, 0.03])).toBe("74 % " + classes[0]!.label + " · 23 % " + classes[1]!.label + " · 3,0 % " + classes[2]!.label);
    expect(distributionText(classes.slice(0, 2), [1, 0])).toBe("100 % " + classes[0]!.label);
  });

  it("gives the period as UTC days with the exclusive end taken back one day", () => {
    expect(periodText(summary)).toBe("1 de enero de 2024 – 31 de diciembre de 2024");
  });

  it("keeps NO₂ as written and lowers only a capitalised word", () => {
    expect([lcFirst("NO₂ horario observado"), lcFirst("Oxígeno disuelto observado")]).toEqual(["NO₂ horario observado", "oxígeno disuelto observado"]);
  });

  it("counts stations with data and formats counts in es-ES", () => {
    expect(rowsOf(summary, "entity").length).toBe(entities.features.length - 1);
    expect(stationsWithData(summary).every((r) => r.n > 0)).toBe(true);
    expect(count(1234567)).toBe("1.234.567");
  });
});
