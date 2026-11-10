import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import { control, emit, maps, resetMaps } from "../test/maplibreMock";
import { CANVAS_LABEL, canvasLabel, createMapLink, FALLBACK_STYLE, StationMap } from "./StationMap";
import type { StationRow } from "./stations";
import type { LayerOptions } from "./mapLayers";
import { VIRIDIS } from "../lib/colorScale";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

const point = (x: number) => ({ type: "Point", coordinates: [x, 40] }) as StationRow["geometry"];
const rows: StationRow[] = [
  { entityId: "A", name: "A", value: 0, missingReason: null, nValid: 1, geometry: point(-3.7) },
  { entityId: "D", name: "D", value: null, missingReason: "missing_input", nValid: 0, geometry: point(-3.6) },
];
const options: LayerOptions = { kind: "values", stops: VIRIDIS, domain: [0, 1], emphasis: 0.5, selectedId: null };

beforeEach(() => resetMaps());

describe("StationMap", () => {
  it("adds the stations source with API values (0 and null untouched) and the three layers", async () => {
    render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} basemapUrl="https://example.test/style.json" />);
    await act(async () => {});
    const m = maps[0]!;
    expect(m.style).toBe("https://example.test/style.json");
    const data = (m.sources["stations"] as { data: { features: { properties: { value: number | null } }[] } }).data;
    expect(data.features.map((f) => f.properties.value)).toEqual([0, null]);
    expect(Object.keys(m.layers)).toContain("stations-valid");
    expect(Object.keys(m.layers)).toContain("stations-missing");
    expect(Object.keys(m.layers)).toContain("stations-selected");
    expect(JSON.stringify(m.layers["stations-valid"]!.paint!["circle-color"])).toContain('["get","value"]');
    expect(m.fitBoundsCalls).toBe(1);
  });

  it("updates paint (not the data) when only the emphasis threshold changes", async () => {
    const { rerender } = render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} />);
    await act(async () => {});
    rerender(<StationMap rows={rows} layerOptions={{ ...options, emphasis: 0.8 }} onSelect={() => {}} />);
    expect(JSON.stringify(maps[0]!.layers["stations-valid"]!.paint!["circle-opacity"])).toContain("0.8");
  });

  it("reports the clicked station", async () => {
    const onSelect = vi.fn();
    render(<StationMap rows={rows} layerOptions={options} onSelect={onSelect} />);
    await act(async () => {});
    emit("click", { features: [{ properties: { entity_id: "D" } }] }, "stations-missing");
    expect(onSelect).toHaveBeenCalledWith("D");
  });

  it("shows a hover tooltip with the station name and value, and hides it on leave", async () => {
    render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} tipText={(r) => `${r.name}: ${r.value ?? "sin dato"}`} />);
    await act(async () => {});
    act(() => emit("mousemove", { features: [{ properties: { entity_id: "D" } }], point: { x: 10, y: 20 } }, "stations-missing"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("D: sin dato");
    act(() => emit("mouseleave", {}, "stations-missing"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("does not draw entities without geometry, and frames only the drawn ones", async () => {
    const withNull: StationRow[] = [...rows, { entityId: "N", name: "N", value: 1, missingReason: null, nValid: 1, geometry: null }];
    render(<StationMap rows={withNull} layerOptions={options} onSelect={() => {}} />);
    await act(async () => {});
    const data = (maps[0]!.sources["stations"] as { data: { features: { properties: { entity_id: string } }[] } }).data;
    expect(data.features.map((f) => f.properties.entity_id)).toEqual(["A", "D"]);
  });

  it("frames the entities the model covers, not the \"sin modelo\" ones, and any `fitTo` replaces that rule", async () => {
    const far: StationRow = { entityId: "Z", name: "Z", value: null, missingReason: "not_modelled", nValid: 0, geometry: point(10) };
    const { unmount } = render(<StationMap rows={[...rows, far]} layerOptions={options} onSelect={() => {}} />);
    await act(async () => {});
    expect([...new Set(maps[0]!.fitted?.map((p) => p[0]))]).toEqual([-3.7, -3.6]);
    unmount();
    render(<StationMap rows={[...rows, far]} layerOptions={options} onSelect={() => {}} fitTo={(r) => r.entityId === "A"} />);
    await act(async () => {});
    expect([...new Set(maps[1]!.fitted?.map((p) => p[0]))]).toEqual([-3.7]);
  });

  it("falls back to a plain background, with a visible notice, when the basemap fails", async () => {
    control.autoLoad = false;
    const { container } = render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} />);
    expect(container.querySelector(".map-attribution")).toHaveTextContent("OpenStreetMap");
    act(() => emit("error", new Error("offline")));
    expect(maps[0]!.styleSets).toEqual([FALLBACK_STYLE]);
    expect(container.querySelector(".map-attribution")).toHaveAttribute("data-basemap", "fallback");
    // Once the plain style is up, the stations are drawn again.
    control.autoLoad = true;
    act(() => emit("style.load"));
    expect(Object.keys(maps[0]!.layers)).toContain("stations-valid");
  });
  describe("polygons (taxi zones)", () => {
    const square = (x: number, y: number) =>
      ({ type: "Polygon", coordinates: [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]] }) as StationRow["geometry"];
    const multi = {
      type: "MultiPolygon",
      coordinates: [[[[10, 10], [11, 10], [11, 11], [10, 10]]], [[[20, 20], [21, 20], [21, 21], [20, 20]]]],
    } as StationRow["geometry"];
    const zones: StationRow[] = [
      { entityId: "4", name: "Alphabet City", value: null, label: "alta", missingReason: null, nValid: null, geometry: square(-74, 40.7) },
      { entityId: "35", name: "Brownsville", value: null, label: null, noReference: true, missingReason: "prediction_unavailable", nValid: null, geometry: square(-73.9, 40.6) },
      { entityId: "39", name: "Canarsie", value: null, label: null, missingReason: "prediction_unavailable", nValid: null, geometry: multi },
    ];
    const categories: LayerOptions = {
      kind: "categories",
      stops: VIRIDIS,
      domain: [0, 1],
      emphasis: null,
      selectedId: null,
      classes: [{ label: "alta", color: "#4292C6" }],
    };

    it("adds the polygon geometries as they are, with the label and no_reference flag from the rows", async () => {
      render(<StationMap rows={zones} layerOptions={categories} onSelect={() => {}} plural="zonas de taxi" />);
      await act(async () => {});
      const data = (maps[0]!.sources["stations"] as { data: { features: { geometry: { type: string }; properties: Record<string, unknown> }[] } }).data;
      expect(data.features.map((f) => f.geometry.type)).toEqual(["Polygon", "Polygon", "MultiPolygon"]);
      expect(data.features.map((f) => [f.properties.label, f.properties.no_reference])).toEqual([["alta", false], [null, true], [null, false]]);
      expect(Object.keys(maps[0]!.layers)).toEqual(expect.arrayContaining(["zones-fill", "zones-no-reference", "zones-missing", "zones-line", "zones-line-missing", "zones-line-no-reference", "zones-line-selected"]));
      expect(screen.getByRole("region", { name: /Mapa de zonas de taxi\. La tabla de zonas de taxi/ })).toBeInTheDocument();
    });

    it("registers the hatch image for 'sin referencia' (and again after the style is reloaded)", async () => {
      control.autoLoad = false;
      render(<StationMap rows={zones} layerOptions={categories} onSelect={() => {}} />);
      act(() => emit("style.load"));
      expect(maps[0]!.images["no-reference-hatch"]).toMatchObject({ width: 8, height: 8 });
      const { data } = maps[0]!.images["no-reference-hatch"] as { data: Uint8Array };
      expect(data).toHaveLength(8 * 8 * 4);
      expect(new Set([...data].filter((_, i) => i % 4 === 3))).toEqual(new Set([255])); // opaque: hatch on white
    });

    it("frames the polygons (every vertex of every part) and reports a click on any polygon layer", async () => {
      const onSelect = vi.fn();
      render(<StationMap rows={zones} layerOptions={categories} onSelect={onSelect} />);
      await act(async () => {});
      expect(maps[0]!.fitBoundsCalls).toBe(1);
      emit("click", { features: [{ properties: { entity_id: "4" } }] }, "zones-fill");
      emit("click", { features: [{ properties: { entity_id: "35" } }] }, "zones-no-reference");
      emit("click", { features: [{ properties: { entity_id: "39" } }] }, "zones-missing");
      expect(onSelect.mock.calls.map((c) => c[0])).toEqual(["4", "35", "39"]);
    });

    it("shows the hover text of a polygon", async () => {
      render(<StationMap rows={zones} layerOptions={categories} onSelect={() => {}} tipText={(r) => `${r.name}: ${r.noReference ? "sin referencia" : (r.label ?? "sin predicción")}`} />);
      await act(async () => {});
      act(() => emit("mousemove", { features: [{ properties: { entity_id: "35" } }], point: { x: 5, y: 5 } }, "zones-no-reference"));
      expect(screen.getByRole("tooltip")).toHaveTextContent("Brownsville: sin referencia");
    });
  });
});

describe("StationMap link (Rule Duel: two maps, one camera)", () => {
  const moveOn = (i: number, originalEvent?: unknown) => maps[i]!.handlers["move"]!.forEach((h) => h({ originalEvent }));

  it("copies a user's pan or zoom to the sibling map, but not a programmatic move (no echo)", async () => {
    const link = createMapLink();
    render(
      <>
        <StationMap rows={rows} layerOptions={options} onSelect={() => {}} link={link} name="A" />
        <StationMap rows={rows} layerOptions={options} onSelect={() => {}} link={link} name="B" />
      </>,
    );
    await act(async () => {});
    expect(link.members.size).toBe(2);
    expect(screen.getByRole("region", { name: /Mapa de estaciones · A\./ })).toBeInTheDocument();
    moveOn(0, undefined);
    expect(maps[1]!.jumps ?? []).toHaveLength(0);
    moveOn(0, new Event("mousemove"));
    expect(maps[1]!.jumps).toHaveLength(1);
    expect(maps[0]!.jumps ?? []).toHaveLength(0);
    moveOn(1, new Event("wheel"));
    expect(maps[0]!.jumps).toHaveLength(1);
  });

  it("forgets a map that is removed", async () => {
    const link = createMapLink();
    const { unmount } = render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} link={link} />);
    await act(async () => {});
    expect(link.members.size).toBe(1);
    unmount();
    expect(link.members.size).toBe(0);
  });
});

describe("StationMap in English", () => {
  afterEach(() => setLang("es"));

  it("names the map, its canvas and the basemap fallback in English, and renames the canvas when the language changes", async () => {
    setLang("en");
    const { rerender } = render(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} plural="stations" />);
    await act(async () => {});
    expect(screen.getByRole("region", { name: "Map of stations. The table of stations does the same by keyboard." })).toBeInTheDocument();
    expect(maps[0]!.canvasAttributes?.["aria-label"]).toBe("Interactive map: arrow keys to pan, + and − to zoom in or out");
    expect(screen.getByText(/data © OpenStreetMap contributors/)).toBeInTheDocument();
    setLang("es");
    rerender(<StationMap rows={rows} layerOptions={options} onSelect={() => {}} plural="estaciones" />);
    expect(maps[0]!.canvasAttributes?.["aria-label"]).toBe(CANVAS_LABEL);
    expect(canvasLabel()).toBe(CANVAS_LABEL);
  });
});
