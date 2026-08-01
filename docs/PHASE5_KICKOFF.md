# Phase 5 — kickoff prompt (post-Phase-4: parameter recommendation → paper-trading rehearsal)

**Purpose.** A single, ready-to-paste starting prompt for the next-session agent. Phase-4
(per-trade cost transparency → phase-1-vs-2 explainer → the entry × size edge-hunt campaign) is
complete and **merged to `main`, but NOT deployed to production**. This bootstraps the next batch —
**two operator-requested tasks, in order** — with the verified numbers, code map and gate encoded
so nothing is re-derived.

**How to use.** Start a fresh session in this repo and paste the fenced block below as the first
message. Keep it in sync if scope changes.

> **Required order:** **Task 1 → Task 2.** Task 1 (which parameters to trade manually) must be
> answered and logged before Task 2 (the paper-trading rehearsal), because Task 2 rehearses
> whatever Task 1 selects.

> **Naming note:** "Phase 5" is the *work-batch* name (successor to `PHASE4_KICKOFF.md`). It is NOT
> the `Strategy.phase` provenance column, which is only ever `1` or `2`. New backtests still stamp
> `phase=2`.

> **The tension to hold.** The operator has decided to trade manually with his own money and wants
> a concrete parameterisation. The evidence says nothing clears the selection bar. Both things are
> true, and the prompt below deliberately requires the honest verdict **first** and a concrete,
> risk-managed recommendation **second** — a hedge that refuses to recommend anything is useless to
> him, and a recommendation that buries the verdict would be dishonest.

> **The trap the next session must not fall into.** `PER_MARKET_SLIPPAGE` and `MARKET_IMPACT` are
> **backtest-only** — the real-time simulation and fast-forward paths still use the flat
> `slippage_pct`. A paper-trading run would therefore be *systematically more optimistic* than the
> honest backtest that produced the NO-GO. Task 2 forces this to be resolved explicitly rather than
> discovered after two weeks of results.

---

```
ROLE: Senior QUANT + full-stack engineer specialised in crypto pair trading, on statsArbBot
(Hyperliquid pairs-trading / stat-arb bot). FIRST load context: CONTEXT.md, .claude/CLAUDE.md,
docs/strategy.md (esp. the "Phase-4 campaign — the entry × size interaction" section at the end),
docs/PHASE2_STRATEGY_PLAN.md §1 (gates B1-B5), docs/PHASE4_TASKC_PLAN.md, docs/QA.md (2026-07-29
and 2026-07-30 entries), docs/USER_GUIDE.md §9 + §11.

════════ STANDING CONTEXT — do NOT overturn, and do NOT let it quietly erode ════════
The bot is NO-GO for live trading. Phase-4 (2026-07-29/31) tested the entry × per-leg-size
interaction on prod and CONFIRMED A MECHANISM BUT NOT AN EDGE. Do not convert "entry 4.0 made
money in the backtest" into a recommendation to trade without stating what it fails.

Phase-4 results (18 runs, OOS spans s2/s3/s4, honest costs: PER_MARKET_SLIPPAGE + MARKET_IMPACT on,
scan 21 / trade 7, zscore_window 21, exit 0.5, stop 5.0, pvalue_max 0.01, max_half_life_h 72):

  Entry | OOS total @ $100/leg | OOS total @ $1,000/leg | trades
  3.5   |   -$1,246            |  -$48,872              | ~7,650
  3.75  |     +$911            |   -$8,374              | ~3,710
  4.0   |   +$2,346            |  +$15,787              | ~1,510

  Control validated: entry 3.5 @ $1k reproduces the published gate-B5 figure (-$48,872 vs
  -$50,670, within 3.5%; residual is stop 5.0 vs the reference's 4.0).

WHY THIS IS STILL NO-GO (both pre-stated before any result existed):
  (a) DSR = 0.0000 for ALL 18 runs. n_trials=72, trial-SR dispersion 0.76 => corrected bar
      sr_star = 1.839; entry 4.0's window Sharpe is 0.26. Verified against the engine's own
      backend/stats/deflated_sharpe.py, not a reimplementation.
  (b) EXTREME WINDOW CONCENTRATION. Of 13 walk-forward windows per span only 5-7 are positive.
      Across s2+s3+s4, 9 of 39 windows produce +$31,957 while the other 30 lose -$16,170.
      Strip the best 3 windows from any span and it goes negative.
  (c) B3 reads "net >= +$424 OR DSR > 0.95", so +$15,787 passes LITERALLY. The prior session
      judged the net arm inapplicable (its ±$212 noise floor was estimated at $100/leg on
      thousand-trade runs, not on 1,511 trades whose P&L sits in 9 windows) and documented that
      reasoning. THE OPERATOR MAY OVERRULE THIS — if he does, say so explicitly in the write-up
      and state exactly what risk he is accepting. Do not overrule it silently.

OTHER VERIFIED PHASE-4 FINDINGS (use these, don't re-derive):
  - FUNDING IS THE DOMINANT EXPLICIT COST: 1.8-5.5x larger than fees, eating 32-61% of gross,
    scaling near-linearly with notional (9.95x for 10x size => pure carry, not microstructure).
  - IMPACT COST PER TRADE IS ~CONSTANT ACROSS ENTRY THRESHOLDS ($4.35-$4.47 at $1k/leg). What
    changes is how many trades pay it. Entry 4.0 wins at size ONLY because gross/trade is 5.5x
    higher ($3.08 vs $0.56 at $100/leg) on 5x fewer trades. TRADE COUNT, not size, is the lever.
  - Phase-1 lever taxonomy (all swept, all at $100/leg under the OLD flat cost model): exit |Z| =
    noise; entry |Z| = dominant, single-peaked at 3.5 IN-SAMPLE; p-value = potent below 0.05 then
    saturates (keep 0.01); half-life cap = INERT (24h cap removes ~4% of trades); stop |Z| = pure
    risk/return trade-off, weak on net.

PROD (read-only recon already done 2026-07-31; re-verify, don't assume):
  ubuntu@13.219.54.108, key ~/.ssh/pairArbBotKeyPridevel.pem, containers statsarbbot-{api,ui,
  postgres}-1, DB statsarb/statsarb, backend key = DASHBOARD_PASSWORD (NOT 123456 — that's local).
  ENVIRONMENT=testnet. PER_MARKET_SLIPPAGE=on, MARKET_IMPACT=on, MIN_LIQUIDITY_USD=1000000.
  Inventory: hyperliquid phase=1 -> 75 rows (the preserved baseline), phase=2 -> 27 rows
  (18 Phase-4 campaign members + 9 that failed instantly on a bad window spec, kept deliberately).
  Campaigns: entry-size-100 (9 FAILED, kept as a record), entry-size-100-r2 (9 done),
  entry-size-1000 (9 done).
  GOTCHA: SCAN_DATA_SOURCE env default is dydx and resets on api restart; campaign/strategy
  creation resolves `exchange` AT CREATE TIME from the live data source, so re-POST
  /api/system/data-source -> hyperliquid BEFORE creating anything. Monitor long runs via psql in
  the postgres container, NOT HTTP (the CPU-bound scan saturates the event loop on 2 vCPU).
  DEPLOY STATE: prod runs branch `production` @ c095bc4 (PR #244). Phase-4's merged work
  (PRs #246-251, incl. Task A's per-trade cost columns and GET /api/backtest/strategies/{id}/costs)
  is on `main` but NOT DEPLOYED. Promotion main->production is a SEPARATE explicit operator OK.

════════ TASK 1 — Parameter recommendation for MANUAL trading (analysis + QA.md log) ════════
The operator trades signals BY HAND with MARKET ORDERS ONLY, so only taker economics apply
(maker modelling is off the table). He asks: analysing phase-1 AND phase-2/Phase-4 saved
strategies together, which entry Z-score, p-value, half-life, per-leg capital, stop-loss (and any
other parameter) should he use for a month of manual trading — and which is most optimised?

METHOD (do this properly, it is a quant question not a doc question):
  - Pull the saved strategies from PROD (read-only psql; 75 phase-1 + 27 phase-2). Separate them
    by the existing taxonomy axes: cost tier (ZERO/REDUCED/MODELLED), span (IN_SAMPLE/OVERLAPS/
    OUT_OF_SAMPLE), family, and phase. NEVER rank on in-sample net — that is search output.
  - Use the Task-A cost decomposition (Σgross / Σfees / Σfunding / Σnet, trade count, avg hold)
    computed from `backtest_trades` via psql. NOTE: the /costs endpoint is NOT on prod yet, so
    aggregate in SQL directly.
  - For EACH parameter the operator named, give: the evidence, the recommended value, the reason,
    and the confidence. Explicitly separate "what the data supports" from "what is extrapolation".
  - Per-leg capital deserves special care: within the TESTED range, $1,000/leg BEAT $100/leg for
    entry 4.0 (+$15,787 vs +$2,346) because gross scales as Q while entry-4.0's low trade count
    keeps total impact small. $5,000/leg is UNTESTED and the docs warn the sqrt-law breaks down
    there (many thin markets hit the 5%/leg impact cap). Do not extrapolate past what was measured.
  - Address the concentration problem head-on: a month of manual trading is roughly ONE
    walk-forward window. Given only 5-7 of 13 windows were positive, quantify the probability that
    a single month is a losing one, and say what that means for position sizing and for how the
    operator should judge the month.

DELIVERABLE: a clear, actionable recommendation — not a hedge. State the honest verdict FIRST
(nothing clears the bar), then, because the operator has decided to trade manually with his own
money, give the least-bad, risk-managed parameterisation and state plainly what he is accepting by
using it. Include a "what would make me tell you to stop" list (concrete drawdown / losing-streak /
funding-drag triggers). LOG THE QUESTION AND THE FULL ANSWER TO docs/QA.md via /qa-skill.

════════ TASK 2 — Plan a live paper-trading (real-time simulation) rehearsal ════════
The operator's proposal, which is SOUND and already supported: before risking real money, run the
selected strategy/parameters for ~2 weeks in REAL-TIME SIMULATION (Phase 6 — virtual trading against
live prices via scheduled ticks, DB-backed; `Simulation` nav, USER_GUIDE §9), so the bot records
live data and executes virtual trades, and we can watch how the selection actually behaves.

WRITE THE PLAN FIRST AND GET OPERATOR APPROVAL BEFORE CREATING ANY SESSION. It must resolve:
  1. **THE COST-MODEL TRAP (critical — do not skip).** PER_MARKET_SLIPPAGE and MARKET_IMPACT are
     BACKTEST-ONLY; the sim/fast-forward paths still use the FLAT slippage_pct. So a paper run will
     be SYSTEMATICALLY MORE OPTIMISTIC than the honest backtest that produced the NO-GO. Verify this
     in backend/simulation/ before writing the plan. Then choose and justify:
       (a) extend the per-market + impact cost model to the sim path (engine change, TDD, gated PR); or
       (b) run flat-cost and explicitly discount the result by the measured gap (~$0.31/trade spread
           at $100/leg, ~$4.4/trade impact at $1k/leg) — stating the correction up front, not after.
     Recommend one. (a) is the honest choice if the paper run is meant to inform a real-money decision.
  2. **What 2 weeks can and cannot prove.** At entry 4.0 the measured rate is ~6.4 trades/day
     (730 trades / 114 days), so ~90 trades in a fortnight. Against a ±$212 noise floor and P&L that
     lives in 3 of 13 windows, TWO WEEKS CANNOT VALIDATE EDGE. Frame it as an OPERATIONAL REHEARSAL —
     does the signal fire when expected, are the pairs fillable, does funding accrue as modelled, does
     the blotter reconcile — NOT as statistical evidence. Say this to the operator plainly.
  3. Concrete setup: which strategy/params, session config, tick cadence, duration, capital, and the
     EXACT pre-registered success criteria (written BEFORE it runs, so the bar cannot move).
  4. What gets compared afterwards: paper-trade cost decomposition vs the backtest's, per-trade —
     especially FUNDING, since it is the dominant cost and the thing a live run can genuinely verify.

════════ THE GATE (.claude/CLAUDE.md — non-negotiable) ════════
Per unit of work: short-lived feat-/fix-/docs-<slug> branch off main -> implement (TDD where code) ->
test e2e on the LOCAL DEV DOCKER STACK -> PR (CI: backend·pytest + frontend·typecheck+build +
e2e·playwright) -> EXPLICIT operator approval -> merge. Promotion main->production and ANY prod action
(deploy, creating a sim session on prod, launching a campaign) is a SEPARATE explicit operator OK.
ENVIRONMENT stays testnet; going live is deliberate, never a side effect. pg_dump before any
prisma migrate deploy. NEVER delete strategy rows. ASK BEFORE GUESSING on scope/criteria/data.
Docker tip: `docker cp backend/tests <cid>:/app/tests` NESTS into /app/tests/tests if the dir already
exists — remove the target first or you will silently run a STALE test tree.

START: load the docs above, confirm the Task 1 -> Task 2 order with me, then do Task 1's analysis
against real prod data and log it to docs/QA.md. Do NOT create any simulation session until the
Task 2 plan is written and approved. Nothing in this session ships a live strategy or relaxes the gate.
```
