import { statusLabel } from "../format";
import { Icon, type IconName } from "../icons";

export const STATUS_ICONS: Record<string, IconName> = {
  CREATED: "box",
  PICKED_UP: "package",
  IN_TRANSIT: "truck",
  OUT_FOR_DELIVERY: "map-pin",
  DELIVERED: "check-circle",
  EXCEPTION: "alert",
};

/** Status is always shown as text; the colour and the icon are decoration only. */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status.toLowerCase().replaceAll("_", "-")}`} data-status={status}>
      <Icon name={STATUS_ICONS[status] ?? "info"} size={14} />
      {statusLabel(status)}
    </span>
  );
}
