# Phase 2 — Sub-phase B kickoff prompt

**Purpose.** A ready-to-paste starting prompt for the next-session agent that will
**implement** Phase 2 sub-phase B. The approved plan/spec is
[`docs/PHASE2_STRATEGY_PLAN.md`](./PHASE2_STRATEGY_PLAN.md) — this file just bootstraps an
agent against it, with the verified code map + gate encoded so nothing has to be
re-discovered and the agent cannot drift into going live.

**How to use.** Start a fresh session in this repo and paste the fenced block below as the
first message. Keep it in sync with `PHASE2_STRATEGY_PLAN.md` if the plan changes.

> Standing verdict (do not overturn): the bot is **NO-GO for live trading**; sub-phase B
> builds the honest measurement + selection machinery, it does **not** ship a live strategy.
> The gate in `.claude/CLAUDE.md` is non-negotiable — one gated PR per slice, explicit
> operator approval before every merge/promotion, nothing goes live.

---

```
ROLE: You are a senior quant + full-stack engineer on statsArbBot (Hyperliquid
pairs-trading / stat-arb bot). Prod on EC2: ubuntu@13.219.54.108, key
~/.ssh/pairArbBotKeyPridevel.pem, containers statsarbbot-{api,ui,postgres}-1,
DB statsarb/statsarb, local API key 123456.

THIS IS PHASE 2 — SUB-PHASE B: IMPLEMENTATION. The plan from sub-phase A is
APPROVED and lives at docs/PHASE2_STRATEGY_PLAN.md (on main + production, PRs #222/#223).
READ IT IN FULL FIRST — it is the spec. Build on it; do not re-derive it.

═══ THE STANDING VERDICT (do not try to overturn it) ═══
No config clears the selection bar; the bot is NO-GO for live trading. The signal has a
real OOS gross edge (+$2,554, entry |Z|≥3.5) but flat taker friction erases it (best OOS
net +$187, inside the ±$212 noise floor). The liquidity "deciding experiment" REFUTED the
raise-the-floor hypothesis: gross is concentrated in the thinnest, untradeable markets, so
filtering up loses money. Your job is NOT to make it profitable. Your job is to BUILD THE
HONEST MEASUREMENT + SELECTION MACHINERY (§7 slices) so any future edge can be proven or
ruled out cheaply. Going live is out of scope and forbidden here.

═══ THE GATE — FOLLOW .claude/CLAUDE.md EXACTLY (non-negotiable) ═══
- production = dYdX/HL MAINNET, REAL MONEY. A deploy must leave the bot SAFE
  (ENVIRONMENT stays testnet; going live is deliberate, never a side effect). NOTHING here
  goes live.
- Per slice: short-lived feat-<slug>/fix-<slug> branch OFF main → implement with TDD →
  test END-TO-END on the LOCAL DEV DOCKER STACK → open PR (CI must pass) → GET EXPLICIT
  OPERATOR APPROVAL → merge to main → (only if operator explicitly says) promote main→
  production. Never commit straight to production; never let production get ahead of main.
- ASK BEFORE GUESSING on scope/criteria/data.

═══ SLICES (full spec in docs/PHASE2_STRATEGY_PLAN.md §7) — do them in order, one PR each ═══
0. MIN_LIQUIDITY_USD → 1_000_000 (config-only, live scan path a). Bump .env.example +
   sync docs (TRADING_CONCEPTS.md, USER_GUIDE.md, a QA.md line). It's tractability, NOT
   alpha. Apply to prod .env as part of this slice's deploy (env-only restart; remember
   SCAN_DATA_SOURCE resets to dydx on restart — POST /api/system/data-source back to
   hyperliquid).
1. Per-market realistic cost model: replace flat slippage_pct with a per-market spread
   cost (seed measured per-coin half-spread; fallback volume→spread curve). Re-run s2–s4.
2. Liquidity/spread filter on the backtest universe (_universe(), path b): optional,
   DEFAULT OFF, driven by config; ship WITH the §4 refutation documented so no one expects
   alpha. This is the engine change the docs call the "deciding experiment."
3. First-order market-impact charge (σ·√(Q/ADV) or calibrated participation), size-aware,
   in the cost layer.
4. Multiple-testing correction: in-house Deflated Sharpe Ratio + PBO (ref esvhd/pypbo,
   Bailey & López de Prado — ~40 lines, no heavy dep) surfaced on the strategy dashboard.
   Use statsmodels only as a cointegration/half-life TEST ORACLE. Reject vectorbt/zipline/
   ccxt/mlfinlab.
5. (optional) Pair-selection stability report across s2–s4.
6. UI + data model phase-tagging (NON-DESTRUCTIVE — never delete the 69 phase-1 rows):
   add `phase Int @default(1)` to Strategy (schema.prisma), backfill existing = 1,
   sub-phase-B create path stamps 2; add a "Phase 2" badge + a Phase filter toggle
   (default = ALL phases) in ui/lib/strategyTaxonomy.ts and the strategy list. Additive
   migration: pg_dump → prisma migrate deploy on prod.

═══ VERIFIED CODE MAP (from sub-phase A recon — re-confirm line numbers against the tree) ═══
- Two liquidity paths: scan filter MIN_LIQUIDITY_USD backend/config.py:188 (applied
  backend/exchanges/hyperliquid/client.py:249, dydx/client.py:130). Backtest universe
  _universe() backend/backtest/engine.py:604 → OhlcvCacheSource.available_markets()
  backend/replay/candle_source.py:56 → get_markets() in backend/ingest/cache_repository.py
  (bare GROUP BY market, NO filter). They are decoupled.
- Backtest API: StrategyBody backend/routers/backtest.py:51-70 (no market/universe field);
  create_strategy stamps data_source=SCAN_DATA_SOURCE; engine.run(strategy_id) engine.py:154
  → _sweep engine.py:182 (universe fetched at :244). No universe/allow-list param exists —
  slice 2 must add one.
- Cost model backend/simulation/costs.py (apply_slippage() ~:49-51 moves fills adversely;
  taker_fee_pct charged every leg entry+exit; net = gross − fees + funding).
- Schemas backend/prisma/schema.prisma: Strategy :431-498 (stores net_pnl only, no gross);
  BacktestTrade :506-540 (base_market, quote_market, entry_time, notional_usd, gross_pnl,
  fee_cost, funding_pnl, net_pnl, entry_z, half_life — use for cost/impact re-derivation);
  OhlcvCache :130-145 (has volume); FundingRateCache :404-414.
- Taxonomy classifier ui/lib/strategyTaxonomy.ts (families; cost tier MODELLED = fee≥0.05 &
  slip≥0.05; span vs in-sample 2026-03-01→06-23; realistic = MODELLED_COST && OUT_OF_SAMPLE).
  Introduced in PR #217. Extend it for the phase badge/toggle (slice 6) and DSR badge (slice 4).

═══ KEY NUMBERS (for tests/verification) ═══
- Spans: s1 2026-03-01→06-23 (in-sample); s2 2025-11-07→2026-03-01; s3 2025-07-16→11-07;
  s4 2025-03-24→2025-07-16. Baseline: entry|Z|3.0, exit0.5, stop4.0, p0.01, half-life72h,
  z-window21, scan21d/trade7d, $100/leg, $10k capital.
- Real taker cost 0.045% fee + 0.0316% mean slippage = 0.0766%/fill; friction/trade ≈
  4×(fee%+slip%) dollars at $100/leg. OOS entry-3.5 gross +$2,554 (from zero-cost runs
  cost-000-s2/s3/s4), net at real taker = +$187. Noise floor ±$212. entry-3.0 gross +$4,379.
- Zero-cost OOS trade rows (for cost-model re-derivation tests): cost-000-s2
  cmrut42o4gdi1xmy4dx6v9lqh, cost-000-s3 cmrule0f5g9djxmy4f937qrjo, cost-000-s4
  cmrut42oegdi2xmy41iut5cwd (entry3.5); cost000-e30-s2/s3/s4 cmrv3uniughg1xmy4pafg5328 /
  cmrv3unj2ghg2xmy4u6ou6h3d / cmrv3unjaghg3xmy4z6xfr8k5 (entry3.0).

═══ DEVOPS / GOTCHAS ═══
- Local dev docker stack for e2e: docker compose up -d --build. Host `npm run build` is
  broken (corrupted swc) — build/e2e in the CONTAINER; `npx tsc --noEmit` + lint work on host.
- Backend tests aren't in the api image: docker cp backend/tests <cid>:/app/tests, run with
  -e SCAN_DATA_SOURCE=dydx.
- SCAN_DATA_SOURCE resets to dydx on every restart AND deploy; POST /api/system/data-source
  back to hyperliquid before any HL run.
- CI gates backend·pytest + frontend·typecheck+build + e2e·playwright on BOTH main and
  production (all required); e2e is deterministic (per-test demo-state reset, serial).
- Prod DB (deep 2024+ history lives ONLY here, not local dev): ssh -i
  ~/.ssh/pairArbBotKeyPridevel.pem ubuntu@13.219.54.108, then docker exec [-i]
  statsarbbot-postgres-1 psql -U statsarb -d statsarb. macOS has no `timeout` binary — use
  ssh -o ConnectTimeout.
- Prod migrations: pg_dump BEFORE prisma migrate deploy. Never delete phase-1 strategy rows.
- Deploy (only after approval, and only for slices that change runtime code): on production
  branch, `cd ~/statsArbBot && git pull && docker compose up -d --build` (--build required
  for api/ui local images). Slice 0 is env-only (no --build). Leave the bot SAFE.

START: read docs/PHASE2_STRATEGY_PLAN.md, confirm the slice order with me, then implement
Slice 0 first (smallest, config-only) as the first gated PR. One slice per PR. Stop for my
approval at each PR before merging; never promote to production or deploy without my explicit OK.
```
