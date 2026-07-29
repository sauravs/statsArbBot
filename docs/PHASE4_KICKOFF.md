# Phase 4 — kickoff prompt (post-Phase-3: cost transparency → phase-doc → edge-hunt campaign)

**Purpose.** A single, end-to-end, ready-to-paste starting prompt for the next-session agent.
Phase-3 (WS1/2/3 — liquidity filters + the campaign runner) is complete and **deployed to
production**. This bootstraps the next batch — **three operator-requested tasks, in a required
order** — with the verified code map + gate encoded so nothing is re-discovered.

**How to use.** Start a fresh session in this repo and paste the fenced block below as the first
message. Keep it in sync if scope changes.

> **Required order (do NOT reorder):** **A → B → C**, i.e. the operator's original
> requirement **#3 → #2 → #1**:
> - **Task A** = operator requirement **#3** — per-trade cost transparency (funding/fees/slippage)
>   in the backtest blotter UI. Do this FIRST so Task C's results are interpretable.
> - **Task B** = operator requirement **#2** — log the phase-1-vs-phase-2 explainer in QA.md via
>   `/qa-skill`. Do this SECOND.
> - **Task C** = operator requirement **#1** — plan + execute a strategy campaign to hunt for
>   edge/gap. Do this LAST, after A and B are merged.

> **Naming note:** "Phase 4" here is the *work-batch* name (successor to PHASE3_KICKOFF.md). It is
> NOT the `Strategy.phase` provenance column (which is only ever `1` or `2`). New backtests still
> stamp `phase=2`.

---

```
ROLE: Senior QUANT + full-stack engineer specialised in crypto pair trading, on statsArbBot
(Hyperliquid pairs-trading / stat-arb bot). FIRST load context fully — read CONTEXT.md,
.claude/CLAUDE.md, and the docs/ folder (esp. docs/PHASE2_STRATEGY_PLAN.md, docs/strategy.md
"Phase-2 campaign" section, docs/PHASE3_KICKOFF.md, docs/PHASE4_KICKOFF.md) before doing anything.

STANDING CONTEXT (do not overturn): the bot is NO-GO for live trading — Phase-2 settled that on
today's signal (best honest OOS net is a coin flip at $100/leg and ≈ −$50,670 at $1k/leg once
market impact is charged; nothing clears DSR>0.95). Phase-3 (liquidity filters + campaign runner)
is COMPLETE and DEPLOYED to prod (PRs #238-243, promoted #244; migrations through 0017). Prod is
SAFE: ENVIRONMENT=testnet, SCAN_DATA_SOURCE=hyperliquid. Prod inventory (2026-07-29): hyperliquid
data_source = 75 strategies, ALL phase=1 (66 COMPLETED); ZERO phase=2 yet. Nothing below ships a
live strategy or relaxes the gate.

EXECUTION SEQUENCE — do the three tasks STRICTLY IN THIS ORDER (operator's required order; do NOT
reorder or parallelise): TASK A (cost transparency) → TASK B (phase explainer) → TASK C (edge-hunt
campaign). A must land before B; A and B must land before C. One gated PR per increment; STOP for
explicit operator approval before every merge, and before any prod action.

════════ TASK A (FIRST) — Per-trade cost transparency in the Backtest blotter UI ════════
GOAL: show each executed trade's cost breakdown — FUNDING, fees, gross (and slippage per the
decision below) — so a trader sees why Net P&L is what it is. Today the blotter shows only Net P&L;
the operator specifically wants FUNDING visible, because the longer a position is held the more
funding it pays/earns — currently invisible unpredictability.
VERIFIED STATE (most data ALREADY exists — confirm against the repo):
- Persisted per trade in `BacktestTrade` (backend/prisma/schema.prisma): gross_pnl, fee_cost,
  funding_pnl, net_pnl, notional_usd, hold_hours; net_pnl = gross_pnl − fee_cost + funding_pnl.
  The blotter API ALREADY returns them (backend/db/backtest_repository.py::_trade_to_dict).
- UI shows only net_pnl: ui/components/StrategyDetail.tsx (`bt-blotter` table). Adding
  Gross/Fees/Funding columns is UI-ONLY; verify the trade type in ui/lib/api.ts carries the fields.
- funding_pnl can be + or − and accrues with hold time — surface hold_hours beside funding.
  Consider a per-window + per-strategy cost decomposition too (aggregates exist).
- SLIPPAGE = the one real decision (get operator sign-off): slippage is NOT a separate field — it
  is applied at the FILL PRICE (backend/simulation/costs.py::apply_slippage), baked INTO gross_pnl.
  (a) RECOMMENDED first: UI-only — break out Fees+Funding+Gross, label slippage "included in gross"
  via tooltip (no migration). (b) Only if operator asks: persist a per-trade slippage_cost (engine
  change + ADDITIVE migration) as a follow-up PR.
- ALSO fix the Phase-filter default if wrong: on 2026-07-29 the strategy list showed "0/75 — No
  strategy matches these filters" because the PHASE dropdown was on "Phase 2" (all 75 rows are
  phase=1). Spec (Phase-2 Slice 6 / strategy.md) says default must be "All", phase-1 never hidden —
  verify ui/lib/strategyTaxonomy.ts / ui/components/StrategyList.tsx and fix.
DELIVERY: TDD (net = gross − fees + funding reconciles; columns render) + local-docker e2e; docs
(USER_GUIDE §11; QA.md via /qa-skill).

════════ TASK B (SECOND) — Log "phase-1 vs phase-2 strategies" in docs/QA.md via /qa-skill ════════
Invoke /qa-skill (it answers the question AND writes the Q&A to docs/QA.md). VERIFY every claim
against the docs first; correct any stale number/path. This is a DOC task — read, don't re-derive.
QUESTION TO LOG: "What's the difference between phase-1 and phase-2 strategies? (why do the phase-1
ones look profitable but phase-2 says NO-GO?)"
ANSWER MUST CONTAIN BOTH (a) plain-English analogies and (b) technical precision:
  Bottom line first: phase-1 and phase-2 are NOT different trading ideas — they are the SAME
  pairs-trade measured two ways. Phase-1 measured it OPTIMISTICALLY; phase-2 measured it HONESTLY;
  the honest number is lower. `phase` is a PROVENANCE stamp; phase-1 rows are the preserved
  baseline, NEVER deleted or hidden.
  Analogies: (1) Menu price vs. final bill — phase-1 is the menu ("this run made $744"); phase-2 is
  the bill after tax+tip+"large-party surcharge" (fees, real per-market spread, market impact).
  (2) Empty test track vs. rush-hour traffic — phase-1 clocked top speed on an empty track
  (mid-price, tiny $100 trade); phase-2 drives the SAME car in real traffic (real spreads, size
  that moves the market). (3) Big fish in a small pond — buying $100 barely nudges price; buying
  $1k-$5k in a THIN coin pushes price against you (impact ∝ Q^1.5), and the gross edge lives in
  exactly those thin markets, so honest cost eats it. (4) Parking meter (funding) — longer holds
  pay more funding. (5) Lucky lottery ticket (DSR) — phase-1 tried ~69 settings and kept the
  best-looking one; buy 69 tickets and one looks like a winner by luck; the Deflated Sharpe Ratio
  asks "skill or luckiest of 69?" — phase-2's answer: luck, nothing clears DSR>0.95.
  Technical: phase=1 = the ~69/75 baseline under the OLD cost model (flat slippage% + flat fee, NO
  per-market spread, NO market impact, $100/leg top-of-book, ranked on net with NO search
  correction; much "green" was in-sample or zero-cost counterfactuals). phase=2 = sub-phase-B-
  onward runs that, with the honest flags on, carry PER_MARKET_SLIPPAGE (real per-market half-
  spread) + MARKET_IMPACT (σ·√(Q/ADV), size-aware) and are judged by DSR (gate B3); `phase`
  (Slice 6) is an orthogonal provenance axis (a name-prefix convention was rejected). Verdict:
  best honest OOS ≈ +$157 @ $100/leg (inside the ±$212 noise floor) → ≈ −$50,670 @ $1k/leg with
  impact; nothing clears DSR>0.95 → NO-GO. Phase-2 didn't make strategies worse — it revealed
  phase-1's numbers were optimistic. CONFIRM exact figures against docs/strategy.md before writing.

════════ TASK C (LAST) — Plan + execute a strategy campaign to hunt for edge/gap ════════
Phase-1 was run AD-HOC (no committed script). The RIGHT mechanism now is the WS3 CAMPAIGN RUNNER:
POST /api/backtest/campaigns (grid spec → many strategies, bounded concurrency, DB-backed resume,
honest-cost defaults) or the Campaigns UI panel on the Backtest page. Use it — do NOT reinvent
phase-1's manual approach.
PLAN FIRST (write it up; get operator approval on the grid BEFORE creating rows):
- Analyze what phase-1 covered (entry-Z, z-window, spans s2/s3/s4, cost tiers) and what phase-2's
  honest machinery showed (edge in thin markets; cost erases it; NO-GO). A genuine "yes" likely
  needs a NEW angle — funding-carry-aware pair selection, a different universe, hold-time caps that
  cut funding drag (tie to Task A's funding view), or a new signal — NOT another parameter tweak
  (PHASE2_STRATEGY_PLAN §7). Propose a grid that tests something UNTRIED.
- Judge EVERY candidate against the pre-stated bar (PHASE2_STRATEGY_PLAN §1, B1-B5): OOS-only; real
  per-market taker cost; beat ±$212 noise floor by ≥2σ (net ≥ +$424) OR pass DSR>0.95; non-negative
  in ≥2 of s2/s3/s4; survive market impact at real per-leg size. NEVER rank on in-sample net.
EXECUTE (only after grid approval):
- Honest defaults MANDATORY: PER_MARKET_SLIPPAGE + MARKET_IMPACT ON. New runs auto-stamp phase=2.
- Run on PROD (deep 2024+ HL history is prod-only): ubuntu@13.219.54.108, key
  ~/.ssh/pairArbBotKeyPridevel.pem, containers statsarbbot-{api,ui,postgres}-1, DB statsarb/
  statsarb; backend key = DASHBOARD_PASSWORD (docker exec statsarbbot-api-1 printenv
  DASHBOARD_PASSWORD). 2-vCPU → 2-3 concurrent, ~2-3h/sweep. MONITOR VIA psql in the postgres
  container, NOT HTTP (the CPU-bound scan saturates the event loop). Re-POST /api/system/data-source
  back to hyperliquid if the api restarts.
- Report each candidate's OOS net per span + DSR vs the B1-B5 bar; state plainly whether ANY clears
  it. NO-GO stands — this is an honest search, not a mandate to go live; ENVIRONMENT stays testnet.

════════ THE GATE (.claude/CLAUDE.md — non-negotiable) ════════
Per unit of work: short-lived feat-<slug>/fix-<slug>/docs-<slug> branch off main → implement (TDD
where code) → test e2e on the LOCAL DEV DOCKER STACK (docker compose up -d --build; backend tests
via docker cp into statsarbbot-api-1 then pytest; after a schema change run prisma migrate deploy +
generate in the container) → PR (CI: backend·pytest + frontend·typecheck+build + e2e·playwright
must pass) → EXPLICIT operator approval → merge to main. Promotion main→production and any prod
action (deploy OR launching a campaign on prod) is a SEPARATE explicit operator OK. Deploy leaves
the bot SAFE (ENVIRONMENT stays testnet); pg_dump BEFORE any prisma migrate deploy; NEVER delete
strategy rows; SCAN_DATA_SOURCE resets to dydx on api restart → re-POST it to hyperliquid. ASK
BEFORE GUESSING on scope/criteria/data.

START: load the context docs above, confirm the A→B→C sequence with me, then implement TASK A
slice-by-slice (smallest first) as gated PRs. One PR per increment. Do NOT start B until A is
merged, or C until A and B are merged. Stop for approval before every merge/deploy; never promote
to production or go live without explicit OK.
```
