import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { setLang } from "./i18n";
import { officialNames } from "./lib/labels";
import { installApi } from "./test/fakeApi";
import * as fx from "./test/fixturesClass";
import { MADRID_ATTRIBUTION } from "./test/fixturesV04";
import { resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

// The first credit carries its English (v0.6.1); the others do not and fall back to the text as sent.
const credits = MADRID_ATTRIBUTION.map((a, i) => (i === 0 ? { ...a, text_en: "Madrid City Council, Air Quality Service (English credit)." } : a));

describe("the footer follows the interface language", () => {
  it("English shows the credit's English text and keeps the original where there is none", async () => {
    installApi({}, { ...fx.classifierData(), real: true, card: { ...fx.card, attribution: credits } });
    render(<App initialTab="explorar" initialLang="en" />);
    const footer = within(screen.getByRole("contentinfo"));
    const attribution = await screen.findByTestId("attribution");
    expect(attribution).toHaveTextContent("Madrid City Council, Air Quality Service (English credit).");
    expect(attribution).not.toHaveTextContent(MADRID_ATTRIBUTION[0]!.text);
    if (MADRID_ATTRIBUTION.length > 1) expect(attribution).toHaveTextContent(MADRID_ATTRIBUTION[1]!.text);
    expect(footer.getByText("Versions and provenance")).toBeInTheDocument();
  });

  it("Spanish keeps the credit as the source states it", async () => {
    installApi({}, { ...fx.classifierData(), real: true, card: { ...fx.card, attribution: credits } });
    render(<App initialTab="explorar" />);
    expect(await screen.findByTestId("attribution")).toHaveTextContent(MADRID_ATTRIBUTION[0]!.text);
  });

  it("a scheme that is not an official index has no 'official names' line", () => {
    const classes = [{ label: "baja", display_label_en: "low" }, { label: "alta", display_label_en: "high" }];
    setLang("en");
    expect(officialNames({ kind: "percentile_reference", short_name: "Nivel relativo", classes } as never)).toBeNull();
    expect(officialNames({ kind: "official_index", short_name: "ICA", classes } as never)).toBe("official ICA names: baja, alta");
  });
});
