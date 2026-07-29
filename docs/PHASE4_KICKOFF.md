# Phase 4 — kickoff prompt (post-Phase-3: cost transparency → phase-doc → edge-hunt campaign)

**Purpose.** A ready-to-paste starting prompt for the next-session agent. Phase-3 (WS1/2/3 —
liquidity filters + the campaign runner) is complete and **deployed to production**. This
bootstraps the next batch — **three operator-requested tasks, in a required order** — with the
verified code map + gate encoded so nothing is re-discovered.

**How to use.** Start a fresh session in this repo and paste the fenced block below as the first
message. Keep it in sync if scope changes.

> **Naming note:** "Phase 4" here is the *work-batch* name (successor to PHASE3_KICKOFF.md). It is
> NOT the `Strategy.phase` provenance column (which is only ever `1` or `2`). New backtests still
> stamp `phase=2`.

> Standing context (do not overturn): the bot is **NO-GO for live trading** — Phase-2 settled that
> on today's signal (best honest OOS net is a coin flip at $100/leg and −$50,670 at $1k/leg once
> market impact is charged; nothing clears DSR>0.95). None of the tasks below ships a live strategy
> or relaxes the gate in `.claude/CLAUDE.md`. Task C is an **honest search** for whether *any* config
> clears the bar — not a mandate to go live.

> **Operator's ordering (do NOT reorder):** **A → B → C.** Do the per-trade cost transparency (A)
> first so Task C's results are interpretable; then log the phase-1-vs-phase-2 explainer (B); then
> plan + execute the strategy campaign (C). Each is a gated PR (or PRs).

---

```
ROLE: Senior quant + full-stack engineer on statsArbBot (Hyperliquid pairs-trading /
stat-arb bot). Prod on EC2: ubuntu@13.219.54.108, key ~/.ssh/pairArbBotKeyPridevel.pem,
containers statsarbbot-{api,ui,postgres}-1, DB statsarb/statsarb. Backend API key is
DASHBOARD_PASSWORD (read from the container: `docker exec statsarbbot-api-1 printenv
DASHBOARD_PASSWORD`); header X-API-Key. The box is 2-vCPU → backtest sweeps are slow
(~2-3h for 2-3 concurrent). Monitor sweeps via the DB (psql in the postgres container),
NOT the HTTP API (the CPU-bound scan saturates the event loop). See memory prod-ops-facts.

CONTEXT: Phase-3 (WS1 liquidity filters, WS2 manual-list minimiser, WS3 campaign runner)
is COMPLETE + DEPLOYED to prod (PRs #238-243, promoted via #244, deployed 2026-07-27/28;
migrations through 0017 applied). Prod is SAFE: ENVIRONMENT=testnet, SCAN_DATA_SOURCE=
hyperliquid, PER_MARKET_SLIPPAGE + MARKET_IMPACT available (default OFF), MIN_LIQUIDITY_USD
=$1M. Read docs/PHASE2_STRATEGY_PLAN.md + the docs/strategy.md "Phase-2 campaign" section +
docs/PHASE3_KICKOFF.md for the full picture before starting. Prod strategy inventory
(2026-07-29): hyperliquid data_source = 75 strategies, ALL phase=1 (66 COMPLETED, 6 PENDING,
2 FAILED, 1 STOPPED); dydx=6; fake=1. There are ZERO phase=2 strategies yet — nothing new
has been run on the deployed build.

  GOTCHA seen 2026-07-29: the Backtest strategy list showed "0/75 — No strategy matches
  these filters" because the PHASE dropdown was on "Phase 2" (all 75 saved rows are phase 1).
  Set PHASE=All to see them. Verify the Phase-filter DEFAULT in the UI — the spec (Phase-2
  Slice 6 / strategy.md) says default should be "All", never hiding phase-1; if it defaults
  to "Phase 2", that's a small bug to fix inside Task A.

THE GATE — follow .claude/CLAUDE.md EXACTLY (non-negotiable):
- Per unit of work: short-lived feat-<slug>/fix-<slug> branch off main → implement with TDD →
  test end-to-end on the LOCAL DEV DOCKER STACK → PR (CI must pass) → EXPLICIT OPERATOR
  APPROVAL → merge to main → (only if operator says) promote main→production + deploy.
- production = HL/dYdX MAINNET, real money. Deploy leaves the bot SAFE (ENVIRONMENT stays
  testnet; going live is deliberate, never a side effect). pg_dump BEFORE any prisma migrate
  deploy; NEVER delete strategy rows. SCAN_DATA_SOURCE resets to dydx on api restart →
  re-POST /api/system/data-source back to hyperliquid after any deploy.
- ASK BEFORE GUESSING on scope/criteria/data. (Last session the operator granted merge-to-main
  autonomy on green CI for the Phase-3 batch; do NOT assume it carries here — re-confirm the
  autonomy level for this batch before merging. Prod deploy is ALWAYS a separate explicit OK.)

═══ TASK A (FIRST) — Per-trade cost transparency in the Backtest UI ═══
Operator ask: show funding cost, slippage, fees (and any other tx cost) for EACH executed
trade in the backtest blotter — because a longer-held position pays more funding, and that
unpredictability is currently invisible (only Net P&L is shown per trade).

VERIFIED STATE (the good news — most of the data already exists):
- Persisted per trade: `BacktestTrade` already stores gross_pnl, fee_cost, funding_pnl,
  net_pnl, notional_usd, hold_hours (backend/prisma/schema.prisma; net_pnl = gross − fees +
  funding). The blotter API ALREADY RETURNS all of them
  (db/backtest_repository.py::_trade_to_dict).
- UI shows only net_pnl: ui/components/StrategyDetail.tsx (the `bt-blotter` table — columns
  Pair/Dir/Entry/Exit/Hold/Net P&L/Outcome/Reason/Chart). So adding Gross / Fees / Funding
  columns per trade is a UI-ONLY change (types in ui/lib/api.ts likely already carry the
  fields — verify BacktestTrade/blotter interface).
- Funding is per-trade `funding_pnl` and CAN be + or − (a credit or a cost); it accrues with
  hold time (operator's intuition is correct). Surface hold_hours next to funding so the
  correlation is visible. Consider a per-window + per-strategy cost decomposition too (the
  aggregates exist: gross vs fees vs funding).
- SLIPPAGE CAVEAT (the one real decision): slippage is NOT a separate column — it is applied
  at the FILL PRICE (simulation/costs.py::apply_slippage) and thus baked INTO gross_pnl.
  Showing slippage as its own per-trade line requires an engine + schema change (compute +
  persist a per-trade slippage_cost + a migration). DECIDE WITH THE OPERATOR:
    (a) UI-only now: break out Fees + Funding + Gross per trade (cheap, high value), and
        label slippage as "included in gross" with a tooltip; OR
    (b) also add a persisted per-trade slippage_cost line (engine change + additive migration).
  Recommend (a) first as its own PR, (b) as a follow-up only if the operator wants the split.
- Also fix the Phase-filter default if it isn't "All" (see the CONTEXT gotcha).
- TDD (blotter renders the new columns; net = gross − fees + funding reconciles) + local-docker
  e2e; docs (USER_GUIDE §11, QA.md via qa-skill).

═══ TASK B (SECOND, before Task C) — Log "phase-1 vs phase-2 strategies" in QA.md ═══
Operator ask: before running new strategies, clearly explain how phase-1 strategies differ
from phase-2, and LOG the question + answer in docs/QA.md USING THE qa-skill (invoke
/qa-skill; it writes the entry). This is a DOC task — read, don't re-derive:
- Source material: docs/PHASE2_STRATEGY_PLAN.md, docs/strategy.md (Phase-2 campaign section),
  the existing QA.md phase entries, ui/lib/strategyTaxonomy.ts, schema.prisma (`phase` column).
- The answer must cover: phase=1 = the ~69/75 baseline configs (the honest baseline, NEVER
  deleted), created under the OLD cost model (flat slippage_pct, single flat fee, NO per-market
  spread, NO market impact, pre-DSR); phase=2 = runs from sub-phase B onward that carry the
  HONEST cost model when the flags are on (PER_MARKET_SLIPPAGE, MARKET_IMPACT) and are judged
  against DSR (gate B3). `phase` (Slice 6) is an orthogonal PROVENANCE tag, coexisting with the
  cost/span/family axes; a name-prefix convention was explicitly rejected. Note the standing
  verdict (NO-GO) and that phase-2's honest numbers are LOWER/HONEST, not "better".

═══ TASK C (LAST) — Plan + execute a strategy campaign to hunt for edge/gap ═══
Operator ask: like phase-1, plan and execute multiple strategies "one by one from scripts".
IMPORTANT: phase-1 was run AD-HOC (there is NO committed campaign script). The RIGHT mechanism
now is the WS3 CAMPAIGN RUNNER shipped in Phase-3 (POST /api/backtest/campaigns, or the
Campaigns UI panel on the Backtest page) — a grid spec expands into many strategies run with
bounded concurrency, DB-backed resume, honest-cost defaults ON. Use it (or a thin script that
POSTs a campaign spec); do NOT reinvent phase-1's manual approach.
- As a quant, FIRST analyze (and write up): what phase-1 already tried (the 69-config space —
  entry-Z, z-window, spans s2/s3/s4, cost tiers), what phase-2's honest machinery showed
  (edge lives in thin markets; cost erases it; NO-GO), and therefore what a NEW grid could
  test that hasn't been — e.g. funding-carry-aware pair selection, different universes,
  hold-time caps (funding sensitivity per Task A), or genuinely new signals. The probes suggest
  a real "yes" likely needs a NEW signal, not another parameter tweak (PHASE2_STRATEGY_PLAN §7).
- Honest defaults: campaigns MUST run with PER_MARKET_SLIPPAGE + MARKET_IMPACT ON (phase-2
  cost). New runs auto-stamp phase=2.
- Run on PROD (deep 2024+ HL history is prod-only — memory hyperliquid-deep-history-location).
  2-vCPU → 2-3 concurrent, ~2-3h/sweep; monitor via psql, not HTTP.
- Selection bar is pre-stated in PHASE2_STRATEGY_PLAN §1 (B1-B5: OOS-only, real per-market
  cost, beat the ±$212 noise floor by ≥2σ OR pass DSR>0.95, cross-span robust, survive
  market-impact at real size). Judge every candidate against it — do NOT rank on in-sample net.
- ASK the operator to approve the grid spec (axes, spans, size, cost flags) BEFORE creating rows.

═══ VERIFIED CODE MAP (re-confirm line numbers) ═══
- Per-trade cost data: schema.prisma `model BacktestTrade` (gross_pnl/fee_cost/funding_pnl/
  net_pnl/notional_usd/hold_hours); returned by db/backtest_repository.py::_trade_to_dict;
  blotter UI ui/components/StrategyDetail.tsx (`bt-blotter*` testids), types in ui/lib/api.ts.
- Cost model: simulation/costs.py (apply_slippage at fill price → slippage is IN gross;
  close_position returns {gross_pnl, fee_cost, funding_pnl, net_pnl}); per-market spread
  simulation/spread_cost.py; market impact simulation/market_impact.py; engine composes them
  in backtest/engine.py::_build_slippage_map. Flags config.PER_MARKET_SLIPPAGE / MARKET_IMPACT.
- Funding: FundingTable (backend/simulation), applied in backtest/engine.py (~line 401,
  funding_rates per tick); funding_pnl accrues with hold time.
- Campaign runner (WS3): backend/backtest/campaign.py (grid expansion), campaign_runner.py
  (bounded-concurrency queue, auto-start, pause/stop/resume, resume_running_campaigns on
  startup), db/campaign_repository.py; endpoints in routers/backtest.py
  (POST/GET/DELETE /api/backtest/campaigns, /{id}/pause|stop|resume); UI
  ui/components/CampaignPanel.tsx on the Backtest page. Spec format + behaviour: docs/QA.md
  (2026-07-27 WS3 entries).
- Phase tagging / taxonomy: schema.prisma `phase Int @default(1)`; ui/lib/strategyTaxonomy.ts;
  Phase filter + badges in ui/components/StrategyList.tsx / SafetyBadges.tsx; significance/DSR
  backend/stats/ + GET /api/backtest/significance.

═══ DEVOPS / GOTCHAS ═══
- Local dev e2e: docker compose up -d --build. Host `npm run build` is broken (corrupted swc)
  → build/e2e in CI or the container; `npx tsc --noEmit` + eslint + vitest work on host.
  Backend tests: `docker exec statsarbbot-api-1 rm -rf /app/tests && docker cp backend/tests
  <cid>:/app/tests` then `docker exec -e SCAN_DATA_SOURCE=dydx <cid> python -m pytest -q`.
  After a schema change: prisma migrate deploy + prisma generate in the container before pytest.
- CI gates backend·pytest + frontend·typecheck+build + e2e·playwright on main AND production.
- Promotion is a PR `main → production` MERGE (production carries merge commits main lacks, so
  `git merge-base --is-ancestor`/`--ff-only` FAILS by design — that's NOT divergence; verify
  parity with `git diff --stat origin/production origin/main` == empty). Deploy runbook:
  docs/DEPLOYMENT.md §0. pg_dump before migrate; api-start auto-runs migrate deploy.
- Prod: 2-vCPU → sweeps slow; monitor via psql not HTTP. Old ~/backups dumps + .env.bak.*
  files may need pruning (disk was 79% used post-deploy). Memory: prod-ops-facts,
  phase3-shipped-not-deployed, ec2-ssh-dynamic-ip.

START: read docs/PHASE2_STRATEGY_PLAN.md + the docs/strategy.md Phase-2 campaign section +
docs/PHASE3_KICKOFF.md, confirm the A→B→C order + the merge-autonomy level with me, then
implement Task A slice-by-slice as gated PRs (smallest first). One PR per increment. Stop for
approval before every merge/deploy; never promote to production or go live without explicit OK.
```
