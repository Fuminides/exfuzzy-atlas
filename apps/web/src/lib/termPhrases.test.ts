import { describe, expect, it } from "vitest";
import { conditionText, conditionWords, nounOf, termPhrase } from "./termPhrases";

describe("termPhrase: a term names what it qualifies", () => {
  it("agrees in gender with the noun in Spanish", () => {
    expect(termPhrase("rel_lag1", "alta", "es", "alta")).toBe("demanda alta");
    expect(termPhrase("rel_lag24", "muy alta", "es", "muy alta")).toBe("demanda muy alta");
    expect(termPhrase("relative_humidity", "Medium", "es", "media")).toBe("humedad media");
    expect(termPhrase("temperature", "Low", "es", "baja")).toBe("temperatura baja");
    expect(termPhrase("wind_speed", "High", "es", null)).toBe("viento alto");
    expect(termPhrase("ph", "Low", "es", "bajo")).toBe("pH bajo");
    expect(termPhrase("no2_lag3h", "Medium", "es", null)).toBe("nivel de NO₂ medio");
  });

  it("puts the adjective before the noun in English", () => {
    expect(termPhrase("rel_lag1", "alta", "en", "high")).toBe("high demand");
    expect(termPhrase("rel_lag2", "muy alta", "en", "very high")).toBe("very high demand");
    expect(termPhrase("relative_humidity", "Medium", "en", "medium")).toBe("medium humidity");
    expect(termPhrase("water_temperature", "High", "en", "high")).toBe("high water temperature");
  });

  it("keeps the model's own word for a level when it published one", () => {
    // Water's hour of the sample: «temprana», «a media mañana», «tardía»
    expect(termPhrase("local_hour", "Low", "es", "temprana")).toBe("hora temprana");
    expect(termPhrase("local_hour", "Low", "en", "early")).toBe("early hour");
    expect(termPhrase("local_hour", "Medium", "en", "mid-morning")).toBe("mid-morning hour");
    // NYC's mean of the last 24 h, relative to what is usual
    expect(termPhrase("rel_mean24h", "High", "es", "por encima de lo habitual")).toBe("demanda por encima de lo habitual");
    expect(termPhrase("rel_mean24h", "Medium", "en", "as usual")).toBe("usual demand");
  });

  it("says Water's detection-limit terms in words (L is the common detection limit)", () => {
    expect(termPhrase("ammoniacal_nitrogen", "<=L", "es")).toBe("nitrógeno amoniacal en el límite de detección o por debajo");
    expect(termPhrase("orthophosphate_reactive", "Alto>L", "es")).toBe("ortofosfato alto, sobre el límite de detección");
    expect(termPhrase("ammoniacal_nitrogen", "Bajo>L", "en")).toBe("low ammoniacal nitrogen, above the detection limit");
    expect(termPhrase("orthophosphate_reactive", "<=L", "en")).toBe("orthophosphate at or below the detection limit");
  });

  it("passes complete terms through: EAQI classes, named periods, seasons, Beaufort names", () => {
    expect(termPhrase("no2_last", "Good", "es", "Buena")).toBe("Buena");
    expect(termPhrase("no2_lag24h", "Poor or worse", "en", "Poor or worse")).toBe("Poor or worse");
    expect(termPhrase("valid_hour_local", "Midday", "es", "Mediodía")).toBe("Mediodía");
    expect(termPhrase("local_dow", "Domingo", "en", "Sunday")).toBe("Sunday");
    expect(termPhrase("days_from_midwinter", "Invierno", "es", null)).toBe("Invierno");
    expect(termPhrase("wind_speed", "Light breeze", "es", "Brisa ligera")).toBe("Brisa ligera");
  });

  it("falls back to today's label for a variable it does not know", () => {
    expect(nounOf("turbidity_index")).toBeNull();
    expect(termPhrase("turbidity_index", "High", "es", "alta")).toBe("alta");
    expect(termPhrase("y_lag3", "Low", "en", null)).toBe("Low");
  });

  it("completes the classes of a relative level with the target's noun", () => {
    expect(termPhrase("pickups", "baja", "es", "baja")).toBe("demanda baja");
    expect(termPhrase("pickups", "normal", "en", "normal")).toBe("normal demand");
    expect(termPhrase("no2", "Good", "es", "Buena")).toBe("Buena");
  });
});

describe("conditionWords: the variable named once, the term agreeing with it", () => {
  it("adds the article and drops a unit parenthesis in Spanish", () => {
    const c = conditionWords("relative_humidity", "High", "Humedad relativa hace 1 h (%)", "alta", "%", "es");
    expect(c).toEqual({ article: "la", subject: "humedad relativa hace 1 h", verb: "es", value: "alta" });
    expect(conditionText(conditionWords("no2_last", "Good", "NO₂ hace 1 h (último dato)", "Buena", "ug/m3", "es"))).toBe("el NO₂ hace 1 h (último dato) es Buena");
    expect(conditionText(conditionWords("ph", "Low", "pH de la muestra", "bajo", "pH", "es"))).toBe("el pH de la muestra es bajo");
  });

  it("names NYC's level as demand, so «alta» agrees", () => {
    expect(conditionText(conditionWords("rel_lag1", "alta", "Nivel hace 1 h (percentil)", "alta", "percentile", "es"))).toBe("la demanda hace 1 h es alta");
    expect(conditionText(conditionWords("rel_lag168", "normal", "Nivel hace 168 h (percentil)", "normal", "percentile", "es"))).toBe("la demanda hace 1 semana es normal");
    expect(conditionText(conditionWords("rel_lag1", "alta", "Level 1 h ago (percentile)", "high", "percentile", "en"))).toBe("demand 1 h ago is high");
    expect(conditionText(conditionWords("rel_mean24h", "High", "Nivel medio, 24 h previas (razón)", "por encima de lo habitual", "ratio", "es"))).toBe(
      "la demanda media de las 24 h previas está por encima de lo habitual",
    );
  });

  it("uses the verb each term needs", () => {
    expect(conditionText(conditionWords("ammoniacal_nitrogen", "<=L", "Nitrógeno amoniacal de la muestra (mg/l)", "≤ límite de detección", "mg/l", "es"))).toBe(
      "el nitrógeno amoniacal de la muestra está en el límite de detección o por debajo",
    );
    expect(conditionText(conditionWords("ammoniacal_nitrogen", "Medio>L", "Ammoniacal nitrogen in the sample (mg/l)", "medium (above the limit)", "mg/l", "en"))).toBe(
      "ammoniacal nitrogen in the sample is medium, above the detection limit",
    );
    expect(conditionText(conditionWords("days_from_midwinter", "Invierno", "Días desde pleno invierno", null, "days", "es"))).toBe("la época del año es Invierno");
  });

  it("reads as before for a variable it does not know", () => {
    expect(conditionWords("y_lag3", "Low", "Y lag3", "baja", null, "es")).toEqual({ article: "", subject: "Y lag3", verb: "es", value: "baja" });
  });
});
