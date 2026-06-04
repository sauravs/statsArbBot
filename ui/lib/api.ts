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
  /** Active market-data source: "fake" (synthetic demo) or "dydx" (live indexer). */
  data_source?: string;
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

/** Current price (latest close) per market across the latest scan's pairs. */
export interface PairPricesResponse {
  prices: Record<string, number>;
  error?: string | null;
}

/** Light, pollable price read for the pairs table (issue #37 PR-2). */
export function getPairPrices(): Promise<PairPricesResponse> {
  return proxyGet<PairPricesResponse>("api/pairs/prices");
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

// ── Live Manual Trading (Phase 4, PRD F4) ────────────────────────────────────

export interface ManualTrade {
  id: string;
  exchange: string;
  mode: string;
  base_market: string;
  quote_market: string;
  hedge_ratio: number;
  half_life: number;
  z_score: number;
  spread_value: number;
  entry_price_leg1: number;
  entry_price_leg2: number;
  capital_leg1_usd: number;
  capital_leg2_usd: number;
  recorded_at: string;
  status: "OPEN" | "CLOSED";
  closed_at: string | null;
  exit_price_leg1: number | null;
  exit_price_leg2: number | null;
  pnl: number | null;
}

export interface ManualTradesResponse {
  trades: ManualTrade[];
  count: number;
  error?: string | null;
}

/** Record a manual trade off a scanned pair; entry prices captured server-side. */
export function recordManualTrade(input: {
  base_market: string;
  quote_market: string;
  capital_leg1_usd: number;
  capital_leg2_usd: number;
}): Promise<ManualTrade> {
  return proxyPost<ManualTrade>("api/manual/record", input);
}

/** List recorded manual trades (newest first). */
export function getManualTrades(): Promise<ManualTradesResponse> {
  return proxyGet<ManualTradesResponse>("api/manual");
}

/** Portfolio summary across manual trades (issue #37 PR-2). */
export interface ManualPortfolio {
  allocated_capital: number;
  unrealized_pnl: number | null;
  realized_pnl: number;
  open_count: number;
  closed_count: number;
  error?: string | null;
}

/** Allocated capital + live mark-to-market over OPEN trades, realized over CLOSED. */
export function getManualPortfolio(): Promise<ManualPortfolio> {
  return proxyGet<ManualPortfolio>("api/manual/portfolio");
}

/** Mark a manual trade closed with exit prices; server computes & stores P&L. */
export function closeManualTrade(
  id: string,
  input: { exit_price_leg1: number; exit_price_leg2: number },
): Promise<ManualTrade & { pnl_breakdown: { pnl_leg1: number; pnl_leg2: number; pnl: number; base_is_long: boolean } }> {
  return proxyPost(`api/manual/${encodeURIComponent(id)}/close`, input);
}

export function startScan(quick = false): Promise<{ message: string; started: boolean }> {
  return proxyPost("api/scan/start", { quick });
}

export function resetScan(): Promise<ScanStatus> {
  return proxyPost("api/scan/reset");
}

// ── Live Trading Bot (Phase 5, PRD F5) ───────────────────────────────────────

/** The two live trading modes (a virtual sim account is Phase 6, not the bot). */
export type LiveMode = "forward_test" | "production";

const DEFAULT_EXCHANGE = "dydx";

export interface LiveSession {
  id: string;
  exchange: string;
  mode: string;
  active: boolean;
  started_at: string | null;
  stopped_at: string | null;
}

export interface LiveSessionResponse {
  session: LiveSession | null;
  active: boolean;
}

export interface LiveTrade {
  id: string;
  session_id: string;
  exchange: string;
  mode: string;
  base_market: string;
  quote_market: string;
  base_side: string; // "BUY" | "SELL"
  quote_side: string;
  base_size: number;
  quote_size: number;
  hedge_ratio: number;
  half_life: number;
  entry_z_score: number;
  entry_price_leg1: number;
  entry_price_leg2: number;
  status: "OPEN" | "CLOSED" | "ERROR" | "PENDING";
  opened_at: string | null;
  exit_z_score: number | null;
  exit_price_leg1: number | null;
  exit_price_leg2: number | null;
  exit_reason: string | null;
  pnl: number | null;
  closed_at: string | null;
  error: string | null;
}

export interface LiveTradesResponse {
  trades: LiveTrade[];
  count: number;
}

export interface LiveAccount {
  free_collateral: number;
  equity: number;
}

export interface EntryScanResult {
  opened: number;
  evaluated: number;
  free_collateral?: number;
  collateral_ok?: boolean;
  message: string;
  outcomes: unknown[];
}

export interface ExitManageResult {
  managed: number;
  closed: number;
  message: string;
  outcomes: unknown[];
}

export interface AbortResult {
  positions_closed: { market: string; ok: boolean }[];
  trades_marked: number;
}

function scopeQuery(mode: LiveMode): string {
  return `exchange=${encodeURIComponent(DEFAULT_EXCHANGE)}&mode=${encodeURIComponent(mode)}`;
}

function scopeBody(mode: LiveMode): { exchange: string; mode: LiveMode } {
  return { exchange: DEFAULT_EXCHANGE, mode };
}

/** Current active live session for (dydx, mode), or null. */
export function getLiveSession(mode: LiveMode): Promise<LiveSessionResponse> {
  return proxyGet<LiveSessionResponse>(`api/live/session?${scopeQuery(mode)}`);
}

/** Activate the bot for the mode (idempotent — returns the active session). */
export function startLiveSession(mode: LiveMode): Promise<LiveSession> {
  return proxyPost<LiveSession>("api/live/session/start", scopeBody(mode));
}

/** Deactivate the bot (open trades remain for the exit manager / abort). */
export function stopLiveSession(
  mode: LiveMode,
): Promise<{ stopped_sessions: number }> {
  return proxyPost("api/live/session/stop", scopeBody(mode));
}

/** Run one entry-scan pass; optional entry-Z override (defaults to config 1.5). */
export function runEntryScan(
  mode: LiveMode,
  entryThreshold?: number,
): Promise<EntryScanResult> {
  return proxyPost<EntryScanResult>("api/live/entry-scan", {
    ...scopeBody(mode),
    ...(entryThreshold != null ? { entry_threshold: entryThreshold } : {}),
  });
}

/** Run one exit-management pass (take-profit / stop / time-stop). */
export function runExitManage(mode: LiveMode): Promise<ExitManageResult> {
  return proxyPost<ExitManageResult>("api/live/exit-manage", scopeBody(mode));
}

/** Emergency stop: cancel orders, close every position, mark trades ABORTED. */
export function abortLive(mode: LiveMode): Promise<AbortResult> {
  return proxyPost<AbortResult>("api/live/abort", scopeBody(mode));
}

/** List live trades for the mode, optionally filtered by status. */
export function getLiveTrades(
  mode: LiveMode,
  status?: LiveTrade["status"],
): Promise<LiveTradesResponse> {
  const q = status ? `${scopeQuery(mode)}&status=${status}` : scopeQuery(mode);
  return proxyGet<LiveTradesResponse>(`api/live/trades?${q}`);
}

/** Free collateral + equity from the exchange account. */
export function getLiveAccount(mode: LiveMode): Promise<LiveAccount> {
  return proxyGet<LiveAccount>(`api/live/account?${scopeQuery(mode)}`);
}

// ── Real-Time Simulation (Phase 6, PRD F6) ───────────────────────────────────

export type SimStatus = "RUNNING" | "PAUSED" | "STOPPED";

export interface SimSession {
  id: string;
  exchange: string;
  mode: string;
  label: string | null;
  status: SimStatus;
  starting_capital: number;
  current_capital: number;
  interval_seconds: number;
  zscore_window: number;
  entry_threshold: number;
  exit_threshold: number;
  stop_threshold: number;
  usd_per_trade: number;
  max_active_pairs: number | null;
  slippage_pct: number;
  taker_fee_pct: number;
  funding_freq_h: number;
  tick_count: number;
  last_tick_at: string | null;
  created_at: string | null;
  stopped_at: string | null;
  // Σ closed-trade net P&L — only present on the list endpoint (GET /sessions).
  realised_pnl?: number;
}

export interface SimPosition {
  id: string;
  base_market: string;
  quote_market: string;
  direction: string; // "LONG_BASE" | "SHORT_BASE"
  base_size: number;
  quote_size: number;
  hedge_ratio: number;
  entry_z: number;
  entry_base_px: number;
  entry_quote_px: number;
  entry_time: string | null;
  fee_cost: number;
  funding_pnl: number;
  unrealized_pnl: number | null;
  current_z: number | null;
}

export interface SimTrade {
  id: string;
  base_market: string;
  quote_market: string;
  direction: string;
  entry_time: string | null;
  exit_time: string | null;
  hold_hours: number;
  entry_z: number;
  exit_z: number | null;
  exit_reason: string;
  notional_usd: number;
  gross_pnl: number;
  fee_cost: number;
  funding_pnl: number;
  net_pnl: number;
}

export interface SimOverview {
  session: SimSession;
  positions: SimPosition[];
  trades: SimTrade[];
  equity: number;
  unrealized_pnl: number;
  open_count: number;
  closed_count: number;
}

export interface CreateSimInput {
  label?: string;
  starting_capital: number;
  interval_seconds: number;
  entry_threshold?: number;
  exit_threshold?: number;
  stop_threshold?: number;
  zscore_window?: number;
  usd_per_trade?: number;
  max_active_pairs?: number | null;
  slippage_pct?: number;
  taker_fee_pct?: number;
}

export interface SimTickResult {
  entries?: number;
  exits?: number;
  evaluated?: number;
  funding_accrued?: number;
  current_capital?: number;
  skipped?: boolean;
  reason?: string;
  message?: string;
}

/** Create a real-time simulation session (starts ticking on its interval). */
export function createSimSession(input: CreateSimInput): Promise<SimSession> {
  return proxyPost<SimSession>("api/sim/sessions", input);
}

/** List all simulation sessions (newest first). */
export function listSimSessions(): Promise<{ sessions: SimSession[]; count: number }> {
  return proxyGet("api/sim/sessions");
}

/** Session + open positions (marked to market) + trade history + equity. */
export function getSimSession(id: string): Promise<SimOverview> {
  return proxyGet<SimOverview>(`api/sim/sessions/${encodeURIComponent(id)}`);
}

export function pauseSim(id: string): Promise<SimSession> {
  return proxyPost(`api/sim/sessions/${encodeURIComponent(id)}/pause`);
}

export function resumeSim(id: string): Promise<SimSession> {
  return proxyPost(`api/sim/sessions/${encodeURIComponent(id)}/resume`);
}

export function stopSim(id: string): Promise<{ session: SimSession; positions_closed: number }> {
  return proxyPost(`api/sim/sessions/${encodeURIComponent(id)}/stop`);
}

export function topupSim(id: string, amount: number): Promise<SimSession> {
  return proxyPost(`api/sim/sessions/${encodeURIComponent(id)}/topup`, { amount });
}

/** Run one tick now (manual / deterministic driver; otherwise the scheduler ticks). */
export function tickSim(id: string): Promise<SimTickResult> {
  return proxyPost<SimTickResult>(`api/sim/sessions/${encodeURIComponent(id)}/tick`);
}

// ── Fast-Forward Simulation (Phase 7, PRD F7) ────────────────────────────────

export type FFStatus = "RUNNING" | "COMPLETED" | "STOPPED" | "FAILED";

export interface FFEquityPoint {
  t: number; // UNIX seconds
  equity: number;
}

export interface FFPairPnl {
  net_pnl: number;
  trades: number;
  wins: number;
}

export interface FFSimulation {
  id: string;
  exchange: string;
  label: string | null;
  status: FFStatus;
  start_time: string | null;
  end_time: string | null;
  speed: number;
  zscore_window: number;
  entry_threshold: number;
  exit_threshold: number;
  stop_threshold: number;
  usd_per_trade: number;
  max_active_pairs: number | null;
  slippage_pct: number;
  taker_fee_pct: number;
  funding_freq_h: number;
  pairs_count: number;
  total_ticks: number;
  processed_ticks: number;
  progress: number; // 0..1
  starting_capital: number;
  final_capital: number | null;
  realised_pnl: number | null;
  total_trades: number;
  equity_curve: FFEquityPoint[] | null;
  per_pair_pnl: Record<string, FFPairPnl> | null;
  exit_reasons: Record<string, number> | null;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface CreateFFInput {
  label?: string;
  start_time?: string; // ISO; optional offline (defaults to demo window)
  end_time?: string;
  speed?: number;
  starting_capital: number;
  zscore_window?: number;
  entry_threshold?: number;
  exit_threshold?: number;
  stop_threshold?: number;
  usd_per_trade?: number;
}

/** Create + launch a fast-forward replay (runs in the background). */
export function createFFSim(input: CreateFFInput): Promise<FFSimulation> {
  return proxyPost<FFSimulation>("api/ff/simulations", input);
}

/** List all fast-forward runs (newest first). */
export function listFFSims(): Promise<{ simulations: FFSimulation[]; count: number }> {
  return proxyGet("api/ff/simulations");
}

/** One run with its saved aggregates. */
export function getFFSim(id: string): Promise<FFSimulation> {
  return proxyGet<FFSimulation>(`api/ff/simulations/${encodeURIComponent(id)}`);
}

/** Cancel a running replay (partial aggregates are saved). */
export function stopFFSim(id: string): Promise<FFSimulation> {
  return proxyPost(`api/ff/simulations/${encodeURIComponent(id)}/stop`);
}

// ── Walk-Forward Backtest (Phase 8, PRD F8) ──────────────────────────────────

async function proxyPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const msg =
      typeof detail?.detail === "string" ? detail.detail : `API ${path} failed: ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

async function proxyDelete<T>(path: string): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const msg =
      typeof detail?.detail === "string" ? detail.detail : `API ${path} failed: ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export type BacktestStatus =
  | "PENDING"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "STOPPED"
  | "FAILED";

export interface BacktestEquityPoint {
  t: number;
  equity: number;
}

export interface BacktestPairPnl {
  net_pnl: number;
  trades: number;
  wins: number;
}

export interface BacktestWindow {
  index: number;
  scan_start: string;
  scan_end: string;
  trade_start: string;
  trade_end: string;
  pairs: number;
  trades: number;
  net_pnl: number;
}

export interface Strategy {
  id: string;
  exchange: string;
  name: string;
  description: string | null;
  status: BacktestStatus;
  scan_window_days: number;
  trade_window_days: number;
  zscore_window: number;
  entry_threshold: number;
  exit_threshold: number;
  stop_threshold: number;
  pvalue_max: number;
  max_half_life_h: number;
  start_time: string | null;
  end_time: string | null;
  starting_capital: number;
  usd_per_trade: number;
  max_active_pairs: number | null;
  slippage_pct: number;
  taker_fee_pct: number;
  funding_freq_h: number;
  total_windows: number;
  processed_windows: number;
  progress: number;
  current_capital: number | null;
  final_capital: number | null;
  net_pnl: number | null;
  total_trades: number;
  win_rate: number | null;
  rank: number | null;
  equity_curve: BacktestEquityPoint[] | null;
  per_window: BacktestWindow[] | null;
  per_pair_pnl: Record<string, BacktestPairPnl> | null;
  exit_reasons: Record<string, number> | null;
  report_md: string | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface CreateStrategyInput {
  name: string;
  description?: string;
  scan_window_days?: number;
  trade_window_days?: number;
  zscore_window?: number;
  entry_threshold?: number;
  exit_threshold?: number;
  stop_threshold?: number;
  start_time?: string;
  end_time?: string;
  starting_capital?: number;
}

/** List strategies, ranked by net P&L (best first). */
export function listStrategies(): Promise<{ strategies: Strategy[]; count: number }> {
  return proxyGet("api/backtest/strategies");
}

/** One strategy + its latest backtest result. */
export function getStrategy(id: string): Promise<Strategy> {
  return proxyGet<Strategy>(`api/backtest/strategies/${encodeURIComponent(id)}`);
}

/** Create a strategy (CRUD). */
export function createStrategy(input: CreateStrategyInput): Promise<Strategy> {
  return proxyPost<Strategy>("api/backtest/strategies", input);
}

/** Edit a strategy's parameters (CRUD). */
export function updateStrategy(id: string, input: Partial<CreateStrategyInput>): Promise<Strategy> {
  return proxyPut<Strategy>(`api/backtest/strategies/${encodeURIComponent(id)}`, input);
}

/** Delete a strategy (re-ranks the rest). */
export function deleteStrategy(id: string): Promise<{ deleted: string }> {
  return proxyDelete(`api/backtest/strategies/${encodeURIComponent(id)}`);
}

/** Run (or resume) the walk-forward sweep (runs in the background). */
export function runStrategy(id: string): Promise<Strategy> {
  return proxyPost<Strategy>(`api/backtest/strategies/${encodeURIComponent(id)}/run`);
}

/** Pause a running sweep (resumable). */
export function pauseStrategy(id: string): Promise<Strategy> {
  return proxyPost<Strategy>(`api/backtest/strategies/${encodeURIComponent(id)}/pause`);
}

/** Stop a running sweep (terminal; partial results saved). */
export function stopStrategy(id: string): Promise<Strategy> {
  return proxyPost<Strategy>(`api/backtest/strategies/${encodeURIComponent(id)}/stop`);
}

/** Seed the S1–S4 baseline strategies. */
export function seedDefaultStrategies(): Promise<{ created: Strategy[]; count: number }> {
  return proxyPost("api/backtest/seed-defaults");
}
