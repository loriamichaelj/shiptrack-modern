import type { ShipmentStatus } from "../api";
import type { Shipment } from "../client";

/** One shipment as the browser holds it. Both the live page and Browse read these. */
export interface Row {
  id: string;
  trackingNumber: string;
  carrier: string;
  origin: string;
  destination: string;
  status: ShipmentStatus;
  createdAt: string;
  promisedAt: string;
  slaBreached: boolean;
  /** When this row last changed in this browser, in epoch milliseconds. */
  touchedAt: number;
}

const RANK: Record<ShipmentStatus, number> = {
  CREATED: 0,
  PICKED_UP: 1,
  IN_TRANSIT: 2,
  OUT_FOR_DELIVERY: 3,
  DELIVERED: 4,
  EXCEPTION: 4,
};

export interface SyncState {
  syncing: boolean;
  pagesRead: number;
  lastSyncedAt: number | null;
  error: string | null;
}

export function rowFrom(shipment: Shipment, now: number): Row {
  return {
    id: shipment.id,
    trackingNumber: shipment.tracking_number,
    carrier: shipment.carrier_code,
    origin: shipment.origin,
    destination: shipment.destination,
    status: shipment.status,
    createdAt: shipment.created_at,
    promisedAt: shipment.promised_delivery_at,
    slaBreached: shipment.sla_breached,
    touchedAt: now,
  };
}

/**
 * The one place the browser keeps shipments. The traffic engine writes to it as it creates and
 * reads, and Browse writes to it as it reads the server's list, so every page shows the same data.
 * A status never moves backwards: a read that was started earlier cannot undo a newer one.
 */
export class ShipmentStore {
  private rows = new Map<string, Row>();
  private listeners = new Set<() => void>();
  private cache: Row[] = [];
  private dirty = false;
  private sync: SyncState = { syncing: false, pagesRead: 0, lastSyncedAt: null, error: null };

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Newest first. The same array is returned until something changes. */
  getRows = (): readonly Row[] => {
    if (this.dirty) {
      this.cache = [...this.rows.values()].sort(
        (a, b) => b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id),
      );
      this.dirty = false;
    }
    return this.cache;
  };

  getSync = (): SyncState => this.sync;

  get size(): number {
    return this.rows.size;
  }

  private changed(): void {
    this.dirty = true;
    this.listeners.forEach((listener) => {
      listener();
    });
  }

  add(shipment: Shipment, now: number): void {
    this.mergeOne(shipment, now);
    this.changed();
  }

  setStatus(id: string, status: ShipmentStatus, now: number): void {
    const row = this.rows.get(id);
    if (row === undefined || RANK[status] < RANK[row.status] || status === row.status) return;
    this.rows.set(id, { ...row, status, touchedAt: now });
    this.changed();
  }

  /** Merge a page read from the server. Rows already here are updated, never moved backwards. */
  merge(shipments: readonly Shipment[], now: number): void {
    let any = false;
    for (const shipment of shipments) any = this.mergeOne(shipment, now) || any;
    if (any) this.changed();
  }

  private mergeOne(shipment: Shipment, now: number): boolean {
    const existing = this.rows.get(shipment.id);
    if (existing === undefined) {
      this.rows.set(shipment.id, rowFrom(shipment, now));
      return true;
    }
    const status = RANK[shipment.status] >= RANK[existing.status] ? shipment.status : existing.status;
    if (status === existing.status && shipment.sla_breached === existing.slaBreached) return false;
    this.rows.set(shipment.id, {
      ...existing,
      status,
      slaBreached: shipment.sla_breached,
      touchedAt: now,
    });
    return true;
  }

  /**
   * After a complete read of the server's list: drop what it no longer lists, such as shipments a
   * data reset deleted. A row touched since the read began is kept, because it may have been created
   * after the server answered the page that would have shown it.
   */
  retain(seen: ReadonlySet<string>, readStartedAt: number): void {
    let any = false;
    for (const [id, row] of this.rows) {
      if (!seen.has(id) && row.touchedAt < readStartedAt) {
        this.rows.delete(id);
        any = true;
      }
    }
    if (any) this.changed();
  }

  setSync(next: Partial<SyncState>): void {
    this.sync = { ...this.sync, ...next };
    this.listeners.forEach((listener) => {
      listener();
    });
  }
}
