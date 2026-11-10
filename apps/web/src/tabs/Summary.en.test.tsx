import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { setLang } from "../i18n";
import { installApi } from "../test/fakeApi";
import { resetMaps } from "../test/maplibreMock";
import { classifierV05, regressionV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

/** Summary in English: the page's sentences are English; the summary's label, entity and territory names are data. */
describe("Summary in English (classified variable)", () => {
  beforeEach(() => installApi({}, classifierV05()));

  it("has the English title, lead and data strip, with English dates and numbers", async () => {
    render(<App initialLang="en" initialTab="resumen" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Data summary: Zona de prueba" })).toBeInTheDocument();
    const lead = screen.getByTestId("page-lead");
    expect(lead).toHaveTextContent("You are looking at concentración observada in Zona de prueba, measured at 2 stations");
    expect(lead).toHaveTextContent("1 January 2024 – 31 December 2024");
    expect(lead).toHaveTextContent("with no model, so there are no predictions here");
    const strip = screen.getByRole("region", { name: "What is in the data" });
    expect(within(strip).getByTestId("data-facts")).toHaveTextContent("2 of 3 stations");
    expect(within(strip).getByTestId("data-facts")).toHaveTextContent("1,000 observations");
    expect(within(strip).getByRole("img", { name: "All the observations in Zona de prueba: 70% low · 20% mid · 10% high" })).toBeInTheDocument();
  });

  it("the map, its legend and the ranking speak English", async () => {
    render(<App initialLang="en" initialTab="resumen" />);
    expect(await screen.findByRole("region", { name: "Where hours in “mid or worse” are most frequent" })).toBeInTheDocument();
    const legend = await screen.findByRole("region", { name: "Legend: Hours in “mid or worse”" });
    expect(legend).toHaveTextContent("Stations with data: 2 of 3");
    expect(legend).toHaveTextContent("no observations at this station (hollow ring)");
    const table = screen.getByRole("table", { name: /Ranking of stations \(text alternative to the map\): hours in “mid or worse”/ });
    expect(within(table).getAllByRole("row")[3]).toHaveTextContent("no data");
    expect(screen.getByRole("region", { name: "Choose a station" })).toBeInTheDocument();
  });

  it("draws the calendar groups with English titles, months and table", async () => {
    render(<App initialLang="en" initialTab="resumen" />);
    for (const title of ["By year", "By month", "By hour of the day", "By day of the week"]) expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "By month: Hours in “mid or worse”. 2 of 12 groups with data." })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /By month/ });
    expect(within(table).getByRole("row", { name: /Feb\s+no data/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /Mar.*20 \(few\)/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How it changes over time" })).toBeInTheDocument();
  });
});

describe("Summary in English (numeric variable, not published)", () => {
  it("numeric: median and spread in English", async () => {
    installApi({}, regressionV05());
    render(<App initialLang="en" initialTab="resumen" />);
    expect(await screen.findByRole("region", { name: /Legend: Median of NO₂ horario observado/ })).toHaveTextContent("Stations with data: 3 of 4");
    const strip = screen.getByRole("region", { name: "What is in the data" });
    expect(strip).toHaveTextContent(/Median 30\sµg\/m³/);
    expect(strip).toHaveTextContent(/half of the values between 27 and 33\sµg\/m³/);
    expect(within(screen.getByRole("table", { name: /Ranking of stations/ })).getAllByRole("row")[1]).toHaveTextContent(/40\.0\sµg\/m³/);
  });

  it("404: not available yet, in English", async () => {
    installApi({}, classifierV05({ summary: false }));
    render(<App initialLang="en" initialTab="resumen" />);
    expect(await screen.findByTestId("not-yet")).toHaveTextContent("The data summary: not available yet.");
    expect(screen.getByTestId("page-lead")).toHaveTextContent("What the observed data in");
  });

  it("a server error keeps a retry, in English", async () => {
    installApi({ "/summary": () => Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), { status: 500 })) }, classifierV05());
    render(<App initialLang="en" initialTab="resumen" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the summary");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
