# Phase 5 — Live paper-trading rehearsal plan (pre-approval)

**Status:** PROPOSAL for operator approval. **No simulation session created, no prod action taken.**
**Date:** 2026-08-01
**Gate:** `.claude/CLAUDE.md` + `docs/PHASE2_STRATEGY_PLAN.md` §1. Approval of this plan is required
*before* any engine change is merged; creating the session on prod is a **separate** explicit OK.

> **Standing verdict unchanged: NO-GO for live trading.** Nothing here ships a live strategy or
> relaxes a gate. `ENVIRONMENT` stays `testnet`. The rehearsal trades **virtual money only**.

---

## 0. TL;DR

Run the Task-1 recommended parameterisation for **~2 weeks in real-time simulation** (Phase 6,
`Simulation` nav, `docs/USER_GUIDE.md` §9) against live Hyperliquid prices.

Two things must happen first, and both are **engine changes**, not config:

1. **Port the honest cost model to the sim path.** Verified: it is not there today. Operator has
   chosen the exact honest model (option **(a)** in §1).
2. **Give the sim session pair-quality knobs.** Verified gap: `SimSession` has no `pvalue_max` /
   `max_half_life_h`, so the recommended **p-value 0.01 cannot be expressed** (§5).

And one expectation must be set before it runs, not after: **two weeks cannot validate edge.** At the
measured rate this produces **~26 trades**, and distinguishing this config's mean from zero at 95%
would take **~6,759 trades ≈ 10.1 years** (§2). This is an **operational rehearsal**. Judging it on
P&L is the one way to draw a wrong conclusion from it.

---

## 1. THE COST-MODEL TRAP — verified, and how it gets fixed

### 1.1 What I verified in the code

**The trap is real.** `PER_MARKET_SLIPPAGE` and `MARKET_IMPACT` are **backtest-only**:

- `backend/simulation/engine.py:213-227` — `_per_leg_slippage()` reads per-leg spreads from
  `session["slippage_by_market"]`. Its own docstring says the map is set *"only when
  `config.PER_MARKET_SLIPPAGE` is on (Phase-2 Slice 1)"* by **the backtest**, and that with no map it
  falls back to the flat `slippage_pct` — *"preserving Phase-1 backtests and the real-time sim/FF
  paths unchanged."*
- The only writer of that key is `backend/backtest/engine.py:287`, from
  `_build_slippage_map()` (`backend/backtest/engine.py:677-717`).
- `simulation.market_impact` is **never imported** by `backend/simulation/engine.py`. There is no
  impact term on the sim path at all.
- `SimSession` (`backend/prisma/schema.prisma:275-289`) carries a single flat
  `slippage_pct Float @default(0.05)`.

**Consequence:** a paper run today charges a flat half-spread and **zero market impact**, so it is
systematically **more optimistic** than the honest backtest that produced the NO-GO — by roughly
**$0.31/trade** (spread, at $100/leg) and **~$4.9/trade** (impact, at $1,000/leg; measured $4.35–5.99
across the Phase-4 spans).

**Why that is disqualifying here, not merely imprecise:** the Task-1 recommended config earns
**+$0.248 per trade**. The un-modelled spread error alone is **larger than the entire edge**. A
flat-cost paper run would not be "a bit optimistic" — it would reliably print a profit for a
configuration measured at approximately zero, and would be actively misleading.

### 1.2 Decision: option (a) — extend the honest cost model to the sim path

Operator has chosen the exact live honest cost model. Option (b) (run flat and discount afterwards) is
**rejected** for the reason above: the correction is bigger than the signal, so the discounted number
would carry more correction than measurement.

**Good news on feasibility — the data the model needs is live on prod.** Verified 2026-08-01:

| Input | Source | Prod state |
|---|---|---|
| Per-market dollar volume (→ half-spread curve, ADV) | `ohlcv_cache` via `get_dollar_volumes()` (`backend/ingest/cache_repository.py:106`) | **fresh**, hyperliquid 181 markets, newest bar 2026-08-01 03:00Z (~7h) |
| σ (realised daily vol → impact) | closes from `ohlcv_cache` | same |
| Funding rates | `funding_rate_cache` | **fresh**, 181 markets, newest 2026-08-01 02:00Z |

So the port needs **no new ingest** — only a shared code path.

### 1.3 Design

The cleanest shape, and the one CONTEXT.md's "pure, isolated statistical core" stance points at:
**extract `_build_slippage_map` into a shared module and call it from both engines.**

- **New:** `backend/simulation/cost_map.py::build_cost_map(...)` — the existing logic from
  `backend/backtest/engine.py:677-717`, moved verbatim, parameterised by
  `(exchange, markets, start, end, flat_slippage_pct, per_leg_usd, closes_by_market)`.
- **Backtest:** `_build_slippage_map` becomes a thin adapter. **Behaviour must not change** — the
  Phase-4 numbers are the control and have to reproduce exactly.
- **Sim:** `SimulationEngine.tick` builds the map for the current scan's markets and puts it on the
  session dict as `slippage_by_market`, so `_per_leg_slippage` (already written, already tested)
  picks it up with **no change to `run_tick`**.
- **Cadence:** rebuild the map **hourly** (not per tick). Dollar volumes and σ are trailing-window
  aggregates that move slowly, and the tick runs every 60s by default — rebuilding per tick would put
  a `GROUP BY` over `ohlcv_cache` on the event loop 60× an hour on a 2-vCPU box. Cache in-process with
  a timestamp; on miss, reuse the last good map.
- **Trailing window for ADV/σ:** 7 days, matching the backtest's per-window scale.
- **Flags:** honour the same process-global `config.PER_MARKET_SLIPPAGE` / `config.MARKET_IMPACT` the
  backtest honours, so there is one switch. On prod both are already **ON**.
- **Provenance (additive migration):** record on the session what it actually ran under —
  `per_market_slippage Boolean?`, `market_impact Boolean?` on `SimSession`, null = "followed the
  global". Without this, a session's costs are unreproducible after an env change. Nullable +
  defaulted, so existing rows are untouched.

**Fast-forward is deliberately left alone.** It replays historical candles and is not on the path to
this decision; widening scope to FF would add risk without adding evidence. It keeps its current
flat-cost behaviour and that stays documented.

### 1.4 TDD plan (tests written first)

| Test | Asserts |
|---|---|
| `test_cost_map_shared_matches_backtest` | The extracted `build_cost_map` returns **identical** output to the current `_build_slippage_map` on a fixed fixture — the refactor is behaviour-preserving. |
| `test_sim_charges_per_market_spread` | With `PER_MARKET_SLIPPAGE=on` and a thin/liquid market pair, the two legs are charged **different** slippage; with it off, both get the flat rate. |
| `test_sim_charges_market_impact` | With `MARKET_IMPACT=on`, a thin market (low ADV) at $1,000/leg is charged materially more than at $100/leg, and impact scales ~Q^1.5. Mirrors `backend/tests/test_backtest_engine.py:605-625`. |
| `test_sim_cost_map_cached_hourly` | The map builder is called once per hour, not once per tick. |
| `test_sim_falls_back_to_last_good_map` | A failed volume query reuses the previous map rather than silently reverting to flat cost (a silent revert is exactly the optimism this PR exists to remove). |
| `test_backtest_regression_phase4` | An existing Phase-4-shaped fixture run reproduces its previous net **to the cent**. |

Then: local dev Docker stack end-to-end — create a session, tick it, confirm `sim_trades` rows carry
per-market-differentiated costs.

---

## 2. What 2 weeks can and cannot prove

**It cannot prove edge. Not close.** Stated before the run, so this cannot be renegotiated afterwards.

Measured from the Task-1 capped replay of the recommended config (`docs/QA.md`, 2026-08-01):

| Quantity | Value |
|---|---|
| Trade rate under the K=5 cap | **1.84/day** → **~26 trades in 14 days** |
| Mean net per trade | **+$0.248** |
| Per-trade standard deviation | **$10.40** |
| Expected 14-day P&L | **+$6.37** |
| Standard deviation of that sum | **±$52.72** |
| 95% interval for the fortnight | **−$97 to +$110** |
| Trades needed to distinguish the mean from zero at 95% | **6,759 → ≈ 10.1 years at this rate** |

The expected result is **+$6 inside a ±$100 band**. Any outcome in that range — including a healthy-
looking profit — is noise. And the P&L is concentrated: 3 of 39 windows carried two-thirds of it, so a
fortnight most likely contains **none** of the windows that matter.

> **Note on the kickoff's estimate.** ~6.4 trades/day is the **s2 rate only**; s3 is 4.8/day and s4 is
> 2.1/day (blended 4.4/day uncapped). Under the recommended K=5 concurrency cap it falls to
> **1.84/day**. So the fortnight yields **~26 trades, not ~90**.

**What it genuinely can establish** — all operational, all binary, none statistical:

1. **Does the signal fire when and where expected?** Compare live entry timestamps/pairs against what
   the same parameters would have selected. A rate far from ~1.8/day means the live universe or scan
   policy differs from the backtest's.
2. **Are the selected pairs actually fillable?** The edge lives in the thinnest markets
   (`PHASE2_STRATEGY_PLAN.md` §4). This is the first look at whether those names quote continuously
   at the sizes the model assumes.
3. **Does funding accrue as modelled?** The most valuable output of the whole exercise — see §4.
4. **Does the blotter reconcile?** `gross − fees + funding = net` per trade, and equity ties to the
   sum of closed trades.
5. **Does the plumbing survive two weeks?** Scheduler ticks, API restarts (sessions re-register,
   `simulation/scheduler.py`), scan staleness, no stuck positions.

---

## 3. Concrete setup

### 3.1 Session configuration

| Field | Value | Why |
|---|---|---|
| `label` | `phase5-rehearsal-e40-k5` | Identifiable |
| `exchange` / data source | `hyperliquid` | **Re-POST `/api/system/data-source` first** — it resets to `dydx` on api restart |
| `mode` | `simulation` | Virtual money |
| `entry_threshold` | **4.0** | Task-1 recommendation (API ceiling) |
| `exit_threshold` | **0.5** | Noise lever; keep the documented value |
| `stop_threshold` | **5.0** | Avoids degenerate `entry == stop`; fires on only 1.6–4.7% of trades |
| `zscore_window` | **21** | Held constant across all Phase-4 runs |
| `usd_per_trade` | **$100** | The only tier measured at an executable workload |
| `max_active_pairs` | **5** | **The whole point.** Already enforced at `backend/simulation/engine.py:176`. Caps the run at what a human could execute |
| `starting_capital` | **$2,000** | 5 pairs × $100 committed + headroom; the margin guard at `engine.py:190` needs capital > committed |
| `interval_seconds` | **300** (5 min) | Hourly candles drive the Z, so 60s adds load without information; 5 min still catches intra-hour entries. 2 vCPU box |
| `funding_freq_h` | **1** | Hyperliquid funds hourly |
| `taker_fee_pct` | **0.045** | Real Hyperliquid base taker |
| `slippage_pct` | **0.0316** | Measured mean half-spread — **fallback only**; the per-market curve overrides it once §1 lands |
| pair quality | **p-value ≤ 0.01, half-life ≤ 72h** | See §5 — needs the new session fields |
| Duration | **14 days**, then stop | — |

### 3.2 Pre-registered success criteria — written BEFORE it runs

The run **passes** as an operational rehearsal if **all** hold. **P&L is deliberately not a criterion.**

| # | Criterion | Threshold |
|---|---|---|
| R1 | **Signal rate in the expected band** | 15–45 closed trades over 14 days (~26 expected, ±~1.9σ) |
| R2 | **Blotter reconciles** | 100% of `sim_trades` satisfy `gross − fees + funding = net` to ±$0.005 |
| R3 | **Cost model is live and differentiated** | Per-leg slippage **varies by market** across trades (proves §1 shipped and is active, not silently flat) |
| R4 | **Funding is in the modelled range** | Total funding is **20–45% of gross** (Phase-4 measured 29% for this config) |
| R5 | **No stuck state** | Zero positions open > 72h; zero positions with no live price for > 6 consecutive ticks |
| R6 | **Uptime** | ≥ 95% of scheduled ticks execute; session survives at least one api restart with positions intact |
| R7 | **Pairs are real** | ≥ 80% of entered pairs are still in the scan's pair list 24h later (not one-tick phantoms) |
| R8 | **Hold time matches** | Median hold **6–20h** (backtest: 11.6h avg, p95 22–25h) |

**Explicit non-criteria** — recorded so they cannot be promoted later:

- **Net P&L.** Any value in −$97…+$110 is consistent with the model. A profit does **not** upgrade the
  verdict, and a loss does **not** downgrade it further.
- **Win rate** on ~26 trades (±9pp standard error at 64%) — reported, not judged.

**If R1–R8 pass, the outcome is: "the machinery works honestly."** It does **not** become a go-live
argument. Going live still requires clearing B1–B5, which DSR alone forecloses (best DSR on prod:
**0.031** against a 0.95 bar).

---

## 4. What gets compared afterwards

Per-trade, sim vs the backtest arm it mirrors (`entry-size-100-r2 · entry_threshold=4.0 · s2/s3/s4`).
`SimTrade` (`schema.prisma:329-357`) carries `gross_pnl / fee_cost / funding_pnl / net_pnl /
hold_hours / notional_usd` — the **same columns** as `BacktestTrade`, so the comparison is direct and
needs no new persistence.

| Metric | Backtest (measured, OOS) | Why it matters |
|---|---|---|
| **Funding per trade** | **−$0.72** (−$1,086 / 1,513) | **The headline test.** Funding is the dominant cost and the one a live run can genuinely verify — it depends only on real rates and real hold time, not on a fill model |
| **Funding as % of gross** | **29%** | Criterion R4 |
| Fees per trade | −$0.19 | Deterministic; a mismatch means a fee-config error |
| Gross per trade | +$2.46 | Includes slippage+impact in the fill price — **not** mid-price |
| Net per trade | +$0.248 | Reported with its ±$10.40 per-trade sd, never as a point estimate |
| Avg hold | 11.6h | R8 |
| Exit mix | 90.4% TAKE_PROFIT / 5.1% window-end / 4.5% time-stop | A very different mix means the signal is behaving differently live |

**The funding comparison is the deliverable.** If live funding lands materially above the modelled
−$0.72/trade, that is a real, actionable finding: it would mean the honest backtest is *still* too
optimistic, and it directly strengthens the case that the next experiment should be
**funding-carry-aware pair selection** (`PHASE2_STRATEGY_PLAN.md` §7).

A short comparison report gets appended to `docs/QA.md` when the run ends, whatever it shows.

---

## 5. Second gap found: the sim cannot express the recommended pair quality

**Verified.** `SimSession` has **no** `pvalue_max` / `max_half_life_h` (`schema.prisma:275-289`), and
the sim trades **whatever the latest scan produced** — `build_realtime_snapshots`
(`backend/simulation/feed.py:78-93`) applies no quality filter of its own. Pair quality is set
process-globally at scan time by `config.PVALUE_MAX` / `config.MAX_HALF_LIFE_H`
(`backend/config.py:101-102`).

**Prod is currently at `PVALUE_MAX = 0.05`, not the recommended 0.01.** Inferred read-only from the
latest hyperliquid scan (2026-08-01 08:44Z, 40 pairs): p-values run to **0.0479**, and only **10 of
40** pairs meet p ≤ 0.01. So a session started today would trade at **5× looser pair quality than the
recommendation** — and the phase-1 sweep found loosening 0.01 → 0.05 flips +$1,865 to −$1,176.

Two ways to fix it:

- **(i) Change the global env** (`PVALUE_MAX=0.01`) and re-scan. Zero code, but it silently changes the
  live scan for every consumer, and is lost on any env reset — the same failure mode as
  `SCAN_DATA_SOURCE`.
- **(ii) Add `pvalue_max` / `max_half_life_h` to `SimSession`** and filter in the feed. Additive
  nullable columns (null = follow global), one migration, ~20 lines, and the session becomes
  self-describing and reproducible. **Recommended**, and it matches how `Strategy` already carries its
  own `pvalue_max` / `max_half_life_h`.

Incidentally the scan also confirms a Task-1 finding **live**: every scanned pair's half-life is
**5.65–27.73h**, all far below the 72h cap — the cap cannot bind in the live universe either.

---

## 6. Proposed work order (each its own gated PR)

| # | Work | Type | Gate |
|---|---|---|---|
| 1 | Extract `build_cost_map`; wire it into the sim tick; provenance columns on `SimSession` | Engine + additive migration | TDD → local dev stack e2e → CI → **operator approval** → merge to `main` |
| 2 | `pvalue_max` / `max_half_life_h` on `SimSession` + feed filter (§5) | Engine + additive migration | same |
| 3 | Promote `main` → `production`, `pg_dump` → `prisma migrate deploy`, `docker compose up -d --build` | Deploy | **Separate** explicit operator OK |
| 4 | Fresh scan on prod (data source → `hyperliquid` first), then create the session per §3.1 | Prod action | **Separate** explicit operator OK |
| 5 | Monitor 14 days (via `psql`, not HTTP), then stop and write the §4 comparison to `docs/QA.md` | Analysis | — |

**Safety invariants for the whole exercise:** `ENVIRONMENT` stays `testnet`; the session is
`mode=simulation` (virtual money, no exchange orders); no strategy row is ever deleted; `pg_dump`
precedes any `prisma migrate deploy`.

---

## 7. Risks and what would abort the rehearsal

| Risk | Mitigation / abort trigger |
|---|---|
| **The cost-map port silently changes backtest numbers** | `test_backtest_regression_phase4` must reproduce a Phase-4 run to the cent. If it doesn't, the PR does not merge |
| **Cost map silently falls back to flat** (the exact optimism being removed) | R3 checks per-market variation in live trades; the fallback reuses the last good map and logs, never reverts to flat |
| `ohlcv_cache` goes stale mid-run → ADV/σ drift | Monitor bar recency daily; abort if > 48h stale |
| Scan goes stale → sim trades dead pairs | R7; re-scan cadence checked at day 7 |
| 2-vCPU box saturates | 5-min tick, hourly map rebuild, monitor via `psql` not HTTP |
| **Result gets over-read** | §2 and §3.2's explicit non-criteria are pre-registered; the write-up leads with them |
| Scope creep into "just go live" | Nothing in this plan changes `ENVIRONMENT` or the gate. Going live needs B1–B5, which DSR forecloses |

---

## 8. Honest summary

This rehearsal is worth doing **for the plumbing, not for the P&L**. It will not tell us whether the
strategy makes money — that needs ~10 years at this trade rate. It will tell us whether the honest cost
model, the funding accrual, the pair selection and the blotter all behave live the way they behave in
the backtest, and it will produce the **first real-world measurement of funding drag**, which is both
the dominant cost and the most promising direction for the next genuine attempt at an edge.

If the operator would rather skip it, that is a defensible call — §2's arithmetic already says a
fortnight is uninformative about edge. The counter-argument is that items 1–5 of §2 are genuinely
unknown today, they are cheap to establish, and every one of them would have to be established anyway
before any real money moved.
