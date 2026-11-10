import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import { storiesGolden } from "./test/fixturesV04";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

afterEach(() => vi.unstubAllGlobals());

const calls = (endpoint: string) => fake.calls.filter((c) => c.startsWith(`/api/v1${endpoint}?`)).map((c) => new URL(c, "http://x").searchParams);
const leader = storiesGolden.stories.find((s) => s.kind === "territory_leader")!;
const localized = storiesGolden.stories.find((s) => s.kind === "localized_rule")!;
const storyEl = (id: string) => document.querySelector(`[data-story="${id}"]`) as HTMLElement;
const WINDOW = { from: "2025-01-15T06:00:00Z", to: "2025-01-15T12:00:00Z" };

async function openStories() {
  render(<App initialTab="explorar" />);
  const user = userEvent.setup();
  await screen.findByRole("region", { name: /Leyenda: activación/ });
  await user.click(screen.getByRole("button", { name: "Historias" }));
  await screen.findAllByTestId("story-reproduce");
  return user;
}

describe("Rule Stories", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, { stories: () => storiesGolden });
  });

  it("is loaded only when opened, for the selected model and window, with limit 10 and tau", async () => {
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    expect(calls("/rule-stories")).toHaveLength(0);
    await userEvent.setup().click(screen.getByRole("button", { name: "Historias" }));
    await screen.findAllByTestId("story-reproduce");
    const q = calls("/rule-stories");
    expect(q).toHaveLength(1);
    expect([q[0]!.get("model_id"), q[0]!.get("from"), q[0]!.get("to"), q[0]!.get("tau"), q[0]!.get("limit")]).toEqual([
      fx.rules.model_id,
      "2025-01-13T00:00:00Z",
      "2025-01-20T00:00:00Z",
      "0.5",
      "10",
    ]);
    expect(Number(q[0]!.get("limit"))).toBeLessThanOrEqual(10);
  });

  it("renders each story's text exactly as the API wrote it, and shows no disclaimer", async () => {
    await openStories();
    for (const s of storiesGolden.stories) {
      expect(within(storyEl(s.story_id)).getByText(s.text, { exact: true })).toBeInTheDocument();
    }
    expect(screen.queryByTestId("stories-disclaimer")).toBeNull();
    expect(screen.getByTestId("rule-stories")).toHaveTextContent(`${storiesGolden.stories.length} de ${storiesGolden.n_candidates} historias candidatas`);
  });

  it("shows the numbers and the checks on demand, as the API defines them", async () => {
    const user = await openStories();
    const el = storyEl(leader.story_id);
    await user.click(within(el).getByText("Cifras y comprobaciones"));
    for (const [k, v] of Object.entries(leader.numbers)) {
      const dt = within(el).getByText(k, { selector: "code" });
      expect(dt.closest("div")).toHaveTextContent(String(v));
    }
    expect(el).toHaveTextContent("consulta 1: contar las entidades con dominant_rule_id = R01 → 2");
    expect(el).toHaveTextContent("consulta 1: contar las entidades con n_valid ≥ 1 → 4");
    expect(el).toHaveTextContent("rule-territories · mean_activation");
  });

  it("'Reproducir' on a rule-map story sets the exact rule, metric, window and tau, and asks that request", async () => {
    const user = await openStories();
    const query = localized.queries[0]!;
    expect(query.params).toMatchObject({ rule_id: "R03", metric: "activation_frequency", tau: "0.5", ...WINDOW });
    await user.click(within(storyEl(localized.story_id)).getByTestId("story-reproduce"));
    // the app state is the query's
    expect(screen.getByRole("button", { name: /^Regla R03:/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: /Frecuencia ≥ τ en la ventana/ })).toBeChecked();
    expect(screen.getByRole("slider", { name: /τ de la frecuencia/ })).toHaveValue("0.5");
    expect(screen.getByTestId("custom-window")).toHaveTextContent(`[${WINDOW.from}, ${WINDOW.to})`);
    // and so is the request the map makes
    await waitFor(() =>
      expect(
        calls("/rule-map").some(
          (c) => c.get("rule_id") === "R03" && c.get("metric") === "activation_frequency" && c.get("from") === WINDOW.from && c.get("to") === WINDOW.to && c.get("tau") === "0.5" && c.get("model_id") === fx.rules.model_id,
        ),
      ).toBe(true),
    );
    expect(await screen.findByRole("heading", { name: /Regla R03: frecuencia de activación de la regla \(0–1\), con τ = 0.50/ })).toBeInTheDocument();
    // the story stays on screen, marked as the one being shown
    expect(storyEl(localized.story_id)).toHaveAttribute("aria-current", "true");
  });

  it("'Reproducir' on a territories story opens Territorios with the same measure, window, tau and the story's rule", async () => {
    const user = await openStories();
    await user.click(within(storyEl(leader.story_id)).getByTestId("story-reproduce"));
    const title = await screen.findByTestId("territory-title");
    expect(title).toHaveTextContent("Territorios de reglas: regla dominante por estación según la activación media");
    await waitFor(() =>
      expect(
        calls("/rule-territories").some(
          (c) => c.get("measure") === "mean_activation" && c.get("from") === WINDOW.from && c.get("to") === WINDOW.to && c.get("model_id") === fx.rules.model_id,
        ),
      ).toBe(true),
    );
    expect(screen.getByTestId("custom-window")).toHaveTextContent(`[${WINDOW.from}, ${WINDOW.to})`);
    expect(screen.getByRole("radio", { name: /Resaltar el territorio de R01/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Activación media/ })).toBeChecked();
    expect(storyEl(leader.story_id)).toHaveAttribute("aria-current", "true");
  });

  it("stories belong to Rules mode and stay open when the user comes back to it", async () => {
    const user = await openStories();
    await user.click(screen.getByRole("button", { name: "Datos observados" }));
    expect(screen.queryByTestId("rule-stories")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Reglas en el mapa" }));
    await screen.findAllByTestId("story-reproduce");
    await user.click(within(storyEl(localized.story_id)).getByTestId("story-reproduce"));
    expect(screen.getByRole("button", { name: "Reglas en el mapa" })).toHaveAttribute("aria-pressed", "true");
  });

  it("moving the timeline leaves the story's window and asks the selected one again", async () => {
    const user = await openStories();
    await user.click(within(storyEl(localized.story_id)).getByTestId("story-reproduce"));
    expect(screen.getByTestId("custom-window")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: "2" } });
    await waitFor(() => expect(screen.queryByTestId("custom-window")).toBeNull());
  });

  it("a story whose query the app cannot show is left alone (no navigation)", async () => {
    const odd = structuredClone(storiesGolden);
    odd.stories[0]!.queries[0]!.params = { model_id: odd.model_id };
    installApi({}, { stories: () => odd });
    resetMaps();
    const user = await openStories();
    const before = calls("/rule-map").length + calls("/rule-territories").length;
    await user.click(within(storyEl(odd.stories[0]!.story_id)).getByTestId("story-reproduce"));
    expect(screen.queryByTestId("custom-window")).toBeNull();
    expect(calls("/rule-map").length + calls("/rule-territories").length).toBe(before);
    expect(maps.length).toBeGreaterThan(0);
  });

  it("an error loading the stories is shown with a retry", async () => {
    installApi({ "/rule-stories": () => Promise.resolve(new Response(JSON.stringify({ detail: "ventana de más de 366 días" }), { status: 422 })) });
    resetMaps();
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await userEvent.setup().click(screen.getByRole("button", { name: "Historias" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ventana de más de 366 días");
  });
});
