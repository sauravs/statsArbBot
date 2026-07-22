import { describe, expect, it } from "vitest";
import type { Strategy } from "@/lib/api";
import {
  BASELINE_REFERENCE,
  autoDescription,
  classify,
  classifyCost,
  classifyFamily,
  classifySpan,
  groupByFamily,
  median,
} from "@/lib/strategyTaxonomy";

// Fixtures mirror real rows from the production database (69 hyperliquid
// strategies as of 2026-07-22), so a regression here is a regression against the
// data the operator actually looks at.

function strategy(over: Partial<Strategy> = {}): Strategy {
  return {
    id: "id",
    exchange: "hyperliquid",
    data_source: "hyperliquid",
    name: "Untitled strategy",
    description: null,
    status: "COMPLETED",
    scan_window_days: BASELINE_REFERENCE.scan_window_days,
    trade_window_days: BASELINE_REFERENCE.trade_window_days,
    zscore_window: BASELINE_REFERENCE.zscore_window,
    entry_threshold: BASELINE_REFERENCE.entry_threshold,
    exit_threshold: BASELINE_REFERENCE.exit_threshold,
    stop_threshold: BASELINE_REFERENCE.stop_threshold,
    pvalue_max: BASELINE_REFERENCE.pvalue_max,
    max_half_life_h: BASELINE_REFERENCE.max_half_life_h,
    start_time: "2026-03-01T16:09:00.000Z",
    end_time: "2026-06-23T16:10:00.000Z",
    starting_capital: 10000,
    usd_per_trade: 100,
    max_active_pairs: null,
    slippage_pct: 0.05,
    taker_fee_pct: 0.05,
    funding_freq_h: 8,
    total_windows: 15,
    processed_windows: 15,
    progress: 1,
    current_capital: null,
    final_capital: 11865,
    net_pnl: 1865,
    total_trades: 100,
    win_rate: 0.6,
    rank: 1,
    equity_curve: null,
    per_window: null,
    per_pair_pnl: null,
    exit_reasons: null,
    report_md: null,
    error: null,
    created_at: null,
    updated_at: null,
    completed_at: null,
    ...over,
  };
}

const S2 = { start_time: "2025-11-07T00:00:00.000Z", end_time: "2026-03-01T00:00:00.000Z" };
const S3 = { start_time: "2025-07-16T00:00:00.000Z", end_time: "2025-11-07T00:00:00.000Z" };
const S4 = { start_time: "2025-03-24T00:00:00.000Z", end_time: "2025-07-16T00:00:00.000Z" };

describe("classifyCost", () => {
  it("flags a zero-cost counterfactual", () => {
    // cost-000-s2 — the row that reads +$1,181 and cannot be traded.
    expect(classifyCost(strategy({ taker_fee_pct: 0, slippage_pct: 0 }))).toBe("ZERO_COST");
  });

  it("flags a reduced-cost run", () => {
    // cost-002-s3 sits between free and realistic — still untradeable.
    expect(classifyCost(strategy({ taker_fee_pct: 0.02, slippage_pct: 0.02 }))).toBe(
      "REDUCED_COST",
    );
  });

  it("flags a run with only ONE side discounted", () => {
    expect(classifyCost(strategy({ taker_fee_pct: 0.05, slippage_pct: 0 }))).toBe(
      "REDUCED_COST",
    );
  });

  it("accepts modelled costs, and anything above them", () => {
    expect(classifyCost(strategy())).toBe("MODELLED_COST");
    expect(classifyCost(strategy({ taker_fee_pct: 0.1, slippage_pct: 0.1 }))).toBe(
      "MODELLED_COST",
    );
  });
});

describe("classifySpan", () => {
  it("calls the designated baseline window in-sample", () => {
    expect(classifySpan(strategy())).toEqual({ label: "IN_SAMPLE", spanName: "s1" });
  });

  it("names the re-validation spans and calls them out-of-sample", () => {
    expect(classifySpan(strategy(S2))).toEqual({ label: "OUT_OF_SAMPLE", spanName: "s2" });
    expect(classifySpan(strategy(S3))).toEqual({ label: "OUT_OF_SAMPLE", spanName: "s3" });
    expect(classifySpan(strategy(S4))).toEqual({ label: "OUT_OF_SAMPLE", spanName: "s4" });
  });

  // The whole point of the three-way split: a binary rule would stamp these
  // OUT-OF-SAMPLE and launder in-sample runs as validation.
  it("does NOT call a near-copy of the in-sample window out-of-sample", () => {
    // "Test A" / "Follow up" — 2026-03-01 → 06-15, almost entirely inside s1.
    const near = strategy({
      name: "Test A",
      start_time: "2026-03-01T00:00:00.000Z",
      end_time: "2026-06-15T00:00:00.000Z",
    });
    expect(classifySpan(near).label).toBe("IN_SAMPLE");
  });

  it("marks a partial overlap as OVERLAPS_IN_SAMPLE", () => {
    // "6 months same data" — 2026-01-01 → 06-15: half of it precedes the window.
    const straddle = strategy({
      start_time: "2026-01-01T00:00:00.000Z",
      end_time: "2026-06-15T00:00:00.000Z",
    });
    expect(classifySpan(straddle).label).toBe("OVERLAPS_IN_SAMPLE");
  });

  it("handles a missing span", () => {
    expect(classifySpan(strategy({ start_time: null, end_time: null }))).toEqual({
      label: "NO_SPAN",
      spanName: null,
    });
  });
});

describe("classifyFamily", () => {
  const cases: [string, Partial<Strategy>, string][] = [
    ["entry-sweep-3.5", { entry_threshold: 3.5 }, "entry-sweep"],
    ["sweep-exit-0.1", { exit_threshold: 0.1 }, "exit-sweep"],
    ["sweep2-exit-0.05", { exit_threshold: 0.05 }, "exit-sweep"],
    ["pval-sweep-0.10", { pvalue_max: 0.1 }, "pvalue-sweep"],
    ["reval-3.5-s2", S2, "revalidation"],
    ["reval-3.0-s4", S4, "revalidation"],
    ["hl-24-s3", S3, "half-life"],
    ["stop-6.0-s3", S3, "z-stop"],
    ["cost-000-s4", { ...S4, taker_fee_pct: 0, slippage_pct: 0 }, "cost-decomposition"],
    ["cost-002-s3", { ...S3, taker_fee_pct: 0.02, slippage_pct: 0.02 }, "cost-decomposition"],
    ["cost000-e30-s2", { ...S2, taker_fee_pct: 0, slippage_pct: 0 }, "cost-decomposition"],
    ["Scan 21, Trade 7", {}, "window-sweep"],
    ["Scan 30, Trade 15", {}, "window-sweep"],
    ["S1 — Baseline", { start_time: null, end_time: null }, "seed-defaults"],
  ];

  it.each(cases)("classifies %s", (name, over, expected) => {
    const s = strategy({ name, ...over });
    expect(classifyFamily(s, classifySpan(s).label)).toBe(expected);
  });

  it("recognises the baseline by CONFIG, not by name", () => {
    // The rank-#1 row is literally called "Untitled strategy".
    expect(classifyFamily(strategy(), "IN_SAMPLE")).toBe("baseline");
  });

  it("keeps a deliberately-named sweep member in its own family even when its config equals the baseline", () => {
    // entry-sweep-3.0 and sweep-exit-0.5 ARE the baseline config, saved under a
    // sweep name. Their family should follow the experiment they belong to.
    expect(classifyFamily(strategy({ name: "entry-sweep-3.0" }), "IN_SAMPLE")).toBe(
      "entry-sweep",
    );
    expect(classifyFamily(strategy({ name: "sweep-exit-0.5" }), "IN_SAMPLE")).toBe(
      "exit-sweep",
    );
  });

  it("does NOT file the other 23 'Untitled strategy' rows under Baseline", () => {
    // Same default name, different config/span — these are ad-hoc, not the baseline.
    const other = strategy({ ...S3, entry_threshold: 3.0, max_half_life_h: 108 });
    expect(classifyFamily(other, classifySpan(other).label)).toBe("ad-hoc");
  });

  it("classifies an unmatched name gracefully", () => {
    const s = strategy({ name: "sauravs_demo_test_2", entry_threshold: 1.5 });
    expect(classifyFamily(s, classifySpan(s).label)).toBe("ad-hoc");
  });
});

describe("classify — safety flags", () => {
  it("marks an out-of-sample run at modelled cost as the only realistic kind", () => {
    const s = classify(strategy({ name: "reval-3.5-s2", entry_threshold: 3.5, ...S2 }));
    expect(s.safety).toMatchObject({
      cost: "MODELLED_COST",
      span: "OUT_OF_SAMPLE",
      tradeable: true,
      realistic: true,
    });
  });

  it("denies 'realistic' to an in-sample run even at full cost", () => {
    expect(classify(strategy()).safety).toMatchObject({ tradeable: true, realistic: false });
  });

  it("denies both to a zero-cost counterfactual, however good its span", () => {
    const s = classify(
      strategy({ name: "cost-000-s2", ...S2, taker_fee_pct: 0, slippage_pct: 0 }),
    );
    expect(s.safety).toMatchObject({ tradeable: false, realistic: false });
  });
});

describe("autoDescription", () => {
  it("reports no changes for the baseline itself", () => {
    const text = autoDescription(strategy(), "IN_SAMPLE");
    expect(text).toContain("Baseline parameters, unchanged.");
    expect(text).toContain("the in-sample window every sweep was tuned on");
  });

  it("names each changed parameter with its baseline value", () => {
    const s = strategy({ name: "entry-sweep-3.5", entry_threshold: 3.5 });
    const text = autoDescription(s, "IN_SAMPLE");
    expect(text).toContain("entry |Z| 3.5 (baseline 3)");
  });

  it("describes zeroed costs as a single clause", () => {
    const s = strategy({ taker_fee_pct: 0, slippage_pct: 0, ...S2 });
    expect(autoDescription(s, "OUT_OF_SAMPLE")).toContain("fees and slippage set to 0");
  });

  it("describes reduced costs with the actual values", () => {
    const s = strategy({ taker_fee_pct: 0.02, slippage_pct: 0.02, ...S3 });
    expect(autoDescription(s, "OUT_OF_SAMPLE")).toContain(
      "costs reduced to 0.02% fee + 0.02% slippage",
    );
  });

  it("warns when the span merely overlaps the tuning window", () => {
    const s = strategy({ start_time: "2026-01-01T00:00:00.000Z" });
    expect(autoDescription(s, "OVERLAPS_IN_SAMPLE")).toContain("not a clean test");
  });

  it("always produces a description, even for an unrecognised run", () => {
    const s = strategy({ name: "???", entry_threshold: 1.5, start_time: null, end_time: null });
    expect(classify(s).autoDescription.length).toBeGreaterThan(0);
  });
});

describe("classify — description precedence", () => {
  it("prefers the operator's own description", () => {
    expect(classify(strategy({ description: "  my note  " })).description).toBe("my note");
  });

  it("falls back to the curated family text", () => {
    expect(classify(strategy({ name: "hl-24-s3", ...S3 })).description).toContain(
      "how slowly a pair is allowed to revert",
    );
  });
});

describe("median", () => {
  it("returns null for an empty set", () => {
    expect(median([])).toBeNull();
  });
  it("takes the middle of an odd-length set", () => {
    expect(median([3, 1, 2])).toBe(2);
  });
  it("averages the two middles of an even-length set", () => {
    expect(median([4, 1, 3, 2])).toBe(2.5);
  });
});

describe("groupByFamily", () => {
  const rows = [
    strategy({ id: "e1", name: "entry-sweep-2.5", entry_threshold: 2.5, net_pnl: -5640 }),
    strategy({ id: "e2", name: "entry-sweep-3.5", entry_threshold: 3.5, net_pnl: 2307 }),
    strategy({ id: "e3", name: "entry-sweep-4.0", entry_threshold: 4.0, net_pnl: 1020 }),
    strategy({ id: "e4", name: "entry-sweep-1.5", entry_threshold: 1.5, net_pnl: null }),
    strategy({ id: "r1", name: "reval-3.5-s2", ...S2, net_pnl: -170 }),
  ];

  it("buckets by family and keeps never-run rows in the count but out of the stats", () => {
    const entry = groupByFamily(rows).find((g) => g.family === "entry-sweep")!;
    expect(entry.strategies).toHaveLength(4);
    expect(entry.scored).toBe(3);
    expect(entry.medianNet).toBe(1020);
    expect(entry.bestNet).toBe(2307);
    expect(entry.worstNet).toBe(-5640);
  });

  it("orders re-validation ahead of the seductive families, not by P&L", () => {
    const order = groupByFamily([
      ...rows,
      strategy({ id: "c1", name: "cost-000-s2", ...S2, taker_fee_pct: 0, slippage_pct: 0 }),
    ]).map((g) => g.family);
    expect(order.indexOf("revalidation")).toBeLessThan(order.indexOf("entry-sweep"));
    expect(order.indexOf("entry-sweep")).toBeLessThan(order.indexOf("cost-decomposition"));
  });

  it("omits families with no members", () => {
    expect(groupByFamily(rows).map((g) => g.family)).not.toContain("z-stop");
  });
});
