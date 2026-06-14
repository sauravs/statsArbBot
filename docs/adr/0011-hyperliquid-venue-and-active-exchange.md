# 11. Hyperliquid as the second venue; active-exchange derived from the data source

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

dYdX v4 was the only integrated venue. This phase adds **Hyperliquid (HL)** as a
second venue, scoped to the **Manual Trading** and **Backtest** sections only.
LiveBot, Fast-Forward, Simulation, and live/testnet automated trading are out of
scope (a future phase). Research and the full slice log live in
`docs/HYPERLIQUID_{RESEARCH,PLAN,PROGRESS}.md`; this ADR records the load-bearing
decisions.

HL was chosen over Binance because it mirrors dYdX (perp DEX, EIP-712 wallet
signing, no KYC, no US geo-block), so the existing auth/UX model transfers and the
eventual real-money path avoids Binance's US restriction. The data layer was
already multi-exchange (`enum Exchange { dydx, binance, hyperliquid }`, the ADR-0004
exchange registry), so the work was integration, not re-architecture.

Two conflations surfaced during integration and had to be resolved:

1. **Source ↔ exchange.** `SCAN_DATA_SOURCE` (the global `fake` / `dydx` /
   `hyperliquid` toggle) is the single switch the whole app keys off, but the rows
   it writes (scan results, manual trades, backtest strategies) and the data it
   reads were stamped/defaulted to a static `DEFAULT_EXCHANGE` (`dydx`). Selecting
   HL therefore produced HL data mislabelled `dydx`, or UI reads that asked for
   `dydx` while the data was HL.
2. **Capability granularity.** A single `integrated` boolean gated data *and*
   simulation *and* live trading. HL needs data (for Backtest/Manual) without its
   sim/live paths being enabled this phase.

## Decision

1. **Venue-consistent, HL-native data.** Backtests read HL's own candles **and
   funding** (funding is venue-specific and dominates stat-arb P&L). HL's
   ~5,000-candle live-API cap is sufficient for the ~60–200-day backtests this
   phase needs; the S3 archive (multi-year history) is deferred. Binance is not
   integrated.

2. **`config.active_exchange()` derives the venue from the active source** —
   `dydx`/`hyperliquid` → themselves, `fake` → `DEFAULT_EXCHANGE`. The scan stamp,
   and the pairs / manual / backtest read+write defaults, resolve the exchange
   **at call time** via this helper instead of the static `DEFAULT_EXCHANGE`. The
   whole section then follows the selected venue with no per-call exchange wiring
   in the UI. Backward-compatible: in `fake`/`dydx` mode it returns `dydx`.

3. **Two capability gates in the registry, separate from `integrated` (= data):**
   - `live_modes` — live/automated trading modes. HL `= []` ⇒ `routers/live.py`
     rejects HL live trading.
   - `sim_enabled` — the Simulation + Fast-Forward sections. HL `= False` ⇒
     `routers/{sim,ff}.py` reject HL. (dYdX `= True`.)
   The HL **trade client** (`exchanges/hyperliquid/trade_client.py`, EIP-712 via
   `hyperliquid-python-sdk`) is **built and unit-tested but parked** behind these
   gates for the future LiveBot phase. `production` (mainnet/real money) is never
   enabled by a deploy — going live stays deliberate (CLAUDE.md / DEPLOYMENT.md §7).

4. **UI venue selector.** The market-data control is a venue selector
   (Demo / dYdX / Hyperliquid) that sets `SCAN_DATA_SOURCE`; nothing else in the UI
   needs an exchange parameter because of decision (2).

## Consequences

- **Positive.** Selecting HL scopes scan + Manual Trading + Backtest onto HL with
  one switch and venue-consistent funding. Capability gates make "data-only" a
  first-class, enforced state — no reachable-but-unvalidated sim/live paths. The
  schema and registry generalise to further venues.
- **Trade-off — the global-toggle model persists.** Data source is app-wide, not
  per-strategy. A backtest reads whatever venue the global source points at; in
  `fake` mode `replay/candle_source.make_candle_source` returns the demo source
  regardless of a strategy's exchange (offline/demo is intentional). A future
  per-strategy data-source decouple would remove this coupling; it was out of scope
  here and `active_exchange()` is the minimal consistent fix.
- **Deferred (future phases):** HL LiveBot/FF/Sim (un-park the trade client), the
  S3 deep-history backfill, and any Binance work.
