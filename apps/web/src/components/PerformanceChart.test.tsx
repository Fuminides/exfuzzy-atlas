import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { ModelCard } from "../api/types";
import { setLang } from "../i18n";
import * as fx from "../test/fixturesReal";
import { PerformanceChart } from "./PerformanceChart";

afterEach(() => setLang("es"));

const row = (estimator: string, metric: string, value: number, slice = "all") => ({ estimator, metric, value, n: 100, slice });
const asCard = (rows: ReturnType<typeof row>[], classifier: boolean) => ({ target_scheme: classifier ? { classes: [] } : null, metrics: { rows } }) as unknown as ModelCard;
// the water model's test-period mean error: random forest 0.548, ExFuzzy 0.635, ridge 0.659 (lower is better)
const waterCard = asCard([row("exfuzzy", "mae", 0.635), row("ridge", "mae", 0.659), row("ridge", "mae", 0.7, "validation/all"), row("random_forest", "mae", 0.548), row("random_forest", "mae", 0.6, "validation/all")], false);
const classCard = asCard([
  row("exfuzzy_classifier", "macro_f1", 0.41), row("exfuzzy_classifier", "accuracy", 0.82),
  row("persistence", "macro_f1", 0.29), row("persistence", "accuracy", 0.77),
  row("logistic_regression", "macro_f1", 0.5), row("logistic_regression", "macro_f1", 0.5, "validation/all"), row("logistic_regression", "accuracy", 0.84),
], true);
const water = () => <PerformanceChart card={waterCard} rules={fx.water.rules} period="2025" unit="mg/l" context="Ríos · misma muestra" />;
const nyc = () => <PerformanceChart card={classCard} rules={fx.nyc.rules} period="2025" unit="" context="Nueva York · +1 h" />;

describe("the performance report's reading aid", () => {
  it("an error metric says «menos es mejor» next to the toggle's place, a score «más es mejor»", async () => {
    const { unmount } = render(water());
    expect(screen.getByTestId("perf-bars")).toHaveAttribute("data-metric", "mae");
    expect(screen.getByTestId("perf-direction")).toHaveTextContent("menos es mejor");
    expect(screen.getByTestId("perf-direction")).toHaveAttribute("data-higher-is-better", "false");
    expect(document.querySelector(".report-foot")).not.toHaveTextContent(/es mejor/); // said once, where the eye lands
    unmount();
    render(nyc());
    expect(screen.getByTestId("perf-direction")).toHaveTextContent("más es mejor");
    await userEvent.setup().click(screen.getByRole("button", { name: "Acierto" }));
    expect(screen.getByTestId("perf-direction")).toHaveTextContent("más es mejor");
  });

  it("in English", () => {
    setLang("en");
    render(water());
    expect(screen.getByTestId("perf-direction")).toHaveTextContent("lower is better");
  });
});

describe("baseline names inside the verdict and the chips", () => {
  it("English: lower case with consistent articles, bar labels keep their capitals", () => {
    setLang("en");
    render(water());
    const verdict = document.querySelector(".hero-verdict")!.textContent!;
    expect(verdict).toMatch(/beats [^;]*linear regression/);
    expect(verdict).toMatch(/the random forest/);
    expect(verdict).not.toMatch(/Random forest|Linear regression|Logistic regression/);
    const chips = [...screen.getByTestId("perf-standing").querySelectorAll("li")].map((li) => li.textContent);
    expect(chips.join("|")).toMatch(/than the random forest/);
    expect(chips.join("|")).not.toMatch(/Random forest|Linear regression/);
    expect(within(screen.getByTestId("perf-bars")).getByText("Random forest")).toBeInTheDocument();
  });

  it("Spanish: «la regresión lineal», «el Random Forest», with the article contracted", () => {
    render(water());
    const text = `${document.querySelector(".hero-verdict")!.textContent} ${screen.getByTestId("perf-standing").textContent}`;
    expect(text).toMatch(/regresión lineal/);
    expect(text).toMatch(/del Random Forest/);
    expect(text).not.toMatch(/bosque aleatorio|Random forest|Linear regression|\bde el\b|\ba el\b/);
    expect(within(screen.getByTestId("perf-bars")).getByText("Random Forest")).toBeInTheDocument(); // Spanish label
  });

  it("a classifier names logistic regression", () => {
    setLang("en");
    render(nyc());
    const text = `${document.querySelector(".hero-verdict")!.textContent} ${screen.getByTestId("perf-standing").textContent}`;
    expect(text).toMatch(/logistic regression/);
    expect(text).not.toMatch(/Logistic regression/);
  });
});
