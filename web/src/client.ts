// The calls beyond tracking, all same-origin and all through the activity log.
import { loggedFetch } from "./apiLog";
import type { ShipmentStatus, TrackEvent } from "./api";

export interface Shipment {
  id: string;
  tracking_number: string;
  carrier_code: string;
  origin: string;
  destination: string;
  status: ShipmentStatus;
  promised_delivery_at: string;
  estimated_delivery_at: string | null;
  delivered_at: string | null;
  sla_breached: boolean;
  created_at: string;
  updated_at: string;
}

export interface ShipmentPage {
  items: Shipment[];
  next_cursor: string | null;
}

export interface PodDocument {
  document_id: string;
  shipment_id: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
}

export type EventType = Exclude<ShipmentStatus, "CREATED">;
export const EVENT_TYPES: EventType[] = [
  "PICKED_UP",
  "IN_TRANSIT",
  "OUT_FOR_DELIVERY",
  "DELIVERED",
  "EXCEPTION",
];

export const POD_TYPES = ["application/pdf", "image/png", "image/jpeg"];
export const POD_MAX_BYTES = 10 * 1024 * 1024;

export type ApiResult<T> =
  | { ok: true; data: T; stack: string | null; requestId: string | null }
  | {
      ok: false;
      status: number | null;
      code: string | null;
      message: string;
      stack: string | null;
      requestId: string | null;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function run<T>(
  url: string,
  init: Parameters<typeof loggedFetch>[1],
  accept: (body: unknown) => body is T,
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await loggedFetch(url, init);
  } catch {
    return {
      ok: false, status: null, code: null, stack: null, requestId: null,
      message: "Could not reach ShipTrack. Check your connection and try again.",
    };
  }
  const stack = response.headers.get("X-ShipTrack-Stack");
  const requestId = response.headers.get("X-Request-Id");
  const body: unknown = await response.json().catch(() => null);
  if (response.ok && accept(body)) return { ok: true, data: body, stack, requestId };
  const error = isRecord(body) && isRecord(body.error) ? body.error : null;
  return {
    ok: false,
    status: response.status,
    code: error !== null && typeof error.code === "string" ? error.code : null,
    message:
      error !== null && typeof error.message === "string"
        ? error.message
        : response.ok
          ? "ShipTrack returned a response this page could not read."
          : `ShipTrack answered ${response.status}.`,
    stack,
    requestId:
      error !== null && typeof error.request_id === "string" ? error.request_id : requestId,
  };
}

const isShipment = (v: unknown): v is Shipment =>
  isRecord(v) && typeof v.id === "string" && typeof v.tracking_number === "string";
const isPage = (v: unknown): v is ShipmentPage => isRecord(v) && Array.isArray(v.items);
const isPod = (v: unknown): v is PodDocument => isRecord(v) && typeof v.document_id === "string";
const isAccepted = (v: unknown): v is { accepted: boolean; idempotency_key: string } =>
  isRecord(v) && typeof v.accepted === "boolean";
const isReady = (v: unknown): v is { ready: boolean; reason: string | null } =>
  isRecord(v) && typeof v.ready === "boolean";

export interface ListQuery {
  status?: ShipmentStatus | "";
  carrierCode?: string;
  limit?: number;
  cursor?: string | null;
}

export function listShipments(query: ListQuery = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.carrierCode) params.set("carrier_code", query.carrierCode);
  params.set("limit", String(query.limit ?? 100));
  if (query.cursor) params.set("cursor", query.cursor);
  return run(`/api/v1/shipments?${params.toString()}`, { signal, headers: json }, isPage);
}

const json = { Accept: "application/json" };

export function getShipment(id: string, signal?: AbortSignal) {
  return run(`/api/v1/shipments/${encodeURIComponent(id)}`, { signal, headers: json }, isShipment);
}

export interface NewShipment {
  carrier_code: string;
  origin: string;
  destination: string;
  promised_delivery_at: string;
}

export function createShipment(body: NewShipment) {
  return run(
    "/api/v1/shipments",
    {
      method: "POST",
      headers: { ...json, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    isShipment,
  );
}

export interface NewEvent {
  event_type: EventType;
  location: string;
  occurred_at: string;
}

export function postEvent(shipmentId: string, body: NewEvent, idempotencyKey: string) {
  return run(
    `/api/v1/shipments/${encodeURIComponent(shipmentId)}/events`,
    {
      method: "POST",
      headers: { ...json, "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    },
    isAccepted,
  );
}

export function uploadPod(shipmentId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return run(
    `/api/v1/shipments/${encodeURIComponent(shipmentId)}/pod`,
    { method: "POST", headers: json, body: form, skipBody: true, note: file.name },
    isPod,
  );
}

export function podUrl(shipmentId: string, documentId: string): string {
  return `/api/v1/shipments/${encodeURIComponent(shipmentId)}/pod/${encodeURIComponent(documentId)}`;
}

export function readiness(signal?: AbortSignal) {
  return run("/readyz", { signal, headers: json }, isReady);
}

export type { TrackEvent };
