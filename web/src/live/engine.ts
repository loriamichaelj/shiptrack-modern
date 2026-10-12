import type { ShipmentStatus } from "../api";
import type { EventType, Shipment } from "../client";
import type { ShipmentStore } from "./store";

/** One line of the live feed. */
export interface FeedItem {
  id: number;
  at: number;
  kind: "created" | "event" | "duplicate" | "applied" | "read" | "error";
  trackingNumber: string | null;
  text: string;
  ms: number | null;
  ok: boolean;
}

export interface BoardCard {
  id: string;
  trackingNumber: string;
  status: ShipmentStatus;
  /** An event has been accepted but the shipment has not shown it yet. */
  pending: EventType | null;
}

export interface SecondBucket {
  /** Seconds since the engine started. */
  t: number;
  requests: number;
  errors: number;
  p95: number;
}

export interface Snapshot {
  running: boolean;
  rate: number;
  elapsedMs: number;
  totals: {
    requests: number;
    errors: number;
    created: number;
    eventsSent: number;
    duplicates: number;
    applied: number;
    reads: number;
  };
  seconds: SecondBucket[];
  latency: { p50: number; p95: number };
  applyLag: { p50: number | null; p95: number | null; samples: number };
  board: BoardCard[];
  feed: FeedItem[];
  inFlight: number;
  stack: string | null;
  stoppedBecause: string | null;
}

/** What the engine needs from the API. The page passes the real calls; a test passes fakes. */
export interface TrafficApi {
  createShipment(carrier: string, origin: string, destination: string): Promise<CreateResult>;
  postEvent(shipmentId: string, type: EventType, location: string, key: string): Promise<EventResult>;
  track(trackingNumber: string): Promise<TrackResult>;
}

export type CreateResult =
  | { ok: true; shipment: Shipment; stack: string | null }
  | { ok: false; message: string; status: number | null };
export type EventResult = { ok: true; stack: string | null } | { ok: false; message: string; status: number | null };
export type TrackResult =
  | { ok: true; status: ShipmentStatus; stack: string | null }
  | { ok: false; message: string; status: number | null };

export interface Clock {
  now(): number;
  random(): number;
}

/**
 * The carriers migration 0001 seeds; the API answers 422 for any other code. Each created shipment
 * takes one at random, so the data is spread across them. ZZTEST is the one the platform's tests use.
 */
export const CARRIERS: readonly string[] = ["ACME", "BOLT", "CRWN", "MFLT", "ZZTEST"];

export const MAX_RATE = 20;
export const MIN_RATE = 1;
const MAX_IN_FLIGHT = 8;
const MAX_TRACKED = 120;
const FEED_LENGTH = 60;
const STALL_MS = 30_000;
const POLL_MS = 400;
const WINDOW_SECONDS = 60;
/** A run stops by itself after this long, so that a forgotten tab does not write for ever. */
export const AUTO_STOP_MS = 60 * 60 * 1000;
/** A run creates at most this many shipments. Browse reads all of them, so the number is bounded. */
export const MAX_CREATED = 1000;
const CITIES = ["Rotterdam", "Hamburg", "Leeds", "Cardiff", "Lyon", "Gdansk", "Bilbao", "Antwerp"];
const HAPPY: EventType[] = ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"];
const EXCEPTION_PATH: EventType[] = ["PICKED_UP", "IN_TRANSIT", "EXCEPTION"];
const RANK: Record<ShipmentStatus, number> = {
  CREATED: 0,
  PICKED_UP: 1,
  IN_TRANSIT: 2,
  OUT_FOR_DELIVERY: 3,
  DELIVERED: 4,
  EXCEPTION: 4,
};

interface Tracked extends BoardCard {
  plan: EventType[];
  pendingSince: number | null;
  lastPoll: number;
  done: boolean;
  /** An event is being sent. Another dispatch must not pick the same shipment meanwhile. */
  busy: boolean;
}

export function percentile(values: readonly number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, index)] ?? 0;
}

function idempotencyKey(clock: Clock): string {
  let out = "live-";
  for (let i = 0; i < 24; i += 1) out += Math.floor(clock.random() * 16).toString(16);
  return out;
}

/**
 * Drives synthetic traffic through the real API from the browser and keeps what it saw: a board of
 * shipments moving through their statuses, throughput and latency per second, and how long an
 * accepted event takes to show up on the shipment (the queue and the worker in between).
 */
export class TrafficEngine {
  private readonly api: TrafficApi;
  private readonly clock: Clock;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private tracked: Tracked[] = [];
  private feed: FeedItem[] = [];
  private nextFeed = 1;
  private buckets = new Map<number, { requests: number; errors: number; latencies: number[] }>();
  private latencies: number[] = [];
  private lags: number[] = [];
  private totals = { requests: 0, errors: 0, created: 0, eventsSent: 0, duplicates: 0, applied: 0, reads: 0 };
  private budget = 0;
  private lastTick = 0;
  private inFlight = 0;
  private rate = 5;
  private startedAt: number | null = null;
  private runningSince = 0;
  private stack: string | null = null;
  private stoppedBecause: string | null = null;
  private snapshot: Snapshot;
  private readonly store: ShipmentStore | null;

  constructor(
    api: TrafficApi,
    clock: Clock = { now: () => Date.now(), random: () => Math.random() },
    store: ShipmentStore | null = null,
  ) {
    this.api = api;
    this.clock = clock;
    this.store = store;
    this.snapshot = this.build();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): Snapshot => this.snapshot;

  setRate(rate: number): void {
    this.rate = Math.max(MIN_RATE, Math.min(MAX_RATE, Math.round(rate)));
    this.publish();
  }

  start(): void {
    if (this.timer !== null) return;
    const now = this.clock.now();
    this.startedAt ??= now;
    this.runningSince = now;
    this.lastTick = now;
    this.stoppedBecause = null;
    this.timer = setInterval(() => {
      this.tick();
    }, 100);
    this.publish();
  }

  stop(reason: string | null = null): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.stoppedBecause = reason;
    this.publish();
  }

  reset(): void {
    this.stop();
    this.tracked = [];
    this.feed = [];
    this.buckets = new Map();
    this.latencies = [];
    this.lags = [];
    this.totals = { requests: 0, errors: 0, created: 0, eventsSent: 0, duplicates: 0, applied: 0, reads: 0 };
    this.budget = 0;
    this.startedAt = null;
    this.stack = null;
    this.stoppedBecause = null;
    this.publish();
  }

  // -- one tick: turn the rate into operations ------------------------------------------------

  private tick(): void {
    const now = this.clock.now();
    if (now - this.runningSince > AUTO_STOP_MS) {
      this.stop("Stopped after an hour, so that a forgotten tab does not keep generating data.");
      return;
    }
    // The budget follows the clock and not the number of ticks: a background tab runs its timers
    // about once a second, and counting ticks would make the rate a tenth of what was asked.
    const elapsed = Math.max(0, now - this.lastTick);
    this.lastTick = now;
    // Decided before this tick starts anything, while nothing is in flight to make it look busy.
    if (this.totals.created >= MAX_CREATED && this.inFlight === 0 && !this.tracked.some((s) => !s.done)) {
      this.stop(`Reached ${MAX_CREATED} shipments. Press Reset to count from zero again.`);
      return;
    }
    this.budget += (this.rate * elapsed) / 1000;
    while (this.budget >= 1 && this.inFlight < MAX_IN_FLIGHT) {
      this.budget -= 1;
      void this.dispatch();
    }
    this.budget = Math.min(this.budget, this.rate * 2);
    this.publish();
  }

  private pick<T>(items: readonly T[]): T | undefined {
    return items[Math.floor(this.clock.random() * items.length)];
  }

  private async dispatch(): Promise<void> {
    this.inFlight += 1;
    try {
      const now = this.clock.now();
      const movable = this.tracked.filter((s) => !s.done && !s.busy && s.pending === null && s.plan.length > 0);
      const pending = this.tracked.filter((s) => s.pending !== null);
      // A shipment waiting for its event to show is looked at again soon, oldest first, so that the
      // lag measured is the lag of the system and not of the next random read.
      const due = pending
        .filter((s) => now - s.lastPoll >= POLL_MS)
        .sort((a, b) => (a.pendingSince ?? 0) - (b.pendingSince ?? 0));
      const roll = this.clock.random();
      const canCreate = this.totals.created < MAX_CREATED;
      if (due.length > 0 && this.clock.random() < 0.8) {
        const first = due[0];
        if (first !== undefined) await this.read(first);
      } else if (canCreate && (this.tracked.length < 4 || roll < 0.18 || (movable.length === 0 && pending.length === 0))) {
        await this.create();
      } else if (roll < 0.62 && movable.length > 0) {
        const shipment = this.pick(movable);
        if (shipment !== undefined) await this.advance(shipment);
      } else {
        const shipment = this.pick(pending.length > 0 ? pending : this.tracked);
        if (shipment !== undefined) await this.read(shipment);
      }
    } finally {
      this.inFlight -= 1;
    }
  }

  // -- operations -----------------------------------------------------------------------------

  private async create(): Promise<void> {
    const origin = this.pick(CITIES) ?? "Leeds";
    const destination = this.pick(CITIES.filter((c) => c !== origin)) ?? "Cardiff";
    const started = this.clock.now();
    const carrier = this.pick(CARRIERS) ?? "ZZTEST";
    const result = await this.api.createShipment(carrier, origin, destination);
    const ms = this.clock.now() - started;
    this.count(ms, !result.ok);
    if (!result.ok) {
      this.log("error", null, `create failed: ${result.message}`, ms, false);
      return;
    }
    this.stack = result.stack ?? this.stack;
    this.totals.created += 1;
    this.store?.add(result.shipment, this.clock.now());
    this.tracked.push({
      id: result.shipment.id,
      trackingNumber: result.shipment.tracking_number,
      status: "CREATED",
      pending: null,
      pendingSince: null,
      lastPoll: 0,
      done: false,
      busy: false,
      plan: this.clock.random() < 0.06 ? [...EXCEPTION_PATH] : [...HAPPY],
    });
    if (this.tracked.length > MAX_TRACKED) {
      const drop = this.tracked.findIndex((s) => s.done);
      this.tracked.splice(drop === -1 ? 0 : drop, 1);
    }
    this.log("created", result.shipment.tracking_number, `${origin} → ${destination}`, ms, true);
  }

  private async advance(shipment: Tracked): Promise<void> {
    const type = shipment.plan[0];
    if (type === undefined) return;
    // Claimed before the first await: two dispatches that picked the same shipment would each send
    // this event and each remove one from the plan, and the one after it would never be sent.
    shipment.busy = true;
    try {
      await this.send(shipment, type);
    } finally {
      shipment.busy = false;
    }
  }

  private async send(shipment: Tracked, type: EventType): Promise<void> {
    const location = this.pick(CITIES) ?? "Hub";
    const key = idempotencyKey(this.clock);
    const started = this.clock.now();
    const result = await this.api.postEvent(shipment.id, type, location, key);
    const ms = this.clock.now() - started;
    this.count(ms, !result.ok);
    if (!result.ok) {
      this.log("error", shipment.trackingNumber, `${type} refused: ${result.message}`, ms, false);
      return;
    }
    this.stack = result.stack ?? this.stack;
    this.totals.eventsSent += 1;
    shipment.plan.shift();
    shipment.pending = type;
    shipment.pendingSince = this.clock.now();
    this.log("event", shipment.trackingNumber, `${type} accepted (202)`, ms, true);

    if (this.clock.random() < 0.08) {
      const again = this.clock.now();
      const repeat = await this.api.postEvent(shipment.id, type, location, key);
      const repeatMs = this.clock.now() - again;
      this.count(repeatMs, !repeat.ok);
      if (repeat.ok) {
        this.totals.duplicates += 1;
        this.log("duplicate", shipment.trackingNumber, `same key sent again: accepted, applied once`, repeatMs, true);
      } else {
        this.log("error", shipment.trackingNumber, `repeat refused: ${repeat.message}`, repeatMs, false);
      }
    }
  }

  private async read(shipment: Tracked): Promise<void> {
    const started = this.clock.now();
    shipment.lastPoll = started;
    const result = await this.api.track(shipment.trackingNumber);
    const ms = this.clock.now() - started;
    this.count(ms, !result.ok);
    this.totals.reads += 1;
    if (!result.ok) {
      this.log("error", shipment.trackingNumber, `read failed: ${result.message}`, ms, false);
      return;
    }
    this.stack = result.stack ?? this.stack;
    const before = shipment.status;
    shipment.status = result.status;
    this.store?.setStatus(shipment.id, result.status, this.clock.now());
    // Seen delivered or in exception, by whichever read: it has nowhere further to go.
    if (result.status === "DELIVERED" || result.status === "EXCEPTION") shipment.done = true;
    if (shipment.pending !== null && RANK[result.status] >= RANK[shipment.pending]) {
      const lag = this.clock.now() - (shipment.pendingSince ?? this.clock.now());
      this.lags.push(lag);
      if (this.lags.length > 200) this.lags.shift();
      this.totals.applied += 1;
      shipment.pending = null;
      shipment.pendingSince = null;
      if (shipment.status === "DELIVERED" || shipment.status === "EXCEPTION") shipment.done = true;
      // Nothing left to send and nothing waiting to show: whatever it reads, it is finished.
      if (shipment.plan.length === 0) shipment.done = true;
      this.log("applied", shipment.trackingNumber, `now ${result.status} (applied after ${lag} ms)`, ms, true);
    } else if (before !== result.status) {
      this.log("read", shipment.trackingNumber, `now ${result.status}`, ms, true);
    } else if (shipment.pending !== null && this.clock.now() - (shipment.pendingSince ?? 0) > STALL_MS) {
      // Accepted but never shown: say so instead of waiting for it for ever.
      this.totals.errors += 1;
      this.log("error", shipment.trackingNumber, `${shipment.pending} accepted but not applied after ${STALL_MS / 1000} s`, ms, false);
      shipment.pending = null;
      shipment.pendingSince = null;
      shipment.done = true;
    }
  }

  // -- bookkeeping ----------------------------------------------------------------------------

  private count(ms: number, failed: boolean): void {
    const second = Math.floor((this.clock.now() - (this.startedAt ?? this.clock.now())) / 1000);
    const bucket = this.buckets.get(second) ?? { requests: 0, errors: 0, latencies: [] };
    bucket.requests += 1;
    if (failed) bucket.errors += 1;
    bucket.latencies.push(ms);
    this.buckets.set(second, bucket);
    for (const key of this.buckets.keys()) {
      if (key < second - WINDOW_SECONDS * 2) this.buckets.delete(key);
    }
    this.totals.requests += 1;
    if (failed) this.totals.errors += 1;
    this.latencies.push(ms);
    if (this.latencies.length > 500) this.latencies.shift();
  }

  private log(kind: FeedItem["kind"], trackingNumber: string | null, text: string, ms: number | null, ok: boolean): void {
    this.feed = [
      { id: this.nextFeed, at: this.clock.now(), kind, trackingNumber, text, ms, ok },
      ...this.feed,
    ].slice(0, FEED_LENGTH);
    this.nextFeed += 1;
  }

  private publish(): void {
    this.snapshot = this.build();
    this.listeners.forEach((listener) => {
      listener();
    });
  }

  private build(): Snapshot {
    const now = this.clock.now();
    const elapsed = this.startedAt === null ? 0 : now - this.startedAt;
    const current = Math.floor(elapsed / 1000);
    const seconds: SecondBucket[] = [];
    for (let t = Math.max(0, current - WINDOW_SECONDS + 1); t <= current; t += 1) {
      const bucket = this.buckets.get(t);
      seconds.push({
        t,
        requests: bucket?.requests ?? 0,
        errors: bucket?.errors ?? 0,
        p95: bucket === undefined ? 0 : percentile(bucket.latencies, 95),
      });
    }
    return {
      running: this.timer !== null,
      rate: this.rate,
      elapsedMs: elapsed,
      totals: { ...this.totals },
      seconds,
      latency: { p50: percentile(this.latencies, 50), p95: percentile(this.latencies, 95) },
      applyLag: {
        p50: this.lags.length === 0 ? null : percentile(this.lags, 50),
        p95: this.lags.length === 0 ? null : percentile(this.lags, 95),
        samples: this.lags.length,
      },
      board: this.tracked.map(({ id, trackingNumber, status, pending }) => ({ id, trackingNumber, status, pending })),
      feed: this.feed,
      inFlight: this.inFlight,
      stack: this.stack,
      stoppedBecause: this.stoppedBecause,
    };
  }
}
