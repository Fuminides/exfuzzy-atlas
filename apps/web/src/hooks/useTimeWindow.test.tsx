import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelCard } from "../api/types";
import { LangContext, setLang, type Lang } from "../i18n";
import { useTimeWindow } from "./useTimeWindow";

const coverage = { issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-03-15T00:00:00Z", step_hours: 24, regular: false } as unknown as NonNullable<ModelCard["coverage"]>;

afterEach(() => setLang("es"));

describe("useTimeWindow: the date label", () => {
  it("names the window of an irregular task in the interface language, and sends it again when the language changes", () => {
    const onDate = vi.fn();
    let lang: Lang = "es";
    const wrapper = ({ children }: { children: React.ReactNode }) => <LangContext.Provider value={{ lang, setLang: () => {} }}>{children}</LangContext.Provider>;
    const view = renderHook(() => useTimeWindow({ coverage, irregular: true, zone: "UTC", onDate }), { wrapper });
    expect(onDate).toHaveBeenLastCalledWith("ventana del 1 de marzo de 2025 al 31 de marzo de 2025");
    lang = "en";
    setLang("en");
    view.rerender();
    expect(onDate).toHaveBeenLastCalledWith("window from 1 March 2025 to 31 March 2025");
  });
});
