import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { csvFileName, DEFAULT_SORT, matchesPlace, nextSort, sortRows, toCsv } from "../browse";
import type { Row } from "../live/store";
import { jsonResponse, renderApp, stubFetch } from "./helpers";

function row(overrides: Partial<Row> = {}): Row {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    trackingNumber: "MF0000000001",
    carrier: "ACME",
    origin: "Leeds",
    destination: "Cardiff",
    status: "IN_TRANSIT",
    createdAt: "2026-10-10T12:00:00Z",
    promisedAt: "2026-10-12T12:00:00Z",
    slaBreached: false,
    touchedAt: 0,
    ...overrides,
  };
}

function shipment(n: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `00000000-0000-0000-0000-00000000000${n}`,
    tracking_number: `MF000000000${n}`,
    carrier_code: "ACME",
    origin: "Leeds",
    destination: "Cardiff",
    status: "IN_TRANSIT",
    promised_delivery_at: "2026-10-12T12:00:00Z",
    estimated_delivery_at: null,
    delivered_at: null,
    sla_breached: false,
    created_at: `2026-10-10T12:00:0${n}Z`,
    updated_at: `2026-10-10T12:00:0${n}Z`,
    ...overrides,
  };
}

/** The tracking numbers in the table, top to bottom. */
function tableOrder(): string[] {
  const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
  return rows.map((r) => within(r).getAllByRole("link")[0]?.textContent ?? "");
}

describe("browse helpers", () => {
  it("sorts by each column and keeps ties in the order they came in", () => {
    const a = row({ id: "a", trackingNumber: "MF0000000003", status: "DELIVERED", carrier: "BOLT", promisedAt: "2026-10-13T00:00:00Z" });
    const b = row({ id: "b", trackingNumber: "MF0000000001", status: "CREATED", carrier: "ACME", promisedAt: "2026-10-11T00:00:00Z" });
    const c = row({ id: "c", trackingNumber: "MF0000000002", status: "CREATED", carrier: "ACME", origin: "Antwerp" });
    const ids = (rows: Row[]) => rows.map((r) => r.id);

    expect(ids(sortRows([a, b, c], { key: "trackingNumber", direction: "asc" }))).toEqual(["b", "c", "a"]);
    expect(ids(sortRows([a, b, c], { key: "status", direction: "asc" }))).toEqual(["b", "c", "a"]);
    expect(ids(sortRows([a, b, c], { key: "carrier", direction: "desc" }))).toEqual(["a", "b", "c"]);
    expect(ids(sortRows([a, b, c], { key: "route", direction: "asc" }))).toEqual(["c", "a", "b"]);
    expect(ids(sortRows([a, b, c], { key: "promisedAt", direction: "asc" }))).toEqual(["b", "c", "a"]);
  });

  it("turns the sorted column round and starts a new one ascending", () => {
    expect(nextSort(DEFAULT_SORT, "createdAt")).toEqual({ key: "createdAt", direction: "asc" });
    expect(nextSort({ key: "carrier", direction: "asc" }, "carrier")).toEqual({ key: "carrier", direction: "desc" });
    expect(nextSort({ key: "carrier", direction: "desc" }, "status")).toEqual({ key: "status", direction: "asc" });
  });

  it("matches a place in the origin or the destination, ignoring case", () => {
    expect(matchesPlace(row(), "")).toBe(true);
    expect(matchesPlace(row(), "lee")).toBe(true);
    expect(matchesPlace(row(), " CARD ")).toBe(true);
    expect(matchesPlace(row(), "Lyon")).toBe(false);
  });

  it("writes CSV with quoting, and defuses text a spreadsheet would run", () => {
    const csv = toCsv([row({ origin: 'Port "A", North', destination: "=HYPERLINK(1)" })]);
    const [header, line] = csv.split("\r\n");
    expect(header).toBe("tracking_number,status,carrier_code,origin,destination,promised_delivery_at,created_at,sla_breached,id");
    expect(line).toBe(
      'MF0000000001,IN_TRANSIT,ACME,"Port ""A"", North",\'=HYPERLINK(1),2026-10-12T12:00:00Z,2026-10-10T12:00:00Z,false,11111111-1111-1111-1111-111111111111',
    );
    expect(csv.endsWith("\r\n")).toBe(true);
  });

  it("names the file after the time in UTC", () => {
    expect(csvFileName(new Date("2026-10-18T22:01:05.123Z"))).toBe("shiptrack-shipments-20261018T220105Z.csv");
  });
});

describe("browse page", () => {
  it("sorts when a header is clicked and says which way", async () => {
    stubFetch(
      jsonResponse({
        items: [shipment(1, { carrier_code: "ZZTEST" }), shipment(2, { carrier_code: "ACME" }), shipment(3, { carrier_code: "BOLT" })],
        next_cursor: null,
      }),
    );
    const user = userEvent.setup();
    renderApp("/shipments");
    await screen.findByText(/3 shipments, in step with the server/);

    expect(tableOrder()).toEqual(["MF0000000003", "MF0000000002", "MF0000000001"]);
    expect(screen.getByRole("columnheader", { name: /Created/ })).toHaveAttribute("aria-sort", "descending");

    await user.click(screen.getByRole("button", { name: /Carrier/ }));
    expect(tableOrder()).toEqual(["MF0000000002", "MF0000000003", "MF0000000001"]);
    expect(screen.getByRole("columnheader", { name: /Carrier/ })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("columnheader", { name: /Created/ })).not.toHaveAttribute("aria-sort");

    await user.click(screen.getByRole("button", { name: /Carrier/ }));
    expect(tableOrder()).toEqual(["MF0000000001", "MF0000000003", "MF0000000002"]);
  });

  it("filters by origin or destination", async () => {
    stubFetch(
      jsonResponse({
        items: [shipment(1, { origin: "Lyon" }), shipment(2, { destination: "Bilbao" }), shipment(3)],
        next_cursor: null,
      }),
    );
    const user = userEvent.setup();
    renderApp("/shipments");
    await screen.findByText(/3 shipments, in step with the server/);

    await user.type(screen.getByLabelText("Origin or destination contains"), "bil");
    expect(tableOrder()).toEqual(["MF0000000002"]);
    await user.clear(screen.getByLabelText("Origin or destination contains"));
    await user.type(screen.getByLabelText("Origin or destination contains"), "lyon");
    expect(tableOrder()).toEqual(["MF0000000001"]);
  });

  it("downloads the filtered rows in the table's order", async () => {
    stubFetch(
      jsonResponse({
        items: [shipment(1, { status: "DELIVERED" }), shipment(2), shipment(3)],
        next_cursor: null,
      }),
    );
    let saved: Blob | undefined;
    const createObjectURL = vi.fn((blob: Blob) => {
      saved = blob;
      return "blob:test";
    });
    // jsdom has no object URLs; a subclass keeps the real URL untouched for other tests.
    vi.stubGlobal(
      "URL",
      class extends URL {
        static override createObjectURL = createObjectURL;
        static override revokeObjectURL = vi.fn();
      },
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderApp("/shipments");
    await screen.findByText(/3 shipments, in step with the server/);

    await user.click(within(screen.getByRole("group", { name: "Filter by status" })).getByRole("button", { name: /In transit/ }));
    await user.click(screen.getByRole("button", { name: /Tracking number/ }));
    await user.click(screen.getByRole("button", { name: "Download CSV" }));

    expect(click).toHaveBeenCalledTimes(1);
    const lines = (await saved?.text())?.trim().split("\r\n") ?? [];
    expect(lines).toHaveLength(3);
    expect(lines[1]).toMatch(/^MF0000000002,IN_TRANSIT,/);
    expect(lines[2]).toMatch(/^MF0000000003,IN_TRANSIT,/);
  });

  it("offers no download when nothing matches", async () => {
    stubFetch(jsonResponse({ items: [shipment(1)], next_cursor: null }));
    const user = userEvent.setup();
    renderApp("/shipments");
    await screen.findByText(/1 shipments, in step with the server/);
    await user.type(screen.getByLabelText("Origin or destination contains"), "nowhere");
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();
  });
});
