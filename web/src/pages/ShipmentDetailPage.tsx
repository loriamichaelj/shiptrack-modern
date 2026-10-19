import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { fetchTrack, type TrackEvent } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { StatusStepper } from "../components/StatusStepper";
import { Timeline } from "../components/Timeline";
import {
  EVENT_TYPES,
  getShipment,
  listProofsOfDelivery,
  proofOfDeliveryUrl,
  postEvent,
  PROOF_OF_DELIVERY_LIST_LIMIT,
  PROOF_OF_DELIVERY_MAX_BYTES,
  PROOF_OF_DELIVERY_TYPES,
  uploadProofOfDelivery,
  type ApiResult,
  type EventType,
  type ListedProofOfDelivery,
  type ProofOfDeliveryList,
  type Shipment,
} from "../client";
import { formatTimestamp, statusLabel } from "../format";
import { Icon } from "../icons";
import { newIdempotencyKey } from "../keys";
import { relativeTime } from "../stats";
import { useStack } from "../stack";
import { useNow } from "../useNow";
import { localInput, toUtcIso } from "./NewShipmentPage";

const REFRESH_DELAYS_MS = [1500, 4000, 8000];

export function ShipmentDetailPage() {
  const { id = "" } = useParams();
  const { setStack } = useStack();
  const [shipment, setShipment] = useState<ApiResult<Shipment> | null>(null);
  const [events, setEvents] = useState<TrackEvent[]>([]);
  const [reload, setReload] = useState(0);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const result = await getShipment(id, controller.signal);
      if (controller.signal.aborted) return;
      if (result.stack !== null) setStack(result.stack);
      setShipment(result);
      if (!result.ok) return;
      const track = await fetchTrack(result.data.tracking_number, controller.signal);
      if (!controller.signal.aborted && track.kind === "found") setEvents(track.view.events);
    })();
    return () => {
      controller.abort();
    };
  }, [id, reload, setStack]);

  const refreshSoon = () => {
    REFRESH_DELAYS_MS.forEach((delay) => {
      window.setTimeout(() => {
        setReload((n) => n + 1);
      }, delay);
    });
  };

  if (shipment === null) return <p role="status">Loading…</p>;
  if (!shipment.ok) {
    return (
      <section>
        <h1>Shipment not found</h1>
        <p className="error">{shipment.message}</p>
        <p><Link to="/shipments">Back to shipments</Link></p>
      </section>
    );
  }
  const s = shipment.data;
  const reached = events.map((e) => e.event_type);

  return (
    <section aria-labelledby="detail-heading">
      <p className="crumbs"><Link to="/shipments">Shipments</Link> <Icon name="chevron" size={12} /> <span className="mono">{s.tracking_number}</span></p>
      <div className="page-head">
        <h1 id="detail-heading" className="mono">{s.tracking_number}</h1>
        <div className="page-actions">
          <StatusBadge status={s.status} />
          {s.sla_breached && <span className="flag flag-red"><Icon name="flag" size={13} /> SLA breach</span>}
        </div>
      </div>

      <div className="card">
        <StatusStepper status={s.status} reached={reached} />
      </div>

      <div className="grid-2">
        <div className="card">
          <h2><Icon name="info" size={18} /> Shipment</h2>
          <dl className="details">
            <dt>Carrier</dt><dd><span className="carrier">{s.carrier_code}</span></dd>
            <dt>Route</dt><dd>{s.origin} <Icon name="arrow-right" size={12} /> {s.destination}</dd>
            <dt>Promised</dt><dd>{formatTimestamp(s.promised_delivery_at)} <span className="muted">({relativeTime(s.promised_delivery_at, now)})</span></dd>
            <dt>Estimated</dt><dd>{formatTimestamp(s.estimated_delivery_at)}</dd>
            <dt>Delivered</dt><dd>{formatTimestamp(s.delivered_at)}</dd>
            <dt>Created</dt><dd>{formatTimestamp(s.created_at)}</dd>
            <dt>Updated</dt><dd>{formatTimestamp(s.updated_at)}</dd>
            <dt>Shipment id</dt><dd className="mono small">{s.id}</dd>
          </dl>
          <p>
            <Link to={`/track/${s.tracking_number}`}><Icon name="link" size={14} /> Public tracking page</Link>
          </p>
        </div>
        <div className="card">
          <h2><Icon name="clock" size={18} /> History</h2>
          <Timeline events={events} />
        </div>
      </div>

      <div className="grid-2">
        <EventForm shipment={s} onSent={refreshSoon} />
        <ProofOfDeliveryPanel shipmentId={s.id} />
      </div>
    </section>
  );
}

function EventForm({ shipment, onSent }: { shipment: Shipment; onSent: () => void }) {
  const [type, setType] = useState<EventType>("IN_TRANSIT");
  const [location, setLocation] = useState("Hamburg");
  const [when, setWhen] = useState(() => localInput(0));
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ key: string; outcome: Awaited<ReturnType<typeof postEvent>> } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const occurred = toUtcIso(when);
    if (location.trim() === "") return setProblem("A location is required.");
    if (occurred === null) return setProblem("Choose when it happened.");
    setProblem(null);
    setBusy(true);
    const key = newIdempotencyKey();
    const outcome = await postEvent(shipment.id, { event_type: type, location: location.trim(), occurred_at: occurred }, key);
    setBusy(false);
    setLast({ key, outcome });
    if (outcome.ok) onSent();
  }

  return (
    <div className="card">
      <h2><Icon name="send" size={18} /> Add a tracking event</h2>
      <form className="form" onSubmit={(event) => void submit(event)} noValidate>
        <label htmlFor="event-type">Event</label>
        <select id="event-type" value={type} onChange={(e) => { setType(e.target.value as EventType); }}>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{statusLabel(t)}</option>
          ))}
        </select>
        <label htmlFor="event-location">Location</label>
        <input id="event-location" type="text" maxLength={100} value={location} onChange={(e) => { setLocation(e.target.value); }} />
        <label htmlFor="event-when">Occurred at</label>
        <input id="event-when" type="datetime-local" value={when} onChange={(e) => { setWhen(e.target.value); }} />
        {problem !== null && <p className="error" role="alert">{problem}</p>}
        <button type="submit" disabled={busy}><Icon name="send" size={16} /> {busy ? "Sending…" : "Send event"}</button>
      </form>
      {last !== null && last.outcome.ok && (
        <p className="success-note" role="status">
          <Icon name="check-circle" size={16} /> Accepted (202). The event is queued and applied by a worker, so this page refreshes in a moment.
          <span className="muted"> Idempotency key {last.key}. Sending the same key again is a no-op.</span>
        </p>
      )}
      {last !== null && !last.outcome.ok && (
        <p className="error" role="alert">
          {last.outcome.message}
          <span className="muted"> {last.outcome.status !== null && `HTTP ${last.outcome.status}`} {last.outcome.code}</span>
        </p>
      )}
    </div>
  );
}

function ProofOfDeliveryPanel({ shipmentId }: { shipmentId: string }) {
  const [listed, setListed] = useState<ApiResult<ProofOfDeliveryList> | null>(null);
  const [reload, setReload] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The server's list, so every viewer sees every document; read again after an upload.
  useEffect(() => {
    const controller = new AbortController();
    void listProofsOfDelivery(shipmentId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setListed(result);
    });
    return () => {
      controller.abort();
    };
  }, [shipmentId, reload]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null) return setProblem("Choose a PDF, PNG, or JPEG file.");
    if (!PROOF_OF_DELIVERY_TYPES.includes(file.type)) return setProblem("Only PDF, PNG, and JPEG files are accepted.");
    if (file.size > PROOF_OF_DELIVERY_MAX_BYTES) return setProblem("Files are limited to 10 MiB.");
    setProblem(null);
    setBusy(true);
    const outcome = await uploadProofOfDelivery(shipmentId, file);
    setBusy(false);
    if (outcome.ok) {
      setFile(null);
      setReload((n) => n + 1);
    } else {
      setProblem(outcome.message);
    }
  }

  return (
    <div className="card">
      <h2><Icon name="file" size={18} /> Proof of delivery</h2>
      <form className="form" onSubmit={(event) => void submit(event)} noValidate>
        <label htmlFor="proof-file">Document</label>
        <input id="proof-file" type="file" accept={PROOF_OF_DELIVERY_TYPES.join(",")} onChange={(e) => { setFile(e.target.files?.[0] ?? null); }} />
        <p className="muted">PDF, PNG, or JPEG, up to 10 MiB. Stored in object storage.</p>
        {problem !== null && <p className="error" role="alert">{problem}</p>}
        <button type="submit" disabled={busy}><Icon name="upload" size={16} /> {busy ? "Uploading…" : "Upload"}</button>
      </form>
      <div className="proofs">
        <ProofOfDeliveryList shipmentId={shipmentId} listed={listed} />
      </div>
    </div>
  );
}

function ProofOfDeliveryList({ shipmentId, listed }: { shipmentId: string; listed: ApiResult<ProofOfDeliveryList> | null }) {
  const now = useNow(30_000);
  if (listed === null) return <p className="muted" role="status">Reading the documents…</p>;
  if (!listed.ok) return <p className="muted" role="status">The documents could not be listed: {listed.message}</p>;
  const items = listed.data.items;
  if (items.length === 0) return <p className="muted">No documents yet.</p>;
  return (
    <>
      <div className="call-title">Documents ({items.length})</div>
      {items.map((proof) => (
        <ProofOfDeliveryItem key={proof.document_id} shipmentId={shipmentId} proof={proof} now={now} />
      ))}
      {items.length >= PROOF_OF_DELIVERY_LIST_LIMIT && (
        <p className="muted small">Showing the newest {PROOF_OF_DELIVERY_LIST_LIMIT}.</p>
      )}
    </>
  );
}

function ProofOfDeliveryItem({ shipmentId, proof, now }: { shipmentId: string; proof: ListedProofOfDelivery; now: number }) {
  const url = proofOfDeliveryUrl(shipmentId, proof.document_id);
  return (
    <div className="proof">
      {proof.available && proof.content_type.startsWith("image/") ? (
        <img src={url} alt="Proof of delivery" width="72" height="72" />
      ) : (
        <span className="proof-icon"><Icon name="file" size={28} /></span>
      )}
      <div>
        {proof.available ? (
          <a href={url} target="_blank" rel="noreferrer">Open document</a>
        ) : (
          <span className="muted">Still on a legacy host; it opens once it is copied to storage.</span>
        )}
        <div className="muted small">
          {proof.content_type} · {(proof.size_bytes / 1024).toFixed(1)} KiB · <span title={formatTimestamp(proof.uploaded_at)}>uploaded {relativeTime(proof.uploaded_at, now)}</span>
        </div>
        <div className="muted small mono">sha256 {proof.sha256.slice(0, 16)}…</div>
      </div>
    </div>
  );
}
