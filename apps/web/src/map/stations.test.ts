import { describe, expect, it } from "vitest";
import { positions, toCollection, type StationRow } from "./stations";
import { nyc } from "../test/fixturesReal";

const base = { value: null, missingReason: null, nValid: null } as const;

describe("toCollection", () => {
  it("keeps the real polygon geometries and flags 'sin referencia', and drops entities without geometry", () => {
    const rows: StationRow[] = nyc.entities.features.map((f) => ({
      ...base,
      entityId: f.properties.entity_id,
      name: f.properties.name ?? "",
      label: null,
      noReference: f.properties.entity_id === "35",
      geometry: f.properties.entity_id === "4" ? null : f.geometry,
    }));
    const out = toCollection(rows);
    expect(out.features).toHaveLength(nyc.entities.features.length - 1);
    expect(out.features.map((f) => f.id)).not.toContain("4");
    const brownsville = out.features.find((f) => f.id === "35")!;
    expect(brownsville.properties.no_reference).toBe(true);
    expect(out.features.filter((f) => f.properties.no_reference)).toHaveLength(1);
    // the geometry is the API's, untouched
    expect(brownsville.geometry).toEqual(nyc.entities.features.find((f) => f.id === "35")!.geometry);
  });
});

describe("positions", () => {
  it("lists points, and every vertex of polygons and of each MultiPolygon part", () => {
    const rows: StationRow[] = [
      { ...base, entityId: "p", name: "p", geometry: { type: "Point", coordinates: [1, 2] } },
      { ...base, entityId: "a", name: "a", geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } },
      { ...base, entityId: "m", name: "m", geometry: { type: "MultiPolygon", coordinates: [[[[5, 5], [6, 5], [6, 6], [5, 5]]], [[[7, 7], [8, 7], [8, 8], [7, 7]]]] } },
      { ...base, entityId: "n", name: "n", geometry: null },
    ];
    expect(positions(rows)).toHaveLength(1 + 4 + 8);
    expect(positions(rows)).toContainEqual([8, 8]);
  });

  it("frames the real NYC zones inside the city", () => {
    const all = positions(nyc.entities.features.map((f) => ({ ...base, entityId: f.id, name: "", geometry: f.geometry })));
    expect(all.length).toBeGreaterThan(100);
    for (const [lon, lat] of all) {
      expect(lon).toBeGreaterThan(-74.3);
      expect(lon).toBeLessThan(-73.6);
      expect(lat).toBeGreaterThan(40.4);
      expect(lat).toBeLessThan(41);
    }
  });
});
