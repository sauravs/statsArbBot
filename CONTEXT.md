# statsArbBot — Domain Context & Glossary (CONTEXT.md)

**Purpose:** Ground the codebase in shared domain language so architecture work (and the `improve-codebase-architecture` skill) reasons about the *right* concepts. This is the ubiquitous language of the system — module, class, and function names should track these terms.

---

## What the System Does

`statsArbBot` trades **pairs** of dYdX v4 perpetual futures using **statistical arbitrage**. It finds two assets whose prices move together over the long run (**cointegrated**), watches the gap between them (**spread**), and bets that an abnormally wide gap will **revert** to its historical mean — going long the underpriced leg and short the overpriced leg simultaneously (market-neutral).

---

## Core Domain Terms

- **Pair** — two markets (S1 = *base*, S2 = *quote*) tested/traded together. Identified as `base_market` / `quote_market`.
- **Leg** — one side of a pair trade. **Leg 1** = base market order; **Leg 2** = quote market order. A pair position has two legs placed atomically.
- **Cointegration** — a statistical property: although S1 and S2 are individually non-stationary (they wander), a specific linear combination of them is **stationary** (mean-reverting). Tested via the **Engle-Granger** two-step method (`statsmodels.coint`). Stronger than correlation.
- **Hedge ratio (β)** — the OLS slope from `S1 = α + β·S2 + ε`. How many units of the quote leg offset one unit of the base leg to form a market-neutral position.
- **Intercept (α)** — the OLS constant from the same regression. **Included** in the spread (see below) so the spread is centered at its true equilibrium rather than drifting.
- **Spread** — the cointegrating residual: `spread = S1 − β·S2 − α`. The quantity that should mean-revert. The traded signal is derived from it.
- **Ornstein-Uhlenbeck (OU) process** — the continuous-time mean-reverting process the spread is assumed to follow. Its key statistic here is the half-life.
- **Half-life** — average time for the spread to revert halfway to its mean: `half_life = ln(2)/θ`, θ from regressing `Δspread` on lagged `spread`. Shorter = faster reversion = better pair. **Filter:** keep `0 < half_life ≤ 72h`.
- **Z-score** — standardized spread over a rolling **window** (default 21 bars): `z = (spread − rolling_mean) / rolling_std`. The live trading signal.
- **Signal** — an actionable state derived from the Z-score for a pair: entry, exit, or stop.
- **Zero-crossings** — count of times the spread crosses its mean in the formation window; a quality proxy (more crossings = more reliably mean-reverting).

---

## Trading Rules (the decision logic)

- **Entry:** `|Z| ≥ ZSCORE_THRESH` (default 1.5).
  - `Z < 0` (spread below mean) → **BUY base, SELL quote**.
  - `Z > 0` (spread above mean) → **SELL base, BUY quote**.
- **Exit:** `|Z| < 0.5` — spread has reverted; take profit.
- **Stop-loss:** `|Z| ≥ 4.0` **or** position age `> 3 × half_life` — likely cointegration breakdown; cut losses.
- **Sizing:** fixed notional per leg (default $100).
- **Collateral guard:** suspend new entries when free collateral `< USD_MIN_COLLATERAL`.

*(The exit/stop/intercept/half-life-cap values reflect the four research-backed "Option-B" changes; evidence in `research.md`.)*

---

## Execution & Safety Terms

- **BotAgent** — the executor that places a pair's two legs atomically and manages partial-fill risk.
- **Failsafe close** — if Leg 2 fails to fill after Leg 1 fills, Leg 1 is immediately closed to avoid a naked (one-sided) position.
- **CODE-RED** — critical alert when even the failsafe close fails; demands human attention.
- **Abort-all** — cancel all open orders and flatten all positions.
- **Approval gate** — an interface that must approve a signal before execution. Implementations: **stub** (`approve_all`/`reject_all`, used in early phases/tests) and **Telegram** (human ✅/❌, later phase).
- **Collateral / free collateral** — account equity available to open new positions.
- **Funding rate** — periodic (hourly on dYdX) payment between long and short perp holders; a real carrying cost that motivates the tighter `|Z|<0.5` exit.
- **Half-spread** — half the bid/ask gap; the per-leg cost of crossing the book at top-of-book. **Per-market spread** (Phase-2 Slice 1, `simulation/spread_cost.py`) charges each market its own half-spread (volume→spread curve) instead of one flat `slippage_pct`.
- **Market impact** — the *extra* adverse fill from a large order **walking the book**, beyond the half-spread. Modelled size-aware as `σ·√(Q/ADV)` (Phase-2 Slice 3, `simulation/market_impact.py`); grows ∝ Q^1.5, so bigger size erodes the edge. Gate **B5** ("executable at real size").
- **Deflated Sharpe Ratio (DSR)** — the probability a strategy's *true* Sharpe is positive after correcting for the **number of configs searched** (the best of 69 is plausibly the luckiest draw), return non-normality, and sample length (Bailey & López de Prado; Phase-2 Slice 4, `stats/deflated_sharpe.py`). DSR > 0.95 clears gate **B3**. Surfaced as a dashboard badge.
- **PBO (Probability of Backtest Overfitting)** — via CSCV; the chance the in-sample-best config underperforms the median out-of-sample. A validated tool for a same-window overfitting study (not wired to the mixed-span leaderboard).

---

## System Modes & Run Types

- **Mode** — `forward_test` (dYdX **testnet**, safe validation) vs `production` (**mainnet**, real funds).
- **Live trading** — the bot autonomously scans, enters, and exits on the real exchange.
- **Manual trading** *(new)* — the operator records a trade they take by hand off a bot signal: capital per leg + pair params + timestamp captured to DB, with a close/P&L lifecycle. Distinct from live trading (no bot order execution).
- **Real-time simulation** — virtual (paper) trading against live prices via scheduled ticks; DB-backed.
- **Fast-forward simulation** — replay of historical candles at N× speed through the same simulation engine.
- **Walk-forward backtest** — sliding scan/trade windows over history to evaluate strategies (S1–S4), ranked by net P&L.

---

## Data & Persistence Terms

- **Candle / OHLCV** — open/high/low/close/volume bar (hourly resolution by default).
- **Price matrix** — datetime-indexed DataFrame of close prices across all scanned markets; input to pairwise cointegration.
- **Scan** — the discovery run that produces cointegrated pairs; results dual-written to **CSV** and the **`CointScanResult`** table.
- **DB-backed state** — all live/sim/manual state lives in PostgreSQL (via Prisma), not flat files — eliminating the prototype's race conditions and lost-state bugs.

---

## Architectural Stances (see `docs/adr/`)
- **Pure, isolated statistical core** (`statcore/`) — single source of algorithmic truth, reused by live, simulation, fast-forward, and backtest paths.
- **Exchange-registry abstraction** — dYdX v4 implemented; other exchanges are stubs behind the same interface.
- **Approval gate as an interface** — swap stub → Telegram without touching the trading engine.
- **No flat-file live state** — DB-backed everywhere.
