import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SiteCredits } from "./SiteCredits";

describe("SiteCredits", () => {
  it("names the author with their profiles, credits every data source with its licence and shows the AGPL logo", () => {
    render(<SiteCredits />);
    const block = screen.getByTestId("site-credits");
    expect(block).toHaveTextContent("Javier Fumanal Idocin");
    for (const name of ["Google Scholar", "ORCID", "ex-fuzzy en GitHub", "ex-fuzzy en PyPI", "Código de esta demo"]) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
    for (const source of ["European Environment Agency", "Deutscher Wetterdienst", "Environment Agency", "NYC Taxi & Limousine Commission", "OpenFreeMap"]) {
      expect(screen.getByRole("link", { name: source })).toBeInTheDocument();
    }
    expect(block).toHaveTextContent("CC BY 4.0");
    expect(block).toHaveTextContent("OGL v3.0");
    expect(block).toHaveTextContent("no producidos ni respaldados por NYC ni por la TLC");
    expect(screen.getByRole("img", { name: "GNU AGPL v3" })).toBeInTheDocument();
    expect(block).toHaveTextContent("AGPL-3.0-or-later");
  });
});
