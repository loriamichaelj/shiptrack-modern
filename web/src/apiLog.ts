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

const MAX_CALLS = 60;
const MAX_BODY = 4000;

let calls: ApiCall[] = [];
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

export function clearApiCalls(): void {
  calls = [];
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

function truncate(text: string): string {
  return text.length > MAX_BODY ? `${text.slice(0, MAX_BODY)}\n… ${text.length - MAX_BODY} more characters` : text;
}

function record(call: Omit<ApiCall, "id" | "at">): void {
  calls = [{ id: nextId, at: Date.now(), ...call }, ...calls].slice(0, MAX_CALLS);
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
