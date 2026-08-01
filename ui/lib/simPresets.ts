import type { CreateSimInput, Strategy } from "@/lib/api";

/**
 * The Phase-5 rehearsal parameterisation (docs/QA.md 2026-08-01, docs/PHASE5_PAPER_TRADING_PLAN.md §3.1).
 *
 * This is the *least-bad executable* configuration, not a recommendation to expect
 * profit: measured at +$0.248/trade with 5 of 12 out-of-sample months negative,
 * which sits inside the ±$212 noise floor. Its distinguishing feature is
 * `max_active_pairs: 5` — the uncapped result needs 20–100 simultaneous positions,
 * which no one can execute by hand, and capping it to human scale is what makes the
 * rehearsal honest rather than aspirational.
 */
export const PHASE5_REHEARSAL: CreateSimInput = {
  label: "phase5-rehearsal-e40-k5",
  starting_capital: 2000,
  interval_seconds: 300,
  zscore_window: 21,
  entry_threshold: 4.0,
  exit_threshold: 0.5,
  stop_threshold: 5.0,
  usd_per_trade: 100,
  max_active_pairs: 5,
  taker_fee_pct: 0.045,
  slippage_pct: 0.0316,
  funding_freq_h: 1,
  pvalue_max: 0.01,
  max_half_life_h: 72,
};

/** Prefill a session from a saved strategy, so a paper run mirrors what was backtested. */
export function presetFromStrategy(s: Strategy): CreateSimInput {
  return {
    label: `sim · ${s.name}`.slice(0, 120),
    // The backtest's capital sizes a 100-slot walk-forward; a hand-executable paper
    // run holds far fewer, so carry the per-leg size and let capital follow the cap.
    starting_capital: Math.max(1000, (s.usd_per_trade ?? 100) * 20),
    interval_seconds: 300,
    zscore_window: s.zscore_window,
    entry_threshold: s.entry_threshold,
    exit_threshold: s.exit_threshold,
    stop_threshold: s.stop_threshold,
    usd_per_trade: s.usd_per_trade,
    max_active_pairs: 5,
    taker_fee_pct: s.taker_fee_pct,
    slippage_pct: s.slippage_pct,
    pvalue_max: s.pvalue_max,
    max_half_life_h: s.max_half_life_h,
    source_strategy_id: s.id,
  };
}

/** Session statuses that mean "this strategy is being paper-traded right now". */
const LIVE_STATUSES = new Set(["RUNNING", "PAUSED"]);

/**
 * Map strategy id → the live sim session paper-trading it.
 *
 * Drives the dashboard highlight: the operator asked to see, at a glance, which
 * saved strategy is the one currently running in simulation.
 */
export function liveSimByStrategy<T extends { source_strategy_id: string | null; status: string }>(
  sessions: T[],
): Map<string, T> {
  const out = new Map<string, T>();
  for (const s of sessions) {
    if (!s.source_strategy_id || !LIVE_STATUSES.has(s.status)) continue;
    // A strategy could have been simulated more than once; the first match wins
    // because the list arrives newest-first.
    if (!out.has(s.source_strategy_id)) out.set(s.source_strategy_id, s);
  }
  return out;
}

/** sessionStorage key used to hand a prefilled session across the Backtest → Simulation
 *  navigation. sessionStorage rather than a query string: the payload is a dozen
 *  numeric params, and a URL carrying them is both ugly and easy to half-edit. */
export const SIM_PRESET_KEY = "statsarb.simPreset";

export function stashSimPreset(input: CreateSimInput): void {
  try {
    sessionStorage.setItem(SIM_PRESET_KEY, JSON.stringify(input));
  } catch {
    // Private mode / storage disabled — the form just opens with its defaults.
  }
}

/** Read and CLEAR the stashed preset, so a later visit doesn't resurrect it. */
export function takeSimPreset(): CreateSimInput | null {
  try {
    const raw = sessionStorage.getItem(SIM_PRESET_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(SIM_PRESET_KEY);
    return JSON.parse(raw) as CreateSimInput;
  } catch {
    return null;
  }
}
