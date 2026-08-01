import { describe, expect, it } from "vitest";
import { PHASE5_REHEARSAL, liveSimByStrategy, presetFromStrategy } from "./simPresets";
import type { Strategy } from "./api";

function session(over: Partial<{ source_strategy_id: string | null; status: string; label: string | null }>) {
  return {
    source_strategy_id: null,
    status: "RUNNING",
    label: null,
    ...over,
  };
}

describe("PHASE5_REHEARSAL", () => {
  it("caps concurrency, which is the whole point of the recommendation", () => {
    // The uncapped result needs 20-100 simultaneous positions and is not
    // hand-executable; a preset without this cap would quietly restore that.
    expect(PHASE5_REHEARSAL.max_active_pairs).toBe(5);
  });

  it("uses the only per-leg size measured at an executable workload", () => {
    expect(PHASE5_REHEARSAL.usd_per_trade).toBe(100);
  });

  it("demands tighter pair quality than the live scan does", () => {
    // The scan admits everything under the global PVALUE_MAX (0.05); loosening
    // 0.01 -> 0.05 flipped +$1,865 to -$1,176 in the phase-1 sweep.
    expect(PHASE5_REHEARSAL.pvalue_max).toBe(0.01);
  });

  it("carries capital that can actually hold the capped positions", () => {
    const needed = (PHASE5_REHEARSAL.max_active_pairs ?? 0) * (PHASE5_REHEARSAL.usd_per_trade ?? 0);
    expect(PHASE5_REHEARSAL.starting_capital).toBeGreaterThan(needed);
  });
});

describe("presetFromStrategy", () => {
  const strategy = {
    id: "st_1",
    name: "entry-4.0 · s2",
    zscore_window: 21,
    entry_threshold: 4,
    exit_threshold: 0.5,
    stop_threshold: 5,
    usd_per_trade: 1000,
    taker_fee_pct: 0.045,
    slippage_pct: 0.0316,
    pvalue_max: 0.01,
    max_half_life_h: 72,
  } as unknown as Strategy;

  it("mirrors the strategy's signal parameters", () => {
    const p = presetFromStrategy(strategy);
    expect(p.entry_threshold).toBe(4);
    expect(p.exit_threshold).toBe(0.5);
    expect(p.stop_threshold).toBe(5);
    expect(p.pvalue_max).toBe(0.01);
  });

  it("links the session back to the strategy", () => {
    expect(presetFromStrategy(strategy).source_strategy_id).toBe("st_1");
  });

  it("caps concurrency even when the backtest ran 100 slots", () => {
    expect(presetFromStrategy(strategy).max_active_pairs).toBe(5);
  });

  it("sizes capital from the per-leg size, not the backtest's slot capital", () => {
    // The backtest used $100k to hold 100 slots; a hand-run paper session holds 5.
    expect(presetFromStrategy(strategy).starting_capital).toBe(20000);
  });
});

describe("liveSimByStrategy", () => {
  it("maps a running session to its strategy", () => {
    const m = liveSimByStrategy([session({ source_strategy_id: "a", label: "run" })]);
    expect(m.get("a")?.label).toBe("run");
  });

  it("includes PAUSED sessions — a paused run is still the picked strategy", () => {
    const m = liveSimByStrategy([session({ source_strategy_id: "a", status: "PAUSED" })]);
    expect(m.has("a")).toBe(true);
  });

  it("ignores STOPPED sessions", () => {
    const m = liveSimByStrategy([session({ source_strategy_id: "a", status: "STOPPED" })]);
    expect(m.has("a")).toBe(false);
  });

  it("ignores sessions not linked to a strategy", () => {
    expect(liveSimByStrategy([session({})]).size).toBe(0);
  });

  it("keeps the newest session when a strategy was simulated more than once", () => {
    const m = liveSimByStrategy([
      session({ source_strategy_id: "a", label: "newer" }),
      session({ source_strategy_id: "a", label: "older" }),
    ]);
    expect(m.get("a")?.label).toBe("newer");
  });
});
