import { describe, expect, it } from "vitest";
import type { Shipment } from "../client";
import { newIdempotencyKey } from "../keys";
import { isOverdue, relativeTime, summarize } from "../stats";

const NOW = Date.parse("2026-10-11T12:00:00Z");

function shipment(overrides: Partial<Shipment> = {}): Shipment {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    tracking_number: "MF0000000001",
    carrier_code: "ACME",
    origin: "Leeds",
    destination: "Cardiff",
    status: "IN_TRANSIT",
    promised_delivery_at: "2026-10-12T12:00:00Z",
    estimated_delivery_at: null,
    delivered_at: null,
    sla_breached: false,
    created_at: "2026-10-10T12:00:00Z",
    updated_at: "2026-10-10T12:00:00Z",
    ...overrides,
  };
}

describe("summarize", () => {
  it("counts by status and carrier, and the overdue ones", () => {
    const summary = summarize(
      [
        shipment(),
        shipment({ status: "DELIVERED", promised_delivery_at: "2026-10-01T00:00:00Z" }),
        shipment({ carrier_code: "ZZTEST", promised_delivery_at: "2026-10-01T00:00:00Z", sla_breached: true }),
        shipment({ carrier_code: "ZZTEST", status: "EXCEPTION" }),
      ],
      NOW,
    );
    expect(summary.total).toBe(4);
    expect(summary.byStatus.IN_TRANSIT).toBe(2);
    expect(summary.byStatus.DELIVERED).toBe(1);
    expect(summary.overdue).toBe(1); // delivered ones are never overdue
    expect(summary.breached).toBe(1);
    expect(summary.deliveredShare).toBe(0.25);
    expect(summary.byCarrier).toEqual([
      { carrier: "ZZTEST", count: 2 },
      { carrier: "ACME", count: 2 },
    ].sort((a, b) => a.carrier.localeCompare(b.carrier)).sort((a, b) => b.count - a.count));
  });

  it("is all zeros for no shipments", () => {
    const summary = summarize([], NOW);
    expect(summary.total).toBe(0);
    expect(summary.deliveredShare).toBe(0);
    expect(summary.byCarrier).toEqual([]);
  });
});

describe("isOverdue", () => {
  it("is past the promise and not delivered", () => {
    const late = shipment({ promised_delivery_at: "2026-10-11T11:00:00Z" });
    expect(isOverdue(late, NOW)).toBe(true);
    expect(isOverdue({ ...late, status: "DELIVERED" }, NOW)).toBe(false);
    expect(isOverdue(shipment(), NOW)).toBe(false);
  });
});

describe("relativeTime", () => {
  it.each([
    ["2026-10-14T12:00:00Z", "in 3 days"],
    ["2026-10-11T10:00:00Z", "2 hours ago"],
    ["2026-10-11T12:30:00Z", "in 30 minutes"],
    ["2026-10-11T12:00:20Z", "just now"],
    [null, "—"],
  ])("%s is %s", (iso, expected) => {
    expect(relativeTime(iso, NOW)).toBe(expected);
  });
});

describe("newIdempotencyKey", () => {
  it("is random, within the API's 64 characters, and works without randomUUID", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).not.toBe(b);
    expect(a.length).toBeLessThanOrEqual(64);
    expect(a).toMatch(/^ui-[0-9a-f]{32}$/);
  });
});
