import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_STOP_MS, percentile, TrafficEngine, type TrafficApi } from "../live/engine";
import { LivePage } from "../pages/LivePage";
import { StackProvider } from "../stack";

/** A fake API that applies each event after a fixed delay, like a queue and a worker would. */
function fakeApi(options: { applyAfterMs?: number; failCreate?: boolean; neverApply?: boolean } = {}) {
  const applyAfter = options.applyAfterMs ?? 300;
  const status = new Map<string, string>();
  const accepted: { id: string; type: string; key: string; at: number }[] = [];
  let seq = 0;
  const api: TrafficApi = {
    createShipment() {
      if (options.failCreate === true) {
        return Promise.resolve({ ok: false as const, message: "boom", status: 500 });
      }
      seq += 1;
      const id = `id-${seq}`;
      status.set(id, "CREATED");
      return Promise.resolve({ ok: true as const, id, trackingNumber: `MF${String(seq).padStart(10, "0")}`, stack: "modern" });
    },
    postEvent(id, type, _location, key) {
      accepted.push({ id, type, key, at: Date.now() });
      if (options.neverApply !== true) {
        setTimeout(() => {
          status.set(id, type);
        }, applyAfter);
      }
      return Promise.resolve({ ok: true as const, stack: "modern" });
    },
    track(trackingNumber) {
      const id = `id-${Number(trackingNumber.slice(2))}`;
      return Promise.resolve({ ok: true as const, status: (status.get(id) ?? "CREATED") as never, stack: "modern" });
    },
  };
  return { api, accepted };
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

function engineFor(api: TrafficApi, seed = 1): TrafficEngine {
  return new TrafficEngine(api, { now: () => Date.now(), random: seeded(seed) });
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

  it("stops itself after the limit, so a forgotten tab does not keep writing", async () => {
    const engine = engineFor(fakeApi().api);
    engine.setRate(1);
    engine.start();
    await run(AUTO_STOP_MS + 5_000);
    const snap = engine.getSnapshot();
    expect(snap.running).toBe(false);
    expect(snap.stoppedBecause).toMatch(/15 minutes/);
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
  function renderLive(engine: TrafficEngine) {
    return render(
      <MemoryRouter>
        <StackProvider>
          <LivePage engineFor={() => engine} />
        </StackProvider>
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

  it("changes the rate with the slider", () => {
    const engine = engineFor(fakeApi().api);
    renderLive(engine);
    const slider = screen.getByLabelText(/Rate/);
    act(() => {
      slider.focus();
      engine.setRate(12);
    });
    expect(screen.getByText("12 requests/s")).toBeVisible();
  });

  it("stops the traffic when the page is left", () => {
    const engine = engineFor(fakeApi().api);
    const { unmount } = renderLive(engine);
    act(() => {
      engine.start();
    });
    expect(engine.getSnapshot().running).toBe(true);
    unmount();
    expect(engine.getSnapshot().running).toBe(false);
  });
});
