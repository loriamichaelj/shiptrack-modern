import type { TrackEvent } from "../api";
import { formatTimestamp, statusLabel } from "../format";
import { Icon } from "../icons";
import { STATUS_ICONS } from "./StatusBadge";

/** Event timeline, newest first. The API returns events oldest first. */
export function Timeline({ events }: { events: TrackEvent[] }) {
  if (events.length === 0) return <p className="muted">No tracking events yet.</p>;
  const newestFirst = events.map((event, index) => ({ event, index })).reverse();
  return (
    <ol className="timeline" aria-label="Tracking events, newest first">
      {newestFirst.map(({ event, index }) => (
        <li key={index} className={`timeline-item tone-${event.event_type.toLowerCase().replaceAll("_", "-")}`}>
          <span className="timeline-dot">
            <Icon name={STATUS_ICONS[event.event_type] ?? "info"} size={14} />
          </span>
          <span className="timeline-status">{statusLabel(event.event_type)}</span>
          <span className="timeline-location">
            <Icon name="map-pin" size={13} />
            {event.location}
          </span>
          <time className="timeline-time" dateTime={event.occurred_at}>
            {formatTimestamp(event.occurred_at)}
          </time>
        </li>
      ))}
    </ol>
  );
}
