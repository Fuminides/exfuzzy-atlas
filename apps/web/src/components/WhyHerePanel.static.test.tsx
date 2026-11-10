import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { rules, trace } from "../test/fixtures";
import { WhyHerePanel } from "./WhyHerePanel";

vi.mock("../lib/dataMode", () => ({ isStaticData: () => true, staticDataBase: () => "/data/x/", STORIES_TAU: 0.5 }));

describe("WhyHerePanel on a static site", () => {
  it("has no reproducible request: there is no API to ask", () => {
    render(<WhyHerePanel entityName="Station" state={{ status: "ok", data: trace("SYN_A", "07:00") }} rules={rules} selectedRuleId={null} onSelectRule={() => {}} />);
    expect(screen.getByRole("heading", { name: /Station/ })).toBeInTheDocument();
    expect(screen.queryByTestId("trace-request")).toBeNull();
    expect(screen.queryByText(/Petición reproducible/)).toBeNull();
    expect(screen.queryByText(/\/api\/v1/)).toBeNull();
  });
});
