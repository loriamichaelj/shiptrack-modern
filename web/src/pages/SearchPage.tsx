import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { isValidTrackingNumber, normalizeTrackingNumber } from "../api";
import { statusLabel } from "../format";
import { Icon, type IconName } from "../icons";
import { useServerSync, useShipments } from "../live/runtime";

export const SEARCH_ERROR = "Enter a tracking number: MF followed by 10 digits.";
/** How many of the newest shipments the page offers as quick links. */
const RECENT_COUNT = 5;

const FEATURES: { to: string; icon: IconName; title: string; text: string }[] = [
  { to: "/live", icon: "activity", title: "Live traffic", text: "Watch synthetic traffic move through the API in real time." },
  { to: "/shipments", icon: "grid", title: "Browse", text: "Every shipment, with counts, charts, and filters." },
  { to: "/shipments/new", icon: "plus", title: "New shipment", text: "Create a shipment and watch the API answer." },
  { to: "/system", icon: "activity", title: "System", text: "Readiness, the stack serving you, and an API explorer." },
];

export function SearchPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The newest shipments the server has, not what was typed here: a lookup that was deleted, or
  // made in another browser, would be the wrong thing to offer. Read from the shared store.
  useServerSync(30_000);
  const recent = useShipments().slice(0, RECENT_COUNT);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trackingNumber = normalizeTrackingNumber(value);
    if (!isValidTrackingNumber(trackingNumber)) {
      setError(SEARCH_ERROR);
      return;
    }
    setError(null);
    void navigate(`/track/${trackingNumber}`);
  }

  return (
    <>
      <section className="hero" aria-labelledby="search-heading">
        <h1 id="search-heading">Track a shipment</h1>
        <p className="lede">Follow a parcel from pickup to delivery.</p>
        <form onSubmit={onSubmit} noValidate>
          <label htmlFor="tracking-number">Tracking number</label>
          <div className="search-row">
            <input
              id="tracking-number"
              name="tracking-number"
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="MF0123456789"
              value={value}
              onChange={(event) => { setValue(event.target.value); }}
              aria-invalid={error !== null}
              aria-describedby={error === null ? "tracking-hint" : "tracking-hint tracking-error"}
            />
            <button type="submit">
              <Icon name="search" size={16} /> Track
            </button>
          </div>
          <p id="tracking-hint" className="muted">
            Tracking numbers start with MF followed by 10 digits.
          </p>
          {error !== null && (
            <p id="tracking-error" className="error" role="alert">
              {error}
            </p>
          )}
        </form>
        {recent.length > 0 && (
          <div className="recent">
            <span className="muted">Recent</span>
            {recent.map((row) => (
              <Link key={row.id} to={`/track/${row.trackingNumber}`} className="chip mono" title={`${statusLabel(row.status)}, ${row.carrier}`}>
                {row.trackingNumber}
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="features" aria-label="More">
        {FEATURES.map((f) => (
          <Link key={f.to} to={f.to} className="feature">
            <span className="feature-icon"><Icon name={f.icon} size={22} /></span>
            <strong>{f.title}</strong>
            <span className="muted">{f.text}</span>
          </Link>
        ))}
      </section>
    </>
  );
}
