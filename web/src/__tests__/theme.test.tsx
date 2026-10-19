import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readTheme, saveTheme } from "../theme";
import { jsonResponse, renderApp, stubFetch } from "./helpers";

const root = document.documentElement;

afterEach(() => {
  delete root.dataset.theme;
});

describe("theme", () => {
  it("follows the system when nothing is stored", () => {
    expect(readTheme()).toBe("system");
    applyTheme(readTheme());
    expect(root.dataset.theme).toBeUndefined();
  });

  it("applies and remembers a choice, and forgets it for system", () => {
    saveTheme("dark");
    expect(root.dataset.theme).toBe("dark");
    expect(localStorage.getItem("shiptrack.theme")).toBe("dark");
    expect(readTheme()).toBe("dark");

    saveTheme("system");
    expect(root.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("shiptrack.theme")).toBeNull();
  });

  it("ignores a stored value it does not know", () => {
    localStorage.setItem("shiptrack.theme", "sepia");
    expect(readTheme()).toBe("system");
  });

  it("still switches when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readTheme()).toBe("system");
    saveTheme("light");
    expect(root.dataset.theme).toBe("light");
  });

  it("switches from the header and shows which choice is on", async () => {
    stubFetch(jsonResponse({ items: [], next_cursor: null }));
    localStorage.setItem("shiptrack.theme", "light");
    renderApp("/");

    const group = screen.getByRole("group", { name: "Theme" });
    expect(within(group).getByRole("button", { name: "Light theme" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(within(group).getByRole("button", { name: "Dark theme" }));
    expect(root.dataset.theme).toBe("dark");
    expect(within(group).getByRole("button", { name: "Dark theme" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "Light theme" })).toHaveAttribute("aria-pressed", "false");
    expect(localStorage.getItem("shiptrack.theme")).toBe("dark");
  });
});
