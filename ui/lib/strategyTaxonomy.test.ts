import { describe, expect, it } from "vitest";
import type { Strategy } from "@/lib/api";
import {
  BASELINE_REFERENCE,
  DSR_SIGNIFICANT,
  NO_FILTERS,
  autoDescription,
  classify,
  classifyCost,
  classifyFamily,
  classifySpan,
  dsrLevel,
  filterMissReason,
  filtersActive,
  groupByFamily,
  matchesFilters,
  median,
  phaseMatches,
  phaseOf,
  sortGroups,
  sortStrategies,
  type ActiveFilters,
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
    phase: 1,
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

describe("sortStrategies", () => {
  const rows = [
    strategy({ id: "b", name: "entry-sweep-3.75", net_pnl: 1916, created_at: "2026-07-02" }),
    strategy({ id: "a", name: "entry-sweep-4.0", net_pnl: 1020, created_at: "2026-07-03" }),
    strategy({ id: "c", name: "entry-sweep-3.5", net_pnl: 2307, created_at: "2026-07-01" }),
    strategy({ id: "d", name: "entry-sweep-1.5", net_pnl: null, created_at: "2026-07-04" }),
  ];

  it("ranks by net P&L, nulls last", () => {
    expect(sortStrategies(rows, "pnl").map((s) => s.id)).toEqual(["c", "b", "a", "d"]);
  });

  it("orders by name numerically so a sweep reads as its curve", () => {
    // 3.5 < 3.75 < 4.0 — a plain string sort would put "3.75" before "3.5".
    expect(sortStrategies(rows, "default").map((s) => s.name)).toEqual([
      "entry-sweep-1.5",
      "entry-sweep-3.5",
      "entry-sweep-3.75",
      "entry-sweep-4.0",
    ]);
  });

  it("orders by newest first", () => {
    expect(sortStrategies(rows, "newest").map((s) => s.id)).toEqual(["d", "a", "b", "c"]);
  });

  it("does not mutate its input", () => {
    const before = rows.map((s) => s.id);
    sortStrategies(rows, "pnl");
    expect(rows.map((s) => s.id)).toEqual(before);
  });
});

// The bug this guards: picking a sort in the default grouped view moved rows only
// WITHIN each group, so the groups stayed put, the header medians stayed put, and
// with the groups collapsed nothing on screen changed at all — indistinguishable
// from a broken control.
describe("sortGroups", () => {
  const groups = groupByFamily([
    strategy({ name: "reval-3.5-s3", ...S3, net_pnl: -1313, created_at: "2026-07-01" }),
    strategy({ name: "entry-sweep-3.5", entry_threshold: 3.5, net_pnl: 2307, created_at: "2026-07-05" }),
    strategy({ name: "entry-sweep-2.5", entry_threshold: 2.5, net_pnl: -5640, created_at: "2026-07-04" }),
    strategy({ name: "hl-24-s3", ...S3, net_pnl: -1348, created_at: "2026-07-09" }),
  ]);

  it("reorders the groups themselves when ranking by net P&L", () => {
    // Entry sweep's median (-1666.5) sits below revalidation's (-1313), so the
    // order must actually change rather than staying in FAMILY_ORDER.
    const order = sortGroups(groups, "pnl").map((g) => g.family);
    expect(order).toEqual(["revalidation", "half-life", "entry-sweep"]);
  });

  it("ranks groups by MEDIAN, not by their best member", () => {
    // Entry sweep holds the single best row in the set (+$2,307). Ranking by best
    // would float it to the top and rebuild the leaderboard; by median it sinks.
    expect(sortGroups(groups, "pnl")[0].family).not.toBe("entry-sweep");
  });

  it("orders groups by their newest member", () => {
    expect(sortGroups(groups, "newest").map((g) => g.family)).toEqual([
      "half-life",
      "entry-sweep",
      "revalidation",
    ]);
  });

  it("orders groups alphabetically by label", () => {
    expect(sortGroups(groups, "name").map((g) => g.label)).toEqual([
      "Entry |Z| sweep",
      "Half-life sweep",
      "Multi-span re-validation",
    ]);
  });

  it("leaves the deliberate FAMILY_ORDER alone on 'default'", () => {
    expect(sortGroups(groups, "default").map((g) => g.family)).toEqual(
      groups.map((g) => g.family),
    );
  });

  it("sinks groups with nothing scored yet", () => {
    const withUnrun = groupByFamily([
      strategy({ name: "stop-6.0-s3", ...S3, net_pnl: -1291 }),
      strategy({ name: "pval-sweep-0.05", pvalue_max: 0.05, net_pnl: null }),
    ]);
    expect(sortGroups(withUnrun, "pnl").map((g) => g.family)).toEqual([
      "z-stop",
      "pvalue-sweep",
    ]);
  });
});

describe("dsrLevel — corrected-significance bucketing (Slice 4, gate B3)", () => {
  it("is 'unknown' when the DSR is missing or NaN", () => {
    expect(dsrLevel(null)).toBe("unknown");
    expect(dsrLevel(undefined)).toBe("unknown");
    expect(dsrLevel(NaN)).toBe("unknown");
  });

  it("is 'significant' only at or above the 0.95 threshold", () => {
    expect(dsrLevel(DSR_SIGNIFICANT)).toBe("significant");
    expect(dsrLevel(0.99)).toBe("significant");
    expect(dsrLevel(0.9499)).toBe("insignificant");
    expect(dsrLevel(0.5)).toBe("insignificant");
    expect(dsrLevel(0)).toBe("insignificant");
  });
});

describe("phase provenance (Slice 6)", () => {
  it("phaseOf defaults a missing phase to 1", () => {
    expect(phaseOf(strategy())).toBe(1);
    expect(phaseOf(strategy({ phase: 2 }))).toBe(2);
    expect(phaseOf(strategy({ phase: undefined }))).toBe(1);
  });

  it("phaseMatches: 'all' keeps everything (Phase 1 is never hidden)", () => {
    expect(phaseMatches(strategy({ phase: 1 }), "all")).toBe(true);
    expect(phaseMatches(strategy({ phase: 2 }), "all")).toBe(true);
  });

  it("phaseMatches: phase1 / phase2 partition the list", () => {
    expect(phaseMatches(strategy({ phase: 1 }), "phase1")).toBe(true);
    expect(phaseMatches(strategy({ phase: 2 }), "phase1")).toBe(false);
    expect(phaseMatches(strategy({ phase: 2 }), "phase2")).toBe(true);
    expect(phaseMatches(strategy({ phase: 1 }), "phase2")).toBe(false);
  });
});

// ── Filters + empty-state diagnosis (Phase-4 Task A) ────────────────────────
// The list and its empty state must agree by construction: `matchesFilters` is
// the single predicate both use, and `filterMissReason` explains a 0-row result
// instead of dead-ending. Motivated by the 2026-07-29 report of "0/75 — No
// strategy matches these filters" with the Phase dropdown on "Phase 2".

const filters = (over: Partial<ActiveFilters> = {}): ActiveFilters => ({
  ...NO_FILTERS,
  ...over,
});

/** Classified rows in the shape the list holds them. */
function rows(...list: Strategy[]) {
  return list.map((s) => ({ s, c: classify(s) }));
}

/** A realistic-cost, out-of-sample row (span s2). */
const oosRow = (over: Partial<Strategy> = {}) => strategy({ ...S2, ...over });

describe("matchesFilters", () => {
  it("keeps every row at the defaults — nothing is hidden out of the box", () => {
    const all = rows(strategy({ phase: 1 }), oosRow({ phase: 2 }));
    expect(all.every(({ s, c }) => matchesFilters(s, c, NO_FILTERS))).toBe(true);
  });

  it("partitions on phase", () => {
    const p1 = rows(strategy({ phase: 1 }))[0];
    const p2 = rows(strategy({ phase: 2 }))[0];
    expect(matchesFilters(p1.s, p1.c, filters({ phaseFilter: "phase1" }))).toBe(true);
    expect(matchesFilters(p2.s, p2.c, filters({ phaseFilter: "phase1" }))).toBe(false);
    expect(matchesFilters(p2.s, p2.c, filters({ phaseFilter: "phase2" }))).toBe(true);
  });

  it("drops zero-cost counterfactuals under 'Tradeable only'", () => {
    const zeroCost = rows(strategy({ taker_fee_pct: 0, slippage_pct: 0 }))[0];
    expect(matchesFilters(zeroCost.s, zeroCost.c, filters({ costFilter: "tradeable" }))).toBe(
      false,
    );
    expect(matchesFilters(zeroCost.s, zeroCost.c, filters({ costFilter: "diagnostic" }))).toBe(
      true,
    );
  });

  it("drops the in-sample window under the out-of-sample span filter", () => {
    const inSample = rows(strategy())[0];
    const oos = rows(oosRow())[0];
    expect(matchesFilters(inSample.s, inSample.c, filters({ spanFilter: "oos" }))).toBe(false);
    expect(matchesFilters(oos.s, oos.c, filters({ spanFilter: "oos" }))).toBe(true);
  });
});

describe("filtersActive", () => {
  it("is false at the defaults and true for any single change", () => {
    expect(filtersActive(NO_FILTERS)).toBe(false);
    expect(filtersActive(filters({ phaseFilter: "phase2" }))).toBe(true);
    expect(filtersActive(filters({ realisticOnly: true }))).toBe(true);
    expect(filtersActive(filters({ spanFilter: "oos" }))).toBe(true);
    expect(filtersActive(filters({ costFilter: "diagnostic" }))).toBe(true);
    expect(filtersActive(filters({ family: "entry-sweep" }))).toBe(true);
  });
});

describe("filterMissReason", () => {
  it("names the Phase filter when every saved run is phase 1 (the 0/75 case)", () => {
    const all = rows(...Array.from({ length: 3 }, () => strategy({ phase: 1 })));
    const why = filterMissReason(all, filters({ phaseFilter: "phase2" }));
    expect(why).toContain("Phase 2");
    expect(why).toContain("all 3 saved runs are Phase 1");
  });

  it("uses singular grammar for a single saved run", () => {
    // "none of the 1 saved run match it" is not English — n=1 gets its own clause.
    expect(filterMissReason(rows(strategy({ phase: 1 })), filters({ phaseFilter: "phase2" })))
      .toContain("the one saved run is Phase 1");
    expect(filterMissReason(rows(strategy()), filters({ costFilter: "diagnostic" })))
      .toContain("the one saved run does not match it");
    expect(filterMissReason(rows(strategy()), filters({ spanFilter: "oos" })))
      .toContain("the one saved run is not in that span");
    expect(filterMissReason(rows(strategy()), filters({ realisticOnly: true })))
      .toContain("the one saved run is not both");
  });

  it("negates correctly in the plural — 'none of the N ... are' never reads as a positive", () => {
    const two = rows(strategy(), strategy());
    expect(filterMissReason(two, filters({ spanFilter: "oos" }))).toContain(
      "none of the 2 saved runs are in that span",
    );
    expect(filterMissReason(two, filters({ realisticOnly: true }))).toContain(
      "none of the 2 saved runs are both tradeable-cost AND out-of-sample",
    );
    expect(filterMissReason(two, filters({ costFilter: "diagnostic" }))).toContain(
      "none of the 2 saved runs match it",
    );
  });

  it("names the Span filter when nothing is out-of-sample", () => {
    const why = filterMissReason(rows(strategy(), strategy()), filters({ spanFilter: "oos" }));
    expect(why).toContain("Span filter");
    expect(why).toContain("Out-of-sample");
  });

  it("names the Costs filter when every run is realistically costed", () => {
    const why = filterMissReason(rows(strategy()), filters({ costFilter: "diagnostic" }));
    expect(why).toContain("Costs filter");
    expect(why).toContain("Diagnostics only");
  });

  it("names 'Realistic runs only' when no row is both tradeable AND out-of-sample", () => {
    // The fixture is modelled-cost but IN-SAMPLE, so it fails `realistic`.
    const why = filterMissReason(rows(strategy()), filters({ realisticOnly: true }));
    expect(why).toContain("Realistic runs only");
  });

  it("returns null when no SINGLE filter explains the miss (a combination does)", () => {
    // Each filter alone keeps a row; only together do they exclude everything.
    const all = rows(
      strategy({ phase: 2 }), // phase-2 but in-sample
      oosRow({ phase: 1 }), // out-of-sample but phase-1
    );
    expect(filterMissReason(all, filters({ phaseFilter: "phase2", spanFilter: "oos" }))).toBeNull();
  });

  it("returns null when there are no saved runs at all", () => {
    expect(filterMissReason([], filters({ phaseFilter: "phase2" }))).toBeNull();
  });

  it("stays silent when the filters actually match something", () => {
    expect(filterMissReason(rows(strategy({ phase: 2 })), filters({ phaseFilter: "phase2" })))
      .toBeNull();
  });
});
