/**
 * Typed API client. Every backend call goes through the same-origin Next.js
 * proxy (`/api/proxy/...`), which verifies the session cookie and injects the
 * `X-API-Key` header before forwarding to FastAPI. Components never call the
 * backend directly.
 *
 * Phase 0 exposes only the system-health probe; this file grows per phase.
 */

export interface SystemHealth {
  status: string;
  database: string;
  environment: string;
}

async function proxyGet<T>(path: string): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

/** Authenticated readiness probe — proves UI → proxy → API → DB. */
export function getSystemHealth(): Promise<SystemHealth> {
  return proxyGet<SystemHealth>("api/system/health");
}
