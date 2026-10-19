import { useEffect, useState } from "react";
import { ApiCallRow } from "../components/ApiInspector";
import { getApiCalls, loggedFetch, MAX_CALLS, useApiCalls, useApiTotals, type ApiCall } from "../apiLog";
import { readiness } from "../client";
import { stackLabel } from "../format";
import { Icon } from "../icons";
import { StatCard } from "../components/StatCard";
import { useShipments, useSync } from "../live/runtime";
import { useStack } from "../stack";
import { relativeTime } from "../stats";
import { useNow } from "../useNow";

interface Health {
  ready: boolean | null;
  reason: string | null;
  ms: number | null;
  stack: string | null;
  error: string | null;
}

/** The read-only calls the explorer can make: nothing here changes data. */
export const EXPLORER_CALLS = [
  { label: "Liveness", path: "/healthz", note: "The process answers. Never looks at a dependency." },
  { label: "Readiness", path: "/readyz", note: "Whether the database is reachable and the schema is one this build knows." },
  { label: "Three shipments", path: "/api/v1/shipments?limit=3", note: "A page of the list. next_cursor continues it." },
  { label: "Unknown tracking number", path: "/api/v1/track/MF0000000000", note: "A 404 with the error envelope: code, message, request_id." },
] as const;

export function SystemPage() {
  const { setStack } = useStack();
  const calls = useApiCalls();
  const totals = useApiTotals();
  const rows = useShipments();
  const sync = useSync();
  const now = useNow();
  const [health, setHealth] = useState<Health>({ ready: null, reason: null, ms: null, stack: null, error: null });
  const [last, setLast] = useState<ApiCall | null>(null);

  const [checks, setChecks] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const started = performance.now();
      const result = await readiness(controller.signal).catch(() => null);
      if (result === null || controller.signal.aborted) return;
      if (result.stack !== null) setStack(result.stack);
      // /readyz answers 503 when it is not ready, which the client reports as a failure.
      setHealth({
        ready: result.ok ? result.data.ready : false,
        reason: result.ok ? result.data.reason : result.message,
        ms: Math.round(performance.now() - started),
        stack: result.stack,
        error: null,
      });
    })();
    return () => {
      controller.abort();
    };
  }, [checks, setStack]);

  async function explore(path: string) {
    await loggedFetch(path, { headers: { Accept: "application/json" } }).catch(() => undefined);
    setLast(getApiCalls()[0] ?? null);
  }

  return (
    <section aria-labelledby="system-heading">
      <h1 id="system-heading"><Icon name="server" size={24} /> System</h1>
      <div className="stats">
        <StatCard
          icon={health.ready === false ? "alert" : "check-circle"}
          label="Readiness"
          value={health.ready === null ? "…" : health.ready ? "Ready" : "Not ready"}
          hint={health.reason ?? undefined}
          tone={health.ready === false ? "red" : "green"}
        />
        <StatCard icon="server" label="Served by" value={health.stack === null ? "unknown" : stackLabel(health.stack)} tone="violet" />
        <StatCard icon="activity" label="Readiness latency" value={health.ms === null ? "…" : `${health.ms} ms`} tone="blue" />
        <StatCard
          icon="database"
          label="API calls this session"
          value={totals.calls}
          hint={`${totals.failed} failed · avg ${totals.calls === 0 ? 0 : Math.round(totals.totalMs / totals.calls)} ms`}
          tone="slate"
        />
        <StatCard
          icon="package"
          label="Shipments in this browser"
          value={rows.length}
          hint={
            sync.lastSyncedAt === null
              ? "not synced with the server yet"
              : `synced ${relativeTime(new Date(sync.lastSyncedAt).toISOString(), now)}`
          }
          tone="blue"
        />
      </div>
      <p>
        <button type="button" className="ghost" onClick={() => { setChecks((n) => n + 1); }}>
          <Icon name="refresh" size={16} /> Check again
        </button>
      </p>

      <div className="card">
        <h2><Icon name="terminal" size={18} /> API explorer</h2>
        <p className="muted">Each button makes a real request to this site. The call, its timing, the stack that answered, and the body appear below and in the activity panel.</p>
        <div className="explorer">
          {EXPLORER_CALLS.map((c) => (
            <button key={c.path} type="button" className="ghost" onClick={() => void explore(c.path)} title={c.note}>
              <span className="call-method">GET</span> {c.label}
            </button>
          ))}
        </div>
        {last !== null && <ApiCallRow key={last.id} call={last} />}
        <p className="muted">
          The list keeps the latest {MAX_CALLS} calls ({calls.length} now); the count above is every call since the page
          loaded.
        </p>
      </div>
    </section>
  );
}
