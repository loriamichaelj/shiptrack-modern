import { useEffect } from "react";
import { Link } from "react-router";
import type { ShipmentStatus } from "../api";
import { DonutChart } from "../components/Charts";
import { LineChart } from "../components/LineChart";
import { StatCard } from "../components/StatCard";
import { STATUS_ICONS } from "../components/StatusBadge";
import { statusLabel } from "../format";
import { Icon } from "../icons";
import { CARRIERS, MAX_RATE, MIN_RATE, type FeedItem, type Snapshot } from "../live/engine";
import { useRuntime, useEngine } from "../live/runtime";
import { useStack } from "../stack";
import { STATUS_ORDER } from "../stats";

const COLUMNS: ShipmentStatus[] = STATUS_ORDER;
const KIND_ICON: Record<FeedItem["kind"], "plus" | "send" | "refresh" | "check-circle" | "activity" | "alert"> = {
  created: "plus",
  event: "send",
  duplicate: "refresh",
  applied: "check-circle",
  read: "activity",
  error: "alert",
};

function recentRate(snapshot: Snapshot): number {
  const last = snapshot.seconds.slice(-6, -1);
  return last.length === 0 ? 0 : last.reduce((n, s) => n + s.requests, 0) / last.length;
}

export function LivePage() {
  // The engine belongs to the app, not to this page: traffic started here keeps running while
  // Browse or any other page is open, and Browse shows the same shipments as they change.
  const { engine } = useRuntime();
  const snap = useEngine();
  const { setStack } = useStack();

  useEffect(() => {
    if (snap.stack !== null) setStack(snap.stack);
  }, [snap.stack, setStack]);

  const okShare = snap.totals.requests === 0 ? 100 : Math.round(((snap.totals.requests - snap.totals.errors) / snap.totals.requests) * 100);
  const counts = Object.fromEntries(COLUMNS.map((s) => [s, snap.board.filter((c) => c.status === s).length])) as Record<ShipmentStatus, number>;
  // The second in progress is not drawn: it is partial and would dip at the edge of every chart.
  const complete = snap.seconds.slice(0, -1);
  const lastSecond = complete.slice(-1)[0];
  const pendingNow = snap.board.filter((c) => c.pending !== null).length;

  return (
    <section aria-labelledby="live-heading">
      <div className="page-head">
        <h1 id="live-heading">
          <Icon name="activity" size={24} /> Live traffic
          <span className={`live-dot ${snap.running ? "live-on" : ""}`} aria-hidden="true" />
          <span className="live-label">{snap.running ? "LIVE" : "PAUSED"}</span>
        </h1>
      </div>
      <div className="card">
        <h2>Shipments moving through their statuses</h2>
        <div className="board" role="group" aria-label="Shipments by status">
          {COLUMNS.map((status) => {
            const cards = snap.board.filter((c) => c.status === status).slice(-14).reverse();
            return (
              <div key={status} className={`lane lane-${status.toLowerCase().replaceAll("_", "-")}`}>
                <h3 className="lane-title">
                  <Icon name={STATUS_ICONS[status] ?? "info"} size={22} />
                  <span className="lane-label">{statusLabel(status)}</span>
                  <span className="lane-count">{counts[status]}</span>
                </h3>
                <div className="column">
                  <div className="column-body">
                    {cards.map((card) => (
                      <span key={card.id} className={`ship mono ${card.pending !== null ? "ship-pending" : ""}`} title={card.pending !== null ? `${card.pending} accepted, not shown yet` : card.trackingNumber}>
                        …{card.trackingNumber.slice(-5)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <p className="muted">A pulsing chip has an event the API accepted that the shipment does not show yet: it is in the queue. The same shipments move on the <Link to="/shipments">Browse</Link> page.</p>
      </div>
      <p className="lede">
        This page makes real calls to the API from your browser: it creates shipments, sends tracking events, and reads them
        back, and everything below moves as the answers arrive.
      </p>

      <div className="card controls">
        {snap.running ? (
          <button type="button" onClick={() => { engine.stop(); }}>
            <Icon name="x" size={16} /> Stop traffic
          </button>
        ) : (
          <button type="button" onClick={() => { engine.start(); }}>
            <Icon name="send" size={16} /> Start traffic
          </button>
        )}
        <label htmlFor="rate" className="rate-label">
          Rate <strong>{snap.rate} requests/s</strong>
        </label>
        <input
          id="rate"
          type="range"
          min={MIN_RATE}
          max={MAX_RATE}
          value={snap.rate}
          onChange={(e) => { engine.setRate(Number(e.target.value)); }}
        />
        <button type="button" className="ghost" onClick={() => { engine.reset(); }}>
          <Icon name="refresh" size={16} /> Reset
        </button>
        <span className="muted">
          {snap.inFlight} in flight · served by <strong>{snap.stack ?? "unknown"}</strong> · carriers {CARRIERS.join(", ")}
        </span>
      </div>
      {snap.stoppedBecause !== null && <p className="muted" role="status">{snap.stoppedBecause}</p>}

      <div className="stats live-stats">
        <StatCard icon="activity" label="Requests per second" value={recentRate(snap).toFixed(1)} hint={`${snap.totals.requests} so far`} tone="blue" />
        <StatCard icon="check-circle" label="Success" value={`${okShare}%`} hint={`${snap.totals.errors} errors`} tone={snap.totals.errors > 0 ? "amber" : "green"} />
        <StatCard icon="clock" label="Latency p50 / p95" value={`${snap.latency.p50} / ${snap.latency.p95} ms`} hint="seen from this browser" tone="violet" />
        <StatCard icon="package" label="Shipments created" value={snap.totals.created} tone="slate" />
        <StatCard icon="send" label="Events applied / sent" value={`${snap.totals.applied} / ${snap.totals.eventsSent}`} hint={`${pendingNow} waiting, ${snap.totals.duplicates} repeats`} tone="green" />
        <StatCard
          icon="server"
          label="Apply lag p50 / p95"
          value={snap.applyLag.p50 === null ? "…" : `${snap.applyLag.p50} / ${snap.applyLag.p95 ?? 0} ms`}
          hint="202 to visible, through the queue"
          tone="red"
        />
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Throughput</h2>
          <LineChart
            caption="Requests and errors per second"
            unit="per second"
            series={[
              { label: "Requests", values: complete.map((s) => s.requests), className: "line-blue" },
              { label: "Errors", values: complete.map((s) => s.errors), className: "line-red" },
            ]}
          />
          <p className="throughput-legend muted">
            <span className="legend-item"><span className="swatch line-blue-bg" /> requests · {lastSecond?.requests ?? 0}/s</span>
            <span className="legend-item"><span className="swatch line-red-bg" /> errors · {lastSecond?.errors ?? 0}/s</span>
            <span className="legend-note">last second</span>
          </p>
        </div>
        <div className="card">
          <h2>Latency</h2>
          <LineChart
            caption="p95 latency per second in milliseconds"
            unit="ms, p95"
            series={[{ label: "p95", values: complete.map((s) => s.p95), className: "line-violet" }]}
          />
          <p className="muted">One create, one event, or one read is one request. Writes wait for the queue send before they answer.</p>
        </div>
      </div>

      <div className="grid-2 live-row">
        <div className="card">
          <h2>Where the shipments are</h2>
          <DonutChart
            segments={COLUMNS.map((s) => ({ label: statusLabel(s), value: counts[s], className: `seg-${s.toLowerCase().replaceAll("_", "-")}` }))}
            centre={String(snap.board.length)}
            caption="tracked"
          />
        </div>
        <div className="card feed-card">
          <h2>Live feed</h2>
          {snap.feed.length === 0 ? (
            <p className="muted">Nothing yet. Press Start traffic.</p>
          ) : (
            <div className="feed" aria-live="off">
              {snap.feed.slice(0, 14).map((item) => (
                <div key={item.id} className={`feed-row feed-${item.ok ? item.kind : "error"}`}>
                  <span className="feed-icon"><Icon name={KIND_ICON[item.kind]} size={14} /></span>
                  <span className="mono feed-number">{item.trackingNumber ?? "—"}</span>
                  <span className="feed-text">{item.text}</span>
                  <span className="feed-ms">{item.ms === null ? "" : `${item.ms} ms`}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

    </section>
  );
}
