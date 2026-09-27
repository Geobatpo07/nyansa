import { UpstreamError } from '../ports.js';

export type FetchFn = typeof fetch;

/** Sends a JSON request and parses the JSON response; any failure becomes an UpstreamError. */
export async function requestJson<T>(
  fetchFn: FetchFn,
  service: 'ollama' | 'qdrant',
  url: string,
  init: { method: string; body?: unknown; headers?: Record<string, string>; timeoutMs: number },
): Promise<{ status: number; body: T }> {
  let response: Response;
  try {
    response = await fetchFn(url, {
      method: init.method,
      headers: { 'content-type': 'application/json', ...init.headers },
      signal: AbortSignal.timeout(init.timeoutMs),
      ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
    });
  } catch (err) {
    throw new UpstreamError(service, `request to ${new URL(url).pathname} failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  const text = await response.text();
  if (!response.ok) {
    throw new UpstreamError(service, `HTTP ${response.status} on ${new URL(url).pathname}: ${text.slice(0, 300)}`, response.status);
  }
  try {
    return { status: response.status, body: (text === '' ? {} : JSON.parse(text)) as T };
  } catch {
    throw new UpstreamError(service, `invalid JSON from ${new URL(url).pathname}`, response.status);
  }
}
