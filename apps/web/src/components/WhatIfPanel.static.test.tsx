import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStaticSource } from "../api/static";
import { memorySource } from "../api/static/source";
import { testExport } from "../api/static/testExport";
import type { ModelRules, RuleTrace } from "../api/types";
import { WhatIfPanel } from "./WhatIfPanel";

vi.mock("../lib/dataMode", () => ({ isStaticData: () => true, staticDataBase: () => "/data/x/", STORIES_TAU: 0.5 }));

const files = testExport();
const variables = (files.get("models/m-win/rules.json.gz") as unknown as ModelRules).variables;
let store: ReturnType<typeof useStaticSource>;

beforeEach(() => {
  store = useStaticSource(memorySource(files));
});

async function panel(entity: string, at: string, extra: { onGoTo?: (i: string) => void } = {}) {
  const baseline: RuleTrace = await store.ruleTrace(entity, "m-win", at);
  return render(<WhatIfPanel modelId="m-win" entityId={entity} entityName="Alpha" at={at} variables={variables} baseline={baseline} classifier mixture={false} {...extra} />);
}

describe("¿Y si…? on a static export", () => {
  it("offers a slider per input over the precomputed grid, and no free number", async () => {
    await panel("A", "2025-03-05T22:00:00Z");
    const x = await screen.findByRole("slider", { name: /x \(deslizador\)|x.*\(deslizador\)/i });
    expect(x).toHaveAttribute("max", "2"); // 3 values
    expect(x).toHaveValue("1"); // the observed 10 sits on the grid value 10
    expect(screen.getAllByRole("slider")).toHaveLength(2);
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("shows the precomputed answer when a slider moves, and one input at a time", async () => {
    await panel("A", "2025-03-05T22:00:00Z");
    const [x, y] = await screen.findAllByRole("slider");
    fireEvent.change(x!, { target: { value: "2" } });
    const summary = await screen.findByTestId("whatif-prediction", undefined, { timeout: 4000 });
    expect(summary).toHaveTextContent("Good → Bad");
    // moving the other input replaces the first change
    fireEvent.change(y!, { target: { value: "0" } });
    await waitFor(() => expect(screen.getByTestId("whatif-prediction")).toHaveTextContent("Good → Good"), { timeout: 4000 });
    const rows = within(screen.getByTestId("whatif-inputs-table")).getAllByRole("row");
    expect(rows.filter((r) => r.getAttribute("data-origin") === "overridden")).toHaveLength(1);
  });

  it("offers to go to the nearest instant with scenarios when this one has none", async () => {
    const onGoTo = vi.fn();
    await panel("A", "2025-03-06T00:00:00Z", { onGoTo });
    const go = await screen.findByTestId("whatif-goto");
    expect(screen.queryByRole("slider")).toBeNull();
    fireEvent.click(go);
    expect(onGoTo).toHaveBeenCalledWith("2025-03-05T22:00:00Z");
  });

  it("shows nothing for an entity the export holds no sweep for", async () => {
    const { container } = await panel("B", "2025-03-05T23:00:00Z");
    await waitFor(() => expect(store).toBeTruthy());
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector("[data-testid=whatif-panel]")).toBeNull();
  });
});
