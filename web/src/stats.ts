import type { ShipmentStatus } from "./api";
import type { Shipment } from "./client";

export const STATUS_ORDER: ShipmentStatus[] = [
  "CREATED",
  "PICKED_UP",
  "IN_TRANSIT",
  "OUT_FOR_DELIVERY",
  "DELIVERED",
  "EXCEPTION",
];

export interface Summary {
  total: number;
  byStatus: Record<ShipmentStatus, number>;
  byCarrier: { carrier: string; count: number }[];
  breached: number;
  overdue: number;
  delivered: number;
  deliveredShare: number;
}

/** Past its promise and not delivered, whether or not the scan has flagged it yet. */
export function isOverdue(shipment: Shipment, now: number): boolean {
  return shipment.status !== "DELIVERED" && Date.parse(shipment.promised_delivery_at) < now;
}

export function summarize(shipments: readonly Shipment[], now: number): Summary {
  const byStatus = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<ShipmentStatus, number>;
  const carriers = new Map<string, number>();
  let breached = 0;
  let overdue = 0;
  for (const shipment of shipments) {
    byStatus[shipment.status] += 1;
    carriers.set(shipment.carrier_code, (carriers.get(shipment.carrier_code) ?? 0) + 1);
    if (shipment.sla_breached) breached += 1;
    if (isOverdue(shipment, now)) overdue += 1;
  }
  const total = shipments.length;
  return {
    total,
    byStatus,
    byCarrier: [...carriers.entries()]
      .map(([carrier, count]) => ({ carrier, count }))
      .sort((a, b) => b.count - a.count || a.carrier.localeCompare(b.carrier)),
    breached,
    overdue,
    delivered: byStatus.DELIVERED,
    deliveredShare: total === 0 ? 0 : byStatus.DELIVERED / total,
  };
}

/** A friendly distance such as "in 3 days", "2 hours ago", from two instants. */
export function relativeTime(iso: string | null, now: number): string {
  if (iso === null) return "—";
  const delta = Date.parse(iso) - now;
  if (Number.isNaN(delta)) return iso;
  const abs = Math.abs(delta);
  const units: [number, string][] = [
    [86_400_000, "day"],
    [3_600_000, "hour"],
    [60_000, "minute"],
  ];
  for (const [size, name] of units) {
    if (abs >= size) {
      const n = Math.round(abs / size);
      const text = `${n} ${name}${n === 1 ? "" : "s"}`;
      return delta >= 0 ? `in ${text}` : `${text} ago`;
    }
  }
  return "just now";
}
