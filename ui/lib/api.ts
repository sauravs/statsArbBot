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

async function proxyPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    // FastAPI HTTPException → {detail: string}; validation errors → {detail: []}.
    const msg =
      typeof detail?.detail === "string"
        ? detail.detail
        : `API ${path} failed: ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

/** Authenticated readiness probe — proves UI → proxy → API → DB. */
export function getSystemHealth(): Promise<SystemHealth> {
  return proxyGet<SystemHealth>("api/system/health");
}

// ── Cointegration scan & pairs (Phase 2) ─────────────────────────────────────

export interface PairRecord {
  base_market: string;
  quote_market: string;
  hedge_ratio: number;
  intercept: number;
  half_life: number;
  zero_crossings: number;
  p_value: number;
  z_score: number | null;
  spread_std: number | null;
  scanned_at: string | null;
  window_start: string | null;
  window_end: string | null;
  exchange: string;
  mode: string;
}

export interface PairsResponse {
  pairs: PairRecord[];
  count: number;
  scanned_at: string | null;
  exchange: string;
  mode: string;
  error?: string | null;
}

export interface ScanStatus {
  running: boolean;
  phase: number;
  progress_msg: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  markets_fetched: number;
  total_markets: number;
  pairs_tested: number;
  pairs_found: number;
  total_pairs: number;
  timed_out: boolean;
}

/** The latest scan's cointegrated pairs (read from the DB — survives reload). */
export function getPairs(): Promise<PairsResponse> {
  return proxyGet<PairsResponse>("api/pairs");
}

export function getScanStatus(): Promise<ScanStatus> {
  return proxyGet<ScanStatus>("api/scan/status");
}

// ── Pair detail series (Phase 3) ─────────────────────────────────────────────

/** A {time, value} chart point; `time` is UNIX seconds (UTC). */
export interface TimePoint {
  time: number;
  value: number;
}

export interface PairMarker {
  time: number;
  kind: "entry" | "exit";
  side: string; // "LONG_SPREAD" | "SHORT_SPREAD" on entries, "" on exits
  reason: string; // "ENTRY" | "TAKE_PROFIT" | "STOP_LOSS_ZSCORE"
  zscore: number;
}

export interface PairSeries {
  base_market: string;
  quote_market: string;
  hedge_ratio: number;
  intercept: number;
  half_life: number | null;
  zscore_window: number;
  entry_threshold: number;
  exit_threshold: number;
  stop_threshold: number;
  window_start: string | null;
  window_end: string | null;
  count: number;
  normalized: { base: TimePoint[]; quote: TimePoint[] };
  spread: { mean: number; std: number; series: TimePoint[] };
  zscore: { series: TimePoint[]; markers: PairMarker[] };
}

/** The 3-panel chart series for one cointegrated pair (PRD F3). */
export function getPairSeries(
  base: string,
  quote: string,
): Promise<PairSeries> {
  return proxyGet<PairSeries>(
    `api/pairs/${encodeURIComponent(base)}/${encodeURIComponent(quote)}/series`,
  );
}

export function startScan(quick = false): Promise<{ message: string; started: boolean }> {
  return proxyPost("api/scan/start", { quick });
}

export function resetScan(): Promise<ScanStatus> {
  return proxyPost("api/scan/reset");
}
