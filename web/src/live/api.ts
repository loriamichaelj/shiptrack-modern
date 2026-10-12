import { fetchTrack } from "../api";
import { createShipment, postEvent } from "../client";
import type { TrafficApi } from "./engine";

const DAY = 86_400_000;

/** The engine's calls, made against the real API through the same client the pages use. */
export const realApi: TrafficApi = {
  async createShipment(carrier, origin, destination) {
    const result = await createShipment({
      carrier_code: carrier,
      origin,
      destination,
      promised_delivery_at: new Date(Date.now() + 2 * DAY).toISOString().replace(/\.\d{3}Z$/, "Z"),
    });
    if (result.ok) {
      return { ok: true, id: result.data.id, trackingNumber: result.data.tracking_number, stack: result.stack };
    }
    return { ok: false, message: result.message, status: result.status };
  },

  async postEvent(shipmentId, type, location, key) {
    // Milliseconds are kept so that two events of one shipment are never the same instant: an event
    // that is not later than the shipment's last one is stored and not applied.
    const result = await postEvent(
      shipmentId,
      { event_type: type, location, occurred_at: new Date().toISOString() },
      key,
    );
    return result.ok ? { ok: true, stack: result.stack } : { ok: false, message: result.message, status: result.status };
  },

  async track(trackingNumber) {
    const outcome = await fetchTrack(trackingNumber);
    if (outcome.kind === "found") return { ok: true, status: outcome.view.status, stack: outcome.stack };
    return {
      ok: false,
      status: null,
      message: outcome.kind === "not_found" ? "not found" : outcome.kind === "invalid" ? outcome.message : outcome.message,
    };
  },
};
