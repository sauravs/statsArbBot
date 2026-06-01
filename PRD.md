# statsArbBot — Product Requirements Document (PRD)

**Status:** Draft v1 · **Date:** 2026-06-01 · **Owner:** weblife.shekhar24@gmail.com
**Companion docs:** `PLAN.md` (how), `research.md` (quant evidence), `initial-codebase-analysis.md` (codebase map), `CONTEXT.md` (domain glossary)

---

## 1. Overview

`statsArbBot` is a statistical-arbitrage / **pairs-trading** system for **dYdX v4 perpetual futures**. It discovers cointegrated pairs of crypto perpetuals, monitors the spread between them, and trades mean reversion: when the spread deviates abnormally far from its equilibrium it enters a market-neutral two-leg position (long one, short the other) and exits when the spread reverts.

This PRD specifies a **full rewrite** of an existing prototype (`oldCodeRef_Prototype`). The rewrite preserves the prototype's feature set, tech stack, and UI theme, but re-architects the codebase for correctness and robustness, fixes known bugs, validates all formulas against the algorithmic ground truth (`oldCodeRef_Main_Source`), applies four research-backed algorithm improvements, adds one new feature (**Live Manual Trading**), and improves charting.

### 1.1 Goals
- Correct, validated statistical engine (matches ground-truth reference within tolerance).
- Robust architecture: DB-backed state, no race conditions, no flat-file persistence for live state.
- Same tech stack and UI theme; recoded frontend architecture.
- One new feature: Live Manual Trading with full lifecycle tracking.
- Improved 3-panel charting.
- Phased, test-gated delivery.

### 1.2 Non-Goals (this phase)
Binance/Hyperliquid implementations; AI/LangGraph features; WebSocket price feed; advanced quant methods (Johansen, KSS, HMM regime filter, Kalman hedge ratio, log-prices, Z-proportional sizing); live AWS deployment.

---

## 2. Users & Context

Single operator (the owner). Self-hosted. Authenticated by a 6-digit passcode. Trades on dYdX testnet (validation) and mainnet (production), controlled via a web dashboard, optionally gated through Telegram approvals.

---

## 3. Core Trading Algorithm

The single source of algorithmic truth, reused identically by live trading, real-time simulation, fast-forward simulation, and backtest.

### 3.1 Pair Discovery (Scan)
1. Fetch historical hourly candles for all eligible dYdX v4 perpetual markets.
2. For every pair (S1, S2), run the **Engle-Granger** two-step cointegration test (`statsmodels.coint`).
3. Fit OLS `S1 = α + β·S2 + ε` to obtain hedge ratio **β** and intercept **α**.
4. Compute spread `= S1 − β·S2 − α` *(intercept included — Option-B change #1)*.
5. Compute the **Ornstein-Uhlenbeck half-life** of the spread.
6. Keep pairs where `p_value < 0.05` **and** `0 < half_life ≤ 72h` *(cap tightened from 200h — Option-B change #4)*.
7. Persist results to CSV **and** the `CointScanResult` DB table (dual-write).

### 3.2 Signal & Execution
- **Z-score:** rolling window (default 21, configurable) on the spread.
- **Entry:** `|Z| ≥ ZSCORE_THRESH` (default 1.5). `Z<0` → BUY base / SELL quote; `Z>0` → SELL base / BUY quote.
- **Exit:** `|Z| < 0.5` *(Option-B change #3 — replaces zero-crossing)*.
- **Stop-loss:** `|Z| ≥ 4.0` **or** position age `> 3 × half_life` *(Option-B change #2)*.
- **Sizing:** fixed notional per leg (default $100), configurable.
- **Collateral guard:** no new entries when free collateral `< USD_MIN_COLLATERAL`.
- **Execution:** atomic two-leg placement; if leg 2 fails after leg 1 fills, immediately failsafe-close leg 1; if that fails, emit CODE-RED alert.

The four Option-B changes and their evidence are documented in `research.md` (§2, §4, §5, §6).

---

## 4. Features & Requirements

### F1 — Authentication
- **F1.1** 6-digit passcode login with individual digit boxes, auto-submit, shake-on-error, paste support.
- **F1.2** Cookie-based JWT session; Next.js middleware guards all routes; server-side `/api/proxy` injects the API key.
- **Acceptance:** wrong code shakes & rejects; correct code sets cookie and lands on dashboard; unauthenticated route access redirects to login.

### F2 — Cointegration Scan & Pairs Table
- **F2.1** Trigger scan/rescan from the dashboard; background async execution with live progress.
- **F2.2** Pairs table lists cointegrated pairs with base, quote, hedge ratio, half-life, current Z-score, p-value.
- **F2.3** Results dual-written to CSV + `CointScanResult`.
- **Acceptance:** clicking Scan shows progress, then a populated, sortable pairs table; results survive reload (read from DB).

### F3 — Pair Detail & 3-Panel Charts
- **F3.1** Pair detail route shows three stacked panels via `lightweight-charts` v5:
  1. **Normalized price overlay** (both legs rebased to 100).
  2. **Spread** with mean line and ±1σ / ±2σ bands.
  3. **Z-score** with horizontal threshold lines at ±1.5 (entry) and ±4.0 (stop), plus entry/exit markers.
- **Acceptance:** opening a pair renders all three panels with correct data and threshold lines.

### F4 — Live Manual Trading *(NEW)*
- **F4.1 Z-threshold slider:** single-handle control, value range 0.5–4.0, rendered on a −5…+5 axis with a shaded neutral band between ∓threshold. Adjusting it live re-filters which pairs count as "active signal."
- **F4.2 Active-signal detection:** a pair is "active" when `|Z| ≥ slider threshold`.
- **F4.3 Record button:** a "Record Manual Trade" button appears **only** on active-signal pairs.
- **F4.4 Capital popup:** clicking the button opens a modal requesting capital allocated to leg 1 (base) and leg 2 (quote) in USD.
- **F4.5 Record:** on confirm, persist to `ManualTrade`: base/quote markets, hedge_ratio, half_life, z_score, spread_value, capital_leg1_usd, capital_leg2_usd, recorded_at, exchange, mode, status=`OPEN`.
- **F4.6 Manual Trades section:** a separate section (not mixed with bot trades) listing recorded manual trades.
- **F4.7 Lifecycle:** each manual trade can be marked **closed** (user enters exit price/date); system computes and stores P&L; status → `CLOSED`.
- **Acceptance:** set threshold → active pairs reveal the button → record with capital → entry appears in Manual Trades (OPEN) → mark closed → P&L computed and displayed (CLOSED).

### F5 — Live Trading Bot
- **F5.1** Modes: `forward_test` (testnet) and `production` (mainnet).
- **F5.2** Entry scan, exit/stop management, abort-all; order placement via `dydx-v4-client`.
- **F5.3** DB-backed trade state (`LiveSession`/`LiveTrade`); **real P&L** computation.
- **F5.4** Approval gate behind an interface — stub (`approve_all`/`reject_all`) now, Telegram later.
- **F5.5** UI: Open Trades table, bot activate/deactivate controls, account card, portfolio status, trade history, mode tabs.
- **Acceptance (testnet):** entry opens a real testnet position; exit/stop closes it; trade recorded with correct P&L; UI reflects state.

### F6 — Real-Time Simulation
- **F6.1** DB-backed `SimulationEngine`, stateless across ticks, restorable after restart.
- **F6.2** **Proper rolling Z-score** (fixes prototype's `0.02`-std approximation).
- **F6.3** Cost model: slippage, taker fee, funding.
- **F6.4** APScheduler interval ticks; sessions re-registered on API restart.
- **F6.5** UI: create / pause / resume / stop / top-up capital.
- **Acceptance:** a session ticks, opens/closes virtual trades on real signals, and updates positions/PnL/equity.

### F7 — Fast-Forward Simulation
- **F7.1** `FastForwardReplayEngine` replays historical OHLCV at N× speed through the same `SimulationEngine`.
- **F7.2** Progress tracking; saved aggregates (`SavedFFSimulation`): equity curve, per-pair PnL, exit reasons.
- **F7.3** UI: list / run / detail / saved-results views.
- **Acceptance:** an FF run completes over a chosen date range and persists viewable results.

### F8 — Walk-Forward Backtest
- **F8.1** Sliding windows (90-day scan / 30-day trade), strategies S1–S4 (varying Z-threshold/window).
- **F8.2** Subprocess orchestration with progress, pause, stop, partial save + resume.
- **F8.3** Strategy CRUD with rank recompute (by net P&L); markdown reports.
- **F8.4** UI: backtest page, strategy comparison, create strategy, reports viewer.
- **Acceptance:** a backtest runs to completion, ranks strategies, and renders equity curves + reports; pause/stop/resume work.

### F9 — Telegram Integration *(late phase)*
- **F9.1** Real approval flow: signals prompt ✅/❌ in Telegram; timeout auto-rejects; decision drives execution.
- **F9.2** Commands: `/status`, `/balance`, `/positions`, `/pairs`, `/cancel`, `/activate`, `/deactivate` (the prototype's `connect_dydx` naming bug is fixed).
- **Acceptance:** a pending signal posts to Telegram; approving executes; rejecting/timeout skips; commands return live data.

---

## 5. Data Model (Prisma / PostgreSQL)

Tables (carried from prototype, plus the new `ManualTrade`):
- `CointScanResult` — scan output per exchange+mode (now dual-written).
- `ManualTrade` *(new)* — base_market, quote_market, hedge_ratio, half_life, z_score, spread_value, capital_leg1_usd, capital_leg2_usd, recorded_at, closed_at, exit details, pnl, status (`OPEN`/`CLOSED`), exchange, mode.
- `LiveSession` / `LiveTrade` — live bot sessions and trades (with real P&L).
- `SimSession` / `SimPosition` / `SimTrade` — simulation state.
- `SavedFFSimulation` — fast-forward saved aggregates.
- `Strategy` — backtest strategy runs, ranked; supports partial/resume.
- `BotConfigHistory` — append-only config audit.
- `OhlcvCache` — cached candles.
- Exchange-registry metadata (dYdX integrated; Binance/Hyperliquid stub flags).
- *(Deferred/empty)* AI tables retained in schema only if zero-cost.

Final field-level schema is defined during Phase 0/4 implementation.

---

## 6. Non-Functional Requirements

- **Correctness:** statistical engine numerically matches reference data within tolerance (Phase 1 gate).
- **Robustness:** DB-backed live state; proper async concurrency control on shared scan/backtest state; Prisma client generation wired into build + lifespan (no `FieldNotFoundError`/503 class of bugs).
- **Security:** secrets in `.env` (gitignored); previously-exposed keys rotated; no secrets committed.
- **Testability:** unit + integration + Playwright E2E per phase; dYdX and Telegram mockable behind interfaces.
- **Safety:** atomic two-leg execution with failsafe close + CODE-RED alert; collateral guard; testnet validation before production.
- **Maintainability:** pure isolated statistical core; exchange-registry and approval-gate abstractions; ADR-documented decisions.

---

## 7. Bugs the Rewrite Must Eliminate
Simplified simulation Z-score (`0.02` std); `connect_dydx`/`create_dydx_connection` mismatch; Prisma regeneration 503s; scan-state race conditions; unwired stop-loss; missing `CointScanResult` dual-write; missing P&L calculation; missing portfolio snapshots. (Source: `initial-codebase-analysis.md`.)

---

## 8. Release Strategy
Phased, vertical, test-gated — see `PLAN.md`. Each phase delivers a working, tested, committed increment. A phase is complete only when its unit + integration + (UI) Playwright gates pass.
