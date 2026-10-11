import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { createShipment, type ApiResult, type Shipment } from "../client";
import { Icon } from "../icons";
import { useStack } from "../stack";
import { StatusBadge } from "../components/StatusBadge";

export const KNOWN_CARRIERS = ["ACME", "ZZTEST"];

/** `datetime-local` value (browser time) for a moment, with a given number of days added. */
export function localInput(daysAhead: number, from = Date.now()): string {
  const date = new Date(from + daysAhead * 86_400_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** An ISO-8601 UTC timestamp, with a Z suffix and no fraction, from a `datetime-local` value. */
export function toUtcIso(local: string): string | null {
  const parsed = new Date(local);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function NewShipmentPage() {
  const { setStack } = useStack();
  const [carrier, setCarrier] = useState("ACME");
  const [origin, setOrigin] = useState("Rotterdam");
  const [destination, setDestination] = useState("Hamburg");
  const [promised, setPromised] = useState(() => localInput(3));
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApiResult<Shipment> | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const promisedIso = toUtcIso(promised);
    if (carrier.trim() === "" || origin.trim() === "" || destination.trim() === "") {
      setProblem("Carrier, origin, and destination are all required.");
      return;
    }
    if (promisedIso === null) {
      setProblem("Choose a promised delivery date and time.");
      return;
    }
    setProblem(null);
    setBusy(true);
    const outcome = await createShipment({
      carrier_code: carrier.trim().toUpperCase(),
      origin: origin.trim(),
      destination: destination.trim(),
      promised_delivery_at: promisedIso,
    });
    setBusy(false);
    if (outcome.stack !== null) setStack(outcome.stack);
    setResult(outcome);
  }

  return (
    <section aria-labelledby="new-heading">
      <h1 id="new-heading">
        <Icon name="plus" size={24} /> New shipment
      </h1>
      <p className="lede">Creates a shipment with <code>POST /api/v1/shipments</code>. The tracking number comes back from the server.</p>
      <form className="card form" onSubmit={(event) => void onSubmit(event)} noValidate>
        <label htmlFor="carrier">Carrier code</label>
        <input id="carrier" type="text" list="carriers" maxLength={8} value={carrier} onChange={(e) => { setCarrier(e.target.value); }} />
        <datalist id="carriers">
          {KNOWN_CARRIERS.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <div className="form-row">
          <div>
            <label htmlFor="origin">Origin</label>
            <input id="origin" type="text" maxLength={100} value={origin} onChange={(e) => { setOrigin(e.target.value); }} />
          </div>
          <div>
            <label htmlFor="destination">Destination</label>
            <input id="destination" type="text" maxLength={100} value={destination} onChange={(e) => { setDestination(e.target.value); }} />
          </div>
        </div>
        <label htmlFor="promised">Promised delivery</label>
        <input id="promised" type="datetime-local" value={promised} onChange={(e) => { setPromised(e.target.value); }} />
        <p className="muted">The time zone of this browser is used; the API stores it in UTC. A time in the past creates a shipment that is already overdue, which the SLA scan flags.</p>
        {problem !== null && <p className="error" role="alert">{problem}</p>}
        <button type="submit" disabled={busy}>
          <Icon name="plus" size={16} /> {busy ? "Creating…" : "Create shipment"}
        </button>
      </form>

      {result !== null && result.ok && (
        <div className="card success" role="status">
          <h2><Icon name="check-circle" size={20} /> Created {result.data.tracking_number}</h2>
          <p><StatusBadge status={result.data.status} /></p>
          <p>
            <Link to={`/shipments/${result.data.id}`}>Open the shipment</Link>
            {" · "}
            <Link to={`/track/${result.data.tracking_number}`}>Public tracking page</Link>
          </p>
          {result.requestId !== null && <p className="muted">Request id {result.requestId}</p>}
        </div>
      )}
      {result !== null && !result.ok && (
        <div className="card failure" role="alert">
          <h2><Icon name="alert" size={20} /> The API refused it</h2>
          <p>{result.message}</p>
          <p className="muted">
            {result.status !== null && <>HTTP {result.status}</>}
            {result.code !== null && <> · {result.code}</>}
            {result.requestId !== null && <> · request {result.requestId}</>}
          </p>
        </div>
      )}
    </section>
  );
}
