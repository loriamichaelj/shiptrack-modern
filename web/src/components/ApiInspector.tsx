import { clearApiCalls, useApiCalls, type ApiCall } from "../apiLog";
import { stackLabel } from "../format";
import { Icon } from "../icons";

function tone(call: ApiCall): string {
  if (call.status === null) return "bad";
  if (call.status >= 500) return "bad";
  if (call.status >= 400) return "warn";
  return "good";
}

function time(at: number): string {
  return new Date(at).toISOString().slice(11, 19);
}

export function ApiCallRow({ call }: { call: ApiCall }) {
  return (
    <details className="call">
      <summary>
        <span className={`call-status call-${tone(call)}`}>{call.status ?? "ERR"}</span>
        <span className="call-method">{call.method}</span>
        <span className="call-url">{call.url}</span>
        <span className="call-ms">{call.ms} ms</span>
      </summary>
      <div className="call-body">
        <dl className="call-meta">
          <dt>Time</dt>
          <dd>{time(call.at)} UTC</dd>
          <dt>Served by</dt>
          <dd>{call.stack === null ? "unknown" : stackLabel(call.stack)}</dd>
          <dt>Request id</dt>
          <dd>{call.requestId ?? "none"}</dd>
          {call.note !== null && (
            <>
              <dt>Note</dt>
              <dd>{call.note}</dd>
            </>
          )}
        </dl>
        {call.requestBody !== null && (
          <>
            <div className="call-title">Request body</div>
            <pre>{call.requestBody}</pre>
          </>
        )}
        {call.responseBody !== null && (
          <>
            <div className="call-title">Response body</div>
            <pre>{call.responseBody}</pre>
          </>
        )}
      </div>
    </details>
  );
}

/** A panel listing the API calls this page has made, newest first, with their bodies. */
export function ApiInspector({ onClose }: { onClose: () => void }) {
  const calls = useApiCalls();
  return (
    <aside className="inspector" aria-label="API activity">
      <div className="inspector-head">
        <h2>
          <Icon name="activity" size={18} /> API activity
        </h2>
        <button type="button" className="ghost" onClick={clearApiCalls}>
          Clear
        </button>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close API activity">
          <Icon name="x" size={16} />
        </button>
      </div>
      {calls.length === 0 ? (
        <p className="muted">No calls yet. Search for a shipment or open the shipments page.</p>
      ) : (
        <div className="calls">
          {calls.map((call) => (
            <ApiCallRow key={call.id} call={call} />
          ))}
        </div>
      )}
    </aside>
  );
}
