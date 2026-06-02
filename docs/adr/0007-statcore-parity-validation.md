# 7. Validate the statistical core for numeric parity against the reference, in legacy mode

- **Status:** Accepted
- **Date:** 2026-06-02

## Context

Phase 1 builds `statcore/` — the pure statistical engine that every consumer
(scan, live, simulation, fast-forward, backtest) shares. Its correctness gate
(PLAN Phase 1) is *numeric parity against the reference data* (`2_cointegrated_pairs.csv`,
`3_backtest_file.csv`) produced by the ground-truth bot.

There is a tension: Option-B change #1 makes the production spread
`S1 − β·S2 − α`, but the reference CSVs were generated with the legacy
no-intercept form `S1 − β·S2` and a hedge ratio **rounded to 2 dp** (β = 1.29 for
the MATIC/STX pair). Comparing the production (intercept-on) spread to those CSVs
would not match — not because the math is wrong, but because the formula changed.

Additionally, `Old Reference Resources/` is gitignored, so tests cannot depend on
it being present.

## Decision

1. **Parity is validated in legacy mode.** `fit_hedge_ratio(..., include_intercept=False)`
   and `compute_spread(..., intercept=0.0)` reproduce the reference exactly. The
   parity tests drive the primitives (Engle-Granger, OLS hedge ratio, spread,
   rolling Z-score, half-life, zero-crossings) with the *same inputs the reference
   used* (no intercept, β rounded to 1.29) and assert a match to ~1e-9. This
   isolates "is the math correct?" from "did we change the formula?".
2. **Option-B is asserted separately.** Distinct tests prove the intercept is
   included by default, the stop-loss / time-stop / exit-threshold / half-life-cap
   behave as specified — i.e. the four changes are present *on top of* a
   provably-correct core.
3. **The reference CSVs are committed as test fixtures** under
   `backend/tests/fixtures/` (~11 KB each) so parity tests are hermetic and run in
   CI without the gitignored reference tree.

The Engle-Granger p-value / t-stat / critical value are intercept-independent
(`statsmodels.coint` runs its own internal regression), so they match the
reference directly regardless of Option-B #1.

## Consequences

- The highest-risk code is pinned to ground truth to machine precision before any
  consumer depends on it, while the Option-B deviations remain explicit and tested.
- The `include_intercept` flag is retained on `fit_hedge_ratio` (production
  default `True`) — small surface area, but it is the seam that makes parity
  testing possible and could aid future A/B comparison.
- If the pinned `statsmodels`/`numpy` versions change numerics, parity tests are
  the early-warning signal.
