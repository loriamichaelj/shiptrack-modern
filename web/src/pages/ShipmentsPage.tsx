import { useMemo, useState } from "react";
import { Link } from "react-router";
import type { ShipmentStatus } from "../api";
import { DEFAULT_SORT, downloadCsv, matchesPlace, nextSort, sortRows, type Sort, type SortKey } from "../browse";
import { BarChart, DonutChart, type Segment } from "../components/Charts";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, statusLabel } from "../format";
import { Icon } from "../icons";
import { useEngine, useServerSync, useShipments, useSync } from "../live/runtime";
import type { Row } from "../live/store";
import { relativeTime, STATUS_ORDER } from "../stats";
import { useNow } from "../useNow";

/** The server's list is read again this often while Browse is open, to pick up other clients. */
export const SYNC_EVERY_MS = 15_000;
const FLASH_MS = 2500;
const FIRST_ROWS = 100;

function isOverdue(row: Row, now: number): boolean {
  return row.status !== "DELIVERED" && Date.parse(row.promisedAt) < now;
}

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "trackingNumber", label: "Tracking number" },
  { key: "status", label: "Status" },
  { key: "carrier", label: "Carrier" },
  { key: "route", label: "Route" },
  { key: "promisedAt", label: "Promised" },
  { key: "createdAt", label: "Created" },
];

function SortableHeader({ column, sort, onSort }: { column: (typeof COLUMNS)[number]; sort: Sort; onSort: (key: SortKey) => void }) {
  const active = sort.key === column.key;
  return (
    <th aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : undefined}>
      <button type="button" className="sort" onClick={() => { onSort(column.key); }}>
        {column.label}
        <span className="sort-mark" aria-hidden="true">{active ? (sort.direction === "asc" ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}

export function ShipmentsPage() {
  const rows = useShipments();
  const sync = useSync();
  const engine = useEngine();
  const { refresh } = useServerSync(SYNC_EVERY_MS);
  const now = useNow();
  const [status, setStatus] = useState<ShipmentStatus | "">("");
  const [carrier, setCarrier] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [text, setText] = useState("");
  const [place, setPlace] = useState("");
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const [showAll, setShowAll] = useState(false);

  const summary = useMemo(() => {
    const byStatus = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<ShipmentStatus, number>;
    const carriers = new Map<string, number>();
    let overdue = 0;
    let breached = 0;
    for (const row of rows) {
      byStatus[row.status] += 1;
      carriers.set(row.carrier, (carriers.get(row.carrier) ?? 0) + 1);
      if (isOverdue(row, now)) overdue += 1;
      if (row.slaBreached) breached += 1;
    }
    const byCarrier = [...carriers.entries()]
      .map(([name, count]) => ({ carrier: name, count }))
      .sort((a, b) => b.count - a.count || a.carrier.localeCompare(b.carrier));
    return { byStatus, byCarrier, overdue, breached };
    // `now` is left out on purpose: whether a shipment is overdue changes by the minute, not the second.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  const filtered = useMemo(() => {
    const needle = text.trim().toUpperCase();
    return rows
      .filter((r) => status === "" || r.status === status)
      .filter((r) => carrier === "" || r.carrier === carrier)
      .filter((r) => !overdueOnly || isOverdue(r, now))
      .filter((r) => needle === "" || r.trackingNumber.includes(needle))
      .filter((r) => matchesPlace(r, place));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, status, carrier, overdueOnly, text, place]);

  const sorted = useMemo(() => sortRows(filtered, sort), [filtered, sort]);
  const isDefaultSort = sort.key === DEFAULT_SORT.key && sort.direction === DEFAULT_SORT.direction;

  const visible = showAll ? sorted : sorted.slice(0, FIRST_ROWS);
  const segments: Segment[] = STATUS_ORDER.map((s) => ({
    label: statusLabel(s),
    value: summary.byStatus[s],
    className: `seg-${s.toLowerCase().replaceAll("_", "-")}`,
  }));
  const moving = summary.byStatus.PICKED_UP + summary.byStatus.IN_TRANSIT + summary.byStatus.OUT_FOR_DELIVERY;
  const delivered = summary.byStatus.DELIVERED;

  return (
    <section aria-labelledby="ship-heading">
      <div className="page-head">
        <h1 id="ship-heading">
          <Icon name="grid" size={24} /> Browse
          {engine.running && (
            <span className="live-tag">
              <span className="live-dot live-on" aria-hidden="true" /> moving live
            </span>
          )}
        </h1>
        <div className="page-actions">
          <button type="button" className="ghost" onClick={refresh}>
            <Icon name="refresh" size={16} /> Sync now
          </button>
          <Link to="/shipments/new" className="button">
            <Icon name="plus" size={16} /> New shipment
          </Link>
        </div>
      </div>

      <p className="muted" role="status">
        {sync.error !== null
          ? `${rows.length} shipments. The last sync failed: ${sync.error}`
          : sync.syncing
            ? `${rows.length} shipments. Reading the server's list (page ${sync.pagesRead + 1})…`
            : sync.lastSyncedAt === null
              ? `${rows.length} shipments.`
              : `${rows.length} shipments, in step with the server as of ${relativeTime(new Date(sync.lastSyncedAt).toISOString(), now)}. Changes from the live page appear here as they happen.`}
      </p>

      <div className="stats">
        <StatCard icon="package" label="Shipments" value={rows.length} tone="blue" />
        <StatCard icon="truck" label="On the way" value={moving} tone="violet" />
        <StatCard
          icon="check-circle"
          label="Delivered"
          value={delivered}
          hint={rows.length === 0 ? undefined : `${Math.round((delivered / rows.length) * 100)}% of all`}
          tone="green"
        />
        <StatCard icon="clock" label="Overdue" value={summary.overdue} hint={`${summary.breached} flagged by the SLA scan`} tone="amber" />
        <StatCard icon="alert" label="Exceptions" value={summary.byStatus.EXCEPTION} tone="red" />
      </div>

      <div className="charts">
        <div className="card">
          <h2>By status</h2>
          <DonutChart segments={segments} centre={String(rows.length)} caption="shipments" />
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
          <input id="f-text" type="text" placeholder="Filter by tracking number" value={text} onChange={(e) => { setText(e.target.value); }} />
          <label className="visually-hidden" htmlFor="f-place">Origin or destination contains</label>
          <input id="f-place" type="text" placeholder="Filter by origin or destination" value={place} onChange={(e) => { setPlace(e.target.value); }} />
          <label className="visually-hidden" htmlFor="f-carrier">Carrier</label>
          <select id="f-carrier" value={carrier} onChange={(e) => { setCarrier(e.target.value); }}>
            <option value="">All carriers</option>
            {summary.byCarrier.map((c) => (
              <option key={c.carrier} value={c.carrier}>{c.carrier}</option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={overdueOnly} onChange={(e) => { setOverdueOnly(e.target.checked); }} />
            Overdue only
          </label>
          <button
            type="button"
            className="ghost"
            disabled={filtered.length === 0}
            onClick={() => { downloadCsv(sorted, new Date()); }}
          >
            <Icon name="download" size={16} /> Download CSV
          </button>
        </div>
        <div className="chips" role="group" aria-label="Filter by status">
          <button type="button" className={`chip ${status === "" ? "chip-on" : ""}`} aria-pressed={status === ""} onClick={() => { setStatus(""); }}>
            All
          </button>
          {STATUS_ORDER.map((s) => (
            <button key={s} type="button" className={`chip chip-${s.toLowerCase().replaceAll("_", "-")} ${status === s ? "chip-on" : ""}`} aria-pressed={status === s} onClick={() => { setStatus(s); }}>
              {statusLabel(s)} <span className="chip-count">{summary.byStatus[s]}</span>
            </button>
          ))}
        </div>

        {filtered.length === 0 ? (
          <p className="muted">{sync.syncing || sync.lastSyncedAt === null ? "Waiting for the first page…" : "No shipments match."}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((column) => (
                    <SortableHeader key={column.key} column={column} sort={sort} onSort={(key) => { setSort((current) => nextSort(current, key)); }} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id} className={now - r.touchedAt < FLASH_MS ? "row-flash" : undefined}>
                    <td>
                      <Link to={`/shipments/${r.id}`} className="mono">{r.trackingNumber}</Link>
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                      {isOverdue(r, now) && (
                        <span className={`flag ${r.slaBreached ? "flag-red" : "flag-amber"}`}>
                          <Icon name="flag" size={13} /> {r.slaBreached ? "SLA breach" : "overdue"}
                        </span>
                      )}
                    </td>
                    <td><span className="carrier">{r.carrier}</span></td>
                    <td>{r.origin} <Icon name="arrow-right" size={12} /> {r.destination}</td>
                    <td title={formatTimestamp(r.promisedAt)}>{relativeTime(r.promisedAt, now)}</td>
                    <td title={formatTimestamp(r.createdAt)}>{relativeTime(r.createdAt, now)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!showAll && filtered.length > FIRST_ROWS && (
          <p className="muted">
            Showing the {isDefaultSort ? "newest" : "first"} {FIRST_ROWS} of {filtered.length}.{" "}
            <button type="button" className="ghost" onClick={() => { setShowAll(true); }}>
              Show all {filtered.length}
            </button>
          </p>
        )}
      </div>
    </section>
  );
}
