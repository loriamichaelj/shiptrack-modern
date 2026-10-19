import { CLOUD_HEADER, REGION_HEADER, STACK_HEADER } from "./api";

/** Which stack served the page, and where: modern sends its cloud and region (ADR-0039), legacy does not. */
export interface ServerIdentity {
  stack: string;
  cloud: string | null;
  region: string | null;
}

/**
 * Asks the server that served this page which stack it is, so the badge is right before any API
 * call. It reads the X-ShipTrack-Stack, -Cloud, and -Region headers of a GET of the UI's own base
 * path, which both stacks answer with the stack header whatever the status, and which the load
 * balancer routes with the page. Returns null when there is no stack header or no answer.
 */
export async function probeStack(signal?: AbortSignal): Promise<ServerIdentity | null> {
  try {
    const response = await fetch(import.meta.env.BASE_URL, { cache: "no-store", signal });
    void response.body?.cancel();
    const stack = response.headers.get(STACK_HEADER);
    if (stack === null || stack === "") return null;
    return {
      stack,
      cloud: response.headers.get(CLOUD_HEADER) || null,
      region: response.headers.get(REGION_HEADER) || null,
    };
  } catch {
    return null;
  }
}
