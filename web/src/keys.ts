/**
 * A random Idempotency-Key. `crypto.randomUUID` exists only in secure contexts and this site can be
 * served over plain HTTP, so it is built from getRandomValues, which is available everywhere.
 */
export function newIdempotencyKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return `ui-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}
