import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { useStaticSource } from "./api/static";
import { memorySource } from "./api/static/source";
import { testExport } from "./api/static/testExport";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
vi.mock("./lib/dataMode", () => ({ isStaticData: () => true, staticDataBase: () => "/data/x/", STORIES_TAU: 0.5 }));

beforeEach(() => {
  const files = testExport();
  // nothing but a planned domain: the page chrome is what is under test
  files.set("domains.json.gz", { schema_version: "0.7.0", data_version: "dv1", synthetic: false, domains: [{ domain: "mobility", title: "Mobility", status: "planned", tasks: [] }] });
  useStaticSource(memorySource(files));
});

describe("App on a static site", () => {
  it("has no API label in the footer, and says where the data come from", async () => {
    render(<App />);
    await screen.findByText("Mobility", { exact: false });
    expect(screen.queryByText(/^API:/)).toBeNull();
    expect(screen.getByText("Fuente: datos publicados")).toBeInTheDocument();
  });

  it("does not blame an API that is not there when there is nothing to show", async () => {
    const files = testExport();
    files.set("domains.json.gz", { schema_version: "0.7.0", data_version: "dv1", synthetic: false, domains: [] });
    useStaticSource(memorySource(files));
    render(<App />);
    expect(await screen.findByText("No hay datos de ningún territorio.")).toBeInTheDocument();
  });

  it("says what could not be loaded, with no hint about starting an API", async () => {
    useStaticSource(memorySource({}));
    render(<App />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(), { timeout: 4000 });
    expect(screen.getByRole("alert")).not.toHaveTextContent(/make api|API/);
    expect(screen.getByRole("alert")).toHaveTextContent(/Sin datos \(404\)/);
  });
});
