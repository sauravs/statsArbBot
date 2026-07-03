# 12. Manual-trade entry re-validates cointegration on fresh data

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

Manual Trading lets an operator record a trade they take by hand off a bot
signal (`docs/USER_GUIDE.md` §7). Until now the only statistical gate on a manual
entry was **implicit and transitive**: a pair can only be recorded if it is in
the latest scan, and the scan (`backend/scan/orchestrator.py`) already filters
every pair through `statcore.analyze_pair` with `config.PVALUE_MAX` (0.05) and
`config.MAX_HALF_LIFE_H` (72h), persisting only survivors. The `record` endpoint
itself re-checked **nothing** — it recomputed the live Z-score but trusted the
scan's stored half-life and never looked at the p-value (which wasn't even
persisted on `ManualTrade`).

The request (issue #147) was to "add p-value and half-life as entry filters,
since they were most decisive in backtesting." Taken literally — re-apply the
same static 0.05/72h thresholds at record time — this is a **no-op**: every
recordable pair has already cleared exactly those thresholds at scan time.

The real gap is **staleness**. A scan is a point-in-time snapshot; cointegration
and half-life are unstable (regime shifts, structural breaks). A pair that passed
the scan hours or days ago may have **decayed** by the time the operator records.
This is precisely the failure the backtest guards against: there the p-value /
half-life filter is re-evaluated **every formation window**, always on data
current as of the decision — never once, globally.

## Decision

**Manual entry re-validates the pair's cointegration and half-life on fresh
candles at record time, and hard-blocks (HTTP 422) a pair that fails.**

1. **Fresh, like-for-like re-check.** `record_manual_trade` calls a new
   `marketdata.pair_series.current_pair_analysis`, which re-fetches both legs and
   re-runs the *same* `statcore.analyze_pair` the scan uses, at the scan's own
   page depth (`config.MANUAL_FILTER_PAGES`, defaulting to `NUM_HISTORICAL_PAGES`).
   This is the manual analog of the backtest's per-window re-evaluation. The
   fresh `p_value` and `half_life` are persisted on the trade (a new nullable
   `p_value` column; half-life now stores the fresh value, not the scan's).

2. **Operator-configurable thresholds.** `pvalue_max` / `max_half_life_h` are
   optional request fields (bounds mirror the backtest strategy form), defaulting
   to the live scan policy. Without them the re-check just mirrors the scan;
   with them an operator can *tighten* the gate (e.g. p≤0.02, ≤24h) for a
   higher-conviction entry.

3. **Hard block, not a warning.** A failing pair returns 422 with the computed
   values and thresholds in the detail. The pre-existing Z-score gate is UI-only
   and trivially bypassed by calling the endpoint directly; a server-side block
   is enforceable and auditable. The block also fires when fresh history is
   insufficient to re-validate at all — we reject rather than fall back to the
   stale scan values.

The **fast Z/entry-price snapshot is unchanged** (`current_pair_snapshot`, one
page, #54) and still uses the scan's stored β/α, so the recorded spread stays
self-consistent with what the operator saw. The heavier multi-page fetch is
incurred **only** for the filter.

## Consequences

- **Cost:** recording now does one extra ~`MANUAL_FILTER_PAGES`-page fetch, so a
  live record is a few seconds slower. Accepted: a safety gate on a real entry
  is worth seconds. Matching the scan's page depth (rather than full paginated
  history, the pre-#54 multi-minute path) keeps it cheap and comparable.
- **Persisted stats now reflect entry, not scan.** A recorded trade's
  `half_life`/`p_value` are the re-validated values at the moment of entry —
  strictly more truthful for later review.
- **Not redundant with the scan.** Because it runs on fresh data, it can reject a
  pair the scan admitted (drift) — the whole point.
- **Alternatives rejected:** (a) re-apply stored static thresholds — blocks
  nothing; (b) configurable gate on *stored* stats — catches discretionary
  tightening but not drift; (c) display + soft-warn — no enforcement, bypass
  remains. See issue #147 for the full comparison.

## Addendum (#150): two-layer model — scan-time triage → fresh gate

The #147 controls lived only inside the Record popup, so they were
undiscoverable and did nothing for **pair selection** (the real bottleneck with
30+ pairs). #150 adds **visible global p-value / half-life controls** at the top
of the Manual Trading section, making the model explicit **two layers**:

1. **Triage (advisory, scan-time).** The header control row narrows the pairs
   table using each pair's **stored** (scan-time) `p_value` / `half_life`, and
   **seeds** the Record popup's thresholds. This is selection help; it is
   deliberately labelled scan-time and can only *tighten* below the scan's
   0.05/72 (shown pairs already cleared that).
2. **Gate (authoritative, fresh).** Unchanged from #147 — recording re-runs
   `analyze_pair` on fresh candles and hard-blocks (422) on failure.

**Why keep them separate:** the triage filter must never masquerade as the
safety gate. Filtering on stale scan-time numbers is fine for *narrowing what you
look at*, but the *decision to allow an entry* must run on fresh data — otherwise
a decayed pair that still shows good scan-time stats would slip through. So
triage sets the bar and does selection; the fresh re-check enforces it. A pair
can pass the table filter yet be blocked at record — by design.
