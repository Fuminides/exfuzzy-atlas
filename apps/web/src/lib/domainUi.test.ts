import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { domainUi, listOr } from "./domainUi";

afterEach(() => setLang("es"));

describe("task statements", () => {
  it("lists the options of a sentence, in both languages", () => {
    expect(listOr(["baja", "normal", "alta"])).toBe("baja, normal o alta");
    expect(listOr(["Buena"])).toBe("Buena");
    setLang("en");
    expect(listOr(["low", "high"])).toBe("low or high");
  });

  it("every domain states its task in one sentence, with the task's horizon and classes", () => {
    for (const d of ["air", "water", "mobility", "fnirs"]) expect(domainUi(d).task).toBeDefined();
    expect(domainUi("air").task!({ hours: 6, predicts: "la categoría EAQI de NO₂", classes: "Buena o Mala" })).toBe(
      "Prever, 6 h antes, la categoría EAQI de NO₂ (Buena o Mala) en cada estación de medida.",
    );
    expect(domainUi("mobility").task!({ hours: 3, predicts: "", classes: "baja o alta" })).toMatch(/^Prever, 3 h antes, si la demanda de taxi amarillo en cada zona será baja o alta /);
  });
});
