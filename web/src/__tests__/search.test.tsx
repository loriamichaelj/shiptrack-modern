import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SEARCH_ERROR } from "../pages/SearchPage";
import { calledUrls, jsonResponse, renderApp, routedFetch, trackView, TRACKING_NUMBER } from "./helpers";

const EMPTY_LIST = jsonResponse({ items: [], next_cursor: null }, { stack: "modern" });

function listed(number: number, createdAt: string, status = "CREATED") {
  const tracking = `MF${String(number).padStart(10, "0")}`;
  return {
    id: `ship-${number}`,
    tracking_number: tracking,
    carrier_code: "ACME",
    origin: "Leeds",
    destination: "Cardiff",
    status,
    promised_delivery_at: "2026-10-14T00:00:00Z",
    estimated_delivery_at: null,
    delivered_at: null,
    sla_breached: false,
    created_at: createdAt,
    updated_at: createdAt,
  };
}

describe("search page", () => {
  it("renders a labelled input", () => {
    routedFetch([["/api/v1/shipments", EMPTY_LIST]]);
    renderApp("/");
    expect(screen.getByRole("heading", { name: "Track a shipment" })).toBeInTheDocument();
    const input = screen.getByLabelText("Tracking number");
    expect(input).toHaveAttribute("type", "text");
    expect(input).not.toHaveAttribute("aria-invalid", "true");
  });

  it.each(["", "   ", "MF123", "hello", "MF01234567890", "XX0123456789"])(
    "shows an inline error for invalid input %j and does not call the API",
    async (value) => {
      const fetchMock = routedFetch([["/api/v1/shipments", EMPTY_LIST]]);
      const user = userEvent.setup();
      renderApp("/");
      if (value) await user.type(screen.getByLabelText("Tracking number"), value);
      await user.click(screen.getByRole("button", { name: "Track" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(SEARCH_ERROR);
      expect(screen.getByLabelText("Tracking number")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByRole("heading", { name: "Track a shipment" })).toBeInTheDocument();
      expect(calledUrls(fetchMock).filter((url) => url.includes("/api/v1/track/"))).toEqual([]);
    },
  );

  it("navigates to the tracking page for a valid number, normalizing case and spacing", async () => {
    const fetchMock = routedFetch([
      ["/api/v1/track/", jsonResponse(trackView(), { stack: "legacy" })],
      ["/api/v1/shipments", EMPTY_LIST],
    ]);
    const user = userEvent.setup();
    renderApp("/");
    await user.type(screen.getByLabelText("Tracking number"), "  mf0123456789 ");
    await user.click(screen.getByRole("button", { name: "Track" }));

    expect(await screen.findByRole("heading", { name: `Shipment ${TRACKING_NUMBER}` })).toBeVisible();
    await waitFor(() => {
      expect(calledUrls(fetchMock).filter((url) => url.includes("/api/v1/track/"))).toHaveLength(1);
    });
  });

  it("submits with the Enter key", async () => {
    routedFetch([
      ["/api/v1/track/", jsonResponse(trackView())],
      ["/api/v1/shipments", EMPTY_LIST],
    ]);
    const user = userEvent.setup();
    renderApp("/");
    await user.type(screen.getByLabelText("Tracking number"), `${TRACKING_NUMBER}{Enter}`);
    expect(await screen.findByRole("heading", { name: `Shipment ${TRACKING_NUMBER}` })).toBeVisible();
  });
  it("offers the five newest shipments the server has, newest first", async () => {
    // The API lists oldest first, so the newest are on the last page.
    const items = [1, 2, 3, 4, 5, 6, 7].map((n) => listed(n, `2026-10-11T0${n}:00:00Z`));
    routedFetch([["/api/v1/shipments", jsonResponse({ items, next_cursor: null }, { stack: "modern" })]]);
    renderApp("/");

    const recent = await screen.findByText("Recent");
    const links = await waitFor(() => {
      const found = within(recent.parentElement as HTMLElement).getAllByRole("link");
      expect(found).toHaveLength(5);
      return found;
    });
    expect(links.map((l) => l.textContent)).toEqual([
      "MF0000000007", "MF0000000006", "MF0000000005", "MF0000000004", "MF0000000003",
    ]);
    expect(links[0]).toHaveAttribute("href", "/track/MF0000000007");
  });

  it("offers nothing when the server has no shipments, and ignores what was typed here before", async () => {
    localStorage.setItem("shiptrack.recent", JSON.stringify(["MF2060803593"]));
    routedFetch([["/api/v1/shipments", EMPTY_LIST]]);
    renderApp("/");

    await screen.findByRole("heading", { name: "Track a shipment" });
    await waitFor(() => {
      expect(screen.queryByText("Recent")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("MF2060803593")).not.toBeInTheDocument();
  });
});
