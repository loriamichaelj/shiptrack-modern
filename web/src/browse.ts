/** Sorting and CSV export for the Browse table. Both work on the rows the browser already holds. */
import type { Row } from "./live/store";
import { STATUS_ORDER } from "./stats";

export type SortKey = "trackingNumber" | "status" | "carrier" | "route" | "promisedAt" | "createdAt";
export type SortDirection = "asc" | "desc";
export interface Sort {
  key: SortKey;
  direction: SortDirection;
}

/** The store's own order: newest first. */
export const DEFAULT_SORT: Sort = { key: "createdAt", direction: "desc" };

const COMPARE: Record<SortKey, (a: Row, b: Row) => number> = {
  trackingNumber: (a, b) => a.trackingNumber.localeCompare(b.trackingNumber),
  status: (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status),
  carrier: (a, b) => a.carrier.localeCompare(b.carrier),
  route: (a, b) => a.origin.localeCompare(b.origin) || a.destination.localeCompare(b.destination),
  promisedAt: (a, b) => Date.parse(a.promisedAt) - Date.parse(b.promisedAt),
  createdAt: (a, b) => a.createdAt.localeCompare(b.createdAt),
};

/** A sorted copy. Ties keep the order they came in, which is newest first. */
export function sortRows(rows: readonly Row[], sort: Sort): Row[] {
  const sign = sort.direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => sign * COMPARE[sort.key](a, b));
}

/** A click on the sorted column turns it round; a click on another sorts it ascending. */
export function nextSort(current: Sort, key: SortKey): Sort {
  if (current.key !== key) return { key, direction: "asc" };
  return { key, direction: current.direction === "asc" ? "desc" : "asc" };
}

/** True when the shipment matches the place filter by its origin or its destination. */
export function matchesPlace(row: Row, place: string): boolean {
  const needle = place.trim().toLowerCase();
  return needle === "" || row.origin.toLowerCase().includes(needle) || row.destination.toLowerCase().includes(needle);
}

const CSV_COLUMNS = [
  "tracking_number",
  "status",
  "carrier_code",
  "origin",
  "destination",
  "promised_delivery_at",
  "created_at",
  "sla_breached",
  "id",
] as const;

/**
 * One field. Text that a spreadsheet would read as a formula (=, +, -, @, tab, or carriage return
 * first) gets a leading apostrophe, since origin and destination are whatever a client sent.
 */
function csvField(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

export function toCsv(rows: readonly Row[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const r of rows) {
    lines.push(
      [r.trackingNumber, r.status, r.carrier, r.origin, r.destination, r.promisedAt, r.createdAt, String(r.slaBreached), r.id]
        .map(csvField)
        .join(","),
    );
  }
  return `${lines.join("\r\n")}\r\n`;
}

/** shiptrack-shipments-20261018T220000Z.csv */
export function csvFileName(now: Date): string {
  const stamp = now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "");
  return `shiptrack-shipments-${stamp}.csv`;
}

/** Saves the CSV from the browser: a same-origin blob URL, so the CSP needs no allowance. */
export function downloadCsv(rows: readonly Row[], now: Date): void {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = csvFileName(now);
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked a moment later: some browsers start the download after click() returns.
  setTimeout(() => { URL.revokeObjectURL(url); }, 1000);
}
