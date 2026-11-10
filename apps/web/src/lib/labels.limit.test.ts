import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { LinguisticVariable } from "../api/types";
import { DEFAULT_NAMES, namesFor, termLabel } from "./labels";

afterEach(() => setLang("es"));

/** Water's ammonia with no published term labels: the raw ex_fuzzy names are keys, never what is shown. */
const AMMONIA: LinguisticVariable = {
  feature: "ammoniacal_nitrogen", unit: "mg/l", label: "Nitrógeno amoniacal", label_en: "Ammoniacal nitrogen", domain: [0.03, 5],
  terms: [
    { name: "<=L", membership_type: "trapezoidal", params: [0, 0, 1, 2] },
    { name: "Bajo>L", membership_type: "trapezoidal", params: [1, 2, 3, 4] },
    { name: "Medio>L", membership_type: "trapezoidal", params: [3, 4, 5, 6] },
    { name: "Alto>L", membership_type: "trapezoidal", params: [5, 6, 7, 8] },
  ],
};

describe("detection-limit terms without a published label", () => {
  it("are shown in words, in both languages", () => {
    expect(termLabel("<=L")).toBe("≤ límite de detección");
    expect(termLabel("Medio>L")).toBe("media (sobre el límite)");
    setLang("en");
    expect(termLabel("<=L")).toBe("≤ detection limit");
    expect(termLabel("Bajo>L")).toBe("low (above the limit)");
    expect(termLabel("Alto>L")).toBe("high (above the limit)");
  });

  it("do not change the generic terms or any other name", () => {
    expect(termLabel("High")).toBe("alta");
    expect(termLabel("Invierno")).toBe("Invierno");
    expect(termLabel("Lx>L")).toBe("Lx>L");
  });

  it("reach the screen through both fallbacks (no provider, and a provider without labels)", () => {
    for (const lang of ["es", "en"] as const) {
      setLang(lang);
      const viaProvider = namesFor([AMMONIA], null, null).term("ammoniacal_nitrogen", "<=L");
      expect(viaProvider).toBe(DEFAULT_NAMES.term("ammoniacal_nitrogen", "<=L"));
      expect(viaProvider).not.toMatch(/<=L|>L/);
      expect(namesFor([AMMONIA], null, null).label("ammoniacal_nitrogen", { term: "Medio>L", operator: "at_most", terms: ["<=L", "Bajo>L", "Medio>L"] })).not.toMatch(/>L/);
    }
  });
});
