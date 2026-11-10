import { afterEach, describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../errors";
import { staticApi, useStaticSource } from ".";
import { memorySource } from "./source";
import { testExport } from "./testExport";

afterEach(() => useStaticSource(memorySource(testExport())));

describe("staticApi", () => {
  it("has exactly the methods of the live api", () => {
    expect(Object.keys(staticApi).sort()).toEqual(Object.keys(api).sort());
  });

  it("answers through the same call shapes", async () => {
    useStaticSource(memorySource(testExport()));
    expect((await staticApi.domains()).domains.map((d) => d.domain)).toEqual(["air", "water", "mobility"]);
    expect((await staticApi.entities("air", "t-win")).features).toHaveLength(3);
    const trace = await staticApi.ruleTrace("A", "m-win", "2025-03-05T22:00:00Z");
    expect(trace.prediction.label).toBe("Good");
    expect((await staticApi.predictions({ taskId: "t-win", time: "2025-03-05T22:00:00Z" })).features).toHaveLength(3);
  });

  it("raises an ApiError with the API's status, which the UI already handles", async () => {
    useStaticSource(memorySource(testExport()));
    await expect(staticApi.importance("m-mix")).rejects.toBeInstanceOf(ApiError);
    await expect(staticApi.importance("m-mix")).rejects.toMatchObject({ status: 404 });
    await expect(staticApi.ruleStories({ modelId: "m-win", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z", tau: 0.7 })).rejects.toMatchObject({ status: 422 });
  });

  it("has no health to read", async () => {
    await expect(staticApi.health()).rejects.toMatchObject({ status: 404 });
  });
});
