import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { getApiCalls } from "../apiLog";
import { MemoryRouter } from "react-router";
import { TrafficEngine } from "../live/engine";
import { RuntimeProvider } from "../live/runtime";
import { ShipmentStore } from "../live/store";
import { ShipmentsPage } from "../pages/ShipmentsPage";
import { StackProvider } from "../stack";
import { jsonResponse, renderApp, stubFetch, trackView, TRACKING_NUMBER } from "./helpers";

const SID = "11111111-1111-1111-1111-111111111111";

function shipment(overrides: Record<string, unknown> = {}) {
  return {
    id: SID,
    tracking_number: TRACKING_NUMBER,
    carrier_code: "ACME",
    origin: "Leeds",
    destination: "Cardiff",
    status: "IN_TRANSIT",
    promised_delivery_at: "2026-10-12T12:00:00Z",
    estimated_delivery_at: "2026-10-12T08:00:00Z",
    delivered_at: null,
    sla_breached: false,
    created_at: "2026-10-10T12:00:00Z",
    updated_at: "2026-10-10T12:00:00Z",
    ...overrides,
  };
}

function lastCall(fetchMock: ReturnType<typeof stubFetch>) {
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit | undefined][];
  const call = calls[calls.length - 1];
  if (call === undefined) throw new Error("no fetch call");
  return call;
}

describe("shipments page", () => {
  it("loads the list, counts it, and filters by status", async () => {
    const page = {
      items: [
        shipment(),
        shipment({ id: "22222222-2222-2222-2222-22222222222b", tracking_number: "MF0000000002", status: "DELIVERED", carrier_code: "ZZTEST" }),
        shipment({ id: "33333333-3333-3333-3333-33333333333b", tracking_number: "MF0000000003", status: "EXCEPTION" }),
      ],
      next_cursor: null,
    };
    const fetchMock = stubFetch(jsonResponse(page, { stack: "modern" }));
    const user = userEvent.setup();
    renderApp("/shipments");

    expect(await screen.findByText(/3 shipments, in step with the server/)).toBeVisible();
    expect(String(lastCall(fetchMock)[0])).toContain("/api/v1/shipments?limit=100");
    expect(screen.getByRole("link", { name: "MF0000000002" })).toHaveAttribute("href", "/shipments/22222222-2222-2222-2222-22222222222b");
    expect(screen.getByText("Served by: modern")).toBeVisible();

    const group = screen.getByRole("group", { name: "Filter by status" });
    await user.click(within(group).getByRole("button", { name: /Delivered/ }));
    expect(screen.queryByRole("link", { name: TRACKING_NUMBER })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MF0000000002" })).toBeVisible();
  });

  it("keeps reading pages while the API says there is a next cursor", async () => {
    const first = { items: [shipment()], next_cursor: "abc" };
    const second = { items: [shipment({ id: "22222222-2222-2222-2222-22222222222b", tracking_number: "MF0000000002" })], next_cursor: null };
    const fetchMock = stubFetch(jsonResponse(first), jsonResponse(second));
    renderApp("/shipments");
    expect(await screen.findByText(/2 shipments, in step with the server/)).toBeVisible();
    expect(String(lastCall(fetchMock)[0])).toContain("cursor=abc");
  });

  it("reads every page without asking, and has no load-more step", async () => {
    const page = (n: number, next: string | null) =>
      jsonResponse({
        items: [shipment({ id: `00000000-0000-0000-0000-00000000000${n}`, tracking_number: `MF000000000${n}` })],
        next_cursor: next,
      });
    const fetchMock = stubFetch(page(1, "c1"), page(2, "c2"), page(3, null));
    renderApp("/shipments");

    expect(await screen.findByText(/3 shipments, in step with the server/)).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(lastCall(fetchMock)[0])).toContain("cursor=c2");
    expect(screen.getByRole("link", { name: "MF0000000003" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Load .* more/ })).not.toBeInTheDocument();
  });

  it("shows shipments the traffic engine creates and moves, as they change", async () => {
    stubFetch(jsonResponse({ items: [], next_cursor: null }));
    const store = new ShipmentStore();
    const engine = new TrafficEngine({ createShipment: () => Promise.reject(new Error("unused")), postEvent: () => Promise.reject(new Error("unused")), track: () => Promise.reject(new Error("unused")) }, undefined, store);
    render(
      <MemoryRouter initialEntries={["/shipments"]}>
        <RuntimeProvider runtime={{ engine, store }}>
          <StackProvider>
            <ShipmentsPage />
          </StackProvider>
        </RuntimeProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/0 shipments, in step/)).toBeVisible();

    act(() => {
      store.add(
        shipment({ id: "55555555-5555-5555-5555-55555555555b", tracking_number: "MF0000000042", status: "CREATED" }) as never,
        Date.now(),
      );
    });
    expect(await screen.findByRole("link", { name: "MF0000000042" })).toBeVisible();
    expect(screen.getByText("Created", { selector: ".badge" })).toBeVisible();

    act(() => {
      store.setStatus("55555555-5555-5555-5555-55555555555b", "IN_TRANSIT", Date.now());
    });
    expect(await screen.findByText("In transit", { selector: ".badge" })).toBeVisible();
    expect(screen.queryByText("Created", { selector: ".badge" })).not.toBeInTheDocument();
  });

  it("says why it stopped when the API fails", async () => {
    stubFetch(jsonResponse({ error: { code: "INTERNAL", message: "boom", request_id: "r1" } }, { status: 500 }));
    renderApp("/shipments");
    expect(await screen.findByText(/0 shipments. The last sync failed: boom/)).toBeVisible();
  });
});

describe("new shipment page", () => {
  it("creates a shipment with an upper-cased carrier and shows the tracking number", async () => {
    const fetchMock = stubFetch(jsonResponse(shipment({ status: "CREATED" }), { status: 201, stack: "modern" }));
    const user = userEvent.setup();
    renderApp("/shipments/new");
    const carrier = screen.getByLabelText("Carrier code");
    await user.clear(carrier);
    await user.type(carrier, "acme");
    await user.click(screen.getByRole("button", { name: /Create shipment/ }));

    expect(await screen.findByText(`Created ${TRACKING_NUMBER}`)).toBeVisible();
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe("/api/v1/shipments");
    expect(init?.method).toBe("POST");
    expect(typeof init?.body).toBe("string");
    const body = JSON.parse(init?.body as string) as Record<string, string>;
    expect(body.carrier_code).toBe("ACME");
    expect(body.promised_delivery_at).toMatch(/Z$/);
    expect(screen.getByRole("link", { name: "Open the shipment" })).toHaveAttribute("href", `/shipments/${SID}`);
  });

  it("shows the error the API sends", async () => {
    stubFetch(jsonResponse({ error: { code: "UNKNOWN_CARRIER", message: "Unknown carrier code: NOPE", request_id: "req-9" } }, { status: 422 }));
    const user = userEvent.setup();
    renderApp("/shipments/new");
    await user.click(screen.getByRole("button", { name: /Create shipment/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown carrier code: NOPE");
    expect(screen.getByText(/UNKNOWN_CARRIER/)).toBeVisible();
  });

  it("does not call the API when a field is empty", async () => {
    const fetchMock = stubFetch(jsonResponse({}));
    const user = userEvent.setup();
    renderApp("/shipments/new");
    await user.clear(screen.getByLabelText("Origin"));
    await user.click(screen.getByRole("button", { name: /Create shipment/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("required");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("shipment page", () => {
  it("shows the shipment, its progress, and its history", async () => {
    // First the shipment, then its track view.
    stubFetch(jsonResponse(shipment()), jsonResponse(trackView()));
    renderApp(`/shipments/${SID}`);
    expect(await screen.findByRole("heading", { name: TRACKING_NUMBER })).toBeVisible();
    expect(screen.getByRole("img", { name: "Progress: In transit" })).toBeVisible();
    expect(screen.getByText(/Leeds/)).toBeVisible();
    expect(await screen.findByText("Hamburg")).toBeVisible();
  });

  it("sends an event with an Idempotency-Key and says it was queued", async () => {
    const fetchMock = stubFetch(
      jsonResponse(shipment()),
      jsonResponse(trackView()),
      jsonResponse({ accepted: true, idempotency_key: "ui-x" }, { status: 202 }),
    );
    const user = userEvent.setup();
    renderApp(`/shipments/${SID}`);
    await screen.findByRole("heading", { name: TRACKING_NUMBER });
    await user.click(screen.getByRole("button", { name: /Send event/ }));

    expect(await screen.findByText(/Accepted \(202\)/)).toBeVisible();
    const post = (fetchMock.mock.calls as unknown as [string, RequestInit][]).find(([, init]) => init?.method === "POST");
    expect(post).toBeDefined();
    const headers = post?.[1].headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^ui-[0-9a-f]{32}$/);
    expect(post?.[0]).toBe(`/api/v1/shipments/${SID}/events`);
  });

  it("refuses a file that is not a PDF or an image, without calling the API", async () => {
    const fetchMock = stubFetch(jsonResponse(shipment()), jsonResponse(trackView()));
    const user = userEvent.setup({ applyAccept: false });
    renderApp(`/shipments/${SID}`);
    await screen.findByRole("heading", { name: TRACKING_NUMBER });
    const calls = fetchMock.mock.calls.length;
    await user.upload(screen.getByLabelText("Document"), new File(["x"], "notes.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: /Upload/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only PDF, PNG, and JPEG");
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("uploads a document and offers it for opening", async () => {
    const proof = { document_id: "44444444-4444-4444-4444-44444444444b", shipment_id: SID, content_type: "application/pdf", size_bytes: 2048, sha256: "a".repeat(64), uploaded_at: "2026-10-11T12:00:00Z" };
    stubFetch(jsonResponse(shipment()), jsonResponse(trackView()), jsonResponse(proof, { status: 201 }));
    const user = userEvent.setup();
    renderApp(`/shipments/${SID}`);
    await screen.findByRole("heading", { name: TRACKING_NUMBER });
    await user.upload(screen.getByLabelText("Document"), new File(["%PDF"], "proof.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: /Upload/ }));
    const link = await screen.findByRole("link", { name: "Open document" });
    expect(link).toHaveAttribute("href", `/api/v1/shipments/${SID}/pod/${proof.document_id}`);
  });

  it("says so when the shipment is not found", async () => {
    stubFetch(jsonResponse({ error: { code: "NOT_FOUND", message: "Shipment not found", request_id: null } }, { status: 404 }));
    renderApp(`/shipments/${SID}`);
    expect(await screen.findByText("Shipment not found", { selector: "p" })).toBeVisible();
  });
});

describe("system page and the activity panel", () => {
  it("shows readiness and the stack that answered", async () => {
    stubFetch(jsonResponse({ ready: true, reason: null }, { stack: "modern" }));
    renderApp("/system");
    expect(await screen.findByText("Ready")).toBeVisible();
    expect(screen.getByText("modern", { selector: ".stat-value" })).toBeVisible();
  });

  it("lists the calls the page has made, with their bodies", async () => {
    stubFetch(jsonResponse(trackView(), { stack: "legacy" }));
    const user = userEvent.setup();
    renderApp(`/track/${TRACKING_NUMBER}`);
    await screen.findByText("In transit", { selector: ".badge" });
    await user.click(screen.getByRole("button", { name: /API activity/ }));

    const panel = screen.getByRole("complementary", { name: "API activity" });
    expect(within(panel).getByText(`/api/v1/track/${TRACKING_NUMBER}`)).toBeVisible();
    expect(within(panel).getByText("200")).toBeVisible();
    expect(getApiCalls()[0]?.stack).toBe("legacy");
    await act(async () => {
      await user.click(within(panel).getByText("Clear"));
    });
    await waitFor(() => {
      expect(within(panel).getByText(/No calls yet/)).toBeVisible();
    });
  });
});

describe("shipment store", () => {
  const row = (id: string, createdAt: string) =>
    shipment({ id, tracking_number: `MF${id.replace(/\D/g, "").padStart(10, "0")}`, created_at: createdAt });

  it("drops what a complete read no longer lists, and keeps what was touched during it", () => {
    const store = new ShipmentStore();
    store.merge([row("s1", "2026-10-10T10:00:00Z"), row("s2", "2026-10-10T11:00:00Z")] as never, 1_000);
    store.add(row("s3", "2026-10-10T12:00:00Z") as never, 5_000);

    // A read began at 4_000 and listed only s2: s1 was deleted, and s3 arrived after the read began.
    store.retain(new Set(["s2"]), 4_000);

    expect(store.getRows().map((r) => r.id).sort()).toEqual(["s2", "s3"]);
  });

  it("keeps everything the read listed", () => {
    const store = new ShipmentStore();
    store.merge([row("s1", "2026-10-10T10:00:00Z")] as never, 1_000);
    store.retain(new Set(["s1"]), 9_000);
    expect(store.size).toBe(1);
  });
});
