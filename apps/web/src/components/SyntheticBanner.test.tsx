import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SyntheticBanner } from "./SyntheticBanner";

describe("SyntheticBanner", () => {
  it("shows the persistent synthetic-data warning", () => {
    render(<SyntheticBanner show />);
    expect(screen.getByRole("status")).toHaveTextContent("DATOS SINTÉTICOS. No son mediciones reales");
  });
  it("renders nothing for real data", () => {
    const { container } = render(<SyntheticBanner show={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
