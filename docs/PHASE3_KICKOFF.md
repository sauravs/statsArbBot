# Phase 3 — kickoff prompt (post-Phase-2 workstreams)

**Purpose.** A ready-to-paste starting prompt for the next-session agent. Phase-2 sub-phase B
is complete + deployed (the honest measurement machinery; verdict: NO-GO). This bootstraps the
next batch of work — **three operator-requested workstreams** — with the verified code map +
gate encoded so nothing is re-discovered.

**How to use.** Start a fresh session in this repo and paste the fenced block below as the first
message. Keep it in sync if scope changes.

> Standing context (do not overturn): the bot is **NO-GO for live trading** — Phase-2 settled
> that on today's signal. These workstreams build **tooling/UX + a campaign runner**; none of
> them ships a live strategy or relaxes the gate in `.claude/CLAUDE.md`.

> **Operator decisions baked in (2026-07-27):** Workstream 2 minimises the manual list by
> **liquidity/spread, NOT market cap** (already-available data; better fillability proxy; no
> external dependency). Workstream 1's backtest filter is a **per-strategy** field; the scan
> floor is a **runtime-settable** control. All liquidity knobs are framed as
> **tractability/honesty** knobs, never "filter for more profit" (the §4 refutation stands).

---

```
ROLE: Senior quant + full-stack engineer on statsArbBot (Hyperliquid pairs-trading /
stat-arb bot). Prod on EC2: ubuntu@13.219.54.108, key ~/.ssh/pairArbBotKeyPridevel.pem,
containers statsarbbot-{api,ui,postgres}-1, DB statsarb/statsarb. Backend API key is
DASHBOARD_PASSWORD (NOT 123456 — that's the LOCAL dev key); header X-API-Key. The box is
2-vCPU → backtest sweeps are slow (~2-3h for 3 concurrent). Monitor sweeps via the DB, not
the HTTP API (the CPU-bound scan saturates the event loop). See memory prod-ops-facts.

CONTEXT: Phase-2 sub-phase B is COMPLETE + deployed (Slices 0-4,6; PRs #225-236). The honest
measurement machinery shipped and returned an unambiguous NO-GO (best OOS +$157 @ $100/leg →
-$50,670 @ $1k/leg once market impact is charged; nothing clears DSR>0.95). Prod is safe
(ENVIRONMENT=testnet), with PER_MARKET_SLIPPAGE=on, MARKET_IMPACT=on, MIN_LIQUIDITY_USD=1M,
data_source=hyperliquid. Read docs/PHASE2_STRATEGY_PLAN.md + docs/strategy.md (Phase-2
campaign section) for the full picture before starting.

THE GATE — follow .claude/CLAUDE.md EXACTLY (non-negotiable):
- Per unit of work: short-lived feat-<slug>/fix-<slug> branch off main → implement with TDD →
  test end-to-end on the LOCAL DEV DOCKER STACK → PR (CI must pass) → EXPLICIT OPERATOR
  APPROVAL → merge to main → (only if operator says) promote main→production + deploy.
- production = dYdX/HL MAINNET, real money. Deploy leaves the bot SAFE (ENVIRONMENT stays
  testnet; going live is deliberate, never a side effect). pg_dump BEFORE any prisma migrate
  deploy; NEVER delete strategy rows. SCAN_DATA_SOURCE resets to dydx on restart → re-POST
  /api/system/data-source back to hyperliquid.
- ASK BEFORE GUESSING on scope/criteria/data.

═══ WORKSTREAM 1 — Liquidity filters in the UI (backtest + manual trading) ═══
Today all three liquidity knobs are env-only module constants: MIN_LIQUIDITY_USD (scan floor,
path a; read in exchanges/{hyperliquid,dydx}/client.py), and BACKTEST_MIN_DOLLAR_VOLUME +
BACKTEST_MAX_HALF_SPREAD_PCT (backtest universe, path b; read in backtest/engine.py
_filter_universe). Surface them in the UI:
- Scan floor (drives the manual/scan list): a runtime-settable control mirroring the existing
  config.set_scan_data_source pattern + a POST /api/system endpoint (resets on restart, like
  data-source — acceptable). Show it in the Manual Trading + scan controls.
- Backtest universe filter: make it a PER-STRATEGY config field (Strategy schema column →
  additive migration → StrategyBody + create form ADVANCED panel → thread into _filter_universe
  instead of the global env). Persisted with the run.
- FRAMING (critical): present these as tractability/honesty knobs, NOT "filter for more
  profit" — the §4 refutation shows filtering up LOSES money. Add a short inline note + link
  to the QA.md entry. Default OFF for the backtest filter; $1M for the scan floor.
- TDD + local-docker e2e; docs (USER_GUIDE, QA.md). Migration: pg_dump → prisma migrate deploy.

═══ WORKSTREAM 2 — Minimise the manual-trading market/pair list (liquidity, not market cap) ═══
Minimise by LIQUIDITY, not market cap (operator-approved 2026-07-27). The scan pairs markets
(~N²/2), so a dollar-volume floor cuts the pair list super-linearly; add an optional half-spread
ceiling (tradability) and a top-N cap by a tradability score (dollar-volume × cointegration
quality: low p-value / short half-life). Reuses existing data (ohlcv_cache volume + spread_cost)
— no external dependency. Market cap is explicitly REJECTED: needs an external API (CoinGecko) +
brittle HL-symbol mapping, and it's a WORSE proxy for "can I fill this at market size" than
liquidity/spread (a high-mcap illiquid token still can't be filled). This overlaps Workstream
1's scan-floor control; the half-spread ceiling + top-N tradability cap are the new parts. TDD +
e2e; docs.

═══ WORKSTREAM 3 — Backend strategy-campaign runner (automate phase-1-style sweeps) ═══
Build a campaign/sweep orchestrator so the backend can plan → create → execute many strategies
automatically (like the phase-1 69-config campaign, but repeatable and hands-off):
- A campaign spec = a parameter grid (e.g. entry-Z ∈ {3.0,3.5}, spans s2/s3/s4, cost flags),
  expanded into concrete strategy configs. New runs auto-stamp phase 2 (Slice 6 create path).
- Batch-create + an execution queue with BOUNDED concurrency (2-vCPU box → ~2-3 concurrent max;
  make it configurable), reusing the existing BacktestEngine run/pause/stop/resume + the
  per-market cost model. DB-backed progress so a restart resumes (mirror the sweep's
  processed_windows pattern).
- Endpoints: POST /api/backtest/campaigns (spec → created strategies + queued), GET status.
  Optional: a minimal UI to launch/monitor a campaign.
- Honest defaults: campaigns run with PER_MARKET_SLIPPAGE + MARKET_IMPACT on (phase-2 cost).
- TDD (grid expansion, queue concurrency, resume) + local-docker e2e; docs.

═══ VERIFIED CODE MAP (re-confirm line numbers) ═══
- Scan floor: config.MIN_LIQUIDITY_USD (config.py); applied exchanges/hyperliquid/client.py,
  dydx/client.py. Read at call time → a runtime-settable global takes effect (see
  config.set_scan_data_source as the pattern to mirror).
- Backtest universe filter: config.BACKTEST_MIN_DOLLAR_VOLUME / BACKTEST_MAX_HALF_SPREAD_PCT;
  backtest/engine.py::_filter_universe (built into _sweep before _load_history); pure logic in
  simulation/spread_cost.py::filter_universe. Per-market $-vol via
  ingest/cache_repository.get_dollar_volumes.
- Cost model: simulation/spread_cost.py (per-market half-spread), simulation/market_impact.py
  (σ·√(Q/ADV)); engine composes them in backtest/engine.py::_build_slippage_map. Flags
  PER_MARKET_SLIPPAGE / MARKET_IMPACT.
- Backtest CRUD/run: routers/backtest.py (StrategyBody, create_strategy, /strategies/{id}/run,
  /seed-defaults, /significance); engine backtest/engine.py (BacktestEngine.run/_sweep,
  pause/stop/resume); repo db/backtest_repository.py (_to_dict, _encode). Strategy schema
  backend/prisma/schema.prisma (phase Int @default(1), Slice 6).
- Significance/DSR: backend/stats/ (deflated_sharpe.py, significance.py) +
  GET /api/backtest/significance; UI DsrBadge/PhaseBadge in ui/components/SafetyBadges.tsx,
  filters in ui/components/StrategyList.tsx, taxonomy ui/lib/strategyTaxonomy.ts.
- Manual trading/scan: routers/scan.py, scan orchestrator backend/scan/, manual routers/manual.py,
  UI ui/components/PairsTable.tsx + Manual Trading page.

═══ DEVOPS / GOTCHAS ═══
- Local dev e2e: docker compose up -d --build. Host `npm run build` is broken (corrupted swc) →
  build/e2e in CI or the container; `npx tsc --noEmit` + eslint + vitest work on host. Backend
  tests: docker cp into statsarbbot-api-1 + run with -e SCAN_DATA_SOURCE=dydx. After a schema
  change: prisma migrate deploy + prisma generate in the container before pytest.
- CI gates backend·pytest + frontend·typecheck+build + e2e·playwright on main AND production.
- Prod: 2-vCPU → sweeps ~2-3h; monitor via psql not HTTP. pg_dump before migrate. Prod backend
  key = DASHBOARD_PASSWORD. Old ~/backups dumps may need pruning (disk).

START: read docs/PHASE2_STRATEGY_PLAN.md + the docs/strategy.md Phase-2 campaign section, confirm
the workstream order with me, then implement Workstream 1 slice-by-slice (smallest first) as
gated PRs. One PR per increment. Stop for approval before every merge/deploy; never promote to
production or go live without explicit OK.
```
