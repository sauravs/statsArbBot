# 2. Adopt the reference algorithm plus four research-backed changes ("Option B")

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The algorithmic ground truth is the pure-Python reference bot (`oldCodeRef_Main_Source`): Engle-Granger cointegration, OLS hedge ratio, OU half-life filter, rolling Z-score, `|Z|≥1.5` entry, zero-crossing exit. The prototype (`oldCodeRef_Prototype`) may contain formula errors and uses a loose 200h half-life cap with no wired stop-loss.

Independent quant research (`research.md`) identifies several improvements. We must decide how many to adopt now without changing the project's intent or risking incorrect implementation.

## Decision

Replicate the reference algorithm exactly, with **four** low-complexity, high-impact, well-evidenced changes — and **defer** the rest:

1. **Spread includes the intercept:** `spread = S1 − β·S2 − α` (was `S1 − β·S2`). *Evidence: research.md §2.*
2. **Hard stop-loss:** exit when `|Z| ≥ 4.0` **or** position age `> 3 × half_life`. *Evidence: research.md §6.*
3. **Exit threshold:** close at `|Z| < 0.5` instead of zero-crossing. *Evidence: research.md §5.*
4. **Half-life cap:** tighten from 200h to **72h**. *Evidence: research.md §4.*

**Deferred (later phase):** Johansen & KSS tests, HMM/volatility regime filter, Kalman dynamic hedge ratio, log-prices, Z-proportional position sizing.

## Consequences

- Materially better risk control (stop-loss) and signal quality (intercept) with minimal code and low implementation risk.
- Phase 1 validates the engine against reference data within tolerance, accounting for these deliberate deltas.
- Deferred methods remain documented in `research.md` for a future phase; the engine stays simple and verifiable now.
