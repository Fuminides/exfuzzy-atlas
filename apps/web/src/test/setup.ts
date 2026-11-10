import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// findBy*/waitFor wait up to 1 s by default; with the whole suite running in parallel on a busy machine that is flaky.
configure({ asyncUtilTimeout: 4000 });
