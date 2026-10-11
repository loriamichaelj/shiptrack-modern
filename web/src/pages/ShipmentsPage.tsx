import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import type { ShipmentStatus } from "../api";
import { BarChart, DonutChart, type Segment } from "../components/Charts";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { listShipments, type ApiResult, type Shipment, type ShipmentPage } from "../client";
import { formatTimestamp, statusLabel } from "../format";
import { Icon } from "../icons";
import { isOverdue, relativeTime, STATUS_ORDER, summarize } from "../stats";
import { useStack } from "../stack";

/**
 * Pages of up to 100 shipments are read in turn. The API lists oldest first and has no total, so
 * the newest shipments are on the last page: a cap that stops early drops exactly those. A batch
 * is this many pages, and when it ends with more to read the page says so and offers the next one.
 */
export const MAX_PAGES = 50;
const SHOWN_STEP = 25;

interface Loaded {
  items: Shipment[];
  pages: number;
  /** `done`: every page is read. `paused`: a batch ended and the API has more. */
  state: "loading" | "done" | "paused";
  error: string | null;
}

const EMPTY: Loaded = { items: [], pages: 0, state: "loading", error: null };

export function ShipmentsPage({ pageLimit = MAX_PAGES }: { pageLimit?: number }) {
  const { setStack } = useStack();
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);
  const [status, setStatus] = useState<ShipmentStatus | "">("");
  const [carrier, setCarrier] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [text, setText] = useState("");
  const [shown, setShown] = useState(SHOWN_STEP);
  const [batch, setBatch] = useState(0);
  const [now] = useState(() => Date.now());
  // Where the next page starts, kept across batches so that "Load more" resumes.
  const cursor = useRef<string | null>(null);
  const pages = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      for (let n = 0; n < pageLimit; n += 1) {
        const result: ApiResult<ShipmentPage> | null = await listShipments(
          { cursor: cursor.current, limit: 100 },
          controller.signal,
        ).catch(() => null);
        if (controller.signal.aborted) return;
        if (result === null || !result.ok) {
          setLoaded((prev) => ({
            ...prev,
            state: "paused",
            error: result !== null && !result.ok ? result.message : "Could not reach ShipTrack.",
          }));
          return;
        }
        if (result.stack !== null) setStack(result.stack);
        const items: Shipment[] = result.data.items;
        const next: string | null = result.data.next_cursor;
        pages.current += 1;
        cursor.current = next;
        const read = pages.current;
        setLoaded((prev) => ({
          items: [...prev.items, ...items],
          pages: read,
          state: next === null ? "done" : "loading",
          error: null,
        }));
        if (next === null) return;
      }
      setLoaded((prev) => ({ ...prev, state: "paused" }));
    })();
    return () => {
      controller.abort();
    };
  }, [batch, pageLimit, setStack]);

  function restart(): void {
    cursor.current = null;
    pages.current = 0;
    setLoaded(EMPTY);
    setBatch((n) => n + 1);
  }

  function loadMore(): void {
    setLoaded((prev) => ({ ...prev, state: "loading", error: null }));
    setBatch((n) => n + 1);
  }

  const complete = loaded.state === "done";

  const summary = useMemo(() => summarize(loaded.items, now), [loaded.items, now]);
  const carriers = useMemo(() => summary.byCarrier.map((c) => c.carrier), [summary]);

  const rows = useMemo(() => {
    const needle = text.trim().toUpperCase();
    return [...loaded.items]
      .filter((s) => status === "" || s.status === status)
      .filter((s) => carrier === "" || s.carrier_code === carrier)
      .filter((s) => !overdueOnly || isOverdue(s, now))
      .filter((s) => needle === "" || s.tracking_number.includes(needle))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [loaded.items, status, carrier, overdueOnly, text, now]);

  const segments: Segment[] = STATUS_ORDER.map((s) => ({
    label: statusLabel(s),
    value: summary.byStatus[s],
    className: `seg-${s.toLowerCase().replaceAll("_", "-")}`,
  }));

  return (
    <section aria-labelledby="ship-heading">
      <div className="page-head">
        <h1 id="ship-heading">
          <Icon name="grid" size={24} /> Shipments
        </h1>
        <div className="page-actions">
          <button type="button" className="ghost" onClick={restart}>
            <Icon name="refresh" size={16} /> Reload
          </button>
          <Link to="/shipments/new" className="button">
            <Icon name="plus" size={16} /> New shipment
          </Link>
        </div>
      </div>

      <p className="muted" role="status">
        {loaded.error !== null
          ? `Stopped after ${loaded.items.length} shipments: ${loaded.error}`
          : complete
            ? `${loaded.items.length} shipments loaded in ${loaded.pages} request${loaded.pages === 1 ? "" : "s"} to GET /api/v1/shipments.`
            : loaded.state === "paused"
              ? `Showing the oldest ${loaded.items.length} shipments (${loaded.pages} requests). The API has more, and it lists oldest first, so the newest are further on.`
              : `Loading… ${loaded.items.length} shipments so far (page ${loaded.pages + 1}).`}
      </p>
      {loaded.state === "paused" && (
        <p>
          <button type="button" onClick={loadMore}>
            <Icon name="arrow-right" size={16} /> {loaded.error !== null ? "Try again" : `Load ${pageLimit * 100} more`}
          </button>
        </p>
      )}

      <div className="stats">
        <StatCard
          icon="package"
          label="Shipments"
          value={complete ? summary.total : `${summary.total}+`}
          hint={complete ? "all loaded" : "oldest first, more to load"}
          tone="blue"
        />
        <StatCard icon="truck" label="On the way" value={summary.byStatus.PICKED_UP + summary.byStatus.IN_TRANSIT + summary.byStatus.OUT_FOR_DELIVERY} tone="violet" />
        <StatCard icon="check-circle" label="Delivered" value={summary.delivered} hint={`${Math.round(summary.deliveredShare * 100)}% of loaded`} tone="green" />
        <StatCard icon="clock" label="Overdue" value={summary.overdue} hint={`${summary.breached} flagged by the SLA scan`} tone="amber" />
        <StatCard icon="alert" label="Exceptions" value={summary.byStatus.EXCEPTION} tone="red" />
      </div>

      <div className="charts">
        <div className="card">
          <h2>By status</h2>
          <DonutChart segments={segments} centre={String(summary.total)} caption="shipments" />
        </div>
        <div className="card">
          <h2>By carrier</h2>
          {summary.byCarrier.length === 0 ? (
            <p className="muted">No data yet.</p>
          ) : (
            <BarChart
              caption="Shipments by carrier"
              items={summary.byCarrier.slice(0, 8).map((c) => ({ label: c.carrier, value: c.count }))}
            />
          )}
        </div>
      </div>

      <div className="card">
        <div className="filters">
          <label className="visually-hidden" htmlFor="f-text">Tracking number contains</label>
          <input id="f-text" type="text" placeholder="Filter by tracking number" value={text} onChange={(e) => { setText(e.target.value); setShown(SHOWN_STEP); }} />
          <label className="visually-hidden" htmlFor="f-carrier">Carrier</label>
          <select id="f-carrier" value={carrier} onChange={(e) => { setCarrier(e.target.value); setShown(SHOWN_STEP); }}>
            <option value="">All carriers</option>
            {carriers.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={overdueOnly} onChange={(e) => { setOverdueOnly(e.target.checked); setShown(SHOWN_STEP); }} />
            Overdue only
          </label>
        </div>
        <div className="chips" role="group" aria-label="Filter by status">
          <button type="button" className={`chip ${status === "" ? "chip-on" : ""}`} aria-pressed={status === ""} onClick={() => { setStatus(""); setShown(SHOWN_STEP); }}>
            All
          </button>
          {STATUS_ORDER.map((s) => (
            <button key={s} type="button" className={`chip chip-${s.toLowerCase().replaceAll("_", "-")} ${status === s ? "chip-on" : ""}`} aria-pressed={status === s} onClick={() => { setStatus(s); setShown(SHOWN_STEP); }}>
              {statusLabel(s)} <span className="chip-count">{summary.byStatus[s]}</span>
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <p className="muted">{complete ? "No shipments match." : "Waiting for pages…"}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Tracking number</th>
                  <th>Status</th>
                  <th>Carrier</th>
                  <th>Route</th>
                  <th>Promised</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Link to={`/shipments/${s.id}`} className="mono">{s.tracking_number}</Link>
                    </td>
                    <td>
                      <StatusBadge status={s.status} />
                      {isOverdue(s, now) && (
                        <span className={`flag ${s.sla_breached ? "flag-red" : "flag-amber"}`} title={s.sla_breached ? "SLA breach flagged" : "Past its promise"}>
                          <Icon name="flag" size={13} /> {s.sla_breached ? "SLA breach" : "overdue"}
                        </span>
                      )}
                    </td>
                    <td><span className="carrier">{s.carrier_code}</span></td>
                    <td>{s.origin} <Icon name="arrow-right" size={12} /> {s.destination}</td>
                    <td title={formatTimestamp(s.promised_delivery_at)}>{relativeTime(s.promised_delivery_at, now)}</td>
                    <td title={formatTimestamp(s.created_at)}>{relativeTime(s.created_at, now)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > shown && (
          <button type="button" className="ghost" onClick={() => { setShown((n) => n + SHOWN_STEP); }}>
            Show {Math.min(SHOWN_STEP, rows.length - shown)} more of {rows.length - shown}
          </button>
        )}
      </div>
    </section>
  );
}
