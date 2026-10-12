import { useSyncExternalStore } from "react";
import { STACK_HEADER } from "./api";

/** One API call the page made, kept so that a person can see how the API behaves. */
export interface ApiCall {
  id: number;
  at: number;
  method: string;
  url: string;
  status: number | null;
  ok: boolean;
  ms: number;
  stack: string | null;
  requestId: string | null;
  requestBody: string | null;
  responseBody: string | null;
  note: string | null;
}

/** How many calls are kept to look at. The totals below are not limited by it. */
export const MAX_CALLS = 200;
const MAX_BODY = 4000;

export interface ApiTotals {
  calls: number;
  failed: number;
  totalMs: number;
  since: number | null;
}

let calls: ApiCall[] = [];
let totals: ApiTotals = { calls: 0, failed: 0, totalMs: 0, since: null };
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  calls = [...calls];
  listeners.forEach((listener) => {
    listener();
  });
}

export function getApiCalls(): readonly ApiCall[] {
  return calls;
}

/** Every call since the page loaded, however many are still kept in the list. */
export function getApiTotals(): ApiTotals {
  return totals;
}

export function clearApiCalls(): void {
  calls = [];
  totals = { calls: 0, failed: 0, totalMs: 0, since: null };
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The recorded calls, newest first, re-rendered as they arrive. */
export function useApiCalls(): readonly ApiCall[] {
  return useSyncExternalStore(subscribe, getApiCalls, getApiCalls);
}

export function useApiTotals(): ApiTotals {
  return useSyncExternalStore(subscribe, getApiTotals, getApiTotals);
}

function truncate(text: string): string {
  return text.length > MAX_BODY ? `${text.slice(0, MAX_BODY)}\n… ${text.length - MAX_BODY} more characters` : text;
}

function record(call: Omit<ApiCall, "id" | "at">): void {
  const at = Date.now();
  calls = [{ id: nextId, at, ...call }, ...calls].slice(0, MAX_CALLS);
  totals = {
    calls: totals.calls + 1,
    failed: totals.failed + (call.ok ? 0 : 1),
    totalMs: totals.totalMs + call.ms,
    since: totals.since ?? at,
  };
  nextId += 1;
  emit();
}

interface LoggedInit extends RequestInit {
  /** Do not read the body into the log (a file, for example). */
  skipBody?: boolean;
  /** A short remark shown beside the call. */
  note?: string;
}

/** `fetch`, with the call written to the activity log. The response is returned untouched. */
export async function loggedFetch(url: string, init: LoggedInit = {}): Promise<Response> {
  const { skipBody = false, note = null, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const started = performance.now();
  const requestBody = typeof rest.body === "string" ? truncate(rest.body) : null;
  let response: Response;
  try {
    response = await fetch(url, rest);
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")) {
      record({
        method, url, status: null, ok: false, ms: Math.round(performance.now() - started),
        stack: null, requestId: null, requestBody, responseBody: null, note: "no response",
      });
    }
    throw error;
  }
  const ms = Math.round(performance.now() - started);
  let responseBody: string | null = null;
  const type = response.headers.get("Content-Type") ?? "";
  if (!skipBody && (type.includes("json") || type.includes("text"))) {
    responseBody = truncate(await response.clone().text().catch(() => ""));
  }
  record({
    method, url, status: response.status, ok: response.ok, ms,
    stack: response.headers.get(STACK_HEADER),
    requestId: response.headers.get("X-Request-Id"),
    requestBody, responseBody, note,
  });
  return response;
}
