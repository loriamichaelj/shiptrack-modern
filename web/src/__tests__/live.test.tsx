import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_STOP_MS, CARRIERS, MAX_CREATED, percentile, TrafficEngine, type TrafficApi } from "../live/engine";
import { RuntimeProvider } from "../live/runtime";
import { ShipmentStore } from "../live/store";
import { LivePage } from "../pages/LivePage";
import { StackProvider } from "../stack";

/** A fake API that applies each event after a fixed delay, like a queue and a worker would. */
function shipmentRow(id: string, trackingNumber: string) {
  return {
    id,
    tracking_number: trackingNumber,
    carrier_code: "ZZTEST",
    origin: "Leeds",
    destination: "Cardiff",
    status: "CREATED" as const,
    promised_delivery_at: "2026-10-14T00:00:00Z",
    estimated_delivery_at: null,
    delivered_at: null,
    sla_breached: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function fakeApi(
  options: { applyAfterMs?: number; failCreate?: boolean; neverApply?: boolean; postDelayMs?: number } = {},
) {
  const applyAfter = options.applyAfterMs ?? 300;
  const status = new Map<string, string>();
  const accepted: { id: string; type: string; key: string; at: number }[] = [];
  const carriers: string[] = [];
  let seq = 0;
  const api: TrafficApi = {
    createShipment(carrier) {
      carriers.push(carrier);
      if (options.failCreate === true) {
        return Promise.resolve({ ok: false as const, message: "boom", status: 500 });
      }
      seq += 1;
      const id = `id-${seq}`;
      status.set(id, "CREATED");
      return Promise.resolve({
        ok: true as const,
        shipment: shipmentRow(id, `MF${String(seq).padStart(10, "0")}`),
        stack: "modern",
      });
    },
    postEvent(id, type, _location, key) {
      accepted.push({ id, type, key, at: Date.now() });
      if (options.neverApply !== true) {
        setTimeout(() => {
          status.set(id, type);
        }, applyAfter);
      }
      const answer = { ok: true as const, stack: "modern" };
      if (options.postDelayMs === undefined) return Promise.resolve(answer);
      // A slow write, so that other dispatches run while this one is waiting.
      return new Promise((resolve) => {
        setTimeout(() => {
          resolve(answer);
        }, options.postDelayMs);
      });
    },
    track(trackingNumber) {
      const id = `id-${Number(trackingNumber.slice(2))}`;
      return Promise.resolve({ ok: true as const, status: (status.get(id) ?? "CREATED") as never, stack: "modern" });
    },
  };
  return { api, accepted, carriers };
}

/** A small deterministic generator, so that a test never depends on luck. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

const SEEDS = [1, 2, 3, 7, 42];

function engineFor(api: TrafficApi, seed = 1, store: ShipmentStore | null = null): TrafficEngine {
  return new TrafficEngine(api, { now: () => Date.now(), random: seeded(seed) }, store);
}

describe("percentile", () => {
  it("is the value at that rank, and zero for nothing", () => {
    expect(percentile([], 95)).toBe(0);
    expect(percentile([10, 20, 30, 40], 50)).toBe(20);
    expect(percentile([10, 20, 30, 40], 95)).toBe(40);
  });
});

describe("traffic engine", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function run(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it.each(SEEDS)("creates shipments, moves them through their statuses, and sees the events applied (seed %i)", async (seed) => {
    const { api } = fakeApi();
    const engine = engineFor(api, seed);
    engine.setRate(15);
    engine.start();
    await run(30_000);
    engine.stop();
    const snap = engine.getSnapshot();

    expect(snap.totals.created).toBeGreaterThan(5);
    expect(snap.totals.eventsSent).toBeGreaterThan(10);
    expect(snap.totals.applied).toBeGreaterThan(5);
    expect(snap.totals.errors).toBe(0);
    expect(snap.board.some((c) => c.status === "DELIVERED" || c.status === "IN_TRANSIT")).toBe(true);
    expect(snap.applyLag.samples).toBeGreaterThan(0);
    // The fake worker takes 300 ms, so the lag seen is at least that and well under the wait.
    expect(snap.applyLag.p50).toBeGreaterThanOrEqual(300);
    expect(snap.applyLag.p50).toBeLessThan(5_000);
    expect(snap.stack).toBe("modern");
    expect(snap.feed.length).toBeGreaterThan(0);
  });

  it("keeps to the chosen rate", async () => {
    const { api } = fakeApi();
    const engine = engineFor(api);
    engine.setRate(4);
    engine.start();
    await run(10_000);
    engine.stop();
    const { requests } = engine.getSnapshot().totals;
    expect(requests).toBeGreaterThanOrEqual(30);
    expect(requests).toBeLessThanOrEqual(46);
  });

  it("clamps the rate", () => {
    const engine = engineFor(fakeApi().api);
    engine.setRate(500);
    expect(engine.getSnapshot().rate).toBe(20);
    engine.setRate(0);
    expect(engine.getSnapshot().rate).toBe(1);
  });

  it("counts a failed call as an error and says so in the feed", async () => {
    const engine = engineFor(fakeApi({ failCreate: true }).api);
    engine.setRate(5);
    engine.start();
    await run(3_000);
    engine.stop();
    const snap = engine.getSnapshot();
    expect(snap.totals.errors).toBeGreaterThan(0);
    expect(snap.totals.created).toBe(0);
    expect(snap.feed[0]).toMatchObject({ kind: "error", ok: false });
  });

  it.each(SEEDS)("repeats an Idempotency-Key now and then and counts it as a repeat (seed %i)", async (seed) => {
    const { api, accepted } = fakeApi();
    const engine = engineFor(api, seed);
    engine.setRate(20);
    engine.start();
    await run(60_000);
    engine.stop();
    const keys = accepted.map((a) => a.key);
    expect(new Set(keys).size).toBeLessThan(keys.length);
    expect(engine.getSnapshot().totals.duplicates).toBeGreaterThan(0);
  });

  it.each(SEEDS)("reports an event that is accepted and never shown, instead of waiting for it (seed %i)", async (seed) => {
    const engine = engineFor(fakeApi({ neverApply: true }).api, seed);
    engine.setRate(10);
    engine.start();
    await run(60_000);
    engine.stop();
    const snap = engine.getSnapshot();
    expect(snap.totals.applied).toBe(0);
    expect(snap.feed.some((f) => /not applied after 30 s/.test(f.text))).toBe(true);
  });

  it("keeps the rate when its timer is slowed, as a background tab's is", async () => {
    // A tab in the background runs timers about once a second, not ten times.
    vi.useRealTimers();
    vi.useFakeTimers();
    const engine = engineFor(fakeApi().api);
    engine.setRate(10);
    engine.start();
    for (let i = 0; i < 20; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    engine.stop();
    // Twenty seconds at ten a second, with a tick a second: about 200, never about 20.
    expect(engine.getSnapshot().totals.requests).toBeGreaterThan(120);
  });

  it("writes what it creates and reads to the shipment store, which the other pages show", async () => {
    const store = new ShipmentStore();
    const engine = engineFor(fakeApi().api, 3, store);
    engine.setRate(15);
    engine.start();
    await run(20_000);
    engine.stop();
    const rows = store.getRows();
    expect(rows.length).toBe(engine.getSnapshot().totals.created);
    expect(rows.length).toBeGreaterThan(5);
    expect(rows.some((r) => r.status !== "CREATED")).toBe(true);
  });

  it.each(SEEDS)("sends every event of a lifecycle in order, even when dispatches overlap (seed %i)", async (seed) => {
    const { api, accepted } = fakeApi({ postDelayMs: 150 });
    const engine = engineFor(api, seed);
    engine.setRate(40);
    engine.start();
    await run(40_000);
    engine.stop();

    // One entry per shipment and key: a repeat of the same key is a duplicate, not a new event.
    const byShipment = new Map<string, string[]>();
    const seen = new Set<string>();
    for (const e of accepted) {
      if (seen.has(e.key)) continue;
      seen.add(e.key);
      byShipment.set(e.id, [...(byShipment.get(e.id) ?? []), e.type]);
    }
    const happy = ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"];
    const exception = ["PICKED_UP", "IN_TRANSIT", "EXCEPTION"];
    expect(byShipment.size).toBeGreaterThan(5);
    for (const [id, types] of byShipment) {
      const ok = happy.slice(0, types.length).join() === types.join() || exception.slice(0, types.length).join() === types.join();
      expect(ok, `${id} sent ${types.join(", ")}`).toBe(true);
    }
  });

  it.each(SEEDS)("spreads the shipments it creates across the seeded carriers (seed %i)", async (seed) => {
    const { api, carriers } = fakeApi();
    const engine = engineFor(api, seed);
    engine.setRate(15);
    engine.start();
    await run(30_000);
    engine.stop();

    expect(carriers.length).toBeGreaterThan(20);
    expect(new Set(carriers).size).toBeGreaterThanOrEqual(4);
    expect(carriers.every((c) => CARRIERS.includes(c))).toBe(true);
  });

  it("stops creating at its cap and then stops itself", async () => {
    const engine = engineFor(fakeApi({ applyAfterMs: 50 }).api, 5);
    engine.setRate(20);
    engine.start();
    await run(AUTO_STOP_MS - 10_000);
    const snap = engine.getSnapshot();
    expect(snap.totals.created).toBeLessThanOrEqual(MAX_CREATED);
    expect(snap.running).toBe(false);
  });

  it("stops itself after the limit, so a forgotten tab does not keep writing", async () => {
    const engine = engineFor(fakeApi().api);
    engine.setRate(1);
    engine.start();
    await run(AUTO_STOP_MS + 5_000);
    const snap = engine.getSnapshot();
    expect(snap.running).toBe(false);
    expect(snap.stoppedBecause).toMatch(/an hour/);
  });

  it("resets to nothing", async () => {
    const engine = engineFor(fakeApi().api);
    engine.start();
    await run(3_000);
    engine.reset();
    const snap = engine.getSnapshot();
    expect(snap.totals.requests).toBe(0);
    expect(snap.board).toEqual([]);
    expect(snap.running).toBe(false);
  });
});

describe("live page", () => {
  function renderLive(engine: TrafficEngine, store = new ShipmentStore()) {
    return render(
      <MemoryRouter>
        <RuntimeProvider runtime={{ engine, store }}>
          <StackProvider>
            <LivePage />
          </StackProvider>
        </RuntimeProvider>
      </MemoryRouter>,
    );
  }

  it("starts paused with the controls, and starts and stops the traffic", async () => {
    const engine = engineFor(fakeApi().api);
    const user = userEvent.setup();
    renderLive(engine);
    expect(screen.getByText("PAUSED")).toBeVisible();
    expect(screen.getByText(/Nothing yet/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Start traffic/ }));
    expect(engine.getSnapshot().running).toBe(true);
    expect(await screen.findByText("LIVE")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Stop traffic/ }));
    expect(engine.getSnapshot().running).toBe(false);
  });

  it("puts the shipments' board above the numbers", () => {
    const engine = engineFor(fakeApi().api);
    renderLive(engine);
    const board = screen.getByRole("group", { name: "Shipments by status" });
    const rate = screen.getByText("Requests per second");
    expect(board.compareDocumentPosition(rate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("labels each throughput line with its own rate for the last second", async () => {
    const engine = engineFor(fakeApi().api);
    const user = userEvent.setup();
    renderLive(engine);
    await user.click(screen.getByRole("button", { name: /Start traffic/ }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2500));
    });
    await user.click(screen.getByRole("button", { name: /Stop traffic/ }));

    expect(screen.getByText(/^requests · \d+\/s$/)).toBeVisible();
    expect(screen.getByText(/^errors · 0\/s$/)).toBeVisible();
    expect(screen.queryByText(/errors · [1-9]\d* in the last second/)).not.toBeInTheDocument();
  });

  it("names the carriers it uses", () => {
    renderLive(engineFor(fakeApi().api));
    expect(screen.getByText(/carriers ACME, BOLT, CRWN, MFLT, ZZTEST/)).toBeVisible();
  });

  it("changes the rate with the slider", () => {
    const engine = engineFor(fakeApi().api);
    renderLive(engine);
    act(() => {
      engine.setRate(12);
    });
    expect(screen.getByText("12 requests/s")).toBeVisible();
  });

  it("keeps the traffic running when the page is left", () => {
    const engine = engineFor(fakeApi().api);
    const { unmount } = renderLive(engine);
    act(() => {
      engine.start();
    });
    unmount();
    expect(engine.getSnapshot().running).toBe(true);
    engine.stop();
  });
});
