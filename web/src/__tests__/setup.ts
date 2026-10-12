import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { clearApiCalls } from "../apiLog";

// The page asks the server which stack it is; no test has a server, so by default there is no answer.
vi.mock("../stackProbe", () => ({ probeStack: () => Promise.resolve(null) }));

// Queries wait up to five seconds for the page to render. The default of one second is too short
// for a loaded CI runner, and a failure there says nothing about the code.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  clearApiCalls();
  localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
