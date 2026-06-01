
# Initial Codebase Analysis — statsArbBot Rewrite
*Analyzed 2026-05-31. Reference for future sessions — do not re-analyze from scratch.*

---

## Project Goal

Rebuild a statistical arbitrage / pairs trading bot for **dYdX v4 perpetuals**. The rebuild must:
- Fix all known bugs from `oldCodeRef_Prototype`
- Use the correct algorithms from `oldCodeRef_Main_Source` as the ground truth
- Apply four targeted research-backed improvements (see `research.md`)
- Add one new feature: "Live Manual Trading" (record manual trades from bot signals)
- Same tech stack, same UI theme, recoded frontend architecture
- Improved charting (reference: `Old Reference Resources/oldCodeRef_Main_Source/dydxRefResource/For AI/Screenshot 2026-02-19 at 1.32.06 PM.png`)

---

## Reference Source: `oldCodeRef_Main_Source/dydxRefResource/program/`

### Architecture (3 Stages)
```
Stage 1 (one-time setup):
  Connect to dYdX → Abort existing positions → Get ISO time windows

Stage 2 (run once or periodically):
  Fetch historical candles for ALL markets → Build price matrix →
  Run pairwise cointegration tests → Filter by p-value, half-life →
  Save passing pairs to cointegrated_pairs.csv

Stage 3 (continuous loop):
  [Exit manager]  Read bot_agents.json → Recalculate z-score →
                  If z-score crosses zero → Close both legs
  [Entry manager] Read cointegrated_pairs.csv → Compute spread z-score →
                  If |z-score| >= 1.5 → Check collateral → Place orders
```

### Key Algorithm (Ground Truth)
- **Exchange:** dYdX v3 (StarkEx L2) — prototype upgraded to v4
- **Cointegration:** Engle-Granger two-step (`statsmodels.tsa.stattools.coint`)
- **Hedge ratio:** OLS regression `series_1 = β * series_2` (no intercept — this is a known weakness, fix in rewrite)
- **Spread:** `series_1 - hedge_ratio * series_2`
- **Half-life:** OU model — `Δspread = α + β * spread_lag`, `half_life = -ln(2) / β`
- **Z-score:** Rolling 21-period: `(current - rolling_mean) / rolling_std`
- **Entry trigger:** `|z_score| >= 1.5`
- **Entry direction:** z < 0 → BUY base, SELL quote; z > 0 → SELL base, BUY quote
- **Exit trigger:** Z-score crosses zero (sign reversal)
- **Pair filter:** `0 < half_life <= 24h`, `p_value < 0.05`
- **Position sizing:** Fixed `$100 / price` per leg
- **Order type:** Market orders (FOK, 70s expiry, 1.5% max fee)
- **Collateral guard:** Stop new entries if free collateral < $1,880
- **State persistence:** `bot_agents.json` (flat file)
- **Notifications:** Telegram Bot API

### Key File Structure
```
main.py           — Entry point, four boolean flags control execution
constants.py      — All trading parameters
func_connections.py — dYdX client setup
func_public.py    — Market data (candles, price matrix)
func_cointegration.py — Core statistical engine
func_private.py   — Order placement, abort
func_entry_pairs.py — Entry signal scanning
func_exit_pairs.py  — Exit management
func_bot_agent.py   — Two-leg atomic order executor
func_messaging.py   — Telegram notifications
func_utils.py     — Time windows, number formatting
```

### Critical Safety Logic (must preserve in rewrite)
In `func_bot_agent.py`: if leg 2 fails after leg 1 fills → immediately place failsafe close on leg 1. If failsafe close also fails → send Telegram "Code red" + `exit(1)`.

---

## Prototype: `oldCodeRef_Prototype/`

### Tech Stack
- **Backend:** Python 3.12, FastAPI (async), Uvicorn, Prisma ORM (async), PostgreSQL 16
- **Exchange SDK:** `dydx-v4-client` v1.1.6
- **Data science:** pandas, numpy, statsmodels
- **Scheduler:** APScheduler (`AsyncIOScheduler`) for simulation ticks
- **Telegram:** `python-telegram-bot` v20+ (async)
- **Frontend:** Next.js 14 (App Router, TypeScript), Tailwind CSS (pure, no component library)
- **Charts:** Recharts (equity curves), TradingView `lightweight-charts` v5 (OHLCV)
- **Data fetching:** SWR (polling hooks)
- **Auth:** Cookie-based JWT (`jose`), Next.js middleware
- **Testing:** pytest, pytest-asyncio, Jest, Playwright (E2E)
- **Infrastructure:** Docker Compose (postgres + api + ui)

### UI Theme (preserve)
```
Background:     #0a0b0d  (near-black)
Card surface:   #12141a
Border:         #21262d
Muted text:     #8b949e
Primary text:   #e4e6ea
Accent green:   #00d4a1  (profit/active)
Accent red:     #ff4757  (loss/inactive)
Yellow:         #ffd32a  (warnings)
Blue:           #4a90e2  (links/active tabs)
```
Dark terminal/trading-terminal aesthetic. No component library — pure Tailwind.

### Features Implemented
1. **Live Bot** (forward_test + production modes) — scan, entry, exit, abort
2. **Real-time Simulation** — DB-backed, APScheduler ticks
3. **Fast-Forward Simulation** — historical OHLCV replay at N× speed
4. **Walk-forward Backtest** — 90-day scan / 30-day trade windows, 4 strategies
5. **Telegram approval gates** — approve/reject signals via Telegram
6. **6-digit passcode login** — cookie-based auth
7. **Cointegrated pairs scan** — background async scan with progress streaming
8. **Portfolio status** — live indexer data + DB metrics

### Database Schema (Prisma / PostgreSQL)
Key tables:
- `Strategy` — saved backtest runs, ranked by net_pnl
- `SimSession` / `SimPosition` / `SimTrade` — simulation state
- `SavedFFSimulation` — completed fast-forward results
- `LiveSession` / `LiveTrade` — live bot trade records
- `BotConfigHistory` — config change audit log
- `OhlcvCache` — seeded OHLCV data
- `CointScanResult` — scan results (schema exists, not fully populated)
- `AiAgentState` / `AiObservation` — Phase 3 AI (empty)

### Backend Router Structure
```
/api/*          — live.py   (bot control, scan, agents, portfolio, signals, trades)
/backtest/*     — backtest.py (results, equity curve, strategies CRUD, run/pause/stop)
/sim/*          — simulation.py (RT sim + FF sim sessions, saved FF)
/exchange/*     — exchange.py (registry)
```

### Frontend Structure
```
app/
  login/page.tsx              — 6-digit passcode auth
  dashboard/page.tsx          — Main trading dashboard (SPA-style)
  dashboard/pair/[b]/[q]/     — Pair detail view
  backtest/page.tsx           — Backtest page
  backtest/pair/[e]/[b]/[q]/  — Pair backtest detail
  api/auth/                   — Next.js auth route
  api/proxy/[...path]/        — Server-side API proxy (adds X-API-Key)

components/
  Navbar.tsx, AccountCard.tsx, BotControls.tsx
  OpenTradesTable.tsx, PairsTable.tsx, PairCharts.tsx
  PortfolioStatus.tsx, TradeHistoryPanel.tsx
  backtest/ (12 components), simulation/ (8 components)

lib/api.ts     — Typed API client (900+ lines, all endpoints)
middleware.ts  — Cookie auth guard for all routes
```

---

## Known Bugs in Prototype (All Must Be Fixed in Rewrite)

### Critical Bugs
1. **Simplified Z-score in simulation engine** (`simulation/engine.py:152-154`): Uses `abs(spread_ref) * 0.02` as estimated std instead of proper rolling window. Causes wrong exits/entries in real-time simulation.
2. **`func_connections.py` naming mismatch**: `telegram_bot.py` `/cancel` command calls `create_dydx_connection` but function is named `connect_dydx`. NameError at runtime if /cancel used.
3. **Prisma client regeneration issue**: Multiple endpoints catch `FieldNotFoundError` and return HTTP 503 — schema and generated client can go out of sync.
4. **`_scan_state` threading race conditions** in `routers/live.py`: background tasks using `run_in_executor` may cause races on shared `_bt_state` dict without proper locking.

### Incomplete Features (in scope for rewrite)
1. Missing hard stop-loss — `STOP_LOSS_ZSCORE` constant defined but not wired to exit logic
2. Spread formula missing intercept (see `research.md` Section 2)
3. Half-life cap too loose (200h vs recommended 48-72h)
4. `CointScanResult` DB table exists but scan results not written to it
5. PnL calculation not implemented (`/cmd_pnl` returns static message)
6. Portfolio snapshots not implemented

### Out of Scope for Rewrite (Deferred)
1. Binance / Hyperliquid integrations (stubs only)
2. Phase 3 AI tables (LangGraph)
3. WebSocket price feed
4. Johansen cointegration test
5. HMM regime filter
6. Dynamic (Kalman) hedge ratio
7. Z-score-proportional position sizing

---

## New Feature: "Live Manual Trading"

### Purpose
Allow the user to manually execute trades based on bot-generated signals, with those trades tracked in the system database.

### Requirements (as understood)
1. **Location:** Main dashboard, after cointegration scan/rescan
2. **Signal display:** Eligible pairs table — shows all cointegrated pairs that currently have `|Z-score| >= entry_threshold`
3. **Per-pair action:** "Record Manual Trade" button next to each eligible pair
4. **On button click:** Pop-up modal opens asking for:
   - Capital allocated to Leg 1 (base market) in USD
   - Capital allocated to Leg 2 (quote market) in USD
5. **On confirm:** Record to DB:
   - All pair parameters: base_market, quote_market, hedge_ratio, half_life, z_score, spread value
   - capital_leg1_usd, capital_leg2_usd
   - Timestamp of recording
   - Pair status: "MANUAL_RECORDED"

### Database Table Needed
New table: `ManualTrade`
- `id` (CUID)
- `base_market` (String)
- `quote_market` (String)
- `hedge_ratio` (Float)
- `half_life` (Float)
- `z_score` (Float)
- `spread_value` (Float)
- `capital_leg1_usd` (Float)
- `capital_leg2_usd` (Float)
- `recorded_at` (DateTime)
- `exchange` (String)
- `mode` (String)

### Questions Still Open
- Should "Record Manual Trade" also appear for all pairs in the pairs table (even those not currently at |Z| >= threshold), or only for pairs with active signals?
- Should there be a way to mark a manually recorded trade as "closed" with P&L?
- Should the recorded pairs show up in a separate "Manual Trades" section or mixed with live bot trades?

---

## Algorithmic Improvements for Rewrite (Option B — 4 Changes Only)

These four changes are included in the rewrite. All other research findings are deferred.

| Change | Original | Rewrite | Evidence |
|---|---|---|---|
| Spread formula | `S1 - β*S2` | `S1 - β*S2 - α` | Kostadinov; QuantStart CADF |
| Stop-loss | None | \|Z\| >= 4.0 | arXiv:1706.07021; QuantInsti |
| Exit threshold | Zero-crossing | \|Z\| < 0.5 | arXiv:2412.12555; arXiv:2407.16103 |
| Half-life cap | 200h | 72h | arXiv:2109.10662; QuantConnect |

---

## Charts — Improvement Target

Reference screenshot: `Old Reference Resources/oldCodeRef_Main_Source/dydxRefResource/For AI/Screenshot 2026-02-19 at 1.32.06 PM.png`

The cryptowizards.net pair screener shows:
- Clean price overlay chart (two normalized price series on one chart)
- Spread chart below (with mean line and ±1σ, ±2σ bands)
- Z-score chart with entry/exit threshold lines clearly marked
- Good color contrast between the two price series

Current prototype uses TradingView `lightweight-charts` v5 for OHLCV and Recharts for equity curves. Improvement: add Bollinger-band-style visualization on the spread chart with σ bands.

---
*End of initial-codebase-analysis.md*
