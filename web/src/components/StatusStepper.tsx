import type { ShipmentStatus } from "../api";
import { statusLabel } from "../format";
import { Icon } from "../icons";
import { STATUS_ICONS } from "./StatusBadge";

const STEPS: ShipmentStatus[] = ["CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"];

/** Where a shipment is on its way. An exception is shown beside the steps, not as one of them. */
export function StatusStepper({ status, reached }: { status: ShipmentStatus; reached?: ShipmentStatus[] }) {
  const seen = new Set<ShipmentStatus>(reached ?? []);
  const index = STEPS.indexOf(status);
  const furthest = Math.max(index, ...STEPS.map((step, i) => (seen.has(step) ? i : -1)));
  return (
    <div className="stepper" role="img" aria-label={`Progress: ${statusLabel(status)}`}>
      {STEPS.map((step, i) => {
        const state = i < furthest || (i === furthest && status === "DELIVERED") ? "done" : i === furthest ? "current" : "todo";
        return (
          <div key={step} className={`step step-${state}`}>
            <span className="step-dot">
              <Icon name={state === "done" ? "check" : STATUS_ICONS[step] ?? "box"} size={16} />
            </span>
            <span className="step-label">{statusLabel(step)}</span>
          </div>
        );
      })}
      {status === "EXCEPTION" && (
        <div className="step step-exception">
          <span className="step-dot">
            <Icon name="alert" size={16} />
          </span>
          <span className="step-label">Exception</span>
        </div>
      )}
    </div>
  );
}
