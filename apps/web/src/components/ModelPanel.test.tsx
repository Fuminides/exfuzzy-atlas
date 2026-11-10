import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { MetricRow, MetricsReport, ModelCard } from "../api/types";
import { card } from "../test/fixtures";
import * as cls from "../test/fixturesClass";
import { ModelPanel } from "./ModelPanel";

const split = card.manifest.split;
const row = (estimator: string, metric: string, value: number, n = 5000, slice?: string): MetricRow => ({ estimator, metric, value, n, ...(slice ? { slice } : {}) });
const report: MetricsReport = {
  model_id: card.manifest.model_id,
  task_id: card.manifest.task_id,
  split,
  rows: [
    row("exfuzzy", "mae", 7.5), row("exfuzzy", "rmse", 10.25), row("exfuzzy", "r2", 0.5),
    row("exfuzzy", "n_rules", 18, 18), row("exfuzzy", "fraction_fallback", 0.01),
    row("persistence", "mae", 8.5), row("persistence", "rmse", 11.5), row("persistence", "r2", 0.4),
    row("climatology", "mae", 12), row("climatology", "rmse", 15), row("climatology", "r2", 0),
    row("ridge", "mae", 7.5), row("ridge", "rmse", 9.75), row("ridge", "r2", 0.55),
    row("hist_gradient_boosting", "mae", 7.0), row("hist_gradient_boosting", "rmse", 9.5), row("hist_gradient_boosting", "r2", 0.6),
    row("exfuzzy", "mae", 99, 10, "entity=X"),
  ],
};
const withMetrics = (m: MetricsReport | null, warnings?: string[]): ModelCard => ({
  ...card,
  data_version: "madrid-2025-test",
  metrics: m,
  manifest: { ...card.manifest, warnings: warnings ?? card.manifest.warnings },
});

describe("ModelPanel", () => {
  it("renders ExFuzzy against the baselines on the test split with MAE, RMSE and R²", () => {
    render(<ModelPanel card={withMetrics(report)} open />);
    const table = screen.getByRole("table", { name: /Mismo periodo de prueba/ });
    const head = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(head).toEqual(["Estimador", "MAE", "RMSE", "R²", "n"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent("ExFuzzy"); // ExFuzzy first, baselines after
    const exfuzzy = within(rows[0]!).getAllByRole("cell").map((c) => c.getAttribute("data-best") ?? "");
    expect(within(rows[0]!).getByText("7,500")).toHaveAttribute("data-raw", "7.5");
    expect(rows[0]).toHaveTextContent("0,500");
    expect(exfuzzy.some((x) => x === "true")).toBe(false);
    expect(rows[1]).toHaveTextContent("Persistencia");
    expect(rows[1]).toHaveTextContent("8,500");
    // The per-entity slice row is not mixed into the overall table.
    expect(table).not.toHaveTextContent("99,000");
  });

  it("marks the most favourable value of a column only when it is unique, with no disclaimer", () => {
    render(<ModelPanel card={withMetrics(report)} open />);
    const table = screen.getByRole("table", { name: /Mismo periodo de prueba/ });
    const best = [...table.querySelectorAll('td[data-best="true"]')].map((td) => td.textContent);
    // MAE: exfuzzy and ridge tie at 7.5 but HGB's 7.0 is unique; RMSE and R²: HGB too.
    expect(best).toEqual(["7,000", "9,500", "0,600"]);
    expect(screen.getByText(/En negrita, el valor más favorable de cada columna/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/No dice que ese estimador/);
  });

  it("shows the split dates from the manifest, the data_version and the warnings", () => {
    render(<ModelPanel card={withMetrics(report, ["154 test rows dropped for a missing feature"])} open />);
    expect(screen.getByText(`[${split.test_from_utc.slice(0, 10)} 00:00 UTC, ${split.test_to_utc.slice(0, 10)} 00:00 UTC)`)).toBeInTheDocument();
    expect(screen.getByText("madrid-2025-test")).toBeInTheDocument();
    expect(screen.getByText("154 test rows dropped for a missing feature")).toBeInTheDocument();
    expect(screen.getByText(`${split.embargo_hours} h`)).toBeInTheDocument();
  });

  it("is neutral: no 'best model' or causal wording", () => {
    const { container } = render(<ModelPanel card={withMetrics(report)} open />);
    expect(container.textContent).not.toMatch(/mejor modelo|ganador|causa|porque/i);
  });

  it("says so when the model publishes no metrics, and warns if the report's split differs", () => {
    const { rerender } = render(<ModelPanel card={withMetrics(null)} open />);
    expect(screen.getByText("Este modelo no publica métricas de evaluación.")).toBeInTheDocument();
    rerender(<ModelPanel card={withMetrics({ ...report, split: { ...split, embargo_hours: split.embargo_hours + 1 } })} open />);
    expect(screen.getByText(/no coincide con la del manifiesto/)).toBeInTheDocument();
  });
});

describe("ModelPanel for a classifier", () => {
  it("renders the classification metrics against the baselines, per-class detail and a confusion matrix", () => {
    const card = { ...cls.card, metrics: cls.icaMetrics, target_scheme: cls.icaScheme };
    render(<ModelPanel card={card} open />);
    const table = screen.getByRole("table", { name: /Mismo periodo de prueba/ });
    expect(within(table).getByRole("columnheader", { name: "F1 macro" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "MAE" })).toBeNull();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(7); // ExFuzzy and 6 baselines
    // ExFuzzy first, values as published (raw kept in data-raw).
    expect(rows[0]).toHaveTextContent("ExFuzzy (clasificador)");
    const f1 = cls.icaMetrics.rows.find((r) => r.estimator === "exfuzzy_classifier" && r.metric === "macro_f1")!;
    expect(rows[0]!.querySelector("[data-raw]")).toHaveAttribute("data-raw", String(f1.value));
    // Neutral: the best of a column is marked only where unique, and ExFuzzy is not marked in macro-F1.
    const best = within(table).getAllByRole("cell").filter((c) => c.getAttribute("data-best") === "true");
    expect(best.length).toBeGreaterThan(0);
    expect(rows[0]!.querySelector('[data-best="true"]')).toBeNull();

    const perClass = screen.getByRole("table", { name: /Por categoría observada/ });
    const last = within(perClass).getByRole("row", { name: /Desfavorable o peor/ });
    expect(last).toHaveTextContent("81"); // observed rows in the test period
    const recall = cls.icaMetrics.rows.find((r) => r.estimator === "exfuzzy_classifier" && r.metric === "recall[Desfavorable o peor]")!;
    expect(recall.n).toBe(81);
    expect(last.querySelectorAll("[data-raw]")[0]).toHaveAttribute("data-raw", String(recall.value));

    const confusion = screen.getByRole("table", { name: /Matriz de confusión/ });
    const buena = within(confusion).getByRole("row", { name: /^Buena/ });
    expect(buena.querySelector('td[data-diagonal="true"]')).toHaveAttribute("data-raw", "120605");
    expect(within(confusion).getByRole("columnheader", { name: "sin predicción" })).toBeInTheDocument();
  });

  it("switches the per-class detail to a baseline", async () => {
    render(<ModelPanel card={{ ...cls.card, metrics: cls.icaMetrics, target_scheme: cls.icaScheme }} open />);
    await userEvent.setup().selectOptions(screen.getByLabelText("Estimador para el detalle por categoría"), "persistence");
    const confusion = screen.getByRole("table", { name: /Matriz de confusión/ });
    const p = cls.icaMetrics.rows.find((r) => r.estimator === "persistence" && r.metric === "confusion[Buena>Buena]")!;
    expect(within(confusion).getByRole("row", { name: /^Buena/ }).querySelector('td[data-diagonal="true"]')).toHaveAttribute("data-raw", String(p.value));
  });

  it("works with the synthetic classifier (no baselines)", () => {
    render(<ModelPanel card={cls.card} open />);
    expect(within(screen.getByRole("table", { name: /Mismo periodo de prueba/ })).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Clasificación en el periodo de prueba" })).toBeInTheDocument();
  });
});
